"""
POST /tasks/{id}/dispatch-state — the control plane's machine-readable dispatch block.

The block is overwritable state, never history: older control planes read every
non-amend `approved`/operator history row as a fresh approval, so a history entry here
would silently restart a worker across the fleet. That invariant is tested explicitly.
"""

import importlib

import pytest
import yaml
from starlette.testclient import TestClient

from src.tools.queue import get_task_handler, set_dispatch_state_handler, submit_task_handler

SECRET = "test-secret-value"
AUTH = {"X-Task-Queue-Secret": SECRET}
SESSION = "2467bc07-dee3-4702-8b96-6c04155f954c"


@pytest.fixture
def env(tmp_path, monkeypatch):
    import src.server as srv

    importlib.reload(srv)
    monkeypatch.setattr(srv, "QUEUE_DIR", str(tmp_path))
    monkeypatch.setenv("TASK_QUEUE_API_SECRET", SECRET)
    return srv, tmp_path


@pytest.fixture
def client(env):
    srv, _ = env
    with TestClient(srv.mcp.http_app()) as c:
        yield c


def _seed(tmp_path, status="approved"):
    r = submit_task_handler(
        source_agent="projektplaner",
        target_agent="administrator",
        task_type="build",
        summary="Projekt anlegen",
        description="d",
        queue_dir=str(tmp_path),
    )
    path = tmp_path / r["filename"]
    data = yaml.safe_load(path.read_text())
    data["status"] = status
    path.write_text(yaml.dump(data, default_flow_style=False, sort_keys=False))
    return r["task_id"], path


