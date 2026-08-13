import asyncio
import os
import sys
sys.path.insert(0, os.path.abspath("."))
from app.api.v1.endpoints.whatsapp import handle_client_message
from app.modules.salon import services as svc

messages = [
    "Quiero servicio de Pestañas",
    "quiero reservar servicio de pestañas",
    "para el Lunes proximo ?",
    "puede ser para el lunes proximo ?",
    "Quiero reservar para el lunes proximo, cuanto debo pagar para reservar ?"
]

captured_replies = []
async def mock_send(phone, text):
    captured_replies.append(text)
    return True

svc.send_message = mock_send

async def run_simulation():
    test_phone = "51999999999"
    await svc.clear_state(test_phone)
    for i, msg in enumerate(messages, 1):
        print(f"================== TURNO {i} ==================")
        print(f"Cliente: \"{msg}\"")
        
        state_before = await svc.load_state(test_phone)
        print(f"State BEFORE: {state_before}")
        
        intent_data = await svc.extract_intent(state_before, msg)
        print(f"intent_data: {intent_data}")
        
        captured_replies.clear()
        await handle_client_message(
            sender_number=test_phone,
            sender_name="Test User",
            message_text=msg,
            message_data={"conversation": msg},
            raw_item={"key": {"remoteJid": f"{test_phone}@s.whatsapp.net"}}
        )
        
        state_after = await svc.load_state(test_phone)
        reply = captured_replies[0] if captured_replies else "NO REPLY"
        print(f"Bot: \"{reply}\"")
        print(f"State AFTER: {state_after}")
        print()

if __name__ == "__main__":
    asyncio.run(run_simulation())
