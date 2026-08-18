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
import asyncio
import json
import logging
import re
import time
import uuid
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo  # type: ignore

import httpx
from sqlalchemy import and_, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import async_session_factory
from app.modules.salon.models import Cita, Cliente, Conversacion, OpenAIUsageLog, Tenant, Service, StaffMember, ServiceFollowup

from app.modules.salon.prompts import CLIENT_SYSTEM_PROMPT, build_tenant_system_prompt, DEFAULT_GLOWLAB_CATALOG

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

# Servicios oficiales del catálogo (solo estos nombres pueden guardarse en el campo servicio)
OFFICIAL_SERVICES: Dict[str, str] = {
    # Capilares
    "botox capilar": "botox capilar",
    "botox": "botox capilar",
    "tratamiento de keratina": "keratina",
    "keratina": "keratina",
    "tratamiento de hidratación": "tratamiento de hidratación",
    "tratamiento de hidratacion": "tratamiento de hidratación",
    "hidratación express": "hidratación express",
    "hidratacion express": "hidratación express",
    "hidratación": "tratamiento de hidratación",
    "hidratacion": "tratamiento de hidratación",
    # Pestañas
    "extensiones naturales": "pestañas",
    "extensiones más definidas": "pestañas",
    "extensiones mas definidas": "pestañas",
    "estilo a medida": "pestañas",
    "extensiones de pestañas": "pestañas",
    "extensiones de pestanas": "pestañas",
    "pestañas": "pestañas",
    "pestanas": "pestañas",
    # Uñas
    "diseños y decoración": "uñas",
    "diseños y decoracion": "uñas",
    "diseño y decoración": "uñas",
    "diseño y decoracion": "uñas",
    "pintado de uñas": "uñas",
    "pintado": "uñas",
    "uñas": "uñas",
    "unas": "uñas",
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
SESSION_TIMEOUT_SECONDS = 3 * 3600  # 3 horas (10,800 segundos)

INTERACTIVE_MENU_MESSAGE = (
    "¡Hola! ✨ Bienvenida a Glowlab. \n"
    "Para brindarte una mejor atención, te invitamos a elegir una de las siguientes opciones:\n"
    "1️⃣ Asistente virtual: Para ver servicios, consultar precios y agendar tu cita de forma automática y rápida.\n"
    "2️⃣ Atención personalizada: Para consultas directas, dudas específicas o asesoría detallada.\n"
    "¿Qué opción elijes? Responde con el número."
)

HUMAN_ADVISOR_CONFIRMATION_MESSAGE = (
    "¡Perfecto! Un asesor se comunicará contigo en breve para brindarte atención personalizada. 🌸"
)

MENU_INVALID_OPTION_MESSAGE = (
    "Por favor, elige una de las siguientes opciones respondiendo con el número:\n\n"
    "1️⃣ Asistente virtual: Para ver servicios, consultar precios y agendar tu cita de forma automática y rápida.\n"
    "2️⃣ Atención personalizada: Para consultas directas, dudas específicas o asesoría detallada."
)


# ============================================================
# ============================================================
# CATÁLOGO DE SERVICIOS Y CONFIGURACIÓN DINÁMICA MULTI-TENANT
# ============================================================

SERVICE_CATALOG: Dict[str, List[Dict[str, Any]]] = {
    "Pestañas": [
        {"name": "Extensiones naturales", "desc": "Look natural y sutil realizado por lashista", "price": 80, "price_prefix": "desde", "duration_minutes": 60},
        {"name": "Extensiones más definidas", "desc": "Mayor volumen y definición en tu mirada", "price": 100, "price_prefix": "desde", "duration_minutes": 60},
        {"name": "Estilo a medida", "desc": "Diseño personalizado según tu estilo", "price": 50, "price_prefix": "desde", "duration_minutes": 60},
    ],
    "Uñas": [
        {"name": "Pintado", "desc": "Pintado tradicional o semipermanente de uñas", "price": 30, "price_prefix": "desde", "duration_minutes": 30},
        {"name": "Diseños y decoración", "desc": "Arte y decoración personalizada en uñas", "price": 45, "price_prefix": "desde", "duration_minutes": 45},
        {"name": "Otros servicios de uñas", "desc": "Servicios especiales de uñas disponibles en catálogo", "price": 0, "duration_minutes": 30},
    ],
    "Tratamientos capilares": [
        {"name": "Tratamiento de hidratación", "desc": "Nutrición y suavidad profunda para el cabello", "price": 80, "duration_minutes": 60},
        {"name": "Tratamiento de keratina", "desc": "Control de frizz, alisado y restauración capilar", "price": 160, "duration_minutes": 90},
        {"name": "Botox capilar", "desc": "Mejora la apariencia, suavidad y brillo del cabello", "price": 120, "duration_minutes": 60},
        {"name": "Hidratación express", "desc": "Tratamiento rápido de hidratación y brillo", "price": 50, "duration_minutes": 30},
    ],
}

# Caché en memoria para perfiles y catálogos de tenants
_tenant_cache: Dict[str, Dict[str, Any]] = {}


async def get_tenant_profile(tenant_id: str = "glowlab") -> Dict[str, Any]:
    """Obtiene el perfil, rubro, etiquetas y reglas de un tenant desde PostgreSQL o memoria."""
    tenant_profile = {
        "slug": tenant_id,
        "name": "Glowlab Salón" if tenant_id == "glowlab" else tenant_id.title(),
        "industry": "un salón de belleza" if tenant_id == "glowlab" else "un centro de atención profesional",
        "entity_labels": {
            "customer": "clienta",
            "customer_plural": "clientas",
            "staff": "asesora",
            "staff_plural": "asesoras",
            "item": "servicio",
            "item_plural": "servicios",
            "booking": "cita",
            "booking_plural": "citas",
        },
        "requires_deposit": True,
        "deposit_amount": 20.0,
        "currency": "PEN",
        "slot_interval_minutes": 60,
        "plan_name": "pro" if tenant_id == "glowlab" else "starter",
        "max_appointments_per_month": 500 if tenant_id == "glowlab" else 100,
        "max_ai_cost_usd_per_month": 50.0 if tenant_id == "glowlab" else 15.0,
        "billing_cycle_day": 1,
    }

    try:
        async with async_session_factory() as db:
            res = await db.execute(select(Tenant).where(Tenant.slug == tenant_id))
            t = res.scalar_one_or_none()
            if t:
                tenant_profile["name"] = t.name
                tenant_profile["industry"] = t.industry
                if hasattr(t, "plan_name") and t.plan_name:
                    tenant_profile["plan_name"] = t.plan_name
                if hasattr(t, "max_appointments_per_month") and t.max_appointments_per_month is not None:
                    tenant_profile["max_appointments_per_month"] = int(t.max_appointments_per_month)
                if hasattr(t, "max_ai_cost_usd_per_month") and t.max_ai_cost_usd_per_month is not None:
                    tenant_profile["max_ai_cost_usd_per_month"] = float(t.max_ai_cost_usd_per_month)
                if hasattr(t, "billing_cycle_day") and t.billing_cycle_day is not None:
                    tenant_profile["billing_cycle_day"] = int(t.billing_cycle_day)

                stg = t.settings or {}
                if "plan_name" in stg:
                    tenant_profile["plan_name"] = stg["plan_name"]
                if "max_appointments_per_month" in stg:
                    tenant_profile["max_appointments_per_month"] = int(stg["max_appointments_per_month"])
                if "max_ai_cost_usd_per_month" in stg:
                    tenant_profile["max_ai_cost_usd_per_month"] = float(stg["max_ai_cost_usd_per_month"])
                if "billing_cycle_day" in stg:
                    tenant_profile["billing_cycle_day"] = int(stg["billing_cycle_day"])

                if "entity_labels" in stg:
                    tenant_profile["entity_labels"].update(stg["entity_labels"])
                if "requires_deposit" in stg:
                    tenant_profile["requires_deposit"] = stg["requires_deposit"]
                if "deposit_amount" in stg:
                    tenant_profile["deposit_amount"] = float(stg["deposit_amount"])
                if "slot_interval_minutes" in stg:
                    tenant_profile["slot_interval_minutes"] = int(stg["slot_interval_minutes"])
    except Exception as e:
        logger.debug(f"Aviso leyendo perfil de tenant '{tenant_id}': {e}")

    return tenant_profile


async def get_tenant_catalog(tenant_id: str = "glowlab") -> Dict[str, List[Dict[str, Any]]]:
    """Obtiene el catálogo de servicios de un tenant desde PostgreSQL con fallback seguro."""
    try:
        async with async_session_factory() as db:
            res = await db.execute(
                select(Service).where(Service.tenant_id == tenant_id, Service.is_active == True).order_by(Service.category, Service.price.asc())
            )
            services = res.scalars().all()
            if services:
                catalog: Dict[str, List[Dict[str, Any]]] = {}
                for s in services:
                    catalog.setdefault(s.category, []).append({
                        "id": s.id,
                        "name": s.name,
                        "desc": s.description or "",
                        "price": float(s.price),
                        "price_prefix": s.price_prefix or "",
                        "duration_minutes": s.duration_minutes or 60,
                    })
                return catalog
    except Exception as e:
        logger.debug(f"Aviso leyendo catálogo de BD para '{tenant_id}': {e}")

    if tenant_id == "glowlab":
        return SERVICE_CATALOG
    return {}


async def get_tenant_staff(tenant_id: str = "glowlab") -> List[Dict[str, Any]]:
    """Obtiene el personal registrado para un tenant."""
    try:
        async with async_session_factory() as db:
            res = await db.execute(
                select(StaffMember).where(StaffMember.tenant_id == tenant_id, StaffMember.is_active == True)
            )
            staff = res.scalars().all()
            if staff:
                return [
                    {
                        "name": sm.name,
                        "phone": sm.phone,
                        "role": sm.role,
                        "skills": sm.skills or [],
                    }
                    for sm in staff
                ]
    except Exception as e:
        logger.debug(f"Aviso leyendo staff de BD para '{tenant_id}': {e}")

    if tenant_id == "glowlab":
        return [
            {"name": "Lizbeth", "phone": "51992509246", "role": "lashista", "skills": ["pestañas", "uñas"]},
            {"name": "Anali", "phone": "51925528059", "role": "estilista", "skills": ["capilar", "botox", "keratina", "hidratación"]},
        ]
    return []


def get_service_price(service_name: str, tenant_id: str = "glowlab") -> Optional[str]:
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
    """
    Convierte texto en lenguaje natural o formatos estándar a un objeto date.
    Jerarquía de prioridad:
    1. Fechas explícitas completas con nombre de mes (ej. '21 de agosto', 'el viernes 21 de agosto').
    2. Formatos numéricos estándar (ej. '2026-08-21', '21/08/2026', '21/08').
    3. Día de semana + Número de día (ej. 'viernes 21', 'martes 18', 'el 21', 'para el 21').
    4. Palabras clave relativas ('hoy', 'mañana', 'pasado mañana').
    5. Día de la semana solo (ej. 'este viernes', 'el próximo lunes' - sin número de día).
    """
    if not text:
        return None

    today = date.today()
    s = text.lower().strip()

    month_names = {
        "enero": 1, "febrero": 2, "marzo": 3, "abril": 4,
        "mayo": 5, "junio": 6, "julio": 7, "agosto": 8,
        "setiembre": 9, "septiembre": 9, "octubre": 10,
        "noviembre": 11, "diciembre": 12,
    }

    # 1. Fechas con nombre de mes explícito: ej. '21 de agosto', 'viernes 21 de agosto', '21 de agosto de 2026'
    month_regex = r'(?:el\s+)?(?:lunes|martes|mi[eé]rcoles|jueves|viernes|s[aá]bado|domingo)?\s*(\d{1,2})\s+de\s+(' + '|'.join(month_names.keys()) + r')(?:\s+(?:de|del)?\s*(\d{4}))?'
    m_match = re.search(month_regex, s)
    if m_match:
        day_num = int(m_match.group(1))
        m_name = m_match.group(2)
        month_num = month_names.get(m_name, today.month)
        year_num = int(m_match.group(3)) if m_match.group(3) else today.year
        try:
            target = date(year_num, month_num, day_num)
            if not m_match.group(3) and target < today:
                target = date(year_num + 1, month_num, day_num)
            return target
        except ValueError:
            pass

    # 2. Formatos numéricos estándar: '2026-08-21', '21/08/2026', '21-08-2026'
    num_match = re.search(r'\b(\d{4})[-/](\d{1,2})[-/](\d{1,2})\b', s)
    if num_match:
        try:
            return date(int(num_match.group(1)), int(num_match.group(2)), int(num_match.group(3)))
        except ValueError:
            pass

    num_match_dmy = re.search(r'\b(\d{1,2})[-/](\d{1,2})[-/](\d{4})\b', s)
    if num_match_dmy:
        try:
            return date(int(num_match_dmy.group(3)), int(num_match_dmy.group(2)), int(num_match_dmy.group(1)))
        except ValueError:
            pass

    num_match_short = re.search(r'\b(\d{1,2})[-/](\d{1,2})\b', s)
    if num_match_short:
        try:
            d_val = int(num_match_short.group(1))
            m_val = int(num_match_short.group(2))
            res = date(today.year, m_val, d_val)
            if res < today:
                res = date(today.year + 1, m_val, d_val)
            return res
        except ValueError:
            pass

    # 3. Día de semana + Número de día o 'el <día>': ej. 'viernes 21', 'el viernes 21', 'martes 18', 'para el 21', 'el 21'
    day_num_match = re.search(r'(?:el\s+)?(?:lunes|martes|mi[eé]rcoles|jueves|viernes|s[aá]bado|domingo)\s+(\d{1,2})\b', s)
    if not day_num_match:
        day_num_match = re.search(r'(?:para\s+el|el)\s+(\d{1,2})\b', s)

    if day_num_match:
        target_day = int(day_num_match.group(1))
        if 1 <= target_day <= 31:
            try:
                target = date(today.year, today.month, target_day)
                if target < today:
                    next_month = today.month + 1 if today.month < 12 else 1
                    next_year = today.year if today.month < 12 else today.year + 1
                    target = date(next_year, next_month, target_day)
                return target
            except ValueError:
                pass

    # 4. Palabras clave relativas
    if "pasado mañana" in s or "pasado manana" in s:
        return today + timedelta(days=2)
    if "mañana" in s or "manana" in s:
        return today + timedelta(days=1)
    if re.search(r'\bhoy\b', s):
        return today

    # 5. Día de la semana solo (sin número de día)
    day_map = {
        "lunes": 0, "martes": 1,
        "miercoles": 2, "miércoles": 2,
        "jueves": 3, "viernes": 4,
        "sabado": 5, "sábado": 5, "domingo": 6,
    }
    for name, num in day_map.items():
        if re.search(r'\b' + name + r'\b', s):
            ahead = num - today.weekday()
            if ahead <= 0:
                ahead += 7
            return today + timedelta(days=ahead)


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
# GESTIÓN DE ESTADO CONVERSACIONAL (REDIS + POSTGRESQL)
# ============================================================

def normalize_phone(phone: str) -> str:
    """Normaliza un número telefónico conservando solo los dígitos numéricos."""
    return "".join(filter(str.isdigit, str(phone)))


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


_in_memory_state: Dict[str, Dict[str, Any]] = {}
_in_memory_phone_locks: Dict[str, asyncio.Lock] = {}

# Script Lua para liberación segura y atómica del lock en Redis
_RELEASE_LOCK_LUA = """
if redis.call("get", KEYS[1]) == ARGV[1] then
    return redis.call("del", KEYS[1])
else
    return 0
end
"""


def _get_in_memory_phone_lock(phone_norm: str, tenant_id: str = "glowlab") -> asyncio.Lock:
    """Obtiene o crea un asyncio.Lock local para el número de teléfono y tenant especificado."""
    key = f"{tenant_id}:{phone_norm}"
    if key not in _in_memory_phone_locks:
        _in_memory_phone_locks[key] = asyncio.Lock()
    return _in_memory_phone_locks[key]


@asynccontextmanager
async def phone_distributed_lock(
    phone: str,
    tenant_id: str = "glowlab",
    ttl_ms: int = 30000,
    max_wait_sec: float = 25.0,
    retry_interval_sec: float = 0.25,
):
    """
    Lock distribuido en Redis por (tenant_id, número de teléfono) para serializar el procesamiento
    de mensajes entrantes sin bloquear números distintos ni negocios distintos.

    - Clave: tenant:{tenant_id}:lock:{phone_norm}
    - Adquisición: SET key token NX PX ttl_ms
    - Espera con reintentos cada ~250ms hasta max_wait_sec si el lock está ocupado
    - Liberación segura con script Lua (solo libera si el token coincide)
    - Fallback a asyncio.Lock local si Redis no está disponible
    """
    phone_norm = normalize_phone(phone)
    lock_key = f"tenant:{tenant_id}:lock:{phone_norm}"
    token = str(uuid.uuid4())

    mem_lock = _get_in_memory_phone_lock(phone_norm, tenant_id=tenant_id)
    # 1. Serialización intra-proceso (resguarda concurrencia local)
    await mem_lock.acquire()

    redis_locked = False
    start_time = time.time()

    try:
        # 2. Adquisición de lock distribuido en Redis
        while True:
            try:
                r = await _get_redis()
                if r:
                    acquired = await r.set(lock_key, token, nx=True, px=ttl_ms)
                    if acquired:
                        redis_locked = True
                        break
                else:
                    # Si no hay cliente Redis configurado, mem_lock provee exclusión
                    break
            except Exception as e:
                logger.warning(f"Error intentando adquirir lock Redis ({tenant_id}:{phone_norm}): {e}")
                # En caso de desconexión de Redis, se continúa con mem_lock
                break

            elapsed = time.time() - start_time
            if elapsed >= max_wait_sec:
                logger.error(
                    f"❌ [LOCK TIMEOUT] No se pudo adquirir el lock de Redis para {tenant_id}:{phone_norm} "
                    f"tras {elapsed:.2f}s de espera. Se procederá con precaución."
                )
                break

            await asyncio.sleep(retry_interval_sec)

        yield token

    finally:
        # 3. Liberación segura en Redis (solo si el token coincide exactamente)
        if redis_locked:
            try:
                r = await _get_redis()
                if r:
                    await r.eval(_RELEASE_LOCK_LUA, 1, lock_key, token)
            except Exception as e:
                logger.warning(f"Error liberando lock Redis ({tenant_id}:{phone_norm}): {e}")

        # 4. Liberación de lock en memoria
        if mem_lock.locked():
            mem_lock.release()


def _mask_phone(phone: str) -> str:
    """Anonimiza un número telefónico para no exponer PII en observabilidad (ej. +519***246)."""
    p = normalize_phone(phone)
    if len(p) >= 6:
        return f"+{p[:4]}***{p[-3:]}"
    return "+***"


def _capture_sentry_fallback(
    phone_norm: str,
    message_snippet: str,
    reason: str,
    exception: Optional[Exception] = None,
) -> None:
    """Envía una alerta a Sentry cuando se activa el fallback por fallo en OpenAI."""
    try:
        import sentry_sdk
        masked_phone = _mask_phone(phone_norm)
        with sentry_sdk.push_scope() as scope:
            scope.set_tag("module", "conversational_agent")
            scope.set_tag("fallback_triggered", "true")
            scope.set_tag("phone_masked", masked_phone)
            scope.set_context(
                "agent_fallback_context",
                {
                    "masked_phone": masked_phone,
                    "message_snippet": message_snippet[:50],
                    "failure_reason": reason[:150],
                },
            )
            if exception:
                sentry_sdk.capture_exception(exception)
            else:
                sentry_sdk.capture_message(
                    f"OpenAI Agent Fallback activado: {reason[:100]}",
                    level="warning",
                )
    except Exception as err:
        logger.debug(f"Error enviando evento fallback a Sentry: {err}")


def _capture_sentry_desync(
    phone_norm: str,
    layer_failed: str,
    detail: str = "",
) -> None:
    """Envía una alerta a Sentry cuando ocurre una desincronización entre Postgres y Redis."""
    try:
        import sentry_sdk
        masked_phone = _mask_phone(phone_norm)
        with sentry_sdk.push_scope() as scope:
            scope.set_tag("module", "state_persistence")
            scope.set_tag("layer_failed", layer_failed)
            scope.set_tag("phone_masked", masked_phone)
            scope.set_context(
                "desync_context",
                {
                    "masked_phone": masked_phone,
                    "layer_failed": layer_failed,
                    "detail": detail[:150],
                },
            )
            sentry_sdk.capture_message(
                f"Desincronización de estado en persistencia ({layer_failed}): {masked_phone}",
                level="warning",
            )
    except Exception as err:
        logger.debug(f"Error enviando evento desync a Sentry: {err}")


# ============================================================
# MONITOREO DE USO Y COSTOS DE OPENAI
# ============================================================

def calculate_openai_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    """Calcula el costo en USD según los tokens de entrada y salida."""
    m = (model or "").lower()
    if "deepseek" in m:
        input_price = 0.14 / 1_000_000
        output_price = 0.28 / 1_000_000
    elif "mini" in m:
        input_price = 0.15 / 1_000_000
        output_price = 0.60 / 1_000_000
    elif "gpt-4o" in m:
        input_price = 2.50 / 1_000_000
        output_price = 10.00 / 1_000_000
    elif "gpt-3.5" in m:
        input_price = 0.50 / 1_000_000
        output_price = 1.50 / 1_000_000
    else:
        input_price = 0.15 / 1_000_000
        output_price = 0.60 / 1_000_000

    cost = (prompt_tokens * input_price) + (completion_tokens * output_price)
    return round(cost, 6)


_last_budget_alert_month: Optional[str] = None


async def log_openai_usage(
    phone_norm: str,
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
    total_tokens: int,
    cost_usd: float,
    tenant_id: str = "glowlab",
) -> None:
    """Registra de forma no bloqueante el consumo de tokens y verifica el umbral mensual por tenant."""
    try:
        masked_phone = _mask_phone(phone_norm)
        async with async_session_factory() as db:
            log_entry = OpenAIUsageLog(
                tenant_id=tenant_id,
                phone_masked=masked_phone,
                provider=settings.AI_PROVIDER,
                model=model,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens,
                cost_usd=cost_usd,
                created_at=datetime.utcnow(),
            )
            db.add(log_entry)
            await db.commit()

        # Verificar alerta de presupuesto mensual
        await _check_monthly_budget_alert(tenant_id=tenant_id)

    except Exception as e:
        logger.debug(f"Error registrando uso de OpenAI ({tenant_id}): {e}")


async def _check_monthly_budget_alert(tenant_id: str = "glowlab") -> None:
    """
    Verifica si el gasto mensual acumulado supera el umbral preventivo ($25 USD)
    y el límite del Plan SaaS (Quota Guard), emitiendo alertas a Sentry.
    """
    global _last_budget_alert_month
    budget_limit = getattr(settings, "OPENAI_MONTHLY_BUDGET_USD", 25.0)

    now = datetime.utcnow()
    current_month_str = now.strftime("%Y-%m")
    alert_key = f"{tenant_id}:{current_month_str}"

    start_of_month = datetime(now.year, now.month, 1)

    try:
        from sqlalchemy import func
        async with async_session_factory() as db:
            res = await db.execute(
                select(func.sum(OpenAIUsageLog.cost_usd)).where(
                    OpenAIUsageLog.tenant_id == tenant_id,
                    OpenAIUsageLog.created_at >= start_of_month
                )
            )
            total_month_usd = res.scalar() or 0.0

        profile = await get_tenant_profile(tenant_id)
        plan_name = profile.get("plan_name", "pro" if tenant_id == "glowlab" else "starter")
        plan_max_ai = profile.get("max_ai_cost_usd_per_month", 50.0 if tenant_id == "glowlab" else 15.0)

        # 1. Alerta Crítica de Cuota SaaS (Quota Guard)
        if total_month_usd >= plan_max_ai:
            logger.critical(
                f"🚨 [QUOTA GUARD EXCEEDED] Tenant '{tenant_id}' ha superado su cuota de plan '{plan_name}' "
                f"(${total_month_usd:.2f} / ${plan_max_ai:.2f} USD). Modo alerta crítica activado."
            )
            try:
                import sentry_sdk
                with sentry_sdk.push_scope() as scope:
                    scope.set_tag("alert_type", "quota_exceeded_critical")
                    scope.set_tag("tenant_id", tenant_id)
                    scope.set_tag("plan_name", plan_name)
                    scope.set_context("quota_info", {
                        "tenant_id": tenant_id,
                        "plan_name": plan_name,
                        "month": current_month_str,
                        "spent_usd": float(total_month_usd),
                        "plan_limit_usd": float(plan_max_ai),
                    })
                    sentry_sdk.capture_message(
                        f"Alerta Crítica de Cuota SaaS [{tenant_id}]: Gasto mensual de IA (${total_month_usd:.2f} USD) superó el límite del plan '{plan_name}' (${plan_max_ai:.2f} USD)",
                        level="error",
                    )
            except Exception:
                pass

        # 2. Alerta Preventiva de Presupuesto ($25 USD)
        if budget_limit and budget_limit > 0 and total_month_usd >= budget_limit:
            if _last_budget_alert_month != alert_key:
                _last_budget_alert_month = alert_key
                logger.warning(
                    f"⚠️ [ALERTA PRESUPUESTO OPENAI] Gasto mensual (${total_month_usd:.2f} USD) "
                    f"ha superado el umbral preventivo (${budget_limit:.2f} USD) para tenant '{tenant_id}'."
                )
                try:
                    import sentry_sdk
                    with sentry_sdk.push_scope() as scope:
                        scope.set_tag("budget_alert", "openai_monthly_exceeded")
                        scope.set_tag("tenant_id", tenant_id)
                        scope.set_context("budget_info", {
                            "tenant_id": tenant_id,
                            "month": current_month_str,
                            "spent_usd": float(total_month_usd),
                            "budget_limit_usd": float(budget_limit),
                        })
                        sentry_sdk.capture_message(
                            f"Alerta de Presupuesto [{tenant_id}]: Gasto mensual de OpenAI (${total_month_usd:.2f} USD) superó el umbral (${budget_limit:.2f} USD)",
                            level="warning",
                        )
                except Exception:
                    pass

    except Exception as e:
        logger.debug(f"Error verificando cuota y presupuesto mensual ({tenant_id}): {e}")


async def get_openai_cost_report(timeframe: str = "hoy", tenant_id: str = "glowlab") -> str:
    """Genera un reporte resumido de consumo de tokens y costo estimado de OpenAI para un tenant."""
    now = datetime.utcnow()
    PEN_EXCHANGE_RATE = 3.75  # Tipo de cambio referencial PEN/USD

    if timeframe == "mes":
        start_date = datetime(now.year, now.month, 1)
        period_title = f"Mes actual ({MONTHS_ES[now.month].title()} {now.year})"
    elif timeframe == "semana":
        start_date = now - timedelta(days=7)
        period_title = "Últimos 7 días"
    else:  # hoy
        start_date = datetime(now.year, now.month, now.day)
        period_title = f"Hoy ({now.strftime('%d/%m/%Y')})"

    try:
        from sqlalchemy import func
        async with async_session_factory() as db:
            res = await db.execute(
                select(
                    func.count(OpenAIUsageLog.id),
                    func.sum(OpenAIUsageLog.prompt_tokens),
                    func.sum(OpenAIUsageLog.completion_tokens),
                    func.sum(OpenAIUsageLog.total_tokens),
                    func.sum(OpenAIUsageLog.cost_usd),
                ).where(
                    OpenAIUsageLog.tenant_id == tenant_id,
                    OpenAIUsageLog.created_at >= start_date
                )
            )
            row = res.fetchone()
            if row:
                count, prompt_tok, compl_tok, total_tok, total_cost = row
            else:
                count, prompt_tok, compl_tok, total_tok, total_cost = 0, 0, 0, 0, 0.0

            count = count or 0
            prompt_tok = prompt_tok or 0
            compl_tok = compl_tok or 0
            total_tok = total_tok or 0
            total_cost = float(total_cost or 0.0)
            cost_pen = total_cost * PEN_EXCHANGE_RATE
            avg_turn_usd = (total_cost / count) if count > 0 else 0.0
            avg_turn_pen = (cost_pen / count) if count > 0 else 0.0

    except Exception as e:
        logger.error(f"Error consultando reporte de costos de OpenAI: {e}")
        return f"⚠️ Error al consultar las métricas de OpenAI: {e}"

    lines = [
        f"📊 *Reporte de Consumo OpenAI — Glowlab*",
        f"📅 Periodo: *{period_title}*",
        f"🤖 Modelo principal: *{settings.OPENAI_MODEL}*\n",
        f"• *Turnos procesados:* {count:,}",
        f"• *Tokens Entrada (Prompt):* {prompt_tok:,}",
        f"• *Tokens Salida (Respuesta):* {compl_tok:,}",
        f"• *Total de Tokens:* {total_tok:,}\n",
        f"💰 *Costo Total Estimado:*",
        f"   💵 USD: *${total_cost:.4f}*",
        f"   🇵🇪 PEN: *S/ {cost_pen:.3f}*",
    ]

    if count > 0:
        lines.append(f"\n📈 *Promedio por Turno:* ${avg_turn_usd:.5f} USD (~S/ {avg_turn_pen:.4f})")

    lines.append("\n💡 _Para ver el acumulado del mes usa:_ `costo openai mes`")
    return "\n".join(lines)


async def load_state(phone: str, tenant_id: str = "glowlab") -> Dict[str, Any]:
    """Carga estado por (tenant_id, teléfono); PostgreSQL es la fuente durable y Redis la caché."""
    phone_norm = normalize_phone(phone)
    mem_key = f"{tenant_id}:{phone_norm}"
    redis_key = f"tenant:{tenant_id}:conv:{phone_norm}"
    durable_state: Dict[str, Any] = {"paso": "inicial"}
    try:
        async with async_session_factory() as db:
            result = await db.execute(
                select(Conversacion.estado).where(
                    Conversacion.tenant_id == tenant_id,
                    Conversacion.phone == phone_norm
                )
            )
            saved = result.scalar_one_or_none()
            if isinstance(saved, dict):
                durable_state = dict(saved)
    except Exception as e:
        logger.warning(f"Error leyendo estado durable ({tenant_id}:{phone_norm}): {e}")

    try:
        r = await _get_redis()
        if r:
            raw = await r.get(redis_key)
            if raw:
                cached = json.loads(raw)
                if isinstance(cached, dict) and cached.get("updated_at", "") >= durable_state.get("updated_at", ""):
                    return cached
    except Exception as e:
        logger.warning(f"Error leyendo estado Redis ({tenant_id}:{phone_norm}): {e}")

    if durable_state.get("updated_at") is None and mem_key in _in_memory_state:
        return dict(_in_memory_state[mem_key])

    return durable_state


async def save_state(phone: str, state: Dict[str, Any], tenant_id: str = "glowlab") -> None:
    """Persiste el estado en PostgreSQL y actualiza la caché Redis con TTL de 48h."""
    phone_norm = normalize_phone(phone)
    mem_key = f"{tenant_id}:{phone_norm}"
    redis_key = f"tenant:{tenant_id}:conv:{phone_norm}"
    state["updated_at"] = datetime.utcnow().isoformat()
    state_to_save = dict(state)
    _in_memory_state[mem_key] = state_to_save

    db_ok = False
    redis_ok = False
    db_err_detail = ""
    redis_err_detail = ""

    try:
        from sqlalchemy.orm.attributes import flag_modified
        async with async_session_factory() as db:
            result = await db.execute(
                select(Conversacion).where(
                    Conversacion.tenant_id == tenant_id,
                    Conversacion.phone == phone_norm
                )
            )
            conversation = result.scalar_one_or_none()
            if conversation:
                conversation.estado = state_to_save
                flag_modified(conversation, "estado")
            else:
                db.add(Conversacion(tenant_id=tenant_id, phone=phone_norm, estado=state_to_save))
            await db.commit()
            db_ok = True
    except Exception as e:
        db_err_detail = str(e)
        logger.warning(f"Error guardando estado durable en PostgreSQL ({tenant_id}:{phone_norm}): {e}")

    try:
        r = await _get_redis()
        if r:
            await r.set(
                redis_key,
                json.dumps(state_to_save, ensure_ascii=False),
                ex=REDIS_STATE_TTL,
            )
            redis_ok = True
        else:
            redis_ok = True  # Redis no configurado o modo standalone
    except Exception as e:
        redis_err_detail = str(e)
        logger.warning(f"Error guardando estado en caché Redis ({tenant_id}:{phone_norm}): {e}")

    # Monitoreo y alerta a Sentry por desincronización entre PostgreSQL y Redis
    if db_ok and not redis_ok:
        logger.warning(
            f"⚠️ [DESINCRONIZACIÓN DE ESTADO] ({tenant_id}:{phone_norm}): PostgreSQL persistió correctamente "
            f"pero falló la actualización en Redis."
        )
        _capture_sentry_desync(phone_norm, "Redis", redis_err_detail)
    elif redis_ok and not db_ok:
        logger.warning(
            f"⚠️ [DESINCRONIZACIÓN DE ESTADO] ({tenant_id}:{phone_norm}): Redis actualizó la caché "
            f"pero falló la persistencia durable en PostgreSQL."
        )
        _capture_sentry_desync(phone_norm, "PostgreSQL", db_err_detail)


async def clear_state(phone: str, tenant_id: str = "glowlab") -> None:
    """Elimina el estado conversacional de una clienta para el tenant especificado."""
    phone_norm = normalize_phone(phone)
    mem_key = f"{tenant_id}:{phone_norm}"
    redis_key = f"tenant:{tenant_id}:conv:{phone_norm}"
    session_key = f"tenant:{tenant_id}:session:{phone_norm}"
    _in_memory_state.pop(mem_key, None)
    try:
        r = await _get_redis()
        if r:
            await r.delete(redis_key, session_key)
    except Exception as e:
        logger.warning(f"Error borrando estado Redis ({tenant_id}:{phone_norm}): {e}")

    await save_state(phone_norm, {"paso": "inicial", "session_active": False}, tenant_id=tenant_id)


# ============================================================
# GESTIÓN DE SESIÓN Y MENÚ INTERACTIVO (REDIS + POSTGRESQL)
# ============================================================

def is_greeting_message(text: str) -> bool:
    """
    Detecta si el mensaje es un saludo natural (ej. 'Hola', 'Buenos días', 'Buenas tardes', etc.).
    """
    if not text:
        return False
    t = text.strip().lower()
    t_clean = re.sub(r"[^\w\s]", " ", t)
    tokens = t_clean.split()
    if not tokens:
        return False

    greeting_words = {
        "hola", "holas", "holaa", "holaaa", "buenos", "buenas",
        "hi", "hey", "hello", "saludos", "start", "inicio", "menu", "menú"
    }
    greeting_phrases = [
        "buenos dias", "buenos días", "buenas tardes", "buenas noches",
        "hola buenas", "hola buenos dias", "hola buenos días", "hola buenas tardes", "hola buenas noches",
        "saludos cordiales", "que tal", "qué tal", "buen dia", "buen día"
    ]

    for phrase in greeting_phrases:
        if phrase in t:
            return True

    if tokens[0] in greeting_words:
        return True

    return False


def is_scheduling_intent_message(text: str) -> bool:
    """
    Detecta si el mensaje contiene intenciones de agendamiento o reserva
    (ej. 'quiero hacer una cita', 'agendar', 'reservar', 'quiero una cita').
    """
    if not text:
        return False
    t = text.strip().lower()
    scheduling_keywords = [
        "quiero hacer una cita", "quiero una cita", "hacer una cita", "sacar una cita",
        "quiero agendar", "quisiera agendar", "deseo agendar", "agendar una cita",
        "agendar cita", "agendar", "quiero reservar", "quisiera reservar",
        "deseo reservar", "reservar una cita", "reservar cita", "reservar",
        "separar cita", "separar una cita", "separar turno", "sacar cita",
        "sacar turno", "pedir cita", "pedir una cita", "solicitar cita",
        "necesito una cita", "necesito agendar", "necesito reservar"
    ]
    for kw in scheduling_keywords:
        if kw in t:
            return True
    return False


def is_interactive_menu_trigger(text: str) -> bool:
    """Verifica si el mensaje es un disparador para presentar el Menú Interactivo."""
    return is_greeting_message(text) or is_scheduling_intent_message(text)


def is_menu_option_1(text: str) -> bool:
    """Verifica si la respuesta del usuario corresponde a la Opción 1 (Asistente Virtual)."""
    t = text.strip().lower()
    if t in ("1", "1.", "1️⃣", "uno", "primera", "opcion 1", "opción 1", "opc 1", "asistente", "asistente virtual", "ia", "robot", "bot"):
        return True
    if re.match(r"^1(\b|\.|\))", t) or t == "1":
        return True
    return False


def is_menu_option_2(text: str) -> bool:
    """Verifica si la respuesta del usuario corresponde a la Opción 2 (Atención Personalizada)."""
    t = text.strip().lower()
    if t in ("2", "2.", "2️⃣", "dos", "segunda", "opcion 2", "opción 2", "opc 2", "atencion personalizada", "atención personalizada", "asesor", "asesora", "humano", "persona"):
        return True
    if re.match(r"^2(\b|\.|\))", t) or t == "2":
        return True
    return False


async def check_session_active(state: Dict[str, Any], phone: str, tenant_id: str = "glowlab") -> bool:
    """
    Verifica si la sesión de IA está activa (session_active == True) y no ha superado
    el umbral de 3 horas de inactividad. Si han pasado >3h, desactiva la sesión automáticamente.
    """
    phone_norm = normalize_phone(phone)
    session_active = bool(state.get("session_active", False))

    if not session_active:
        return False

    last_interaction = state.get("last_interaction_at")
    now_ts = time.time()

    if last_interaction is not None:
        try:
            if isinstance(last_interaction, str):
                try:
                    last_ts = float(last_interaction)
                except ValueError:
                    last_dt = datetime.fromisoformat(last_interaction)
                    last_ts = last_dt.timestamp()
            elif isinstance(last_interaction, (int, float)):
                last_ts = float(last_interaction)
            else:
                last_ts = now_ts

            if (now_ts - last_ts) > SESSION_TIMEOUT_SECONDS:
                logger.info(f"⏳ [SESIÓN EXPIRADA] Sesión de IA desactivada tras 3h de inactividad para {tenant_id}:{phone_norm}")
                await deactivate_ai_session(phone_norm, state, tenant_id=tenant_id, paso="inicial")
                return False
        except Exception as e:
            logger.warning(f"Error verificando inactividad de sesión ({tenant_id}:{phone_norm}): {e}")

    # Verificar existencia en Redis
    try:
        r = await _get_redis()
        if r:
            session_key = f"tenant:{tenant_id}:session:{phone_norm}"
            exists = await r.exists(session_key)
            if not exists and last_interaction:
                state["session_active"] = False
                return False
    except Exception as e:
        logger.debug(f"Aviso consultando clave de sesión Redis: {e}")

    return True


async def activate_ai_session(phone: str, state: Dict[str, Any], tenant_id: str = "glowlab") -> None:
    """
    Activa el flag de sesión de la IA (session_active = True), resetea el temporizador de inactividad
    y actualiza la clave en Redis con TTL de 3 horas.
    """
    phone_norm = normalize_phone(phone)
    now_ts = time.time()
    state["session_active"] = True
    state["last_interaction_at"] = now_ts
    state["menu_displayed"] = False
    state["paso"] = "asistente_ia"

    try:
        r = await _get_redis()
        if r:
            session_key = f"tenant:{tenant_id}:session:{phone_norm}"
            await r.set(session_key, "1", ex=SESSION_TIMEOUT_SECONDS)
    except Exception as e:
        logger.warning(f"Error activando clave de sesión en Redis ({tenant_id}:{phone_norm}): {e}")

    await save_state(phone_norm, state, tenant_id=tenant_id)


async def deactivate_ai_session(
    phone: str,
    state: Dict[str, Any],
    tenant_id: str = "glowlab",
    paso: Optional[str] = None
) -> None:
    """
    Desactiva el flag de sesión de la IA (session_active = False), apagando automáticamente
    la IA tras confirmación de cita, derivación a asesor humano o expiración de inactividad.
    """
    phone_norm = normalize_phone(phone)
    state["session_active"] = False
    state["menu_displayed"] = False
    if paso:
        state["paso"] = paso

    try:
        r = await _get_redis()
        if r:
            session_key = f"tenant:{tenant_id}:session:{phone_norm}"
            await r.delete(session_key)
    except Exception as e:
        logger.warning(f"Error eliminando clave de sesión en Redis ({tenant_id}:{phone_norm}): {e}")

    await save_state(phone_norm, state, tenant_id=tenant_id)



# ============================================================
# DETECCIÓN DE ASESORA POR SERVICIO
# ============================================================

def detect_advisor(servicio: str, tenant_id: str = "glowlab") -> Optional[str]:
    """Retorna la asesora o profesional asignado según el servicio solicitado y tenant."""
    if not servicio:
        return "lizbeth" if tenant_id == "glowlab" else "especialista"
    s = servicio.lower()
    if tenant_id == "glowlab":
        for keyword, advisor in SERVICE_TO_ADVISOR.items():
            if keyword in s:
                return advisor
        return "lizbeth"
    return "especialista"


# ============================================================
# MOTOR DE RESERVAS (POSTGRESQL)
# ============================================================

async def get_available_slots(
    db: AsyncSession,
    advisor: str,
    target_date: date,
    service_name: Optional[str] = None,
    tenant_id: str = "glowlab",
) -> List[str]:
    """Retorna los horarios libres de una asesora/especialista para una fecha dada y tenant específico calculando duración."""
    # Sin atención los domingos
    if target_date.weekday() == 6:
        return []

    date_str = target_date.strftime("%Y-%m-%d")
    result = await db.execute(
        select(Cita.hora).where(
            and_(
                Cita.tenant_id == tenant_id,
                Cita.asesora == advisor,
                Cita.fecha == date_str,
                Cita.estado.in_(["pendiente", "confirmada"]),
            )
        )
    )
    booked = {row[0] for row in result.fetchall()}

    # Intervalo y duración
    profile = await get_tenant_profile(tenant_id)
    slot_interval = profile.get("slot_interval_minutes", 60)

    if service_name:
        try:
            res_svc = await db.execute(
                select(Service.duration_minutes).where(
                    Service.tenant_id == tenant_id,
                    Service.name.ilike(f"%{service_name}%"),
                    Service.is_active == True
                )
            )
            svc_dur = res_svc.scalar_one_or_none()
            if svc_dur and svc_dur > 0:
                slot_interval = svc_dur
        except Exception:
            pass

    if slot_interval == 30:
        base_slots = [f"{h:02d}:{m:02d}" for h in range(10, 18) for m in (0, 30)]
    elif slot_interval == 45:
        base_slots = ["10:00", "10:45", "11:30", "12:15", "14:00", "14:45", "15:30", "16:15", "17:00"]
    elif slot_interval == 90:
        base_slots = ["10:00", "11:30", "14:00", "15:30", "17:00"]
    else:
        base_slots = AVAILABLE_SLOTS

    return [slot for slot in base_slots if slot not in booked]


async def create_cita(
    db: AsyncSession,
    cliente_phone: str,
    cliente_nombre: str,
    servicio: str,
    asesora: str,
    fecha: str,
    hora: str,
    observaciones: str = "",
    tenant_id: str = "glowlab",
) -> Cita:
    """Crea una nueva cita asociada al tenant en estado 'pendiente' y actualiza el perfil del cliente."""
    cita = Cita(
        tenant_id=tenant_id,
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

    # Upsert del cliente con aislamiento por tenant
    res = await db.execute(
        select(Cliente).where(
            Cliente.tenant_id == tenant_id,
            Cliente.phone == cliente_phone
        )
    )
    cliente = res.scalar_one_or_none()
    if not cliente:
        cliente = Cliente(tenant_id=tenant_id, phone=cliente_phone, nombre=cliente_nombre or "")
        db.add(cliente)
    elif cliente_nombre and not cliente.nombre:
        cliente.nombre = cliente_nombre

    await db.commit()
    await db.refresh(cita)
    return cita


async def update_cita_estado(
    db: AsyncSession, cita_id: int, estado: str, tenant_id: str = "glowlab", **kwargs
) -> Optional[Cita]:
    """Actualiza el estado de una cita filtrando por ID y tenant_id."""
    res = await db.execute(
        select(Cita).where(
            Cita.id == cita_id,
            Cita.tenant_id == tenant_id
        )
    )
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

# ============================================================
# GENERACIÓN DE RESPUESTAS CONVERSACIONALES (OPENAI + CLIENT SYSTEM PROMPT)
# ============================================================

def _fallback_client_reply(state: Dict[str, Any], message: str) -> str:
    """Respuesta de respaldo determinista y contextual cuando OpenAI no está disponible."""
    text_low = message.lower().strip()
    paso = state.get("paso", "inicial")

    # 1. Saludos puros (Prioridad 1: Siempre responder al saludo sin forzar slots)
    if any(k in text_low for k in ("hola", "buenos dias", "buenas tardes", "buenas noches", "buenas", "hi", "hey")):
        if not any(k in text_low for k in ("precio", "costo", "cuanto", "cuánto", "cita", "reserva", "horario", "botox", "keratina", "uñas", "pestañas", "seco", "dañado", "frizz", "servicios", "catalogo", "catálogo", "cabello", "pelo")):
            return "¡Hola! 💕 Bienvenida a Glowlab. ¿En qué te podemos ayudar hoy? ✨"

    # 2. Consulta sobre precio o servicio específico (Sección 11)
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

    # Coincidencia por palabra clave de servicio oficial
    for kw in sorted(OFFICIAL_SERVICES.keys(), key=len, reverse=True):
        if kw in text_low:
            price_msg = get_service_price(kw)
            if price_msg:
                return price_msg

    # 3. Consulta o recomendación capilar específica (Sección 9 - Filtrado por necesidad)
    if any(k in text_low for k in ("cabello", "pelo", "seco", "dañado", "maltratado", "frizz", "capilar", "hidratar", "alisar", "caida")):
        return (
            "Claro 😊 Para el cuidado de tu cabello tenemos las siguientes opciones de tratamientos capilares:\n\n"
            "• *Tratamiento de hidratación:* S/ 80 (nutrición y suavidad profunda)\n"
            "• *Botox capilar:* S/ 120 (mejora la apariencia, brillo y sedosidad)\n"
            "• *Keratina:* S/ 160 (restauración intensa y control de frizz)\n"
            "• *Hidratación express:* S/ 50 (hidratación y brillo rápido)\n\n"
            "Si me cuentas qué resultado buscas en tu cabello, puedo orientarte sobre cuál es el más indicado para ti. ✨"
        )

    # 4. Consulta o recomendación de pestañas específica (Sección 9 / 10)
    if any(k in text_low for k in ("pestaña", "pestañas", "pestana", "pestanas", "lash", "mirada")) and not any(k in text_low for k in ("cita", "agendar", "reservar", "separar")):
        return (
            "Claro 😊 Para pestañas tenemos las siguientes opciones realizadas por nuestra lashista:\n\n"
            "• *Extensiones naturales:* desde S/ 80\n"
            "• *Extensiones más definidas:* desde S/ 100\n"
            "• *Estilo a medida:* desde S/ 50\n\n"
            "¿Qué estilo te gustaría lucir? ✨"
        )

    # 5. Consulta o recomendación de uñas específica (Sección 9 / 10)
    if any(k in text_low for k in ("uña", "uñas", "unas", "manicura", "manicure", "pedicure", "pedicura", "esmalte", "gel", "acrílica", "acrilica")) and not any(k in text_low for k in ("cita", "agendar", "reservar", "separar")):
        return (
            "Claro 😊 Para uñas tenemos las siguientes opciones:\n\n"
            "• *Pintado:* desde S/ 30\n"
            "• *Diseños y decoración:* desde S/ 45\n"
            "• *Otros servicios de uñas* según diseño\n\n"
            "¿Qué tipo de servicio o diseño te gustaría realizarte? ✨"
        )

    # 6. Lista general de servicios / catálogo (Sección 8 y 10)
    if any(k in text_low for k in ("servicios", "catálogo", "catalogo", "que tienen", "qué tienen", "tratamientos", "opciones", "hacen")):
        return list_services()

    # 7. Consulta sobre pago / adelanto de reserva
    if any(k in text_low for k in ("cuánto pagar", "cuanto pagar", "cuánto debo pagar", "cuanto debo pagar", "adelanto", "pago para reservar", "separar cita")):
        return build_advance_message()

    # 8. Solicitud de horarios / disponibilidad explícita cuando hay slots calculados
    if any(k in text_low for k in ("horario", "horarios", "disponibilidad", "qué hora", "que hora", "a qué hora", "a que hora")) and state.get("slots_disponibles"):
        fecha_str = state.get("fecha", "")
        fecha_obj = parse_fecha(fecha_str) if fecha_str else None
        fecha_es = format_fecha_es(fecha_obj) if fecha_obj else fecha_str
        return build_slots_message(state["slots_disponibles"], fecha_es)

    # 9. Agendamiento explícito (Sección 6 y 7)
    if any(k in text_low for k in ("cita", "agendar", "reservar", "separar")):
        if not state.get("servicio"):
            return "¡Claro! 😊 ¿Qué servicio deseas realizarte?"
        if not state.get("fecha"):
            return f"¡Perfecto! 😊 Para *{state['servicio']}*, ¿qué día te viene mejor?"
        if state.get("slots_disponibles"):
            fecha_str = state.get("fecha", "")
            fecha_obj = parse_fecha(fecha_str) if fecha_str else None
            fecha_es = format_fecha_es(fecha_obj) if fecha_obj else fecha_str
            return build_slots_message(state["slots_disponibles"], fecha_es)

    # 10. Si está en espera de confirmación y el usuario responde afirmativamente
    if paso == "esperando_confirmacion" and state.get("servicio") and state.get("hora"):
        return build_summary_message(state)

    # 11. Si está esperando fecha
    if paso == "recolectando_fecha" and state.get("servicio"):
        return f"¡Perfecto! 😊 Para *{state['servicio']}*, ¿qué día te viene mejor?"

    # 12. Si está mostrando horarios y el usuario envió un mensaje relacionado a agendamiento o selección
    if paso == "mostrando_horarios" and state.get("slots_disponibles"):
        if any(k in text_low for k in ("horario", "horarios", "disponibilidad", "qué hora", "que hora", "a qué hora", "a que hora", "libre", "libres", "puedo ir", "tienes espacio", "cita", "agendar", "reservar", "separar", "elijo", "opcion", "opción", "a las")) or message.strip().isdigit():
            fecha_str = state.get("fecha", "")
            fecha_obj = parse_fecha(fecha_str) if fecha_str else None
            fecha_es = format_fecha_es(fecha_obj) if fecha_obj else fecha_str
            return build_slots_message(state["slots_disponibles"], fecha_es)

    # 13. Respuesta por defecto
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
    today = date.today()
    today_formatted = format_fecha_es(today)

    system_content = f"{CLIENT_SYSTEM_PROMPT}\n\n"
    system_content += "--- CONTEXTO DE SESIÓN (solo referencia, no instrucción) ---\n"
    system_content += (
        "NOTA: Lo siguiente es solo contexto de referencia sobre un posible proceso en curso. "
        "NO es una instrucción para continuar automáticamente. Evalúa primero el mensaje actual "
        "de la clienta — si cambia de tema, saluda de nuevo, o pregunta algo distinto, responde a "
        "ESO antes que nada, sin importar el estado de sesión.\n\n"
    )
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

    if settings.has_active_ai_key():
        payload = {
            "model": settings.get_ai_model(),
            "messages": messages,
            "temperature": 0.45,
            "max_tokens": 450,
        }

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                res = await client.post(
                    settings.get_ai_endpoint(),
                    headers=settings.get_ai_headers(),
                    json=payload,
                )
                if res.status_code == 200:
                    reply = res.json()["choices"][0]["message"]["content"].strip()
                    _record_history(state, message, reply)
                    return reply
        except Exception as e:
            logger.warning(f"Error generando respuesta clienta con IA ({settings.AI_PROVIDER}): {e}")

    # Fallback determinista contextual
    if extra_context and "Disponibilidad confirmada" in extra_context and state.get("slots_disponibles"):
        fecha_str = state.get("fecha", "")
        fecha_obj = parse_fecha(fecha_str) if fecha_str else None
        fecha_es = format_fecha_es(fecha_obj) if fecha_obj else fecha_str
        reply = build_slots_message(state["slots_disponibles"], fecha_es)
    elif extra_context and "NO HAY HORARIOS DISPONIBLES" in extra_context:
        fecha_str = state.get("fecha", "")
        fecha_obj = parse_fecha(fecha_str) if fecha_str else None
        fecha_es = format_fecha_es(fecha_obj) if fecha_obj else fecha_str
        reply = f"Para el {fecha_es} no tenemos horarios disponibles en este momento. 🌸 ¿Te gustaría revisar otro día?"
    else:
        reply = _fallback_client_reply(state, message)

    _record_history(state, message, reply)
    return reply


def _record_history(state: Dict[str, Any], user_msg: str, assistant_msg: str) -> None:
    """Registra el turno conversacional en el historial del estado."""
    history = state.get("history", [])
    history.append({"role": "user", "content": user_msg})
    history.append({"role": "assistant", "content": assistant_msg})
    state["history"] = history[-8:]


# ============================================================
# DEFINICIÓN DE HERRAMIENTAS AUTÓNOMAS (OPENAI FUNCTION CALLING)
# ============================================================

def get_openai_tools(tenant_id: str = "glowlab", categories: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    """Genera dinámicamente las herramientas de Function Calling según el tenant y sus categorías."""
    cat_enums = ["todos"]
    if categories:
        for c in categories:
            clean = re.sub(r'[^a-zA-Z0-9_]', '', c.lower().replace(" ", "_"))
            if clean and clean not in cat_enums:
                cat_enums.append(clean)
    else:
        cat_enums.extend(["pestanas", "unas", "capilar"])

    return [
        {
            "type": "function",
            "function": {
                "name": "get_services",
                "description": f"Obtiene la lista oficial de servicios/tratamientos y precios disponibles para {tenant_id}.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "category": {
                            "type": "string",
                            "enum": cat_enums,
                            "description": "Categoría opcional para filtrar los servicios disponibles."
                        }
                    }
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "get_available_slots",
                "description": "Consulta en tiempo real en la base de datos los horarios libres y disponibles para una fecha y servicio.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "date": {
                            "type": "string",
                            "description": "Fecha a consultar en formato YYYY-MM-DD o lenguaje natural ('mañana', 'lunes', 'sábado', '2026-08-17')."
                        },
                        "service": {
                            "type": "string",
                            "description": "Servicio o tratamiento de interés."
                        }
                    },
                    "required": ["date"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "create_reservation",
                "description": "Registra una nueva reserva de cita en el sistema una vez que el cliente acordó y confirmó el servicio, fecha y hora.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "service": {
                            "type": "string",
                            "description": "Nombre del servicio a reservar."
                        },
                        "date": {
                            "type": "string",
                            "description": "Fecha de la cita en formato YYYY-MM-DD o fecha natural."
                        },
                        "time": {
                            "type": "string",
                            "description": "Hora seleccionada en formato 24h (ej. '10:00', '14:00', '16:00') o 12h ('10 am', '4 pm')."
                        },
                        "client_name": {
                            "type": "string",
                            "description": "Nombre del cliente si lo mencionó."
                        }
                    },
                    "required": ["service", "date", "time"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "cancel_or_reset_reservation",
                "description": "Cancela la reserva en curso o reinicia el proceso de agendamiento si el cliente indica que ya no desea agendar.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "reason": {
                            "type": "string",
                            "description": "Motivo de la cancelación si fue expresado."
                        }
                    }
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "escalate_to_human",
                "description": "Deriva la conversación al personal humano del negocio cuando el caso requiere atención especial o excepciones.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "issue": {
                            "type": "string",
                            "description": "Detalle del motivo de la derivación al staff humano."
                        }
                    },
                    "required": ["issue"]
                }
            }
        }
    ]

