"""
Tests para el Flujo del Menú Inicial de WhatsApp con Máquina de Estados 'menu_estado'.

Cubre los requerimientos actualizados:
1. Keyword repetida varias veces en no_iniciado/pendiente_seleccion reenvía el mensaje de bienvenida cada vez con el texto exacto.
2. Mensaje sin keyword y sin '1'/'2' no responde nada (silencio total en no_iniciado y pendiente_seleccion).
3. Opción '1' (y variantes) activa 'asistente_virtual' y entrega el control al agente conversacional OpenAI.
4. Opción '2' (y variantes) envía un único mensaje de confirmación, pasa a 'atencion_personalizada' y luego guarda silencio total (incluso ante keywords).
5. Keyword mientras está en 'atencion_personalizada' no genera ninguna respuesta.
6. Reset por comando de staff ('liberar bot <numero>') o expiración de 48h en 'atencion_personalizada' vuelve a 'no_iniciado'.
"""
import asyncio
import time
from unittest.mock import AsyncMock, patch, MagicMock
import pytest

from app.api.v1.endpoints.whatsapp import handle_client_message
from app.modules.salon import services as svc


class FakeRedis:
    """Simulador en memoria de Redis para pruebas ultra rápidas con soporte de TTL."""
    def __init__(self):
        self.data = {}
        self.ttls = {}

    async def get(self, key):
        if key in self.ttls and time.time() > self.ttls[key]:
            self.data.pop(key, None)
            self.ttls.pop(key, None)
            return None
        return self.data.get(key)

    async def set(self, key, value, ex=None, px=None, nx=False):
        if nx and key in self.data:
            return False
        self.data[key] = value
        if ex:
            self.ttls[key] = time.time() + ex
        return True

    async def delete(self, *keys):
        count = 0
        for k in keys:
            if k in self.data:
                del self.data[k]
                self.ttls.pop(k, None)
                count += 1
        return count

    async def exists(self, key):
        if key in self.ttls and time.time() > self.ttls[key]:
            self.data.pop(key, None)
            self.ttls.pop(key, None)
            return 0
        return 1 if key in self.data else 0

    async def eval(self, script, numkeys, key, token):
        if self.data.get(key) == token:
            self.data.pop(key, None)
            return 1
        return 0


class DummyDBSession:
    async def __aenter__(self):
        mock_db = MagicMock()
        mock_db.execute = AsyncMock(
            return_value=MagicMock(
                first=MagicMock(return_value=None),
                scalar_one_or_none=MagicMock(return_value=None),
                scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
            )
        )
        mock_db.commit = AsyncMock()
        mock_db.add = MagicMock()
        return mock_db

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass


@pytest.fixture(autouse=True)
def setup_environment():
    """Inicializa el entorno simulado en memoria para cada test."""
    fake_redis = FakeRedis()
    svc._in_memory_state.clear()
    svc._in_memory_phone_locks.clear()

    with (
        patch("app.modules.salon.services._get_redis", new=AsyncMock(return_value=fake_redis)),
        patch("app.modules.salon.services.async_session_factory", side_effect=DummyDBSession),
        patch("app.api.v1.endpoints.whatsapp.async_session_factory", side_effect=DummyDBSession),
        patch("app.modules.salon.services.send_presence", new=AsyncMock(return_value=True)),
        patch("app.modules.salon.services.notify_all_staff", new=AsyncMock(return_value=True)),
        patch("app.modules.salon.services.notify_advisor", new=AsyncMock(return_value=True)),
    ):
        yield fake_redis
        svc._in_memory_state.clear()
        svc._in_memory_phone_locks.clear()


# ============================================================
# 1. MENSAJES SIN KEYWORD Y SIN "1"/"2" -> SILENCIO TOTAL
# ============================================================

@pytest.mark.asyncio
@pytest.mark.parametrize("msg", [
    "que hiciste en la noche",
    "mañana iras",
    "ok",
    "gracias",
    "donde estan ubicados?",
    "precio de que?",
    "12345",
    "qwerty",
    "a que hora abren?",
    "no entiendo nada",
])
async def test_message_without_trigger_keyword_is_ignored(msg):
    """Verifica que mensajes sin keywords ni 1/2 no activen el menú ni respondan nada."""
    phone = f"5191111{abs(hash(msg)) % 10000:04d}"
    sent_messages = []
    with patch("app.modules.salon.services.send_message", new=AsyncMock(side_effect=lambda _, m: sent_messages.append(m))):
        await handle_client_message(
            sender_number=phone,
            sender_name="Cliente Test",
            message_text=msg,
            message_data={"conversation": msg},
            raw_item={"key": {"remoteJid": f"{phone}@s.whatsapp.net"}},
        )

    # Cero mensajes enviados
    assert len(sent_messages) == 0
    state = await svc.load_state(phone)
    assert state.get("menu_estado") == svc.MENU_ESTADO_NO_INICIADO


