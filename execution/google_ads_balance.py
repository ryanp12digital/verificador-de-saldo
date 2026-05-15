"""Consulta de saldo / orcamento na API Google Ads (melhor esforco por tipo de conta)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional


def normalize_customer_id(value: str) -> str:
    digits = "".join(ch for ch in str(value or "") if ch.isdigit())
    return digits[:10]


def _env_required(name: str) -> str:
    raw = os.getenv(name)
    if raw is None or not str(raw).strip():
        raise ValueError(f"Variavel obrigatoria ausente no .env: {name}")
    return str(raw).strip()


def build_client_config() -> Dict[str, Any]:
    login = os.getenv("GOOGLE_ADS_LOGIN_CUSTOMER_ID", "").strip()
    if not login:
        login = os.getenv("GOOGLE_ADS_MCC_ID", "").strip()
    cfg: Dict[str, Any] = {
        "developer_token": _env_required("GOOGLE_ADS_DEVELOPER_TOKEN"),
        "client_id": _env_required("GOOGLE_ADS_CLIENT_ID"),
        "client_secret": _env_required("GOOGLE_ADS_CLIENT_SECRET"),
        "refresh_token": _env_required("GOOGLE_ADS_REFRESH_TOKEN"),
        "use_proto_plus": True,
    }
    if login:
        cfg["login_customer_id"] = normalize_customer_id(login)
    return cfg


def get_google_ads_client():  # type: ignore[no-untyped-def]
    from google.ads.googleads.client import GoogleAdsClient

    return GoogleAdsClient.load_from_dict(build_client_config())


@dataclass
class GoogleAdsBalanceRow:
    customer_id: str
    name: str
    currency: str
    balance: Optional[float]
    status: str
    message: str
    source: str


def _micros_to_float(micros: Optional[int]) -> Optional[float]:
    if micros is None:
        return None
    try:
        return float(micros) / 1_000_000.0
    except (TypeError, ValueError):
        return None


def _iter_gaql_rows(ga_service: Any, client: Any, customer_id: str, query: str) -> list[Any]:
    """Materializa linhas GAQL (search_stream preferencial, fallback search)."""
    rows: list[Any] = []
    stream_fn = getattr(ga_service, "search_stream", None)
    if callable(stream_fn):
        try:
            stream = stream_fn(customer_id=customer_id, query=query)
        except TypeError:
            req = client.get_type("SearchGoogleAdsStreamRequest")
            req.customer_id = customer_id
            req.query = query
            stream = stream_fn(request=req)
        for batch in stream:
            for row in batch.results:
                rows.append(row)
        return rows

    search_fn = getattr(ga_service, "search", None)
    if not callable(search_fn):
        raise RuntimeError("GoogleAdsService sem search_stream nem search.")
    for row in search_fn(customer_id=customer_id, query=query):
        rows.append(row)
    return rows


def fetch_balance_for_customer(customer_id: str) -> GoogleAdsBalanceRow:
    cid = normalize_customer_id(customer_id)
    if len(cid) != 10:
        return GoogleAdsBalanceRow(
            customer_id=cid,
            name="",
            currency="",
            balance=None,
            status="erro",
            message="customer_id deve ter 10 digitos.",
            source="",
        )

    try:
        client = get_google_ads_client()
    except Exception as exc:  # noqa: BLE001
        return GoogleAdsBalanceRow(
            customer_id=cid,
            name="",
            currency="",
            balance=None,
            status="erro",
            message=str(exc),
            source="",
        )

    ga_service = client.get_service("GoogleAdsService")

    name = ""
    currency = ""

    try:
        q_customer = """
            SELECT customer.descriptive_name, customer.currency_code
            FROM customer
            LIMIT 1
        """
        for row in _iter_gaql_rows(ga_service, client, cid, q_customer):
            name = str(row.customer.descriptive_name or "")
            currency = str(row.customer.currency_code or "")
            break
    except Exception as exc:  # noqa: BLE001
        return GoogleAdsBalanceRow(
            customer_id=cid,
            name=name,
            currency=currency,
            balance=None,
            status="erro",
            message=f"Falha ao ler customer: {exc}",
            source="customer",
        )

    q_budget = """
        SELECT
          account_budget.status,
          account_budget.approved_spending_limit_micros,
          account_budget.amount_served_micros
        FROM account_budget
    """

    best_remaining: Optional[float] = None
    source = ""

    try:
        for row in _iter_gaql_rows(ga_service, client, cid, q_budget):
            status_enum = row.account_budget.status
            status = status_enum.name if hasattr(status_enum, "name") else str(status_enum)
            if status == "REMOVED":
                continue
            approved = row.account_budget.approved_spending_limit_micros
            served = row.account_budget.amount_served_micros
            if approved is None or served is None:
                continue
            ap = _micros_to_float(approved) if approved is not None else None
            sv = _micros_to_float(served) if served is not None else None
            if ap is not None and sv is not None:
                remaining = ap - sv
                if best_remaining is None or remaining < best_remaining:
                    best_remaining = remaining
                    source = f"account_budget({status})"
    except Exception as exc:  # noqa: BLE001
        return GoogleAdsBalanceRow(
            customer_id=cid,
            name=name,
            currency=currency,
            balance=None,
            status="erro",
            message=f"Falha ao ler account_budget: {exc}",
            source="account_budget",
        )

    if best_remaining is None:
        return GoogleAdsBalanceRow(
            customer_id=cid,
            name=name,
            currency=currency,
            balance=None,
            status="indisponivel",
            message="Sem orcamento account_budget utilizavel (conta pode ser faturamento automatico).",
            source="",
        )

    return GoogleAdsBalanceRow(
        customer_id=cid,
        name=name,
        currency=currency,
        balance=float(best_remaining),
        status="ok",
        message="",
        source=source,
    )


def fetch_balances_for_customers(customer_ids: List[str]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for raw in customer_ids:
        row = fetch_balance_for_customer(raw)
        item: Dict[str, Any] = {
            "customer_id": row.customer_id,
            "name": row.name,
            "currency": row.currency,
            "status": row.status,
            "message": row.message,
            "balance_source": row.source,
        }
        if row.balance is not None:
            item["balance"] = row.balance
        rows.append(item)
    return rows
