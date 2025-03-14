import msgspec


class DbMigration(msgspec.Struct):
    version: int
    description: str
    statements: list[str]
    # Automatically executes a UPDATE db_version statement
    # after migrations are done
    bump_version: bool
    autocommit_mode: bool = False


MIGRATIONS = [
    DbMigration(
        version=0,
        description="Change into WAL mode",
        statements=[
            "PRAGMA journal_mode=WAL;",
        ],
        autocommit_mode=True,
        bump_version=False,
    ),
    DbMigration(
        version=1,
        description="Create initial db_version table",
        statements=[
            "CREATE TABLE db_version (version INTEGER) STRICT;",
            "INSERT INTO db_version VALUES (1);",
        ],
        bump_version=False,
    ),
]
