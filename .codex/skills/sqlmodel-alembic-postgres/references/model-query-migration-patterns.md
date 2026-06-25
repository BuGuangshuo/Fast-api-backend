# Model Query Migration Patterns

## File Targets

- ORM models and enums: `app/models.py`
- CRUD modules: `app/crud/`
- API schemas: `app/schemas/`
- Alembic revisions: `app/alembic/versions/`

## Checklist

- Keep new ORM models in `app/models.py`; do not split into per-model files.
- Add forward references with `from __future__ import annotations` instead of `TYPE_CHECKING`.
- Add enum label maps immediately after enum declarations.
- Export schema additions from `app/schemas/__init__.py`.
- Export CRUD additions from `app/crud/__init__.py`.
- Prefer UUID primary keys and UTC timestamps to match existing models.
- Inspect generated migrations for indexes and foreign keys before running them.

## Comment Conventions

Use the `datasets` area in `app/models.py`, `app/schemas/dataset.py`, and `app/crud/dataset.py` as the baseline.

### Models

- Keep business-domain separator comments in `app/models.py`.
- Add short purpose comments or class docstrings for non-obvious enums and ORM classes.
- Explain fields or relationships that are easy to misunderstand, such as snapshot tables, historical versions, link tables, or parent-child lineage fields.

### Schemas

- Group schema files with section comments so request, response, list, detail, and workflow-specific payloads are easy to scan.
- Give complex schemas a short docstring when their role is not obvious from the class name alone.
- Keep enum label fields and validators visually close enough that the mapping pattern is easy to recognize.

### CRUD Queries

- List, aggregate, and batch queries should have a docstring.
- Add comments when query phases are not obvious, especially permission filters, date normalization, total count queries, ordering, pagination, preloading, and batch aggregation.
- Keep simple `get/create/update/delete` helpers lightweight.

## Current Examples

- Dataset and import models: `app/models.py`
- Dataset CRUD query patterns: `app/crud/dataset.py`
- Existing revisions: `app/alembic/versions/`
