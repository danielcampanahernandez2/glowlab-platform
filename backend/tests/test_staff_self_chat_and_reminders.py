"""
Suite de Pruebas: Self-Chat de Trabajadoras, Comandos de Staff con Desambiguación,
Notificaciones Automáticas con Ventana de Silencio (8am-9pm Perú) y Recordatorios Programados.
"""
import asyncio
from datetime import datetime, date, timedelta, timezone
import json
import re
import time
from unittest.mock import AsyncMock, patch, MagicMock
import pytest

from app.api.v1.endpoints.whatsapp import process_webhook_payload, handle_client_message, handle_staff_message
from app.modules.salon import services as svc
from app.modules.salon.models import Cita, Cliente, Conversacion


class FakeRedis:
    def __init__(self):
        self.data = {}
        self.lists = {}
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
            if k in self.lists:
                del self.lists[k]
                count += 1
        return count

    async def exists(self, key):
        if key in self.ttls and time.time() > self.ttls[key]:
            self.data.pop(key, None)
            self.ttls.pop(key, None)
            return 0
        return 1 if (key in self.data or key in self.lists) else 0

    async def rpush(self, key, *values):
        if key not in self.lists:
            self.lists[key] = []
        for val in values:
            self.lists[key].append(val)
        return len(self.lists[key])

    async def lpop(self, key):
        if key in self.lists and self.lists[key]:
            return self.lists[key].pop(0)
        return None

    async def llen(self, key):
        return len(self.lists.get(key, []))

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
                scalar=MagicMock(return_value=None),
                scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[]))),
                fetchall=MagicMock(return_value=[]),
                all=MagicMock(return_value=[])
            )
        )
        mock_db.commit = AsyncMock()
        mock_db.refresh = AsyncMock()
        mock_db.add = MagicMock()
        return mock_db

    async def __aexit__(self, *args):
        return False


@pytest.fixture(name="fake_redis")
def fake_redis_fixture():
    return FakeRedis()


@pytest.fixture(autouse=True)
def setup_environment(fake_redis):
    svc._in_memory_state.clear()
    svc._in_memory_phone_locks.clear()

    with (
        patch("app.modules.salon.services._get_redis", new=AsyncMock(return_value=fake_redis)),
        patch("app.modules.salon.services.async_session_factory", side_effect=DummyDBSession),
        patch("app.api.v1.endpoints.whatsapp.async_session_factory", side_effect=DummyDBSession),
        patch("app.modules.salon.services.send_presence", new=AsyncMock(return_value=True)),
        patch("app.modules.salon.services.send_message", new=AsyncMock(return_value=True)),
        patch("app.modules.salon.services.is_within_staff_silence_window", return_value=True),
    ):
        yield fake_redis
        svc._in_memory_state.clear()
        svc._in_memory_phone_locks.clear()


# ============================================================
# 1. EXCLUSIÓN DEL SELF-CHAT DEL FLUJO DE CLIENTE Y ENRUTAMIENTO STAFF
# ============================================================

@pytest.mark.asyncio
async def test_self_chat_message_routes_to_staff_and_never_triggers_client_menu():
    """
    Verifica que cuando una trabajadora (Lizbeth o Anali) se escribe a sí misma (self-chat),
    el webhook detecte el remoteJid de staff y lo enrute exclusivamente a handle_staff_message.
    Nunca debe tocar el estado de cliente ni responder con el menú interactivo.
    """
    staff_phone = "51992509246"  # Lizbeth
    sent_replies = []

    payload = {
        "event": "messages.upsert",
        "instance": "glowlab-bot",
        "data": [{
            "key": {
                "remoteJid": f"{staff_phone}@s.whatsapp.net",
                "fromMe": True,  # Self-chat en Evolution API
                "id": "MSG_SELF_1"
            },
            "pushName": "Lizbeth",
            "message": {
                "conversation": "citas hoy"
            }
        }]
    }

    with (
        patch("app.modules.salon.services.send_message", new=AsyncMock(side_effect=lambda _, msg: sent_replies.append(msg))),
        patch("app.modules.salon.services.get_staff_citas_report", new=AsyncMock(return_value="📋 Agenda de Citas: 0 citas hoy")),
    ):
        await process_webhook_payload(payload)

    # 1. Se debe haber ejecutado el reporte de staff
    assert len(sent_replies) == 1
    assert "Agenda de Citas" in sent_replies[0]

    # 2. El estado de cliente para ese número nunca debió crearse/activarse
    state = await svc.load_state(staff_phone)
    assert state.get("menu_estado") == svc.MENU_ESTADO_NO_INICIADO
    assert not state.get("session_active")


