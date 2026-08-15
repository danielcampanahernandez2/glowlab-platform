"""
Test de Endpoints Administrativos, Facturación SaaS y Quota Guard.
Valida:
1. Seguridad y autenticación de endpoints administrativos (/api/v1/admin/*).
2. Endpoint GET /api/v1/admin/tenants/{tenant_id}/usage (tokens, gasto USD/PEN, citas vs cuota del plan).
3. Endpoint GET /api/v1/admin/billing/summary (consolidado de todos los tenants y top consumidores).
4. Quota Guard: Alerta crítica a Sentry al sobrepasar la cuota del plan sin corte abrupto del servicio.
"""
import asyncio
import json
import os
import sys
from datetime import datetime
from unittest.mock import patch, AsyncMock

from fastapi.testclient import TestClient

sys.path.insert(0, os.path.abspath("."))
from app.main import app
from app.core.config import settings
from app.modules.salon import services as svc

client = TestClient(app)
ADMIN_KEY = settings.ADMIN_API_KEY


def test_admin_auth_security():
    """Valida la protección de acceso a los endpoints administrativos."""
    print("================================================================================")
    print("🔒 1. TEST: SEGURIDAD Y AUTENTICACIÓN ADMINISTRATIVA")
    print("================================================================================")

    # 1. Petición sin credenciales -> 401
    res_no_auth = client.get("/api/v1/admin/billing/summary")
    assert res_no_auth.status_code == 401
    print("• Sin credenciales: HTTP 401 Unauthorized ✅ [OK]")

    # 2. Petición con clave incorrecta -> 403
    res_bad_auth = client.get(
        "/api/v1/admin/billing/summary",
        headers={"x-admin-api-key": "clave-falsa-123"}
    )
    assert res_bad_auth.status_code == 403
    print("• Clave incorrecta: HTTP 403 Forbidden ✅ [OK]")

    # 3. Petición con clave correcta -> 200
    res_ok = client.get(
        "/api/v1/admin/billing/summary",
        headers={"x-admin-api-key": ADMIN_KEY}
    )
    assert res_ok.status_code == 200
    print("• Clave válida: HTTP 200 OK ✅ [OK]")


def test_get_tenant_usage_endpoint():
    """Valida el endpoint de métricas de uso por tenant comparado con su plan."""
    print("\n================================================================================")
    print("📊 2. TEST: ENDPOINT DE USO POR TENANT (GET /api/v1/admin/tenants/{tenant_id}/usage)")
    print("================================================================================")

    # 1. Consulta para Glowlab (Plan Pro)
    res_glowlab = client.get(
        "/api/v1/admin/tenants/glowlab/usage",
        headers={"x-admin-api-key": ADMIN_KEY}
    )
    assert res_glowlab.status_code == 200
    data_glowlab = res_glowlab.json()
    print("📋 Respuesta Glowlab:")
    print(json.dumps(data_glowlab, indent=2, ensure_ascii=False))

    assert data_glowlab["tenant_id"] == "glowlab"
    assert data_glowlab["plan"]["name"] in ("pro", "starter")
    assert "ai_usage" in data_glowlab
    assert "appointments" in data_glowlab
    assert "quota_status" in data_glowlab
    assert data_glowlab["plan"]["max_ai_cost_usd_per_month"] == 50.0

    # 2. Consulta para Sonrisas Dental (Plan Starter)
    res_dental = client.get(
        "/api/v1/admin/tenants/sonrisas-dental/usage",
        headers={"x-admin-api-key": ADMIN_KEY}
    )
    assert res_dental.status_code == 200
    data_dental = res_dental.json()
    assert data_dental["tenant_id"] == "sonrisas-dental"
    assert data_dental["plan"]["max_ai_cost_usd_per_month"] == 15.0
    print("\n• Consulta Glowlab & Sonrisas Dental validadas con éxito ✅ [OK]")


def test_get_billing_summary_endpoint():
    """Valida el endpoint de resumen consolidado de facturación de la plataforma."""
    print("\n================================================================================")
    print("💳 3. TEST: ENDPOINT DE FACTURACIÓN GLOBAL (GET /api/v1/admin/billing/summary)")
    print("================================================================================")

    res_summary = client.get(
        "/api/v1/admin/billing/summary",
        headers={"x-admin-api-key": ADMIN_KEY}
    )
    assert res_summary.status_code == 200
    summary = res_summary.json()
    print("📋 Resumen Consolidado de Facturación:")
    print(json.dumps(summary, indent=2, ensure_ascii=False))

    assert "total_active_tenants" in summary
    assert "total_platform_ai_cost_usd" in summary
    assert "total_platform_ai_cost_pen" in summary
    assert "tenants" in summary
    assert "top_ai_consumers" in summary
    assert len(summary["tenants"]) >= 1
    print("✅ [OK] Reporte global de facturación y ranking de consumo verificado.")


async def test_quota_guard_critical_alert():
    """Valida que sobrepasar la cuota del plan dispare alerta crítica a Sentry."""
    print("\n================================================================================")
    print("🚨 4. TEST: QUOTA GUARD Y ALERTA CRÍTICA DE SOBRECONSUMO A SENTRY")
    print("================================================================================")

    sentry_captured_alerts = []

    class MockSentryScope:
        def set_tag(self, k, v): pass
        def set_context(self, k, v): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass

    # Mock DB retornando $55 USD de consumo para Glowlab (límite plan Pro: $50 USD)
    class MockDB:
        async def execute(self, query):
            class Res:
                def scalar(self): return 55.00
            return Res()

        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass

    with patch("app.modules.salon.services.async_session_factory", return_value=MockDB()), \
         patch("sentry_sdk.push_scope", return_value=MockSentryScope()), \
         patch("sentry_sdk.capture_message", side_effect=lambda msg, level=None: sentry_captured_alerts.append((msg, level))):

        await svc._check_monthly_budget_alert(tenant_id="glowlab")

    assert len(sentry_captured_alerts) > 0
    msg, level = sentry_captured_alerts[0]
    print(f"• Alerta emitida a Sentry: [{level.upper()}] {msg}")
    assert level == "error"
    assert "Alerta Crítica de Cuota SaaS" in msg
    print("✅ [OK] Quota Guard auditó el sobreconsumo como alerta crítica a Sentry sin bloquear el servicio.")


def main():
    test_admin_auth_security()
    test_get_tenant_usage_endpoint()
    test_get_billing_summary_endpoint()
    asyncio.run(test_quota_guard_critical_alert())
    print("\n================================================================================")
    print("🌟 TODAS LAS PRUEBAS DE FACTURACIÓN SAAS Y QUOTA GUARD PASARON AL 100%")
    print("================================================================================")


if __name__ == "__main__":
    main()
