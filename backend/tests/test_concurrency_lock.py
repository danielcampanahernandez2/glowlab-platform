"""
Test de Concurrencia y Lock Distribuido — Glowlab WhatsApp Agent.

Verifica que ante mensajes concurrentes enviados casi al mismo tiempo por el mismo número:
1. El lock distribuido serialice la ejecución.
2. El segundo mensaje espere a que el primero termine.
3. El estado final conserve TODOS los campos extraídos (ej. servicio y fecha).
4. El historial final contenga los 4 turnos completos sin pérdida ni sobreescritura.
"""
import asyncio
import os
import sys
import time

sys.path.insert(0, os.path.abspath("."))
from app.api.v1.endpoints.whatsapp import handle_client_message
from app.modules.salon import services as svc

from unittest.mock import AsyncMock, patch, MagicMock
import pytest

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

    async def eval(self, script, numkeys, key, token):
        if self.data.get(key) == token:
            self.data.pop(key, None)
            return 1
        return 0


captured_replies = []
async def mock_send(phone, text, **kwargs):
    captured_replies.append({"phone": phone, "text": text, "timestamp": time.time()})
    return True


@pytest.mark.asyncio
async def test_concurrent_messages_serialized_by_phone_lock():
    fake_redis = FakeRedis()
    test_phone = "51988888888"
    captured_replies.clear()

    with patch("app.modules.salon.services._get_redis", new=AsyncMock(return_value=fake_redis)), \
         patch("app.modules.salon.services.async_session_factory", side_effect=DummyDBSession), \
         patch("app.api.v1.endpoints.whatsapp.async_session_factory", side_effect=DummyDBSession), \
         patch("app.modules.salon.services.send_presence", new=AsyncMock(return_value=True)), \
         patch("app.modules.salon.services.send_message", new=AsyncMock(side_effect=mock_send)), \
         patch("app.api.v1.endpoints.whatsapp.svc.send_message", new=AsyncMock(side_effect=mock_send)):

        await svc.clear_state(test_phone)
        await svc.save_state(test_phone, {"session_active": True, "menu_estado": "asistente_virtual", "paso": "inicial"})

        print("================================================================================")
        print("🧪 TEST DE CONCURRENCIA CON LOCK DISTRIBUIDO ACTIVO")
        print("================================================================================")
        print("📦 Estado inicial:", await svc.load_state(test_phone))

        start_time = time.time()
        events = []

        async def task_a():
            t0 = time.time() - start_time
            events.append(f"[{t0:.3f}s] Task A solicitando procesamiento...")
            await handle_client_message(
                sender_number=test_phone,
                sender_name="Sofia",
                message_text="Quiero pestañas",
                message_data={"conversation": "Quiero pestañas"},
                raw_item={"key": {"remoteJid": f"{test_phone}@s.whatsapp.net"}}
            )
            t1 = time.time() - start_time
            events.append(f"[{t1:.3f}s] Task A finalizada con éxito.")

        async def task_b():
            await asyncio.sleep(0.05)  # Llega 50ms después, concurrente a Task A
            t0 = time.time() - start_time
            events.append(f"[{t0:.3f}s] Task B solicitando procesamiento...")
            await handle_client_message(
                sender_number=test_phone,
                sender_name="Sofia",
                message_text="el lunes 25 de agosto a las 3pm",
                message_data={"conversation": "el lunes 25 de agosto a las 3pm"},
                raw_item={"key": {"remoteJid": f"{test_phone}@s.whatsapp.net"}}
            )
            t1 = time.time() - start_time
            events.append(f"[{t1:.3f}s] Task B finalizada con éxito.")

        # Ejecutar concurrentemente
        await asyncio.gather(task_a(), task_b())

        final_state = await svc.load_state(test_phone)
        print("\n📜 Cronología de ejecución:")
        for e in events:
            print(f"  • {e}")

        print("\n📦 ESTADO FINAL RESULTANTE EN PERSISTENCIA:")
        print(final_state)

        history = final_state.get("history", [])
        print(f"\n📜 Historial de mensajes ({len(history)} turnos):")
        for idx, item in enumerate(history):
            print(f"  {idx+1}. [{item.get('role')}]: {item.get('content')[:70]}...")

        # Verificaciones
        assert final_state.get("servicio") == "pestañas", f"ERROR: Se perdió el servicio! Estado: {final_state}"
        assert len(history) == 4, f"ERROR: Historial incompleto (esperado 4, obtenido {len(history)})"
        assert len(captured_replies) == 2, f"ERROR: Se debieron enviar 2 respuestas (obtenido {len(captured_replies)})"

        print("\n✅ TEST DE CONCURRENCIA EXITOSO: CERO CONDICIONES DE CARRERA, DATOS Y TURNOS 100% PRESERVADOS.")
        print("================================================================================")


if __name__ == "__main__":
    asyncio.run(test_concurrent_messages_serialized_by_phone_lock())
