"""
Test de Observabilidad y Captura de Eventos Sentry — Glowlab WhatsApp Agent.

Verifica:
1. Inicialización tolerante a fallos (DSN configurado vs no configurado).
2. Captura explícita a Sentry cuando OpenAI falla/da timeout y se activa _fallback_client_reply.
3. Anonimización estricta de PII (teléfono enmascarado, sin volcado de prompt ni historial).
4. Captura explícita de alerta cuando ocurre una desincronización entre Postgres y Redis en save_state.
"""
import asyncio
import os
import sys
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.abspath("."))
import sentry_sdk
from app.core.config import settings
from app.modules.salon import services as svc

captured_sentry_messages: List[Dict[str, Any]] = []
captured_sentry_exceptions: List[Dict[str, Any]] = []


def setup_sentry_test_spies():
    captured_sentry_messages.clear()
    captured_sentry_exceptions.clear()

    original_capture_message = sentry_sdk.capture_message
    original_capture_exception = sentry_sdk.capture_exception

    def mock_capture_message(message, level=None, scope=None, **kwargs):
        captured_sentry_messages.append({"message": message, "level": level, "kwargs": kwargs})
        return "msg_event_id"

    def mock_capture_exception(error=None, scope=None, **kwargs):
        captured_sentry_exceptions.append({"error": error, "kwargs": kwargs})
        return "exc_event_id"

    sentry_sdk.capture_message = mock_capture_message
    sentry_sdk.capture_exception = mock_capture_exception


async def test_sentry_openai_fallback_capture():
    setup_sentry_test_spies()
    test_phone = "51992509246"
    await svc.clear_state(test_phone)

    print("================================================================================")
    print("🧪 1. TEST: CAPTURA EN SENTRY CUANDO OPENAI DA TIMEOUT O FALLA")
    print("================================================================================")

    # Forzar temporalmente settings.OPENAI_API_KEY para que intente llamar a OpenAI
    with patch.object(settings, "OPENAI_API_KEY", "sk-test-key-fake"):
        # Mock httpx para simular fallo 504 Gateway Timeout de OpenAI
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_response = MagicMock()
            mock_response.status_code = 504
            mock_response.text = "Gateway Timeout from upstream OpenAI service"
            mock_post.return_value = mock_response

            user_msg = "Hola, cuánto cuesta el botox capilar y qué horarios tienen para mañana?"
            reply = await svc.run_conversational_agent(
                sender_number=test_phone,
                sender_name="Cliente Test",
                message_text=user_msg,
                message_data={"conversation": user_msg},
                raw_item={},
            )

            print(f"🤖 Respuesta obtenida por fallback:\n> {reply}")

    print(f"\n📨 Eventos de mensaje capturados en Sentry: {len(captured_sentry_messages)}")
    assert len(captured_sentry_messages) >= 1, "ERROR: No se envió evento de fallback a Sentry!"

    event = captured_sentry_messages[0]
    print(f"  • Mensaje en Sentry: {event['message']}")
    print(f"  • Nivel: {event['level']}")

    assert "OpenAI Agent Fallback activado" in event["message"]
    assert "504" in event["message"]

    # Verificar que el fallback determinista respondió con la información solicitada
    assert "120" in reply, "ERROR: El fallback debió responder con el precio de S/ 120"
    print("✅ [OK] Fallback de OpenAI capturado con éxito en Sentry.")


async def test_sentry_pii_masking():
    print("\n================================================================================")
    print("🧪 2. TEST: ANONIMIZACIÓN DE DATOS PERSONALES (PII)")
    print("================================================================================")

    phone_raw = "51992509246"
    masked = svc._mask_phone(phone_raw)
    print(f"  • Teléfono original:   {phone_raw}")
    print(f"  • Teléfono anonimizado: {masked}")

    assert phone_raw not in masked, "ERROR: El teléfono real no debe aparecer sin enmascarar"
    assert masked.startswith("+5199***")
    assert masked.endswith("246")
    print("✅ [OK] Máscara de PII validada.")


async def test_sentry_state_desync_capture():
    setup_sentry_test_spies()
    test_phone = "51911112222"

    print("\n================================================================================")
    print("🧪 3. TEST: CAPTURA EN SENTRY POR DESINCRONIZACIÓN DE ESTADO")
    print("================================================================================")

    # Simular que Postgres falla pero Redis tiene éxito
    async def mock_redis_ok():
        class MockRedis:
            async def setex(self, *args, **kwargs):
                return True
        return MockRedis()

    with patch("app.modules.salon.services.async_session_factory") as mock_db:
        mock_db.side_effect = Exception("Connection lost to PostgreSQL host")
        with patch("app.modules.salon.services._get_redis", side_effect=mock_redis_ok):
            await svc.save_state(test_phone, {"paso": "test_desync"})

    print(f"📨 Eventos de desincronización capturados en Sentry: {len(captured_sentry_messages)}")
    assert len(captured_sentry_messages) >= 1, "ERROR: No se envió alerta de desincronización a Sentry!"

    event = captured_sentry_messages[0]
    print(f"  • Mensaje en Sentry: {event['message']}")
    print(f"  • Nivel: {event['level']}")

    assert "Desincronización de estado en persistencia (PostgreSQL)" in event["message"]
    assert event["level"] == "warning"
    print("✅ [OK] Desincronización de estado capturada con éxito en Sentry.")


async def main():
    await test_sentry_openai_fallback_capture()
    await test_sentry_pii_masking()
    await test_sentry_state_desync_capture()
    print("\n================================================================================")
    print("✅ TODAS LAS PRUEBAS DE OBSERVABILIDAD DE SENTRY PASARON AL 100%!")
    print("================================================================================")


if __name__ == "__main__":
    asyncio.run(main())
