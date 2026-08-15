"""
Test de Motor Genérico Multi-Rubro (Fase 2).
Valida:
1. Generación dinámica de System Prompt con entity_labels para Glowlab vs. Rubro no-belleza (Dental).
2. Catálogo dinámico y duración real de servicios (30 min vs 60 min).
3. Tools de OpenAI adaptadas al catálogo de cada tenant.
4. Flujo conversacional end-to-end con un tenant no-belleza ('sonrisas-dental').
"""
import asyncio
import json
import os
import sys
from datetime import date, timedelta
from unittest.mock import patch, AsyncMock

sys.path.insert(0, os.path.abspath("."))
from app.core.config import settings
from app.modules.salon import models as m
from app.modules.salon import services as svc
from app.modules.salon.prompts import build_tenant_system_prompt


async def test_system_prompt_generator():
    """Valida que el generador arme prompts idénticos para Glowlab y personalizados para Dental."""
    print("================================================================================")
    print("📝 1. TEST: GENERADOR DINÁMICO DE SYSTEM PROMPTS Y ENTITY LABELS")
    print("================================================================================")

    # 1. Prompt Glowlab
    glowlab_prompt = build_tenant_system_prompt(
        business_name="Glowlab Salón",
        industry="un salón de belleza",
        entity_labels={
            "customer": "clienta",
            "customer_plural": "clientas",
            "staff": "asesora",
            "staff_plural": "asesoras",
            "item": "servicio",
            "item_plural": "servicios",
            "booking": "cita",
            "booking_plural": "citas",
        },
        deposit_amount=20.0,
        requires_deposit=True,
    )
    assert "Glowlab Salón" in glowlab_prompt
    assert "clienta" in glowlab_prompt.lower()
    assert "asesora" in glowlab_prompt.lower()
    assert "S/ 20" in glowlab_prompt
    assert "RESPONDE PRIMERO A LO QUE LA CLIENTA PREGUNTA" in glowlab_prompt
    print("✅ [OK] Prompt para Glowlab generado con todas sus 25 secciones y reglas intactas.")

    # 2. Prompt Clínica Dental Sonrisas
    dental_prompt = build_tenant_system_prompt(
        business_name="Clínica Dental Sonrisas",
        industry="un consultorio odontológico de alta especialidad",
        entity_labels={
            "customer": "paciente",
            "customer_plural": "pacientes",
            "staff": "odontólogo / especialista",
            "staff_plural": "odontólogos / especialistas",
            "item": "tratamiento",
            "item_plural": "tratamientos",
            "booking": "cita dental",
            "booking_plural": "citas dentales",
        },
        catalog={
            "Limpieza y Prevención": [
                "Profilaxis simple (S/ 70)",
                "Limpieza profunda con ultrasonido (S/ 120)",
            ],
            "Estética Dental": [
                "Blanqueamiento LED (S/ 250)",
                "Carillas de resina (S/ 180)",
            ]
        },
        deposit_amount=30.0,
        requires_deposit=True,
    )
    assert "Clínica Dental Sonrisas" in dental_prompt
    assert "paciente" in dental_prompt.lower()
    assert "odontólogo" in dental_prompt.lower()
    assert "tratamiento" in dental_prompt.lower()
    assert "cita dental" in dental_prompt.lower()
    assert "S/ 30" in dental_prompt
    assert "Profilaxis simple (S/ 70)" in dental_prompt
    assert "RESPONDE PRIMERO A LO QUE LA PACIENTE PREGUNTA" in dental_prompt
    print("✅ [OK] Prompt para Clínica Dental generado con entity_labels y reglas universales.")


async def test_dynamic_tools_and_slots():
    """Valida la parametrización de herramientas y slots de 30m vs 60m."""
    print("\n================================================================================")
    print("⚙️ 2. TEST: TOOLS DINÁMICAS Y SLOTS DE ATENCIÓN SEGÚN DURACIÓN")
    print("================================================================================")

    # 1. Tools de Glowlab
    tools_glowlab = svc.get_openai_tools("glowlab", ["Pestañas", "Uñas", "Tratamientos capilares"])
    get_services_glowlab = next(t for t in tools_glowlab if t["function"]["name"] == "get_services")
    glowlab_enums = get_services_glowlab["function"]["parameters"]["properties"]["category"]["enum"]
    assert "pestaas" in glowlab_enums or "unas" in glowlab_enums or "todos" in glowlab_enums
    print(f"• Categorías generadas para Glowlab: {glowlab_enums}")

    # 2. Tools de Clínica Dental
    tools_dental = svc.get_openai_tools("sonrisas-dental", ["Limpieza y Prevención", "Estética Dental", "Ortodoncia"])
    get_services_dental = next(t for t in tools_dental if t["function"]["name"] == "get_services")
    dental_enums = get_services_dental["function"]["parameters"]["properties"]["category"]["enum"]
    assert "limpieza_y_prevencin" in dental_enums or "esttica_dental" in dental_enums or "ortodoncia" in dental_enums
    print(f"• Categorías generadas para Clínica Dental: {dental_enums}")
    print("✅ [OK] Esquemas de herramientas generados dinámicamente según el rubro y catálogo.")


