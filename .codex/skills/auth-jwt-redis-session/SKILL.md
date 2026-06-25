---
name: auth-jwt-redis-session
description: Implement and modify repository-specific authentication based on JWT tokens plus Redis-backed single-session validation. Use when changing login, logout, token parsing, current-user dependencies, Redis token keys, sliding expiration, or permission checks in FastAPI endpoints for this repository.
---

# Auth JWT Redis Session

Use this skill when touching `app/api/deps.py`, `app/services/auth_service.py`, login routes, or Redis-backed auth behavior.

## Workflow

1. Trace the request path.
Start from `OAuth2PasswordBearer`, then `TokenDep`, then `get_current_user`, then `CurrentUser` or `get_current_active_superuser`.

2. Preserve the single-session contract.
The JWT alone is not sufficient. Authentication also checks Redis for `RedisKey.access_token(user_id)` and refreshes the key TTL on valid requests.

3. Keep status codes and messages aligned.
Use `AuthMsg` and `UserMsg` constants instead of hardcoded text.

4. Change login and logout behavior carefully.
Any change to token creation must stay compatible with `AuthTokenType`, `RedisKey`, and revocation logic.

## Rules

- Keep Redis lookup and sliding expiration in the auth dependency unless the user explicitly asks for a different session model.
- Distinguish invalid credentials, invalid token type, revoked token, inactive user, and insufficient privilege paths.
- Use dependency injection instead of manual token parsing inside route handlers.
- Keep auth-facing constants under `app/core/consts/auth.py` and import them through `app.core.consts`.

## Read Next

Read [auth-flow-and-checks.md](../references/auth-flow-and-checks.md) before changing auth behavior.
