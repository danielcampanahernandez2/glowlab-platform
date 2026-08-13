"""Validación manual de Prueba 1 y Prueba 2 para el Agente Conversacional Glowlab."""
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

async def run_validation():
    print("================================================================================")
    print("🧪 PRUEBA 1 — Log 1: Precio con servicio en curso (sin forzar fecha)")
    print("================================================================================")
    phone1 = "51991111111"
    await svc.clear_state(phone1)

    # Mensaje 1: Me gustaría hacerme botox capilar
    captured_replies.clear()
    await handle_client_message(
        sender_number=phone1,
        sender_name="Andrea",
        message_text="Me gustaría hacerme botox capilar",
        message_data={"conversation": "Me gustaría hacerme botox capilar"},
        raw_item={"key": {"remoteJid": f"{phone1}@s.whatsapp.net"}}
    )
    print("👤 [Turno 1 - Andrea]: \"Me gustaría hacerme botox capilar\"")
    print("🤖 [Bot 1]:", captured_replies[-1] if captured_replies else "NO REPLY")
    state1 = await svc.load_state(phone1)
    print("📦 [Estado 1]:", state1)
    print("--------------------------------------------------------------------------------")

    # Mensaje 2: ¿Cuánto cuesta el botox capilar?
    captured_replies.clear()
    await handle_client_message(
        sender_number=phone1,
        sender_name="Andrea",
        message_text="¿Cuánto cuesta el botox capilar?",
        message_data={"conversation": "¿Cuánto cuesta el botox capilar?"},
        raw_item={"key": {"remoteJid": f"{phone1}@s.whatsapp.net"}}
    )
    print("👤 [Turno 2 - Andrea]: \"¿Cuánto cuesta el botox capilar?\"")
    bot_reply_2 = captured_replies[-1] if captured_replies else "NO REPLY"
    print("🤖 [Bot 2]:\n" + bot_reply_2)
    state2 = await svc.load_state(phone1)
    print("📦 [Estado 2]:", state2)

    # Verificaciones Prueba 1:
    assert "120" in bot_reply_2, "FALLÓ: Debe dar el precio de S/ 120"
    assert not any(q in bot_reply_2.lower() for q in ["¿qué día deseas reservar?", "¿qué día te gustaría venir?", "qué día y horario"]), "FALLÓ: No debe forzar una fecha directamente"
    print("\n✅ PRUEBA 1 VALIDADA CORRECTAMENTE")

    print("\n================================================================================")
    print("🧪 PRUEBA 2 — Log 2: Pregunta mixta (info + disponibilidad en un solo mensaje)")
    print("================================================================================")
    phone2 = "51992222222"
    await svc.clear_state(phone2)

    # Mensaje 1: Pregunta mixta
    captured_replies.clear()
    msg_mixto = "Hola! Tengo el cabello muy seco y maltratado, qué servicios tienen para eso y cuándo podría ir?"
    await handle_client_message(
        sender_number=phone2,
        sender_name="Valeria",
        message_text=msg_mixto,
        message_data={"conversation": msg_mixto},
        raw_item={"key": {"remoteJid": f"{phone2}@s.whatsapp.net"}}
    )
    print("👤 [Turno 1 - Valeria]:", msg_mixto)
    bot_reply_mixto = captured_replies[-1] if captured_replies else "NO REPLY"
    print("🤖 [Bot]:\n" + bot_reply_mixto)
    state_mixto = await svc.load_state(phone2)
    print("📦 [Estado]:", state_mixto)

    # Verificaciones Prueba 2:
    assert state_mixto.get("servicio") is None, f"FALLÓ: El estado guardó '{state_mixto.get('servicio')}' en lugar de None"
    assert any(w in bot_reply_mixto.lower() for w in ["hidratación", "botox", "keratina"]), "FALLÓ: Debe explicar opciones capilares"
    assert "pestaña" not in bot_reply_mixto.lower() and "lashista" not in bot_reply_mixto.lower(), "FALLÓ: No debe mencionar pestañas cuando solo se preguntó por cabello"
    assert "uñas" not in bot_reply_mixto.lower() and "pintado" not in bot_reply_mixto.lower(), "FALLÓ: No debe mencionar uñas cuando solo se preguntó por cabello"
    assert "Horarios disponibles" not in bot_reply_mixto, "FALLÓ: No debe ejecutar horarios a ciegas sin acordar servicio"
    print("\n✅ PRUEBA 2 VALIDADA CORRECTAMENTE")
    print("================================================================================")

if __name__ == "__main__":
    asyncio.run(run_validation())
