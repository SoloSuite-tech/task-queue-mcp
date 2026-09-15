import uuid
from unittest.mock import patch

import yaml

from src.tools import queue


def write(path, task_id, status="approved"):
    path.write_text(yaml.safe_dump({"id": task_id, "status": status}))


def test_lookup_reads_only_matching_file_and_sees_external_revocation(tmp_path):
    task_id = str(uuid.uuid4())
    for i in range(50):
        write(tmp_path / f"unrelated-{i}.yml", str(uuid.uuid4()))
    path = tmp_path / f"20260915-000000-{task_id[:8]}.yml"
    write(path, task_id)
    with patch.object(queue, "_load_task_file", wraps=queue._load_task_file) as load:
        assert queue.get_task_handler(task_id, str(tmp_path))["status"] == "approved"
        assert load.call_count == 1
    write(path, task_id, "parked")
    assert queue.get_task_handler(task_id, str(tmp_path))["status"] == "parked"
    path.unlink()
    assert queue.get_task_handler(task_id, str(tmp_path))["error"] == "not found"


def test_prefix_collision_requires_full_uuid_and_finds_legacy_filename(tmp_path):
    task_id = str(uuid.uuid4())
    collision = str(uuid.UUID(task_id[:8] + "-0000-0000-0000-000000000000"))
    write(tmp_path / f"20260915-000000-{task_id[:8]}.yml", collision)
    write(tmp_path / "legacy.yml", task_id, "parked")
    assert queue.get_task_handler(task_id, str(tmp_path))["status"] == "parked"


def test_legacy_main_queue_entry_takes_precedence_over_archived_copy(tmp_path):
    task_id = str(uuid.uuid4())
    archive = tmp_path / "archive"
    archive.mkdir()
    write(archive / f"20260915-000000-{task_id[:8]}.yml", task_id, "approved")
    main = tmp_path / "legacy.yml"
    write(main, task_id, "parked")
    assert queue.get_task_handler(task_id, str(tmp_path))["status"] == "parked"
    main.unlink()
    assert queue.get_task_handler(task_id, str(tmp_path))["status"] == "approved"
