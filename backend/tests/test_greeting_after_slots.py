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

async def test_greeting_and_services_not_blocked_by_slots():
    test_phone = "51911223344"
    await svc.clear_state(test_phone)

    # 1. Reserva hasta mostrar horarios
    await handle_client_message(
        sender_number=test_phone,
        sender_name="Daniel",
        message_text="quiero reservar pestañas para el lunes",
        message_data={"conversation": "quiero reservar pestañas para el lunes"},
        raw_item={"key": {"remoteJid": f"{test_phone}@s.whatsapp.net"}}
    )
    state = await svc.load_state(test_phone)
    assert state.get("paso") == "mostrando_horarios"
    print("Paso 1 (Slots generados):", state.get("slots_disponibles"))

    # 2. El usuario envía "Hola"
    captured_replies.clear()
    await handle_client_message(
        sender_number=test_phone,
        sender_name="Daniel",
        message_text="Hola",
        message_data={"conversation": "Hola"},
        raw_item={"key": {"remoteJid": f"{test_phone}@s.whatsapp.net"}}
    )
    reply = captured_replies[0]
    print("Paso 2 ('Hola'):", reply)
    assert "Horarios disponibles" not in reply, "ERROR: Respondió con horarios en lugar del saludo!"
    assert "¡Hola!" in reply or "Bienvenida" in reply, f"Respuesta inesperada: {reply}"

    # 3. El usuario envía "que servicios tiene ?"
    captured_replies.clear()
    await handle_client_message(
        sender_number=test_phone,
        sender_name="Daniel",
        message_text="que servicios tiene ?",
        message_data={"conversation": "que servicios tiene ?"},
        raw_item={"key": {"remoteJid": f"{test_phone}@s.whatsapp.net"}}
    )
    reply = captured_replies[0]
    print("Paso 3 ('que servicios tiene ?'):", reply[:80])
    assert "Horarios disponibles" not in reply, "ERROR: Respondió con horarios en lugar de la lista de servicios!"
    assert "Pestañas" in reply and "Uñas" in reply, f"Respuesta inesperada: {reply}"

    # 4. El usuario envía "cuanto cuesta el botox ?"
    captured_replies.clear()
    await handle_client_message(
        sender_number=test_phone,
        sender_name="Daniel",
        message_text="cuanto cuesta el botox ?",
        message_data={"conversation": "cuanto cuesta el botox ?"},
        raw_item={"key": {"remoteJid": f"{test_phone}@s.whatsapp.net"}}
    )
    reply = captured_replies[0]
    print("Paso 4 ('cuanto cuesta el botox ?'):", reply[:80])
    assert "120" in reply, f"Respuesta inesperada: {reply}"

    print("\n✅ TODAS LAS PRUEBAS DE SALUDO Y SERVICIOS PASARON CORRECTAMENTE!")

if __name__ == "__main__":
    asyncio.run(test_greeting_and_services_not_blocked_by_slots())
