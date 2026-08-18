"""
Tests para el Sistema de Seguimiento Post-Cita Automatizado (FastAPI + APScheduler + PostgreSQL + Redis).

Verifica:
1. Prevención de envíos duplicados ante scans concurrentes mediante update atómico.
2. Contenido dinámico configurable desde la tabla service_followups con placeholders.
3. Respeto estricto de la ventana horaria (8:00 AM - 9:00 PM hora Perú / America/Lima) y postergación (pending_morning).
4. Manejo de fallos en Evolution API: reversión de post_service_sent = False para reintentar y captura en Sentry con teléfono anonimizado.
"""
import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch, MagicMock
import pytest

from app.modules.salon import services as svc
from app.modules.salon.models import Cita, ServiceFollowup


class FakeRedis:
    """Simulador en memoria de Redis con soporte de locks y atomicidad."""
    def __init__(self):
        self.data = {}

    async def get(self, key):
        return self.data.get(key)

    async def set(self, key, value, ex=None, px=None, nx=False):
        if nx and key in self.data:
            return False
        self.data[key] = value
        return True

    async def delete(self, *keys):
        count = 0
        for k in keys:
            if k in self.data:
                del self.data[k]
                count += 1
        return count

    async def eval(self, script, numkeys, key, token):
        if self.data.get(key) == token:
            self.data.pop(key, None)
            return 1
        return 0


class InMemoryDBStore:
    """Almacén en memoria de SQLAlchemy para simular operaciones y updates atómicos."""
    def __init__(self):
        self.citas = {}
        self.followups = {}
        self._next_cita_id = 1
        self._next_followup_id = 1

    def add_cita(self, **kwargs) -> Cita:
        cita_id = kwargs.pop("id", None) or self._next_cita_id
        self._next_cita_id = max(self._next_cita_id, cita_id + 1)
        cita = Cita(id=cita_id, **kwargs)
        self.citas[cita_id] = cita
        return cita

    def add_followup(self, **kwargs) -> ServiceFollowup:
        fid = kwargs.pop("id", None) or self._next_followup_id
        self._next_followup_id = max(self._next_followup_id, fid + 1)
        f = ServiceFollowup(id=fid, **kwargs)
        self.followups[fid] = f
        return f


class MockResult:
    def __init__(self, items=None, rowcount=0):
        self._items = items if items is not None else []
        self.rowcount = rowcount

    def scalars(self):
        return self

    def all(self):
        return list(self._items)

    def first(self):
        return self._items[0] if self._items else None

    def scalar_one_or_none(self):
        return self._items[0] if self._items else None

    def scalar(self):
        return self._items[0] if self._items else None

    def fetchone(self):
        return self._items[0] if self._items else None

    def fetchall(self):
        return list(self._items)


class MockAsyncSession:
    def __init__(self, store: InMemoryDBStore):
        self.store = store

    async def execute(self, stmt):
        stmt_str = str(stmt).lower()

        # Update atómico sobre citas
        if "update citas" in stmt_str:
            params = stmt.compile().params

            cita_id = None
            for k, v in params.items():
                if k == "id" or k.startswith("id_") or k.startswith("citas_id"):
                    cita_id = v
                    break

            values_to_set = {}
            if hasattr(stmt, "_values") and stmt._values:
                for col, bind in stmt._values.items():
                    col_name = col.name if hasattr(col, "name") else str(col)
                    val = bind.value if hasattr(bind, "value") else bind
                    values_to_set[col_name] = val
            else:
                for k, v in params.items():
                    if k in ("post_service_sent", "post_service_pending_morning", "seguimiento_enviado", "updated_at"):
                        values_to_set[k] = v

            rowcount = 0
            if cita_id and cita_id in self.store.citas:
                cita = self.store.citas[cita_id]
                # Simular condición atómica WHERE post_service_sent = FALSE
                if "post_service_sent" in values_to_set and values_to_set["post_service_sent"] is True:
                    if not cita.post_service_sent:
                        cita.post_service_sent = True
                        cita.post_service_pending_morning = values_to_set.get("post_service_pending_morning", False)
                        cita.seguimiento_enviado = values_to_set.get("seguimiento_enviado", True)
                        rowcount = 1
                elif "post_service_sent" in values_to_set and values_to_set["post_service_sent"] is False:
                    cita.post_service_sent = False
                    cita.seguimiento_enviado = False
                    rowcount = 1
                elif "post_service_pending_morning" in values_to_set:
                    cita.post_service_pending_morning = values_to_set["post_service_pending_morning"]
                    rowcount = 1

            return MockResult(rowcount=rowcount)

        # Consulta SELECT de citas
        if "from citas" in stmt_str:
            citas_list = [c for c in self.store.citas.values() if c.estado == "completada" and not c.post_service_sent]
            return MockResult(items=citas_list)

        # Consulta SELECT de service_followups
        if "from service_followups" in stmt_str:
            followups_list = [f for f in self.store.followups.values() if f.is_active]
            return MockResult(items=followups_list)

        return MockResult()

    async def commit(self):
        pass

    async def rollback(self):
        pass


