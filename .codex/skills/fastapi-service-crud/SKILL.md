---
name: fastapi-service-crud
description: Implement and modify repository-specific FastAPI endpoints using the established router-to-service-to-CRUD layering, schema patterns, pagination style, options endpoints, and message constants. Use when adding a new business module, changing list/detail/create/update/delete APIs, adjusting query parameters, wiring response_model declarations, or enforcing this repository's backend conventions.
---

# FastAPI Service CRUD

Use this skill to keep HTTP-layer work aligned with this repository's backend contract. Apply it before editing routers, services, CRUD functions, schemas, or options endpoints.

## Workflow

1. Identify the feature boundary.
Decide which files belong in `app/api/routes/`, `app/services/`, `app/crud/`, `app/schemas/`, `app/core/consts/<domain>.py`, and `app/api/main.py`.

2. Keep responsibilities narrow.
Put input validation and dependency injection in routers, orchestration and permission checks in services, and pure database access in CRUD functions.

3. Follow repository response patterns.
Declare `response_model` on the decorator, return schema objects, use `PaginatedResponse[T]` for list endpoints that truly need browsing, and expose enum select data through `app/api/routes/options.py`.
If a UI only needs badge state, unread counts, or other high-frequency summary data, add a separate lightweight summary endpoint instead of reusing a heavy list endpoint.

4. Use message constants for user-facing text.
Do not hardcode `HTTPException.detail`, success messages, or other user-visible strings in routers or services. Pull them from `app.core.consts`, and add new business constants under the matching `app/core/consts/<domain>.py` file.

5. Keep naming consistent.
Prefer `list_xxx`, `get_xxx_by_id`, `create_xxx`, `update_xxx`, `delete_xxx`, and router endpoint names like `delete_project_endpoint`.

6. Mirror the dataset module's comment style.
When editing routers, services, CRUD, schemas, consts, or options endpoints, keep the same comment granularity and docstring style used by the `datasets` module instead of mixing sparse and dense files.

## API Identity Rules

- Keep UUID as the backend resource identity for persistence, foreign keys, router path params, and internal associations.
- If a module has a business display code, return both the UUID `id` and the display code field in list/detail/create/copy responses.
- Do not replace existing `/{id}` style routes with code-based routes unless a requirement explicitly asks for that API change.
- For nested creator, dataset, template, or related-resource summaries, include the corresponding business display code when it improves frontend display consistency.
- Do not return frontend-owned route URLs from backend APIs. Return stable ids, codes, action keys, or other jump parameters, and let the frontend map them to routes.
- Demo-only `Item` does not need a business display code in API schemas.
- `Label` keeps using its existing `code` semantics and should not be expanded into the daily-sequence display-code pattern by default.

## Router Rules

- Keep dependency order as `session`, optional `redis`, `current_user`, then request/query params.
- Use camelCase aliases for frontend query parameters such as `pageSize`, `sortOrder`, `startTime`, and `endTime`.
- Keep route handlers thin. If business logic starts branching, move it into a service.
- Use admin dependencies on the decorator when the entire endpoint requires elevated access.
- Keep a module docstring at the top and a short docstring on every endpoint.
- Group `/options` endpoints by business domain and note dynamic sources such as environment-driven model lists.

## Service Rules

- Validate permissions and existence early.
- Raise `HTTPException` with the repository's status-code conventions: `403` for permission, `404` for missing resources, `409` for conflicts.
- Queue Celery tasks from the service layer, not from routers.
- Return response schemas or message schemas instead of raw ORM objects when the API shape matters.
- For complex service functions, add both a function docstring and numbered step comments like `create_dataset_service()` or `process_import()`.
- Explain status resets, snapshot rebuilds, fallback reselection, export rewrites, and other logic that looks removable but is not.

## CRUD Rules

- Keep CRUD functions free of business orchestration.
- For paginated lists, return `tuple[list[T], int]`.
- When a requirement explicitly says a small timeline or history feed should be returned whole, keep the CRUD and router contract non-paginated instead of forcing `PaginatedResponse[T]`.
- For notification, operation-log, or other potentially growing feeds, prefer a split contract: lightweight summary endpoint for badge state and paginated list endpoint for detail browsing.
- Use `col(Model.field).icontains(keyword)` for keyword search where applicable.
- For end dates at midnight, expand to the end of that day before querying.
- Avoid N+1 queries with `selectinload` and batched aggregation queries.
- Give list, aggregate, and batch queries a docstring plus comments for filters, total counts, pagination, and preloading.

## Read Next

Read [router-service-crud-patterns.md](/home/RealAI/cert_phase2_backend/.codex/skills/fastapi-service-crud/references/router-service-crud-patterns.md) before making structural changes. It contains the concrete repository checklist and the dataset-style comment conventions for router/service/crud/schema/const/options files.
