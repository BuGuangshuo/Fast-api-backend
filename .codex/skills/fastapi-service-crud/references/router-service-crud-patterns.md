# Router Service CRUD Patterns

## File Targets

- Router: `app/api/routes/`
- Service: `app/services/`
- CRUD: `app/crud/`
- Schemas: `app/schemas/`
- Business constants: `app/core/consts/<domain>.py`
- Const exports: `app/core/consts/__init__.py`
- Route registration: `app/api/main.py`

## Checklist

- Add schema exports in `app/schemas/__init__.py`.
- Add CRUD exports in `app/crud/__init__.py` when introducing a new CRUD module.
- Add const exports in `app/core/consts/__init__.py` when introducing a new const module.
- Add `/options/...` endpoints for business enums through `app/api/routes/options.py` and `app/services/options_service.py`.
- Use `response_model=...` on decorators.
- Keep list endpoints on page 1-based pagination with `page_size <= 100`.
- When the UI only needs red-dot state, counts, or other summary data, add a dedicated lightweight endpoint instead of letting the frontend call a paginated list just to decide whether to show a badge.
- Alias frontend camelCase query params with `Query(..., alias=\"...\")`.
- Use `SelectOptionsResponse` for dropdown options and `PaginatedResponse[T]` for paginated lists.
- Fill enum label fields with `{field}_label: str = \"\"` plus one `@model_validator(mode=\"after\")`.
- Reuse business constants from `app.core.consts`, including `AuthMsg`, `UserMsg`, `DatasetMsg`, `FileMsg`, `TemplateMsg`, or `LabelMsg`.
- Keep business constants in domain files such as `app/core/consts/dataset.py`, `app/core/consts/label.py`, or `app/core/consts/prompt_template.py`.
- Import constants via `from app.core.consts import ...`, not from deep subpaths inside routers or services.

## Comment Conventions

Use the `datasets` module as the repository baseline:

- Router examples: `app/api/routes/datasets.py`
- Service examples: `app/services/dataset_service.py`
- CRUD examples: `app/crud/dataset.py`
- Schema examples: `app/schemas/dataset.py`
- Options examples: `app/api/routes/options.py`, `app/services/options_service.py`

### Router and Options Router

- Keep a module docstring at the top.
- Add a short docstring to every endpoint.
- Group `/options` endpoints by business domain with separator comments.
- When an option source is dynamic rather than enum-backed or DB-backed, note the source in the docstring or a nearby comment.

### Services and Options Service

- Complex functions need a function docstring plus numbered step comments.
- The docstring should state what the function does, the important parameters or call context, and the main steps.
- Explain why status fields are reset, why old results are cleared, why exports are regenerated, and why fallback selection exists.
- Simple enum-to-option helpers in `options_service.py` can stay lightweight, but every function should still have a one-line docstring.
- If an option list comes from environment config, explain that it is environment-driven and intentionally not stored in the database.

### CRUD

- List, aggregate, and batch queries need a docstring.
- Comment key phases when useful: permission filters, status filters, date normalization, total count queries, pagination, ordering, `selectinload`, and anti-N+1 batching.
- Simple `get/create/update/delete` helpers may use a single concise docstring.

### Schemas and Consts

- Group schema files with section comments so request, response, list, detail, and other subsets are easy to scan.
- Give complex schemas a short docstring.
- Keep const files lightweight but add enough docstrings or section markers that the business domain is obvious at a glance.

### Must Comment

- Service functions longer than roughly 20 to 30 lines.
- Logic with ordering constraints, compatibility fallbacks, snapshot semantics, or cross-field state coupling.
- Dynamic options and other behavior that is easy to mistake for arbitrary duplication.

## Current Examples

- Options patterns: `app/api/routes/options.py`, `app/services/options_service.py`
- Pagination patterns: `app/api/routes/datasets.py`, `app/api/routes/prompt_templates.py`
- Service orchestration: `app/services/dataset_service.py`, `app/services/prompt_template_service.py`
