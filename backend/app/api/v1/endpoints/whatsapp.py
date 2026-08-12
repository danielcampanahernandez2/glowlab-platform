"""WhatsApp Webhook endpoint with OpenAI AI Assistant for Glowlab."""
import logging
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, BackgroundTasks, Request, Response, status
import httpx

from app.core.config import settings

logger = logging.getLogger("glowlab.whatsapp")

router = APIRouter(prefix="/whatsapp", tags=["WhatsApp Webhook"])

SYSTEM_PROMPT = """Eres la Asistente Virtual y Recepcionista Oficial de "Glowlab", un exclusivo centro de estética, belleza integral y spa.

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
- Respuestas directas: No escribas textos excesivamente largos. Si el cliente tiene dudas complejas, ofrécele contactarlo con un especialista del equipo humano.
"""


async def get_openai_reply(sender_name: str, message_text: str) -> Optional[str]:
    """Genera una respuesta inteligente utilizando OpenAI GPT."""
    if not settings.OPENAI_API_KEY:
        return None

    url = "https://api.openai.com/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {settings.OPENAI_API_KEY.strip()}",
        "Content-Type": "application/json",
    }

    user_context = f"Cliente ({sender_name or 'Cliente'}): {message_text}"

    payload = {
        "model": settings.OPENAI_MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_context},
        ],
        "temperature": 0.7,
        "max_tokens": 350,
    }

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(url, headers=headers, json=payload)
            if response.status_code == 200:
                data = response.json()
                reply = data["choices"][0]["message"]["content"].strip()
                logger.info(f"✔ Respuesta generada por OpenAI ({settings.OPENAI_MODEL})")
                return reply
            else:
                logger.warning(
                    f"⚠ OpenAI devolvió status {response.status_code} ({response.text}). Usando menú de contingencia."
                )
                return None
    except Exception as e:
        logger.warning(f"⚠ Excepción llamando a OpenAI API: {str(e)}. Usando menú de contingencia.")
        return None


def get_fallback_reply(sender_name: str, message_text: str) -> str:
    """Respuesta de respaldo garantizada si la API de IA no está disponible o sin saldo."""
    text_clean = message_text.lower().strip()
    nombre = sender_name or "Cliente"

    # Saludos comunes
    if any(greet in text_clean for greet in ["hola", "buenas", "buenos dias", "buenas tardes", "buenas noches", "hey", "ola"]):
        return (
            f"✨ ¡Hola {nombre}! Bienvenido/a a *Glowlab*.\n\n"
            "¿En qué podemos consentirte hoy?\n"
            "1️⃣ *Servicios y Tratamientos*\n"
            "2️⃣ *Agendar una Cita*\n"
            "3️⃣ *Precios y Promociones*\n"
            "4️⃣ *Hablar con un Asesor*\n\n"
            "Escribe el número de la opción o cuéntanos qué necesitas."
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
        f"Gracias por comunicarte con *Glowlab*, {nombre}. 🌸\n\n"
        "Hemos recibido tu mensaje y una asesora se comunicará contigo en breve para darte todos los detalles.\n\n"
        "Si deseas ver nuestros servicios, escribe *Menu* o *Cita* para agendar."
    )


async def send_whatsapp_message(number: str, text: str, instance_name: Optional[str] = None) -> bool:
    """Envía un mensaje de texto a través de Evolution API."""
    target_instance = instance_name or "glowlab-bot"
    url = f"{settings.EVOLUTION_API_URL.rstrip('/')}/message/sendText/{target_instance}"
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
                logger.info(f"✔ Mensaje enviado exitosamente a {number} via [{target_instance}]")
                return True
            else:
                logger.error(
                    f"✖ Error enviando mensaje a {number} via [{target_instance}]. Status: {response.status_code}, Body: {response.text}"
                )
                return False
    except Exception as e:
        logger.error(f"✖ Excepción conectando con Evolution API para {number}: {str(e)}")
        return False


def extract_message_items(raw_data: Any) -> List[Dict[str, Any]]:
    """Normaliza el payload de data tanto si viene como lista o como dict."""
    if isinstance(raw_data, list):
        return [item for item in raw_data if isinstance(item, dict)]
    elif isinstance(raw_data, dict):
        return [raw_data]
    return []


async def process_incoming_whatsapp_message(payload: Dict[str, Any]):
    """Procesa el webhook de Evolution API y responde con IA o menú."""
    try:
        # Detectar el nombre exacto de la instancia que disparó el webhook
        instance_name = payload.get("instance") or getattr(settings, "EVOLUTION_INSTANCE_NAME", "glowlab-bot") or "glowlab-bot"
        
        raw_data = payload.get("data")
        items = extract_message_items(raw_data)

        if not items:
            if "key" in payload and isinstance(payload["key"], dict):
                items = [payload]

        for item in items:
            key = item.get("key", {})
            if not isinstance(key, dict):
                continue

            # Ignorar mensajes enviados por el propio bot para evitar bucles
            if key.get("fromMe", False):
                continue

            remote_jid = key.get("remoteJid", "")
            if not remote_jid or remote_jid == "status@broadcast" or "@g.us" in remote_jid:
                continue

            sender_number = remote_jid.split("@")[0]
            sender_name = item.get("pushName", "")

            # Extraer contenido de texto
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

            logger.info(f"Mensaje entrante de [{sender_number}] ({sender_name}): {message_text}")

            # 1. Intentar responder con OpenAI
            reply = await get_openai_reply(sender_name, message_text)

            # 2. Si OpenAI falla (ej. error 429 de saldo), usar el menú interactivo garantizado
            if not reply:
                reply = get_fallback_reply(sender_name, message_text)

            # 3. Enviar respuesta por WhatsApp usando la instancia correcta
            await send_whatsapp_message(sender_number, reply, instance_name)

    except Exception as e:
        logger.error(f"Error procesando mensaje entrante de WhatsApp: {str(e)}", exc_info=True)


@router.get("/webhook")
async def verify_webhook():
    """Endpoint de verificación del webhook."""
    return {
        "status": "online",
        "service": "Glowlab WhatsApp AI Assistant",
        "ai_engine": getattr(settings, "OPENAI_MODEL", "gpt-4o-mini"),
        "instance": getattr(settings, "EVOLUTION_INSTANCE_NAME", "glowlab-bot"),
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

    if "upsert" in event:
        background_tasks.add_task(process_incoming_whatsapp_message, payload)

    return {"status": "received", "event": payload.get("event")}
