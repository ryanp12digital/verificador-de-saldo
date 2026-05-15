"""Execucao do monitor Meta/Google para API e scheduler (retorno estruturado)."""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional

import requests
from dotenv import load_dotenv

from accounts_config import load_google_accounts_for_monitor, load_meta_allowlist_for_monitor
from alert_message_style import (
    build_google_whatsapp_message,
    build_meta_whatsapp_message,
    load_merged_style,
)
from evolution_notify import send_group_message
from google_ads_balance import fetch_balance_for_customer
from meta_ads_balance import (
    fetch_accounts,
    normalize_account_id,
    normalize_accounts,
)


@dataclass
class MonitorRunResult:
    platform: str
    exit_code: int
    sent: bool
    forced: bool
    message: str
    summary: Dict[str, Any]
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _env_required(name: str) -> str:
    value = os.getenv(name)
    if value is None or not value.strip():
        raise ValueError(f"Variavel obrigatoria ausente no .env: {name}")
    return value.strip()


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name, str(default)).strip()
    return int(raw)


def _thresholds() -> tuple[float, float]:
    alert = float(os.getenv("ALERT_THRESHOLD", "200").strip() or "200")
    near = float(os.getenv("NEAR_THRESHOLD", "120").strip() or "120")
    return alert, near


def run_meta_monitor(
    *,
    force_send: bool = False,
    dry_run: bool = False,
    alert_threshold: Optional[float] = None,
    near_threshold: Optional[float] = None,
) -> MonitorRunResult:
    load_dotenv()
    alert_t, near_t = _thresholds()
    if alert_threshold is not None:
        alert_t = alert_threshold
    if near_threshold is not None:
        near_t = near_threshold

    summary: Dict[str, Any] = {
        "limite_alerta": alert_t,
        "limite_proximo": near_t,
        "force_send": force_send,
    }

    try:
        access_token = _env_required("META_ACCESS_TOKEN")
        business_id = _env_required("META_BUSINESS_ID")
        evolution_base_url = _env_required("EVOLUTION_SERVER_URL")
        evolution_api_key = _env_required("EVOLUTION_API_KEY")
        evolution_instance = _env_required("EVOLUTION_INSTANCE")
        evolution_group_id = _env_required("EVOLUTION_GROUP_ID")
        max_retries = _env_int("MAX_RETRIES", 3)
        retry_delay_seconds = _env_int("RETRY_DELAY_SECONDS", 300)
        treat_as_cents = os.getenv("META_BALANCE_IS_CENTS", "true").lower() == "true"
        tz_name = os.getenv("TZ", "America/Sao_Paulo").strip() or "America/Sao_Paulo"
        json_accounts_path = (
            os.getenv("META_ACCOUNTS_JSON_PATH", "config/meta_ad_accounts.json").strip()
            or "config/meta_ad_accounts.json"
        )
    except ValueError as exc:
        return MonitorRunResult(
            platform="meta",
            exit_code=2,
            sent=False,
            forced=force_send,
            message="",
            summary=summary,
            error=str(exc),
        )

    try:
        allowed_account_ids, account_labels, source_accounts, strict_whitelist = (
            load_meta_allowlist_for_monitor(json_accounts_path)
        )
    except Exception as exc:  # noqa: BLE001
        return MonitorRunResult(
            platform="meta",
            exit_code=2,
            sent=False,
            forced=force_send,
            message="",
            summary=summary,
            error=str(exc),
        )

    summary["fonte_contas"] = source_accounts

    if strict_whitelist and not allowed_account_ids:
        return MonitorRunResult(
            platform="meta",
            exit_code=0,
            sent=False,
            forced=force_send,
            message="",
            summary={**summary, "motivo": "nenhuma_conta_habilitada"},
        )

    session = requests.Session()
    try:
        accounts_raw = fetch_accounts(
            session,
            business_id=business_id,
            access_token=access_token,
            max_retries=max_retries,
            retry_delay_seconds=retry_delay_seconds,
        )
        accounts = normalize_accounts(accounts_raw, treat_as_cents=treat_as_cents)
    except Exception as exc:  # noqa: BLE001
        return MonitorRunResult(
            platform="meta",
            exit_code=1,
            sent=False,
            forced=force_send,
            message="",
            summary=summary,
            error=str(exc),
        )

    if allowed_account_ids:
        accounts = [
            item
            for item in accounts
            if normalize_account_id(item.account_id) in allowed_account_ids
        ]

    if account_labels:
        for account in accounts:
            label = account_labels.get(normalize_account_id(account.account_id))
            if label:
                account.name = label

    low_balances = [a for a in accounts if a.balance_brl <= alert_t]
    to_message = accounts if force_send else low_balances

    summary.update(
        {
            "total_contas": len(accounts),
            "contas_abaixo_limite": len(low_balances),
            "contas_na_mensagem": len(to_message),
        }
    )

    if not to_message:
        reason = (
            "nenhuma_conta_configurada"
            if not accounts
            else "nenhuma_conta_abaixo_limite"
        )
        return MonitorRunResult(
            platform="meta",
            exit_code=0,
            sent=False,
            forced=force_send,
            message="",
            summary={**summary, "motivo": reason},
        )

    from monitorar_saldo_meta_ads import get_now_in_timezone

    now_str = get_now_in_timezone(tz_name).strftime("%d/%m/%Y %H:%M")
    style = load_merged_style("meta")
    message = build_meta_whatsapp_message(
        low_balances=to_message,
        alert_threshold=alert_t,
        near_threshold=near_t,
        tz_name=tz_name,
        now_str=now_str,
        style=style,
    )

    if force_send:
        message = "📣 *Envio manual / forcado*\n\n" + message

    if dry_run:
        return MonitorRunResult(
            platform="meta",
            exit_code=0,
            sent=False,
            forced=force_send,
            message=message,
            summary={**summary, "dry_run": True},
        )

    try:
        send_group_message(
            session,
            base_url=evolution_base_url,
            api_key=evolution_api_key,
            instance=evolution_instance,
            group_id=evolution_group_id,
            message=message,
            max_retries=max_retries,
            retry_delay_seconds=retry_delay_seconds,
        )
    except Exception as exc:  # noqa: BLE001
        return MonitorRunResult(
            platform="meta",
            exit_code=1,
            sent=False,
            forced=force_send,
            message=message,
            summary=summary,
            error=str(exc),
        )

    return MonitorRunResult(
        platform="meta",
        exit_code=0,
        sent=True,
        forced=force_send,
        message=message,
        summary=summary,
    )


