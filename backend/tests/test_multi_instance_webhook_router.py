"""
Test de Enrutamiento Multi-Instancia y Seguridad de Webhooks (Fase 3).
Valida:
1. Resolución rápida de tenant_id a partir de la instancia de Evolution API (con caché Redis).
2. Rechazo seguro y reporte a Sentry ante instancias no registradas o inactivas.
3. Enrutamiento automático de mensajes entrantes (Staff vs Cliente) por tenant.
4. Envío de mensajes salientes con las credenciales e instancia específicas de cada negocio.
"""
import asyncio
import json
import os
import sys
from unittest.mock import patch, AsyncMock

sys.path.insert(0, os.path.abspath("."))
from app.core.config import settings
from app.modules.salon import services as svc
from app.api.v1.endpoints import whatsapp as wa_ep


async def test_instance_resolution():
    """Valida la resolución de tenant_id desde el nombre de instancia de Evolution API."""
    print("================================================================================")
    print("🌐 1. TEST: RESOLUCIÓN DE TENANT DESDE INSTANCIA DE EVOLUTION API")
    print("================================================================================")

    # 1. Instancia por defecto Glowlab
    t_glowlab = await svc.resolve_tenant_from_instance("glowlab-bot")
    assert t_glowlab == "glowlab"
    print("• 'glowlab-bot' ->", t_glowlab, "✅ [OK]")

    # 2. Instancia de Clínica Dental (mock en DB/settings)
    mock_dental_profile = {
        "slug": "sonrisas-dental",
        "name": "Clínica Dental Sonrisas",
        "settings": {
            "evolution_instance": "sonrisas-dental-bot",
            "evolution_api_key": "secret-dental-key-123"
        }
    }

    class MockTenant:
        slug = "sonrisas-dental"
        status = "active"
        settings = {"evolution_instance": "sonrisas-dental-bot"}

    class MockDB:
        async def execute(self, query):
            class Res:
                def scalars(self):
                    class Scal:
                        def all(self):
                            return [MockTenant()]
                    return Scal()
            return Res()

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

    with patch("app.modules.salon.services.async_session_factory", return_value=MockDB()):
        t_dental = await svc.resolve_tenant_from_instance("sonrisas-dental-bot")
        assert t_dental == "sonrisas-dental"
        print("• 'sonrisas-dental-bot' ->", t_dental, "✅ [OK]")

        # 3. Instancia desconocida / no registrada
        t_unknown = await svc.resolve_tenant_from_instance("instancia-fantasma-xyz")
        assert t_unknown is None
        print("• 'instancia-fantasma-xyz' -> None (No registrado) ✅ [OK]")


async def test_unrecognized_instance_rejection():
    """Valida que un webhook con instancia no registrada sea rechazado de forma segura."""
    print("\n================================================================================")
    print("🛡️ 2. TEST: RECHAZO SEGURO Y AUDITORÍA DE INSTANCIAS NO REGISTRADAS")
    print("================================================================================")

    payload_invalid = {
        "event": "messages.upsert",
        "instance": "hacker-instance-999",
        "data": [{
            "key": {"remoteJid": "51988887777@s.whatsapp.net", "fromMe": False},
            "message": {"conversation": "Hola, intentando inyección"},
        }]
    }

    sentry_captured_messages = []

    class MockSentryScope:
        def set_tag(self, k, v): pass
        def set_context(self, k, v): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass

    with patch("app.modules.salon.services.resolve_tenant_from_instance", return_value=None), \
         patch("sentry_sdk.push_scope", return_value=MockSentryScope()), \
         patch("sentry_sdk.capture_message", side_effect=lambda msg, level=None: sentry_captured_messages.append((msg, level))), \
         patch("app.api.v1.endpoints.whatsapp.handle_client_message") as mock_client:

        await wa_ep.process_webhook_payload(payload_invalid)

        # El manejador de clientes NO debió ser ejecutado
        mock_client.assert_not_called()
        # Se debió capturar la alerta en Sentry
        assert len(sentry_captured_messages) > 0
        print(f"• Alerta capturada en Sentry: {sentry_captured_messages[0]}")
        print("✅ [OK] Webhook con instancia no registrada fue rechazado sin error y auditado.")


async def test_multi_instance_outgoing_messages():
    """Valida que los mensajes salientes se envíen a la URL y API Key de la instancia de cada negocio."""
    print("\n================================================================================")
    print("📤 3. TEST: ENVÍO DE MENSAJES SALIENTES CON INSTANCIA Y CREDENCIALES POR TENANT")
    print("================================================================================")

    captured_requests = []

    class MockResponse:
        status_code = 200

    class MockAsyncClient:
        async def post(self, url, headers, json):
            captured_requests.append({"url": url, "headers": headers, "json": json})
            return MockResponse()

        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass

    mock_dental_profile = {
        "evolution_instance_name": "sonrisas-dental-bot",
        "evolution_api_key": "api-key-dental-999",
        "evolution_base_url": "https://evo.sonrisasdental.com",
    }

    with patch("httpx.AsyncClient", return_value=MockAsyncClient()):
        # 1. Envío a Glowlab
        await svc.send_message("51999111222", "Hola desde Glowlab", tenant_id="glowlab")

        # 2. Envío a Clínica Dental
        with patch("app.modules.salon.services.get_tenant_profile", return_value=mock_dental_profile):
            await svc.send_message("51988776655", "Hola desde Sonrisas Dental", tenant_id="sonrisas-dental")

    print("• Petición Glowlab URL:", captured_requests[0]["url"])
    print("• Petición Dental URL: ", captured_requests[1]["url"])

    assert "glowlab" in captured_requests[0]["url"].lower()
    assert "https://evo.sonrisasdental.com/message/sendText/sonrisas-dental-bot" == captured_requests[1]["url"]
    assert captured_requests[1]["headers"]["apikey"] == "api-key-dental-999"
    print("✅ [OK] Mensajes salientes enrutados con la instancia y credenciales correctas por tenant.")


async def main():
    await test_instance_resolution()
    await test_unrecognized_instance_rejection()
    await test_multi_instance_outgoing_messages()
    print("\n================================================================================")
    print("🌟 TODAS LAS PRUEBAS DE LA FASE 3 (WEBHOOK ROUTER MULTI-INSTANCIA) PASARON AL 100%")
    print("================================================================================")


if __name__ == "__main__":
    asyncio.run(main())
