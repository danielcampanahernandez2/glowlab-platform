"""
WhatsApp Webhook — Glowlab Conversational Agent.

Sistema dual de atención:
  • Clientas → Asistente virtual de atención y reservas con System Prompt oficial (25 secciones)
  • Staff (Lizbeth / Anali) → Asistente de agenda interna
"""
import logging
import random
import difflib
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, BackgroundTasks, Request, Response, status

from app.core.config import settings
from app.core.database import async_session_factory
from app.modules.salon import services as svc
from app.modules.salon.prompts import CLIENT_SYSTEM_PROMPT, STAFF_SYSTEM_PROMPT

logger = logging.getLogger("glowlab.whatsapp")

router = APIRouter(prefix="/whatsapp", tags=["WhatsApp Webhook"])


# ============================================================
# MANEJADOR: STAFF (LIZBETH / ANALI)
# ============================================================

async def handle_staff_message(
    staff_phone: str, staff_name: str, message_text: str
) -> None:
    """
    Procesa comandos enviados por las asesoras del equipo (Lizbeth / Anali)
    de forma 100% determinista (sin LLM) para garantizar velocidad y precisión.
    """
    logger.info(f"[STAFF COMANDO] {staff_name} ({staff_phone}): {message_text}")
    phone_norm = svc.normalize_phone(staff_phone)

    async with svc.phone_distributed_lock(phone_norm):
        reply = await svc.execute_staff_command(
            staff_phone=phone_norm,
            staff_name=staff_name,
            message=message_text,
        )
        if reply:
            await svc.send_message(phone_norm, reply)


# ============================================================
# MANEJADOR: CLIENTAS (AGENTE CONVERSACIONAL CON FUNCTION CALLING)
# ============================================================

async def handle_client_message(
    sender_number: str,
    sender_name: str,
    message_text: str,
    message_data: Dict[str, Any],
    raw_item: Dict[str, Any],
) -> None:
    """
    Atención de clientas a través del Agente Conversacional Autónomo de Glowlab (OpenAI Tools).
    Permite diálogo libre, cambios de tema y ejecución autónoma de reservas y consultas.
    Utiliza lock distribuido por teléfono para garantizar procesamiento serializado y libre de condiciones de carrera.
    """
    phone_norm = svc.normalize_phone(sender_number)
    has_image = "imageMessage" in message_data

    # Indicador visual de presencia 'escribiendo...' (composing) en WhatsApp
    # Se activa de inmediato (mientras espera en el lock o procesa con OpenAI)
    async with svc.typing_indicator(phone_norm):
        async with svc.phone_distributed_lock(phone_norm):
            # Manejo de comprobantes de pago recibidos como imagen
            if has_image:
                async with async_session_factory() as db:
                    state = await svc.load_state(phone_norm)
                    intent_data = await svc.extract_intent(state, message_text)
                    await _handle_voucher_step(
                        phone_norm, state, message_text,
                        message_data, raw_item, intent_data, db
                    )
                    return

            # Procesamiento inteligente con el Agente Conversacional OpenAI
            reply = await svc.run_conversational_agent(
                sender_number=phone_norm,
                sender_name=sender_name,
                message_text=message_text,
                message_data=message_data,
                raw_item=raw_item,
            )

            if reply:
                await svc.send_message(phone_norm, reply)

# ============================================================
# GESTIÓN DE COMPROBANTES DE PAGO (VOUCHERS)
# ============================================================

