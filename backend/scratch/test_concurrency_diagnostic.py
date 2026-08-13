"""Diagnóstico y simulación de concurrencia en Glowlab WhatsApp Agent."""
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

async def run_concurrency_diagnostic():
    test_phone = "51988888888"
    await svc.clear_state(test_phone)

    print("================================================================================")
    print("🔬 SIMULACIÓN DE CONCURRENCIA: 2 MENSAJES SIMULTÁNEOS DEL MISMO NÚMERO")
    print("================================================================================")
    print("📦 Estado inicial:", await svc.load_state(test_phone))

    # Mensaje A: 'Quiero pestañas' (debe registrar servicio='pestañas' e historial de turno A)
    # Mensaje B: 'Para el lunes próximo' (debe registrar fecha='2026-08-17' e historial de turno B)
    # Si no hay lock, Mensaje B lee el estado antes de que Mensaje A lo guarde,
    # y al terminar B sobreescribe y destruye el estado de A.

    start_time = time.time()

    async def task_a():
        t0 = time.time() - start_time
        print(f"[{t0:.3f}s] 📥 Mensaje A entra a handle_client_message: 'Quiero pestañas'")
        await handle_client_message(
            sender_number=test_phone,
            sender_name="Sofia",
            message_text="Quiero pestañas",
            message_data={"conversation": "Quiero pestañas"},
            raw_item={"key": {"remoteJid": f"{test_phone}@s.whatsapp.net"}}
        )
        t1 = time.time() - start_time
        print(f"[{t1:.3f}s] 📤 Mensaje A terminó y ejecutó save_state()")

    async def task_b():
        await asyncio.sleep(0.05)  # Llega 50ms después, mientras A sigue procesando OpenAI / DB
        t0 = time.time() - start_time
        print(f"[{t0:.3f}s] 📥 Mensaje B entra a handle_client_message: 'Para el lunes próximo'")
        await handle_client_message(
            sender_number=test_phone,
            sender_name="Sofia",
            message_text="Para el lunes próximo",
            message_data={"conversation": "Para el lunes próximo"},
            raw_item={"key": {"remoteJid": f"{test_phone}@s.whatsapp.net"}}
        )
        t1 = time.time() - start_time
        print(f"[{t1:.3f}s] 📤 Mensaje B terminó y ejecutó save_state()")

    # Ejecutar concurrentemente
    await asyncio.gather(task_a(), task_b())

    final_state = await svc.load_state(test_phone)
    print("\n================================================================================")
    print("📦 ESTADO FINAL RESULTANTE EN PERSISTENCIA:")
    print("================================================================================")
    print(final_state)
    print("\n📜 Historial de mensajes en el estado:")
    history = final_state.get("history", [])
    for idx, item in enumerate(history):
        print(f"  {idx+1}. [{item.get('role')}]: {item.get('content')[:70]}...")

    has_servicio = final_state.get("servicio") == "pestañas"
    has_fecha = final_state.get("fecha") is not None
    has_full_history = len(history) == 4

    print("\n🔍 EVALUACIÓN DE LA CONDICIÓN DE CARRERA (Race Condition):")
    print(f"  1. ¿Se conservó el 'servicio' extraído por el Mensaje A? -> {has_servicio} (Valor: {final_state.get('servicio')})")
    print(f"  2. ¿Se conservó la 'fecha' extraída por el Mensaje B?    -> {has_fecha} (Valor: {final_state.get('fecha')})")
    print(f"  3. ¿Se preservó el historial de AMBOS turnos (4 items)? -> {has_full_history} (Total: {len(history)} items)")
    
    if not (has_servicio and has_fecha and has_full_history):
        print("\n❌ CONDICIÓN DE CARRERA CONFIRMADA:")
        if not has_servicio:
            print("   -> Mensaje B sobreescribió y BORRÓ el 'servicio' que había guardado Mensaje A.")
        if len(history) < 4:
            print(f"   -> Se perdieron turnos en el historial: solo quedaron {len(history)} de 4 entradas.")
    else:
        print("\n✅ No hubo pérdida de datos.")
    print("================================================================================")

if __name__ == "__main__":
    asyncio.run(run_concurrency_diagnostic())
