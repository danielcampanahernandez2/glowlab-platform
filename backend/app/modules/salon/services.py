"""
Lógica de negocio central de Glowlab.

Incluye:
- Gestión de estado conversacional (Redis)
- Extracción de intención con OpenAI
- Motor de reservas y disponibilidad (PostgreSQL)
- Validación de voucher de pago (OpenAI Vision)
- Mensajes de recordatorio y seguimiento post-servicio
- Cliente de Evolution API para enviar mensajes
"""
import json
import logging
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import httpx
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import async_session_factory
from app.modules.salon.models import Cita, Cliente, Conversacion
from app.modules.salon.prompts import CLIENT_SYSTEM_PROMPT

logger = logging.getLogger("glowlab.salon.services")


# ============================================================
# CONFIGURACIÓN Y CONSTANTES
# ============================================================

# Palabras clave → asesora interna asignada
SERVICE_TO_ADVISOR: Dict[str, str] = {
    # Lizbeth: uñas
    "uña": "lizbeth", "uñas": "lizbeth", "una": "lizbeth", "unas": "lizbeth",
    "manicure": "lizbeth", "manicura": "lizbeth",
    "pedicure": "lizbeth", "pedicura": "lizbeth",
    "gel": "lizbeth", "acrilica": "lizbeth", "acrílica": "lizbeth",
    "acrilicas": "lizbeth", "acrílicas": "lizbeth",
    "nail": "lizbeth", "semipermanente": "lizbeth", "semiperm": "lizbeth",
    "pintado": "lizbeth", "diseño": "lizbeth", "diseños": "lizbeth",
    # Lizbeth: pestañas
    "pestaña": "lizbeth", "pestañas": "lizbeth",
    "pestana": "lizbeth", "pestanas": "lizbeth",
    "extension": "lizbeth", "extensiones": "lizbeth",
    "lash": "lizbeth", "lashes": "lizbeth",
    "lashista": "lizbeth",
    # Anali: tratamientos capilares
    "capilar": "anali", "capilares": "anali",
    "cabello": "anali", "pelo": "anali",
    "alisado": "anali", "alisamiento": "anali",
    "tinte": "anali", "tintura": "anali",
    "tratamiento": "anali", "tratamientos": "anali",
    "corte": "anali",
    "hidratacion": "anali", "hidratación": "anali",
    "hidratacion express": "anali", "hidratación express": "anali",
    "keratina": "anali",
    "botox": "anali", "botox capilar": "anali",
    "mechas": "anali", "balayage": "anali",
    "peinado": "anali", "brushing": "anali",
    "ondas": "anali", "rulos": "anali",
}

# Teléfonos internos (solo uso del sistema)
STAFF_PHONES: Dict[str, str] = {
    "lizbeth": "51992509246",
    "anali":   "51925528059",
}

ADVISOR_SPECIALTIES: Dict[str, str] = {
    "lizbeth": "pestañas y uñas",
    "anali":   "tratamientos capilares",
}

# Horarios disponibles por defecto (lunes-sábado, 10:00-18:00, cada 60 min)
AVAILABLE_SLOTS: List[str] = [
    "10:00", "11:00", "12:00", "13:00",
    "14:00", "15:00", "16:00", "17:00", "18:00",
]

DAYS_ES: Dict[int, str] = {
    0: "lunes", 1: "martes", 2: "miércoles",
    3: "jueves", 4: "viernes", 5: "sábado", 6: "domingo",
}

MONTHS_ES: Dict[int, str] = {
    1: "enero",    2: "febrero",   3: "marzo",
    4: "abril",    5: "mayo",      6: "junio",
    7: "julio",    8: "agosto",    9: "septiembre",
    10: "octubre", 11: "noviembre", 12: "diciembre",
}

REDIS_STATE_TTL = 60 * 60 * 48   # 48 horas

# ============================================================
# CATÁLOGO DE SERVICIOS OFICIAL (SECCIÓN 10 DEL SYSTEM PROMPT)
# ============================================================

SERVICE_CATALOG: Dict[str, List[Dict[str, Any]]] = {
    "Pestañas": [
        {"name": "Extensiones naturales", "desc": "Look natural y sutil realizado por lashista", "price": 80},
        {"name": "Extensiones más definidas", "desc": "Mayor volumen y definición en tu mirada", "price": 100},
        {"name": "Estilo a medida", "desc": "Diseño personalizado según tu estilo", "price": 50},
    ],
    "Uñas": [
        {"name": "Pintado", "desc": "Pintado tradicional o semipermanente de uñas", "price": 30},
        {"name": "Diseños y decoración", "desc": "Arte y decoración personalizada en uñas", "price": 45},
        {"name": "Otros servicios de uñas", "desc": "Servicios especiales de uñas disponibles en catálogo", "price": 0},
    ],
    "Tratamientos capilares": [
        {"name": "Tratamiento de hidratación", "desc": "Nutrición y suavidad profunda para el cabello", "price": 80},
        {"name": "Tratamiento de keratina", "desc": "Control de frizz, alisado y restauración capilar", "price": 160},
        {"name": "Botox capilar", "desc": "Mejora la apariencia, suavidad y brillo del cabello", "price": 120},
        {"name": "Hidratación express", "desc": "Tratamiento rápido de hidratación y brillo", "price": 50},
    ],
}


