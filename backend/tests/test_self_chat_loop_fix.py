"""
Suite de Pruebas: Fix para Bucle Infinito en Self-Chat de Lizbeth y Deduplicación de Eventos en Tiempo Real
"""
import asyncio
import json
import time
from unittest.mock import AsyncMock, patch, MagicMock
import pytest

from app.api.v1.endpoints.whatsapp import process_webhook_payload
from app.modules.salon import services as svc


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
        if key in self.ttls and time.time() > self.ttls[key]:
            self.data.pop(key, None)
            self.ttls.pop(key, None)
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


@pytest.mark.asyncio
async def test_bot_notification_echo_is_ignored_and_breaks_loop():
    """
    FIX 1 - Escenario 1:
    El bot envía una notificación a Lizbeth (51992509246).
    Evolution API emite el webhook de eco con `fromMe=True` y el ID del mensaje enviado por el bot.
    Se confirma que el webhook se IGNERA y NO genera una respuesta recursiva (menú de ayuda).
    """
    fake_redis = FakeRedis()

    with patch("app.modules.salon.services._get_redis", return_value=fake_redis), \
         patch("httpx.AsyncClient.post") as mock_httpx_post:

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "key": {"id": "BOT_NOTIFICATION_MSG_101", "remoteJid": "51992509246@s.whatsapp.net", "fromMe": True}
        }
        mock_httpx_post.side_effect = AsyncMock(return_value=mock_response)

        sent_text = "📅 *Nueva Cita Confirmada — Glowlab*\n🆔 Cita #55\n👤 Clienta: Maria"
        sent_success = await svc.send_message("51992509246", sent_text, tenant_id="glowlab")
        assert sent_success is True

        # Verificar que el mensaje saliente quedó registrado en Redis
        is_bot_msg = await svc.is_bot_outgoing_message("BOT_NOTIFICATION_MSG_101", "51992509246", sent_text)
        assert is_bot_msg is True, "El mensaje saliente debió quedar registrado en Redis"

        # 2. Simular webhook de eco entrante (Evolution API notifica el mensaje enviado con fromMe=True)
        echo_payload = {
            "event": "messages.upsert",
            "instance": "glowlab-bot",
            "data": {
                "key": {
                    "remoteJid": "51992509246@s.whatsapp.net",
                    "fromMe": True,
                    "id": "BOT_NOTIFICATION_MSG_101"
                },
                "pushName": "Lizbeth",
                "message": {
                    "conversation": sent_text
                }
            }
        }

        # Espiar si send_message vuelve a ser llamado
        with patch("app.modules.salon.services.send_message", new_callable=AsyncMock) as spy_send_message:
            await process_webhook_payload(echo_payload)

            # CONFIRMACIÓN CRÍTICA: NO debió ejecutarse NINGÚN nuevo send_message (el bucle fue roto!)
            spy_send_message.assert_not_called()


@pytest.mark.asyncio
async def test_manual_staff_command_in_self_chat_is_processed():
    """
    FIX 1 - Escenario 2:
    Lizbeth escribe manualmente un comando ("citas hoy") desde su celular en su propio chat (fromMe=True).
    Dado que este ID NO fue generado por el bot, el sistema SÍ debe procesarlo como comando entrante de staff.
    """
    fake_redis = FakeRedis()

    with patch("app.modules.salon.services._get_redis", return_value=fake_redis), \
         patch("app.modules.salon.services.get_staff_citas_report", new_callable=AsyncMock) as mock_report, \
         patch("app.modules.salon.services.send_message", new_callable=AsyncMock) as spy_send_message:

        mock_report.return_value = ("📋 *Citas de Hoy (Lizbeth):*\n- 10:00 AM Clienta Ana", True)
        spy_send_message.return_value = True

        manual_payload = {
            "event": "messages.upsert",
            "instance": "glowlab-bot",
            "data": {
                "key": {
                    "remoteJid": "51992509246@s.whatsapp.net",
                    "fromMe": True,
                    "id": "MANUAL_HUMAN_STAFF_MSG_999"
                },
                "pushName": "Lizbeth",
                "message": {
                    "conversation": "citas hoy"
                }
            }
        }

        await process_webhook_payload(manual_payload)

        # CONFIRMACIÓN: El comando manual SÍ fue procesado y respondió el reporte de citas
        mock_report.assert_called_once()
        spy_send_message.assert_called_once()
        sent_phone, sent_response = spy_send_message.call_args[0]
        assert sent_phone == "51992509246"
        assert "Citas de Hoy" in sent_response


@pytest.mark.asyncio
async def test_event_notifications_deduplication():
    """
    FIX 2:
    Confirma la deduplicación de eventos en tiempo real con Redis SET NX (TTL 120s).
    Si un mismo evento (o webhook duplicado) se dispara 2 veces seguidas,
    la 2da llamada debe ser ignorada por la guarda de idempotencia.
    """
    fake_redis = FakeRedis()

    with patch("app.modules.salon.services._get_redis", return_value=fake_redis), \
         patch("app.modules.salon.services.send_staff_notification", new_callable=AsyncMock) as spy_staff_notify:

        spy_staff_notify.return_value = True

        # A) notify_cita_confirmed_event
        await svc.notify_cita_confirmed_event(
            cita_id=123,
            cliente_nombre="Carla",
            cliente_phone="51987654321",
            servicio="pestañas",
            fecha="2026-08-25",
            hora="15:00",
            tenant_id="glowlab"
        )
        assert spy_staff_notify.call_count == 1

        # 2do intento duplicado del mismo evento (ej: reintento de webhook)
        await svc.notify_cita_confirmed_event(
            cita_id=123,
            cliente_nombre="Carla",
            cliente_phone="51987654321",
            servicio="pestañas",
            fecha="2026-08-25",
            hora="15:00",
            tenant_id="glowlab"
        )
        # El conteo se mantiene en 1 (el duplicado fue suprimido)
        assert spy_staff_notify.call_count == 1

        # B) notify_atencion_personalizada_event
        spy_staff_notify.reset_mock()
        await svc.notify_atencion_personalizada_event(
            phone="51911112222",
            nombre="Sofia",
            tenant_id="glowlab"
        )
        assert spy_staff_notify.call_count == 1

        # 2do intento duplicado
        await svc.notify_atencion_personalizada_event(
            phone="51911112222",
            nombre="Sofia",
            tenant_id="glowlab"
        )
        assert spy_staff_notify.call_count == 1

        # C) notify_voucher_unclear_event
        spy_staff_notify.reset_mock()
        await svc.notify_voucher_unclear_event(
            phone="51933334444",
            nombre="Lucia",
            reason="Monto borroso",
            tenant_id="glowlab"
        )
        assert spy_staff_notify.call_count == 1

        # 2do intento duplicado
        await svc.notify_voucher_unclear_event(
            phone="51933334444",
            nombre="Lucia",
            reason="Monto borroso",
            tenant_id="glowlab"
        )
        assert spy_staff_notify.call_count == 1
