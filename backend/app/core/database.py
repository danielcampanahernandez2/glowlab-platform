"""SQLAlchemy 2.0 Async Database Connection and Session Management."""
import logging
from typing import AsyncGenerator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncAttrs,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase
from app.core.config import settings

logger = logging.getLogger("glowlab.database")

# Crear el motor asíncrono de SQLAlchemy
engine = create_async_engine(
    settings.ASYNC_DATABASE_URI,
    echo=False,
    future=True,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
)

# Fábrica de sesiones asíncronas
async_session_factory = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
    autocommit=False,
)


class Base(AsyncAttrs, DeclarativeBase):
    """Clase base declarativa para todos los modelos de dominio de Glowlab."""
    pass


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependencia de FastAPI para obtener una sesión asíncrona de base de datos."""
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def check_database_connection() -> bool:
    """Verifica si la base de datos PostgreSQL está accesible y responde a consultas."""
    try:
        async with async_session_factory() as session:
            result = await session.execute(text("SELECT 1"))
            return result.scalar() == 1
    except Exception as e:
        logger.error(f"Error comprobando conexión a base de datos: {e}")
        return False
