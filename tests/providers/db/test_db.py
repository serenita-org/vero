from pathlib import Path

from providers import DB
from providers.db.migrations import MIGRATIONS


def test_db_run_migrations_empty_db(tmp_path: Path) -> None:
    db = DB(data_dir=str(tmp_path))
    assert db.current_version == -1
    db.run_migrations()
    assert db.current_version == 2
    assert db.current_version == max(m.version for m in MIGRATIONS)


def test_db_run_migrations_with_data_in_db(tmp_path: Path) -> None:
    db = DB(data_dir=str(tmp_path))
    assert db.current_version == -1
    db.run_migration_statements(migration=next(m for m in MIGRATIONS if m.version == 1))
    assert db.current_version == 1

    db.run_migration_statements(migration=next(m for m in MIGRATIONS if m.version == 2))
    assert db.current_version == 2
    data = [
        ("0x" + "a" * 96, "http://remote-signer-1:9000", None, None, None),
        (
            "0x" + "b" * 96,
            "http://remote-signer-1:9000",
            "0x" + "a" * 40,
            "50000000",
            "custom-graffiti",
        ),
        ("0x" + "c" * 96, "http://remote-signer-2:9000", "0x" + "0" * 40, None, None),
        ("0x" + "d" * 96, "http://remote-signer-2:9000", None, "100000000", None),
        ("0x" + "e" * 96, "http://remote-signer-2:9000", None, None, "my-graffiti"),
    ]
    with db.connection as conn:
        conn.executemany("""INSERT INTO keymanager_data VALUES (?, ?, ?, ?, ?)""", data)

    # Add data to tables here when you introduce new tables in a DB migration

    assert db.current_version == max(m.version for m in MIGRATIONS)