# Mantenemos OPENAI_TOOLS global para retrocompatibilidad
OPENAI_TOOLS = get_openai_tools("glowlab", ["pestanas", "unas", "capilar"])


async def execute_tool_call(
    tool_name: str,
    arguments: Dict[str, Any],
    phone: str,
    state: Dict[str, Any],
    tenant_id: str = "glowlab",
) -> Dict[str, Any]:
    """Ejecuta de manera segura la herramienta solicitada por el modelo de IA asociada a un tenant."""
    phone_norm = normalize_phone(phone)

    if tool_name == "get_services":
        category = arguments.get("category", "todos").lower()
        catalog_raw = await get_tenant_catalog(tenant_id)

        # Buscar coincidencia en categorías
        matched_cat = None
        for cat_name in catalog_raw.keys():
            clean_name = re.sub(r'[^a-zA-Z0-9_]', '', cat_name.lower().replace(" ", "_"))
            if category == clean_name or category in cat_name.lower() or cat_name.lower() in category:
                matched_cat = cat_name
                break

        if matched_cat:
            services = catalog_raw.get(matched_cat, [])
            return {"category": matched_cat, "services": services}
        return {"catalog": catalog_raw}

    elif tool_name == "get_available_slots":
        raw_date = arguments.get("date", "")
        service = arguments.get("service") or state.get("servicio", "")
        target_date = parse_fecha(raw_date)

        if not target_date:
            return {
                "status": "error",
                "message": f"No se pudo determinar la fecha para '{raw_date}'. Solicita al cliente que indique el día deseado."
            }

        # Validación de domingos
        if target_date.weekday() == 6:
            profile = await get_tenant_profile(tenant_id)
            return {
                "status": "closed",
                "date": target_date.strftime("%Y-%m-%d"),
                "date_formatted": format_fecha_es(target_date),
                "message": f"{profile.get('name', 'El establecimiento')} permanece cerrado los domingos. Atendemos de lunes a sábado de 10:00 a 18:00."
            }

        if target_date < date.today():
            return {
                "status": "invalid_date",
                "message": "La fecha solicitada es anterior a hoy. Solicita una fecha actual o futura."
            }

        advisor = detect_advisor(service, tenant_id=tenant_id) or state.get("asesora") or "lizbeth"
        state["asesora"] = advisor
        state["fecha"] = target_date.strftime("%Y-%m-%d")
        if service:
            state["servicio"] = service
        slots = []
        try:
            async with async_session_factory() as db:
                slots = await get_available_slots(db, advisor, target_date, service_name=service, tenant_id=tenant_id)
        except Exception as e:
            logger.debug(f"Aviso consultando slots en BD ({tenant_id}): {e}")
            profile = await get_tenant_profile(tenant_id)
            slot_interval = profile.get("slot_interval_minutes", 60)
            if slot_interval == 30:
                slots = [f"{h:02d}:{m:02d}" for h in range(10, 18) for m in (0, 30)]
            elif slot_interval == 45:
                slots = ["10:00", "10:45", "11:30", "12:15", "14:00", "14:45", "15:30", "16:15", "17:00"]
            elif slot_interval == 90:
                slots = ["10:00", "11:30", "14:00", "15:30", "17:00"]
            else:
                slots = AVAILABLE_SLOTS

        state["slots_disponibles"] = slots
        fecha_es = format_fecha_es(target_date)

        return {
            "status": "available" if slots else "no_slots",
            "date": target_date.strftime("%Y-%m-%d"),
            "date_formatted": fecha_es,
            "service": service,
            "slots": slots,
            "slots_formatted": [format_hora_12h(s) for s in slots],
            "message": (
                f"Horarios disponibles para el {fecha_es}: {', '.join([format_hora_12h(s) for s in slots])}"
                if slots else f"No hay horarios libres para el {fecha_es}."
            )
        }

    elif tool_name == "create_reservation":
        service = arguments.get("service") or state.get("servicio", "Servicio general")
        raw_date = arguments.get("date", "")
        raw_time = arguments.get("time", "")
        client_name = arguments.get("client_name") or state.get("nombre", "")

        target_date = parse_fecha(raw_date) or parse_fecha(state.get("fecha", "")) or date.today()
        date_str = target_date.strftime("%Y-%m-%d")

        # Normalizar hora (ej. '10am' -> '10:00', '3pm' -> '15:00')
        hora_norm = raw_time
        try:
            h_clean = raw_time.lower().replace("am", "").replace("pm", "").strip().split(":")[0]
            h_int = int(h_clean)
            if "pm" in raw_time.lower() and h_int < 12:
                h_int += 12
            hora_norm = f"{h_int:02d}:00"
        except Exception:
            pass

        advisor = detect_advisor(service, tenant_id=tenant_id) or state.get("asesora") or "lizbeth"

        profile = await get_tenant_profile(tenant_id)
        deposit_amount = profile.get("deposit_amount", 20.0)
        requires_deposit = profile.get("requires_deposit", True)

        cita_id = 1
        try:
            async with async_session_factory() as db:
                cita = await create_cita(
                    db=db,
                    cliente_phone=phone_norm,
                    cliente_nombre=client_name,
                    servicio=service,
                    asesora=advisor,
                    fecha=date_str,
                    hora=hora_norm,
                    tenant_id=tenant_id,
                )
                cita_id = cita.id
        except Exception as e:
            logger.debug(f"Aviso registrando cita en BD ({tenant_id}): {e}")
            cita_id = int(time.time()) % 100000

        state["cita_id"] = cita_id
        state["servicio"] = service
        state["fecha"] = date_str
        state["paso"] = "esperando_voucher" if requires_deposit else "cita_confirmada"
        if not requires_deposit:
            state["session_active"] = False


        instruction_msg = (
            f"Informa al cliente que su cita ha sido pre-registrada con éxito. Explícale que para confirmarla debe abonar el adelanto de S/ {int(deposit_amount) if deposit_amount.is_integer() else deposit_amount} por Yape/Plin y enviar la foto del comprobante aquí."
            if requires_deposit
            else "Informa al cliente que su cita ha sido registrada con éxito."
        )

        return {
            "status": "success",
            "reservation_id": cita.id,
            "service": service,
            "date": date_str,
            "date_formatted": format_fecha_es(target_date),
            "time": format_hora_12h(hora_norm),
            "client_name": client_name,
            "advance_amount": deposit_amount,
            "payment_info": settings.PAYMENT_INFO,
            "instruction": instruction_msg
        }

    elif tool_name == "cancel_or_reset_reservation":
        state["servicio"] = None
        state["fecha"] = None
        state["hora"] = None
        state["slots_disponibles"] = None
        state["paso"] = "inicial"
        return {"status": "cancelled", "message": "Proceso cancelado. Responde con amabilidad que no hay inconveniente."}

    elif tool_name == "escalate_to_human":
        issue = arguments.get("issue", "Solicitud especial")
        state["paso"] = "derivada"
        await notify_all_staff(f"⚠️ [{tenant_id}] Atención especial requerida para +{phone_norm} ({state.get('nombre', '')}):\n\"{issue}\"")
        return {"status": "escalated", "message": f"Notificación enviada al equipo de {tenant_id}. Indica al cliente que un asesor se comunicará en breve."}

    return {"status": "error", "message": f"Herramienta '{tool_name}' no reconocida."}


