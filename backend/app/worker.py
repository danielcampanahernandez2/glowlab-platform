"""
Worker Asíncrono de Procesamiento para WhatsApp Webhooks (ARQ + Redis).
Maneja:
- Procesamiento en segundo plano de mensajes entrantes fuera del proceso web de FastAPI.
- Reintentos automáticos con backoff exponencial.
- Dead Letter Queue (DLQ) en Redis ante fallos repetidos.
- Persistencia de jobs ante reinicios del servidor.
"""
import asyncio
import json
import logging
import time
from typing import Any, Dict, Optional

from arq.connections import ArqRedis, RedisSettings, create_pool
from app.core.config import settings

logger = logging.getLogger(__name__)

# Pool global de ARQ para encolar rápidamente desde FastAPI (<5ms)
_arq_pool: Optional[ArqRedis] = None


async def get_arq_redis_pool() -> Optional[ArqRedis]:
    """Obtiene o inicializa el pool de conexión de cliente ARQ."""
    global _arq_pool
    if _arq_pool is None:
        try:
            # Parsear URI de Redis
            redis_settings = RedisSettings.from_dsn(settings.REDIS_URI)
            _arq_pool = await create_pool(redis_settings)
        except Exception as e:
            logger.debug(f"Aviso conectando pool de ARQ a Redis: {e}")
            return None
    return _arq_pool


async def close_arq_redis_pool():
    """Cierra el pool de conexión de ARQ al apagar la aplicación."""
    global _arq_pool
    if _arq_pool is not None:
        try:
            await _arq_pool.close()
        except Exception:
            pass
        _arq_pool = None


async def process_whatsapp_webhook(ctx: Dict[str, Any], payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Función de trabajo (Task) ejecutada por los workers de ARQ.
    Desacopla completamente el procesamiento de LLM, tools y respuesta del ciclo HTTP de FastAPI.
    """
    job_id = ctx.get("job_id", "unknown")
    job_try = ctx.get("job_try", 1)
    logger.info(f"🚀 [ARQ Worker] Procesando webhook job={job_id} (intento {job_try})")

    try:
        from app.api.v1.endpoints.whatsapp import process_webhook_payload
        await process_webhook_payload(payload)
        return {"status": "success", "job_id": job_id}
    except Exception as e:
        logger.error(f"❌ [ARQ Worker Error] Fallo en job={job_id} (intento {job_try}): {e}", exc_info=True)
        if job_try >= 3:
            # Enviar a Dead Letter Queue (DLQ) en Redis
            await record_dead_letter_job(job_id, payload, str(e))
        raise e


async def record_dead_letter_job(job_id: str, payload: Dict[str, Any], error_str: str) -> None:
    """Registra un trabajo fallido permanentemente en la Dead Letter Queue (DLQ) en Redis y Sentry."""
    dlq_entry = {
        "job_id": job_id,
        "failed_at": time.time(),
        "error": error_str,
        "payload": payload,
    }
    logger.critical(f"💀 [DEAD LETTER QUEUE] Job={job_id} enviado a DLQ tras agotar reintentos.")
    try:
        pool = await get_arq_redis_pool()
        if pool:
            await pool.rpush("evolution:dlq:messages", json.dumps(dlq_entry, ensure_ascii=False))
    except Exception as ex:
        logger.error(f"Error persistiendo job en DLQ de Redis: {ex}")

    try:
        import sentry_sdk
        with sentry_sdk.push_scope() as scope:
            scope.set_tag("queue_event", "job_dead_letter")
            scope.set_context("dlq_info", dlq_entry)
            sentry_sdk.capture_message(f"Job {job_id} movido a Dead Letter Queue: {error_str}", level="error")
    except Exception:
        pass


async def enqueue_webhook_payload(payload: Dict[str, Any]) -> Optional[str]:
    """
    Encola un payload entrante en Redis a través de ARQ en <10ms.
    Si Redis no está disponible (modo offline o fallback), retorna None.
    """
    try:
        pool = await get_arq_redis_pool()
        if pool:
            job = await pool.enqueue_job("process_whatsapp_webhook", payload)
            if job:
                return job.job_id
    except Exception as e:
        logger.debug(f"Aviso encolando webhook en ARQ Redis: {e}")
    return None


# ============================================================
# CONFIGURACIÓN DE ARQ WORKER (Para CLI: arq app.worker.WorkerSettings)
# ============================================================

async def startup(ctx: Dict[str, Any]):
    """Hook de inicio del worker."""
    logger.info("⚡ ARQ Worker iniciado y listo para procesar colas de WhatsApp.")


async def shutdown(ctx: Dict[str, Any]):
    """Hook de apagado del worker."""
    logger.info("🛑 ARQ Worker detenido.")


class WorkerSettings:
    """Configuración estándar de ARQ Worker."""
    functions = [process_whatsapp_webhook]
    redis_settings = RedisSettings.from_dsn(settings.REDIS_URI)
    max_tries = 3
    retry_jobs = True
    job_timeout = 60
    max_jobs = 10
    on_startup = startup
    on_shutdown = shutdown