@pytest.fixture
def env():
    """Configura el entorno de prueba con almacén en memoria compartido y Redis mock."""
    store = InMemoryDBStore()
    fake_redis = FakeRedis()
    svc._in_memory_state.clear()
    svc._in_memory_phone_locks.clear()

    class SessionContext:
        async def __aenter__(self):
            return MockAsyncSession(store)
        async def __aexit__(self, *args):
            return False

    with (
        patch("app.modules.salon.services._get_redis", new=AsyncMock(return_value=fake_redis)),
        patch("app.modules.salon.services.async_session_factory", side_effect=SessionContext),
        patch("app.modules.salon.services.send_presence", new=AsyncMock(return_value=True)),
    ):
        yield store
        svc._in_memory_state.clear()
        svc._in_memory_phone_locks.clear()


@pytest.mark.asyncio
async def test_followup_window_check():
    """Verifica que la ventana horaria de 8:00 AM a 9:00 PM hora Perú funcione correctamente."""
    tz_lima = timezone(timedelta(hours=-5))

    # 1. 07:59 AM -> Fuera de ventana (antes de las 8am)
    t_0759 = datetime(2026, 8, 18, 7, 59, 0, tzinfo=tz_lima)
    assert svc.is_within_followup_window(t_0759) is False

    # 2. 08:00 AM -> Dentro de ventana
    t_0800 = datetime(2026, 8, 18, 8, 0, 0, tzinfo=tz_lima)
    assert svc.is_within_followup_window(t_0800) is True

    # 3. 02:30 PM -> Dentro de ventana
    t_1430 = datetime(2026, 8, 18, 14, 30, 0, tzinfo=tz_lima)
    assert svc.is_within_followup_window(t_1430) is True

    # 4. 08:59 PM (20:59) -> Dentro de ventana
    t_2059 = datetime(2026, 8, 18, 20, 59, 0, tzinfo=tz_lima)
    assert svc.is_within_followup_window(t_2059) is True

    # 5. 09:00 PM (21:00) -> Fuera de ventana (a partir de las 9pm)
    t_2100 = datetime(2026, 8, 18, 21, 0, 0, tzinfo=tz_lima)
    assert svc.is_within_followup_window(t_2100) is False

    # 6. 11:30 PM -> Fuera de ventana
    t_2330 = datetime(2026, 8, 18, 23, 30, 0, tzinfo=tz_lima)
    assert svc.is_within_followup_window(t_2330) is False


