import asyncio
import os
import sys
sys.path.insert(0, os.path.abspath("."))
from sqlalchemy import text
from app.core.database import engine, Base
from app.modules.salon.models import Tenant, Service, StaffMember, Cliente, Conversacion, Cita, OpenAIUsageLog

async def migrate():
    async with engine.begin() as conn:
        # Recreate tables or add missing columns
        print("Adding missing columns to tables...")
        statements = [
            "ALTER TABLE conversaciones ADD COLUMN IF NOT EXISTS tenant_id VARCHAR(100) DEFAULT 'glowlab' NOT NULL;",
            "ALTER TABLE citas ADD COLUMN IF NOT EXISTS tenant_id VARCHAR(100) DEFAULT 'glowlab' NOT NULL;",
            "ALTER TABLE clientes ADD COLUMN IF NOT EXISTS tenant_id VARCHAR(100) DEFAULT 'glowlab' NOT NULL;",
            "ALTER TABLE openai_usage_logs ADD COLUMN IF NOT EXISTS tenant_id VARCHAR(100) DEFAULT 'glowlab' NOT NULL;",
        ]
        for stmt in statements:
            try:
                await conn.execute(text(stmt))
                print(f"Executed: {stmt}")
            except Exception as e:
                print(f"Error on {stmt}: {e}")
        
        # Ensure all tables in metadata exist
        await conn.run_sync(Base.metadata.create_all)
        print("Base.metadata.create_all completed.")

if __name__ == "__main__":
    asyncio.run(migrate())
