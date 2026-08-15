import asyncio
import os
import sys
import json

sys.path.insert(0, os.path.abspath("."))
from app.core.config import settings
from app.core.database import async_session_factory
from app.modules.salon import services as svc
from app.modules.salon.models import OpenAIUsageLog, Cita
from sqlalchemy import select, desc

async def simulate_conversation():
    print("=" * 80)
    print(f"🤖 INICIANDO SIMULACIÓN DE CONVERSACIÓN END-TO-END CON DEEPSEEK")
    print(f"• Proveedor AI: {settings.AI_PROVIDER}")
    print(f"• Modelo:       {settings.get_ai_model()}")
    print(f"• Endpoint:     {settings.get_ai_endpoint()}")
    print("=" * 80)

    test_phone = "51966554433"
    client_name = "Camila"
    await svc.clear_state(test_phone, tenant_id="glowlab")

    # Turno 1: Consulta de servicios
    print("\n💬 [TURNO 1 - Clienta]: Hola, qué tratamientos tienen para el cabello y cuánto cuestan?")
    reply_1 = await svc.run_conversational_agent(
        sender_number=test_phone,
        sender_name=client_name,
        message_text="Hola, qué tratamientos tienen para el cabello y cuánto cuestan?",
        tenant_id="glowlab"
    )
    print(f"✨ [Glowlab Bot (DeepSeek)]:\n{reply_1}")

    # Turno 2: Consulta de disponibilidad
    print("\n💬 [TURNO 2 - Clienta]: Tienen disponibilidad para botox capilar este sábado 22 de agosto?")
    reply_2 = await svc.run_conversational_agent(
        sender_number=test_phone,
        sender_name=client_name,
        message_text="Tienen disponibilidad para botox capilar este sábado 22 de agosto?",
        tenant_id="glowlab"
    )
    print(f"✨ [Glowlab Bot (DeepSeek)]:\n{reply_2}")

    # Turno 3: Solicitud de reserva
    print("\n💬 [TURNO 3 - Clienta]: Perfecto, quiero reservar a las 3:00 pm por favor.")
    reply_3 = await svc.run_conversational_agent(
        sender_number=test_phone,
        sender_name=client_name,
        message_text="Perfecto, quiero reservar a las 3:00 pm por favor.",
        tenant_id="glowlab"
    )
    print(f"✨ [Glowlab Bot (DeepSeek)]:\n{reply_3}")

    # Breve pausa para asegurar escritura en DB de logs asíncronos
    await asyncio.sleep(1)

    print("\n" + "=" * 80)
    print("📊 VERIFICACIÓN EN BASE DE DATOS (openai_usage_logs y citas)")
    print("=" * 80)

    async with async_session_factory() as db:
        # 1. Verificar registros de uso de IA
        res_logs = await db.execute(
            select(OpenAIUsageLog)
            .where(OpenAIUsageLog.tenant_id == "glowlab")
            .order_by(desc(OpenAIUsageLog.created_at))
            .limit(5)
        )
        logs = res_logs.scalars().all()
        print(f"• Últimos registros de consumo encontrados: {len(logs)}")
        for i, l in enumerate(logs, 1):
            print(f"  [{i}] Provider: {l.provider} | Model: {l.model} | Tokens: {l.total_tokens} (Prompt: {l.prompt_tokens}, Comp: {l.completion_tokens}) | Cost: ${l.cost_usd:.6f} USD | Tenant: {l.tenant_id}")

        # 2. Verificar cita creada si se ejecutó tool create_reservation
        res_citas = await db.execute(
            select(Cita)
            .where(Cita.cliente_phone == test_phone)
            .order_by(desc(Cita.created_at))
            .limit(1)
        )
        cita = res_citas.scalar_one_or_none()
        if cita:
            print(f"\n✅ Cita registrada con éxito en PostgreSQL:")
            print(f"  • ID: {cita.id} | Cliente: {cita.cliente_nombre} | Teléfono: {cita.cliente_phone}")
            print(f"  • Servicio: {cita.servicio} | Fecha: {cita.fecha} | Hora: {cita.hora}")
            print(f"  • Estado: {cita.estado} | Adelanto requerido: S/ {cita.adelanto_monto}")
        else:
            print("\nℹ️ No se registró cita directa en Cita (el agente guió el proceso conversacional).")

    print("\n" + "=" * 80)
    print("🌟 SIMULACIÓN COMPLETADA EXITOSAMENTE CON DEEPSEEK")
    print("=" * 80)

if __name__ == "__main__":
    asyncio.run(simulate_conversation())
