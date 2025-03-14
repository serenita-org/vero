from tempfile import TemporaryDirectory

from providers import DB
from providers.db.migrations import MIGRATIONS


def test_db_run_migrations_empty_db() -> None:
    tmp_dir = TemporaryDirectory()
    db = DB(data_dir=tmp_dir.name)
    assert db.current_version == -1
    db.run_migrations()
    assert db.current_version == 1
    assert db.current_version == max(m.version for m in MIGRATIONS)


def test_db_run_migrations_with_data_in_db() -> None:
    tmp_dir = TemporaryDirectory()
    db = DB(data_dir=tmp_dir.name)
    assert db.current_version == -1
    db.run_migration_statements(migration=next(m for m in MIGRATIONS if m.version == 1))
    assert db.current_version == 1

    # Add data to tables here when you introduce new tables in a DB migration

    assert db.current_version == max(m.version for m in MIGRATIONS)