async def _handle_voucher_step(
    sender_number: str,
    state: Dict[str, Any],
    message_text: str,
    message_data: Dict[str, Any],
    raw_item: Dict[str, Any],
    intent_data: Dict[str, Any],
    db: Any,
) -> None:
    """Valida el comprobante de pago y confirma o rechaza la cita."""
    has_image = "imageMessage" in message_data

    # Excepción explícita (no puede pagar el adelanto)
    if intent_data.get("requiere_excepcion") or any(
        k in message_text.lower() for k in ("sin adelanto", "no puedo pagar", "excepcion", "excepción")
    ):
        state["paso"] = "derivada"
        await svc.save_state(sender_number, state)
        await svc.notify_all_staff(
            f"⚠️ Clienta +{sender_number} ({state.get('nombre', '')}) "
            f"solicita excepción de adelanto.\n"
            f"Servicio: {state.get('servicio')} | Fecha: {state.get('fecha')} | Hora: {state.get('hora')}"
        )
        await svc.send_message(
            sender_number,
            "Entiendo. Voy a consultar con una asesora y te avisamos enseguida. 🌸"
        )
        return

    if has_image:
        # Intentar obtener base64 de la imagen
        image_b64 = await svc.get_media_base64(raw_item)
        valid = True
        reason = ""

        if image_b64:
            valid, reason = await svc.validate_voucher(image_b64)

        if valid:
            # Confirmar la cita
            state["adelanto_validado"] = True
            if state.get("cita_id"):
                await svc.update_cita_estado(
                    db, state["cita_id"], "confirmada", adelanto_pagado=True
                )

            asesora = state.get("asesora", "lizbeth")
            await svc.notify_advisor(asesora, svc.build_staff_notification(state, sender_number))

            state["paso"] = "cita_confirmada"
            await svc.save_state(sender_number, state)
            await svc.send_message(sender_number, svc.build_confirmation_message(state))

        else:
            # Voucher inválido: reintento o derivar
            intentos = state.get("intentos_voucher", 0) + 1
            state["intentos_voucher"] = intentos

            if intentos >= 3:
                state["paso"] = "derivada"
                await svc.save_state(sender_number, state)
                await svc.notify_all_staff(
                    f"⚠️ Clienta +{sender_number} ({state.get('nombre', '')}) "
                    f"tuvo problemas con el comprobante. Verificar manualmente."
                )
                await svc.send_message(
                    sender_number,
                    "No pudimos verificar el comprobante. Una asesora te contactará para ayudarte. 🌸"
                )
            else:
                await svc.save_state(sender_number, state)
                await svc.send_message(
                    sender_number,
                    f"No pudimos verificar el comprobante ({reason}). "
                    "¿Puedes enviarnos una imagen más nítida? 📸"
                )
    else:
        # No enviaron imagen
        await svc.save_state(sender_number, state)
        await svc.send_message(
            sender_number,
            f"Para confirmar tu cita envíanos la imagen del comprobante de S/ {settings.ADVANCE_AMOUNT}. 📸"
        )


# ============================================================
# PROCESADOR PRINCIPAL DEL WEBHOOK
# ============================================================

async def process_webhook_payload(payload: Dict[str, Any]) -> None:
    """Enruta cada mensaje entrante según el remitente (staff vs clienta)."""
    try:
        staff_dict: Dict[str, str] = getattr(
            settings, "STAFF_MEMBERS", {"51992509246": "Lizbeth", "51925528059": "Anali"}
        )

        raw_data = payload.get("data")
        if isinstance(raw_data, list):
            items = [i for i in raw_data if isinstance(i, dict)]
        elif isinstance(raw_data, dict):
            items = [raw_data]
        else:
            items = []

        # Compatibilidad con estructura plana
        if not items and "key" in payload and isinstance(payload.get("key"), dict):
            items = [payload]

        for item in items:
            key = item.get("key", {})
            if not isinstance(key, dict):
                continue
            if key.get("fromMe", False):
                continue

            remote_jid = key.get("remoteJid", "")
            if not remote_jid or remote_jid == "status@broadcast" or "@g.us" in remote_jid:
                continue

            # Evolution can include a device suffix (number:device@...). Keep a
            # stable, canonical key for the same person's conversation.
            raw_sender = remote_jid.split("@")[0].split(":")[0]
            sender_number = svc.normalize_phone(raw_sender)
            sender_name = item.get("pushName", "") or ""

            message_data: Dict[str, Any] = item.get("message", {}) or {}

            # Extraer texto del mensaje
            message_text = ""
            if message_data.get("conversation"):
                message_text = str(message_data["conversation"])
            elif isinstance(message_data.get("extendedTextMessage"), dict):
                message_text = str(message_data["extendedTextMessage"].get("text", ""))
            elif isinstance(message_data.get("imageMessage"), dict):
                message_text = str(message_data["imageMessage"].get("caption", ""))
            elif isinstance(message_data.get("videoMessage"), dict):
                message_text = str(message_data["videoMessage"].get("caption", ""))

            # Solo procesamos si hay texto o imagen
            has_image = "imageMessage" in message_data
            if not message_text.strip() and not has_image:
                continue

            # ── Enrutamiento por rol ──
            if sender_number in staff_dict:
                staff_name = staff_dict[sender_number]
                await handle_staff_message(sender_number, staff_name, message_text)
            else:
                await handle_client_message(
                    sender_number, sender_name, message_text, message_data, item
                )

    except Exception as e:
        logger.error(f"Error procesando payload del webhook: {e}", exc_info=True)
        try:
            import sentry_sdk
            sentry_sdk.capture_exception(e)
        except Exception:
            pass


