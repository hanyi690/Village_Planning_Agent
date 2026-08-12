from pathlib import Path


def test_checkpoint_db_is_separate_from_business_db():
    from app.database.engine import CHECKPOINT_DB_PATH, DB_PATH

    assert CHECKPOINT_DB_PATH.name == "checkpoints.db"
    assert CHECKPOINT_DB_PATH != DB_PATH
    assert CHECKPOINT_DB_PATH.parent == DB_PATH.parent
