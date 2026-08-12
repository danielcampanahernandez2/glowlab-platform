"""WhatsApp Webhook endpoint for Evolution API integration."""
import logging
from typing import Any, Dict, Optional
from fastapi import APIRouter, BackgroundTasks, Request, Response, status
import httpx

from app.core.config import settings

logger = logging.getLogger("glowlab.whatsapp")

router = APIRouter(prefix="/whatsapp", tags=["WhatsApp Webhook"])


async def send_whatsapp_message(number: str, text: str) -> bool:
    """Envía un mensaje de texto a través de Evolution API."""
    url = f"{settings.EVOLUTION_API_URL.rstrip('/')}/message/sendText/{settings.EVOLUTION_INSTANCE_NAME}"
    headers = {
        "apikey": settings.EVOLUTION_API_KEY,
        "Content-Type": "application/json",
    }
    payload = {
        "number": number,
        "text": text,
    }

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(url, headers=headers, json=payload)
            if response.status_code in (200, 201):
                logger.info(f"Mensaje enviado con éxito a {number}")
                return True
            else:
                logger.error(
                    f"Error al enviar mensaje a {number}. Status: {response.status_code}, Body: {response.text}"
                )
                return False
    except Exception as e:
        logger.error(f"Excepción al conectar con Evolution API para {number}: {str(e)}")
        return False


def generate_bot_reply(sender_name: str, message_text: str) -> str:
    """Genera una respuesta automatizada según el mensaje recibido."""
    text_clean = message_text.lower().strip()
    nombre = sender_name or "Cliente"

    # Saludos comunes
    if any(greet in text_clean for greet in ["hola", "buenas", "buenos dias", "buenas tardes", "buenas noches", "hey"]):
        return (
            f"✨ ¡Hola {nombre}! Bienvenido/a a *Glowlab*.\n\n"
            "¿En qué podemos ayudarte hoy?\n"
            "1️⃣ *Servicios y Tratamientos*\n"
            "2️⃣ *Agendar una Cita*\n"
            "3️⃣ *Precios y Promociones*\n"
            "4️⃣ *Hablar con un Asesor*\n\n"
            "Responde con el número de la opción que deseas."
        )

    # Opciones de menú
    elif text_clean in ["1", "servicios", "tratamientos"]:
        return (
            "💆‍♀️ *Nuestros Servicios en Glowlab:*\n\n"
            "• Limpieza Facial Profunda & Hidratación\n"
            "• Tratamientos Anti-Edad & Rejuvenecimiento\n"
            "• Manicura, Pedicura & Spa\n"
            "• Masajes Relajantes y Reductores\n\n"
            "Escribe *2* o *Agendar* para reservar tu turno."
        )

    elif text_clean in ["2", "cita", "agendar", "reservar"]:
        return (
            "📅 *Agenda tu Cita en Glowlab:*\n\n"
            "Por favor indícanos:\n"
            "1. Tu nombre completo\n"
            "2. Servicio de interés\n"
            "3. Fecha y hora tentativa\n\n"
            "Un asesor confirmará tu reserva en breves minutos. ✨"
        )

    elif text_clean in ["3", "precios", "promociones", "costo"]:
        return (
            "🏷️ *Promociones del Mes en Glowlab:*\n\n"
            "✨ *Pack Glow Radiante:* Facial + Hidratación (20% OFF)\n"
            "✨ *Spa Day Relajante:* Masaje + Manicura Spa\n\n"
            "¿Deseas más información de algún tratamiento en específico?"
        )

    elif text_clean in ["4", "asesor", "humano", "ayuda"]:
        return (
            "👤 Hemos notificado a uno de nuestros especialistas.\n"
            "En un momento se comunicará contigo por este mismo chat. ¡Gracias por tu paciencia!"
        )

    # Respuesta por defecto
    return (
        f"Gracias por escribirnos a *Glowlab*, {nombre}. 🌸\n\n"
        "Hemos recibido tu mensaje y un miembro de nuestro equipo te responderá a la brevedad.\n\n"
        "Si deseas ver nuestro menú de opciones, escribe *Hola* o *Menu*."
    )


async def process_incoming_whatsapp_message(payload: Dict[str, Any]):
    """Procesa el webhook recibido de Evolution API en segundo plano."""
    try:
        data = payload.get("data", {})
        key = data.get("key", {})

        # Ignorar mensajes enviados por el propio bot (fromMe: true) para evitar bucles infinitos
        if key.get("fromMe", False):
            return

        remote_jid = key.get("remoteJid", "")
        # Ignorar mensajes de difusión o grupos si es necesario
        if not remote_jid or remote_jid == "status@broadcast":
            return

        # Extraer el número de teléfono limpio
        sender_number = remote_jid.split("@")[0]
        sender_name = data.get("pushName", "")

        # Extraer el contenido del mensaje
        message_data = data.get("message", {})
        message_text = ""

        if "conversation" in message_data and message_data["conversation"]:
            message_text = message_data["conversation"]
        elif "extendedTextMessage" in message_data and "text" in message_data["extendedTextMessage"]:
            message_text = message_data["extendedTextMessage"]["text"]

        if not message_text.strip():
            logger.info(f"Mensaje recibido sin texto procesable de {sender_number}")
            return

        logger.info(f"Mensaje recibido de [{sender_number}] ({sender_name}): {message_text}")

        # Generar respuesta automática
        reply = generate_bot_reply(sender_name, message_text)

        # Enviar respuesta al usuario
        await send_whatsapp_message(sender_number, reply)

    except Exception as e:
        logger.error(f"Error procesando mensaje entrante de WhatsApp: {str(e)}", exc_info=True)


@router.get("/webhook")
async def verify_webhook():
    """Endpoint de verificación y healthcheck del webhook."""
    return {
        "status": "online",
        "service": "Glowlab WhatsApp Webhook",
        "instance": settings.EVOLUTION_INSTANCE_NAME,
    }


@router.post("/webhook")
async def receive_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
):
    """Endpoint receptor de eventos de Evolution API."""
    try:
        payload = await request.json()
    except Exception:
        return Response(status_code=status.HTTP_400_BAD_REQUEST, content="Invalid JSON")

    event = payload.get("event", "")
    logger.info(f"Evento recibido en Webhook: {event}")

    # Procesar mensajes entrantes en segundo plano para responder HTTP 200 de inmediato a Evolution API
    if event in ("messages.upsert", "MESSAGES_UPSERT"):
        background_tasks.add_task(process_incoming_whatsapp_message, payload)

    return {"status": "received", "event": event}
