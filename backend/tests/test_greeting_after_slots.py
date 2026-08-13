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
    print("Paso 1 (Mensaje inicial procesado):", captured_replies)

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


async def test_log3_greeting_with_active_service_in_state():
    """
    Reproduce el Log 3: Clienta con servicio 'pestañas' y fecha activa en estado de sesión
    que envía un saludo simple ('Hola').
    Verifica que el agente responda con un saludo abierto y NO continúe la reserva.
    """
    test_phone = "51911223399"
    await svc.clear_state(test_phone)

    # Simular estado previo con servicio y fecha activa
    initial_state = {
        "nombre": "Daniel",
        "servicio": "pestañas",
        "fecha": "2026-08-17",
        "slots_disponibles": ["10:00", "11:00", "12:00"],
        "paso": "mostrando_horarios",
        "history": [
            {"role": "user", "content": "quiero reservar pestañas para el lunes"},
            {"role": "assistant", "content": "Horarios disponibles el lunes 17 de agosto:\n1. 10:00 am\n2. 11:00 am\n\n¿Cuál prefieres?"}
        ]
    }
    await svc.save_state(test_phone, initial_state)

    captured_replies.clear()
    await handle_client_message(
        sender_number=test_phone,
        sender_name="Daniel",
        message_text="Hola",
        message_data={"conversation": "Hola"},
        raw_item={"key": {"remoteJid": f"{test_phone}@s.whatsapp.net"}}
    )

    assert len(captured_replies) == 1
    reply = captured_replies[0]
    print("\n[Log 3 Test] Respuesta a 'Hola' con servicio previo en curso:")
    print(">", reply)

    # Comprobar que responde con saludo abierto y no fuerza la reserva
    assert "¡Hola!" in reply or "Bienvenida" in reply or "hola" in reply.lower()
    assert "Horarios disponibles" not in reply, "ERROR: No debió responder con la lista de horarios!"
    assert "Continuamos con tu reserva" not in reply, "ERROR: No debió forzar la continuidad de la reserva!"
    print("✅ [OK] Log 3 test pasó exitosamente: el saludo simple no continuó la reserva.")


async def test_log1_price_query_with_active_service():
    """
    Reproduce el Log 1: Consulta de precio con servicio en curso ya guardado en el estado.
    Verifica que dé el precio (S/ 120) y ofrezca continuar sin forzar una fecha directamente.
    """
    test_phone = "51911223388"
    await svc.clear_state(test_phone)

    # Mensaje 1: Me gustaría hacerme botox capilar (guarda servicio en curso)
    captured_replies.clear()
    await handle_client_message(
        sender_number=test_phone,
        sender_name="Andrea",
        message_text="Me gustaría hacerme botox capilar",
        message_data={"conversation": "Me gustaría hacerme botox capilar"},
        raw_item={"key": {"remoteJid": f"{test_phone}@s.whatsapp.net"}}
    )
    state1 = await svc.load_state(test_phone)
    assert state1.get("servicio") == "botox capilar"

    # Mensaje 2: ¿Cuánto cuesta el botox capilar?
    captured_replies.clear()
    await handle_client_message(
        sender_number=test_phone,
        sender_name="Andrea",
        message_text="¿Cuánto cuesta el botox capilar?",
        message_data={"conversation": "¿Cuánto cuesta el botox capilar?"},
        raw_item={"key": {"remoteJid": f"{test_phone}@s.whatsapp.net"}}
    )
    assert len(captured_replies) == 1
    reply = captured_replies[0]
    print("\n[Log 1 Test] Respuesta a '¿Cuánto cuesta el botox capilar?' con servicio en curso:")
    print(">", reply)

    assert "120" in reply, "ERROR: Debe dar el precio de S/ 120"
    assert not any(q in reply.lower() for q in ["¿qué día deseas reservar?", "¿qué día te gustaría venir?", "qué día y horario"]), "ERROR: No debe forzar una fecha directamente"
    print("✅ [OK] Log 1 test pasó exitosamente: dio el precio sin forzar fecha.")


async def test_valeria_hair_specific_need_and_clean_state():
    """
    Reproduce el caso de Valeria (Prueba 2): Pregunta de necesidad específica (cabello seco y maltratado).
    Verifica que:
    (a) El estado NO guarde palabras sueltas como 'cabello' en el campo servicio.
    (b) La respuesta SOLO mencione servicios relevantes a esa necesidad (hidratación, botox, keratina)
        y NO el catálogo completo (no pestañas ni uñas).
    """
    test_phone = "51911223377"
    await svc.clear_state(test_phone)

    captured_replies.clear()
    msg = "Hola! Tengo el cabello muy seco y maltratado, qué servicios tienen para eso y cuándo podría ir?"
    await handle_client_message(
        sender_number=test_phone,
        sender_name="Valeria",
        message_text=msg,
        message_data={"conversation": msg},
        raw_item={"key": {"remoteJid": f"{test_phone}@s.whatsapp.net"}}
    )
    assert len(captured_replies) == 1
    reply = captured_replies[0]
    state = await svc.load_state(test_phone)
    print("\n[Valeria Test] Respuesta a pregunta específica de cabello seco:")
    print(">", reply)
    print("Estado tras mensaje:", state)

    # (a) No guarda palabras genéricas como servicio
    assert state.get("servicio") is None, f"ERROR: El estado guardó '{state.get('servicio')}' indebidamente en lugar de None!"

    # (b) Solo menciona opciones capilares relevantes, sin mezclar pestañas ni uñas
    assert any(w in reply.lower() for w in ["hidratación", "botox", "keratina"]), "ERROR: Debe ofrecer opciones capilares"
    assert "pestaña" not in reply.lower() and "lashista" not in reply.lower(), "ERROR: No debe mencionar pestañas cuando solo se preguntó por cabello!"
    assert "uñas" not in reply.lower() and "pintado" not in reply.lower(), "ERROR: No debe mencionar uñas cuando solo se preguntó por cabello!"
    assert "Horarios disponibles" not in reply, "ERROR: No debe ejecutar get_available_slots a ciegas!"
    print("✅ [OK] Valeria test pasó exitosamente: estado limpio y filtrado por necesidad.")


async def main():
    await test_greeting_and_services_not_blocked_by_slots()
    await test_log3_greeting_with_active_service_in_state()
    await test_log1_price_query_with_active_service()
    await test_valeria_hair_specific_need_and_clean_state()


if __name__ == "__main__":
    asyncio.run(main())