@pytest.mark.asyncio
async def test_dynamic_content_from_service_followups_config(env):
    """
    Verifica que el mensaje se arme leyendo la configuración dinámica de la tabla service_followups
    reemplazando los placeholders ({cliente_nombre}, {servicio}, {asesora}, {business_name}).
    """
    store = env
    store.add_followup(
        tenant_id="glowlab",
        service_name="Botox capilar",
        message_template=(
            "🌸 ¡Hola {cliente_nombre}! Esperamos que te haya encantado tu {servicio} con {asesora} en {business_name}.\n"
            "Recuerda no lavar tu cabello las próximas 48 horas. ✨"
        ),
        delay_hours=3,
        is_active=True,
    )

    tz_lima = timezone(timedelta(hours=-5))
    now_lima = datetime.now(tz_lima)
    past_end_dt = now_lima - timedelta(hours=4)

    cita = store.add_cita(
        id=101,
        tenant_id="glowlab",
        cliente_phone="51992509246",
        cliente_nombre="Valeria",
        servicio="Botox capilar",
        asesora="Anali",
        fecha=past_end_dt.strftime("%Y-%m-%d"),
        hora=(past_end_dt - timedelta(hours=1)).strftime("%H:%M"),
        hora_fin=past_end_dt.strftime("%H:%M"),
        estado="completada",
        post_service_sent=False,
    )

    sent_messages = []
    with (
        patch("app.modules.salon.services.is_within_followup_window", return_value=True),
        patch("app.modules.salon.services.send_message", new=AsyncMock(side_effect=lambda phone, text: sent_messages.append((phone, text)) or True)),
    ):
        sent_count = await svc.run_post_service_followup_check()

    assert sent_count == 1
    assert len(sent_messages) == 1
    phone_sent, text_sent = sent_messages[0]
    assert phone_sent == "51992509246"
    assert "¡Hola Valeria!" in text_sent
    assert "Botox capilar" in text_sent
    assert "Anali" in text_sent
    assert "Glowlab" in text_sent
    assert cita.post_service_sent is True


@pytest.mark.asyncio
async def test_atomic_update_prevents_duplicate_sends(env):
    """
    Verifica que ejecuciones concurrentes de run_post_service_followup_check()
    NO envíen mensajes duplicados gracias al update atómico en PostgreSQL.
    """
    store = env
    tz_lima = timezone(timedelta(hours=-5))
    now_lima = datetime.now(tz_lima)
    past_end_dt = now_lima - timedelta(hours=4)

    cita = store.add_cita(
        id=202,
        tenant_id="glowlab",
        cliente_phone="51988776655",
        cliente_nombre="Carla",
        servicio="Extensiones de pestañas",
        asesora="Lizbeth",
        fecha=past_end_dt.strftime("%Y-%m-%d"),
        hora=(past_end_dt - timedelta(hours=1)).strftime("%H:%M"),
        hora_fin=past_end_dt.strftime("%H:%M"),
        estado="completada",
        post_service_sent=False,
    )

    sent_messages = []
    with (
        patch("app.modules.salon.services.is_within_followup_window", return_value=True),
        patch("app.modules.salon.services.send_message", new=AsyncMock(side_effect=lambda phone, text: sent_messages.append((phone, text)) or True)),
    ):
        # Ejecutar 3 scans en paralelo simulando concurrencia
        results = await asyncio.gather(
            svc.run_post_service_followup_check(),
            svc.run_post_service_followup_check(),
            svc.run_post_service_followup_check(),
        )

    # Solo uno debe haber ganado la carrera y enviado el mensaje
    total_sent = sum(results)
    assert total_sent == 1
    assert len(sent_messages) == 1
    assert cita.post_service_sent is True


