"""
Test de Paridad de Function Calling y Multi-Proveedor (OpenAI vs DeepSeek).
Verifica que el agente soporte alternar de proveedor mediante AI_PROVIDER sin cambios de código,
y que el formato de tools, tool_choice y ejecución de llamadas funcione con idéntica paridad.
"""
import asyncio
import json
import os
import sys
from unittest.mock import patch, AsyncMock, MagicMock

sys.path.insert(0, os.path.abspath("."))
from app.core.config import settings
from app.modules.salon import services as svc


async def test_provider_configuration_switch():
    """Verifica que el switch de proveedor configure correctamente URLs, headers y modelos."""
    print("================================================================================")
    print("🔧 1. TEST: CONFIGURACIÓN DINÁMICA DE PROVEEDOR (OPENAI VS DEEPSEEK)")
    print("================================================================================")

    # Modo OpenAI por defecto
    with patch.object(settings, "AI_PROVIDER", "openai"), \
         patch.object(settings, "OPENAI_API_KEY", "sk-openai-key-test"):
        assert settings.get_ai_endpoint() == "https://api.openai.com/v1/chat/completions"
        assert settings.get_ai_model() == "gpt-4o-mini"
        assert settings.get_ai_headers()["Authorization"] == "Bearer sk-openai-key-test"
        assert settings.has_active_ai_key() is True
        print("✅ [OK] Configuración activa para OpenAI validada.")

    # Modo DeepSeek
    with patch.object(settings, "AI_PROVIDER", "deepseek"), \
         patch.object(settings, "DEEPSEEK_API_KEY", "sk-deepseek-key-test"):
        assert settings.get_ai_endpoint() == "https://api.deepseek.com/chat/completions"
        assert settings.get_ai_model() == "deepseek-chat"
        assert settings.get_ai_headers()["Authorization"] == "Bearer sk-deepseek-key-test"
        assert settings.has_active_ai_key() is True
        print("✅ [OK] Configuración activa para DeepSeek validada.")


async def test_deepseek_function_calling_parity():
    """Verifica que DeepSeek ejecute Function Calling con el mismo esquema de tools que OpenAI."""
    print("\n================================================================================")
    print("🤖 2. TEST: PARIDAD DE FUNCTION CALLING CON DEEPSEEK (TOOLS Y LOOP)")
    print("================================================================================")

    test_phone = "51998877665"
    state = {"nombre": "Luciana"}

    # Mock de respuesta 1 de DeepSeek (retorna tool_calls para get_services)
    mock_deepseek_response_1 = {
        "id": "deepseek-resp-1",
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_ds_12345",
                            "type": "function",
                            "function": {
                                "name": "get_services",
                                "arguments": json.dumps({"category": "capilar"})
                            }
                        }
                    ]
                }
            }
        ],
        "usage": {
            "prompt_tokens": 1250,
            "completion_tokens": 35,
            "total_tokens": 1285
        }
    }

    # Mock de respuesta 2 de DeepSeek (tras recibir el resultado de la tool, responde a la clienta)
    mock_deepseek_response_2 = {
        "id": "deepseek-resp-2",
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": "¡Hola Luciana! ✨ Para el cuidado capilar tenemos Tratamiento de hidratación (S/ 80), Botox capilar (S/ 120) y Keratina (S/ 160). ¿Cuál te gustaría conocer más?",
                    "tool_calls": None
                }
            }
        ],
        "usage": {
            "prompt_tokens": 1420,
            "completion_tokens": 60,
            "total_tokens": 1480
        }
    }

    class MockHttpxResponse:
        def __init__(self, json_data, status_code=200):
            self._json = json_data
            self.status_code = status_code
            self.text = json.dumps(json_data)

        def json(self):
            return self._json

    call_count = 0
    captured_payloads = []

    async def mock_post(url, headers, json, **kwargs):
        nonlocal call_count
        call_count += 1
        captured_payloads.append((url, headers, json))
        if call_count == 1:
            return MockHttpxResponse(mock_deepseek_response_1)
        else:
            return MockHttpxResponse(mock_deepseek_response_2)

    with patch.object(settings, "AI_PROVIDER", "deepseek"), \
         patch.object(settings, "DEEPSEEK_API_KEY", "sk-deepseek-test-key"), \
         patch("httpx.AsyncClient.post", side_effect=mock_post), \
         patch("app.modules.salon.services.load_state", return_value=state), \
         patch("app.modules.salon.services.save_state"):

        reply = await svc.run_conversational_agent(
            sender_number=test_phone,
            sender_name="Luciana",
            message_text="qué tratamientos tienen para el cabello?",
        )

        print(f"• LLM Endpoint llamado: {captured_payloads[0][0]}")
        print(f"• Modelo utilizado:     {captured_payloads[0][2]['model']}")
        print(f"• Tools enviadas:       {len(captured_payloads[0][2]['tools'])} herramientas")
        print(f"• Respuesta generada:\n  \"{reply}\"")

        assert captured_payloads[0][0] == "https://api.deepseek.com/chat/completions"
        assert captured_payloads[0][2]["model"] == "deepseek-chat"
        assert len(captured_payloads[0][2]["tools"]) == 5
        assert call_count == 2, f"Se esperaban 2 rondas de tool calling, pero hubo {call_count}"
        assert "Botox capilar" in reply and "120" in reply
        print("✅ [OK] Flujo de Function Calling con DeepSeek completado con 100% de paridad.")


async def test_deepseek_pricing_calculation():
    """Verifica que el cálculo de costos refleje las tarifas de DeepSeek ($0.14 input / $0.28 output)."""
    print("\n================================================================================")
    print("💰 3. TEST: CÁLCULO DE COSTOS CON PRECIOS DEEPSEEK")
    print("================================================================================")

    # 1,000 prompt tokens + 100 completion tokens
    cost_openai = svc.calculate_openai_cost("gpt-4o-mini", 1000, 100)
    cost_deepseek = svc.calculate_openai_cost("deepseek-chat", 1000, 100)

    print(f"• Costo gpt-4o-mini   (1k prompt + 100 out): ${cost_openai:.6f} USD")
    print(f"• Costo deepseek-chat (1k prompt + 100 out): ${cost_deepseek:.6f} USD")

    # DeepSeek input: 1000 * 0.14e-6 = 0.000140
    # DeepSeek out:   100 * 0.28e-6  = 0.000028
    # Total = 0.000168
    expected_ds_cost = round((1000 * 0.14 / 1e6) + (100 * 0.28 / 1e6), 6)
    assert cost_deepseek == expected_ds_cost
    assert cost_deepseek < cost_openai
    print("✅ [OK] Fórmula de tarificación para DeepSeek validada.")


async def main():
    await test_provider_configuration_switch()
    await test_deepseek_function_calling_parity()
    await test_deepseek_pricing_calculation()
    print("\n================================================================================")
    print("🌟 TODAS LAS PRUEBAS DE PARIDAD MULTI-PROVEEDOR PASARON EXITOSAMENTE (100%)")
    print("================================================================================")


if __name__ == "__main__":
    asyncio.run(main())
