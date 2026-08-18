"""
Tests para el Menú Interactivo y Control de Estados de Sesión en WhatsApp (Redis + FastAPI).

Verifica:
1. Disparadores del Menú Interactivo (Saludos e Intenciones de Agendamiento).
2. Exactitud del mensaje del menú interactivo.
3. Selección de Opción 1 -> Activa session_active = True y OpenAI toma control.
4. Selección de Opción 2 -> session_active = False, envía confirmación de asesor y bloquea IA.
5. Apagado automático de sesión tras confirmación exitosa de cita.
6. Apagado automático de sesión tras 3 horas de inactividad (10,800 segundos).
7. Reactivación del menú cuando la clienta vuelve a saludar o solicitar cita tras apagado/expiración.
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
        mock_db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None), scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))))
        mock_db.commit = AsyncMock()
        mock_db.refresh = AsyncMock()
        mock_db.add = MagicMock()
        return mock_db

    async def __aexit__(self, *args):
        return False


@pytest.fixture(autouse=True)
def setup_teardown():
    fake_redis = FakeRedis()
    svc._in_memory_state.clear()
    svc._in_memory_phone_locks.clear()

    with (
        patch("app.modules.salon.services._get_redis", new=AsyncMock(return_value=fake_redis)),
        patch("app.api.v1.endpoints.whatsapp.async_session_factory", side_effect=DummyDBSession),
        patch("app.modules.salon.services.async_session_factory", side_effect=DummyDBSession),
        patch("app.modules.salon.services.send_presence", new=AsyncMock(return_value=True)),
    ):
        yield fake_redis
        svc._in_memory_state.clear()
        svc._in_memory_phone_locks.clear()


@pytest.mark.asyncio
async def test_exact_interactive_menu_message():
    """Verifica que el mensaje del menú sea exactamente el solicitado."""
    expected = (
        "¡Hola! ✨ Bienvenida a Glowlab. \n"
        "Para brindarte una mejor atención, te invitamos a elegir una de las siguientes opciones:\n"
        "1️⃣ Asistente virtual: Para ver servicios, consultar precios y agendar tu cita de forma automática y rápida.\n"
        "2️⃣ Atención personalizada: Para consultas directas, dudas específicas o asesoría detallada.\n"
        "¿Qué opción elijes? Responde con el número."
    )
    assert svc.INTERACTIVE_MENU_MESSAGE == expected


@pytest.mark.asyncio
@pytest.mark.parametrize("greeting", [
    "Hola",
    "hola!",
    "Buenos días",
    "buenos dias",
    "Buenas tardes",
    "buenas noches",
    "Hola buenas tardes",
    "Hi",
    "Saludos",
])
async def test_greeting_triggers_interactive_menu(greeting):
    """Verifica que cualquier saludo dispare el menú interactivo con session_active = False."""
    phone = "51911110001"
    sent_messages = []

    with patch("app.modules.salon.services.send_message", new=AsyncMock(side_effect=lambda _, msg: sent_messages.append(msg))):
        await handle_client_message(
            sender_number=phone,
            sender_name="Valeria",
            message_text=greeting,
            message_data={"conversation": greeting},
            raw_item={"key": {"remoteJid": f"{phone}@s.whatsapp.net"}},
        )

    assert len(sent_messages) == 1
    assert sent_messages[0] == svc.INTERACTIVE_MENU_MESSAGE

    state = await svc.load_state(phone)
    assert state.get("session_active") is False
    assert state.get("menu_displayed") is True
    assert state.get("paso") == "menu_interactivo"


@pytest.mark.asyncio
@pytest.mark.parametrize("intent_text", [
    "quiero hacer una cita",
    "agendar",
    "reservar",
    "quiero una cita",
    "quisiera agendar una cita por favor",
    "deseo reservar",
    "sacar cita",
    "separar cita",
])
async def test_scheduling_intent_triggers_interactive_menu(intent_text):
    """Verifica que las intenciones de agendamiento disparen el menú interactivo."""
    phone = "51911110002"
    sent_messages = []

    with patch("app.modules.salon.services.send_message", new=AsyncMock(side_effect=lambda _, msg: sent_messages.append(msg))):
        await handle_client_message(
            sender_number=phone,
            sender_name="Camila",
            message_text=intent_text,
            message_data={"conversation": intent_text},
            raw_item={"key": {"remoteJid": f"{phone}@s.whatsapp.net"}},
        )

    assert len(sent_messages) == 1
    assert sent_messages[0] == svc.INTERACTIVE_MENU_MESSAGE

    state = await svc.load_state(phone)
    assert state.get("session_active") is False
    assert state.get("menu_displayed") is True


@pytest.mark.asyncio
@pytest.mark.parametrize("option_1_text", ["1", "1️⃣", "1.", "uno", "opcion 1", "opción 1", "asistente virtual"])
async def test_option_1_activates_ai_session(option_1_text):
    """
    Verifica que responder '1' active session_active = True y otorgue el control
    de la conversación a la inteligencia artificial de OpenAI.
    """
    phone = "51911110003"
    sent_messages = []

    with patch("app.modules.salon.services.send_message", new=AsyncMock(side_effect=lambda _, msg: sent_messages.append(msg))):
        # 1. Saludo inicial (recibe menú)
        await handle_client_message(
            sender_number=phone,
            sender_name="Andrea",
            message_text="Hola",
            message_data={"conversation": "Hola"},
            raw_item={"key": {"remoteJid": f"{phone}@s.whatsapp.net"}},
        )
        assert sent_messages[-1] == svc.INTERACTIVE_MENU_MESSAGE

        # 2. Selección de Opción 1
        sent_messages.clear()
        await handle_client_message(
            sender_number=phone,
            sender_name="Andrea",
            message_text=option_1_text,
            message_data={"conversation": option_1_text},
            raw_item={"key": {"remoteJid": f"{phone}@s.whatsapp.net"}},
        )

        state = await svc.load_state(phone)
        assert state.get("session_active") is True
        assert state.get("menu_displayed") is False
        assert state.get("paso") == "asistente_ia"
        assert len(sent_messages) == 1
        assert "asistente virtual" in sent_messages[0].lower() or "glowlab" in sent_messages[0].lower()

        # 3. Consulta de servicio con IA activa
        sent_messages.clear()
        with patch("app.modules.salon.services.run_conversational_agent", new=AsyncMock(return_value="El Botox capilar cuesta S/ 120 ✨")):
            await handle_client_message(
                sender_number=phone,
                sender_name="Andrea",
                message_text="¿Cuánto cuesta el botox capilar?",
                message_data={"conversation": "¿Cuánto cuesta el botox capilar?"},
                raw_item={"key": {"remoteJid": f"{phone}@s.whatsapp.net"}},
            )

        assert len(sent_messages) == 1
        assert "120" in sent_messages[0]


@pytest.mark.asyncio
@pytest.mark.parametrize("option_2_text", ["2", "2️⃣", "2.", "dos", "opcion 2", "opción 2", "atencion personalizada"])
async def test_option_2_blocks_ai_and_confirms_human_advisor(option_2_text):
    """
    Verifica que responder '2' mantenga session_active = False, envíe confirmación
    de contacto de asesor, notifique al staff y bloquee las respuestas de la IA.
    """
    phone = "51911110004"
    sent_messages = []
    staff_notifications = []

    with (
        patch("app.modules.salon.services.send_message", new=AsyncMock(side_effect=lambda _, msg: sent_messages.append(msg))),
        patch("app.modules.salon.services.notify_all_staff", new=AsyncMock(side_effect=lambda msg: staff_notifications.append(msg))),
    ):
        # 1. Saludo inicial (recibe menú)
        await handle_client_message(
            sender_number=phone,
            sender_name="Lucia",
            message_text="Buenas tardes",
            message_data={"conversation": "Buenas tardes"},
            raw_item={"key": {"remoteJid": f"{phone}@s.whatsapp.net"}},
        )

        # 2. Selección de Opción 2
        sent_messages.clear()
        await handle_client_message(
            sender_number=phone,
            sender_name="Lucia",
            message_text=option_2_text,
            message_data={"conversation": option_2_text},
            raw_item={"key": {"remoteJid": f"{phone}@s.whatsapp.net"}},
        )

        state = await svc.load_state(phone)
        assert state.get("session_active") is False
        assert state.get("paso") == "derivada"
        assert len(sent_messages) == 1
        assert sent_messages[0] == svc.HUMAN_ADVISOR_CONFIRMATION_MESSAGE
        assert len(staff_notifications) == 1
        assert "atención personalizada" in staff_notifications[0].lower() or "opción 2" in staff_notifications[0].lower()

        # 3. Mensaje posterior de la clienta (la IA debe estar bloqueada)
        sent_messages.clear()
        await handle_client_message(
            sender_number=phone,
            sender_name="Lucia",
            message_text="¿Siguen ahí? Tengo una duda urgente",
            message_data={"conversation": "¿Siguen ahí? Tengo una duda urgente"},
            raw_item={"key": {"remoteJid": f"{phone}@s.whatsapp.net"}},
        )

        # La IA no responde porque está derivada al equipo humano
        assert len(sent_messages) == 0


@pytest.mark.asyncio
async def test_auto_off_after_appointment_confirmation():
    """
    Verifica que la sesión de IA se apague automáticamente (session_active = False)
    cuando se confirma una cita con éxito (validación de voucher).
    """
    phone = "51911110005"
    state = {
        "nombre": "Sofia",
        "servicio": "botox capilar",
        "fecha": "2026-08-20",
        "hora": "15:00",
        "asesora": "anali",
        "cita_id": 999,
        "paso": "esperando_voucher",
        "session_active": True,
        "last_interaction_at": time.time(),
    }
    await svc.save_state(phone, state)

    sent_messages = []
    with (
        patch("app.modules.salon.services.send_message", new=AsyncMock(side_effect=lambda _, msg: sent_messages.append(msg))),
        patch("app.modules.salon.services.validate_voucher", new=AsyncMock(return_value=(True, "OK"))),
        patch("app.modules.salon.services.get_media_base64", new=AsyncMock(return_value="fake_base64_image")),
        patch("app.modules.salon.services.update_cita_estado", new=AsyncMock(return_value=None)),
        patch("app.modules.salon.services.notify_advisor", new=AsyncMock(return_value=None)),
    ):
        await handle_client_message(
            sender_number=phone,
            sender_name="Sofia",
            message_text="",
            message_data={"imageMessage": {"caption": ""}},
            raw_item={"key": {"remoteJid": f"{phone}@s.whatsapp.net"}},
        )

    state_after = await svc.load_state(phone)
    assert state_after.get("session_active") is False
    assert state_after.get("paso") == "cita_confirmada"
    assert len(sent_messages) == 1
    assert "confirmada" in sent_messages[0].lower()


@pytest.mark.asyncio
async def test_auto_off_after_3_hours_inactivity_and_menu_reactivation():
    """
    Verifica que la sesión de IA se desactive automáticamente tras más de 3 horas de inactividad
    (10,800 segundos), y que al volver a saludar se vuelva a mostrar el menú interactivo.
    """
    phone = "51911110006"
    now = time.time()
    four_hours_ago = now - (4 * 3600)  # Hace 4 horas

    state = {
        "nombre": "Mariana",
        "servicio": "pestañas",
        "session_active": True,
        "last_interaction_at": four_hours_ago,
        "paso": "asistente_ia",
    }
    await svc.save_state(phone, state)

    # 1. Verificar expiración
    is_active = await svc.check_session_active(state, phone)
    assert is_active is False
    assert state.get("session_active") is False

    # 2. Mariana envía un saludo tras la expiración
    sent_messages = []
    with patch("app.modules.salon.services.send_message", new=AsyncMock(side_effect=lambda _, msg: sent_messages.append(msg))):
        await handle_client_message(
            sender_number=phone,
            sender_name="Mariana",
            message_text="Hola buenas",
            message_data={"conversation": "Hola buenas"},
            raw_item={"key": {"remoteJid": f"{phone}@s.whatsapp.net"}},
        )

    # Debe recibir nuevamente el menú interactivo
    assert len(sent_messages) == 1
    assert sent_messages[0] == svc.INTERACTIVE_MENU_MESSAGE

    state_reactivated = await svc.load_state(phone)
    assert state_reactivated.get("session_active") is False
    assert state_reactivated.get("menu_displayed") is True
    assert state_reactivated.get("paso") == "menu_interactivo"


@pytest.mark.asyncio
async def test_invalid_option_response_prompts_menu_reminder():
    """Verifica que una respuesta inválida mientras el menú espera opción recuerde las 2 opciones."""
    phone = "51911110007"
    state = {
        "nombre": "Elena",
        "session_active": False,
        "menu_displayed": True,
        "paso": "menu_interactivo",
        "last_interaction_at": time.time(),
    }
    await svc.save_state(phone, state)

    sent_messages = []
    with patch("app.modules.salon.services.send_message", new=AsyncMock(side_effect=lambda _, msg: sent_messages.append(msg))):
        await handle_client_message(
            sender_number=phone,
            sender_name="Elena",
            message_text="opción 5",
            message_data={"conversation": "opción 5"},
            raw_item={"key": {"remoteJid": f"{phone}@s.whatsapp.net"}},
        )

    assert len(sent_messages) == 1
    assert sent_messages[0] == svc.MENU_INVALID_OPTION_MESSAGE