import secrets
from fastapi.responses import JSONResponse


# ============================================================
# VERIFICACIÓN DE SEGURIDAD DEL WEBHOOK
# ============================================================

def _verify_webhook_auth(request: Request) -> bool:
    """
    Valida la autenticidad del webhook entrante comparando headers o query params
    contra EVOLUTION_WEBHOOK_SECRET (o EVOLUTION_API_KEY por compatibilidad).
    Utiliza secrets.compare_digest para mitigar ataques de temporización (timing attacks).
    """
    expected_secret = settings.EVOLUTION_WEBHOOK_SECRET or settings.EVOLUTION_API_KEY
    if not expected_secret:
        # En caso de que no haya secreto configurado (modo dev abierto), se permite
        return True

    # 1. Headers estándar de autenticación en Evolution API
    auth_header = (
        request.headers.get("apikey")
        or request.headers.get("x-api-key")
        or request.headers.get("x-webhook-secret")
    )

    # 2. Header Authorization: Bearer <secret>
    if not auth_header:
        bearer = request.headers.get("authorization", "")
        if bearer.lower().startswith("bearer "):
            auth_header = bearer[7:].strip()

    # 3. Query params de respaldo (?token=... o ?apikey=...)
    if not auth_header:
        auth_header = request.query_params.get("token") or request.query_params.get("apikey")

    if not auth_header:
        return False

    return secrets.compare_digest(auth_header, expected_secret)


# ============================================================
# ENDPOINTS FASTAPI
# ============================================================

@router.get("/webhook", summary="Estado del webhook")
async def verify_webhook():
    """Verificación de estado del webhook de WhatsApp."""
    return {
        "status": "online",
        "service": "Glowlab WhatsApp Agent",
        "instance": settings.EVOLUTION_INSTANCE_NAME,
    }


@router.post("/webhook", summary="Receptor de eventos Evolution API")
async def receive_webhook(request: Request, background_tasks: BackgroundTasks):
    """
    Endpoint receptor universal de eventos enviados por Evolution API.
    Verifica la autenticidad del secreto, responde 200 de inmediato y procesa en segundo plano.
    """
    if not _verify_webhook_auth(request):
        client_ip = request.client.host if request.client else "unknown"
        logger.warning(f"⛔ [UNAUTHORIZED] Intento de acceso no autenticado al webhook desde IP: {client_ip}")
        try:
            import sentry_sdk
            with sentry_sdk.push_scope() as scope:
                scope.set_tag("security_event", "unauthorized_webhook_attempt")
                scope.set_context("client_info", {"ip": client_ip})
                sentry_sdk.capture_message(
                    f"Intento de acceso no autorizado a /webhook desde {client_ip}",
                    level="warning",
                )
        except Exception:
            pass
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={"detail": "Unauthorized: Invalid or missing webhook authentication secret"},
        )

    try:
        payload = await request.json()
    except Exception:
        return Response(status_code=status.HTTP_400_BAD_REQUEST, content="Invalid JSON")

    event = str(payload.get("event", "")).lower()
    logger.info(f"Webhook recibido y autenticado: [{event}] instancia=[{payload.get('instance')}]")

    background_tasks.add_task(process_webhook_payload, payload)

    return {"status": "received", "event": payload.get("event")}