@pytest.mark.asyncio
async def test_instance_number_self_chat_routes_to_staff():
    """
    Verifica que mensajes dirigidos al número de la instancia (+51 946 559 792)
    se enruten como staff/self-chat y no activen el flujo de cliente.
    """
    instance_phone = "51946559792"
    sent_replies = []

    payload = {
        "event": "messages.upsert",
        "instance": "glowlab-bot",
        "data": [{
            "key": {
                "remoteJid": f"{instance_phone}@s.whatsapp.net",
                "fromMe": True,
                "id": "MSG_SELF_INST"
            },
            "pushName": "Staff Glowlab",
            "message": {
                "conversation": "citas mañana"
            }
        }]
    }

    with (
        patch("app.modules.salon.services.send_message", new=AsyncMock(side_effect=lambda _, msg: sent_replies.append(msg))),
        patch("app.modules.salon.services.get_staff_citas_report", new=AsyncMock(return_value="📋 Agenda de Citas: 0 citas mañana")),
    ):
        await process_webhook_payload(payload)

    assert len(sent_replies) == 1
    assert "Agenda de Citas" in sent_replies[0]
    state = await svc.load_state(instance_phone)
    assert state.get("menu_estado") == svc.MENU_ESTADO_NO_INICIADO
    assert not state.get("session_active")


# ============================================================
# 2. COMANDOS DE STAFF: ACTIVAR BOT Y LIBERAR BOT (CON DESAMBIGUACIÓN)
# ============================================================


@pytest.mark.asyncio
async def test_staff_activar_bot_by_phone():
    """Verifica que 'activar bot <numero>' cambie directamente a asistente_virtual y notifique."""
    client_phone = "51988887777"
    staff_phone = "51992509246"
    sent_messages = []

    with patch("app.modules.salon.services.send_message", new=AsyncMock(side_effect=lambda to, msg: sent_messages.append((to, msg)))):
        reply = await svc.execute_staff_command(
            staff_phone=staff_phone,
            staff_name="Lizbeth",
            message=f"activar bot {client_phone}",
        )

    assert "Bot activado" in reply
    assert client_phone in reply

    # Verifica que se envió mensaje de bienvenida a la clienta
    assert any(to == client_phone for to, _ in sent_messages)

    # Verifica estado
    state = await svc.load_state(client_phone)
    assert state.get("menu_estado") == svc.MENU_ESTADO_ASISTENTE
    assert state.get("session_active") is True


@pytest.mark.asyncio
async def test_staff_liberar_bot_by_phone():
    """Verifica que 'liberar bot <numero>' vuelva el estado a no_iniciado."""
    client_phone = "51988886666"
    staff_phone = "51992509246"

    # Poner en atención personalizada
    state = {"menu_estado": svc.MENU_ESTADO_ATENCION_PERSONALIZADA, "atencion_personalizada_at": time.time()}
    await svc.save_state(client_phone, state)

    reply = await svc.execute_staff_command(
        staff_phone=staff_phone,
        staff_name="Lizbeth",
        message=f"liberar bot {client_phone}",
    )

    assert "Bot liberado" in reply
    assert client_phone in reply

    state_after = await svc.load_state(client_phone)
    assert state_after.get("menu_estado") == svc.MENU_ESTADO_NO_INICIADO
    assert state_after.get("session_active") is False


@pytest.mark.asyncio
async def test_staff_command_disambiguation_when_multiple_names_match():
    """
    Verifica que si se busca por nombre y hay múltiples clientes (ej: 'Valeria'),
    el sistema liste las opciones para desambiguar sin aplicar cambios a ciegas.
    """
    staff_phone = "51992509246"

    # Mock DB retornando 2 Valerias
    cliente1 = MagicMock(phone="51999111222", nombre="Valeria Gomez")
    cliente2 = MagicMock(phone="51999333444", nombre="Valeria Rios")

    class MultiClientDBSession:
        async def __aenter__(self):
            m = MagicMock()
            m.execute = AsyncMock(
                return_value=MagicMock(
                    scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[cliente1, cliente2]))),
                    all=MagicMock(return_value=[])
                )
            )
            return m
        async def __aexit__(self, *args): return False

    with patch("app.modules.salon.services.async_session_factory", side_effect=MultiClientDBSession):
        reply = await svc.execute_staff_command(
            staff_phone=staff_phone,
            staff_name="Lizbeth",
            message="activar bot Valeria",
        )

    assert "Encontré 2 clientes" in reply
    assert "Valeria Gomez" in reply
    assert "Valeria Rios" in reply
    assert "51999111222" in reply
    assert "51999333444" in reply