def run_google_monitor(
    *,
    force_send: bool = False,
    dry_run: bool = False,
    alert_threshold: Optional[float] = None,
    near_threshold: Optional[float] = None,
) -> MonitorRunResult:
    load_dotenv()
    alert_t, near_t = _thresholds()
    if alert_threshold is not None:
        alert_t = alert_threshold
    if near_threshold is not None:
        near_t = near_threshold

    summary: Dict[str, Any] = {
        "limite_alerta": alert_t,
        "limite_proximo": near_t,
        "force_send": force_send,
    }

    try:
        evolution_base_url = _env_required("EVOLUTION_SERVER_URL")
        evolution_api_key = _env_required("EVOLUTION_API_KEY")
        evolution_instance = _env_required("EVOLUTION_INSTANCE")
        evolution_group_id = _env_required("EVOLUTION_GROUP_ID")
        max_retries = _env_int("MAX_RETRIES", 3)
        retry_delay_seconds = _env_int("RETRY_DELAY_SECONDS", 300)
        tz_name = os.getenv("TZ", "America/Sao_Paulo").strip() or "America/Sao_Paulo"
        json_path = (
            os.getenv("GOOGLE_ACCOUNTS_JSON_PATH", "config/google_ad_accounts.json").strip()
            or "config/google_ad_accounts.json"
        )
    except ValueError as exc:
        return MonitorRunResult(
            platform="google",
            exit_code=2,
            sent=False,
            forced=force_send,
            message="",
            summary=summary,
            error=str(exc),
        )

    try:
        accounts_cfg, source_accounts, strict_whitelist = load_google_accounts_for_monitor(
            json_path
        )
    except Exception as exc:  # noqa: BLE001
        return MonitorRunResult(
            platform="google",
            exit_code=2,
            sent=False,
            forced=force_send,
            message="",
            summary=summary,
            error=str(exc),
        )

    summary["fonte_contas"] = source_accounts

    if strict_whitelist and not accounts_cfg:
        return MonitorRunResult(
            platform="google",
            exit_code=0,
            sent=False,
            forced=force_send,
            message="",
            summary={**summary, "motivo": "nenhuma_conta_habilitada"},
        )

    if not accounts_cfg:
        return MonitorRunResult(
            platform="google",
            exit_code=0,
            sent=False,
            forced=force_send,
            message="",
            summary={**summary, "motivo": "nenhuma_conta_configurada"},
        )

    try:
        from google_ads_balance import build_client_config

        build_client_config()
    except ValueError as exc:
        return MonitorRunResult(
            platform="google",
            exit_code=2,
            sent=False,
            forced=force_send,
            message="",
            summary=summary,
            error=str(exc),
        )

    from monitorar_saldo_google_ads import LowGoogleAccount, get_now_in_timezone

    low: List[LowGoogleAccount] = []
    all_ok: List[LowGoogleAccount] = []
    errors = 0

    for entry in accounts_cfg:
        cid = entry["customer_id"]
        label = entry.get("name") or cid
        row = fetch_balance_for_customer(cid)
        if row.status == "erro":
            errors += 1
            continue
        if row.status == "indisponivel" or row.balance is None:
            continue
        item = LowGoogleAccount(
            customer_id=cid,
            name=row.name or label,
            currency=row.currency or "?",
            balance=row.balance,
            source=row.source,
        )
        all_ok.append(item)
        if row.balance <= alert_t:
            low.append(item)

    summary.update(
        {
            "contas_configuradas": len(accounts_cfg),
            "contas_com_saldo": len(all_ok),
            "contas_abaixo_limite": len(low),
            "erros_consulta": errors,
        }
    )

    to_message = all_ok if force_send else low
    summary["contas_na_mensagem"] = len(to_message)

    if not to_message:
        reason = "nenhuma_conta_abaixo_limite" if not force_send else "nenhum_saldo_disponivel"
        return MonitorRunResult(
            platform="google",
            exit_code=0,
            sent=False,
            forced=force_send,
            message="",
            summary={**summary, "motivo": reason},
        )

    now_str = get_now_in_timezone(tz_name).strftime("%d/%m/%Y %H:%M")
    style = load_merged_style("google")
    message = build_google_whatsapp_message(
        low=to_message,
        alert_threshold=alert_t,
        near_threshold=near_t,
        tz_name=tz_name,
        now_str=now_str,
        style=style,
    )

    if force_send:
        message = "📣 *Envio manual / forcado*\n\n" + message

    if dry_run:
        return MonitorRunResult(
            platform="google",
            exit_code=0,
            sent=False,
            forced=force_send,
            message=message,
            summary={**summary, "dry_run": True},
        )

    session = requests.Session()
    try:
        send_group_message(
            session,
            base_url=evolution_base_url,
            api_key=evolution_api_key,
            instance=evolution_instance,
            group_id=evolution_group_id,
            message=message,
            max_retries=max_retries,
            retry_delay_seconds=retry_delay_seconds,
        )
    except Exception as exc:  # noqa: BLE001
        return MonitorRunResult(
            platform="google",
            exit_code=1,
            sent=False,
            forced=force_send,
            message=message,
            summary=summary,
            error=str(exc),
        )

    return MonitorRunResult(
        platform="google",
        exit_code=0,
        sent=True,
        forced=force_send,
        message=message,
        summary=summary,
    )