# ============================================================
# AGENTE CONVERSACIONAL ABIERTO (OPENAI AGENT RUNNER)
# ============================================================

async def run_conversational_agent(
    sender_number: str,
    sender_name: str,
    message_text: str,
    message_data: Optional[Dict[str, Any]] = None,
    raw_item: Optional[Dict[str, Any]] = None,
    tenant_id: str = "glowlab",
) -> str:
    """
    Agente Conversacional Autónomo basado en OpenAI/DeepSeek con Function Calling (Tools).
    Maneja el diálogo, ejecuta herramientas en la base de datos y mantiene la memoria fluida por tenant.
    """
    phone_norm = normalize_phone(sender_number)
    state = await load_state(phone_norm, tenant_id=tenant_id)
    if sender_name and not state.get("nombre"):
        state["nombre"] = sender_name

    # Perfil y catálogo del tenant activo
    profile = await get_tenant_profile(tenant_id)
    catalog_raw = await get_tenant_catalog(tenant_id)
    categories = list(catalog_raw.keys())
    active_tools = get_openai_tools(tenant_id=tenant_id, categories=categories)

    # Formatear catálogo para el system prompt
    prompt_catalog: Dict[str, List[str]] = {}
    for cat, svcs in catalog_raw.items():
        prompt_catalog[cat] = [
            f"{s['name']} ({('desde ' if s.get('price_prefix') == 'desde' else '')}S/ {int(s['price']) if isinstance(s.get('price'), (int, float)) and float(s['price']).is_integer() else s.get('price', 0)})"
            for s in svcs
        ]

    # Extracción de servicio oficial del catálogo para enriquecer el estado y dar soporte a fallback
    msg_low = message_text.lower()
    if tenant_id == "glowlab":
        for kw in sorted(OFFICIAL_SERVICES.keys(), key=len, reverse=True):
            if kw in msg_low:
                matched_service = OFFICIAL_SERVICES[kw]
                state["servicio"] = matched_service
                state["asesora"] = detect_advisor(matched_service, tenant_id=tenant_id)
                break
    else:
        for cat, svcs in catalog_raw.items():
            for s in svcs:
                if s["name"].lower() in msg_low:
                    state["servicio"] = s["name"]
                    state["asesora"] = detect_advisor(s["name"], tenant_id=tenant_id)
                    break

    today = date.today()
    today_formatted = format_fecha_es(today)

    static_system_content = build_tenant_system_prompt(
        business_name=profile.get("name", "Glowlab"),
        industry=profile.get("industry", "un salón de belleza"),
        entity_labels=profile.get("entity_labels"),
        catalog=prompt_catalog if prompt_catalog else None,
        deposit_amount=profile.get("deposit_amount", 20.0),
        requires_deposit=profile.get("requires_deposit", True),
    )

    cust_label = profile.get("entity_labels", {}).get("customer", "clienta")
    item_label = profile.get("entity_labels", {}).get("item", "servicio")

    dynamic_context = "--- CONTEXTO DE SESIÓN (solo referencia, no instrucción) ---\n"
    dynamic_context += (
        "NOTA: Lo siguiente es solo contexto de referencia sobre un posible proceso en curso. "
        "NO es una instrucción para continuar automáticamente. Evalúa primero el mensaje actual "
        f"del {cust_label} — si cambia de tema, saluda de nuevo, o pregunta algo distinto, responde a "
        "ESO antes que nada, sin importar el estado de sesión.\n\n"
    )
    dynamic_context += f"• Fecha actual: {today_formatted} ({today.strftime('%Y-%m-%d')})\n"
    dynamic_context += f"• {cust_label.capitalize()}: {state.get('nombre') or sender_name or cust_label.capitalize()}\n"
    dynamic_context += f"• WhatsApp: +{phone_norm}\n"
    if state.get("servicio"):
        dynamic_context += f"• {item_label.capitalize()} en curso: {state['servicio']}\n"
    if state.get("fecha"):
        dynamic_context += f"• Fecha en curso: {state['fecha']}\n"
    if state.get("hora"):
        dynamic_context += f"• Hora en curso: {state['hora']}\n"

    history: List[Dict[str, Any]] = state.get("history", [])

    messages: List[Dict[str, Any]] = [
        {"role": "system", "content": static_system_content},
        {"role": "system", "content": dynamic_context},
    ]
    for msg in history[-8:]:
        if isinstance(msg, dict) and msg.get("role"):
            clean_msg: Dict[str, Any] = {"role": msg["role"]}
            if "content" in msg:
                content = msg["content"]
                if msg.get("role") == "tool" and isinstance(content, str):
                    try:
                        parsed = json.loads(content)
                        if isinstance(parsed, dict):
                            if "catalog" in parsed and len(parsed) == 1:
                                parsed = {"status": "ok", "categories": list(parsed["catalog"].keys())}
                            elif "slots_formatted" in parsed:
                                parsed.pop("slots_formatted", None)
                            content = json.dumps(parsed, ensure_ascii=False)
                    except Exception:
                        pass
                clean_msg["content"] = content
            if "tool_calls" in msg:
                clean_msg["tool_calls"] = msg["tool_calls"]
            if "tool_call_id" in msg:
                clean_msg["tool_call_id"] = msg["tool_call_id"]
            messages.append(clean_msg)

    messages.append({"role": "user", "content": message_text})

    final_reply = ""
    fallback_reason = ""
    fallback_exception: Optional[Exception] = None

    if settings.has_active_ai_key():
        ai_model = settings.get_ai_model()
        ai_endpoint = settings.get_ai_endpoint()
        ai_headers = settings.get_ai_headers()
        try:
            async with httpx.AsyncClient(timeout=25.0) as client:
                for _ in range(5):  # Máximo 5 rondas de herramientas
                    payload = {
                        "model": ai_model,
                        "messages": messages,
                        "tools": active_tools,
                        "tool_choice": "auto",
                        "temperature": 0.4,
                        "max_tokens": 500,
                    }
                    res = await client.post(
                        ai_endpoint,
                        headers=ai_headers,
                        json=payload,
                    )
                    if res.status_code != 200:
                        fallback_reason = f"{settings.AI_PROVIDER.capitalize()} HTTP {res.status_code}: {res.text[:100]}"
                        logger.warning(f"{settings.AI_PROVIDER} error {res.status_code}: {res.text[:150]}")
                        break

                    res_json = res.json()

                    # Registro asíncrono y no bloqueante del consumo de tokens y costo
                    usage = res_json.get("usage", {})
                    if usage:
                        p_tok = usage.get("prompt_tokens", 0)
                        c_tok = usage.get("completion_tokens", 0)
                        t_tok = usage.get("total_tokens", p_tok + c_tok)
                        cost_usd = calculate_openai_cost(ai_model, p_tok, c_tok)
                        asyncio.create_task(
                            log_openai_usage(
                                phone_norm=phone_norm,
                                model=ai_model,
                                prompt_tokens=p_tok,
                                completion_tokens=c_tok,
                                total_tokens=t_tok,
                                cost_usd=cost_usd,
                                tenant_id=tenant_id,
                            )
                        )

                    choice = res_json["choices"][0]
                    assistant_msg = choice["message"]

                    if assistant_msg.get("tool_calls"):
                        messages.append(assistant_msg)
                        for tool_call in assistant_msg["tool_calls"]:
                            fn = tool_call["function"]
                            fn_name = fn["name"]
                            try:
                                fn_args = json.loads(fn.get("arguments", "{}"))
                            except Exception:
                                fn_args = {}
                            tool_result = await execute_tool_call(fn_name, fn_args, phone_norm, state, tenant_id=tenant_id)
                            messages.append({
                                "role": "tool",
                                "tool_call_id": tool_call["id"],
                                "content": json.dumps(tool_result, ensure_ascii=False),
                            })
                    else:
                        final_reply = (assistant_msg.get("content") or "").strip()
                        break
        except Exception as e:
            fallback_reason = f"{type(e).__name__}: {str(e)[:100]}"
            fallback_exception = e
            logger.error(f"Error en {settings.AI_PROVIDER.capitalize()} Agent Runner: {e}")

    if not final_reply:
        if fallback_reason:
            _capture_sentry_fallback(
                phone_norm=phone_norm,
                message_snippet=message_text[:50],
                reason=fallback_reason,
                exception=fallback_exception,
            )
        final_reply = _fallback_client_reply(state, message_text)

    _record_history(state, message_text, final_reply)
    await save_state(phone_norm, state, tenant_id=tenant_id)
    return final_reply


