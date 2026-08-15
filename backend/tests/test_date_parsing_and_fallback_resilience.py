"""
Test de Regresión: Parseo de Fechas Jerárquico y Resiliencia de Fallback — Glowlab Platform.

Verifica los 3 casos que fallaron en la conversación real:
1. parse_fecha("y el viernes 21 tiene disponibilidad?") debe devolver el día 21 (no el viernes 14).
2. Una pregunta ajena (ej. "cuántas trabajadoras tiene Glowlab") tras un fallo de OpenAI NO debe
   repetir el mensaje de horarios disponibles.
3. El estado de la conversación ya no se contamina prematuramente con paso='mostrando_horarios'.
"""
import asyncio
from datetime import date, timedelta
import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.abspath("."))
from app.modules.salon import services as svc


async def test_date_parsing_hierarchy():
    print("================================================================================")
    print("📅 1. TEST: PARSEO JERÁRQUICO DE FECHAS (PRIORIDAD DE NÚMERO SOBRE DÍA)")
    print("================================================================================")
    today = date.today()
    print(f"• Fecha base hoy: {today} ({svc.format_fecha_es(today)})")

    # Caso crítico del bug real
    d1 = svc.parse_fecha("y el viernes 21 tiene disponibilidad?")
    print(f"• 'y el viernes 21 tiene disponibilidad?' -> {d1}")
    assert d1 is not None, "ERROR: parse_fecha devolvió None"
    assert d1.day == 21, f"ERROR: Debió devolver el día 21, pero devolvió {d1.day} ({d1})"

    d2 = svc.parse_fecha("viernes 21")
    print(f"• 'viernes 21' -> {d2}")
    assert d2.day == 21

    d3 = svc.parse_fecha("el 21 de agosto")
    print(f"• 'el 21 de agosto' -> {d3}")
    assert d3.day == 21 and d3.month == 8

    d4 = svc.parse_fecha("martes 18")
    print(f"• 'martes 18' -> {d4}")
    assert d4.day == 18

    d5 = svc.parse_fecha("21/08")
    print(f"• '21/08' -> {d5}")
    assert d5.day == 21 and d5.month == 8

    # Día de semana solo (sin número de día)
    d6 = svc.parse_fecha("viernes")
    print(f"• 'viernes' (solo) -> {d6}")
    assert d6.weekday() == 4  # viernes

    # Relativos
    d_manana = svc.parse_fecha("mañana")
    assert d_manana == today + timedelta(days=1)
    print(f"• 'mañana' -> {d_manana}")

    d_pasado = svc.parse_fecha("pasado mañana")
    assert d_pasado == today + timedelta(days=2)
    print(f"• 'pasado mañana' -> {d_pasado}")

    print("✅ [OK] Todas las pruebas de parseo jerárquico de fechas pasaron exitosamente.")


async def test_fallback_not_stuck_on_slots():
    print("\n================================================================================")
    print("🛡️ 2. TEST: EL FALLBACK NO QUEDA PEGADO EN HORARIOS ANTE PREGUNTAS AJENAS")
    print("================================================================================")

    # Simular un estado que previamente tenía slots calculados
    corrupted_state = {
        "paso": "mostrando_horarios",
        "servicio": "Botox capilar",
        "asesora": "Lizbeth",
        "fecha": "2026-08-14",
        "slots_disponibles": ["10:00", "11:30", "14:00", "16:00"],
    }

    # Caso A: Pregunta completamente ajena a horarios
    msg_ajeno = "cuántas trabajadoras tiene Glowlab"
    reply_ajeno = svc._fallback_client_reply(corrupted_state, msg_ajeno)
    print(f"🤖 Pregunta: '{msg_ajeno}'")
    print(f"📋 Respuesta Fallback:\n{reply_ajeno}\n")

    assert "Horarios disponibles" not in reply_ajeno, "ERROR: Fallback devolvió mensaje de horarios a una pregunta ajena!"
    assert "10:00" not in reply_ajeno
    print("✅ [OK] Pregunta ajena no devolvió horarios repetitivos.")

    # Caso B: Pregunta que SÍ pide horarios o disponibilidad
    msg_horarios = "¿qué horarios tienen libres?"
    reply_horarios = svc._fallback_client_reply(corrupted_state, msg_horarios)
    print(f"🤖 Pregunta: '{msg_horarios}'")
    print(f"📋 Respuesta Fallback:\n{reply_horarios}\n")

    assert "Horarios disponibles" in reply_horarios, "ERROR: Fallback debió devolver horarios ante pregunta explícita"
    print("✅ [OK] Pregunta sobre horarios sí devolvió los slots disponibles.")


async def test_no_premature_state_mutation():
    print("\n================================================================================")
    print("🔒 3. TEST: NO HAY MUTACIÓN PREMATURA DE ESTADO ANTES DEL AGENTE")
    print("================================================================================")

    # Estado limpio
    state_mock = {"paso": "inicial"}

    with patch("app.modules.salon.services.load_state", return_value=state_mock), \
         patch("app.modules.salon.services.save_state") as mock_save, \
         patch("app.modules.salon.services.settings.OPENAI_API_KEY", ""):  # Sin OpenAI para forzar ejecución local

        reply = await svc.run_conversational_agent(
            sender_number="51999888777",
            sender_name="Valeria",
            message_text="y el viernes 21 tiene disponibilidad?",
        )

        print(f"📋 Respuesta obtenida:\n{reply}")
        # El estado no debe haber sido forzado a mostrando_horarios sin que la herramienta o lógica lo determine
        assert state_mock.get("slots_disponibles") is None, "ERROR: slots_disponibles fue contaminado prematuramente!"
        print("✅ [OK] El estado no fue contaminado prematuramente.")

    print("\n================================================================================")
    print("✅ TODAS LAS PRUEBAS DE REGRESIÓN PASARON AL 100%!")
    print("================================================================================")


if __name__ == "__main__":
    asyncio.run(test_date_parsing_hierarchy())
    asyncio.run(test_fallback_not_stuck_on_slots())
    asyncio.run(test_no_premature_state_mutation())
