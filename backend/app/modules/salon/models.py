"""Modelos SQLAlchemy para la gestión del salón Glowlab."""
from datetime import datetime
from sqlalchemy import Boolean, Column, DateTime, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from app.core.database import Base


class Cliente(Base):
    """Perfil de una clienta del salón."""
    __tablename__ = "clientes"

    id = Column(Integer, primary_key=True, index=True)
    phone = Column(String(20), unique=True, nullable=False, index=True)
    nombre = Column(String(200))
    ultima_visita = Column(DateTime)
    total_visitas = Column(Integer, default=0)
    historial_servicios = Column(JSONB, default=list)
    preferencias = Column(JSONB, default=dict)
    notas = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Conversacion(Base):
    """Estado durable de una conversación de WhatsApp, identificado por teléfono."""
    __tablename__ = "conversaciones"

    id = Column(Integer, primary_key=True, index=True)
    phone = Column(String(32), unique=True, nullable=False, index=True)
    estado = Column(JSONB, default=dict, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Cita(Base):
    """
    Cita registrada en el sistema.

    Estados posibles:
        pendiente    → creada, esperando voucher
        confirmada   → adelanto validado, lista para atender
        completada   → servicio realizado
        cancelada    → cancelada por clienta o equipo
        no_asistio   → la clienta no se presentó
        derivada     → en revisión manual de una asesora
    """
    __tablename__ = "citas"

    id = Column(Integer, primary_key=True, index=True)
    cliente_phone = Column(String(20), nullable=False, index=True)
    cliente_nombre = Column(String(200))

    # Servicio y asignación interna
    servicio = Column(String(300), nullable=False)
    asesora = Column(String(100))       # Lizbeth | Anali (uso interno)

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
