"""
Servidor da dashboard: arquivos estaticos em web/ e API JSON.

Execucao (na raiz do repositorio):
  pip install -r requirements.txt
  python execution/dashboard_server.py

Variaveis: DASHBOARD_API_TOKEN (obrigatorio), DASHBOARD_HOST (default 127.0.0.1),
  DASHBOARD_PORT (default 5050)
"""

from __future__ import annotations

import json
import os
import sys
from functools import wraps
from pathlib import Path
from typing import Any, Callable, List, Tuple

from dotenv import load_dotenv
from flask import Flask, jsonify, request, send_from_directory

REPO_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(REPO_ROOT / ".env")

# pylint: disable=wrong-import-position
from db import is_database_configured, list_accounts, migrate, replace_accounts
from meta_ads_balance import (
    fetch_meta_balances_for_ids,
    load_accounts_from_json,
    normalize_account_id,
)

WEB_DIR = REPO_ROOT / "web"


def env_int(name: str, default: int) -> int:
    raw = os.getenv(name, str(default)).strip()
    return int(raw)


def env_required(name: str) -> str:
    v = os.getenv(name, "").strip()
    if not v:
        raise ValueError(name)
    return v


def get_bearer_token() -> str:
    auth = request.headers.get("Authorization", "") or ""
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return ""


def require_dashboard_token(view: Callable[..., Any]) -> Callable[..., Any]:
    @wraps(view)
    def wrapped(*args: Any, **kwargs: Any) -> Any:
        expected = os.getenv("DASHBOARD_API_TOKEN", "").strip()
        if not expected:
            return jsonify({"error": "DASHBOARD_API_TOKEN nao configurado no .env"}), 503
        if get_bearer_token() != expected:
            return jsonify({"error": "nao autorizado"}), 401
        return view(*args, **kwargs)

    return wrapped


app = Flask(__name__, static_folder=str(WEB_DIR), static_url_path="")


@app.get("/api/health")
def health() -> Any:
    return jsonify({"ok": True, "database": is_database_configured()})


def _meta_json_path() -> Path:
    rel = (
        os.getenv("META_ACCOUNTS_JSON_PATH", "config/meta_ad_accounts.json").strip()
        or "config/meta_ad_accounts.json"
    )
    return REPO_ROOT / rel


def _google_json_path() -> Path:
    rel = (
        os.getenv("GOOGLE_ACCOUNTS_JSON_PATH", "config/google_ad_accounts.json").strip()
        or "config/google_ad_accounts.json"
    )
    return REPO_ROOT / rel


def _get_meta_accounts() -> Tuple[List[dict[str, Any]], str]:
    if is_database_configured():
        migrate()
        rows = list_accounts("meta", include_disabled=True)
        return (
            [
                {
                    "external_id": str(r["external_id"]),
                    "display_name": str(r.get("display_name") or ""),
                    "enabled": bool(r.get("enabled", True)),
                }
                for r in rows
            ],
            "postgres",
        )
    allowed, labels = load_accounts_from_json(str(_meta_json_path()))
    out = [
        {
            "external_id": i,
            "display_name": labels.get(i, ""),
            "enabled": True,
        }
        for i in sorted(allowed)
    ]
    return out, "json"


def _get_google_accounts() -> Tuple[List[dict[str, Any]], str]:
    if is_database_configured():
        migrate()
        rows = list_accounts("google_ads", include_disabled=True)
        return (
            [
                {
                    "external_id": str(r["external_id"]),
                    "display_name": str(r.get("display_name") or ""),
                    "enabled": bool(r.get("enabled", True)),
                }
                for r in rows
            ],
            "postgres",
        )
    path = _google_json_path()
    if not path.exists():
        return [], "json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    accounts = raw.get("accounts", [])
    out: List[dict[str, Any]] = []
    if isinstance(accounts, list):
        for item in accounts:
            if not isinstance(item, dict):
                continue
            cid = str(item.get("customer_id", "")).replace("-", "").strip()
            if not cid:
                continue
            out.append(
                {
                    "external_id": cid,
                    "display_name": str(item.get("name", "") or ""),
                    "enabled": True,
                }
            )
    return out, "json"


def _normalize_meta_rows(body: Any) -> List[Tuple[str, str, bool]]:
    if not isinstance(body, dict):
        raise ValueError("JSON deve ser um objeto.")
    accounts = body.get("accounts")
    if not isinstance(accounts, list):
        raise ValueError("Campo 'accounts' deve ser uma lista.")
    rows: List[Tuple[str, str, bool]] = []
    for item in accounts:
        if not isinstance(item, dict):
            continue
        eid = normalize_account_id(str(item.get("external_id", "")).strip())
        if not eid:
            continue
        name = str(item.get("display_name", "") or "").strip()
        enabled = bool(item.get("enabled", True))
        rows.append((eid, name, enabled))
    return rows