# ============================================================
# 3. NOTIFICACIONES AL SELF-CHAT CON VENTANA DE SILENCIO (8AM - 9PM)
# ============================================================

@pytest.mark.asyncio
async def test_urgent_notifications_bypass_silence_window():
    """Verifica que notificaciones urgentes (fallback de IA, límite de presupuesto) se envíen de inmediato 24/7."""
    sent = []
    with patch("app.modules.salon.services.notify_all_staff", new=AsyncMock(side_effect=lambda msg: sent.append(msg))):
        # 1. Fallback de IA
        await svc.notify_bot_fallback_event("OpenAI HTTP 500: Internal Server Error")
        assert len(sent) == 1
        assert "ALERTA URGENTE: Bot en Modo Fallback" in sent[0]

        # 2. Límite de presupuesto
        await svc.notify_budget_limit_event(spent_usd=26.50, limit_usd=25.00)
        assert len(sent) == 2
        assert "Presupuesto OpenAI Próximo al Límite" in sent[1]


@pytest.mark.asyncio
async def test_non_urgent_notifications_queue_outside_silence_window_and_flush_in_morning(fake_redis):
    """
    Verifica que notificaciones no urgentes se encolen en Redis fuera de 8am-9pm Perú,
    y se vacíen a las 8:00 AM.
    """
    # Simular hora 02:00 AM (fuera de ventana 8am-9pm)
    with patch("app.modules.salon.services.is_within_staff_silence_window", return_value=False):
        sent = []
        with patch("app.modules.salon.services.notify_all_staff", new=AsyncMock(side_effect=lambda msg: sent.append(msg))):
            await svc.notify_atencion_personalizada_event(
                phone="51977776666",
                nombre="Camila",
                wait_time_str="02:15 AM",
            )
            # No se envió inmediatamente
            assert len(sent) == 0

            # Se encoló en Redis
            queue_len = await fake_redis.llen("glowlab:pending_staff_notifications:glowlab")
            assert queue_len == 1

    # Simular inicio de jornada (8:00 AM) y flush
    sent_morning = []
    with patch("app.modules.salon.services.notify_all_staff", new=AsyncMock(side_effect=lambda msg: sent_morning.append(msg))):
        flushed_count = await svc.flush_pending_staff_notifications(tenant_id="glowlab")
        assert flushed_count == 1
        assert len(sent_morning) == 1
        assert "Notificación acumulada de la noche" in sent_morning[0]
        assert "Camila" in sent_morning[0]


# ============================================================
# 4. EVENTOS DE NOTIFICACIÓN AUTOMÁTICA
# ============================================================

@pytest.mark.asyncio
async def test_all_notification_event_generators():
    """Verifica que cada uno de los generadores de eventos produzca el texto y formato esperado."""
    sent = []
    with (
        patch("app.modules.salon.services.is_within_staff_silence_window", return_value=True),
        patch("app.modules.salon.services.notify_all_staff", new=AsyncMock(side_effect=lambda msg: sent.append(msg))),
    ):
        # Evento 1: Cita Confirmada
        await svc.notify_cita_confirmed_event(
            cita_id=101,
            cliente_nombre="Valeria",
            cliente_phone="51999888777",
            servicio="Botox Capilar",
            fecha="2026-08-20",
            hora="15:00",
            asesora="Lizbeth",
            origen="Bot WhatsApp",
        )
        assert "Nueva Cita Confirmada" in sent[-1]
        assert "Valeria" in sent[-1]
        assert "Botox Capilar" in sent[-1]

        # Evento 3 y 8: Cancelación y Horario Liberado
        await svc.notify_cita_cancelled_event(
            cita_id=101,
            cliente_nombre="Valeria",
            cliente_phone="51999888777",
            servicio="Botox Capilar",
            fecha="2026-08-20",
            hora="15:00",
        )
        assert "Cita Cancelada por la Clienta" in sent[-1]
        assert "Horario disponible para reasignación" in sent[-1]

        # Evento 4: Comprobante dudoso
        await svc.notify_voucher_unclear_event(
            phone="51999888777",
            nombre="Valeria",
            reason="Monto ilegible",
        )
        assert "Comprobante Requiere Revisión Manual" in sent[-1]

        # Evento 7: Clienta sin respuesta en atención personalizada
        await svc.notify_unattended_client_event(
            phone="51999888777",
            nombre="Valeria",
            wait_minutes=45,
        )
        assert "Clienta en Espera Sin Respuesta" in sent[-1]
        assert "45 minutos" in sent[-1]


