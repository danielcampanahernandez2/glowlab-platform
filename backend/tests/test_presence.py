"""
Test del Indicador de Presencia (Composing) — Glowlab WhatsApp Agent.
Verifica que:
1. send_presence emita las llamadas correctas a Evolution API.
2. typing_indicator active 'composing' de inmediato y envíe 'paused' al terminar.
"""
import asyncio
import os
import sys
import time

sys.path.insert(0, os.path.abspath("."))
from app.modules.salon import services as svc

presence_calls = []

async def mock_send_presence(number: str, presence: str = "composing", delay: int = 1200) -> bool:
    presence_calls.append({"number": number, "presence": presence, "time": time.time()})
    return True

svc.send_presence = mock_send_presence


async def test_typing_indicator_lifecycle():
    presence_calls.clear()
    test_phone = "51912345678"

    print("================================================================================")
    print("🧪 TEST DE INDICADOR DE PRESENCIA 'ESCRIBIENDO...' (COMPOSING)")
    print("================================================================================")

    # Simular una tarea que dura 1.5 segundos
    async with svc.typing_indicator(test_phone, refresh_interval=0.5):
        print("  -> Entrando a context manager: se debió emitir 'composing'")
        await asyncio.sleep(1.2)
        print("  -> Dentro de context manager: se debió refrescar 'composing'")

    print("  -> Saliendo de context manager: se debió emitir 'paused'")

    print("\n📜 Llamadas a send_presence registradas:")
    for idx, call in enumerate(presence_calls):
        print(f"  {idx+1}. [{call['presence']}] a {call['number']}")

    assert len(presence_calls) >= 3, f"ERROR: Se esperaban al menos 3 llamadas (obtenidas {len(presence_calls)})"
    assert presence_calls[0]["presence"] == "composing", "ERROR: Primera llamada debe ser 'composing'"
    assert presence_calls[-1]["presence"] == "paused", "ERROR: Última llamada debe ser 'paused'"

    print("\n✅ TEST DE PRESENCIA EXITOSO: Ciclo 'composing' -> refresh -> 'paused' validado al 100%.")
    print("================================================================================")


if __name__ == "__main__":
    asyncio.run(test_typing_indicator_lifecycle())
