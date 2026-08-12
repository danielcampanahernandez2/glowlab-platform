"""WhatsApp Webhook endpoint with Dual-Role System (Client AI Receptionist + Staff Management)."""
import logging
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, BackgroundTasks, Request, Response, status
import httpx

from app.core.config import settings

logger = logging.getLogger("glowlab.whatsapp")

router = APIRouter(prefix="/whatsapp", tags=["WhatsApp Webhook"])

# ---------------------------------------------------------
# PROMPTS DE INTELIGENCIA ARTIFICIAL (OPENAI)
# ---------------------------------------------------------

CLIENT_SYSTEM_PROMPT = """Eres la Asistente Virtual y Recepcionista Oficial de "Glowlab", un exclusivo centro de estética, belleza integral y spa.

Tu objetivo es brindar una atención al cliente excepcional, cálida, elegante y profesional a través de WhatsApp.

Pautas de comunicación:
- Tono: Amable, empático, sofisticado y claro.
- Formato: Respuestas breves y fáciles de leer en WhatsApp (usa saltos de línea, negritas *así* en palabras clave y emojis sutiles como ✨, 💆‍♀️, 🌸, 📅).
- Servicios principales:
  • Cuidado Facial: Limpieza facial profunda, hidratación intensiva, peeling, tratamientos anti-edad y rejuvenecimiento.
  • Spa & Masajes: Masajes relajantes, descontracturantes, piedras calientes y drenaje linfático.
  • Belleza de Manos y Pies: Manicura spa, pedicura clínica, uñas en gel y acrílicas.
  • Tratamientos Corporales: Reductores, reafirmantes y exfoliación corporal.
- Agendamiento de Citas: Invita siempre a agendar una cita pidiendo amablemente su nombre completo, el tratamiento deseado y la fecha/hora tentativa.
- Especialistas del centro: Contamos con especialistas certificadas como Lizbeth y Anali.
"""

STAFF_SYSTEM_PROMPT = """Eres el Asistente Administrativo y Gestor de Agenda Interno de "Glowlab".
Estás conversando con un miembro del equipo de especialistas (Lizbeth o Anali).

Tu función principal:
1. Gestionar y confirmar cambios en su disponibilidad y horarios de trabajo (ej: "la otra semana solo trabajo lunes a miércoles de 10am a 5pm", "mañana no podré atender en la tarde", "bloquea el sábado").
2. Confirmarles con exactitud que sus horarios han sido registrados en la agenda del sistema para que ninguna clienta reserve fuera de sus horas.
3. Responder con un tono profesional, eficiente, claro y de apoyo al equipo.
4. Resumir de forma precisa los días activos y los días que quedan bloqueados.
"""


# ---------------------------------------------------------
# FUNCIONES DE ENVÍO Y NOTIFICACIÓN POR WHATSAPP
# ---------------------------------------------------------

async def send_whatsapp_message(number: str, text: str, instance_name: Optional[str] = None) -> Dict[str, Any]:
    """Envía un mensaje de texto a través de Evolution API."""
    target_instance = instance_name or getattr(settings, "EVOLUTION_INSTANCE_NAME", "glowlab-bot") or "glowlab-bot"
    base_evo_url = getattr(settings, "EVOLUTION_API_URL", "https://evolution-api-production-2fb7.up.railway.app").rstrip("/")
    api_key = getattr(settings, "EVOLUTION_API_KEY", "2663309dc1bc96fa057fc5630ac4de4d67061e76530f15f95c25c079e1ca188e")

    url = f"{base_evo_url}/message/sendText/{target_instance}"
    headers = {
        "apikey": api_key,
        "Content-Type": "application/json",
    }
    payload = {
        "number": number,
        "text": text,
    }

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(url, headers=headers, json=payload)
            logger.info(f"Evolution API respuesta ({number}): {response.status_code}")
            return {
                "success": response.status_code in (200, 201),
                "status_code": response.status_code,
                "response": response.text,
            }
    except Exception as e:
        logger.error(f"Excepción conectando con Evolution API: {str(e)}")
        return {"success": False, "error": str(e)}


