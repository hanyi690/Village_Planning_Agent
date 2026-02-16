import aiosqlite
import asyncio

async def check():
    conn = await aiosqlite.connect('data/village_planning.db')
    cursor = await conn.execute('SELECT name FROM sqlite_master WHERE type="table" AND name NOT LIKE "sqlite_%"')
    tables = [row[0] for row in await cursor.fetchall()]
    print('Tables:', tables)
    if 'checkpoints' in tables:
        cursor = await conn.execute('PRAGMA table_info(checkpoints)')
        cols = await cursor.fetchall()
        print('\ncheckpoints columns:')
        [print(f'  {col[1]} ({col[2]})') for col in cols]
    if 'writes' in tables:
        cursor = await conn.execute('PRAGMA table_info(writes)')
        cols = await cursor.fetchall()
        print('\nwrites columns:')
        [print(f'  {col[1]} ({col[2]})') for col in cols]
    await conn.close()

asyncio.run(check())