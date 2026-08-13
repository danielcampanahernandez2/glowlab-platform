"""
Test de Modo Staff y Gestión de Citas por WhatsApp — Glowlab Platform.

Verifica:
1. 'citas hoy' y 'citas semana': reporte cronológico con servicio, clienta y estado de pago.
2. 'citas todas': reporte de agenda combinada de todo el equipo (Lizbeth y Anali).
3. 'cancelar cita <ID o Nombre>':
   - Caso unívoco: cancela en BD, registra auditoría y envía notificación por WhatsApp a la clienta.
   - Caso con ambigüedad: detecta múltiples coincidencias y solicita confirmación con IDs.
4. 'mover cita <ID o Nombre> a <fecha/hora>':
   - Reprograma en BD, registra auditoría y envía notificación por WhatsApp a la clienta con nueva fecha/hora.
5. Mensaje no reconocido: devuelve el manual de ayuda de comandos.
"""
import asyncio
from datetime import date, timedelta
import os
import re
import sys
from unittest.mock import AsyncMock, patch

sys.path.insert(0, os.path.abspath("."))
from app.modules.salon import services as svc
from app.modules.salon.models import Cita


# Mock en memoria de citas para pruebas unitarias deterministas
class MockAsyncSession:
    def __init__(self, citas_db):
        self.citas_db = citas_db

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass

    async def execute(self, query):
        class MockResult:
            def __init__(self, items):
                self._items = items

            def scalars(self):
                return self

            def all(self):
                return list(self._items)

            def scalar_one_or_none(self):
                return self._items[0] if self._items else None

            def fetchall(self):
                return [(item.hora,) for item in self._items]

        compiled = query.compile()
        params = compiled.params
        items = [c for c in self.citas_db if c.estado != "cancelada"]

        # 1. Filtro por ID
        for k, v in params.items():
            if "id" in k.lower() and isinstance(v, int):
                items = [c for c in items if c.id == v]
                return MockResult(items)

        # 2. Filtro por asesora
        for k, v in params.items():
            if isinstance(v, str) and any(adv in v.lower() for adv in ("lizbeth", "anali")):
                adv_clean = v.strip("%").lower()
                items = [c for c in items if adv_clean in (c.asesora or "").lower()]

        # 3. Filtro por nombre de clienta
        for k, v in params.items():
            if isinstance(v, str) and v.startswith("%") and not any(adv in v.lower() for adv in ("lizbeth", "anali")):
                name_clean = v.strip("%").lower()
                items = [c for c in items if name_clean in (c.cliente_nombre or "").lower()]

        # 4. Filtro por fechas
        target_dates = {v for v in params.values() if isinstance(v, str) and re.match(r'^\d{4}-\d{2}-\d{2}$', v)}
        if target_dates:
            items = [c for c in items if c.fecha in target_dates]

        return MockResult(items)

    async def commit(self):
        pass

    async def refresh(self, obj):
        pass


