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
from datetime import datetime, timedelta, timezone
from functools import wraps
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable, List, Tuple

from dotenv import load_dotenv
from flask import Flask, jsonify, request, send_from_directory
from zoneinfo import ZoneInfo

REPO_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(REPO_ROOT / ".env")

# pylint: disable=wrong-import-position
from alert_message_style import (
    DEFAULT_GOOGLE,
    DEFAULT_META,
    build_google_whatsapp_message,
    build_meta_whatsapp_message,
    get_full_style_payload,
    keys_help,
    load_merged_style,
    merge_style_with_override,
    persist_styles,
)
from dashboard_scheduler import start_dashboard_scheduler
from monitor_runner import run_google_monitor, run_meta_monitor
from monitor_schedule import (
    default_schedule,
    load_schedule,
    persist_schedule,
    sanitize_schedule,
    times_to_cron_expr,
)
from monitor_thresholds import (
    default_thresholds,
    load_threshold_pair,
    load_thresholds,
    persist_thresholds,
    sanitize_thresholds,
)
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


def _preview_now_strings() -> Tuple[str, str]:
    tz_name = os.getenv("TZ", "America/Sao_Paulo").strip() or "America/Sao_Paulo"
    try:
        now = datetime.now(ZoneInfo(tz_name))
    except Exception:
        if tz_name == "America/Sao_Paulo":
            now = datetime.now(timezone.utc) - timedelta(hours=3)
        else:
            now = datetime.now(timezone.utc)
    return now.strftime("%d/%m/%Y %H:%M"), tz_name


def _fake_meta_account() -> SimpleNamespace:
    return SimpleNamespace(
        account_id="1234567890123456",
        name="Conta Exemplo LTDA",
        currency="BRL",
        balance_brl=99.5,
        balance_source="balance",
        raw_balance=None,
    )


def _fake_google_account() -> SimpleNamespace:
    return SimpleNamespace(
        customer_id="1234567890",
        name="Cliente Demo",
        currency="BRL",
        balance=88.0,
        source="account_budget(ENABLED)",
    )


@app.get("/api/alert-style")
@require_dashboard_token
def get_alert_style() -> Any:
    payload = get_full_style_payload(REPO_ROOT)
    now_str, tz_name = _preview_now_strings()
    alert_t, near_t = load_threshold_pair(REPO_ROOT)
    style_m = load_merged_style("meta", REPO_ROOT)
    style_g = load_merged_style("google", REPO_ROOT)
    preview_meta = build_meta_whatsapp_message(
        low_balances=[_fake_meta_account()],
        alert_threshold=alert_t,
        near_threshold=near_t,
        tz_name=tz_name,
        now_str=now_str,
        style=style_m,
    )
    preview_google = build_google_whatsapp_message(
        low=[_fake_google_account()],
        alert_threshold=alert_t,
        near_threshold=near_t,
        tz_name=tz_name,
        now_str=now_str,
        style=style_g,
    )
    return jsonify(
        {
            **payload,
            "thresholds": load_thresholds(REPO_ROOT),
            "defaults": {"meta": DEFAULT_META, "google": DEFAULT_GOOGLE},
            "help": keys_help(),
            "preview_meta": preview_meta,
            "preview_google": preview_google,
        }
    )


@app.put("/api/alert-style")
@require_dashboard_token
def put_alert_style() -> Any:
    body = request.get_json(force=True, silent=False) or {}
    meta = body.get("meta") or {}
    google = body.get("google") or {}
    if not isinstance(meta, dict) or not isinstance(google, dict):
        return jsonify({"error": "meta e google devem ser objetos"}), 400
    try:
        where = persist_styles(meta, google, REPO_ROOT)
    except Exception as exc:  # noqa: BLE001
        return jsonify({"error": str(exc)}), 500
    return jsonify({"ok": True, "saved": where})


@app.get("/api/monitor/schedule")
@require_dashboard_token
def get_monitor_schedule() -> Any:
    sched = load_schedule(REPO_ROOT)
    thresholds = load_thresholds(REPO_ROOT)
    return jsonify(
        {
            **sched,
            "cron": times_to_cron_expr(sched.get("times") or []),
            "defaults": default_schedule(),
            "alert_threshold": thresholds["alert_threshold"],
            "near_threshold": thresholds["near_threshold"],
        }
    )