def get_service_price(service_name: str) -> Optional[str]:
    """Retorna un mensaje formateado con el precio y descripción si el servicio existe."""
    lowered = service_name.lower().strip()
    for cat, cat_services in SERVICE_CATALOG.items():
        for svc_item in cat_services:
            item_name_low = svc_item["name"].lower()
            if item_name_low in lowered or lowered in item_name_low or any(w in lowered for w in item_name_low.split() if len(w) > 3):
                price = svc_item.get("price", 0)
                desc = svc_item.get("desc", "")
                if price:
                    return (
                        f"El {svc_item['name']} tiene un precio de S/ {price}. ✨\n"
                        f"{desc}.\n"
                        f"Si deseas, también puedo ayudarte a revisar horarios disponibles para realizarlo. 😊"
                    )
                else:
                    return (
                        f"El servicio de {svc_item['name']} está disponible en nuestro catálogo. ✨\n"
                        f"{desc}.\n"
                        f"Si deseas, puedo orientarte con más información o revisar disponibilidad. 😊"
                    )
    return None


def list_services() -> str:
    """Retorna la lista organizada de servicios oficiales según el System Prompt (Sección 8 y 10)."""
    return (
        "Claro 😊 Tenemos:\n\n"
        "• *Pestañas:* desde S/ 50 (realizado por lashista)\n"
        "• *Uñas:* desde S/ 30 (pintado, diseños y más)\n"
        "• *Botox capilar:* S/ 120\n"
        "• *Keratina:* S/ 160\n"
        "• *Tratamiento de hidratación:* S/ 80\n"
        "• *Hidratación express:* S/ 50\n\n"
        "Si me cuentas qué resultado buscas, puedo orientarte sobre cuál podría ser más adecuado para ti. ✨"
    )


def prompt_subservice(category: str) -> str:
    """Pregunta por el subservicio específico según la categoría seleccionada."""
    cat_key = category.title()
    if cat_key == "Uñas":
        return "¡Claro! 💅 ¿Te gustaría un pintado sencillo o buscas algún diseño/decoración? 😊"
    if cat_key == "Pestañas":
        return "¡Perfecto! ✨ En pestañas podemos ayudarte con diferentes opciones. ¿Buscas algo natural, más definido o tienes algún estilo específico en mente?"
    if cat_key == "Tratamientos capilares":
        return "¡Claro! 💇‍♀️ Tenemos tratamiento de hidratación, keratina, botox capilar e hidratación express. ¿Qué resultado buscas principalmente para tu cabello?"
    return "¿Qué servicio deseas realizarte? 😊"

# ============================================================
# UTILIDADES DE FECHA
# ============================================================

def parse_fecha(text: str) -> Optional[date]:
    """Convierte texto en lenguaje natural a un objeto date."""
    today = date.today()
    s = text.lower().strip()

    if s in ("hoy",):
        return today
    if "pasado mañana" in s or "pasado manana" in s:
        return today + timedelta(days=2)
    if "mañana" in s or "manana" in s:
        return today + timedelta(days=1)

    day_map = {
        "lunes": 0, "martes": 1,
        "miercoles": 2, "miércoles": 2,
        "jueves": 3, "viernes": 4,
        "sabado": 5, "sábado": 5, "domingo": 6,
    }
    for name, num in day_map.items():
        if name in s:
            ahead = num - today.weekday()
            if ahead <= 0:
                ahead += 7
            return today + timedelta(days=ahead)

    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text.strip(), fmt).date()
        except ValueError:
            pass

    for fmt in ("%d/%m", "%d-%m"):
        try:
            parsed = datetime.strptime(text.strip(), fmt)
            result = parsed.replace(year=today.year).date()
            if result < today:
                result = result.replace(year=today.year + 1)
            return result
        except ValueError:
            pass

    return None


def format_fecha_es(d: date) -> str:
    """Formatea una fecha en español: 'viernes 15 de agosto'."""
    return f"{DAYS_ES[d.weekday()]} {d.day} de {MONTHS_ES[d.month]}"


def format_hora_12h(hora_24: str) -> str:
    """Convierte '14:00' → '2:00 pm'."""
    try:
        h, m = map(int, hora_24.split(":"))
        ampm = "am" if h < 12 else "pm"
        h12 = h if 1 <= h <= 12 else (h - 12 if h > 12 else 12)
        return f"{h12}:{m:02d} {ampm}"
    except Exception:
        return hora_24


# ============================================================
# GESTIÓN DE ESTADO CONVERSACIONAL (REDIS)
# ============================================================