# ============================================================
# COMPATIBILIDAD CON EXTRACT_INTENT Y GENERATE_CLIENT_REPLY
# ============================================================

async def extract_intent(state: Dict[str, Any], message: str) -> Dict[str, Any]:
    """Helper de compatibilidad."""
    return _keyword_extract(message, state)


def _keyword_extract(message: str, state: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Extracción de intención por palabras clave contextual (fallback y compatibilidad)."""
    s = message.lower()
    state = state or {}
    paso = state.get("paso", "inicial")

    # Fecha mencionada
    fecha = None
    for fkw in ("hoy", "mañana", "manana", "pasado mañana", "lunes", "martes", "miercoles", "miércoles", "jueves", "viernes", "sabado", "sábado", "domingo"):
        if fkw in s:
            fecha = fkw
            break

    if any(k in s for k in ("precio", "costo", "cuánto", "cuanto", "vale", "cobran", "información", "informacion", "qué incluye", "que incluye", "recomiendas", "recomendación", "seco", "dañado", "frizz", "diferencia", "servicios", "catálogo", "catalogo")):
        intent = "consultar"
    elif any(k in s for k in ("cita", "agendar", "reservar", "turno", "separar", "disponibilidad", "horarios", "quiero reservar", "sacar cita")):
        intent = "agendar"
    elif fecha and (paso in ("recolectando_fecha", "mostrando_horarios") or state.get("servicio")):
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

    slot_num = None
    for i in range(1, 10):
        if f" {i} " in f" {s} " or s.strip() == str(i):
            slot_num = i
            break

    servicio = None
    for kw in sorted(SERVICE_TO_ADVISOR.keys(), key=len, reverse=True):
        if kw in s:
            servicio = kw
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
# RESOLUCIÓN DE INSTANCIAS Y CLIENTE EVOLUTION API MULTI-TENANT
# ============================================================

async def resolve_tenant_from_instance(instance_name: str) -> Optional[str]:
    """
    Resuelve el slug del tenant a partir del nombre de instancia de Evolution API.
    Utiliza caché en Redis (TTL 24h) con PostgreSQL como fuente de verdad.
    """
    if not instance_name:
        return "glowlab"

    clean_instance = instance_name.strip()
    redis_key = f"evolution:instance:{clean_instance}"

    # 1. Consultar en caché de Redis
    try:
        r = await _get_redis()
        if r:
            cached_tenant = await r.get(redis_key)
            if cached_tenant:
                return cached_tenant
    except Exception as e:
        logger.debug(f"Aviso leyendo mapeo de instancia en Redis ({clean_instance}): {e}")

    # 2. Consultar en PostgreSQL
    try:
        async with async_session_factory() as db:
            res = await db.execute(select(Tenant).where(Tenant.status == "active"))
            tenants = res.scalars().all()
            for t in tenants:
                stg = t.settings or {}
                evo_inst = stg.get("evolution_instance") or stg.get("evolution_instance_name") or t.slug
                if clean_instance.lower() in (t.slug.lower(), str(evo_inst).lower()):
                    tenant_slug = t.slug
                    # Guardar en caché Redis
                    try:
                        r = await _get_redis()
                        if r:
                            await r.set(redis_key, tenant_slug, ex=86400)
                    except Exception:
                        pass
                    return tenant_slug
    except Exception as e:
        logger.debug(f"Aviso consultando tenant en BD para instancia '{clean_instance}': {e}")

    # Fallback predeterminado para Glowlab
    glowlab_instance = getattr(settings, "EVOLUTION_INSTANCE_NAME", "glowlab-bot")
    if clean_instance.lower() in ("glowlab", "glowlab-bot", glowlab_instance.lower()):
        return "glowlab"

    return None


async def send_presence(number: str, presence: str = "composing", delay: int = 1200, tenant_id: str = "glowlab") -> bool:
    """
    Envía el estado de presencia ('composing', 'paused', etc.) a través de Evolution API usando credenciales del tenant.
    """
    profile = await get_tenant_profile(tenant_id)
    instance_name = profile.get("evolution_instance_name") or profile.get("evolution_instance") or settings.EVOLUTION_INSTANCE_NAME
    api_key = profile.get("evolution_api_key") or settings.EVOLUTION_API_KEY
    base_url = (profile.get("evolution_base_url") or settings.EVOLUTION_API_URL).rstrip("/")

    url = f"{base_url}/chat/sendPresence/{instance_name}"
    headers = {
        "apikey": api_key,
        "Content-Type": "application/json",
    }
    payload = {
        "number": number,
        "presence": presence,
        "delay": delay,
    }
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            res = await client.post(url, headers=headers, json=payload)
            return res.status_code in (200, 201)
    except Exception as e:
        logger.debug(f"Error enviando estado de presencia ({presence}) a {number} [{tenant_id}]: {e}")
        return False


@asynccontextmanager
async def typing_indicator(phone: str, refresh_interval: float = 8.0, tenant_id: str = "glowlab"):
    """
    Context manager asíncrono que mantiene activo el estado 'escribiendo...' en WhatsApp
    mientras se procesa la solicitud con la instancia correspondiente al tenant.
    """
    phone_norm = normalize_phone(phone)
    stop_event = asyncio.Event()

    async def _presence_loop():
        while not stop_event.is_set():
            try:
                await send_presence(phone_norm, presence="composing", tenant_id=tenant_id)
            except TypeError:
                await send_presence(phone_norm, presence="composing")
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=refresh_interval)
            except asyncio.TimeoutError:
                pass

    task = asyncio.create_task(_presence_loop())
    try:
        yield
    finally:
        stop_event.set()
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass
        try:
            await send_presence(phone_norm, presence="paused", tenant_id=tenant_id)
        except TypeError:
            await send_presence(phone_norm, presence="paused")


async def send_message(number: str, text: str, tenant_id: str = "glowlab") -> bool:
    """Envía un mensaje de texto a través de Evolution API usando la instancia del tenant correspondiente."""
    profile = await get_tenant_profile(tenant_id)
    instance_name = profile.get("evolution_instance_name") or profile.get("evolution_instance") or settings.EVOLUTION_INSTANCE_NAME
    api_key = profile.get("evolution_api_key") or settings.EVOLUTION_API_KEY
    base_url = (profile.get("evolution_base_url") or settings.EVOLUTION_API_URL).rstrip("/")

    url = f"{base_url}/message/sendText/{instance_name}"
    headers = {
        "apikey": api_key,
        "Content-Type": "application/json",
    }
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            res = await client.post(url, headers=headers, json={"number": number, "text": text})
            return res.status_code in (200, 201)
    except Exception as e:
        logger.error(f"Error enviando mensaje a {number} [{tenant_id}]: {e}")
        return False


async def get_media_base64(item: Dict[str, Any], tenant_id: str = "glowlab") -> Optional[str]:
    """Descarga el contenido de un mensaje multimedia como base64 desde Evolution API."""
    profile = await get_tenant_profile(tenant_id)
    instance_name = profile.get("evolution_instance_name") or profile.get("evolution_instance") or settings.EVOLUTION_INSTANCE_NAME
    api_key = profile.get("evolution_api_key") or settings.EVOLUTION_API_KEY
    base_url = (profile.get("evolution_base_url") or settings.EVOLUTION_API_URL).rstrip("/")

    url = f"{base_url}/chat/getBase64FromMediaMessage/{instance_name}"
    headers = {
        "apikey": api_key,
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
        logger.error(f"Error obteniendo media base64 [{tenant_id}]: {e}")
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


# ============================================================
# SEGUIMIENTO POST-SERVICIO Y RECORDATORIOS AUTOMÁTICOS
# ============================================================

FOLLOWUP_WINDOW_START_HOUR = 8   # 08:00 AM
FOLLOWUP_WINDOW_END_HOUR = 21   # 09:00 PM


def is_within_followup_window(dt: Optional[datetime] = None) -> bool:
    """
    Verifica si la hora en zona horaria Perú (America/Lima / UTC-5) se encuentra
    dentro de la ventana permitida (08:00 a 21:00).
    """
    try:
        from zoneinfo import ZoneInfo
        tz_lima = ZoneInfo("America/Lima")
    except Exception:
        tz_lima = timezone(timedelta(hours=-5))

    if dt is None:
        dt = datetime.now(tz_lima)
    elif dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc).astimezone(tz_lima)
    else:
        dt = dt.astimezone(tz_lima)

    return FOLLOWUP_WINDOW_START_HOUR <= dt.hour < FOLLOWUP_WINDOW_END_HOUR


DEFAULT_FOLLOWUP_TEMPLATES = {
    "unas": (
        "✨ ¡Hola {cliente_nombre}! Gracias por visitarnos en *{business_name}* 💅\n\n"
        "Recomendaciones para el cuidado de tus {servicio}:\n"
        "• Usa guantes al realizar tareas del hogar 🧤\n"
        "• Hidrata tus cutículas diariamente\n"
        "• Evita usarlas como herramientas\n\n"
        "Cualquier consulta estamos a tu disposición. ¡Esperamos verte pronto! 🌸"
    ),
    "pestanas": (
        "✨ ¡Hola {cliente_nombre}! Gracias por tu visita a *{business_name}* 👁️\n\n"
        "Cuidados recomendados para tus {servicio}:\n"
        "• Evita mojarlas durante las primeras 24h 💧\n"
        "• Péinalas suavemente cada mañana\n"
        "• Evita productos oleosos en el contorno de ojos\n\n"
        "¡Que tengas un excelente día! ✨"
    ),
    "capilar": (
        "✨ ¡Hola {cliente_nombre}! Gracias por confiar en *{business_name}* para tu {servicio} 💇‍♀️\n\n"
        "Consejos para maximizar el resultado:\n"
        "• Usa productos libres de sal y sulfatos 🧴\n"
        "• Evita calor excesivo directo esta semana\n"
        "• Aplica mascarilla hidratante semanalmente\n\n"
        "¡Nos encantó atenderte! Si tienes cualquier consulta no dudes en escribirnos. 🌟"
    ),
    "default": (
        "✨ ¡Hola {cliente_nombre}! Gracias por visitarnos en *{business_name}*.\n\n"
        "Esperamos que hayas tenido una experiencia maravillosa con tu {servicio}. "
        "Si tienes alguna duda o sugerencia, estamos aquí para atenderte.\n\n"
        "¡Que tengas un lindo día! 🌸"
    )
}


async def get_service_followup_template(
    db: AsyncSession,
    tenant_id: str = "glowlab",
    service_name: Optional[str] = None,
    service_id: Optional[int] = None,
) -> Tuple[str, int]:
    """
    Obtiene la plantilla de mensaje de seguimiento y las horas de espera (delay_hours)
    desde la tabla service_followups o fallback del catálogo.
    Retorna (template_str, delay_hours).
    """
    delay_hours = 3
    template = ""

    try:
        query = select(ServiceFollowup).where(
            ServiceFollowup.tenant_id == tenant_id,
            ServiceFollowup.is_active == True,
        )
        if service_id:
            query = query.where(
                or_(
                    ServiceFollowup.service_id == service_id,
                    ServiceFollowup.service_name.ilike(f"%{service_name}%") if service_name else False
                )
            )
        elif service_name:
            query = query.where(ServiceFollowup.service_name.ilike(f"%{service_name}%"))

        result = await db.execute(query.order_by(ServiceFollowup.id.desc()))
        row = result.scalars().first()
        if row and row.message_template:
            return (row.message_template, row.delay_hours or 3)

        # Buscar plantilla general del tenant (sin service_id específico)
        res_gen = await db.execute(
            select(ServiceFollowup).where(
                ServiceFollowup.tenant_id == tenant_id,
                ServiceFollowup.is_active == True,
                ServiceFollowup.service_id.is_(None),
                ServiceFollowup.service_name.is_(None),
            )
        )
        row_gen = res_gen.scalars().first()
        if row_gen and row_gen.message_template:
            return (row_gen.message_template, row_gen.delay_hours or 3)

    except Exception as e:
        logger.debug(f"Aviso consultando service_followups en BD ({tenant_id}): {e}")

    # Fallback por categorías de servicio
    s_low = (service_name or "").lower()
    if any(k in s_low for k in ("pestaña", "pestana", "extension", "lash")):
        template = DEFAULT_FOLLOWUP_TEMPLATES["pestanas"]
    elif any(k in s_low for k in ("capilar", "cabello", "alisado", "tinte", "tratamiento", "keratina", "botox", "mechas", "corte", "hidratacion")):
        template = DEFAULT_FOLLOWUP_TEMPLATES["capilar"]
    elif any(k in s_low for k in ("uña", "unas", "manicure", "pedicure", "nail", "gel", "acrilica")):
        template = DEFAULT_FOLLOWUP_TEMPLATES["unas"]
    else:
        template = DEFAULT_FOLLOWUP_TEMPLATES["default"]

    return (template, delay_hours)


def render_followup_message(
    template: str,
    cita: Cita,
    tenant_profile: Optional[Dict[str, Any]] = None,
) -> str:
    """
    Renderiza la plantilla de seguimiento reemplazando los placeholders configurables.
    Placeholders soportados: {cliente_nombre}, {nombre}, {servicio}, {asesora}, {business_name}, {fecha}, {hora}.
    """
    profile = tenant_profile or {}
    business_name = profile.get("name", "Glowlab")
    cliente_nombre = cita.cliente_nombre or "Clienta"
    servicio = cita.servicio or "servicio"
    asesora = cita.asesora or "nuestra especialista"
    fecha = cita.fecha or ""
    hora = cita.hora or ""

    msg = template
    replacements = {
        "{cliente_nombre}": cliente_nombre,
        "{nombre}": cliente_nombre,
        "{servicio}": servicio,
        "{asesora}": asesora,
        "{business_name}": business_name,
        "{fecha}": fecha,
        "{hora}": hora,
    }
    for placeholder, val in replacements.items():
        msg = msg.replace(placeholder, str(val))

    return msg


def build_followup_message(cita: "Cita") -> str:
    """Compatibilidad con selector síncrono por defecto."""
    s = (cita.servicio or "").lower()
    if any(k in s for k in ("pestaña", "pestana", "extension", "lash")):
        return DEFAULT_FOLLOWUP_TEMPLATES["pestanas"].replace("{cliente_nombre}", cita.cliente_nombre or "Clienta").replace("{business_name}", "Glowlab").replace("{servicio}", cita.servicio or "servicio")
    if any(k in s for k in ("capilar", "cabello", "alisado", "tinte", "tratamiento", "keratina", "botox", "mechas", "corte", "hidratacion")):
        return DEFAULT_FOLLOWUP_TEMPLATES["capilar"].replace("{cliente_nombre}", cita.cliente_nombre or "Clienta").replace("{business_name}", "Glowlab").replace("{servicio}", cita.servicio or "servicio")
    return DEFAULT_FOLLOWUP_TEMPLATES["unas"].replace("{cliente_nombre}", cita.cliente_nombre or "Clienta").replace("{business_name}", "Glowlab").replace("{servicio}", cita.servicio or "servicio")


async def run_post_service_followup_check() -> int:
    """
    Job periódico (cada 5-10 minutos) que escanea reservas completadas para enviar
    mensajes de seguimiento post-servicio automatizados.

    Requisitos cumplidos:
    1. Criterio de scan: estado = 'completada' AND post_service_sent = FALSE AND hora_fin + 3h <= NOW().
    2. Update atómico: UPDATE citas SET post_service_sent = TRUE WHERE id = :id AND post_service_sent = FALSE RETURNING *
       para calificar y marcar en la misma operación sin condición de carrera ante scans solapados.
    3. Contenido dinámico configurable desde la tabla service_followups con placeholders.
    4. Ventana horaria: 8:00 AM a 9:00 PM (hora Perú). Si es de noche/madrugada, posterga marcando post_service_pending_morning = TRUE.
    5. Envío vía send_message con distributed lock por teléfono y captura en Sentry con teléfono anonimizado ante fallos.
    """
    try:
        from zoneinfo import ZoneInfo
        tz_lima = ZoneInfo("America/Lima")
    except Exception:
        tz_lima = timezone(timedelta(hours=-5))

    now_lima = datetime.now(tz_lima)
    within_window = is_within_followup_window(now_lima)
    messages_sent = 0

    try:
        async with async_session_factory() as db:
            result = await db.execute(
                select(Cita).where(
                    and_(
                        Cita.estado == "completada",
                        or_(Cita.post_service_sent.is_(False), Cita.post_service_sent == None),
                    )
                )
            )
            citas = result.scalars().all()
            if not citas:
                return 0

            for cita in citas:
                cita_id = cita.id
                tenant_id = cita.tenant_id or "glowlab"
                phone_norm = normalize_phone(cita.cliente_phone)

                # Obtener template y delay_hours configurado
                template, delay_hours = await get_service_followup_template(
                    db, tenant_id=tenant_id, service_name=cita.servicio
                )

                # Calcular hora de fin
                try:
                    fecha_str = cita.fecha or datetime.utcnow().strftime("%Y-%m-%d")
                    hora_str = cita.hora or "10:00"
                    hora_fin_str = cita.hora_fin

                    if not hora_fin_str:
                        h_start, m_start = map(int, hora_str.split(":"))
                        start_minutes = h_start * 60 + m_start + 60
                        hora_fin_str = f"{start_minutes // 60:02d}:{start_minutes % 60:02d}"

                    end_dt_naive = datetime.strptime(f"{fecha_str} {hora_fin_str}", "%Y-%m-%d %H:%M")
                    end_dt_lima = end_dt_naive.replace(tzinfo=tz_lima)
                    target_send_time = end_dt_lima + timedelta(hours=delay_hours)

                    # Verificar si ya transcurrieron las horas de espera
                    if now_lima < target_send_time:
                        continue

                except Exception as ex_dt:
                    logger.debug(f"Error calculando tiempo de cita #{cita_id}: {ex_dt}")
                    continue

                # Validar ventana horaria (8:00 AM - 9:00 PM)
                if not within_window:
                    # Defer para la mañana
                    try:
                        await db.execute(
                            update(Cita)
                            .where(Cita.id == cita_id, Cita.post_service_sent == False)
                            .values(post_service_pending_morning=True, updated_at=datetime.utcnow())
                        )
                        await db.commit()
                        logger.info(
                            f"🌙 [POST-SERVICE DEFERRED] Cita #{cita_id} postergada para la mañana "
                            f"(fuera de ventana 8am-9pm Perú: {now_lima.strftime('%H:%M')})."
                        )
                    except Exception as e_def:
                        logger.warning(f"Error marcando cita #{cita_id} como pending morning: {e_def}")
                    continue

                # UPDATE ATÓMICO: Calificar y marcar la fila en la misma operación
                atomic_res = await db.execute(
                    update(Cita)
                    .where(
                        and_(
                            Cita.id == cita_id,
                            Cita.post_service_sent == False,
                        )
                    )
                    .values(
                        post_service_sent=True,
                        post_service_pending_morning=False,
                        seguimiento_enviado=True,
                        updated_at=datetime.utcnow(),
                    )
                    .execution_options(synchronize_session="fetch")
                )
                await db.commit()

                # Si rowcount == 0, otro proceso/worker ya reclamó esta reserva
                if atomic_res.rowcount == 0:
                    continue

                # Preparar y enviar mensaje con lock distribuido por teléfono
                profile = await get_tenant_profile(tenant_id)
                message_text = render_followup_message(template, cita, profile)

                try:
                    async with phone_distributed_lock(phone_norm, tenant_id=tenant_id):
                        send_ok = await send_message(phone_norm, message_text)

                    if not send_ok:
                        raise RuntimeError("Evolution API retornó respuesta no exitosa.")

                    messages_sent += 1
                    logger.info(f"💌 [POST-SERVICE ENVIADO] Seguimiento post-cita enviado con éxito a #{cita_id} ({_mask_phone(phone_norm)}).")

                except Exception as e_send:
                    masked_phone = _mask_phone(phone_norm)
                    logger.error(
                        f"❌ [POST-SERVICE FALLÓ] Error enviando seguimiento a cita #{cita_id} ({masked_phone}): {e_send}"
                    )

                    # Revertir post_service_sent = False para permitir reintento en el siguiente scan
                    try:
                        await db.execute(
                            update(Cita)
                            .where(Cita.id == cita_id)
                            .values(
                                post_service_sent=False,
                                seguimiento_enviado=False,
                                updated_at=datetime.utcnow(),
                            )
                        )
                        await db.commit()
                    except Exception as e_rev:
                        logger.error(f"Error revirtiendo estado de cita #{cita_id}: {e_rev}")

                    # Captura en Sentry con teléfono anonimizado
                    try:
                        import sentry_sdk
                        with sentry_sdk.push_scope() as scope:
                            scope.set_tag("module", "post_service_followup")
                            scope.set_tag("tenant_id", tenant_id)
                            scope.set_tag("phone_masked", masked_phone)
                            scope.set_context("followup_error_info", {
                                "cita_id": cita_id,
                                "servicio": cita.servicio,
                                "error": str(e_send)[:150],
                            })
                            sentry_sdk.capture_exception(e_send)
                    except Exception:
                        pass

    except Exception as e:
        logger.error(f"Error en run_post_service_followup_check: {e}", exc_info=True)

    return messages_sent


# ============================================================
# TAREA DE RECORDATORIOS (llamada por APScheduler)
# ============================================================

async def run_reminder_check() -> None:
    """
    Verifica y envía recordatorios pendientes de citas (24h y 2h antes).
    Ejecutar periódicamente desde el scheduler en main.py.
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

            await db.commit()

    except Exception as e:
        logger.error(f"Error en run_reminder_check: {e}", exc_info=True)



# ============================================================
# MODO STAFF: PARSER Y GESTIÓN DE CITAS (LIZBETH / ANALI)
# ============================================================

def parse_hora_str(text: str) -> Optional[str]:
    """Extrae y normaliza una hora a formato HH:MM (24h)."""
    s = text.lower().strip()

    # Formato HH:MM con am/pm opcional (ej: 16:00, 11:30, 4:30 pm, 10:15am)
    match = re.search(r'\b(\d{1,2}):(\d{2})\s*(am|pm)?\b', s)
    if match:
        h = int(match.group(1))
        m = int(match.group(2))
        ampm = match.group(3)
        if ampm == "pm" and h < 12:
            h += 12
        elif ampm == "am" and h == 12:
            h = 0
        return f"{h:02d}:{m:02d}"

    # Formato H(H)am / H(H)pm (ej: 4pm, 10am, 4 pm, 11 am)
    match = re.search(r'\b(\d{1,2})\s*(am|pm)\b', s)
    if match:
        h = int(match.group(1))
        ampm = match.group(2)
        if ampm == "pm" and h < 12:
            h += 12
        elif ampm == "am" and h == 12:
            h = 0
        return f"{h:02d}:00"

    # Formato "a las 16" o "a las 4"
    match = re.search(r'(?:a las|a la)\s+(\d{1,2})\b', s)
    if match:
        h = int(match.group(1))
        if 1 <= h <= 7:
            h += 12
        return f"{h:02d}:00"

    return None


async def get_staff_citas_report(staff_name: str, timeframe: str = "hoy", all_advisors: bool = False, tenant_id: str = "glowlab") -> str:
    """Consulta la agenda en la base de datos y genera un reporte ordenado cronológicamente para un tenant."""
    today = date.today()
    if timeframe in ("mañana", "manana"):
        target_dates = [(today + timedelta(days=1)).strftime("%Y-%m-%d")]
        periodo_title = f"Mañana ({format_fecha_es(today + timedelta(days=1))})"
    elif timeframe == "semana":
        target_dates = [(today + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(7)]
        periodo_title = f"Próximos 7 días (del {format_fecha_es(today)} al {format_fecha_es(today + timedelta(days=6))})"
    else:
        target_dates = [today.strftime("%Y-%m-%d")]
        periodo_title = f"Hoy ({format_fecha_es(today)})"

    try:
        async with async_session_factory() as db:
            query = select(Cita).where(
                and_(
                    Cita.tenant_id == tenant_id,
                    Cita.fecha.in_(target_dates),
                    Cita.estado.in_(["pendiente", "confirmada"]),
                )
            )
            if not all_advisors:
                query = query.where(Cita.asesora.ilike(f"%{staff_name}%"))

            query = query.order_by(Cita.fecha.asc(), Cita.hora.asc())
            result = await db.execute(query)
            citas = result.scalars().all()
    except Exception as e:
        logger.error(f"Error consultando agenda en BD ({tenant_id}): {e}")
        return f"⚠️ Error al consultar la base de datos: {e}"

    if not citas:
        advisor_label = "todo el equipo" if all_advisors else f"ti ({staff_name})"
        return f"📅 *Agenda — Glowlab*\n\nNo hay citas activas programadas para {advisor_label} en el periodo: *{periodo_title}*. ✨"

    advisor_header = "Todo el equipo (Lizbeth y Anali)" if all_advisors else staff_name
    lines = [
        f"📋 *Agenda de Citas — Glowlab*",
        f"👤 Asesora: *{advisor_header}*",
        f"📅 Periodo: *{periodo_title}*",
        f"Total: *{len(citas)} cita(s)*\n",
    ]

    for c in citas:
        hora_str = format_hora_12h(c.hora) if c.hora else "Hora por definir"
        fecha_obj = parse_fecha(c.fecha) if c.fecha else None
        fecha_label = f" ({format_fecha_es(fecha_obj)})" if timeframe == "semana" and fecha_obj else ""
        pago_status = "Adelanto Confirmado ✅" if c.adelanto_pagado else "Pendiente de adelanto ⏳"
        advisor_tag = f" | 👩‍🦰 {c.asesora}" if all_advisors and c.asesora else ""

        lines.append(
            f"• *[ID: {c.id}]* 🕒 *{hora_str}*{fecha_label}{advisor_tag}\n"
            f"   👤 Clienta: {c.cliente_nombre or 'Sin nombre'} (📱 +{c.cliente_phone})\n"
            f"   💇‍♀️ Servicio: {c.servicio}\n"
            f"   💰 Estado: {pago_status}"
        )

    lines.append("\n💡 _Para cancelar o mover una cita usa:_ `cancelar cita <ID>` _o_ `mover cita <ID> a <fecha/hora>`")
    return "\n".join(lines)


async def cancel_staff_cita(staff_name: str, staff_phone: str, query: str, tenant_id: str = "glowlab") -> str:
    """Cancela una cita por ID o nombre de clienta dentro del tenant, registra auditoría y notifica a la clienta."""
    cita = None
    clean_q = query.strip()
    id_match = re.match(r'^(?:#|id\s*)?(\d+)$', clean_q, re.IGNORECASE)

    try:
        async with async_session_factory() as db:
            if id_match:
                cita_id = int(id_match.group(1))
                res = await db.execute(
                    select(Cita).where(
                        Cita.id == cita_id,
                        Cita.tenant_id == tenant_id
                    )
                )
                cita = res.scalar_one_or_none()
                if not cita or cita.estado == "cancelada":
                    return f"❌ No se encontró ninguna cita activa con el ID #{cita_id}."
            else:
                res = await db.execute(
                    select(Cita).where(
                        and_(
                            Cita.tenant_id == tenant_id,
                            Cita.estado.in_(["pendiente", "confirmada"]),
                            or_(
                                Cita.cliente_nombre.ilike(f"%{clean_q}%"),
                                Cita.cliente_phone.contains(clean_q),
                            )
                        )
                    ).order_by(Cita.fecha.asc(), Cita.hora.asc())
                )
                matches = res.scalars().all()

                if len(matches) == 0:
                    return f"❌ No encontré ninguna cita activa con el criterio: *{clean_q}*.\nEscribe *citas hoy* o *citas semana* para verificar la agenda."
                elif len(matches) > 1:
                    lines = [
                        f"⚠️ *Encontré {len(matches)} citas activas para '{clean_q}':*",
                        "Por favor confirma cuál deseas cancelar respondiendo con su ID exacto:\n"
                    ]
                    for m in matches:
                        f_dt = parse_fecha(m.fecha) if m.fecha else None
                        f_str = format_fecha_es(f_dt) if f_dt else m.fecha
                        h_str = format_hora_12h(m.hora) if m.hora else m.hora
                        lines.append(f"• *[ID: {m.id}]* 📅 {f_str} 🕒 {h_str} — {m.cliente_nombre} ({m.servicio}) [Asesora: {m.asesora}]")
                    lines.append(f"\n👉 Ejemplo: `cancelar cita {matches[0].id}`")
                    return "\n".join(lines)
                else:
                    cita = matches[0]

            cita.estado = "cancelada"
            cita.updated_at = datetime.utcnow()
            await db.commit()
            await db.refresh(cita)

    except Exception as e:
        logger.error(f"Error cancelando cita en BD ({tenant_id}): {e}")
        return f"⚠️ Error al cancelar la cita: {e}"

    # Auditoría
    logger.info(
        f"📋 [STAFF AUDIT] [{tenant_id}] {staff_name} ({staff_phone}) canceló Cita #{cita.id} "
        f"(Clienta: {cita.cliente_nombre}, Tel: {cita.cliente_phone}, Fecha: {cita.fecha}, Hora: {cita.hora}, Servicio: {cita.servicio})"
    )

    # Notificación a la clienta por WhatsApp
    f_dt = parse_fecha(cita.fecha) if cita.fecha else None
    f_str = format_fecha_es(f_dt) if f_dt else (cita.fecha or "fecha acordada")
    h_str = format_hora_12h(cita.hora) if cita.hora else (cita.hora or "")

    client_msg = (
        f"Hola {cita.cliente_nombre or 'Clienta'} 🌸\n\n"
        f"Te informamos que tu cita para *{cita.servicio}* programada para el *{f_str} a las {h_str}* ha sido cancelada por nuestro equipo.\n\n"
        f"Si deseas reagendar en otro horario o tienes alguna consulta, escríbenos por aquí con gusto. 💕\n"
        f"— Equipo Glowlab"
    )
    if cita.cliente_phone:
        try:
            await send_message(cita.cliente_phone, client_msg)
        except Exception as err:
            logger.warning(f"No se pudo enviar notificación de cancelación a la clienta: {err}")

    return (
        f"✅ *Cita cancelada con éxito*\n\n"
        f"🆔 Cita: *#{cita.id}*\n"
        f"👤 Clienta: {cita.cliente_nombre}\n"
        f"💇‍♀️ Servicio: {cita.servicio}\n"
        f"📅 Fecha: {f_str} a las {h_str}\n\n"
        f"📲 Se ha enviado una notificación automática a la clienta (+{cita.cliente_phone}) por WhatsApp."
    )


async def move_staff_cita(staff_name: str, staff_phone: str, query: str, tenant_id: str = "glowlab") -> str:
    """Reprograma una cita por ID o nombre de clienta dentro del tenant, registra auditoría y notifica a la clienta."""
    parts = re.split(r'\s+(?:a|para)\s+', query, maxsplit=1, flags=re.IGNORECASE)
    if len(parts) < 2:
        return (
            "❌ Formato de comando incorrecto para mover cita.\n\n"
            "👉 *Sintaxis correcta:*\n"
            "• `mover cita <ID> a <nueva fecha y hora>`\n"
            "• `mover cita <Nombre> a <nueva fecha y hora>`\n\n"
            "💡 *Ejemplo:* `mover cita 12 a mañana 4pm` o `mover cita Valeria a viernes 11am`"
        )

    target_q = parts[0].strip()
    new_spec = parts[1].strip()

    new_date = parse_fecha(new_spec)
    new_time = parse_hora_str(new_spec)

    if not new_date and not new_time:
        return (
            f"❌ No pude reconocer la nueva fecha u hora en: *'{new_spec}'*.\n\n"
            f"👉 Ejemplos válidos:\n"
            f"• `mover cita {target_q} a mañana 4pm`\n"
            f"• `mover cita {target_q} a viernes 11:00`\n"
            f"• `mover cita {target_q} a 2026-08-20 15:00`"
        )

    cita = None
    id_match = re.match(r'^(?:#|id\s*)?(\d+)$', target_q, re.IGNORECASE)

    try:
        async with async_session_factory() as db:
            if id_match:
                cita_id = int(id_match.group(1))
                res = await db.execute(
                    select(Cita).where(
                        Cita.id == cita_id,
                        Cita.tenant_id == tenant_id
                    )
                )
                cita = res.scalar_one_or_none()
                if not cita or cita.estado == "cancelada":
                    return f"❌ No se encontró ninguna cita activa con el ID #{cita_id}."
            else:
                res = await db.execute(
                    select(Cita).where(
                        and_(
                            Cita.tenant_id == tenant_id,
                            Cita.estado.in_(["pendiente", "confirmada"]),
                            or_(
                                Cita.cliente_nombre.ilike(f"%{target_q}%"),
                                Cita.cliente_phone.contains(target_q),
                            )
                        )
                    ).order_by(Cita.fecha.asc(), Cita.hora.asc())
                )
                matches = res.scalars().all()

                if len(matches) == 0:
                    return f"❌ No encontré ninguna cita activa con el criterio: *{target_q}*.\nEscribe *citas hoy* o *citas semana* para ver la lista de IDs."
                elif len(matches) > 1:
                    lines = [
                        f"⚠️ *Encontré {len(matches)} citas activas para '{target_q}':*",
                        "Por favor especifica cuál deseas mover usando su ID exacto:\n"
                    ]
                    for m in matches:
                        f_dt = parse_fecha(m.fecha) if m.fecha else None
                        f_str = format_fecha_es(f_dt) if f_dt else m.fecha
                        h_str = format_hora_12h(m.hora) if m.hora else m.hora
                        lines.append(f"• *[ID: {m.id}]* 📅 {f_str} 🕒 {h_str} — {m.cliente_nombre} ({m.servicio})")
                    lines.append(f"\n👉 Ejemplo: `mover cita {matches[0].id} a {new_spec}`")
                    return "\n".join(lines)
                else:
                    cita = matches[0]

            old_fecha = cita.fecha
            old_hora = cita.hora

            if new_date:
                cita.fecha = new_date.strftime("%Y-%m-%d")
            if new_time:
                cita.hora = new_time

            cita.updated_at = datetime.utcnow()
            await db.commit()
            await db.refresh(cita)

    except Exception as e:
        logger.error(f"Error moviendo cita en BD ({tenant_id}): {e}")
        return f"⚠️ Error al reprogramar la cita: {e}"

    # Auditoría
    logger.info(
        f"📋 [STAFF AUDIT] [{tenant_id}] {staff_name} ({staff_phone}) reprogramó Cita #{cita.id} "
        f"(Clienta: {cita.cliente_nombre}, Tel: {cita.cliente_phone}) de [{old_fecha} {old_hora}] a [{cita.fecha} {cita.hora}]"
    )

    # Notificación a la clienta por WhatsApp
    f_dt = parse_fecha(cita.fecha) if cita.fecha else None
    new_f_str = format_fecha_es(f_dt) if f_dt else cita.fecha
    new_h_str = format_hora_12h(cita.hora) if cita.hora else cita.hora

    client_msg = (
        f"Hola {cita.cliente_nombre or 'Clienta'} 🌸\n\n"
        f"Te informamos que tu cita para *{cita.servicio}* ha sido reprogramada para el *{new_f_str} a las {new_h_str}* con {cita.asesora or 'nuestra especialista'}. ✨\n\n"
        f"¡Te esperamos! Si necesitas algún ajuste en el horario, sólo avísanos por este chat. 💕\n"
        f"— Equipo Glowlab"
    )
    if cita.cliente_phone:
        try:
            await send_message(cita.cliente_phone, client_msg)
        except Exception as err:
            logger.warning(f"No se pudo enviar notificación de reprogramación a la clienta: {err}")

    return (
        f"✅ *Cita reprogramada con éxito*\n\n"
        f"🆔 Cita: *#{cita.id}*\n"
        f"👤 Clienta: {cita.cliente_nombre}\n"
        f"💇‍♀️ Servicio: {cita.servicio}\n"
        f"📅 Nueva Fecha: *{new_f_str}*\n"
        f"🕒 Nueva Hora: *{new_h_str}*\n\n"
        f"📲 Se ha enviado una notificación automática a la clienta (+{cita.cliente_phone}) por WhatsApp."
    )


def get_staff_help(staff_name: str) -> str:
    """Devuelve el manual interactivo de comandos para el equipo."""
    return (
        f"👋 ¡Hola *{staff_name}*! Aquí tienes los comandos para gestionar la agenda y monitorear el sistema desde WhatsApp:\n\n"
        f"📋 *Consultar Agenda:*\n"
        f"• `citas hoy` → Citas de hoy\n"
        f"• `citas mañana` → Citas de mañana\n"
        f"• `citas semana` → Citas de los próximos 7 días\n"
        f"• `citas todas` → Citas de todo el equipo (Lizbeth y Anali)\n\n"
        f"❌ *Cancelar Cita:*\n"
        f"• `cancelar cita <ID>` → Ej: _cancelar cita 12_\n"
        f"• `cancelar cita <Nombre>` → Ej: _cancelar cita Valeria_\n\n"
        f"🔄 *Mover / Reprogramar Cita:*\n"
        f"• `mover cita <ID> a <fecha y hora>` → Ej: _mover cita 12 a mañana 4pm_\n"
        f"• `mover cita <Nombre> a <fecha y hora>` → Ej: _mover cita Valeria a viernes 11am_\n\n"
        f"💰 *Gasto y Consumo de IA (OpenAI):*\n"
        f"• `costo openai hoy` → Consumo de tokens y costo acumulado hoy\n"
        f"• `costo openai mes` → Consumo de tokens y costo acumulado del mes\n\n"
        f"💡 _Al cancelar o mover una cita, el sistema le notifica automáticamente a la clienta por WhatsApp._"
    )


async def execute_staff_command(
    staff_phone: str,
    staff_name: str,
    message: str,
    tenant_id: str = "glowlab",
) -> str:
    """
    Parser determinista de comandos para gestión de agenda por parte del Staff asociado al tenant.
    """
    raw = message.strip()
    s = raw.lower()

    # 1. Consultar Citas / Agenda
    if s in ("citas hoy", "citas", "agenda hoy", "agenda", "ver citas hoy", "mis citas hoy", "mis citas"):
        return await get_staff_citas_report(staff_name, timeframe="hoy", all_advisors=False, tenant_id=tenant_id)

    if s in ("citas mañana", "citas manana", "agenda mañana", "agenda manana", "ver citas mañana", "ver citas manana"):
        return await get_staff_citas_report(staff_name, timeframe="mañana", all_advisors=False, tenant_id=tenant_id)

    if s in ("citas semana", "agenda semana", "ver citas semana", "mis citas semana"):
        return await get_staff_citas_report(staff_name, timeframe="semana", all_advisors=False, tenant_id=tenant_id)

    if s in ("citas todas", "agenda todas", "citas todas hoy", "ver todas las citas"):
        return await get_staff_citas_report(staff_name, timeframe="hoy", all_advisors=True, tenant_id=tenant_id)

    if s in ("citas todas mañana", "citas todas manana"):
        return await get_staff_citas_report(staff_name, timeframe="mañana", all_advisors=True, tenant_id=tenant_id)

    if s in ("citas todas semana", "todas las citas semana"):
        return await get_staff_citas_report(staff_name, timeframe="semana", all_advisors=True, tenant_id=tenant_id)

    # 2. Cancelar Cita (cancelar cita <query>, cancelar <query>, anular cita <query>)
    cancel_match = re.match(r'^(?:cancelar\s+cita|cancelar|anular\s+cita|anular)\s+(.+)$', s)
    if cancel_match:
        query = cancel_match.group(1).strip()
        return await cancel_staff_cita(staff_name, staff_phone, query, tenant_id=tenant_id)

    # 3. Mover / Reprogramar Cita (mover cita <query> a <nueva_fecha_hora>, etc.)
    move_match = re.match(r'^(?:mover\s+cita|mover|reprogramar\s+cita|reprogramar|cambiar\s+cita)\s+(.+)$', s)
    if move_match:
        query = move_match.group(1).strip()
        return await move_staff_cita(staff_name, staff_phone, query, tenant_id=tenant_id)

    # 4. Reporte de Costo y Consumo OpenAI (costo openai hoy, costo openai mes, etc.)
    if any(s.startswith(k) for k in ("costo openai", "costo ia", "gasto openai", "gasto ia", "consumo openai", "consumo ia")):
        if "mes" in s:
            return await get_openai_cost_report(timeframe="mes", tenant_id=tenant_id)
        elif "semana" in s:
            return await get_openai_cost_report(timeframe="semana", tenant_id=tenant_id)
        else:
            return await get_openai_cost_report(timeframe="hoy", tenant_id=tenant_id)

    # 5. Ayuda / Comandos no reconocidos
    return get_staff_help(staff_name)

