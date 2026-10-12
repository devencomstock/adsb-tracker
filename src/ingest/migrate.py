"""Apply the numbered SQL migrations in db/migrations/ (decision #20).

Each migration file runs in its own transaction and is recorded in schema_migrations, so running
this again applies only new files. Connection settings come from the standard libpq environment
variables (PGHOST, PGPORT, PGUSER, PGPASSWORD, PGDATABASE). Values in the repo's .env file are
used for any that aren't already set.

Run:  python -m ingest.migrate        (with PYTHONPATH=src)
"""

from __future__ import annotations

import os
from pathlib import Path

import psycopg

REPO = Path(__file__).resolve().parents[2]
MIGRATIONS = REPO / "db" / "migrations"
ENV_FILE = REPO / ".env"


def load_env_file(path: Path = ENV_FILE) -> None:
    """Set KEY=value lines from a .env file as environment variables, without overriding."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())


def migration_files(directory: Path = MIGRATIONS) -> list[Path]:
    """The migration files, in filename order (0001_..., 0002_...)."""
    return sorted(directory.glob("*.sql"))


def apply_migrations(conn: psycopg.Connection, directory: Path = MIGRATIONS) -> list[str]:
    """Apply every migration not yet recorded; returns the names applied this time."""
    with conn.transaction():
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            " name text PRIMARY KEY,"
            " applied_at timestamptz NOT NULL DEFAULT now())"
        )
    done = {row[0] for row in conn.execute("SELECT name FROM schema_migrations")}
    applied = []
    for path in migration_files(directory):
        if path.name in done:
            continue
        with conn.transaction():
            conn.execute(path.read_text(encoding="utf-8"))
            conn.execute("INSERT INTO schema_migrations (name) VALUES (%s)", (path.name,))
        applied.append(path.name)
    return applied


def main() -> None:
    load_env_file()
    with psycopg.connect(autocommit=True) as conn:
        applied = apply_migrations(conn)
    print(f"applied {len(applied)} migration(s): {', '.join(applied) or 'none (up to date)'}")


if __name__ == "__main__":
    main()
