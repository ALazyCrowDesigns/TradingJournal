import os
from pathlib import Path

from alembic import command
from alembic.config import Config


def test_alembic_upgrade_head(tmp_path: Path) -> None:
    # Use a temp DB path
    db_path = tmp_path / "test.sqlite3"
    os.environ["DB_PATH"] = str(db_path)

    cfg = Config("alembic.ini")
    command.upgrade(cfg, "head")

    assert db_path.exists()
