"""Main FastAPI application entry point for Glowlab."""
from contextlib import asynccontextmanager
import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.v1.router import api_v1_router
from app.core.config import settings
from app.core.database import check_database_connection
from app.core.exceptions import register_exception_handlers
from app.core.logging import setup_logging

# Inicializar configuración de logging
setup_logging()
logger = logging.getLogger("glowlab.main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manejo del ciclo de vida de la aplicación (startup y shutdown)."""
    logger.info(f"Iniciando {settings.PROJECT_NAME} v{settings.VERSION} en modo [{settings.ENVIRONMENT}]")
    
    # Comprobación de conectividad a la base de datos al arrancar
    db_connected = await check_database_connection()
    if db_connected:
        logger.info("Conexión a PostgreSQL establecida con éxito.")
    else:
        logger.warning("No se pudo conectar a PostgreSQL al iniciar. Verifique DATABASE_URL.")

    yield

    logger.info(f"Cerrando {settings.PROJECT_NAME}...")


def create_application() -> FastAPI:
    """Fábrica de creación y configuración de la instancia de FastAPI."""
    app = FastAPI(
        title=settings.PROJECT_NAME,
        version=settings.VERSION,
        openapi_url=f"{settings.API_V1_STR}/openapi.json" if settings.DEBUG else None,
        docs_url="/docs" if settings.DEBUG else None,
        redoc_url="/redoc" if settings.DEBUG else None,
        lifespan=lifespan,
    )

    # Configuración de CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.BACKEND_CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Registro de manejadores de excepciones
    register_exception_handlers(app)

    # Registrar rutas de API v1
    app.include_router(api_v1_router, prefix=settings.API_V1_STR)

    # Endpoint raíz /health para balanceadores de carga y healthchecks rápidos
    @app.get("/health", tags=["Health"], include_in_schema=False)
    async def root_health():
        db_ok = await check_database_connection()
        return JSONResponse(
            status_code=200,
            content={
                "status": "healthy" if db_ok else "degraded",
                "version": settings.VERSION,
                "environment": settings.ENVIRONMENT,
                "services": {
                    "database": "connected" if db_ok else "disconnected",
                },
            },
        )

    # Endpoint raíz / informativo
    @app.get("/", tags=["Root"], include_in_schema=False)
    async def root():
        return {
            "name": settings.PROJECT_NAME,
            "version": settings.VERSION,
            "status": "online",
            "docs": "/docs" if settings.DEBUG else "disabled",
        }

    return app


app = create_application()