# ============================================================
# 2. TRIGGER SELECTIVO CON KEYWORDS Y EXACTITUD DEL MENSAJE
# ============================================================

@pytest.mark.asyncio
@pytest.mark.parametrize("trigger_msg", [
    "Hola",
    "hola!",
    "Holi",
    "Buenos días",
    "buenas tardes",
    "buenas noches",
    "hi",
    "saludos",
    "quiero una cita",
    "cita para mañana",
    "agenda por favor",
    "agendar",
    "deseo agendar",
    "quiero reservar",
    "pestañas",
    "pestanas",
    "extensiones de pestañas",
    "uñas",
    "unas",
    "diseño de uñas",
    "cabello",
    "botox capilar",
    "tratamiento de hidratación",
    "keratina",
    "alisado",
    "cejas",
    "manicure",
])
async def test_keyword_triggers_menu_once_with_exact_text(trigger_msg):
    """Verifica que cualquier keyword dispare el menú con el texto exacto especificado."""
    phone = f"5193333{abs(hash(trigger_msg)) % 10000:04d}"
    sent_messages = []
    with patch("app.modules.salon.services.send_message", new=AsyncMock(side_effect=lambda _, m: sent_messages.append(m))):
        await handle_client_message(
            sender_number=phone,
            sender_name="Valeria",
            message_text=trigger_msg,
            message_data={"conversation": trigger_msg},
            raw_item={"key": {"remoteJid": f"{phone}@s.whatsapp.net"}},
        )

    assert len(sent_messages) == 1
    expected_message = (
        "¡Hola! ✨ Bienvenida a Glowlab.\n"
        "Para brindarte una mejor atención, te invitamos a elegir una de las siguientes opciones:\n"
        "1️⃣ Asistente virtual: Para ver servicios, consultar precios y agendar tu cita de forma automática y rápida.\n"
        "2️⃣ Atención personalizada: Para consultas directas, dudas específicas o asesoría detallada.\n"
        "¿Qué opción elijes? Responde con el número 1 o 2. 😊"
    )
    assert sent_messages[0] == expected_message
    assert svc.INTERACTIVE_MENU_MESSAGE == expected_message

    state = await svc.load_state(phone)
    assert state.get("menu_estado") == svc.MENU_ESTADO_PENDIENTE
    assert state.get("session_active") is False


# ============================================================
# 3. KEYWORD REPETIDA VARIAS VECES REENVÍA EL MENÚ CADA VEZ
# ============================================================

@pytest.mark.asyncio
async def test_repeated_keywords_resends_welcome_menu_every_time():
    """
    Verifica que mientras no se haya elegido opción (no_iniciado o pendiente_seleccion),
    cada mensaje con keyword reenvíe el mensaje de bienvenida sin importar cuántas veces se envíe.
    """
    phone = "51944441111"
    sent_messages = []

    with patch("app.modules.salon.services.send_message", new=AsyncMock(side_effect=lambda _, m: sent_messages.append(m))):
        # 1. Primer trigger: "Hola"
        await handle_client_message(
            sender_number=phone,
            sender_name="Lucia",
            message_text="Hola",
            message_data={"conversation": "Hola"},
            raw_item={"key": {"remoteJid": f"{phone}@s.whatsapp.net"}},
        )
        assert len(sent_messages) == 1
        assert sent_messages[-1] == svc.INTERACTIVE_MENU_MESSAGE

        state = await svc.load_state(phone)
        assert state.get("menu_estado") == svc.MENU_ESTADO_PENDIENTE

        # 2. Mensaje irrelevante sin keyword -> Silencio (no cambia contador de mensajes enviados)
        await handle_client_message(
            sender_number=phone,
            sender_name="Lucia",
            message_text="que hiciste en la noche",
            message_data={"conversation": "que hiciste en la noche"},
            raw_item={"key": {"remoteJid": f"{phone}@s.whatsapp.net"}},
        )
        assert len(sent_messages) == 1

        # 3. Segundo trigger: "quiero una cita" -> Reenvía menú
        await handle_client_message(
            sender_number=phone,
            sender_name="Lucia",
            message_text="quiero una cita",
            message_data={"conversation": "quiero una cita"},
            raw_item={"key": {"remoteJid": f"{phone}@s.whatsapp.net"}},
        )
        assert len(sent_messages) == 2
        assert sent_messages[-1] == svc.INTERACTIVE_MENU_MESSAGE

        # 4. Tercer trigger: "pestañas" -> Reenvía menú
        await handle_client_message(
            sender_number=phone,
            sender_name="Lucia",
            message_text="pestañas por favor",
            message_data={"conversation": "pestañas por favor"},
            raw_item={"key": {"remoteJid": f"{phone}@s.whatsapp.net"}},
        )
        assert len(sent_messages) == 3
        assert sent_messages[-1] == svc.INTERACTIVE_MENU_MESSAGE

        # 5. Cuarto trigger: "cabello" -> Reenvía menú
        await handle_client_message(
            sender_number=phone,
            sender_name="Lucia",
            message_text="tratamiento para el cabello",
            message_data={"conversation": "tratamiento para el cabello"},
            raw_item={"key": {"remoteJid": f"{phone}@s.whatsapp.net"}},
        )
        assert len(sent_messages) == 4
        assert sent_messages[-1] == svc.INTERACTIVE_MENU_MESSAGE

        state_final = await svc.load_state(phone)
        assert state_final.get("menu_estado") == svc.MENU_ESTADO_PENDIENTE


