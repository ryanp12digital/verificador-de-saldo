"""Consulta e normalizacao de saldos Meta Ads (Graph API)."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

from http_util import request_with_retry

GRAPH_API_VERSION = "v20.0"
GRAPH_BASE_URL = f"https://graph.facebook.com/{GRAPH_API_VERSION}"


@dataclass
class AdAccountBalance:
    account_id: str
    name: str
    currency: str
    balance_brl: float
    raw_balance: Any
    balance_source: str


def normalize_account_id(value: str) -> str:
    normalized = str(value or "").strip()
    if normalized.startswith("act_"):
        normalized = normalized[4:]
    return normalized


def parse_allowed_account_ids(raw_value: str) -> set[str]:
    if not raw_value.strip():
        return set()
    values = [normalize_account_id(item) for item in raw_value.split(",")]
    return {item for item in values if item}


def parse_account_labels(raw_value: str) -> Dict[str, str]:
    labels: Dict[str, str] = {}
    if not raw_value.strip():
        return labels

    for part in raw_value.split(";"):
        entry = part.strip()
        if not entry or "=" not in entry:
            continue
        raw_id, raw_name = entry.split("=", 1)
        account_id = normalize_account_id(raw_id)
        label = raw_name.strip()
        if account_id and label:
            labels[account_id] = label
    return labels


def load_accounts_from_json(config_path: str) -> tuple[set[str], Dict[str, str]]:
    path = Path(config_path)
    if not path.exists():
        return set(), {}

    raw = json.loads(path.read_text(encoding="utf-8"))
    accounts = raw.get("accounts", [])
    if not isinstance(accounts, list):
        raise ValueError("Campo 'accounts' do JSON deve ser uma lista.")

    allowed_ids: set[str] = set()
    labels: Dict[str, str] = {}
    for item in accounts:
        if not isinstance(item, dict):
            continue
        account_id = normalize_account_id(str(item.get("id", "")).strip())
        account_name = str(item.get("name", "")).strip()
        if not account_id:
            continue
        allowed_ids.add(account_id)
        if account_name:
            labels[account_id] = account_name

    return allowed_ids, labels


def parse_balance_to_brl(raw_balance: Any, treat_as_cents: bool) -> float:
    if raw_balance is None:
        raise ValueError("Campo balance veio nulo.")
    try:
        value = float(raw_balance)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Valor de balance invalido: {raw_balance}") from exc

    if treat_as_cents:
        return value / 100.0
    return value


def parse_brl_number(value: str) -> float:
    cleaned = value.strip()
    cleaned = cleaned.replace(".", "").replace(",", ".")
    return float(cleaned)


def parse_available_balance_from_display_string(display_text: str) -> Optional[float]:
    if not display_text:
        return None

    match = re.search(r"R\$\s*([0-9\.,]+)", display_text)
    if not match:
        return None

    try:
        return parse_brl_number(match.group(1))
    except ValueError:
        return None


def extract_account_balance(account: Dict[str, Any], treat_as_cents: bool) -> tuple[float, str]:
    funding_source_details = account.get("funding_source_details") or {}
    display_string = str(funding_source_details.get("display_string") or "")
    parsed_display_balance = parse_available_balance_from_display_string(display_string)
    if parsed_display_balance is not None:
        return parsed_display_balance, "funding_source_details.display_string"

    raw_balance = account.get("balance")
    if raw_balance is not None:
        return parse_balance_to_brl(raw_balance, treat_as_cents=treat_as_cents), "balance"

    spend_cap = account.get("spend_cap")
    amount_spent = account.get("amount_spent")
    if spend_cap is not None and amount_spent is not None:
        try:
            remaining = (float(spend_cap) - float(amount_spent)) / 100.0
            return remaining, "spend_cap-amount_spent"
        except ValueError:
            pass

    raise ValueError("Nenhum campo de saldo valido encontrado.")


def fetch_accounts(
    session: requests.Session,
    business_id: str,
    access_token: str,
    max_retries: int,
    retry_delay_seconds: int,
) -> List[Dict[str, Any]]:
    fields = (
        "id,account_id,name,currency,balance,account_status,"
        "funding_source_details,is_prepay_account,amount_spent,spend_cap"
    )
    endpoints = [
        f"{GRAPH_BASE_URL}/{business_id}/owned_ad_accounts",
        f"{GRAPH_BASE_URL}/{business_id}/client_ad_accounts",
    ]
    all_accounts: Dict[str, Dict[str, Any]] = {}

    for endpoint in endpoints:
        params: Optional[Dict[str, Any]] = {
            "access_token": access_token,
            "fields": fields,
            "limit": 200,
        }
        next_url: Optional[str] = endpoint

        while next_url:
            response = request_with_retry(
                session,
                "GET",
                next_url,
                params=params,
                max_retries=max_retries,
                retry_delay_seconds=retry_delay_seconds,
            )
            payload = response.json()
            if "error" in payload:
                raise RuntimeError(f"Erro Meta API: {json.dumps(payload['error'])}")

            for item in payload.get("data", []):
                key = str(item.get("id") or item.get("account_id"))
                if key:
                    all_accounts[key] = item

            paging = payload.get("paging", {})
            next_url = paging.get("next")
            params = None

    return list(all_accounts.values())


def normalize_accounts(accounts: List[Dict[str, Any]], treat_as_cents: bool) -> List[AdAccountBalance]:
    normalized: List[AdAccountBalance] = []
    for account in accounts:
        try:
            balance_brl, source = extract_account_balance(account, treat_as_cents=treat_as_cents)
        except ValueError:
            continue

        account_id = str(account.get("account_id") or account.get("id") or "desconhecida")
        normalized.append(
            AdAccountBalance(
                account_id=account_id,
                name=str(account.get("name") or "Conta sem nome"),
                currency=str(account.get("currency") or "BRL"),
                balance_brl=balance_brl,
                raw_balance=account.get("balance"),
                balance_source=source,
            )
        )
    return normalized


def fetch_meta_balances_for_ids(
    session: requests.Session,
    *,
    business_id: str,
    access_token: str,
    account_ids: List[str],
    treat_as_cents: bool,
    max_retries: int,
    retry_delay_seconds: int,
) -> List[Dict[str, Any]]:
    """Retorna uma linha por id solicitado (erro por conta nao bloqueia as demais)."""
    want = {normalize_account_id(x) for x in account_ids if normalize_account_id(x)}
    if not want:
        return []

    all_raw = fetch_accounts(
        session,
        business_id=business_id,
        access_token=access_token,
        max_retries=max_retries,
        retry_delay_seconds=retry_delay_seconds,
    )
    by_id: Dict[str, Dict[str, Any]] = {}
    for acc in all_raw:
        aid = normalize_account_id(str(acc.get("account_id") or acc.get("id") or ""))
        if aid:
            by_id[aid] = acc

    rows: List[Dict[str, Any]] = []
    for raw_id in sorted(want):
        acc = by_id.get(raw_id)
        if not acc:
            rows.append(
                {
                    "account_id": raw_id,
                    "status": "erro",
                    "message": "Conta nao encontrada na Business (owned/client).",
                }
            )
            continue
        try:
            bal, source = extract_account_balance(acc, treat_as_cents=treat_as_cents)
        except ValueError as exc:
            rows.append(
                {
                    "account_id": raw_id,
                    "status": "erro",
                    "message": str(exc),
                }
            )
            continue
        rows.append(
            {
                "account_id": raw_id,
                "name": str(acc.get("name") or ""),
                "currency": str(acc.get("currency") or "BRL"),
                "balance": bal,
                "balance_source": source,
                "status": "ok",
            }
        )
    return rows