@pytest.mark.asyncio
async def test_defer_post_service_when_outside_time_window(env):
    """
    Verifica que si la hora cae fuera de la ventana (ej. madrugada / 2am),
    NO se envíe el mensaje y se marque post_service_pending_morning = TRUE.
    """
    store = env
    tz_lima = timezone(timedelta(hours=-5))
    now_lima = datetime.now(tz_lima)
    past_end_dt = now_lima - timedelta(hours=4)

    cita = store.add_cita(
        id=303,
        tenant_id="glowlab",
        cliente_phone="51977665544",
        cliente_nombre="Gabriela",
        servicio="Pintado de uñas",
        asesora="Lizbeth",
        fecha=past_end_dt.strftime("%Y-%m-%d"),
        hora=(past_end_dt - timedelta(hours=1)).strftime("%H:%M"),
        hora_fin=past_end_dt.strftime("%H:%M"),
        estado="completada",
        post_service_sent=False,
    )

    sent_messages = []
    # 1. Simular escaneo a las 11:30 PM (fuera de ventana)
    with (
        patch("app.modules.salon.services.is_within_followup_window", return_value=False),
        patch("app.modules.salon.services.send_message", new=AsyncMock(side_effect=lambda phone, text: sent_messages.append(text))),
    ):
        sent_count = await svc.run_post_service_followup_check()

    assert sent_count == 0
    assert len(sent_messages) == 0
    assert cita.post_service_sent is False
    assert cita.post_service_pending_morning is True

    # 2. Simular siguiente escaneo a las 8:15 AM (dentro de ventana)
    with (
        patch("app.modules.salon.services.is_within_followup_window", return_value=True),
        patch("app.modules.salon.services.send_message", new=AsyncMock(side_effect=lambda phone, text: sent_messages.append(text) or True)),
    ):
        sent_count_morning = await svc.run_post_service_followup_check()

    assert sent_count_morning == 1
    assert len(sent_messages) == 1
    assert cita.post_service_sent is True
    assert cita.post_service_pending_morning is False


@pytest.mark.asyncio
async def test_send_failure_reverts_flag_and_captures_sentry(env):
    """
    Verifica que si Evolution API falla, post_service_sent se revierte a FALSE
    (para reintento) y se captura la excepción en Sentry con el teléfono anonimizado.
    """
    store = env
    tz_lima = timezone(timedelta(hours=-5))
    now_lima = datetime.now(tz_lima)
    past_end_dt = now_lima - timedelta(hours=4)

    cita = store.add_cita(
        id=404,
        tenant_id="glowlab",
        cliente_phone="51999887766",
        cliente_nombre="Luciana",
        servicio="Tratamiento de hidratación",
        asesora="Anali",
        fecha=past_end_dt.strftime("%Y-%m-%d"),
        hora=(past_end_dt - timedelta(hours=1)).strftime("%H:%M"),
        hora_fin=past_end_dt.strftime("%H:%M"),
        estado="completada",
        post_service_sent=False,
    )

    sentry_captured_exceptions = []
    sentry_scopes = []

    class MockSentryScope:
        def __init__(self):
            self.tags = {}
            self.contexts = {}
        def set_tag(self, k, v):
            self.tags[k] = v
        def set_context(self, k, v):
            self.contexts[k] = v

    def mock_push_scope():
        scope = MockSentryScope()
        sentry_scopes.append(scope)
        class ScopeContext:
            def __enter__(self):
                return scope
            def __exit__(self, *args):
                pass
        return ScopeContext()

    with (
        patch("app.modules.salon.services.is_within_followup_window", return_value=True),
        patch("app.modules.salon.services.send_message", new=AsyncMock(side_effect=RuntimeError("Evolution API 500 Network Timeout"))),
        patch("sentry_sdk.push_scope", side_effect=mock_push_scope),
        patch("sentry_sdk.capture_exception", side_effect=lambda exc: sentry_captured_exceptions.append(exc)),
    ):
        sent_count = await svc.run_post_service_followup_check()

    assert sent_count == 0
    # Flag debe haberse revertido a False para permitir reintento
    assert cita.post_service_sent is False

    # Verificar reporte en Sentry
    assert len(sentry_captured_exceptions) == 1
    assert "Evolution API 500" in str(sentry_captured_exceptions[0])
    assert len(sentry_scopes) == 1
    scope = sentry_scopes[0]
    assert scope.tags.get("module") == "post_service_followup"
    # Teléfono anonimizado (no exponer PII)
    assert scope.tags.get("phone_masked") == "+5199***766"
