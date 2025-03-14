import logging
import sqlite3
from pathlib import Path
from typing import Any

from providers.db.migrations import MIGRATIONS, DbMigration


class DB:
    def __init__(
        self,
        data_dir: str,
    ):
        self.logger = logging.getLogger(self.__class__.__name__)
        self.logger.setLevel(logging.getLogger().level)

        self.db_filepath = Path(data_dir) / "vero.db"
        self.connection = sqlite3.connect(self.db_filepath, autocommit=False)

    @property
    def current_version(self) -> int:
        try:
            with self.connection:
                version = self.connection.execute(
                    "SELECT version FROM db_version;"
                ).fetchone()[0]
                return int(version)
        except sqlite3.OperationalError as e:
            if "no such table: db_version" in str(e):
                # DB does not exist yet
                return -1
            raise

    def run_migration_statements(self, migration: DbMigration) -> None:
        self.logger.info(f"Migrating to version {migration.version}")

        conn = self.connection

        # sqlite3 with autocommit=False cannot change the WAL journal mode of the
        # database because sqlite3 implicitly begins a transaction. The initial
        # migration (version 0) has its autocommit attribute set to True to
        # make it possible to run its journal mode-changing statement.
        if migration.autocommit_mode:
            conn = sqlite3.connect(self.db_filepath, autocommit=True)

        with conn:
            for stmt in migration.statements:
                conn.executescript(stmt)
            if migration.bump_version:
                conn.execute("UPDATE db_version SET version = ?", (migration.version,))

    def run_migrations(self) -> None:
        if self.current_version == max(m.version for m in MIGRATIONS):
            return

        self.logger.info("Running database migrations")

        for migration in sorted(MIGRATIONS, key=lambda m: m.version):
            if self.current_version >= migration.version:
                # Migration already applied
                continue

            self.run_migration_statements(migration)

    def fetch_one(
        self, sql: str, parameters: tuple[Any, ...] = ()
    ) -> tuple[tuple[Any, ...] | None, int]:
        with self.connection:
            cursor = self.connection.execute(sql, parameters)
            return cursor.fetchone(), cursor.rowcount

    def fetch_all(self, sql: str, parameters: tuple[Any, ...] = ()) -> list[Any]:
        with self.connection:
            return self.connection.execute(sql, parameters).fetchall()
