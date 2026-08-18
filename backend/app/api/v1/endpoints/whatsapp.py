"""
WhatsApp Webhook — Glowlab Conversational Agent.

Sistema dual de atención:
  • Clientas → Asistente virtual de atención y reservas con System Prompt oficial (25 secciones)
  • Staff (Lizbeth / Anali) → Asistente de agenda interna
"""
import logging
import random
import difflib
import time
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
    staff_phone: str, staff_name: str, message_text: str, tenant_id: str = "glowlab"
) -> None:
    """
    Procesa comandos enviados por las asesoras del equipo dentro de su tenant
    de forma 100% determinista (sin LLM) para garantizar velocidad y precisión.
    """
    logger.info(f"[STAFF COMANDO] [{tenant_id}] {staff_name} ({staff_phone}): {message_text}")
    phone_norm = svc.normalize_phone(staff_phone)

    async with svc.phone_distributed_lock(phone_norm, tenant_id=tenant_id):
        reply = await svc.execute_staff_command(
            staff_phone=phone_norm,
            staff_name=staff_name,
            message=message_text,
            tenant_id=tenant_id,
        )
        if reply:
            await svc.send_message(phone_norm, reply)


# ============================================================
# MANEJADOR: CLIENTAS (MENÚ INTERACTIVO + AGENTE CONVERSACIONAL)
# ============================================================