# ============================================================
# 4. OPCIÓN 1 ACTIVA ASISTENTE_VIRTUAL
# ============================================================

@pytest.mark.asyncio
@pytest.mark.parametrize("opt1_text", [
    "1",
    "1️⃣",
    "1.",
    "uno",
    "opcion 1",
    "opción 1",
    "asistente virtual",
])
async def test_option_1_activates_asistente_virtual_and_agent(opt1_text):
    """Verifica que la opción 1 active asistente_virtual y entregue el control a OpenAI."""
    phone = f"5195555{abs(hash(opt1_text)) % 10000:04d}"
    state = {
        "nombre": "Camila",
        "menu_estado": svc.MENU_ESTADO_PENDIENTE,
        "session_active": False,
        "last_interaction_at": time.time(),
    }
    await svc.save_state(phone, state)

    sent_messages = []
    mock_agent_reply = "¡Hola Camila! 🌸 En Glowlab ofrecemos pestañas, uñas y tratamientos capilares. ¿Cuál te gustaría ver?"

    with (
        patch("app.modules.salon.services.run_conversational_agent", new=AsyncMock(return_value=mock_agent_reply)) as mock_agent,
        patch("app.modules.salon.services.send_message", new=AsyncMock(side_effect=lambda _, m: sent_messages.append(m))),
    ):
        await handle_client_message(
            sender_number=phone,
            sender_name="Camila",
            message_text=opt1_text,
            message_data={"conversation": opt1_text},
            raw_item={"key": {"remoteJid": f"{phone}@s.whatsapp.net"}},
        )

        mock_agent.assert_called_once()
        assert len(sent_messages) == 1
        assert sent_messages[0] == mock_agent_reply

    state_after = await svc.load_state(phone)
    assert state_after.get("menu_estado") == svc.MENU_ESTADO_ASISTENTE
    assert state_after.get("session_active") is True


# ============================================================
# 5. OPCIÓN 2 ACTIVA ATENCIÓN PERSONALIZADA Y SILENCIO TOTAL
# ============================================================

@pytest.mark.asyncio
@pytest.mark.parametrize("opt2_text", [
    "2",
    "2️⃣",
    "2.",
    "dos",
    "opcion 2",
    "opción 2",
    "atencion personalizada",
    "atención personalizada",
])
async def test_option_2_activates_atencion_personalizada_and_silences_bot_even_with_keywords(opt2_text):
    """Verifica que la opción 2 envíe 1 mensaje y luego el bot guarde silencio total incluso ante keywords."""
    phone = f"5196666{abs(hash(opt2_text)) % 10000:04d}"
    state = {
        "nombre": "Sofia",
        "menu_estado": svc.MENU_ESTADO_PENDIENTE,
        "session_active": False,
        "last_interaction_at": time.time(),
    }
    await svc.save_state(phone, state)

    sent_messages = []
    with patch("app.modules.salon.services.send_message", new=AsyncMock(side_effect=lambda _, m: sent_messages.append(m))):
        await handle_client_message(
            sender_number=phone,
            sender_name="Sofia",
            message_text=opt2_text,
            message_data={"conversation": opt2_text},
            raw_item={"key": {"remoteJid": f"{phone}@s.whatsapp.net"}},
        )

    # 1. Debe haber enviado exactamente 1 mensaje confirmando la asesora
    assert len(sent_messages) == 1
    assert "asesora" in sent_messages[0] or "asesor" in sent_messages[0]
    assert sent_messages[0] == svc.HUMAN_ADVISOR_CONFIRMATION_MESSAGE

    state_after = await svc.load_state(phone)
    assert state_after.get("menu_estado") == svc.MENU_ESTADO_ATENCION_PERSONALIZADA
    assert state_after.get("session_active") is False
    assert state_after.get("atencion_personalizada_at") is not None

    # 2. Mensajes subsiguientes con keywords deben ser TOTALMENTE IGNORADOS (Silencio total)
    sent_subsequent = []
    with (
        patch("app.modules.salon.services.run_conversational_agent", new=AsyncMock()) as mock_agent,
        patch("app.modules.salon.services.send_message", new=AsyncMock(side_effect=lambda _, m: sent_subsequent.append(m))),
    ):
        await handle_client_message(
            sender_number=phone,
            sender_name="Sofia",
            message_text="hola asesora?",
            message_data={"conversation": "hola asesora?"},
            raw_item={"key": {"remoteJid": f"{phone}@s.whatsapp.net"}},
        )
        await handle_client_message(
            sender_number=phone,
            sender_name="Sofia",
            message_text="quiero hacerme pestañas hoy y agendar cita",
            message_data={"conversation": "quiero hacerme pestañas hoy y agendar cita"},
            raw_item={"key": {"remoteJid": f"{phone}@s.whatsapp.net"}},
        )
        await handle_client_message(
            sender_number=phone,
            sender_name="Sofia",
            message_text="1",
            message_data={"conversation": "1"},
            raw_item={"key": {"remoteJid": f"{phone}@s.whatsapp.net"}},
        )

        mock_agent.assert_not_called()
        assert len(sent_subsequent) == 0


