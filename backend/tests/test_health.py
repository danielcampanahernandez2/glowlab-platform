"""Tests for health check and root endpoints."""
from unittest.mock import AsyncMock, patch
import pytest
from httpx import AsyncClient
from app.core.config import settings


@pytest.mark.asyncio
async def test_root_endpoint(async_client: AsyncClient):
    """Prueba que el endpoint raíz devuelva la información de la API."""
    response = await async_client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == settings.PROJECT_NAME
    assert data["version"] == settings.VERSION
    assert data["status"] == "online"


@pytest.mark.asyncio
async def test_health_endpoint_healthy(async_client: AsyncClient):
    """Prueba que /health responda correctamente cuando la base de datos está conectada."""
    with patch("app.main.check_database_connection", new_callable=AsyncMock) as mock_db:
        mock_db.return_value = True
        response = await async_client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["version"] == settings.VERSION
        assert data["environment"] == settings.ENVIRONMENT
        assert data["services"]["database"] == "connected"


@pytest.mark.asyncio
async def test_api_v1_health_endpoint_healthy(async_client: AsyncClient):
    """Prueba que /api/v1/health responda con el esquema correcto."""
    with patch("app.api.v1.endpoints.health.check_database_connection", new_callable=AsyncMock) as mock_db:
        mock_db.return_value = True
        response = await async_client.get("/api/v1/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["services"]["database"] == "connected"


@pytest.mark.asyncio
async def test_health_endpoint_degraded(async_client: AsyncClient):
    """Prueba que /health maneje de forma elegante una desconexión de base de datos."""
    with patch("app.main.check_database_connection", new_callable=AsyncMock) as mock_db:
        mock_db.return_value = False
        response = await async_client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "degraded"
        assert data["services"]["database"] == "disconnected"


@pytest.mark.asyncio
async def test_api_v1_health_endpoint_degraded(async_client: AsyncClient):
    """Prueba que /api/v1/health reporte estado degradado si la DB falla."""
    with patch("app.api.v1.endpoints.health.check_database_connection", new_callable=AsyncMock) as mock_db:
        mock_db.return_value = False
        response = await async_client.get("/api/v1/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "degraded"
        assert data["services"]["database"] == "disconnected"
