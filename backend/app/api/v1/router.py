from fastapi import APIRouter
from app.api.v1.endpoints import admin, health, whatsapp

api_v1_router = APIRouter()

# Registrar endpoints
api_v1_router.include_router(health.router)
api_v1_router.include_router(whatsapp.router)
api_v1_router.include_router(admin.router)

