# Review Checklist

## Authentication

- Are protected endpoints using `CurrentUser` or `get_current_active_superuser` correctly?
- Does auth still validate JWT payload shape and Redis session state together?
- Are token revocation and expiration semantics preserved?

## Uploads and Files

- Are user-controlled filenames, archive contents, and extraction paths sanitized?
- Are file-type checks based on trusted validation rather than extensions alone?
- Are cleanup paths bounded to expected directories?

## Celery and Redis

- Can the same task run twice and corrupt state?
- Is `task_acks_late=False` still justified for the task's semantics?
- Are Redis keys namespaced and expired appropriately?

## API and Data

- Are error messages safe and sourced from constants?
- Are response schemas exposing only intended fields?
- Are logs avoiding secrets, raw tokens, and sensitive payloads?