async def handle_client_message(
    sender_number: str,
    sender_name: str,
    message_text: str,
    message_data: Dict[str, Any],
    raw_item: Dict[str, Any],
    tenant_id: str = "glowlab",
) -> None:
    """
    Atención de clientas con máquina de estados menu_estado:
    - no_iniciado: Solo activa el menú si el mensaje contiene keywords (hola, cita, agenda, servicios). Si no hay match, silencio total.
    - pendiente_seleccion: Opción 1 activa asistente_virtual (IA). Opción 2 activa atencion_personalizada (1 mensaje y silencio). Cualquier otro mensaje se ignora sin insistir.
    - atencion_personalizada: Silencio total del bot (atiende asesor humano). Resetea tras 48h de inactividad o comando de staff.
    - asistente_virtual: Flujo conversacional normal con OpenAI.
    """
    phone_norm = svc.normalize_phone(sender_number)
    has_image = "imageMessage" in message_data

    # Indicador visual de presencia 'escribiendo...' (composing) en WhatsApp
    async with svc.typing_indicator(phone_norm):
        async with svc.phone_distributed_lock(phone_norm, tenant_id=tenant_id):
            state = await svc.load_state(phone_norm, tenant_id=tenant_id)
            if sender_name and not state.get("nombre"):
                state["nombre"] = sender_name

            # 1. Manejo de comprobantes de pago recibidos como imagen
            if has_image:
                async with async_session_factory() as db:
                    intent_data = await svc.extract_intent(state, message_text)
                    await _handle_voucher_step(
                        phone_norm, state, message_text,
                        message_data, raw_item, intent_data, db,
                        tenant_id=tenant_id
                    )
                    return

            clean_text = (message_text or "").strip()
            if not clean_text:
                return

            # 2. Verificar reset por expiración de 48h en atencion_personalizada
            if svc.check_atencion_personalizada_expired(state):
                logger.info(f"⏳ [RESET 48H] Reseteando menu_estado a 'no_iniciado' tras 48h en atención personalizada para +{phone_norm}")
                state["menu_estado"] = svc.MENU_ESTADO_NO_INICIADO
                state["session_active"] = False
                state["paso"] = "inicial"
                state["menu_displayed"] = False
                state.pop("atencion_personalizada_at", None)
                await svc.save_state(phone_norm, state, tenant_id=tenant_id)

            menu_estado = state.get("menu_estado", svc.MENU_ESTADO_NO_INICIADO)

            # 3. ESTADO: atencion_personalizada -> Silencio total (asesora humana atiende manualmente)
            if menu_estado == svc.MENU_ESTADO_ATENCION_PERSONALIZADA:
                logger.info(f"🔇 [SILENCIO TOTAL] Mensaje de +{phone_norm} ignorado en 'atencion_personalizada': '{clean_text}'")
                return

            # 4. ESTADOS PREVIOS A LA SELECCIÓN: no_iniciado O pendiente_seleccion
            if menu_estado in (svc.MENU_ESTADO_NO_INICIADO, svc.MENU_ESTADO_PENDIENTE):
                # A) Opción 1: Asistente virtual (OpenAI toma el control)
                if svc.is_menu_option_1(clean_text):
                    state["menu_estado"] = svc.MENU_ESTADO_ASISTENTE
                    await svc.activate_ai_session(phone_norm, state, tenant_id=tenant_id)
                    reply = await svc.run_conversational_agent(
                        sender_number=phone_norm,
                        sender_name=sender_name,
                        message_text=message_text,
                        message_data=message_data,
                        raw_item=raw_item,
                        tenant_id=tenant_id,
                    )
                    if reply:
                        await svc.send_message(phone_norm, reply)
                    return

                # B) Opción 2: Atención personalizada (Asesor humano)
                elif svc.is_menu_option_2(clean_text):
                    state["menu_estado"] = svc.MENU_ESTADO_ATENCION_PERSONALIZADA
                    state["atencion_personalizada_at"] = time.time()
                    await svc.deactivate_ai_session(phone_norm, state, tenant_id=tenant_id, paso="derivada")
                    await svc.send_message(phone_norm, svc.HUMAN_ADVISOR_CONFIRMATION_MESSAGE)
                    await svc.notify_all_staff(
                        f"🔔 [{tenant_id}] Clienta +{phone_norm} ({state.get('nombre', sender_name)}) "
                        f"ha solicitado atención personalizada con una asesora (Opción 2)."
                    )
                    return

                # C) Si el mensaje contiene alguna keyword (hola, cita, agenda, catálogo): reenvía el menú cada vez
                elif svc.is_menu_trigger_keyword(clean_text):
                    state["menu_estado"] = svc.MENU_ESTADO_PENDIENTE
                    state["menu_displayed"] = True
                    state["session_active"] = False
                    state["last_interaction_at"] = time.time()
                    await svc.save_state(phone_norm, state, tenant_id=tenant_id)
                    await svc.send_message(phone_norm, svc.INTERACTIVE_MENU_MESSAGE)
                    return

                # D) Mensaje sin keyword y sin opción 1/2: Silencio total
                else:
                    logger.info(f"🔇 [SIN COINCIDENCIA] Mensaje sin keyword ni opción de +{phone_norm} ignorado en estado {menu_estado}: '{clean_text}'")
                    return


            # 6. ESTADO: asistente_virtual -> Flujo normal del agente conversacional
            if menu_estado == svc.MENU_ESTADO_ASISTENTE:
                is_active = await svc.check_session_active(state, phone_norm, tenant_id=tenant_id)
                if not is_active:
                    # Inactividad de 3h -> volver a no_iniciado
                    state["menu_estado"] = svc.MENU_ESTADO_NO_INICIADO
                    await svc.save_state(phone_norm, state, tenant_id=tenant_id)
                    if svc.is_menu_trigger_keyword(clean_text):
                        state["menu_estado"] = svc.MENU_ESTADO_PENDIENTE
                        state["menu_displayed"] = True
                        state["last_interaction_at"] = time.time()
                        await svc.save_state(phone_norm, state, tenant_id=tenant_id)
                        await svc.send_message(phone_norm, svc.INTERACTIVE_MENU_MESSAGE)
                    return

                state["last_interaction_at"] = time.time()
                await svc.save_state(phone_norm, state, tenant_id=tenant_id)

                reply = await svc.run_conversational_agent(
                    sender_number=phone_norm,
                    sender_name=sender_name,
                    message_text=message_text,
                    message_data=message_data,
                    raw_item=raw_item,
                    tenant_id=tenant_id,
                )
                if reply:
                    await svc.send_message(phone_norm, reply)
                return



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
    tenant_id: str = "glowlab",
) -> None:
    """Valida el comprobante de pago y confirma o rechaza la cita dentro del tenant."""
    has_image = "imageMessage" in message_data

    # Excepción explícita (no puede pagar el adelanto)
    if intent_data.get("requiere_excepcion") or any(
        k in message_text.lower() for k in ("sin adelanto", "no puedo pagar", "excepcion", "excepción")
    ):
        state["paso"] = "derivada"
        await svc.deactivate_ai_session(sender_number, state, tenant_id=tenant_id, paso="derivada")
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
                    db, state["cita_id"], "confirmada", tenant_id=tenant_id, adelanto_pagado=True
                )

            asesora = state.get("asesora", "lizbeth")
            await svc.notify_advisor(asesora, svc.build_staff_notification(state, sender_number))

            state["paso"] = "cita_confirmada"
            # Apagado automático de la sesión de IA tras confirmación exitosa de cita
            await svc.deactivate_ai_session(sender_number, state, tenant_id=tenant_id, paso="cita_confirmada")
            await svc.send_message(sender_number, svc.build_confirmation_message(state))

        else:
            # Voucher inválido: reintento o derivar
            intentos = state.get("intentos_voucher", 0) + 1
            state["intentos_voucher"] = intentos

            if intentos >= 3:
                state["paso"] = "derivada"
                await svc.deactivate_ai_session(sender_number, state, tenant_id=tenant_id, paso="derivada")
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
# PROCESADOR PRINCIPAL DEL WEBHOOK MULTI-INSTANCIA
# ============================================================

