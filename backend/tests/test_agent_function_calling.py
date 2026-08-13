import asyncio
import os
import sys

sys.path.insert(0, os.path.abspath("."))
from app.modules.salon import services as svc
from app.core.database import async_session_factory
from sqlalchemy import select
from app.modules.salon.models import Cita

async def test_tool_definitions():
    """Verifica que las 5 herramientas requeridas estén correctamente definidas."""
    assert len(svc.OPENAI_TOOLS) == 5
    tool_names = [t["function"]["name"] for t in svc.OPENAI_TOOLS]
    assert "get_services" in tool_names
    assert "get_available_slots" in tool_names
    assert "create_reservation" in tool_names
    assert "cancel_or_reset_reservation" in tool_names
    assert "escalate_to_human" in tool_names
    print("✅ [OK] test_tool_definitions pasó exitosamente.")

async def test_execute_get_services():
    """Verifica la ejecución de get_services."""
    res_all = await svc.execute_tool_call("get_services", {}, "51999999999", {})
    assert "catalog" in res_all
    assert "Pestañas" in res_all["catalog"]

    res_capilar = await svc.execute_tool_call("get_services", {"category": "capilar"}, "51999999999", {})
    assert res_capilar["category"] == "Tratamientos capilares"
    assert len(res_capilar["services"]) >= 4
    print("✅ [OK] test_execute_get_services pasó exitosamente.")

async def test_execute_get_available_slots():
    """Verifica la ejecución de get_available_slots para días válidos y domingos."""
    state = {}
    # Lunes 17 de agosto de 2026
    res = await svc.execute_tool_call(
        "get_available_slots",
        {"date": "2026-08-17", "service": "pestañas"},
        "51999999999",
        state
    )
    assert res["status"] == "available"
    assert len(res["slots"]) > 0
    assert "10:00" in res["slots"]
    assert state.get("servicio") == "pestañas"

    # Domingo (cerrado) - Domingo 16 de agosto de 2026
    res_sun = await svc.execute_tool_call(
        "get_available_slots",
        {"date": "2026-08-16", "service": "pestañas"},
        "51999999999",
        state
    )
    assert res_sun["status"] == "closed"
    assert "cerrado" in res_sun["message"].lower()
    print("✅ [OK] test_execute_get_available_slots pasó exitosamente.")

async def test_execute_create_and_cancel_reservation():
    """Verifica la creación y posterior cancelación de citas a través de las herramientas."""
    test_phone = "51988776655"
    state = {"nombre": "Luciana"}

    # Crear reserva
    res = await svc.execute_tool_call(
        "create_reservation",
        {
            "service": "botox capilar",
            "date": "2026-08-18",
            "time": "15:00",
            "client_name": "Luciana"
        },
        test_phone,
        state
    )
    assert res["status"] == "success"
    assert res["reservation_id"] is not None
    assert res["advance_amount"] == 20
    cita_id = res["reservation_id"]

    # Verificar registro en PostgreSQL
    async with async_session_factory() as db:
        result = await db.execute(select(Cita).where(Cita.id == cita_id))
        cita = result.scalar_one_or_none()
        assert cita is not None
        assert cita.servicio == "botox capilar"
        assert cita.hora == "15:00"
        assert cita.estado == "pendiente"

    # Cancelar / resetear reserva
    res_cancel = await svc.execute_tool_call(
        "cancel_or_reset_reservation",
        {"reason": "Cambio de planes"},
        test_phone,
        state
    )
    assert res_cancel["status"] == "cancelled"
    assert state.get("servicio") is None
    print("✅ [OK] test_execute_create_and_cancel_reservation pasó exitosamente.")

async def test_run_conversational_agent_fallback():
    """Verifica que el agente conversacional responde fluidamente incluso en fallback."""
    test_phone = "51977665544"
    await svc.clear_state(test_phone)

    # 1. Saludo
    reply1 = await svc.run_conversational_agent(test_phone, "Camila", "Hola!")
    assert "¡Hola!" in reply1 or "Bienvenida" in reply1

    # 2. Consulta de precios
    reply2 = await svc.run_conversational_agent(test_phone, "Camila", "cuanto cuesta el botox capilar ?")
    assert "120" in reply2

    # 3. Consulta de catálogo
    reply3 = await svc.run_conversational_agent(test_phone, "Camila", "que servicios tienen?")
    assert "Pestañas" in reply3 and "Uñas" in reply3

    print("✅ [OK] test_run_conversational_agent_fallback pasó exitosamente.")

async def main():
    print("=== INICIANDO PRUEBAS DEL AGENTE FUNCTION CALLING ===")
    await test_tool_definitions()
    await test_execute_get_services()
    await test_execute_get_available_slots()
    await test_execute_create_and_cancel_reservation()
    await test_run_conversational_agent_fallback()
    print("======================================================")
    print("🌟 TODAS LAS PRUEBAS DEL AGENTE PASARON EXITOSAMENTE (100%)")
    print("======================================================")

if __name__ == "__main__":
    asyncio.run(main())