_redis_client = None


async def _get_redis():
    global _redis_client
    if _redis_client is None:
        try:
            import redis.asyncio as aioredis
            _redis_client = aioredis.from_url(
                settings.REDIS_URI,
                encoding="utf-8",
                decode_responses=True,
            )
        except Exception as e:
            logger.error(f"Error conectando a Redis: {e}")
    return _redis_client


async def load_state(phone: str) -> Dict[str, Any]:
    """Carga estado por teléfono; PostgreSQL es la fuente durable y Redis la caché."""
    durable_state: Dict[str, Any] = {"paso": "inicial"}
    try:
        async with async_session_factory() as db:
            result = await db.execute(select(Conversacion.estado).where(Conversacion.phone == phone))
            saved = result.scalar_one_or_none()
            if isinstance(saved, dict):
                durable_state = saved
    except Exception as e:
        logger.warning(f"Error leyendo estado durable ({phone}): {e}")

    try:
        r = await _get_redis()
        if r:
            raw = await r.get(f"glowlab:conv:{phone}")
            if raw:
                cached = json.loads(raw)
                if cached.get("updated_at", "") >= durable_state.get("updated_at", ""):
                    return cached
    except Exception as e:
        logger.warning(f"Error leyendo estado Redis ({phone}): {e}")
    return durable_state


async def save_state(phone: str, state: Dict[str, Any]) -> None:
    """Persiste el estado en PostgreSQL y actualiza la caché Redis con TTL de 48h."""
    state["updated_at"] = datetime.utcnow().isoformat()
    try:
        async with async_session_factory() as db:
            result = await db.execute(select(Conversacion).where(Conversacion.phone == phone))
            conversation = result.scalar_one_or_none()
            if conversation:
                conversation.estado = state
            else:
                db.add(Conversacion(phone=phone, estado=state))
            await db.commit()
    except Exception as e:
        logger.warning(f"Error guardando estado durable ({phone}): {e}")

    try:
        r = await _get_redis()
        if r:
            await r.setex(
                f"glowlab:conv:{phone}",
                REDIS_STATE_TTL,
                json.dumps(state, ensure_ascii=False),
            )
    except Exception as e:
        logger.warning(f"Error guardando estado Redis ({phone}): {e}")


async def clear_state(phone: str) -> None:
    """Elimina el estado conversacional de una clienta."""
    try:
        r = await _get_redis()
        if r:
            await r.delete(f"glowlab:conv:{phone}")
    except Exception as e:
        logger.warning(f"Error borrando estado Redis ({phone}): {e}")

    await save_state(phone, {"paso": "inicial"})


# ============================================================
# DETECCIÓN DE ASESORA POR SERVICIO
# ============================================================

def detect_advisor(servicio: str) -> Optional[str]:
    """Retorna la asesora interna asignada según el servicio solicitado."""
    s = servicio.lower()
    for keyword, advisor in SERVICE_TO_ADVISOR.items():
        if keyword in s:
            return advisor
    return None


# ============================================================
# MOTOR DE RESERVAS (POSTGRESQL)
# ============================================================

async def get_available_slots(
    db: AsyncSession, advisor: str, target_date: date
) -> List[str]:
    """Retorna los horarios libres de una asesora para una fecha dada."""
    # Sin atención los domingos
    if target_date.weekday() == 6:
        return []

    date_str = target_date.strftime("%Y-%m-%d")
    result = await db.execute(
        select(Cita.hora).where(
            and_(
                Cita.asesora == advisor,
                Cita.fecha == date_str,
                Cita.estado.in_(["pendiente", "confirmada"]),
            )
        )
    )
    booked = {row[0] for row in result.fetchall()}
    return [slot for slot in AVAILABLE_SLOTS if slot not in booked]


async def create_cita(
    db: AsyncSession,
    cliente_phone: str,
    cliente_nombre: str,
    servicio: str,
    asesora: str,
    fecha: str,
    hora: str,
    observaciones: str = "",
) -> Cita:
    """Crea una nueva cita en estado 'pendiente' y actualiza el perfil de la clienta."""
    cita = Cita(
        cliente_phone=cliente_phone,
        cliente_nombre=cliente_nombre or "",
        servicio=servicio,
        asesora=asesora,
        fecha=fecha,
        hora=hora,
        estado="pendiente",
        adelanto_requerido=True,
        adelanto_monto=float(settings.ADVANCE_AMOUNT),
        observaciones=observaciones,
    )
    db.add(cita)
    await db.flush()  # obtener el ID sin hacer commit todavía

    # Upsert de la clienta
    res = await db.execute(select(Cliente).where(Cliente.phone == cliente_phone))
    cliente = res.scalar_one_or_none()
    if not cliente:
        cliente = Cliente(phone=cliente_phone, nombre=cliente_nombre or "")
        db.add(cliente)
    elif cliente_nombre and not cliente.nombre:
        cliente.nombre = cliente_nombre

    await db.commit()
    await db.refresh(cita)
    return cita


