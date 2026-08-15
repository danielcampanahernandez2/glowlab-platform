import os
import sys

sys.path.insert(0, os.path.abspath("."))
from app.core.config import settings

print("=== VERIFICACIÓN DE CONFIGURACIÓN ===")
print("AI_PROVIDER:", settings.AI_PROVIDER)
print("DEEPSEEK_API_KEY Configurada:", bool(settings.DEEPSEEK_API_KEY))
print("DEEPSEEK_API_KEY Longitud:", len(settings.DEEPSEEK_API_KEY))
print("DEEPSEEK_BASE_URL:", settings.DEEPSEEK_BASE_URL)
print("DEEPSEEK_MODEL:", settings.DEEPSEEK_MODEL)
print("Endpoint Activo:", settings.get_ai_endpoint())
print("Modelo Activo:", settings.get_ai_model())
print("Tiene Key Activa:", settings.has_active_ai_key())
auth_header = settings.get_ai_headers().get("Authorization", "")
print("Header Authorization Presente:", bool(auth_header))
print("Header Formato Correcto:", auth_header.startswith("Bearer sk-") if auth_header else False)