@app.put("/api/monitor/schedule")
@require_dashboard_token
def put_monitor_schedule() -> Any:
    body = request.get_json(force=True, silent=False) or {}
    try:
        clean = sanitize_schedule(body)
        where = persist_schedule(clean, REPO_ROOT)
    except Exception as exc:  # noqa: BLE001
        return jsonify({"error": str(exc)}), 500
    return jsonify(
        {
            "ok": True,
            "saved": where,
            "schedule": clean,
            "cron": times_to_cron_expr(clean["times"]),
            "note": (
                "No Docker, reinicie o container para o supercronic usar o novo CRON. "
                "Com a dashboard ativa, o agendador interno aplica os horarios sem reiniciar."
            ),
        }
    )


@app.get("/api/monitor/thresholds")
@require_dashboard_token
def get_monitor_thresholds() -> Any:
    cfg = load_thresholds(REPO_ROOT)
    return jsonify({**cfg, "defaults": default_thresholds()})


@app.put("/api/monitor/thresholds")
@require_dashboard_token
def put_monitor_thresholds() -> Any:
    body = request.get_json(force=True, silent=False) or {}
    try:
        clean = sanitize_thresholds(body)
        where = persist_thresholds(clean, REPO_ROOT)
    except Exception as exc:  # noqa: BLE001
        return jsonify({"error": str(exc)}), 500
    return jsonify(
        {
            "ok": True,
            "saved": where,
            "thresholds": clean,
            "note": (
                "Limites aplicados no CRON, envio manual e mensagens. "
                "Valores do .env sao sobrescritos apos salvar no painel."
            ),
        }
    )


@app.post("/api/monitor/run")
@require_dashboard_token
def post_monitor_run() -> Any:
    body = request.get_json(force=True, silent=False) or {}
    platform = str(body.get("platform") or "both").strip().lower()
    force = bool(body.get("force", False))
    dry_run = bool(body.get("dry_run", False))

    if platform not in ("meta", "google", "both"):
        return jsonify({"error": "platform deve ser meta, google ou both"}), 400

    out: dict[str, Any] = {"ok": True, "force": force, "dry_run": dry_run}
    if platform in ("meta", "both"):
        out["meta"] = run_meta_monitor(force_send=force, dry_run=dry_run).to_dict()
    if platform in ("google", "both"):
        out["google"] = run_google_monitor(force_send=force, dry_run=dry_run).to_dict()
    return jsonify(out)


@app.post("/api/alert-style/preview")
@require_dashboard_token
def post_alert_style_preview() -> Any:
    body = request.get_json(force=True, silent=False) or {}
    meta_ov = body.get("meta") if isinstance(body.get("meta"), dict) else None
    google_ov = body.get("google") if isinstance(body.get("google"), dict) else None
    now_str, tz_name = _preview_now_strings()
    alert_t, near_t = load_threshold_pair(REPO_ROOT)
    style_m = merge_style_with_override("meta", meta_ov, REPO_ROOT)
    style_g = merge_style_with_override("google", google_ov, REPO_ROOT)
    preview_meta = build_meta_whatsapp_message(
        low_balances=[_fake_meta_account()],
        alert_threshold=alert_t,
        near_threshold=near_t,
        tz_name=tz_name,
        now_str=now_str,
        style=style_m,
    )
    preview_google = build_google_whatsapp_message(
        low=[_fake_google_account()],
        alert_threshold=alert_t,
        near_threshold=near_t,
        tz_name=tz_name,
        now_str=now_str,
        style=style_g,
    )
    return jsonify(
        {
            "preview_meta": preview_meta,
            "preview_google": preview_google,
            "thresholds": {"alert_threshold": alert_t, "near_threshold": near_t},
        }
    )


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
    try:
        sched = load_schedule(REPO_ROOT)
        cron = times_to_cron_expr(sched.get("times") or [])
        print(f"Agendamento: {sched.get('times')} ({sched.get('timezone')}) -> cron {cron}")
    except Exception as exc:  # noqa: BLE001
        print(f"AVISO: schedule: {exc}", file=sys.stderr)
    start_dashboard_scheduler()
    app.run(host=host, port=port, debug=False)


if __name__ == "__main__":
    main()