async def update_cita_estado(
    db: AsyncSession, cita_id: int, estado: str, **kwargs
) -> Optional[Cita]:
    """Actualiza el estado de una cita y cualquier campo adicional pasado como kwargs."""
    res = await db.execute(select(Cita).where(Cita.id == cita_id))
    cita = res.scalar_one_or_none()
    if cita:
        cita.estado = estado
        cita.updated_at = datetime.utcnow()
        for key, value in kwargs.items():
            if hasattr(cita, key):
                setattr(cita, key, value)
        await db.commit()
        await db.refresh(cita)
    return cita


# ============================================================
# GENERACIÓN DE RESPUESTAS CONVERSACIONALES (OPENAI + CLIENT SYSTEM PROMPT)
# ============================================================

def _fallback_client_reply(state: Dict[str, Any], message: str) -> str:
    """Respuesta de respaldo cuando OpenAI no está disponible."""
    text_low = message.lower().strip()

    # 1. Saludos puros
    if any(k in text_low for k in ("hola", "buenos dias", "buenas tardes", "buenas noches", "buenas", "hi", "hey")):
        if not any(k in text_low for k in ("precio", "costo", "cuanto", "cuánto", "cita", "reserva", "horario", "botox", "keratina", "uñas", "pestañas", "seco", "dañado", "frizz", "servicios", "catalogo", "catálogo")):
            return "¡Hola! 💕 Bienvenida a Glowlab. ¿En qué te podemos ayudar hoy? ✨"

    # 2. Lista general de servicios / catálogo (Sección 8 y 10)
    if any(k in text_low for k in ("servicios", "catálogo", "catalogo", "que tienen", "qué tienen", "tratamientos", "opciones", "hacen")):
        return list_services()

    # 3. Recomendación capilar (Sección 9)
    if any(k in text_low for k in ("seco", "dañado", "frizz", "que me recomiendas", "qué me recomiendas", "maltratado", "caida", "brillo")):
        return (
            "Claro 😊 Si buscas mejorar la hidratación y suavidad del cabello, podemos considerar un tratamiento de hidratación (S/ 80) o botox capilar (S/ 120).\n"
            "Si además buscas un efecto más intenso de control de frizz y restauración, el tratamiento de keratina (S/ 160) es excelente.\n\n"
            "Si quieres, cuéntame cómo tienes actualmente el cabello y te puedo orientar mejor. ✨"
        )

    # 4. Consulta por precio o servicio específico (Sección 11)
    for cat, services in SERVICE_CATALOG.items():
        for svc_item in services:
            svc_name_low = svc_item["name"].lower()
            if svc_name_low in text_low or (len(svc_name_low) > 4 and svc_name_low in text_low):
                price = svc_item.get("price", 0)
                desc = svc_item.get("desc", "")
                if price:
                    return (
                        f"El {svc_item['name']} tiene un precio de S/ {price}. ✨\n"
                        f"{desc}.\n"
                        f"Si deseas, también puedo ayudarte a revisar horarios disponibles para realizarlo. 😊"
                    )
                else:
                    return (
                        f"El servicio de {svc_item['name']} está disponible en Glowlab. ✨\n"
                        f"{desc}.\n"
                        f"Si deseas, puedo orientarte con más información o disponibilidad. 😊"
                    )

    # Coincidencia por palabra clave de servicio si no se encontró el nombre completo
    for kw in sorted(SERVICE_TO_ADVISOR.keys(), key=len, reverse=True):
        if kw in text_low and len(kw) > 3:
            price_msg = get_service_price(kw)
            if price_msg:
                return price_msg

    # 5. Agendamiento explícito (Sección 6 y 7)
    if any(k in text_low for k in ("cita", "agendar", "reservar", "separar", "horarios")):
        if not state.get("servicio"):
            return "¡Claro! 😊 ¿Qué servicio deseas realizarte?"
        if not state.get("fecha"):
            return f"¡Perfecto! 😊 Para *{state['servicio']}*, ¿qué día te viene mejor?"

    # 6. Respuesta por defecto
    return (
        "¡Hola! ✨ En Glowlab ofrecemos servicios de pestañas (lashista), uñas (pintado y diseños) y tratamientos capilares (hidratación, keratina, botox capilar e hidratación express).\n\n"
        "Cuéntame qué información necesitas o en qué podemos asesorarte hoy. 💕"
    )