def _normalize_google_rows(body: Any) -> List[Tuple[str, str, bool]]:
    rows = _normalize_meta_rows(body)  # mesmo formato external_id/display_name/enabled
    fixed: List[Tuple[str, str, bool]] = []
    for eid, name, en in rows:
        digits = "".join(ch for ch in eid if ch.isdigit())[:10]
        if len(digits) != 10:
            raise ValueError(f"customer_id invalido (10 digitos): {eid}")
        fixed.append((digits, name, en))
    return fixed


@app.get("/api/accounts/meta")
@require_dashboard_token
def get_meta_accounts() -> Any:
    rows, source = _get_meta_accounts()
    return jsonify({"source": source, "accounts": rows})


@app.put("/api/accounts/meta")
@require_dashboard_token
def put_meta_accounts() -> Any:
    body = request.get_json(force=True, silent=False)
    try:
        batch = _normalize_meta_rows(body)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    if is_database_configured():
        migrate()
        replace_accounts("meta", batch)
        return jsonify({"ok": True, "saved": "postgres", "count": len(batch)})

    path = _meta_json_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "accounts": [{"id": eid, "name": name} for eid, name, en in batch if en],
    }
    path.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")
    n = len(payload["accounts"])
    return jsonify({"ok": True, "saved": "json", "path": str(path.relative_to(REPO_ROOT)), "count": n})


@app.get("/api/accounts/google")
@require_dashboard_token
def get_google_accounts() -> Any:
    rows, source = _get_google_accounts()
    return jsonify({"source": source, "accounts": rows})


@app.put("/api/accounts/google")
@require_dashboard_token
def put_google_accounts() -> Any:
    body = request.get_json(force=True, silent=False)
    try:
        batch = _normalize_google_rows(body)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    if is_database_configured():
        migrate()
        replace_accounts("google_ads", batch)
        return jsonify({"ok": True, "saved": "postgres", "count": len(batch)})

    path = _google_json_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "accounts": [
            {"customer_id": eid, "name": name} for eid, name, en in batch if en
        ],
    }
    path.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")
    n = len(payload["accounts"])
    return jsonify({"ok": True, "saved": "json", "path": str(path.relative_to(REPO_ROOT)), "count": n})


@app.get("/api/balances/meta")
@require_dashboard_token
def balances_meta() -> Any:
    try:
        access_token = env_required("META_ACCESS_TOKEN")
        business_id = env_required("META_BUSINESS_ID")
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 503

    max_retries = env_int("MAX_RETRIES", 3)
    retry_delay_seconds = env_int("RETRY_DELAY_SECONDS", 300)
    treat_as_cents = os.getenv("META_BALANCE_IS_CENTS", "true").lower() == "true"

    rows, _src = _get_meta_accounts()
    ids = [r["external_id"] for r in rows if r.get("enabled", True)]
    if not ids:
        return jsonify({"accounts": [], "message": "Nenhuma conta configurada."})

    import requests

    session = requests.Session()
    try:
        data = fetch_meta_balances_for_ids(
            session,
            business_id=business_id,
            access_token=access_token,
            account_ids=ids,
            treat_as_cents=treat_as_cents,
            max_retries=max_retries,
            retry_delay_seconds=retry_delay_seconds,
        )
    except Exception as exc:  # noqa: BLE001
        return jsonify({"error": str(exc)}), 502

    return jsonify({"accounts": data})


@app.get("/api/balances/google")
@require_dashboard_token
def balances_google() -> Any:
    try:
        from google_ads_balance import fetch_balances_for_customers
    except ImportError as exc:
        return jsonify({"error": str(exc)}), 503

    rows, _src = _get_google_accounts()
    ids = [r["external_id"] for r in rows if r.get("enabled", True)]
    if not ids:
        return jsonify({"accounts": [], "message": "Nenhuma conta configurada."})

    try:
        data = fetch_balances_for_customers(ids)
    except Exception as exc:  # noqa: BLE001
        return jsonify({"error": str(exc)}), 502

    return jsonify({"accounts": data})


@app.get("/")
def index() -> Any:
    return send_from_directory(app.static_folder or str(WEB_DIR), "index.html")


def main() -> None:
    host = os.getenv("DASHBOARD_HOST", "127.0.0.1").strip() or "127.0.0.1"
    port = env_int("DASHBOARD_PORT", 5050)
    if not os.getenv("DASHBOARD_API_TOKEN", "").strip():
        print(
            "AVISO: defina DASHBOARD_API_TOKEN no .env para proteger as rotas /api/*.",
            file=sys.stderr,
        )
    if is_database_configured():
        try:
            migrate()
        except Exception as exc:  # noqa: BLE001
            print(f"AVISO: migracao Postgres falhou: {exc}", file=sys.stderr)
    app.run(host=host, port=port, debug=False)


if __name__ == "__main__":
    main()
