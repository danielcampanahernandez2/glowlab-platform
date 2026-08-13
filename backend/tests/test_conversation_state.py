"""Regression tests for booking context between WhatsApp turns."""
from datetime import date, timedelta
from unittest.mock import AsyncMock, patch

import pytest

from app.api.v1.endpoints.whatsapp import handle_client_message


class DummySession:
    async def __aenter__(self):
        return object()

    async def __aexit__(self, *args):
        return False


@pytest.mark.asyncio
async def test_date_only_turn_continues_existing_booking_context():
    state = {"paso": "recolectando_fecha", "servicio": "pestañas", "asesora": "lizbeth"}
    next_monday = date.today() + timedelta(days=(7 - date.today().weekday()) % 7 or 7)
    sent = []

    with (
        patch("app.api.v1.endpoints.whatsapp.async_session_factory", return_value=DummySession()),
        patch("app.api.v1.endpoints.whatsapp.svc.load_state", new=AsyncMock(return_value=state)),
        patch("app.api.v1.endpoints.whatsapp.svc.extract_intent", new=AsyncMock(return_value={"intent": "otro", "servicio": None, "fecha": "lunes", "hora": None, "slot_num": None, "requiere_excepcion": False})),
        patch("app.api.v1.endpoints.whatsapp.svc.get_available_slots", new=AsyncMock(return_value=["10:00"])),
        patch("app.api.v1.endpoints.whatsapp.svc.generate_client_reply", new=AsyncMock(return_value="Horario disponible")),
        patch("app.api.v1.endpoints.whatsapp.svc.save_state", new=AsyncMock()) as save_state,
        patch("app.api.v1.endpoints.whatsapp.svc.send_message", new=AsyncMock(side_effect=lambda _, text: sent.append(text))),
    ):
        await handle_client_message("51999999999", "Cliente", "Para el lunes próximo", {}, {})

    assert state["servicio"] == "pestañas"
    assert state["fecha"] == next_monday.isoformat()
    assert state["paso"] == "mostrando_horarios"
    assert save_state.await_count == 1
    assert sent == ["Horario disponible"]


@pytest.mark.asyncio
async def test_payment_question_keeps_existing_booking_context():
    state = {"paso": "mostrando_horarios", "servicio": "pestañas", "fecha": "2026-08-17"}
    sent = []

    with (
        patch("app.api.v1.endpoints.whatsapp.async_session_factory", return_value=DummySession()),
        patch("app.api.v1.endpoints.whatsapp.svc.load_state", new=AsyncMock(return_value=state)),
        patch("app.api.v1.endpoints.whatsapp.svc.extract_intent", new=AsyncMock(return_value={"intent": "consultar", "servicio": None, "fecha": None, "hora": None, "slot_num": None, "requiere_excepcion": False})),
        patch("app.api.v1.endpoints.whatsapp.svc.save_state", new=AsyncMock()),
        patch("app.api.v1.endpoints.whatsapp.svc.send_message", new=AsyncMock(side_effect=lambda _, text: sent.append(text))),
    ):
        await handle_client_message("51999999999", "Cliente", "¿Cuánto debo pagar para reservar?", {}, {})

    assert state["servicio"] == "pestañas"
    assert state["fecha"] == "2026-08-17"
    assert state["paso"] == "mostrando_horarios"
    assert len(sent) == 1
    assert "S/" in sent[0]