async def generate_client_reply(
    state: Dict[str, Any],
    message: str,
    extra_context: str = "",
) -> str:
    """
    Genera una respuesta conversacional natural, cálida y profesional para la clienta usando
    OpenAI y el CLIENT_SYSTEM_PROMPT oficial de Glowlab (25 secciones).
    """
    if not settings.OPENAI_API_KEY:
        reply = _fallback_client_reply(state, message)
        history = state.get("history", [])
        history.append({"role": "user", "content": message})
        history.append({"role": "assistant", "content": reply})
        state["history"] = history[-10:]
        return reply

    today = date.today()
    today_formatted = format_fecha_es(today)

    system_content = f"{CLIENT_SYSTEM_PROMPT}\n\n"
    system_content += "--- INFORMACIÓN DEL SISTEMA EN TIEMPO REAL ---\n"
    system_content += f"• Fecha actual: {today_formatted} ({today.strftime('%Y-%m-%d')})\n"

    if state.get("nombre"):
        system_content += f"• Nombre de la clienta: {state['nombre']}\n"
    if state.get("servicio"):
        system_content += f"• Servicio mencionado/en curso: {state['servicio']}\n"
    if state.get("fecha"):
        system_content += f"• Fecha mencionada/en curso: {state['fecha']}\n"
    if state.get("hora"):
        system_content += f"• Hora seleccionada: {state['hora']}\n"
    if extra_context:
        system_content += f"• Datos consultados en el sistema / Disponibilidad verificada:\n{extra_context}\n"

    history: List[Dict[str, str]] = state.get("history", [])

    messages = [{"role": "system", "content": system_content}]
    for msg in history[-8:]:
        if isinstance(msg, dict) and msg.get("role") in ("user", "assistant") and msg.get("content"):
            messages.append({"role": msg["role"], "content": msg["content"]})

    messages.append({"role": "user", "content": message})

    payload = {
        "model": settings.OPENAI_MODEL,
        "messages": messages,
        "temperature": 0.45,
        "max_tokens": 450,
    }

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
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
                history.append({"role": "user", "content": message})
                history.append({"role": "assistant", "content": reply})
                state["history"] = history[-10:]
                return reply
    except Exception as e:
        logger.warning(f"Error generando respuesta clienta con OpenAI: {e}")

    reply = _fallback_client_reply(state, message)
    history.append({"role": "user", "content": message})
    history.append({"role": "assistant", "content": reply})
    state["history"] = history[-10:]
    return reply


# ============================================================
# EXTRACCIÓN DE INTENCIÓN (OPENAI)
# ============================================================

async def extract_intent(state: Dict[str, Any], message: str) -> Dict[str, Any]:
    """
    Usa OpenAI para extraer intención y entidades del mensaje de la clienta,
    respetando la jerarquía de intenciones del System Prompt (Secciones 2, 3 y 5).
    """
    if not settings.OPENAI_API_KEY:
        return _keyword_extract(message)

    ctx = f"Estado: {state.get('paso', 'inicial')}"
    if state.get("servicio"):
        ctx += f" | Servicio: {state['servicio']}"
    if state.get("fecha"):
        ctx += f" | Fecha: {state['fecha']}"

    system = (
        "Eres un analizador de intenciones de WhatsApp para el salón de belleza Glowlab.\n"
        "Reglas para clasificar 'intent':\n"
        "- 'consultar': si la clienta pregunta precios, qué incluye un servicio, pide recomendación, tiene dudas o compara servicios (ej: 'cuánto cuesta el botox', 'tengo el pelo seco qué me recomiendas', 'qué servicios tienen'). NO lo clasifiques como 'agendar' a menos que explícitamente exprese intención de reservar/agendar.\n"
        "- 'agendar': SOLO si la clienta manifiesta intención clara de reservar o consultar disponibilidad (ej: 'quiero sacar cita', 'quiero reservar', '¿tienen disponibilidad el sábado?', 'qué horarios tienen', 'quiero agendar para mañana').\n"
        "- 'saludo': si solo saluda sin hacer una pregunta específica ni pedir servicio.\n"
        "- 'confirmar': si confirma datos o cita ('sí', 'confirmo', 'de acuerdo', 'está bien', 'dale').\n"
        "- 'rechazar': si cancela o rechaza opción ('no', 'cambiar', 'otro').\n"
        "- 'cancelar': si pide anular todo el proceso.\n"
        "- 'excepcion': si pide no pagar adelanto o solicita caso especial.\n"
        "- 'otro': conversación general.\n\n"
        "Responde ÚNICAMENTE con JSON válido con estas claves:\n"
        "{\n"
        "  \"intent\": \"consultar\" | \"agendar\" | \"saludo\" | \"confirmar\" | \"rechazar\" | \"cancelar\" | \"excepcion\" | \"otro\",\n"
        "  \"servicio\": string o null (ej: 'botox capilar', 'keratina', 'uñas pintado', 'extensiones naturales'),\n"
        "  \"fecha\": string o null (ej: 'sábado', 'mañana', '15/08', 'YYYY-MM-DD'),\n"
        "  \"hora\": string o null (ej: 'mañana', 'tarde', '10am', '3pm', '16:00'),\n"
        "  \"slot_num\": entero o null (si elige opción numerada como 1, 2),\n"
        "  \"requiere_excepcion\": boolean\n"
        "}"
    )

    payload = {
        "model": settings.OPENAI_MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": f"{ctx}\nMensaje: {message}"},
        ],
        "temperature": 0.1,
        "max_tokens": 250,
        "response_format": {"type": "json_object"},
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            res = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {settings.OPENAI_API_KEY}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            if res.status_code == 200:
                data = res.json()["choices"][0]["message"]["content"]
                return json.loads(data)
    except Exception as e:
        logger.warning(f"Error extrayendo intención con OpenAI: {e}")

    return _keyword_extract(message)


