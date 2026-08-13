"""Main FastAPI application entry point for Glowlab."""
import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.v1.router import api_v1_router
from app.core.config import settings
from app.core.database import check_database_connection, engine, Base
from app.core.exceptions import register_exception_handlers
from app.core.logging import setup_logging

# Importar modelos para que SQLAlchemy los registre antes de create_all
from app.modules.salon import models as _salon_models  # noqa: F401

setup_logging()
logger = logging.getLogger("glowlab.main")


# ──────────────────────────────────────────────────────────────
# INICIALIZACIÓN DE OBSERVABILIDAD (SENTRY)
# ──────────────────────────────────────────────────────────────

def _init_sentry() -> None:
    """Inicializa Sentry SDK si SENTRY_DSN está definido."""
    if settings.SENTRY_DSN:
        try:
            import sentry_sdk
            sentry_sdk.init(
                dsn=settings.SENTRY_DSN,
                environment=settings.SENTRY_ENVIRONMENT or settings.ENVIRONMENT,
                traces_sample_rate=settings.SENTRY_TRACES_SAMPLE_RATE,
                release=f"{settings.PROJECT_NAME}@{settings.VERSION}",
                send_default_pii=False,
            )
            logger.info(f"✅ Sentry SDK inicializado (env=[{settings.SENTRY_ENVIRONMENT or settings.ENVIRONMENT}]).")
        except Exception as e:
            logger.warning(f"No se pudo inicializar Sentry SDK: {e}")
    else:
        logger.info("Sentry DSN no configurado; observabilidad de Sentry desactivada.")


_init_sentry()


# ──────────────────────────────────────────────────────────────
# SCHEDULER DE RECORDATORIOS
# ──────────────────────────────────────────────────────────────

def _start_reminder_scheduler() -> None:
    """Inicia APScheduler para enviar recordatorios y seguimientos automáticos."""
    try:
        from apscheduler.schedulers.asyncio import AsyncIOScheduler
        from app.modules.salon.services import run_reminder_check

        scheduler = AsyncIOScheduler(timezone="America/Lima")
        # Cada hora en punto
        scheduler.add_job(run_reminder_check, "cron", minute=0, id="glowlab_reminders")
        scheduler.start()
        logger.info("✅ Scheduler de recordatorios iniciado (cada hora).")
        return scheduler
    except ImportError:
        logger.warning("APScheduler no instalado; recordatorios automáticos desactivados.")
        return None
    except Exception as e:
        logger.error(f"Error iniciando scheduler: {e}")
        return None


# ──────────────────────────────────────────────────────────────
# CICLO DE VIDA DE LA APLICACIÓN
# ──────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup y shutdown de la aplicación."""
    logger.info(
        f"Iniciando {settings.PROJECT_NAME} v{settings.VERSION} "
        f"en modo [{settings.ENVIRONMENT}]"
    )

    # 1. Crear tablas en PostgreSQL (si no existen)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info("✅ Tablas de base de datos verificadas / creadas.")
    except Exception as e:
        logger.error(f"Error al crear tablas: {e}")

    # 2. Verificar conectividad
    db_connected = await check_database_connection()
    if db_connected:
        logger.info("✅ Conexión a PostgreSQL establecida.")
    else:
        logger.warning("⚠️  No se pudo conectar a PostgreSQL al iniciar.")

    # 3. Iniciar scheduler de recordatorios
    scheduler = _start_reminder_scheduler()

    yield

    # Shutdown
    if scheduler:
        scheduler.shutdown(wait=False)
        logger.info("Scheduler de recordatorios detenido.")
    logger.info(f"Cerrando {settings.PROJECT_NAME}...")


# ──────────────────────────────────────────────────────────────
# FÁBRICA DE LA APLICACIÓN
# ──────────────────────────────────────────────────────────────

def create_application() -> FastAPI:
    """Crea y configura la instancia de FastAPI."""
    app = FastAPI(
        title=settings.PROJECT_NAME,
        version=settings.VERSION,
        openapi_url=f"{settings.API_V1_STR}/openapi.json" if settings.DEBUG else None,
        docs_url="/docs" if settings.DEBUG else None,
        redoc_url="/redoc" if settings.DEBUG else None,
        lifespan=lifespan,
    )

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.BACKEND_CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Manejadores de excepciones
    register_exception_handlers(app)

    # Rutas API v1
    app.include_router(api_v1_router, prefix=settings.API_V1_STR)

    # Health check
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
