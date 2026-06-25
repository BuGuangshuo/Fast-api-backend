---
name: security-review-fastapi
description: Review repository-specific security risks in FastAPI APIs, JWT and Redis authentication, file uploads, Celery task inputs, and error handling. Use when performing a code review, pre-release audit, or risk assessment for backend changes in this repository.
---

# Security Review FastAPI

Use this skill for review-style tasks where the primary output should be concrete findings, risks, and missing safeguards.

## Review Order

1. Authentication and authorization.
Inspect token parsing, Redis session validation, privilege checks, and route protection.

2. File and upload handling.
Inspect content-type assumptions, ZIP and CSV processing, image validation, path handling, duplicate handling, and cleanup behavior.

3. Background task boundaries.
Inspect what enters Celery tasks, whether failures are recorded, and whether retries or duplicates could create data integrity issues.

4. Data exposure and error handling.
Inspect response schemas, exception messages, and whether logs leak sensitive data.

## Rules

- Prioritize findings over summaries.
- Cite files and lines when reporting issues.
- Distinguish confirmed bugs from inferred risks.
- Recommend changes that fit the repository's current architecture instead of redesigning it into a distributed system.

## Read Next

Read [review-checklist.md](../references/review-checklist.md) before starting a security review.
