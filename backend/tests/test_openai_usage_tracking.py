"""
Test de Monitoreo de Uso, Cálculo de Costos y Alertas de Presupuesto OpenAI — Glowlab Platform.

Verifica:
1. Cálculo matemático exacto de costo según el pricing oficial de gpt-4o-mini ($0.15/1M in, $0.60/1M out).
2. Registro persistente y no bloqueante de consumo de tokens con teléfono anonimizado (PII masking).
3. Reporte de costos para el Staff por WhatsApp (comando 'costo openai hoy' / 'costo openai mes').
4. Alerta a Sentry cuando el gasto acumulado del mes supera el presupuesto configurado.
"""
import asyncio
from datetime import datetime
import os
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.abspath("."))
import sentry_sdk
from app.core.config import settings
from app.modules.salon import services as svc
from app.modules.salon.models import OpenAIUsageLog

captured_sentry_alerts = []


def setup_sentry_spies():
    captured_sentry_alerts.clear()
    original_capture = sentry_sdk.capture_message

    def mock_capture(message, level=None, **kwargs):
        captured_sentry_alerts.append({"message": message, "level": level, "kwargs": kwargs})
        return "alert_event_id"

    sentry_sdk.capture_message = mock_capture


# Mock en memoria de logs de OpenAI
class MockUsageSession:
    def __init__(self, usage_db):
        self.usage_db = usage_db

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass

    def add(self, log_entry):
        self.usage_db.append(log_entry)

    async def execute(self, query):
        class MockResult:
            def __init__(self, row, single_scalar=None):
                self._row = row
                self._single_scalar = single_scalar

            def fetchone(self):
                return self._row

            def scalar(self):
                return self._single_scalar

        query_str = str(query).lower()

        # Consulta de suma para el presupuesto mensual
        if "sum(openai_usage_logs.cost_usd)" in query_str and "count" not in query_str:
            total_sum = sum(float(x.cost_usd) for x in self.usage_db)
            return MockResult(None, single_scalar=total_sum)

        # Consulta agregada de reporte (count, sum prompt, sum compl, sum total, sum cost)
        count = len(self.usage_db)
        prompt_sum = sum(x.prompt_tokens for x in self.usage_db)
        compl_sum = sum(x.completion_tokens for x in self.usage_db)
        total_tok_sum = sum(x.total_tokens for x in self.usage_db)
        cost_sum = sum(float(x.cost_usd) for x in self.usage_db)

        return MockResult((count, prompt_sum, compl_sum, total_tok_sum, cost_sum))

    async def commit(self):
        pass


async def test_openai_usage_suite():
    setup_sentry_spies()
    print("================================================================================")
    print("💰 TEST DE MONITOREO DE COSTOS Y CONSUMO DE OPENAI (GPT-4O-MINI)")
    print("================================================================================")

    # ── 1. TEST: Cálculo de costo de un turno típico ──
    print("\n1. [Cálculo] Turno típico de Glowlab (1,650 prompt tokens + 95 completion tokens)")
    prompt_tokens = 1650
    completion_tokens = 95
    cost = svc.calculate_openai_cost("gpt-4o-mini", prompt_tokens, completion_tokens)
    
    # Expected: (1650 * 0.00000015) + (95 * 0.00000060) = 0.0002475 + 0.0000570 = $0.0003045 USD
    print(f"   • Prompt:     {prompt_tokens} tokens  -> ${prompt_tokens * 0.00000015:.6f}")
    print(f"   • Completion: {completion_tokens} tokens   -> ${completion_tokens * 0.00000060:.6f}")
    print(f"   • Costo Turno: ${cost:.6f} USD (~S/ {cost * 3.75:.4f} PEN)")

    assert 0.00029 <= cost <= 0.00032, f"ERROR: Cálculo de costo incorrecto ({cost})"
    print("   ✅ [OK] Fórmula de pricing de gpt-4o-mini validada con éxito.")

    # ── 2. TEST: Registro de llamadas y simulación de 10 turnos ──
    print("\n2. [Simulación] Registrando 10 turnos conversacionales en la base de datos...")
    usage_db = []
    
    with patch("app.modules.salon.services.async_session_factory", side_effect=lambda: MockUsageSession(usage_db)):
        for i in range(1, 11):
            p_tok = 1600 + (i * 10)
            c_tok = 80 + (i * 2)
            t_tok = p_tok + c_tok
            turn_cost = svc.calculate_openai_cost("gpt-4o-mini", p_tok, c_tok)
            
            await svc.log_openai_usage(
                phone_norm="51992509246",
                model="gpt-4o-mini",
                prompt_tokens=p_tok,
                completion_tokens=c_tok,
                total_tokens=t_tok,
                cost_usd=turn_cost,
            )

        assert len(usage_db) == 10
        print(f"   ✅ [OK] 10 turnos registrados. Teléfono anonimizado guardado: '{usage_db[0].phone_masked}'")
        assert "+5199***246" == usage_db[0].phone_masked

        # ── 3. TEST: Comando de Staff 'costo openai hoy' ──
        print("\n3. [Comando Staff] Lizbeth escribe: 'costo openai hoy'")
        report = await svc.execute_staff_command(
            staff_phone="51992509246",
            staff_name="Lizbeth",
            message="costo openai hoy",
        )
        print(f"📊 Respuesta generada:\n{report}")
        assert "Reporte de Consumo OpenAI" in report
        assert "Turnos procesados" in report and "10" in report
        assert "USD:" in report
        assert "PEN:" in report
        print("   ✅ [OK] Reporte de costos para el Staff verificado exitosamente.")

        # ── 4. TEST: Alerta a Sentry por Presupuesto Mensual Excedido ──
        print("\n4. [Alerta] Verificando alerta a Sentry al superar umbral presupuestario ($25 USD)...")
        # Simular que el gasto mensual alcanza $26.50 USD
        usage_db.append(OpenAIUsageLog(
            phone_masked="+5199***999",
            model="gpt-4o-mini",
            prompt_tokens=100000,
            completion_tokens=50000,
            total_tokens=150000,
            cost_usd=26.50,
            created_at=datetime.utcnow()
        ))

        # Reset flag para forzar chequeo
        svc._last_budget_alert_month = None
        await svc._check_monthly_budget_alert()

        assert len(captured_sentry_alerts) >= 1, "ERROR: Debió emitirse alerta a Sentry por superar el presupuesto"
        alert = captured_sentry_alerts[0]
        print(f"🚨 Alerta enviada a Sentry:\n   • Mensaje: {alert['message']}\n   • Nivel:   {alert['level']}")
        assert "Alerta de Presupuesto" in alert["message"]
        assert alert["level"] == "warning"
        print("   ✅ [OK] Alerta de presupuesto mensual a Sentry validada.")

    print("\n================================================================================")
    print("✅ TODAS LAS PRUEBAS DE CONSUMO Y COSTOS DE OPENAI PASARON AL 100%!")
    print("================================================================================")


if __name__ == "__main__":
    asyncio.run(test_openai_usage_suite())