def _keyword_extract(message: str) -> Dict[str, Any]:
    """Extracción de intención por palabras clave (fallback sin IA)."""
    s = message.lower()

    # Prioridad: consultas informativas primero (Regla 2 y 3)
    if any(k in s for k in ("precio", "costo", "cuánto", "cuanto", "vale", "cobran", "información", "informacion", "qué incluye", "que incluye", "recomiendas", "recomendación", "seco", "dañado", "frizz", "diferencia", "servicios", "catálogo", "catalogo")):
        intent = "consultar"
    elif any(k in s for k in ("cita", "agendar", "reservar", "turno", "separar", "disponibilidad", "horarios", "quiero reservar", "sacar cita")):
        intent = "agendar"
    elif any(k in s for k in ("cancelar", "anular", "cancel")):
        intent = "cancelar"
    elif any(k in s for k in ("sí", "si", "ok", "dale", "perfecto", "confirmo", "claro", "yes", "de acuerdo", "va")):
        intent = "confirmar"
    elif any(k in s for k in ("no", "nop", "otro", "cambiar", "diferente")):
        intent = "rechazar"
    elif any(k in s for k in ("sin adelanto", "no puedo pagar", "excepcion", "excepción", "caso especial")):
        intent = "excepcion"
    elif any(k in s for k in ("hola", "buenos", "buenas", "hi", "saludos", "start", "menu")):
        intent = "saludo"
    else:
        intent = "otro"

    # Número de slot seleccionado
    slot_num = None
    for i in range(1, 10):
        if f" {i} " in f" {s} " or s.strip() == str(i):
            slot_num = i
            break

    # Servicio mencionado (ordenar por longitud descendente para encontrar el más específico)
    servicio = None
    for kw in sorted(SERVICE_TO_ADVISOR.keys(), key=len, reverse=True):
        if kw in s:
            servicio = kw
            break

    # Fecha mencionada
    fecha = None
    for fkw in ("hoy", "mañana", "manana", "pasado mañana", "lunes", "martes", "miercoles", "miércoles", "jueves", "viernes", "sabado", "sábado", "domingo"):
        if fkw in s:
            fecha = fkw
            break

    return {
        "intent": intent,
        "servicio": servicio,
        "fecha": fecha,
        "hora": None,
        "slot_num": slot_num,
        "requiere_excepcion": "excepcion" in intent or "sin adelanto" in s or "no puedo pagar" in s,
    }


# ============================================================
# VALIDACIÓN DE VOUCHER (OPENAI VISION)
# ============================================================

async def validate_voucher(image_base64: str) -> Tuple[bool, str]:
    """
    Valida un comprobante de pago usando OpenAI Vision.
    Verifica monto de S/20, fecha reciente y que sea un comprobante válido.
    """
    if not settings.OPENAI_API_KEY:
        # Sin IA, aprobamos optimistamente para no bloquear
        return True, "Aprobado automáticamente (sin validación IA)"

    expected = settings.ADVANCE_AMOUNT
    prompt = (
        f"Analiza este comprobante de pago y verifica:\n"
        f"1. ¿El monto es de S/ {expected}?\n"
        f"2. ¿La fecha es de hoy o ayer?\n"
        f"3. ¿Es un comprobante real de Yape, Plin, transferencia o depósito?\n"
        f"Responde SOLO con JSON: {{\"valido\": true/false, \"motivo\": \"explicación breve\"}}"
    )

    payload = {
        "model": "gpt-4o-mini",
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{image_base64}"},
                    },
                ],
            }
        ],
        "max_tokens": 120,
    }

    try:
        async with httpx.AsyncClient(timeout=25.0) as client:
            res = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {settings.OPENAI_API_KEY}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            if res.status_code == 200:
                raw = res.json()["choices"][0]["message"]["content"]
                result = json.loads(raw)
                return result.get("valido", False), result.get("motivo", "")
    except Exception as e:
        logger.error(f"Error validando voucher con OpenAI Vision: {e}")

    # Si falla la IA, no bloqueamos: aprobamos y el staff verifica manualmente
    return True, "Aprobado (validación manual requerida)"


# ============================================================
# CLIENTE EVOLUTION API (ENVÍO DE MENSAJES)
# ============================================================