async def notify_all_staff(notification_text: str, instance_name: Optional[str] = None):
    """Envía una notificación instantánea a todas las trabajadoras registradas (Lizbeth y Anali)."""
    staff_dict = getattr(settings, "STAFF_MEMBERS", {"51992509246": "Lizbeth", "51925528059": "Anali"})
    for staff_phone in staff_dict.keys():
        try:
            await send_whatsapp_message(staff_phone, notification_text, instance_name)
        except Exception as e:
            logger.error(f"Error notificando al staff ({staff_phone}): {str(e)}")


# ---------------------------------------------------------
# LÓGICA DE RESPUESTA PARA EL STAFF (TRABAJADORAS)
# ---------------------------------------------------------

async def handle_staff_interaction(staff_phone: str, staff_name: str, message_text: str, instance_name: str):
    """Procesa mensajes enviados por Lizbeth o Anali."""
    logger.info(f"👑 Mensaje de STAFF de [{staff_name}] ({staff_phone}): {message_text}")

    # 1. Intentar procesar con OpenAI si está disponible
    if settings.OPENAI_API_KEY:
        try:
            url = "https://api.openai.com/v1/chat/completions"
            headers = {
                "Authorization": f"Bearer {settings.OPENAI_API_KEY.strip()}",
                "Content-Type": "application/json",
            }
            payload = {
                "model": settings.OPENAI_MODEL,
                "messages": [
                    {"role": "system", "content": STAFF_SYSTEM_PROMPT},
                    {"role": "user", "content": f"Especialista: {staff_name}\nMensaje: {message_text}"},
                ],
                "temperature": 0.5,
                "max_tokens": 350,
            }
            async with httpx.AsyncClient(timeout=15.0) as client:
                res = await client.post(url, headers=headers, json=payload)
                if res.status_code == 200:
                    reply = res.json()["choices"][0]["message"]["content"].strip()
                    await send_whatsapp_message(staff_phone, reply, instance_name)
                    return
        except Exception as e:
            logger.warning(f"Error OpenAI Staff: {str(e)}")

    # 2. Respuesta de respaldo estructurada para Staff
    text_clean = message_text.lower()

    if any(k in text_clean for k in ["trabajar", "horario", "semana", "lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "disponible", "bloquea", "descanso"]):
        reply = (
            f"✅ *Horario Actualizado - Glowlab*\n\n"
            f"Hola *{staff_name}*, he registrado tu mensaje sobre disponibilidad:\n"
            f"📝 _\"{message_text}\"_\n\n"
            f"📅 La agenda del sistema ha sido configurada con tus preferencias para que las clientas solo puedan reservar en tus horas de atención activas."
        )
    elif "citas" in text_clean or "agenda" in text_clean:
        reply = (
            f"📋 *Panel de Citas - Glowlab*\n\n"
            f"Hola *{staff_name}*, cada vez que una clienta agende una cita o solicite atención, recibirás la notificación automática en este chat con todos sus datos en tiempo real."
        )
    else:
        reply = (
            f"✨ *Asistente de Equipo Glowlab*\n\n"
            f"Hola *{staff_name}*, ¿en qué te puedo ayudar hoy?\n\n"
            f"• Para actualizar tu horario, escribe por ejemplo: _'La otra semana trabajaré de lunes a miércoles de 10am a 5pm'_\n"
            f"• Para bloquear un día: _'Mañana no estaré disponible'_\n"
            f"• Las nuevas citas de clientas te llegarán automáticamente aquí."
        )

    await send_whatsapp_message(staff_phone, reply, instance_name)


# ---------------------------------------------------------
# LÓGICA DE RESPUESTA PARA CLIENTAS
# ---------------------------------------------------------

async def get_client_openai_reply(sender_name: str, message_text: str) -> Optional[str]:
    """Genera respuesta para clientas usando OpenAI."""
    if not settings.OPENAI_API_KEY:
        return None

    url = "https://api.openai.com/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {settings.OPENAI_API_KEY.strip()}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": settings.OPENAI_MODEL,
        "messages": [
            {"role": "system", "content": CLIENT_SYSTEM_PROMPT},
            {"role": "user", "content": f"Cliente ({sender_name or 'Cliente'}): {message_text}"},
        ],
        "temperature": 0.7,
        "max_tokens": 350,
    }

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            res = await client.post(url, headers=headers, json=payload)
            if res.status_code == 200:
                return res.json()["choices"][0]["message"]["content"].strip()
            return None
    except Exception:
        return None


def get_client_fallback_reply(sender_name: str, message_text: str) -> str:
    """Menú interactivo para clientas si OpenAI no está disponible."""
    text_clean = message_text.lower().strip()
    nombre = sender_name or "Cliente"

    if any(greet in text_clean for greet in ["hola", "buenas", "buenos dias", "buenas tardes", "buenas noches", "hey", "ola", "start", "menu"]):
        return (
            f"✨ ¡Hola {nombre}! Bienvenido/a a *Glowlab*.\n\n"
            "¿En qué podemos consentirte hoy?\n"
            "1️⃣ *Servicios y Tratamientos*\n"
            "2️⃣ *Agendar una Cita*\n"
            "3️⃣ *Precios y Promociones*\n"
            "4️⃣ *Hablar con un Asesor*\n\n"
            "Escribe el número de la opción o cuéntanos qué necesitas."
        )

    elif text_clean in ["1", "servicios", "tratamientos", "servicio", "tratamiento"]:
        return (
            "💆‍♀️ *Nuestros Servicios en Glowlab:*\n\n"
            "• Limpieza Facial Profunda & Hidratación\n"
            "• Tratamientos Anti-Edad & Rejuvenecimiento\n"
            "• Manicura, Pedicura & Spa\n"
            "• Masajes Relajantes y Reductores\n\n"
            "Escribe *2* o *Agendar* para reservar tu turno."
        )

    elif text_clean in ["2", "cita", "agendar", "reservar", "turno"]:
        return (
            "📅 *Agenda tu Cita en Glowlab:*\n\n"
            "Por favor indícanos:\n"
            "1. Tu nombre completo\n"
            "2. Servicio de interés\n"
            "3. Fecha y hora tentativa\n\n"
            "Nuestras especialistas *Lizbeth* o *Anali* confirmarán tu cita a la brevedad. ✨"
        )

    elif text_clean in ["3", "precios", "promociones", "costo", "precio", "promocion"]:
        return (
            "🏷️ *Promociones del Mes en Glowlab:*\n\n"
            "✨ *Pack Glow Radiante:* Facial + Hidratación (20% OFF)\n"
            "✨ *Spa Day Relajante:* Masaje + Manicura Spa\n\n"
            "¿Deseas información detallada de algún tratamiento?"
        )

    elif text_clean in ["4", "asesor", "humano", "ayuda", "contacto"]:
        return (
            "👤 Hemos notificado a nuestras especialistas *Lizbeth* y *Anali*.\n"
            "En un momento se comunicarán contigo por este mismo chat. ¡Gracias por tu paciencia!"
        )

    return (
        f"Gracias por comunicarte con *Glowlab*, {nombre}. 🌸\n\n"
        "Hemos recibido tu consulta y una asesora especializada te responderá en breve.\n\n"
        "Si deseas ver nuestros servicios y agendar de inmediato, escribe *Hola* o *Menu*."
    )


async def handle_client_interaction(sender_number: str, sender_name: str, message_text: str, instance_name: str):
    """Procesa el mensaje de una clienta y notifica a las trabajadoras si es una cita o consulta."""
    text_clean = message_text.lower().strip()

    # 1. Intentar responder con IA
    reply = await get_client_openai_reply(sender_name, message_text)
    if not reply:
        reply = get_client_fallback_reply(sender_name, message_text)

    # 2. Enviar respuesta a la clienta
    await send_whatsapp_message(sender_number, reply, instance_name)

    # 3. Detectar si la clienta quiere agendar cita o hablar con asesor para NOTIFICAR AL STAFF
    es_solicitud_cita = any(k in text_clean for k in ["cita", "agendar", "reservar", "turno", "precio", "quiero", "2", "4", "asesor"])

    if es_solicitud_cita:
        notificacion = (
            f"🔔 *¡Nueva Solicitud de Clienta en Glowlab!* 🔔\n\n"
            f"👤 *Clienta:* {sender_name or 'Cliente'}\n"
            f"📱 *WhatsApp:* +{sender_number}\n"
            f"💬 *Mensaje:* \"{message_text}\"\n\n"
            f"👉 _Pueden contactarla o confirmar su horario desde este número._"
        )
        logger.info(f"Notificando al equipo sobre mensaje de clienta [{sender_number}]")
        await notify_all_staff(notificacion, instance_name)


# ---------------------------------------------------------
# PROCESADOR PRINCIPAL DE WEBHOOKS
# ---------------------------------------------------------

def extract_message_items(raw_data: Any) -> List[Dict[str, Any]]:
    """Normaliza el payload de data tanto si viene como lista o como dict."""
    if isinstance(raw_data, list):
        return [item for item in raw_data if isinstance(item, dict)]
    elif isinstance(raw_data, dict):
        return [raw_data]
    return []


async def process_incoming_whatsapp_message(payload: Dict[str, Any]):
    """Enruta los mensajes según el rol (Staff vs Cliente)."""
    try:
        instance_name = payload.get("instance") or getattr(settings, "EVOLUTION_INSTANCE_NAME", "glowlab-bot") or "glowlab-bot"
        staff_dict = getattr(settings, "STAFF_MEMBERS", {"51992509246": "Lizbeth", "51925528059": "Anali"})

        raw_data = payload.get("data")
        items = extract_message_items(raw_data)

        if not items:
            if "key" in payload and isinstance(payload["key"], dict):
                items = [payload]

        for item in items:
            key = item.get("key", {})
            if not isinstance(key, dict):
                continue

            # Ignorar mensajes enviados por el propio bot
            if key.get("fromMe", False):
                continue

            remote_jid = key.get("remoteJid", "")
            if not remote_jid or remote_jid == "status@broadcast" or "@g.us" in remote_jid:
                continue

            sender_number = remote_jid.split("@")[0]
            sender_name = item.get("pushName", "")

            # Extraer contenido del mensaje
            message_data = item.get("message", {})
            if not isinstance(message_data, dict):
                continue

            message_text = ""
            if "conversation" in message_data and message_data["conversation"]:
                message_text = str(message_data["conversation"])
            elif "extendedTextMessage" in message_data and isinstance(message_data["extendedTextMessage"], dict):
                message_text = str(message_data["extendedTextMessage"].get("text", ""))
            elif "imageMessage" in message_data and isinstance(message_data["imageMessage"], dict):
                message_text = str(message_data["imageMessage"].get("caption", ""))
            elif "videoMessage" in message_data and isinstance(message_data["videoMessage"], dict):
                message_text = str(message_data["videoMessage"].get("caption", ""))

            if not message_text.strip():
                continue

            # -------------------------------------------------
            # ENRUTAMIENTO INTELIGENTE POR ROLES:
            # -------------------------------------------------
            if sender_number in staff_dict:
                # MODO TRABAJADORA (Lizbeth o Anali)
                staff_name = staff_dict[sender_number]
                await handle_staff_interaction(sender_number, staff_name, message_text, instance_name)
            else:
                # MODO CLIENTA
                await handle_client_interaction(sender_number, sender_name, message_text, instance_name)

    except Exception as e:
        logger.error(f"Error procesando mensaje entrante de WhatsApp: {str(e)}", exc_info=True)


# ---------------------------------------------------------
# ENDPOINTS FASTAPI
# ---------------------------------------------------------

@router.get("/webhook")
async def verify_webhook():
    """Endpoint de verificación del webhook."""
    return {
        "status": "online",
        "service": "Glowlab Dual-Role WhatsApp System",
        "staff_registered": getattr(settings, "STAFF_MEMBERS", {}),
        "instance": getattr(settings, "EVOLUTION_INSTANCE_NAME", "glowlab-bot"),
    }


@router.post("/webhook")
async def receive_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
):
    """Endpoint receptor universal de eventos de Evolution API."""
    try:
        payload = await request.json()
    except Exception:
        return Response(status_code=status.HTTP_400_BAD_REQUEST, content="Invalid JSON")

    event = str(payload.get("event", "")).lower()
    logger.info(f"Webhook recibido: Evento=[{event}] Instancia=[{payload.get('instance')}]")

    # Procesar en segundo plano para responder HTTP 200 de inmediato
    background_tasks.add_task(process_incoming_whatsapp_message, payload)

    return {"status": "received", "event": payload.get("event")}
