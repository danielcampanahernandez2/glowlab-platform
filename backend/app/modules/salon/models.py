"""Modelos SQLAlchemy para la gestión del SaaS Multi-Tenant (Glowlab Platform)."""
from datetime import datetime
from sqlalchemy import Boolean, Column, DateTime, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from app.core.database import Base


class Tenant(Base):
    """
    Modelo de Negocio / Tenant (SaaS Multi-Tenant).
    Representa un salón de belleza, spa, clínica dental, centro estético, etc.
    """
    __tablename__ = "tenants"

    id = Column(Integer, primary_key=True, index=True)
    slug = Column(String(100), unique=True, nullable=False, index=True)  # ej. "glowlab", "sonrisas-dental"
    name = Column(String(200), nullable=False)                            # ej. "Glowlab Salón", "Clínica Dental Sonrisas"
    industry = Column(String(100), default="salon")                       # ej. "salon", "dental", "spa", "clinica"
    status = Column(String(50), default="active")                         # active, suspended, trial

    # Plan SaaS y Cuotas de consumo
    plan_name = Column(String(50), default="starter")                     # "starter", "pro", "enterprise"
    max_appointments_per_month = Column(Integer, default=100)             # ej. 100, 300, 1000
    max_ai_cost_usd_per_month = Column(Numeric(10, 2), default=15.0)      # ej. 15.00, 50.00, 150.00
    billing_cycle_day = Column(Integer, default=1)                        # día de corte del mes (1-28)

    # Configuración avanzada de negocio
    settings = Column(JSONB, default=dict, nullable=False)
    # settings = {
    #     "entity_labels": {"customer": "clienta", "staff": "asesora", "item": "servicio", "booking": "cita"},
    #     "slot_interval_minutes": 60,
    #     "requires_deposit": True,
    #     "deposit_amount": 20.0,
    #     "currency": "PEN",
    #     "evolution_instance": "glowlab-bot",
    #     "business_hours": {"start": "10:00", "end": "18:00", "closed_days": [6]}
    # }

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Service(Base):
    """
    Servicio, tratamiento o procedimiento ofrecido por un tenant específico.
    """
    __tablename__ = "services"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(String(100), default="glowlab", nullable=False, index=True)
    name = Column(String(200), nullable=False, index=True)          # ej. "Botox capilar", "Limpieza dental profunda"
    category = Column(String(100), nullable=False, index=True)      # ej. "Tratamientos capilares", "Limpieza y Prevención"
    price = Column(Numeric(10, 2), nullable=False)                  # ej. 120.00
    price_prefix = Column(String(20), default="")                   # ej. "desde", ""
    duration_minutes = Column(Integer, default=60, nullable=False)  # ej. 30, 45, 60, 90
    description = Column(Text)                                      # ej. "Mejora la apariencia, brillo y sedosidad"
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class StaffMember(Base):
    """
    Miembro del personal, especialista o profesional de atención del tenant.
    """
    __tablename__ = "staff_members"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(String(100), default="glowlab", nullable=False, index=True)
    name = Column(String(200), nullable=False)                      # ej. "Lizbeth", "Dr. Carlos Mendoza"
    phone = Column(String(30), nullable=False, index=True)          # ej. "51992509246"
    role = Column(String(100), default="specialist")                # ej. "lashista", "estilista", "odontologo", "admin"
    skills = Column(JSONB, default=list)                            # ej. ["pestañas", "cejas"] o ["limpieza", "endodoncia"]
    weekly_schedule = Column(JSONB, default=dict)                   # ej. {"start": "10:00", "end": "18:00"}
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Cliente(Base):
    """Perfil de un cliente/paciente asociado a un tenant específico."""
    __tablename__ = "clientes"
    __table_args__ = (
        UniqueConstraint("tenant_id", "phone", name="uq_cliente_tenant_phone"),
    )

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(String(100), default="glowlab", nullable=False, index=True)
    phone = Column(String(20), nullable=False, index=True)
    nombre = Column(String(200))
    ultima_visita = Column(DateTime)
    total_visitas = Column(Integer, default=0)
    historial_servicios = Column(JSONB, default=list)
    preferencias = Column(JSONB, default=dict)
    notas = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Conversacion(Base):
    """Estado durable de una conversación de WhatsApp, identificado por (tenant_id, phone)."""
    __tablename__ = "conversaciones"
    __table_args__ = (
        UniqueConstraint("tenant_id", "phone", name="uq_conversacion_tenant_phone"),
    )

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(String(100), default="glowlab", nullable=False, index=True)
    phone = Column(String(32), nullable=False, index=True)
    estado = Column(JSONB, default=dict, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Cita(Base):
    """
    Cita o reserva registrada en el sistema asociada a un tenant.

    Estados posibles:
        pendiente    → creada, esperando voucher
        confirmada   → adelanto validado, lista para atender
        completada   → servicio realizado
        cancelada    → cancelada por cliente o equipo
        no_asistio   → el cliente no se presentó
        derivada     → en revisión manual de un asesor/médico
    """
    __tablename__ = "citas"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(String(100), default="glowlab", nullable=False, index=True)
    cliente_phone = Column(String(20), nullable=False, index=True)
    cliente_nombre = Column(String(200))

    # Servicio / tratamiento y asignación interna
    servicio = Column(String(300), nullable=False)
    asesora = Column(String(100))       # Profesional / staff asignado

    # Agenda
    fecha = Column(String(20))          # YYYY-MM-DD
    hora = Column(String(10))           # HH:MM

    # Estado de la cita
    estado = Column(String(50), default="pendiente")

    # Pago / Adelanto
    adelanto_requerido = Column(Boolean, default=True)
    adelanto_pagado = Column(Boolean, default=False)
    adelanto_monto = Column(Numeric(10, 2), default=20.0)
    voucher_url = Column(String(500))

    # Notas
    observaciones = Column(Text)

    # Control de recordatorios y seguimiento
    recordatorio_24h_enviado = Column(Boolean, default=False)
    recordatorio_2h_enviado = Column(Boolean, default=False)
    seguimiento_enviado = Column(Boolean, default=False)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class OpenAIUsageLog(Base):
    """
    Registro detallado de consumo de tokens y costo estimado por llamada a la API de IA.
    Permite monitoreo de costes y facturación por tenant.
    """
    __tablename__ = "openai_usage_logs"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(String(100), default="glowlab", nullable=False, index=True)
    phone_masked = Column(String(30), index=True)
    provider = Column(String(50), default="openai")
    model = Column(String(50), default="gpt-4o-mini")
    prompt_tokens = Column(Integer, default=0)
    completion_tokens = Column(Integer, default=0)
    total_tokens = Column(Integer, default=0)
    cost_usd = Column(Numeric(10, 6), default=0.0)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
