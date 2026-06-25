from fastapi import APIRouter

from app.api.routes import login, options, test_redis, utils

api_router = APIRouter()
api_router.include_router(utils.router)
api_router.include_router(login.router)
api_router.include_router(options.router)
api_router.include_router(test_redis.router)