async def process_webhook_payload(payload: Dict[str, Any]) -> None:
    """
    Enruta cada mensaje entrante resolviendo el tenant a partir de la instancia de Evolution API.
    Aísla las consultas, staff, y estados conversacionales por cada negocio.
    """
    try:
        instance_name = (
            payload.get("instance")
            or payload.get("instanceName")
            or payload.get("instance_name")
            or getattr(settings, "EVOLUTION_INSTANCE_NAME", "glowlab-bot")
        )

        tenant_id = await svc.resolve_tenant_from_instance(instance_name)
        if not tenant_id:
            logger.warning(f"⚠️ [WEBHOOK REJECTED] Instancia de Evolution no reconocida o tenant inactivo: '{instance_name}'")
            try:
                import sentry_sdk
                with sentry_sdk.push_scope() as scope:
                    scope.set_tag("webhook_event", "unrecognized_instance")
                    scope.set_context("payload_info", {"instance": instance_name})
                    sentry_sdk.capture_message(
                        f"Instancia de Evolution no registrada o tenant inactivo: '{instance_name}'",
                        level="warning",
                    )
            except Exception:
                pass
            return

        # Obtener staff registrado para el tenant
        staff_list = await svc.get_tenant_staff(tenant_id)
        staff_dict: Dict[str, str] = {svc.normalize_phone(sm["phone"]): sm["name"] for sm in staff_list}
        if tenant_id == "glowlab" and not staff_dict:
            staff_dict = getattr(
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

            # ── Enrutamiento por rol y tenant ──
            if sender_number in staff_dict:
                staff_name = staff_dict[sender_number]
                await handle_staff_message(sender_number, staff_name, message_text, tenant_id=tenant_id)
            else:
                await handle_client_message(
                    sender_number, sender_name, message_text, message_data, item, tenant_id=tenant_id
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

    # 1. Encolar en ARQ / Redis Queue (<10ms)
    from app.worker import enqueue_webhook_payload
    job_id = await enqueue_webhook_payload(payload)

    if job_id:
        return {"status": "queued", "job_id": job_id, "event": payload.get("event")}

    # 2. Fallback a BackgroundTasks si Redis no está disponible
    background_tasks.add_task(process_webhook_payload, payload)
    return {"status": "received", "event": payload.get("event")}
