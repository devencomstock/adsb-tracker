"""Checkpoint A (Phase 5): migrations and schema, on a throwaway database.

Each test session creates its own database named adsb_test_<random>, applies the migrations, and
drops it at the end. The dev database (PGDATABASE) is never touched. If PostgreSQL isn't
reachable, every test here is skipped with a message saying how to start it.
"""

from __future__ import annotations

import os
import secrets
from collections.abc import Iterator

import psycopg
import pytest
from psycopg import errors

from ingest.migrate import apply_migrations, load_env_file, migration_files

pytestmark = pytest.mark.db

KLAF_LON, KLAF_LAT = -86.936898, 40.412304  # FAA NFDC airport record (decision #19)


@pytest.fixture(scope="session")
def test_dbname() -> Iterator[str]:
    load_env_file()
    name = f"adsb_test_{secrets.token_hex(4)}"
    assert name != os.environ.get("PGDATABASE"), "refusing to use the dev database for tests"
    try:
        admin = psycopg.connect(dbname="postgres", autocommit=True, connect_timeout=3)
    except psycopg.OperationalError as exc:
        host = os.environ.get("PGHOST", "localhost")
        port = os.environ.get("PGPORT", "5432")
        pytest.skip(
            f"PostgreSQL not reachable at {host}:{port} ({exc.__class__.__name__}). "
            "Start it with `docker compose up -d` and make sure .env has the PG* settings."
        )
    with admin:
        admin.execute(f'CREATE DATABASE "{name}"')
        try:
            yield name
        finally:
            admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


@pytest.fixture(scope="session")
def migrated(test_dbname: str) -> list[str]:
    with psycopg.connect(dbname=test_dbname, autocommit=True) as conn:
        return apply_migrations(conn)


@pytest.fixture
def conn(test_dbname: str, migrated: list[str]) -> Iterator[psycopg.Connection]:
    with psycopg.connect(dbname=test_dbname, autocommit=True) as connection:
        connection.execute("TRUNCATE positions, aircraft")
        yield connection


def insert_position(conn: psycopg.Connection, source: str = "decoder", **overrides) -> None:
    row = {
        "icao24": "a2eea2",
        "observed_at": "2026-10-12T19:21:25Z",
        "lon": KLAF_LON,
        "lat": KLAF_LAT,
    }
    row.update(overrides)
    conn.execute(
        "INSERT INTO positions (source, icao24, observed_at, geom, altitude_ft)"
        " VALUES (%s, %s, %s, ST_SetSRID(ST_MakePoint(%s, %s), 4326), 900)",
        (source, row["icao24"], row["observed_at"], row["lon"], row["lat"]),
    )


def test_migrations_apply(test_dbname: str, migrated: list[str]) -> None:
    assert migrated == [p.name for p in migration_files()] == ["0001_init.sql"]
    with psycopg.connect(dbname=test_dbname) as conn:
        tables = {
            r[0]
            for r in conn.execute("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
        }
        assert {"aircraft", "positions", "schema_migrations"} <= tables
        assert conn.execute("SELECT PostGIS_Version()").fetchone() is not None


def test_running_migrations_twice_is_a_no_op(test_dbname: str, migrated: list[str]) -> None:
    with psycopg.connect(dbname=test_dbname, autocommit=True) as conn:
        before = conn.execute("SELECT name, applied_at FROM schema_migrations").fetchall()
        assert apply_migrations(conn) == []
        after = conn.execute("SELECT name, applied_at FROM schema_migrations").fetchall()
    assert before == after


def test_duplicate_source_icao24_observed_at_is_rejected(conn: psycopg.Connection) -> None:
    insert_position(conn)
    with pytest.raises(errors.UniqueViolation):
        insert_position(conn)
    insert_position(conn, source="adsblol")  # the same moment from another source is fine


def test_opensky_source_is_rejected(conn: psycopg.Connection) -> None:
    with pytest.raises(errors.CheckViolation):
        insert_position(conn, source="opensky")


def test_point_at_klaf_is_found_by_st_dwithin(conn: psycopg.Connection) -> None:
    insert_position(conn, icao24="a2eea2")  # at KLAF
    insert_position(conn, icao24="ad617b", lat=KLAF_LAT + 1)  # 60 NM north
    near = conn.execute(
        "SELECT icao24 FROM positions WHERE ST_DWithin("
        " geom::geography, ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography, %s)",
        (KLAF_LON, KLAF_LAT, 5000),  # metres
    ).fetchall()
    assert near == [("a2eea2",)]


def test_every_column_has_a_comment(conn: psycopg.Connection) -> None:
    missing = conn.execute(
        "SELECT table_name, column_name FROM information_schema.columns c"
        " WHERE table_schema = 'public' AND table_name IN ('aircraft', 'positions')"
        " AND column_name <> 'id'"
        " AND col_description(("
        "   quote_ident(table_name))::regclass, ordinal_position) IS NULL"
    ).fetchall()
    assert missing == []
