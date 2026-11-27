from fastapi import APIRouter

from app.api.routes.chat import router as chat_router
from app.api.routes.documents import router as documents_router
from app.api.routes.health import router as health_router
from app.api.routes.memories import router as memories_router
from app.api.routes.threads import router as threads_router
from app.api.routes.auth import router as auth_router

api_router = APIRouter()

api_router.include_router(health_router, tags=["Health"])
api_router.include_router(threads_router, tags=["Threads"])
api_router.include_router(documents_router, tags=["Documents"])
api_router.include_router(memories_router, tags=["Memories"])
api_router.include_router(chat_router, tags=["Chat"])
api_router.include_router(auth_router, prefix = '/auth', tags = ['Auth'])

__all__ = ["api_router"]
