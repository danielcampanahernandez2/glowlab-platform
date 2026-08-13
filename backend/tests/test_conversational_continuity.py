import asyncio
import os
import sys

sys.path.insert(0, os.path.abspath("."))
from app.api.v1.endpoints.whatsapp import handle_client_message
from app.modules.salon import services as svc

captured_replies = []
async def mock_send(phone, text):
    captured_replies.append(text)
    return True

svc.send_message = mock_send

async def test_full_conversational_continuity():
    test_phone = "51988776655"
    await svc.clear_state(test_phone)

    # Mensaje 1: Hola
    captured_replies.clear()
    await handle_client_message(
        sender_number=test_phone,
        sender_name="Maria",
        message_text="Hola",
        message_data={"conversation": "Hola"},
        raw_item={"key": {"remoteJid": f"{test_phone}@s.whatsapp.net"}}
    )
    assert len(captured_replies) == 1
    print("[M1] Saludo OK ->", captured_replies[0][:60])

    # Mensaje 2: Quiero reservar servicio de pestañas
    captured_replies.clear()
    await handle_client_message(
        sender_number=test_phone,
        sender_name="Maria",
        message_text="Quiero reservar servicio de pestañas",
        message_data={"conversation": "Quiero reservar servicio de pestañas"},
        raw_item={"key": {"remoteJid": f"{test_phone}@s.whatsapp.net"}}
    )
    state = await svc.load_state(test_phone)
    assert state.get("servicio") == "pestañas", f"Esperaba pestañas pero obtuve {state.get('servicio')}"
    assert state.get("paso") == "recolectando_fecha"
    assert "día te viene mejor" in captured_replies[0] or "pestañas" in captured_replies[0]
    print("[M2] Reserva con servicio OK ->", captured_replies[0])

    # Mensaje 3: Para el lunes próximo
    captured_replies.clear()
    await handle_client_message(
        sender_number=test_phone,
        sender_name="Maria",
        message_text="Para el lunes próximo",
        message_data={"conversation": "Para el lunes próximo"},
        raw_item={"key": {"remoteJid": f"{test_phone}@s.whatsapp.net"}}
    )
    state = await svc.load_state(test_phone)
    assert state.get("servicio") == "pestañas"
    assert state.get("fecha") is not None
    assert state.get("paso") == "mostrando_horarios"
    assert "Horarios disponibles" in captured_replies[0] or "10:00" in captured_replies[0]
    print("[M3] Selección de fecha conserva servicio y muestra horarios ->", captured_replies[0][:70])

    # Mensaje 4: ¿A qué hora tienen disponibilidad?
    captured_replies.clear()
    await handle_client_message(
        sender_number=test_phone,
        sender_name="Maria",
        message_text="¿A qué hora tienen disponibilidad?",
        message_data={"conversation": "¿A qué hora tienen disponibilidad?"},
        raw_item={"key": {"remoteJid": f"{test_phone}@s.whatsapp.net"}}
    )
    state = await svc.load_state(test_phone)
    assert state.get("servicio") == "pestañas"
    assert state.get("fecha") is not None
    assert "Horarios disponibles" in captured_replies[0]
    print("[M4] Consulta de disponibilidad conserva servicio y fecha -> OK")

    # Mensaje 5: ¿Y cuánto debo pagar para reservar?
    captured_replies.clear()
    await handle_client_message(
        sender_number=test_phone,
        sender_name="Maria",
        message_text="¿Y cuánto debo pagar para reservar?",
        message_data={"conversation": "¿Y cuánto debo pagar para reservar?"},
        raw_item={"key": {"remoteJid": f"{test_phone}@s.whatsapp.net"}}
    )
    state = await svc.load_state(test_phone)
    assert state.get("servicio") == "pestañas"
    assert state.get("fecha") is not None
    assert "adelanto" in captured_replies[0].lower() or "s/ 20" in captured_replies[0].lower()
    assert "qué servicio deseas" not in captured_replies[0].lower()
    print("[M5] Consulta de pago responde sin perder servicio/fecha ->", captured_replies[0][:60])

    # Mensaje 6: Elegir horario (Slot 1: 10:00 am)
    captured_replies.clear()
    await handle_client_message(
        sender_number=test_phone,
        sender_name="Maria",
        message_text="1",
        message_data={"conversation": "1"},
        raw_item={"key": {"remoteJid": f"{test_phone}@s.whatsapp.net"}}
    )
    state = await svc.load_state(test_phone)
    assert state.get("hora") == "10:00"
    assert state.get("paso") == "esperando_confirmacion"
    assert "Resumen de tu cita" in captured_replies[0]
    print("[M6] Selección de slot avanza a resumen de confirmación ->", captured_replies[0][:70])

    print("\n=======================================================")
    print("✅ TODAS LAS PRUEBAS DE CONTINUIDAD CONVERSACIONAL PASARON (100%)")
    print("=======================================================")

if __name__ == "__main__":
    asyncio.run(test_full_conversational_continuity())
