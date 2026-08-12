"""Health check endpoint to verify API and database operational status."""
from typing import Dict
from fastapi import APIRouter, status
from pydantic import BaseModel
from app.core.config import settings
from app.core.database import check_database_connection

router = APIRouter(tags=["Health"])


class HealthResponse(BaseModel):
    status: str
    version: str
    environment: str
    services: Dict[str, str]


@router.get(
    "/health",
    response_model=HealthResponse,
    status_code=status.HTTP_200_OK,
    summary="Verificar estado de salud de la API y dependencias",
)
async def get_health() -> HealthResponse:
    """Endpoint de diagnóstico que verifica el estado del backend y la conexión a PostgreSQL."""
    db_ok = await check_database_connection()

    services_status = {
        "database": "connected" if db_ok else "disconnected",
    }

    overall_status = "healthy" if db_ok else "degraded"

    return HealthResponse(
        status=overall_status,
        version=settings.VERSION,
        environment=settings.ENVIRONMENT,
        services=services_status,
    )