async def send_message(number: str, text: str) -> bool:
    """Envía un mensaje de texto a través de Evolution API."""
    url = f"{settings.EVOLUTION_API_URL.rstrip('/')}/message/sendText/{settings.EVOLUTION_INSTANCE_NAME}"
    headers = {
        "apikey": settings.EVOLUTION_API_KEY,
        "Content-Type": "application/json",
    }
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            res = await client.post(url, headers=headers, json={"number": number, "text": text})
            return res.status_code in (200, 201)
    except Exception as e:
        logger.error(f"Error enviando mensaje a {number}: {e}")
        return False


async def get_media_base64(item: Dict[str, Any]) -> Optional[str]:
    """Descarga el contenido de un mensaje multimedia como base64 desde Evolution API."""
    url = (
        f"{settings.EVOLUTION_API_URL.rstrip('/')}"
        f"/chat/getBase64FromMediaMessage/{settings.EVOLUTION_INSTANCE_NAME}"
    )
    headers = {
        "apikey": settings.EVOLUTION_API_KEY,
        "Content-Type": "application/json",
    }
    try:
        async with httpx.AsyncClient(timeout=25.0) as client:
            res = await client.post(
                url,
                headers=headers,
                json={"message": {"key": item.get("key", {}), "message": item.get("message", {})}},
            )
            if res.status_code == 200:
                data = res.json()
                return data.get("base64") or data.get("data", {}).get("base64")
    except Exception as e:
        logger.error(f"Error obteniendo media base64: {e}")
    return None


async def notify_advisor(advisor: str, text: str) -> None:
    """Envía un mensaje de notificación a una asesora específica (uso interno)."""
    phone = STAFF_PHONES.get(advisor)
    if phone:
        await send_message(phone, text)


async def notify_all_staff(text: str) -> None:
    """Envía una notificación a todas las asesoras del equipo."""
    for phone in STAFF_PHONES.values():
        await send_message(phone, text)


# ============================================================
# MENSAJES PREDEFINIDOS
# ============================================================

def build_slots_message(slots: List[str], fecha_es: str) -> str:
    """Construye el mensaje con la lista de horarios disponibles."""
    lines = [f"Horarios disponibles el *{fecha_es}*:\n"]
    for i, slot in enumerate(slots, 1):
        lines.append(f"{i}. {format_hora_12h(slot)}")
    lines.append("\n¿Cuál prefieres?")
    return "\n".join(lines)


def build_summary_message(state: Dict[str, Any]) -> str:
    """Construye el resumen de la cita antes de confirmar."""
    try:
        d = datetime.strptime(state["fecha"], "%Y-%m-%d").date()
        fecha_es = format_fecha_es(d)
    except Exception:
        fecha_es = state.get("fecha", "")

    return (
        f"📋 *Resumen de tu cita:*\n"
        f"💅 Servicio: {state.get('servicio', '')}\n"
        f"📆 Fecha: {fecha_es}\n"
        f"⏰ Hora: {format_hora_12h(state.get('hora', ''))}\n\n"
        f"¿Confirmamos? Responde *Sí* o *No*."
    )


def build_advance_message() -> str:
    """Mensaje explicando la política de adelanto."""
    return (
        f"Para confirmar tu cita se requiere un adelanto de *S/ {settings.ADVANCE_AMOUNT}*.\n\n"
        f"📲 {settings.PAYMENT_INFO}\n\n"
        f"Envíanos la imagen del comprobante cuando lo hayas realizado. 🙌"
    )


def build_confirmation_message(state: Dict[str, Any]) -> str:
    """Mensaje de confirmación final enviado a la clienta."""
    try:
        d = datetime.strptime(state["fecha"], "%Y-%m-%d").date()
        fecha_es = format_fecha_es(d)
    except Exception:
        fecha_es = state.get("fecha", "")

    return (
        f"✅ *¡Cita confirmada!*\n\n"
        f"💅 {state.get('servicio', '')}\n"
        f"📆 {fecha_es} a las {format_hora_12h(state.get('hora', ''))}\n\n"
        f"Si necesitas cambiar algo, escríbenos con anticipación. ¡Te esperamos! 🌸"
    )


def build_staff_notification(state: Dict[str, Any], sender_number: str) -> str:
    """Notificación interna enviada a la asesora asignada."""
    try:
        d = datetime.strptime(state["fecha"], "%Y-%m-%d").date()
        fecha_es = format_fecha_es(d)
    except Exception:
        fecha_es = state.get("fecha", "")

    adelanto_status = "✅ Pagado" if state.get("adelanto_validado") else "⏳ Pendiente"

    return (
        f"🔔 *Nueva cita - Glowlab*\n\n"
        f"👤 Clienta: {state.get('nombre') or 'Sin nombre'}\n"
        f"📱 WhatsApp: +{sender_number}\n"
        f"💅 Servicio: {state.get('servicio', '')}\n"
        f"📆 {fecha_es} a las {format_hora_12h(state.get('hora', ''))}\n"
        f"💰 Adelanto: {adelanto_status}\n"
        f"🆔 Cita #{state.get('cita_id', 'N/A')}"
    )


