"""Inspect + clean mvp checkpoint rows in the global SqliteSaver DB."""
import sqlite3
import sys
from pathlib import Path

db_path = Path(__file__).resolve().parent.parent.parent / "data" / "database" / "village_planning.db"
conn = sqlite3.connect(str(db_path))
cur = conn.cursor()
cur.execute(
    "SELECT name FROM sqlite_master WHERE type='table' AND (name LIKE '%checkpoint%' OR name LIKE '%write%')"
)
tables = [r[0] for r in cur.fetchall()]
print("checkpoint tables:", tables)

for t in tables:
    cur.execute(f"SELECT COUNT(*) FROM {t}")
    total = cur.fetchone()[0]
    # count mvp- related rows if thread_id column exists
    cols = [c[1] for c in cur.execute(f"PRAGMA table_info({t})").fetchall()]
    mvp_count = 0
    if "thread_id" in cols:
        cur.execute(f"SELECT COUNT(*) FROM {t} WHERE thread_id LIKE '%mvp%'")
        mvp_count = cur.fetchone()[0]
    print(f"{t}: total={total} mvp={mvp_count} cols={cols}")

# Clean mvp threads from checkpoint + writes
mode = sys.argv[1] if len(sys.argv) > 1 else "inspect"
if mode == "clean":
    for t in tables:
        cols = [c[1] for c in cur.execute(f"PRAGMA table_info({t})").fetchall()]
        if "thread_id" in cols:
            cur.execute(f"DELETE FROM {t} WHERE thread_id LIKE '%mvp%'")
            print(f"{t}: deleted mvp rows")
    conn.commit()
    print("CLEANED")
conn.close()
