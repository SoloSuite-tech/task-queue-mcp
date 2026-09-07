"""Exercise the actual broker-only HTTP transition against temporary queue files."""
import importlib

import pytest
from starlette.testclient import TestClient

from src.tools.queue import get_task_handler


MARKER = "customer-release:parker:46:" + "a" * 64 + ":" + "b" * 64
OPERATOR_HEADERS = {"X-Task-Queue-Secret": "operator-test-secret"}
BROKER_HEADERS = {"X-Customer-Release-Queue-Secret": "broker-test-secret"}


@pytest.fixture
def release_client(tmp_path, monkeypatch):
    import src.server as server

    importlib.reload(server)
    monkeypatch.setattr(server, "QUEUE_DIR", str(tmp_path))
    monkeypatch.setenv("TASK_QUEUE_API_SECRET", "operator-test-secret")
    monkeypatch.setenv("CUSTOMER_RELEASE_QUEUE_SECRET", "broker-test-secret")
    with TestClient(server.mcp.http_app()) as client:
        yield client, tmp_path


def submit(client, **changes):
    body = dict(source_agent="tickets:umsetzung", target_agent="frontend-developer",
                task_type="deploy", summary="Customer release", description=MARKER,
                requires_approval=False, workflow_mode="auto")
    body.update(changes)
    response = client.post("/tasks/submit", headers=OPERATOR_HEADERS, json=body)
    assert response.status_code == 200, response.text
    assert response.json()["ok"], response.text
    return response.json()["task_id"]


def task(queue, task_id):
    return get_task_handler(task_id, queue_dir=str(queue))


def approve(client, task_id, headers=BROKER_HEADERS, marker=MARKER):
    return client.post(f"/tasks/{task_id}/customer-release-approve", headers=headers,
                       json={"authorization": marker})


def test_customer_release_http_submit_approve_and_replay(release_client):
    client, queue = release_client
    task_id = submit(client)
    assert task(queue, task_id)["status"] == "submitted"
    response = approve(client, task_id)
    assert response.status_code == 200, response.text
    assert response.json()["ok"], response.text
    approved = task(queue, task_id)
    assert approved["status"] == "approved"
    assert approved["history"][-1]["actor"] == "customer-release"
    assert not any(h["actor"] == "operator" and h["status"] == "approved"
                   for h in approved["history"])
    # The broker reconciles an already-approved task; replay never grants a
    # second approval or replaces its audited customer decision.
    replay = approve(client, task_id)
    assert replay.status_code < 500
    assert task(queue, task_id) == approved


@pytest.mark.parametrize("headers", [{}, {"X-Customer-Release-Queue-Secret": "wrong"}, OPERATOR_HEADERS])
def test_only_dedicated_broker_secret_can_approve(release_client, headers):
    client, queue = release_client
    task_id = submit(client)
    before = task(queue, task_id)
    response = approve(client, task_id, headers=headers)
    assert response.status_code == 401
    assert task(queue, task_id) == before


@pytest.mark.parametrize("marker", [MARKER.replace(":46:", ":47:"), MARKER[:-1], "promote:site"])
def test_forged_scope_cannot_approve(release_client, marker):
    client, queue = release_client
    task_id = submit(client)
    before = task(queue, task_id)
    response = approve(client, task_id, marker=marker)
    assert response.status_code < 500
    assert response.json()["ok"] is False
    assert task(queue, task_id) == before


@pytest.mark.parametrize("changes", [{"source_agent": "administrator"}, {"task_type": "build"}, {"requires_approval": True}])
def test_operator_managed_task_cannot_use_customer_transition(release_client, changes):
    client, queue = release_client
    task_id = submit(client, **changes)
    response = approve(client, task_id)
    assert response.status_code < 500
    assert response.json()["ok"] is False
    assert task(queue, task_id)["status"] == "submitted"


def test_cancelled_task_cannot_be_revived_by_customer_replay(release_client):
    client, queue = release_client
    task_id = submit(client)
    assert approve(client, task_id).json()["ok"]
    cancelled = client.post(f"/tasks/{task_id}/cancel", headers=OPERATOR_HEADERS,
                            json={"note": "Operator stopped this release"})
    assert cancelled.json()["ok"], cancelled.text
    before = task(queue, task_id)
    assert before["status"] == "cancelled"
    response = approve(client, task_id)
    assert response.status_code < 500
    assert response.json()["ok"] is False
    assert task(queue, task_id) == before
