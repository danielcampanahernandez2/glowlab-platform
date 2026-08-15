import asyncio
import os
import sys
sys.path.insert(0, os.path.abspath("."))
from sqlalchemy import text
from app.core.database import engine

async def check():
    async with engine.begin() as conn:
        res = await conn.execute(text("SELECT column_name FROM information_schema.columns WHERE table_name = 'conversaciones'"))
        print('conversaciones cols:', [r[0] for r in res.fetchall()])
        res2 = await conn.execute(text("SELECT column_name FROM information_schema.columns WHERE table_name = 'citas'"))
        print('citas cols:', [r[0] for r in res2.fetchall()])
        res3 = await conn.execute(text("SELECT column_name FROM information_schema.columns WHERE table_name = 'tenants'"))
        print('tenants cols:', [r[0] for r in res3.fetchall()])

if __name__ == '__main__':
    asyncio.run(check())