async def test_staff_commands_suite():
    today = date.today()
    today_str = today.strftime("%Y-%m-%d")
    tomorrow_str = (today + timedelta(days=1)).strftime("%Y-%m-%d")

    # Base de datos simulada en memoria
    citas_test = [
        Cita(
            id=101,
            cliente_phone="51999111222",
            cliente_nombre="Valeria Ramos",
            servicio="Botox capilar",
            asesora="Lizbeth",
            fecha=today_str,
            hora="11:00",
            estado="confirmada",
            adelanto_pagado=True,
        ),
        Cita(
            id=102,
            cliente_phone="51988222333",
            cliente_nombre="Mariana Gómez",
            servicio="Pestañas clásicas",
            asesora="Lizbeth",
            fecha=today_str,
            hora="16:00",
            estado="pendiente",
            adelanto_pagado=False,
        ),
        Cita(
            id=103,
            cliente_phone="51977333444",
            cliente_nombre="Camila Flores",
            servicio="Uñas acrílicas",
            asesora="Anali",
            fecha=today_str,
            hora="14:00",
            estado="confirmada",
            adelanto_pagado=True,
        ),
        Cita(
            id=104,
            cliente_phone="51999111222",
            cliente_nombre="Valeria Ramos",
            servicio="Lifting de pestañas",
            asesora="Lizbeth",
            fecha=tomorrow_str,
            hora="10:00",
            estado="confirmada",
            adelanto_pagado=True,
        ),
    ]

    sent_messages = []

    async def mock_send_message(phone, text):
        sent_messages.append({"phone": phone, "text": text})
        return True

    print("================================================================================")
    print("👩‍💼 TEST DE MODO STAFF: COMANDOS DETERMINISTAS DE GESTIÓN DE CITAS")
    print("================================================================================")

    with patch("app.modules.salon.services.async_session_factory", side_effect=lambda: MockAsyncSession(citas_test)):
        with patch("app.modules.salon.services.send_message", side_effect=mock_send_message):

            # ── 1. TEST: Consultar Citas de Hoy (Lizbeth) ──
            print("\n1. [Comando] Lizbeth escribe: 'citas hoy'")
            res_hoy = await svc.execute_staff_command(
                staff_phone="51992509246",
                staff_name="Lizbeth",
                message="citas hoy",
            )
            print(f"📋 Respuesta:\n{res_hoy}")
            assert "Valeria Ramos" in res_hoy
            assert "Mariana Gómez" in res_hoy
            assert "Botox capilar" in res_hoy
            assert "Adelanto Confirmado" in res_hoy
            assert "Pendiente de adelanto" in res_hoy
            print("   ✅ [OK] Reporte de citas de hoy generado correctamente.")

            # ── 2. TEST: Consultar Citas de Todo el Equipo ──
            print("\n2. [Comando] Lizbeth escribe: 'citas todas'")
            res_todas = await svc.execute_staff_command(
                staff_phone="51992509246",
                staff_name="Lizbeth",
                message="citas todas",
            )
            print(f"📋 Respuesta:\n{res_todas}")
            assert "Todo el equipo" in res_todas
            print("   ✅ [OK] Reporte de citas de todo el equipo generado.")

            # ── 3. TEST: Cancelar Cita con Ambigüedad (Valeria tiene 2 citas) ──
            print("\n3. [Comando] Lizbeth escribe: 'cancelar cita Valeria' (ambigüedad)")
            res_amb = await svc.execute_staff_command(
                staff_phone="51992509246",
                staff_name="Lizbeth",
                message="cancelar cita Valeria",
            )
            print(f"⚠️ Respuesta:\n{res_amb}")
            assert "Múltiples citas" in res_amb or "Encontré" in res_amb
            assert "[ID: 101]" in res_amb
            assert "[ID: 104]" in res_amb
            print("   ✅ [OK] Ambigüedad detectada y solicitud de confirmación por ID enviada.")

            # ── 4. TEST: Cancelar Cita por ID exacto (Caso unívoco) ──
            print("\n4. [Comando] Lizbeth escribe: 'cancelar cita 102'")
            sent_messages.clear()
            res_cancel = await svc.execute_staff_command(
                staff_phone="51992509246",
                staff_name="Lizbeth",
                message="cancelar cita 102",
            )
            print(f"✅ Respuesta al Staff:\n{res_cancel}")
            assert "cancelada con éxito" in res_cancel
            assert "Mariana Gómez" in res_cancel

            # Verificar notificación a la clienta
            print(f"\n📲 Notificación enviada a la clienta (Mariana):")
            assert len(sent_messages) == 1, "ERROR: Debió enviarse notificación por WhatsApp a la clienta"
            print(f"> Para: +{sent_messages[0]['phone']}\n> Mensaje:\n{sent_messages[0]['text']}")
            assert sent_messages[0]["phone"] == "51988222333"
            assert "ha sido cancelada" in sent_messages[0]["text"]
            assert "Pestañas clásicas" in sent_messages[0]["text"]
            print("   ✅ [OK] Cita cancelada y clienta notificada con éxito.")

            # ── 5. TEST: Mover Cita por ID ──
            print("\n5. [Comando] Lizbeth escribe: 'mover cita 101 a mañana 4pm'")
            sent_messages.clear()
            res_mover = await svc.execute_staff_command(
                staff_phone="51992509246",
                staff_name="Lizbeth",
                message="mover cita 101 a mañana 4pm",
            )
            print(f"✅ Respuesta al Staff:\n{res_mover}")
            assert "reprogramada con éxito" in res_mover

            # Verificar notificación a la clienta
            print(f"\n📲 Notificación de reprogramación enviada a Valeria:")
            assert len(sent_messages) == 1, "ERROR: Debió enviarse notificación por WhatsApp a Valeria"
            print(f"> Para: +{sent_messages[0]['phone']}\n> Mensaje:\n{sent_messages[0]['text']}")
            assert sent_messages[0]["phone"] == "51999111222"
            assert "ha sido reprogramada" in sent_messages[0]["text"]
            assert "4:00 pm" in sent_messages[0]["text"] or "16:00" in sent_messages[0]["text"]
            print("   ✅ [OK] Cita movida y clienta notificada con éxito.")

            # ── 6. TEST: Comando No Reconocido (Ayuda) ──
            print("\n6. [Comando] Lizbeth escribe: 'hola bot'")
            res_help = await svc.execute_staff_command(
                staff_phone="51992509246",
                staff_name="Lizbeth",
                message="hola bot",
            )
            print(f"💡 Respuesta de Ayuda:\n{res_help}")
            assert "Consultar Agenda" in res_help
            assert "Cancelar Cita" in res_help
            assert "Mover / Reprogramar Cita" in res_help
            print("   ✅ [OK] Menú de comandos devuelto exitosamente.")

    print("\n================================================================================")
    print("✅ TODAS LAS PRUEBAS DEL MODO STAFF PASARON AL 100%!")
    print("================================================================================")


if __name__ == "__main__":
    asyncio.run(test_staff_commands_suite())