def test_dispatch_state_ok_and_visible_in_get(env, client):
    _, tmp_path = env
    tid, _ = _seed(tmp_path)
    resp = client.post(
        f"/tasks/{tid}/dispatch-state",
        headers=AUTH,
        json={
            "generation": "1:2026-09-21",
            "state": "waiting",
            "role": "administrator",
            "user": "bbpadmin",
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ok"] is True
    assert body["dispatch"]["state"] == "waiting"
    assert body["dispatch"]["attempts"] == 0

    got = client.get(f"/tasks/{tid}", headers=AUTH).json()
    assert got["dispatch"]["state"] == "waiting"
    assert got["dispatch"]["updated_at"]


def test_dispatch_state_requires_secret(env, client):
    _, tmp_path = env
    tid, _ = _seed(tmp_path)
    assert client.post(f"/tasks/{tid}/dispatch-state", json={"state": "running"}).status_code == 401
    assert "dispatch" not in get_task_handler(task_id=tid, queue_dir=str(tmp_path))


def test_running_increments_attempts_and_new_generation_resets(env, client):
    _, tmp_path = env
    tid, _ = _seed(tmp_path)
    for _ in range(2):
        r = client.post(
            f"/tasks/{tid}/dispatch-state",
            headers=AUTH,
            json={"generation": "1:a", "state": "running", "session_id": SESSION},
        )
        assert r.status_code == 200
    d = get_task_handler(task_id=tid, queue_dir=str(tmp_path))["dispatch"]
    assert d["attempts"] == 2
    assert d["last_attempt_at"]
    assert d["session_id"] == SESSION

    r = client.post(
        f"/tasks/{tid}/dispatch-state",
        headers=AUTH,
        json={"generation": "2:b", "state": "running", "session_id": SESSION},
    )
    assert r.json()["dispatch"]["attempts"] == 1


def test_failed_block_keeps_reason_and_exit(env, client):
    _, tmp_path = env
    tid, _ = _seed(tmp_path)
    r = client.post(
        f"/tasks/{tid}/dispatch-state",
        headers=AUTH,
        json={
            "generation": "1:a",
            "state": "failed",
            "reason_code": "auth_expired",
            "reason": "Claude-Anmeldung abgelaufen",
            "worker_exit": 1,
            "auth_problem": True,
            "session_id": SESSION,
        },
    )
    assert r.status_code == 200
    d = get_task_handler(task_id=tid, queue_dir=str(tmp_path))["dispatch"]
    assert d["reason_code"] == "auth_expired"
    assert d["worker_exit"] == 1
    assert d["auth_problem"] is True


def test_dispatch_state_writes_no_history_entry(env, client):
    """A history row would be a new approval generation for older control planes."""
    _, tmp_path = env
    tid, _ = _seed(tmp_path)
    before = len(get_task_handler(task_id=tid, queue_dir=str(tmp_path))["history"])
    client.post(f"/tasks/{tid}/dispatch-state", headers=AUTH, json={"state": "running"})
    client.post(
        f"/tasks/{tid}/dispatch-state",
        headers=AUTH,
        json={"state": "failed", "reason_code": "worker_exit"},
    )
    task = get_task_handler(task_id=tid, queue_dir=str(tmp_path))
    assert len(task["history"]) == before
    assert "amendments" not in task["payload"]


def test_rejects_invalid_state_reason_session_and_exit(env, client):
    _, tmp_path = env
    tid, _ = _seed(tmp_path)
    for bad in (
        {"state": "exploded"},
        {"reason_code": "Nicht-Gut"},
        {"session_id": "nope"},
        {"worker_exit": "1"},
        {"worker_exit": True},
    ):
        r = client.post(f"/tasks/{tid}/dispatch-state", headers=AUTH, json=bad)
        assert r.status_code == 400, bad
    assert "dispatch" not in get_task_handler(task_id=tid, queue_dir=str(tmp_path))


def test_refuses_terminal_archived_and_unknown(env, client):
    _, tmp_path = env
    tid, _ = _seed(tmp_path, status="completed")
    r = client.post(f"/tasks/{tid}/dispatch-state", headers=AUTH, json={"state": "running"})
    assert r.status_code == 400
    assert "terminal" in r.json()["error"]

    r = client.post(f"/tasks/{tid}/archive", headers=AUTH)
    assert r.status_code == 200
    r = client.post(f"/tasks/{tid}/dispatch-state", headers=AUTH, json={"state": "running"})
    assert r.status_code == 400
    assert "archived" in r.json()["error"]

    r = client.post(
        "/tasks/00000000-0000-4000-8000-000000000000/dispatch-state",
        headers=AUTH,
        json={"state": "running"},
    )
    assert r.status_code == 404


def test_reason_is_truncated_and_foreign_keys_ignored(tmp_path):
    tid, _ = _seed(tmp_path)
    r = set_dispatch_state_handler(
        task_id=tid,
        actor="operator",
        fields={"state": "refused", "reason": "x" * 900, "evil": "ignored", "attempts": 99},
        queue_dir=str(tmp_path),
    )
    assert r["ok"] is True
    d = get_task_handler(task_id=tid, queue_dir=str(tmp_path))["dispatch"]
    assert len(d["reason"]) == 500
    assert "evil" not in d
    assert d["attempts"] == 0


def test_actor_must_be_operator(tmp_path):
    tid, _ = _seed(tmp_path)
    r = set_dispatch_state_handler(
        task_id=tid, actor="administrator", fields={"state": "running"}, queue_dir=str(tmp_path)
    )
    assert r["ok"] is False
    assert "operator" in r["error"]


def test_parking_keeps_the_block(env, client):
    _, tmp_path = env
    tid, _ = _seed(tmp_path)
    client.post(
        f"/tasks/{tid}/dispatch-state",
        headers=AUTH,
        json={"state": "failed", "reason_code": "worker_exit"},
    )
    r = client.post(f"/tasks/{tid}/park", headers=AUTH, json={"note": "Worker endete mit Exit 1"})
    assert r.status_code == 200, r.text
    task = get_task_handler(task_id=tid, queue_dir=str(tmp_path))
    assert task["status"] == "parked"
    assert task["dispatch"]["reason_code"] == "worker_exit"
