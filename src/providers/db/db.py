import logging
import sqlite3
from collections.abc import Generator
from pathlib import Path
from typing import Any

from providers.db.migrations import MIGRATIONS, DbMigration


class DB:
    def __init__(
        self,
        data_dir: str,
    ):
        self.logger = logging.getLogger(self.__class__.__name__)

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

    def batch_host_parameters(
        self, host_parameter_values: list[str]
    ) -> Generator[list[str], None, None]:
        """
        SQLite has a limit on the number of host parameters it can process
        in a single query set to 32,766 as of SQLite 3.32.0.
        """
        batch_size = 30_000

        for i in range(0, len(host_parameter_values), batch_size):
            yield host_parameter_values[i : i + batch_size]

    def _check_parameter_count(self, parameters: tuple[Any, ...] | list[Any]) -> None:
        if len(parameters) >= 32766:
            # SQLite limit: Maximum Number Of Host Parameters In A Single SQL Statement
            raise ValueError(f"Too many host parameters provided: ({len(parameters)})")

    def fetch_one(
        self, sql: str, parameters: tuple[Any, ...] | list[Any] = ()
    ) -> tuple[tuple[Any, ...] | None, int]:
        self._check_parameter_count(parameters)

        with self.connection:
            cursor = self.connection.execute(sql, parameters)
            return cursor.fetchone(), cursor.rowcount

    def fetch_all(
        self, sql: str, parameters: tuple[Any, ...] | list[Any] = ()
    ) -> list[Any]:
        self._check_parameter_count(parameters)

        with self.connection:
            return self.connection.execute(sql, parameters).fetchall()
