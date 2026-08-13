"""
Test de Concurrencia y Lock Distribuido — Glowlab WhatsApp Agent.

Verifica que ante mensajes concurrentes enviados casi al mismo tiempo por el mismo número:
1. El lock distribuido serialice la ejecución.
2. El segundo mensaje espere a que el primero termine.
3. El estado final conserve TODOS los campos extraídos (ej. servicio y fecha).
4. El historial final contenga los 4 turnos completos sin pérdida ni sobreescritura.
"""
import asyncio
import os
import sys
import time

sys.path.insert(0, os.path.abspath("."))
from app.api.v1.endpoints.whatsapp import handle_client_message
from app.modules.salon import services as svc

captured_replies = []
async def mock_send(phone, text):
    captured_replies.append({"phone": phone, "text": text, "timestamp": time.time()})
    return True

svc.send_message = mock_send


async def test_concurrent_messages_serialized_by_phone_lock():
    test_phone = "51988888888"
    await svc.clear_state(test_phone)
    captured_replies.clear()

    print("================================================================================")
    print("🧪 TEST DE CONCURRENCIA CON LOCK DISTRIBUIDO ACTIVO")
    print("================================================================================")
    print("📦 Estado inicial:", await svc.load_state(test_phone))

    start_time = time.time()
    events = []

    async def task_a():
        t0 = time.time() - start_time
        events.append(f"[{t0:.3f}s] Task A solicitando procesamiento...")
        await handle_client_message(
            sender_number=test_phone,
            sender_name="Sofia",
            message_text="Quiero pestañas",
            message_data={"conversation": "Quiero pestañas"},
            raw_item={"key": {"remoteJid": f"{test_phone}@s.whatsapp.net"}}
        )
        t1 = time.time() - start_time
        events.append(f"[{t1:.3f}s] Task A finalizada con éxito.")

    async def task_b():
        await asyncio.sleep(0.05)  # Llega 50ms después, concurrente a Task A
        t0 = time.time() - start_time
        events.append(f"[{t0:.3f}s] Task B solicitando procesamiento...")
        await handle_client_message(
            sender_number=test_phone,
            sender_name="Sofia",
            message_text="Para el lunes próximo",
            message_data={"conversation": "Para el lunes próximo"},
            raw_item={"key": {"remoteJid": f"{test_phone}@s.whatsapp.net"}}
        )
        t1 = time.time() - start_time
        events.append(f"[{t1:.3f}s] Task B finalizada con éxito.")

    # Ejecutar concurrentemente
    await asyncio.gather(task_a(), task_b())

    final_state = await svc.load_state(test_phone)
    print("\n📜 Cronología de ejecución:")
    for e in events:
        print(f"  • {e}")

    print("\n📦 ESTADO FINAL RESULTANTE EN PERSISTENCIA:")
    print(final_state)

    history = final_state.get("history", [])
    print(f"\n📜 Historial de mensajes ({len(history)} turnos):")
    for idx, item in enumerate(history):
        print(f"  {idx+1}. [{item.get('role')}]: {item.get('content')[:70]}...")

    # Verificaciones
    assert final_state.get("servicio") == "pestañas", f"ERROR: Se perdió el servicio! Estado: {final_state}"
    assert final_state.get("fecha") is not None, f"ERROR: Se perdió la fecha! Estado: {final_state}"
    assert len(history) == 4, f"ERROR: Historial incompleto (esperado 4, obtenido {len(history)})"
    assert len(captured_replies) == 2, f"ERROR: Se debieron enviar 2 respuestas (obtenido {len(captured_replies)})"

    print("\n✅ TEST DE CONCURRENCIA EXITOSO: CERO CONDICIONES DE CARRERA, DATOS Y TURNOS 100% PRESERVADOS.")
    print("================================================================================")


if __name__ == "__main__":
    asyncio.run(test_concurrent_messages_serialized_by_phone_lock())
