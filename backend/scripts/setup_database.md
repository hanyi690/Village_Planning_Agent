# Database Setup Instructions

## Prerequisites

The database implementation requires additional Python packages:

```bash
pip install sqlmodel>=0.0.14
pip install aiosqlite>=0.19.0
```

Or install from requirements.txt:

```bash
cd backend
pip install -r requirements.txt
```

## Quick Setup

1. **Install dependencies**
   ```bash
   pip install sqlmodel aiosqlite
   ```

2. **Initialize database (async)**
   ```bash
   python -c "import asyncio; from backend.database import init_async_db; asyncio.run(init_async_db())"
   ```

3. **Validate installation**
   ```bash
   python backend/scripts/validate_database.py
   ```

4. **Migrate existing data (optional)**
   ```bash
   python backend/scripts/migrate_checkpoints.py
   ```

## Manual Testing

After setup, test the API:

```bash
# Start backend
python backend/main.py

# In another terminal, create a planning session
curl -X POST http://localhost:8000/api/planning/start \
  -H "Content-Type: application/json" \
  -d '{
    "project_name": "测试村",
    "village_data": "测试村庄数据",
    "task_description": "制定村庄总体规划方案",
    "enable_review": false
  }'

# Verify in database
sqlite3 data/village_planning.db "SELECT session_id, project_name, status FROM planning_sessions;"

# Restart backend and verify session persists
# Press Ctrl+C, then restart:
python backend/main.py

# Check session still exists
curl http://localhost:8000/api/planning/sessions
```

## Troubleshooting

### ModuleNotFoundError: No module named 'sqlmodel'

Install the required package:
```bash
pip install sqlmodel
```

### Database file not created

Check that the `data/` directory exists and is writable:
```bash
mkdir -p data
ls -la data/
```

### Permission errors

Ensure write permissions:
```bash
chmod +w data/village_planning.db
```

### Import errors

Verify Python path includes project root:
```bash
export PYTHONPATH="${PYTHONPATH}:$(pwd)"
python backend/scripts/validate_database.py
```

## Next Steps

After successful setup:

1. **Review documentation**: `docs/backend.md`
2. **Run validation script**: `python backend/scripts/validate_database.py`
3. **Start backend**: `python backend/main.py`
4. **Test API endpoints**: See `docs/backend.md`

## Architecture

The database layer is fully async using SQLAlchemy async engine with `aiosqlite`:

- **Engine**: `backend/database/engine.py` - Async database connection management
- **Models**: `backend/database/models.py` - SQLModel definitions
- **Operations**: `backend/database/operations_async.py` - Async CRUD operations
- **Checkpointer**: LangGraph's `AsyncSqliteSaver` for state persistence

All database operations are async and support concurrent access with WAL mode enabled.