# ============================================================
# 6. RESET POR COMANDO DE STAFF ('liberar bot <numero>')
# ============================================================

@pytest.mark.asyncio
async def test_reset_by_staff_command():
    """Verifica que el comando de staff 'liberar bot <numero>' devuelva el estado a 'no_iniciado'."""
    client_phone = "51977778888"
    staff_phone = "51992509246"  # Lizbeth

    # Cliente actualmente bloqueado en atención personalizada
    state = {
        "nombre": "Andrea",
        "menu_estado": svc.MENU_ESTADO_ATENCION_PERSONALIZADA,
        "session_active": False,
        "atencion_personalizada_at": time.time(),
    }
    await svc.save_state(client_phone, state)

    # 1. Staff ejecuta comando de liberación
    reply = await svc.execute_staff_command(
        staff_phone=staff_phone,
        staff_name="Lizbeth",
        message=f"liberar bot {client_phone}",
    )
    assert "✅ Bot liberado" in reply
    assert client_phone in reply

    # 2. El estado del cliente vuelve a no_iniciado
    state_after = await svc.load_state(client_phone)
    assert state_after.get("menu_estado") == svc.MENU_ESTADO_NO_INICIADO
    assert state_after.get("session_active") is False

    # 3. El siguiente mensaje del cliente con keyword vuelve a recibir el menú
    sent_messages = []
    with patch("app.modules.salon.services.send_message", new=AsyncMock(side_effect=lambda _, m: sent_messages.append(m))):
        await handle_client_message(
            sender_number=client_phone,
            sender_name="Andrea",
            message_text="Hola buenas tardes",
            message_data={"conversation": "Hola buenas tardes"},
            raw_item={"key": {"remoteJid": f"{client_phone}@s.whatsapp.net"}},
        )

    assert len(sent_messages) == 1
    assert sent_messages[0] == svc.INTERACTIVE_MENU_MESSAGE
    state_final = await svc.load_state(client_phone)
    assert state_final.get("menu_estado") == svc.MENU_ESTADO_PENDIENTE


# ============================================================
# 7. RESET AUTOMÁTICO TRAS 48 HORAS DE INACTIVIDAD
# ============================================================

@pytest.mark.asyncio
async def test_reset_after_48_hours_inactivity():
    """Verifica que tras >48h en atencion_personalizada, el bot resetea a no_iniciado."""
    client_phone = "51988889999"
    past_timestamp = time.time() - (49 * 3600)  # Hace 49 horas

    state = {
        "nombre": "Gabriela",
        "menu_estado": svc.MENU_ESTADO_ATENCION_PERSONALIZADA,
        "session_active": False,
        "atencion_personalizada_at": past_timestamp,
        "last_interaction_at": past_timestamp,
    }
    await svc.save_state(client_phone, state)

    # 1. Mensaje con keyword tras 48h
    sent_messages = []
    with patch("app.modules.salon.services.send_message", new=AsyncMock(side_effect=lambda _, m: sent_messages.append(m))):
        await handle_client_message(
            sender_number=client_phone,
            sender_name="Gabriela",
            message_text="Hola, quiero reservar una cita",
            message_data={"conversation": "Hola, quiero reservar una cita"},
            raw_item={"key": {"remoteJid": f"{client_phone}@s.whatsapp.net"}},
        )

    # El bot detectó la expiración de 48h, reseteó y envió el menú interactivo
    assert len(sent_messages) == 1
    assert sent_messages[0] == svc.INTERACTIVE_MENU_MESSAGE

    state_after = await svc.load_state(client_phone)
    assert state_after.get("menu_estado") == svc.MENU_ESTADO_PENDIENTE
