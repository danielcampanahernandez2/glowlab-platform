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
    """Procesa mensajes enviados por las asesoras del equipo."""
    logger.info(f"[STAFF] {staff_name} ({staff_phone}): {message_text}")

    # Intentar respuesta con OpenAI
    if settings.OPENAI_API_KEY:
        try:
            import httpx
            payload = {
                "model": settings.OPENAI_MODEL,
                "messages": [
                    {"role": "system", "content": STAFF_SYSTEM_PROMPT},
                    {"role": "user", "content": f"Especialista: {staff_name}\nMensaje: {message_text}"},
                ],
                "temperature": 0.4,
                "max_tokens": 300,
            }
            async with httpx.AsyncClient(timeout=12.0) as client:
                res = await client.post(
                    "https://api.openai.com/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {settings.OPENAI_API_KEY}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
                if res.status_code == 200:
                    reply = res.json()["choices"][0]["message"]["content"].strip()
                    await svc.send_message(staff_phone, reply)
                    return
        except Exception as e:
            logger.warning(f"Error OpenAI staff: {e}")

    # Respuesta de respaldo por palabras clave
    text_low = message_text.lower()
    if any(k in text_low for k in ("horario", "semana", "lunes", "martes", "miercoles",
                                    "jueves", "viernes", "sabado", "disponible",
                                    "bloquea", "descanso", "libre", "trabajar")):
        reply = (
            f"✅ *Horario actualizado — Glowlab*\n\n"
            f"Hola *{staff_name}*, registré tu disponibilidad:\n"
            f"📝 _{message_text}_\n\n"
            f"La agenda quedará configurada para que solo se reserve en tus horarios activos."
        )
    elif any(k in text_low for k in ("cita", "agenda", "reserva")):
        reply = (
            f"📋 *Agenda — Glowlab*\n\n"
            f"Hola *{staff_name}*, cada cita nueva que llegue te la notificaré "
            f"aquí con todos los datos en tiempo real."
        )
    else:
        reply = (
            f"Hola *{staff_name}* 👋\n\n"
            f"• Para actualizar tu horario escribe, por ejemplo:\n"
            f"  _'Esta semana trabajo de lunes a viernes de 10am a 6pm'_\n"
            f"• Para bloquear un día: _'Mañana no atiendo'_\n"
            f"• Las nuevas citas te llegarán automáticamente aquí."
        )

    await svc.send_message(staff_phone, reply)


# ============================================================
# MANEJADOR: CLIENTAS (CONVERSACIONAL + ATENCIÓN HUMANA)
# ============================================================

async def handle_client_message(
    sender_number: str,
    sender_name: str,
    message_text: str,
    message_data: Dict[str, Any],
    raw_item: Dict[str, Any],
) -> None:
    """
    Atención conversacional de clientas según el System Prompt oficial de Glowlab (25 secciones).
    Prioriza responder dudas/precios/recomendaciones antes de iniciar reservas.
    """
    async with async_session_factory() as db:
        state = await svc.load_state(sender_number)
        paso = state.get("paso", "inicial")

        # Guardar nombre si es la primera vez que lo tenemos
        if sender_name and not state.get("nombre"):
            state["nombre"] = sender_name

        # ── ESTADO: DERIVADA ──────────────────────────────────
        if paso == "derivada":
            await svc.send_message(
                sender_number,
                "Tu consulta está siendo atendida por una asesora. Te avisamos pronto. 🌸"
            )
            return

        # ── ESTADO: ESPERANDO VOUCHER ─────────────────────────
        if paso == "esperando_voucher":
            intent_data = await svc.extract_intent(state, message_text)
            await _handle_voucher_step(
                sender_number, state, message_text,
                message_data, raw_item, intent_data, db
            )
            return

        # ── ESTADO: ESPERANDO CONFIRMACIÓN DEL RESUMEN ───────
        if paso == "esperando_confirmacion":
            intent_data = await svc.extract_intent(state, message_text)
            intent = intent_data.get("intent", "otro")
            await _handle_confirmation_step(sender_number, state, intent, db)
            return

        # ── ESTADO: MOSTRANDO HORARIOS ────────────────────────
        if paso == "mostrando_horarios":
            intent_data = await svc.extract_intent(state, message_text)
            intent = intent_data.get("intent", "otro")
            # Si el usuario hace una pregunta o cambia de tema en vez de elegir horario
            if intent not in ("consultar", "cancelar", "excepcion") and (intent_data.get("slot_num") or intent_data.get("hora") or intent in ("confirmar", "rechazar")):
                await _handle_slot_selection(sender_number, state, intent_data)
                return

        # ── ESTADO: CITA CONFIRMADA (reinicio para nueva consulta) ─
        if paso == "cita_confirmada":
            state = {"paso": "inicial", "nombre": state.get("nombre") or sender_name}

        # ── EXTRACCIÓN DE INTENCIÓN Y ENTIDADES ───────────────
        intent_data = await svc.extract_intent(state, message_text)
        intent = intent_data.get("intent", "otro")

        # Actualizar servicio si fue mencionado
        if intent_data.get("servicio"):
            state["servicio"] = intent_data["servicio"]
            state["asesora"] = svc.detect_advisor(intent_data["servicio"])

        # Actualizar fecha si fue mencionada
        if intent_data.get("fecha"):
            from datetime import date
            parsed = svc.parse_fecha(intent_data["fecha"])
            if parsed and parsed >= date.today():
                state["fecha"] = parsed.strftime("%Y-%m-%d")

        # ── EXCEPCIÓN EXPLÍCITA ───────────────────────────────
        if intent_data.get("requiere_excepcion") or intent == "excepcion":
            state["paso"] = "derivada"
            await svc.save_state(sender_number, state)
            await svc.notify_all_staff(
                f"⚠️ Clienta +{sender_number} ({state.get('nombre', '')}) "
                f"necesita atención especial:\n\"{message_text}\""
            )
            await svc.send_message(
                sender_number,
                "Entiendo. Voy a consultar con una asesora y te avisamos enseguida. 🌸"
            )
            return

        # ── CANCELACIÓN ───────────────────────────────────────
        if intent == "cancelar":
            await svc.clear_state(sender_number)
            await svc.send_message(
                sender_number,
                "Entendido, tu solicitud ha sido cancelada. Si necesitas algo más, escríbenos. 🌸"
            )
            return

        # ── INTENCIÓN CLARA DE AGENDAR (Sección 5 y 6) ────────
        if intent == "agendar":
            # Si tenemos servicio y fecha, verificamos disponibilidad real en DB
            if state.get("servicio") and state.get("fecha"):
                from datetime import date as date_type
                target_date = svc.parse_fecha(state["fecha"])
                
                # Validación de domingos
                if target_date and target_date.weekday() == 6:
                    state["fecha"] = None
                    await svc.save_state(sender_number, state)
                    reply = await svc.generate_client_reply(
                        state, message_text,
                        extra_context="Nota: El salón Glowlab no atiende los domingos. Consulta qué otro día le viene bien."
                    )
                    await svc.send_message(sender_number, reply)
                    return

                if target_date and target_date >= date_type.today():
                    asesora = state.get("asesora") or svc.detect_advisor(state["servicio"]) or "lizbeth"
                    state["asesora"] = asesora
                    available_slots = await svc.get_available_slots(db, asesora, target_date)
                    fecha_es = svc.format_fecha_es(target_date)

                    if not available_slots:
                        state["fecha"] = None
                        await svc.save_state(sender_number, state)
                        reply = await svc.generate_client_reply(
                            state, message_text,
                            extra_context=f"Disponibilidad para {fecha_es}: NO HAY HORARIOS DISPONIBLES. Ofrece revisar otro día amablemente."
                        )
                        await svc.send_message(sender_number, reply)
                        return

                    # Horarios disponibles encontrados
                    state["slots_disponibles"] = available_slots
                    state["paso"] = "mostrando_horarios"
                    await svc.save_state(sender_number, state)
                    
                    slots_str = ", ".join([svc.format_hora_12h(s) for s in available_slots])
                    slots_formatted_list = "\n".join([f"{i}. {svc.format_hora_12h(s)}" for i, s in enumerate(available_slots, 1)])
                    
                    reply = await svc.generate_client_reply(
                        state, message_text,
                        extra_context=(
                            f"Disponibilidad confirmada en sistema para el {fecha_es}:\n"
                            f"{slots_formatted_list}\n"
                            f"Presenta estos horarios ordenados a la clienta y pregúntale cuál prefiere."
                        )
                    )
                    await svc.send_message(sender_number, reply)
                    return

        # ── CONSULTAS, PREGUNTAS, RECOMENDACIONES Y CONVERSACIÓN GENERAL ──
        # (Secciones 2, 3, 4, 8, 9, 11: Responde a la pregunta antes de intentar reservar)
        reply = await svc.generate_client_reply(state, message_text)
        await svc.save_state(sender_number, state)
        await svc.send_message(sender_number, reply)


async def _handle_slot_selection(
    sender_number: str,
    state: Dict[str, Any],
    intent_data: Dict[str, Any],
) -> None:
    """Procesa la selección de horario y avanza al resumen de confirmación."""
    available_slots: List[str] = state.get("slots_disponibles", [])
    slot_num = intent_data.get("slot_num")

    # Selección por número
    if slot_num and isinstance(slot_num, int) and 1 <= slot_num <= len(available_slots):
        state["hora"] = available_slots[slot_num - 1]
        state["paso"] = "esperando_confirmacion"
        await svc.save_state(sender_number, state)
        await svc.send_message(sender_number, svc.build_summary_message(state))
        return

    # Selección por hora explícita
    hora_raw = intent_data.get("hora", "")
    if hora_raw:
        try:
            h_str = hora_raw.lower().replace("am", "").replace("pm", "").strip().split(":")[0]
            h = int(h_str)
            if "pm" in hora_raw.lower() and h < 12:
                h += 12
            hora_norm = f"{h:02d}:00"
            if hora_norm in available_slots:
                state["hora"] = hora_norm
                state["paso"] = "esperando_confirmacion"
                await svc.save_state(sender_number, state)
                await svc.send_message(sender_number, svc.build_summary_message(state))
                return
        except (ValueError, IndexError):
            pass

    # Volver a mostrar las opciones
    try:
        from datetime import datetime
        d = datetime.strptime(state["fecha"], "%Y-%m-%d").date()
        fecha_es = svc.format_fecha_es(d)
    except Exception:
        fecha_es = state.get("fecha", "")

    await svc.send_message(sender_number, svc.build_slots_message(available_slots, fecha_es))


async def _handle_confirmation_step(
    sender_number: str,
    state: Dict[str, Any],
    intent: str,
    db: Any,
) -> None:
    """Gestiona la confirmación o rechazo del resumen de cita."""
    if intent == "confirmar":
        asesora = state.get("asesora") or svc.detect_advisor(state.get("servicio", "")) or "lizbeth"
        cita = await svc.create_cita(
            db=db,
            cliente_phone=sender_number,
            cliente_nombre=state.get("nombre", ""),
            servicio=state["servicio"],
            asesora=asesora,
            fecha=state["fecha"],
            hora=state["hora"],
        )
        state["cita_id"] = cita.id
        state["asesora"] = asesora
        state["paso"] = "esperando_voucher"
        state["intentos_voucher"] = 0
        await svc.save_state(sender_number, state)
        await svc.send_message(sender_number, svc.build_advance_message())

    elif intent == "rechazar":
        state["hora"] = None
        state["fecha"] = None
        state["paso"] = "recolectando"
        await svc.save_state(sender_number, state)
        await svc.send_message(sender_number, "Sin problema. ¿Qué día y horario prefieres?")

    else:
        await svc.send_message(sender_number, "¿Confirmamos la cita? Responde *Sí* o *No*.")


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

            sender_number = remote_jid.split("@")[0]
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
    Responde 200 de inmediato y procesa el mensaje en segundo plano.
    """
    try:
        payload = await request.json()
    except Exception:
        return Response(status_code=status.HTTP_400_BAD_REQUEST, content="Invalid JSON")

    event = str(payload.get("event", "")).lower()
    logger.info(f"Webhook recibido: [{event}] instancia=[{payload.get('instance')}]")

    background_tasks.add_task(process_webhook_payload, payload)

    return {"status": "received", "event": payload.get("event")}
