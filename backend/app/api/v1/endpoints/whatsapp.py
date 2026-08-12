"""WhatsApp Webhook endpoint for Evolution API integration."""
import logging
from typing import Any, Dict, List, Union
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
                logger.info(f"✔ Mensaje enviado exitosamente a {number}")
                return True
            else:
                logger.error(
                    f"✖ Error enviando mensaje a {number}. Status: {response.status_code}, Body: {response.text}"
                )
                return False
    except Exception as e:
        logger.error(f"✖ Excepción conectando con Evolution API para {number}: {str(e)}")
        return False


def generate_bot_reply(sender_name: str, message_text: str) -> str:
    """Genera una respuesta automatizada según el mensaje recibido."""
    text_clean = message_text.lower().strip()
    nombre = sender_name or "Cliente"

    # Saludos comunes
    if any(greet in text_clean for greet in ["hola", "buenas", "buenos dias", "buenas tardes", "buenas noches", "hey", "ola"]):
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
            "Un asesor confirmará tu reserva en breves minutos. ✨"
        )

    elif text_clean in ["3", "precios", "promociones", "costo", "precio", "promocion"]:
        return (
            "🏷️ *Promociones del Mes en Glowlab:*\n\n"
            "✨ *Pack Glow Radiante:* Facial + Hidratación (20% OFF)\n"
            "✨ *Spa Day Relajante:* Masaje + Manicura Spa\n\n"
            "¿Deseas más información de algún tratamiento en específico?"
        )

    elif text_clean in ["4", "asesor", "humano", "ayuda", "contacto"]:
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


def extract_message_items(raw_data: Any) -> List[Dict[str, Any]]:
    """Normaliza el payload de data tanto si viene como lista o como dict."""
    if isinstance(raw_data, list):
        return [item for item in raw_data if isinstance(item, dict)]
    elif isinstance(raw_data, dict):
        return [raw_data]
    return []


async def process_incoming_whatsapp_message(payload: Dict[str, Any]):
    """Procesa el webhook recibido de Evolution API de forma robusta."""
    try:
        raw_data = payload.get("data")
        items = extract_message_items(raw_data)

        if not items:
            # Si el payload es plano
            if "key" in payload and isinstance(payload["key"], dict):
                items = [payload]

        for item in items:
            key = item.get("key", {})
            if not isinstance(key, dict):
                continue

            # Ignorar mensajes enviados por el propio bot para evitar bucles infinitos
            if key.get("fromMe", False):
                continue

            remote_jid = key.get("remoteJid", "")
            if not remote_jid or remote_jid == "status@broadcast" or "@g.us" in remote_jid:
                continue

            # Extraer número limpio
            sender_number = remote_jid.split("@")[0]
            sender_name = item.get("pushName", "")

            # Extraer texto del mensaje
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
                logger.info(f"Mensaje sin texto procesable de {sender_number}")
                continue

            logger.info(f"Mensaje entrante de [{sender_number}] ({sender_name}): {message_text}")

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

    event = str(payload.get("event", "")).lower()
    logger.info(f"Evento recibido en Webhook: {event}")

    # Procesar eventos de tipo messages.upsert (soporta cualquier variación de mayúsculas/guiones)
    if "upsert" in event:
        background_tasks.add_task(process_incoming_whatsapp_message, payload)

    return {"status": "received", "event": payload.get("event")}
