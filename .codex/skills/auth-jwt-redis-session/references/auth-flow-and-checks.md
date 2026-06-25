# Auth Flow and Checks

## File Targets

- Auth dependencies: `app/api/deps.py`
- Auth service: `app/services/auth_service.py`
- Login routes: `app/api/routes/login.py`
- Token schema: `app/schemas/token.py`
- Auth constants: `app/core/consts/auth.py`
- Redis key builders: `app/core/consts/redis_keys.py`

## Checklist

- Keep `OAuth2PasswordBearer` as the extraction layer only.
- Decode JWT, validate payload shape, then validate token type.
- Check Redis with `RedisKey.access_token(user_id)` for the active access token key.
- Refresh TTL on successful authenticated requests.
- Return `403` for invalid credentials and `401` for revoked or wrong-type tokens as currently established.
- Keep superuser checks in `get_current_active_superuser`.
- Keep auth token types in `AuthTokenType`, not ad hoc string literals or deleted legacy modules.

## Current Examples

- Dependency chain and Redis validation: `app/api/deps.py`
- User-facing auth messages and token types: `app/core/consts/auth.py`
- Redis auth key naming: `app/core/consts/redis_keys.py`
