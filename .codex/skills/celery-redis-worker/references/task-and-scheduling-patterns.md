# Task and Scheduling Patterns

## File Targets

- Task registration: `app/tasks/__init__.py`
- Import task: `app/tasks/import_task.py`
- Cleanup task: `app/tasks/cleanup.py`
- Celery app config: `app/core/celery_app.py`
- Producers: `app/services/dataset_service.py`

## Checklist

- Add every new task import to `app/tasks/__init__.py`.
- Keep task names and module paths stable when referenced by beat schedule entries.
- Use Redis as broker only; the repository does not use a result backend.
- Prefer service helpers such as enqueue functions to centralize producer logic.
- Keep the worker compatible with local development and low concurrency assumptions.

## Comment Conventions

Use `app/tasks/import_task.py` and `app/tasks/cleanup.py` as the baseline.

- Keep a module docstring at the top of every task file.
- Add a docstring to helper functions and Celery entrypoints.
- For non-trivial tasks, the docstring should state what the task does, the important parameters, and the execution steps.
- Add inline comments for bridge logic such as `asyncio.run()`, Redis initialization or teardown, lock acquisition, UUID or Enum conversion, and no-retry reasoning.
- When failure handling is delegated to the service layer, say so near the exception handler.
- Keep comments focused on why the step exists, not on rephrasing obvious syntax.

## Current Examples

- Registered tasks: `app/tasks/__init__.py`
- Beat schedule and ACK strategy: `app/core/celery_app.py`
- Producer-side orchestration: `app/services/dataset_service.py`