def build_reminder_message(cita: "Cita") -> str:
    """Mensaje de recordatorio de cita (24h o 2h antes)."""
    try:
        d = datetime.strptime(cita.fecha, "%Y-%m-%d").date()
        fecha_es = format_fecha_es(d)
    except Exception:
        fecha_es = cita.fecha or ""

    return (
        f"📅 *Recordatorio - Glowlab*\n\n"
        f"Hola, te recordamos tu cita:\n"
        f"💅 {cita.servicio}\n"
        f"📆 {fecha_es} a las {format_hora_12h(cita.hora or '')}\n\n"
        f"Si necesitas reagendar, escríbenos con anticipación. ¡Te esperamos! 🌸"
    )


# Mensajes de seguimiento post-servicio por especialidad
_FOLLOWUP: Dict[str, str] = {
    "unas": (
        "✨ ¡Gracias por visitarnos en *Glowlab*!\n\n"
        "Para mantener tus uñas perfectas:\n"
        "• Usa guantes al lavar 🧤\n"
        "• Hidrata tu cutícula diariamente\n"
        "• Evita usarlas como herramienta\n\n"
        "¡Esperamos verte pronto! 💅"
    ),
    "pestanas": (
        "✨ ¡Gracias por tu visita a *Glowlab*!\n\n"
        "Cuidados para tus pestañas:\n"
        "• Evita mojarlas las primeras 24h 💧\n"
        "• No uses máscara de pestañas\n"
        "• Péinalas suavemente cada mañana\n\n"
        "¡Luzcan esos ojos! 👁️"
    ),
    "capilar": (
        "✨ ¡Gracias por tu visita a *Glowlab*!\n\n"
        "Recomendaciones para tu cabello:\n"
        "• Usa el shampoo indicado 🧴\n"
        "• Evita calor excesivo esta semana\n"
        "• Hidrata con mascarilla semanal\n\n"
        "¡Nos vemos pronto! 🌟"
    ),
}


def build_followup_message(cita: "Cita") -> str:
    """Selecciona el mensaje de seguimiento según el servicio realizado."""
    s = (cita.servicio or "").lower()
    if any(k in s for k in ("pestaña", "pestana", "extension", "lash")):
        return _FOLLOWUP["pestanas"]
    if any(k in s for k in ("capilar", "cabello", "alisado", "tinte", "tratamiento",
                             "keratina", "botox", "mechas", "corte", "hidratacion")):
        return _FOLLOWUP["capilar"]
    return _FOLLOWUP["unas"]


# ============================================================
# TAREA DE RECORDATORIOS (llamada por APScheduler)
# ============================================================

async def run_reminder_check() -> None:
    """
    Verifica y envía recordatorios pendientes.
    Ejecutar cada hora desde el scheduler en main.py.
    """
    from app.core.database import async_session_factory

    try:
        async with async_session_factory() as db:
            now = datetime.utcnow()

            # --- Recordatorio 24 horas antes ---
            target_24h = (now + timedelta(hours=24)).strftime("%Y-%m-%d")
            result = await db.execute(
                select(Cita).where(
                    and_(
                        Cita.fecha == target_24h,
                        Cita.estado == "confirmada",
                        Cita.recordatorio_24h_enviado.is_(False),
                    )
                )
            )
            for cita in result.scalars().all():
                await send_message(cita.cliente_phone, build_reminder_message(cita))
                cita.recordatorio_24h_enviado = True
                logger.info(f"Recordatorio 24h enviado → cita #{cita.id}")

            # --- Recordatorio 2 horas antes ---
            from_time = (now + timedelta(hours=2)).strftime("%H:00")
            today_str = now.strftime("%Y-%m-%d")
            result2 = await db.execute(
                select(Cita).where(
                    and_(
                        Cita.fecha == today_str,
                        Cita.hora == from_time,
                        Cita.estado == "confirmada",
                        Cita.recordatorio_2h_enviado.is_(False),
                    )
                )
            )
            for cita in result2.scalars().all():
                await send_message(cita.cliente_phone, build_reminder_message(cita))
                cita.recordatorio_2h_enviado = True
                logger.info(f"Recordatorio 2h enviado → cita #{cita.id}")

            # --- Seguimiento post-servicio (completadas ayer) ---
            yesterday = (now - timedelta(days=1)).strftime("%Y-%m-%d")
            result3 = await db.execute(
                select(Cita).where(
                    and_(
                        Cita.fecha == yesterday,
                        Cita.estado == "completada",
                        Cita.seguimiento_enviado.is_(False),
                    )
                )
            )
            for cita in result3.scalars().all():
                await send_message(cita.cliente_phone, build_followup_message(cita))
                cita.seguimiento_enviado = True
                logger.info(f"Seguimiento post-servicio enviado → cita #{cita.id}")

            await db.commit()

    except Exception as e:
        logger.error(f"Error en run_reminder_check: {e}", exc_info=True)
