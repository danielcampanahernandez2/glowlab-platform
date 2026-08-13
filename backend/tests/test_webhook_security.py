"""
Test de Seguridad y Autenticación del Webhook de WhatsApp — Glowlab Platform.

Verifica:
1. Rechazo con HTTP 401 a peticiones sin credenciales.
2. Rechazo con HTTP 401 a peticiones con secreto incorrecto.
3. Aceptación con HTTP 200 con header 'apikey'.
4. Aceptación con HTTP 200 con header 'x-webhook-secret'.
5. Aceptación con HTTP 200 con header 'Authorization: Bearer <secret>'.
6. Aceptación con HTTP 200 con query param '?token=<secret>'.
"""
import asyncio
import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.abspath("."))
import httpx
from app.core.config import settings
from app.main import app


async def test_webhook_security_suite():
    secret_test = "glowlab_test_secret_998877"

    print("================================================================================")
    print("🔒 TEST DE SEGURIDAD Y AUTENTICACIÓN DEL WEBHOOK (/api/v1/whatsapp/webhook)")
    print("================================================================================")

    sample_payload = {
        "event": "messages.upsert",
        "instance": "glowlab-bot",
        "data": {
            "key": {"remoteJid": "51911223344@s.whatsapp.net", "fromMe": False},
            "message": {"conversation": "Hola bot"}
        }
    }

    with patch("app.api.v1.endpoints.whatsapp.process_webhook_payload", return_value=None):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            with patch.object(settings, "EVOLUTION_WEBHOOK_SECRET", secret_test):
                # 1. Petición sin credenciales
                res1 = await client.post("/api/v1/whatsapp/webhook", json=sample_payload)
                print(f"1. Petición sin credenciales: HTTP {res1.status_code}")
                assert res1.status_code == 401, f"ERROR: Debió rechazar con 401 (obtenido {res1.status_code})"
                assert "Unauthorized" in res1.text
                print("   ✅ [OK] Rechazado con 401 Unauthorized.")

                # 2. Petición con secreto inválido
                res2 = await client.post(
                    "/api/v1/whatsapp/webhook",
                    headers={"apikey": "wrong_secret_123"},
                    json=sample_payload
                )
                print(f"2. Petición con secreto inválido: HTTP {res2.status_code}")
                assert res2.status_code == 401, f"ERROR: Debió rechazar con 401 (obtenido {res2.status_code})"
                print("   ✅ [OK] Rechazado con 401 Unauthorized.")

                # 3. Petición válida con header 'apikey'
                res3 = await client.post(
                    "/api/v1/whatsapp/webhook",
                    headers={"apikey": secret_test},
                    json=sample_payload
                )
                print(f"3. Petición con header 'apikey': HTTP {res3.status_code}")
                assert res3.status_code == 200, f"ERROR: Debió responder 200 (obtenido {res3.status_code})"
                print("   ✅ [OK] Aceptado con 200 OK.")

                # 4. Petición válida con header 'x-webhook-secret'
                res4 = await client.post(
                    "/api/v1/whatsapp/webhook",
                    headers={"x-webhook-secret": secret_test},
                    json=sample_payload
                )
                print(f"4. Petición con header 'x-webhook-secret': HTTP {res4.status_code}")
                assert res4.status_code == 200, f"ERROR: Debió responder 200 (obtenido {res4.status_code})"
                print("   ✅ [OK] Aceptado con 200 OK.")

                # 5. Petición válida con header 'Authorization: Bearer <secret>'
                res5 = await client.post(
                    "/api/v1/whatsapp/webhook",
                    headers={"authorization": f"Bearer {secret_test}"},
                    json=sample_payload
                )
                print(f"5. Petición con header 'Authorization: Bearer': HTTP {res5.status_code}")
                assert res5.status_code == 200, f"ERROR: Debió responder 200 (obtenido {res5.status_code})"
                print("   ✅ [OK] Aceptado con 200 OK.")

                # 6. Petición válida con query param '?token=<secret>'
                res6 = await client.post(
                    f"/api/v1/whatsapp/webhook?token={secret_test}",
                    json=sample_payload
                )
                print(f"6. Petición con query param '?token=': HTTP {res6.status_code}")
                assert res6.status_code == 200, f"ERROR: Debió responder 200 (obtenido {res6.status_code})"
                print("   ✅ [OK] Aceptado con 200 OK.")

    print("\n================================================================================")
    print("✅ TODAS LAS PRUEBAS DE SEGURIDAD DEL WEBHOOK PASARON AL 100%!")
    print("================================================================================")


if __name__ == "__main__":
    asyncio.run(test_webhook_security_suite())
