---
name: celery-redis-worker
description: Add and modify repository-specific Celery tasks, Redis-backed queue workflows, and beat schedules while preserving the current async-to-sync bridge and task registration model. Use when creating a task under app/tasks, wiring .delay() from a service, updating app/tasks/__init__.py imports, or changing beat scheduling in app/core/celery_app.py.
---

# Celery Redis Worker

Use this skill to keep background task changes aligned with the repository's low-throughput, single-worker design.

## Workflow

1. Define the task under `app/tasks/`.
Keep the task function synchronous at the Celery boundary and bridge async code with `asyncio.run()` when needed.

2. Register the task explicitly.
Import the task in `app/tasks/__init__.py` so `celery_app.autodiscover_tasks(["app"])` can register it.

3. Enqueue from the service layer.
Call `.delay()` from `app/services/...`, not from routers.

4. Update scheduling only when needed.
Add beat entries in `app/core/celery_app.py` for periodic jobs.

5. Mirror the dataset task comment style.
Task helpers and Celery entrypoints should use the same documentation style as `app/tasks/import_task.py` and `app/tasks/cleanup.py`: module docstring, function docstring, and inline comments for bridge or safety-critical steps.

## Constraints

- Keep `task_acks_late=False` unless the user explicitly wants to revisit idempotency and retry semantics.
- Do not introduce a result backend without a clear requirement.
- Do not refactor worker database access away from the documented sync-session compromise unless asked.
- Keep `asyncio.run()`, UUID or Enum restoration, Redis setup or teardown, and no-retry decisions documented so later refactors do not remove them blindly.

## Failure Handling

- Prefer logging and continuing over crashing the whole worker process.
- Preserve auditability. Background imports should leave enough DB state or error rows to inspect failures later.

## Read Next

Read [task-and-scheduling-patterns.md](../references/task-and-scheduling-patterns.md) before changing task registration or beat config. It also captures the repository's task-level comment and docstring rules.
