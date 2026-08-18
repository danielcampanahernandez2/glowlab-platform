"""Tests for Glowlab Virtual Assistant System Prompt and Conversational Services."""
import asyncio
from app.modules.salon.prompts import CLIENT_SYSTEM_PROMPT, STAFF_SYSTEM_PROMPT
from app.modules.salon import services as svc


def test_system_prompt_structure():
    """Verifica que el CLIENT_SYSTEM_PROMPT contenga las 25 secciones esenciales."""
    assert "1. ROL DEL AGENTE" in CLIENT_SYSTEM_PROMPT
    assert "2. PRINCIPIO FUNDAMENTAL DE CONVERSACIÓN" in CLIENT_SYSTEM_PROMPT
    assert "3. JERARQUÍA DE INTENCIONES" in CLIENT_SYSTEM_PROMPT
    assert "4. REGLA DE INFORMACIÓN → CONTINUIDAD → RESERVA" in CLIENT_SYSTEM_PROMPT
    assert "5. NO TODA CONVERSACIÓN TERMINA EN UNA RESERVA" in CLIENT_SYSTEM_PROMPT
    assert "6. FLUJO DE AGENDAMIENTO" in CLIENT_SYSTEM_PROMPT
    assert "7. SI LA CLIENTA NO ESPECIFICA EL SERVICIO" in CLIENT_SYSTEM_PROMPT
    assert "8. SI LA CLIENTA PREGUNTA POR VARIOS SERVICIOS" in CLIENT_SYSTEM_PROMPT
    assert "9. RECOMENDACIONES" in CLIENT_SYSTEM_PROMPT
    assert "10. SERVICIOS" in CLIENT_SYSTEM_PROMPT
    assert "11. PRECIOS" in CLIENT_SYSTEM_PROMPT
    assert "12. INFORMACIÓN FALTANTE" in CLIENT_SYSTEM_PROMPT
    assert "13. DISPONIBILIDAD" in CLIENT_SYSTEM_PROMPT
    assert "14. CONFIRMACIÓN DE CITA" in CLIENT_SYSTEM_PROMPT
    assert "15. TONO Y PERSONALIDAD" in CLIENT_SYSTEM_PROMPT
    assert "16. LONGITUD DE LAS RESPUESTAS" in CLIENT_SYSTEM_PROMPT
    assert "17. PREGUNTAS" in CLIENT_SYSTEM_PROMPT
    assert "18. NO REPETIR PREGUNTAS" in CLIENT_SYSTEM_PROMPT
    assert "19. CONTEXTO DE LA CONVERSACIÓN" in CLIENT_SYSTEM_PROMPT
    assert "20. MANEJO DE MENSAJES AMBIGUOS" in CLIENT_SYSTEM_PROMPT
    assert "21. VENTAS" in CLIENT_SYSTEM_PROMPT
    assert "22. PROMOCIONES" in CLIENT_SYSTEM_PROMPT
    assert "23. EMOJIS" in CLIENT_SYSTEM_PROMPT
    assert "24. REGLAS ABSOLUTAS" in CLIENT_SYSTEM_PROMPT
    assert "25. REGLA DE ORO" in CLIENT_SYSTEM_PROMPT


def test_service_catalog_and_prices():
    """Verifica los servicios y precios oficiales según la Sección 10."""
    price_botox = svc.get_service_price("botox capilar")
    assert price_botox is not None
    assert "120" in price_botox

    price_keratina = svc.get_service_price("keratina")
    assert price_keratina is not None
    assert "160" in price_keratina

    price_hidratacion = svc.get_service_price("tratamiento de hidratación")
    assert price_hidratacion is not None
    assert "80" in price_hidratacion

    services_list = svc.list_services()
    assert "Botox capilar" in services_list and "120" in services_list
    assert "Keratina" in services_list and "160" in services_list
    assert "Pestañas" in services_list
    assert "Uñas" in services_list


def test_keyword_extract_hierarchy():
    """Verifica que las consultas no se clasifiquen como agendamiento forzado."""
    # Consulta de precio
    res1 = svc._keyword_extract("¿Cuánto cuesta el botox capilar?")
    assert res1["intent"] == "consultar"
    assert "botox" in res1["servicio"]

    # Recomendación
    res2 = svc._keyword_extract("Tengo el cabello seco, ¿qué me recomiendas?")
    assert res2["intent"] == "consultar"

    # Intención explícita de agendar
    res3 = svc._keyword_extract("Quiero reservar cita para botox capilar el sábado")
    assert res3["intent"] == "agendar"
    assert "botox" in res3["servicio"]
    assert res3["fecha"] == "sábado" or res3["fecha"] == "sabado"


async def test_generate_client_reply_fallback():
    """Verifica que la generación de respuesta en modo fallback respete el tono y reglas."""
    state = {}
    reply_price = await svc.generate_client_reply(state, "¿Cuánto cuesta el botox capilar?")
    assert "120" in reply_price
    assert "botox" in reply_price.lower()


    reply_rec = await svc.generate_client_reply(state, "Tengo el cabello muy seco")
    assert "hidratación" in reply_rec.lower() or "botox" in reply_rec.lower()

    reply_menu = await svc.generate_client_reply(state, "¿Qué servicios tienen?")
    reply_menu_lower = reply_menu.lower()
    assert "pestañas" in reply_menu_lower or "pestanas" in reply_menu_lower
    assert "uñas" in reply_menu_lower or "unas" in reply_menu_lower
    assert "botox" in reply_menu_lower or "capilar" in reply_menu_lower

