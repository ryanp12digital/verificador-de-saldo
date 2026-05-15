"""Resolucao de listas de contas: Postgres (prioritario) ou JSON / .env (legado)."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Dict, Set, Tuple

from db import (
    google_accounts_from_db,
    is_database_configured,
    meta_whitelist_labels_from_db,
    migrate,
)
from meta_ads_balance import load_accounts_from_json, parse_account_labels, parse_allowed_account_ids


def load_meta_allowlist_for_monitor(
    json_path: str,
) -> Tuple[Set[str], Dict[str, str], str, bool]:
    """
    Retorna (allowed_ids, labels, fonte_descricao, strict_whitelist).
    strict_whitelist=True quando Postgres esta ativo: lista vazia => nao monitorar nenhuma conta.
    """
    if is_database_configured():
        migrate()
        ids, labels = meta_whitelist_labels_from_db()
        return ids, labels, "postgres", True

    allowed_ids, labels = load_accounts_from_json(json_path)
    env_ids = parse_allowed_account_ids(os.getenv("META_ALLOWED_ACCOUNT_IDS", ""))
    env_labels = parse_account_labels(os.getenv("META_ACCOUNT_LABELS", ""))
    merged_ids = allowed_ids or env_ids
    merged_labels = labels or env_labels
    source = "json" if allowed_ids else ("env" if env_ids else "nenhum")
    return merged_ids, merged_labels, source, False


def load_google_accounts_for_monitor(json_path: str) -> Tuple[list[dict[str, str]], str, bool]:
    """
    Retorna (lista de {customer_id, name}, fonte, strict).
    strict=True com Postgres: sem linhas => lista vazia (monitor nao consulta nada).
    """
    if is_database_configured():
        migrate()
        rows = google_accounts_from_db()
        return rows, "postgres", True

    path = Path(json_path)
    if not path.exists():
        return [], "json-ausente", False

    raw = json.loads(path.read_text(encoding="utf-8"))
    accounts = raw.get("accounts", [])
    if not isinstance(accounts, list):
        raise ValueError("Campo 'accounts' do JSON deve ser uma lista.")

    out: list[dict[str, str]] = []
    for item in accounts:
        if not isinstance(item, dict):
            continue
        cid = "".join(ch for ch in str(item.get("customer_id", "")) if ch.isdigit())[:10]
        name = str(item.get("name", "")).strip()
        if not cid:
            continue
        out.append({"customer_id": cid, "name": name or cid})
    return out, "json", False
