"""Task mode tests."""

import tempfile
from pathlib import Path

from phaust.tasks.commands import handle_task_command, parse_task_command
from phaust.tasks.manager import TaskManager
from phaust.tasks.models import TaskStatus
from phaust.tasks.store import TaskStore


def _manager() -> TaskManager:
    tmp = tempfile.mkdtemp()
    return TaskManager(TaskStore(Path(tmp)), auto_checkpoint=True)


def test_parse_task_start():
    cmd = parse_task_command("task start Fix bug :: repro :: patch")
    assert cmd is not None
    assert cmd.kind.value == "start"
    assert "Fix bug" in cmd.arg


def test_start_and_checkpoint():
    mgr = _manager()
    reply = handle_task_command(mgr, "task start Demo :: step one :: step two")
    assert reply is not None
    assert "Started task" in reply
    task = mgr.get_active()
    assert task is not None
    assert len(task.steps) == 2
    handle_task_command(mgr, "task checkpoint manual save")
    task = mgr.get_active()
    assert task is not None
    assert len(task.checkpoints) == 1


def test_pause_and_resume():
    mgr = _manager()
    handle_task_command(mgr, "task start Pause test")
    task = mgr.get_active()
    assert task is not None
    task_id = task.id
    handle_task_command(mgr, "task pause")
    assert mgr.get_active() is None
    handle_task_command(mgr, f"task resume {task_id}")
    resumed = mgr.get_active()
    assert resumed is not None
    assert resumed.status == TaskStatus.ACTIVE


def test_next_step_completes_task():
    mgr = _manager()
    handle_task_command(mgr, "task start One step :: only step")
    handle_task_command(mgr, "task next done")
    assert mgr.get_active() is None
    done = mgr.store.list_tasks(status=TaskStatus.DONE)
    assert len(done) == 1
