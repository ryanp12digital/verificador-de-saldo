"""PostgreSQL: contas monitoradas (Meta e Google Ads)."""

from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Any, Generator, Iterable, Literal, Optional, Tuple
from urllib.parse import quote_plus

import psycopg2
from psycopg2.extras import RealDictCursor

Provider = Literal["meta", "google_ads"]


def _strip(value: Optional[str]) -> str:
    return (value or "").strip()


def database_url_from_env() -> Optional[str]:
    direct = _strip(os.getenv("DATABASE_URL"))
    if direct:
        return direct

    host = _strip(os.getenv("POSTGRES_HOST"))
    user = _strip(os.getenv("POSTGRES_USER"))
    password = os.getenv("POSTGRES_PASSWORD")
    dbname = _strip(os.getenv("POSTGRES_DB"))
    if not (host and user and password is not None and dbname):
        return None

    port = _strip(os.getenv("POSTGRES_PORT")) or "5432"
    sslmode = _strip(os.getenv("POSTGRES_SSLMODE"))
    user_q = quote_plus(user)
    pass_q = quote_plus(password)
    base = f"postgresql://{user_q}:{pass_q}@{host}:{port}/{dbname}"
    if sslmode:
        return f"{base}?sslmode={quote_plus(sslmode)}"
    return base


def is_database_configured() -> bool:
    return database_url_from_env() is not None


@contextmanager
def get_connection() -> Generator[Any, None, None]:
    url = database_url_from_env()
    if not url:
        raise RuntimeError("PostgreSQL nao configurado (DATABASE_URL ou POSTGRES_*).")
    conn = psycopg2.connect(url, connect_timeout=15)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


MIGRATION_SQL = """
CREATE TABLE IF NOT EXISTS monitored_accounts (
    id BIGSERIAL PRIMARY KEY,
    provider VARCHAR(32) NOT NULL CHECK (provider IN ('meta', 'google_ads')),
    external_id TEXT NOT NULL,
    display_name TEXT NOT NULL DEFAULT '',
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (provider, external_id)
);

CREATE INDEX IF NOT EXISTS idx_monitored_accounts_provider
    ON monitored_accounts (provider);

CREATE INDEX IF NOT EXISTS idx_monitored_accounts_enabled
    ON monitored_accounts (provider, enabled);
"""


def migrate() -> None:
    if not is_database_configured():
        return
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(MIGRATION_SQL)


def list_accounts(provider: Provider, *, include_disabled: bool = False) -> list[dict[str, Any]]:
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            if include_disabled:
                cur.execute(
                    """
                    SELECT external_id, display_name, enabled
                    FROM monitored_accounts
                    WHERE provider = %s
                    ORDER BY id ASC
                    """,
                    (provider,),
                )
            else:
                cur.execute(
                    """
                    SELECT external_id, display_name, enabled
                    FROM monitored_accounts
                    WHERE provider = %s AND enabled = TRUE
                    ORDER BY id ASC
                    """,
                    (provider,),
                )
            return [dict(row) for row in cur.fetchall()]


def replace_accounts(
    provider: Provider,
    rows: Iterable[Tuple[str, str, bool]],
) -> None:
    batch = [(provider, eid, name, enabled) for eid, name, enabled in rows]
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM monitored_accounts WHERE provider = %s", (provider,))
            if batch:
                cur.executemany(
                    """
                    INSERT INTO monitored_accounts (provider, external_id, display_name, enabled)
                    VALUES (%s, %s, %s, %s)
                    """,
                    batch,
                )


def meta_whitelist_labels_from_db() -> tuple[set[str], dict[str, str]]:
    rows = list_accounts("meta", include_disabled=False)
    allowed: set[str] = set()
    labels: dict[str, str] = {}
    for row in rows:
        eid = str(row["external_id"]).strip()
        if not eid:
            continue
        allowed.add(eid)
        name = str(row.get("display_name") or "").strip()
        if name:
            labels[eid] = name
    return allowed, labels


def google_accounts_from_db() -> list[dict[str, str]]:
    rows = list_accounts("google_ads", include_disabled=False)
    out: list[dict[str, str]] = []
    for row in rows:
        cid = str(row["external_id"]).strip()
        if not cid:
            continue
        out.append(
            {
                "customer_id": cid,
                "name": str(row.get("display_name") or "").strip() or cid,
            }
        )
    return out
