"""Regression tests for booking context between WhatsApp turns."""
from datetime import date, timedelta
from unittest.mock import AsyncMock, patch

try:
    import pytest
except ImportError:
    class DummyPytest:
        class mark:
            @staticmethod
            def asyncio(fn):
                return fn
    pytest = DummyPytest()

from app.api.v1.endpoints.whatsapp import handle_client_message
from app.modules.salon import services as svc


class DummySession:
    async def __aenter__(self):
        return object()

    async def __aexit__(self, *args):
        return False


@pytest.mark.asyncio
async def test_date_only_turn_continues_existing_booking_context():
    test_phone = "51999999999"
    await svc.clear_state(test_phone)
    state = {"paso": "recolectando_fecha", "servicio": "pestañas", "asesora": "lizbeth"}
    await svc.save_state(test_phone, state)
    next_monday = date.today() + timedelta(days=(7 - date.today().weekday()) % 7 or 7)
    sent = []

    with (
        patch("app.api.v1.endpoints.whatsapp.svc.send_message", new=AsyncMock(side_effect=lambda _, text: sent.append(text))),
    ):
        await handle_client_message(test_phone, "Cliente", "Para el lunes próximo", {}, {})

    state_after = await svc.load_state(test_phone)
    assert state_after["servicio"] == "pestañas"
    assert state_after["fecha"] == next_monday.isoformat()
    assert state_after["paso"] == "mostrando_horarios"
    assert len(sent) == 1


@pytest.mark.asyncio
async def test_payment_question_keeps_existing_booking_context():
    test_phone = "51999999998"
    await svc.clear_state(test_phone)
    state = {"paso": "mostrando_horarios", "servicio": "pestañas", "fecha": "2026-08-17"}
    await svc.save_state(test_phone, state)
    sent = []

    with (
        patch("app.api.v1.endpoints.whatsapp.svc.send_message", new=AsyncMock(side_effect=lambda _, text: sent.append(text))),
    ):
        await handle_client_message(test_phone, "Cliente", "¿Cuánto debo pagar para reservar?", {}, {})

    state_after = await svc.load_state(test_phone)
    assert state_after["servicio"] == "pestañas"
    assert state_after["fecha"] == "2026-08-17"
    assert state_after["paso"] == "mostrando_horarios"
    assert len(sent) == 1
    assert "S/" in sent[0] or "20" in sent[0]


async def main():
    await test_date_only_turn_continues_existing_booking_context()
    await test_payment_question_keeps_existing_booking_context()
    print("✅ [OK] test_conversation_state pasó exitosamente.")


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