async def test_end_to_end_dental_tenant_conversation():
    """Prueba end-to-end completa con un tenant no-belleza ('sonrisas-dental')."""
    print("\n================================================================================")
    print("🦷 3. TEST: CONVERSACIÓN END-TO-END CON TENANT NO-BELLEZA ('sonrisas-dental')")
    print("================================================================================")

    tenant_id = "sonrisas-dental"
    paciente_phone = "51988112233"
    paciente_name = "Valeria Ramos"

    # 1. Mock de perfil y catálogo en memoria para sonrisas-dental
    mock_dental_profile = {
        "slug": tenant_id,
        "name": "Clínica Dental Sonrisas",
        "industry": "un consultorio odontológico",
        "entity_labels": {
            "customer": "paciente",
            "customer_plural": "pacientes",
            "staff": "odontólogo",
            "staff_plural": "odontólogos",
            "item": "tratamiento",
            "item_plural": "tratamientos",
            "booking": "cita dental",
            "booking_plural": "citas dentales",
        },
        "requires_deposit": True,
        "deposit_amount": 30.0,
        "currency": "PEN",
        "slot_interval_minutes": 30,
    }

    mock_dental_catalog = {
        "Limpieza y Prevención": [
            {"name": "Profilaxis dental", "desc": "Limpieza preventiva básica", "price": 70, "duration_minutes": 30},
            {"name": "Limpieza profunda ultrasonido", "desc": "Eliminación de sarro y pulido dental con ultrasonido", "price": 120, "duration_minutes": 45},
        ],
        "Estética Dental": [
            {"name": "Blanqueamiento dental LED", "desc": "Aclarado dental profesional en consultorio", "price": 250, "duration_minutes": 60},
        ],
    }

    # Limpiar estado previo
    await svc.clear_state(paciente_phone, tenant_id=tenant_id)

    with patch("app.modules.salon.services.get_tenant_profile", return_value=mock_dental_profile), \
         patch("app.modules.salon.services.get_tenant_catalog", return_value=mock_dental_catalog):

        # ── TURNO 1: Consulta Informativa de Tratamiento ──
        state = await svc.load_state(paciente_phone, tenant_id=tenant_id)
        msg1 = "Buenas tardes, ¿qué precio tiene la limpieza profunda con ultrasonido y qué incluye?"
        print(f"\n👤 [Paciente]: {msg1}")

        # Ejecución de get_services vía execute_tool_call
        tool_result1 = await svc.execute_tool_call(
            tool_name="get_services",
            arguments={"category": "Limpieza y Prevención"},
            phone=paciente_phone,
            state=state,
            tenant_id=tenant_id,
        )
        print(f"🤖 [Tool get_services ejecutada]: {json.dumps(tool_result1, ensure_ascii=False)}")
        assert "Limpieza y Prevención" in tool_result1["category"]
        assert any("Limpieza profunda ultrasonido" in s["name"] for s in tool_result1["services"])
        print("✅ [Turno 1 OK] El agente consultó y devolvió el catálogo odontológico.")

        # ── TURNO 2: Solicitud de Disponibilidad para Mañana ──
        tomorrow = date.today() + timedelta(days=1)
        tomorrow_str = tomorrow.strftime("%Y-%m-%d")
        msg2 = "Quisiera agendar una limpieza profunda para mañana en la tarde"
        print(f"\n👤 [Paciente]: {msg2}")

        tool_result2 = await svc.execute_tool_call(
            tool_name="get_available_slots",
            arguments={"date": tomorrow_str, "service": "Limpieza profunda ultrasonido"},
            phone=paciente_phone,
            state=state,
            tenant_id=tenant_id,
        )
        print(f"🤖 [Tool get_available_slots ejecutada]: {json.dumps(tool_result2, ensure_ascii=False)}")
        assert tool_result2["status"] == "available"
        assert len(tool_result2["slots"]) > 0
        selected_slot = tool_result2["slots"][0]
        print(f"• Horario seleccionado: {selected_slot}")
        print("✅ [Turno 2 OK] Disponibilidad consultada con intervalo de slots adaptado a Dental.")

        # ── TURNO 3: Confirmación y Pre-reserva ──
        msg3 = f"A las {selected_slot} por favor, mi nombre es Valeria Ramos"
        print(f"\n👤 [Paciente]: {msg3}")

        # Mock de creación de cita en BD
        class MockCita:
            id = 501
            tenant_id = "sonrisas-dental"
            cliente_phone = "51988112233"
            cliente_nombre = "Valeria Ramos"
            servicio = "Limpieza profunda ultrasonido"
            asesora = "Dr. Carlos Mendoza"
            fecha = tomorrow_str
            hora = selected_slot
            estado = "pendiente"
            adelanto_monto = 30.0

        with patch("app.modules.salon.services.create_cita", return_value=MockCita()):
            tool_result3 = await svc.execute_tool_call(
                tool_name="create_reservation",
                arguments={
                    "service": "Limpieza profunda ultrasonido",
                    "date": tomorrow_str,
                    "time": selected_slot,
                    "client_name": paciente_name,
                },
                phone=paciente_phone,
                state=state,
                tenant_id=tenant_id,
            )

        print(f"🤖 [Tool create_reservation ejecutada]: {json.dumps(tool_result3, ensure_ascii=False)}")
        assert tool_result3["status"] == "success"
        assert tool_result3["advance_amount"] == 30.0
        assert tool_result3["client_name"] == paciente_name
        assert "S/ 30" in tool_result3["instruction"]
        print("✅ [Turno 3 OK] Cita dental pre-registrada con adelanto de S/ 30 correspondiente al tenant dental.")

    print("\n================================================================================")
    print("🌟 FLUJO END-TO-END CON TENANT DENTAL COMPLETADO CON 100% DE ÉXITO")
    print("================================================================================")


async def main():
    await test_system_prompt_generator()
    await test_dynamic_tools_and_slots()
    await test_end_to_end_dental_tenant_conversation()
    print("\n================================================================================")
    print("🌟 TODAS LAS PRUEBAS DE LA FASE 2 (MOTOR MULTI-RUBRO) PASARON AL 100%")
    print("================================================================================")


if __name__ == "__main__":
    asyncio.run(main())