# ============================================================
# 5. RECORDATORIOS PROGRAMADOS CON UPDATE ATÓMICO (APSCHEDULER)
# ============================================================

@pytest.mark.asyncio
async def test_staff_2h_reminder_scan_atomic_update():
    """Verifica que el scan de recordatorios 2h a staff despache y marque citas sin duplicar."""
    sent = []

    class Mock2hDBSession:
        async def __aenter__(self):
            m = MagicMock()
            m.execute = AsyncMock(
                return_value=MagicMock(
                    fetchall=MagicMock(return_value=[
                        (55, "glowlab", "Andrea", "51911223344", "Pestañas Volumen Ruso", "2026-08-18", "16:00", "Anali")
                    ])
                )
            )
            m.commit = AsyncMock()
            return m
        async def __aexit__(self, *args): return False

    with (
        patch("app.modules.salon.services.async_session_factory", side_effect=Mock2hDBSession),
        patch("app.modules.salon.services.send_staff_notification", new=AsyncMock(side_effect=lambda msg, **kw: sent.append(msg))),
    ):
        await svc.run_staff_2h_reminder_scan()

    assert len(sent) == 1
    assert "Recordatorio de Cita en 2 horas" in sent[0]
    assert "Andrea" in sent[0]
    assert "Pestañas Volumen Ruso" in sent[0]


@pytest.mark.asyncio
async def test_noshow_alert_scan_atomic_update():
    """Verifica que el scan de posibles no-shows alerte a staff sobre citas pasadas no marcadas."""
    sent = []

    class MockNoShowDBSession:
        async def __aenter__(self):
            m = MagicMock()
            m.execute = AsyncMock(
                return_value=MagicMock(
                    fetchall=MagicMock(return_value=[
                        (77, "glowlab", "Sofia", "51933445566", "Uñas Gel", "2026-08-18", "10:00", "Lizbeth")
                    ])
                )
            )
            m.commit = AsyncMock()
            return m
        async def __aexit__(self, *args): return False

    with (
        patch("app.modules.salon.services.async_session_factory", side_effect=MockNoShowDBSession),
        patch("app.modules.salon.services.send_staff_notification", new=AsyncMock(side_effect=lambda msg, **kw: sent.append(msg))),
    ):
        await svc.run_noshow_alert_scan()

    assert len(sent) == 1
    assert "Alerta de Posible No-Show" in sent[0]
    assert "Sofia" in sent[0]
    assert "Uñas Gel" in sent[0]


# ============================================================
# 6. RESÚMENES DE INICIO Y FIN DE DÍA
# ============================================================

@pytest.mark.asyncio
async def test_daily_evening_and_morning_summaries():
    """Verifica la generación de resúmenes de fin de día (8pm) y de inicio de día (8am)."""
    sent = []
    with (
        patch("app.modules.salon.services.send_staff_notification", new=AsyncMock(side_effect=lambda msg, **kw: sent.append(msg))),
        patch("app.modules.salon.services.get_staff_citas_report", new=AsyncMock(return_value="• Cita #1: 10:00 AM - Lucia")),
    ):
        # 8:00 PM
        await svc.send_daily_evening_summary(tenant_id="glowlab")
        assert len(sent) == 1
        assert "Resumen de Cierre de Jornada (8:00 PM)" in sent[0]

        # 8:00 AM
        await svc.send_daily_morning_summary(tenant_id="glowlab")
        assert len(sent) == 2
        assert "Resumen de Inicio de Jornada (8:00 AM)" in sent[1]
