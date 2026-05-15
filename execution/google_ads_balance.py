"""Consulta de saldo / orcamento na API Google Ads (melhor esforco por tipo de conta)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    ZoneInfo = None  # type: ignore[misc, assignment]


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


def _enum_name(value: Any) -> str:
    if value is None:
        return ""
    if hasattr(value, "name"):
        return str(value.name)
    return str(value)


def _parse_ads_datetime(raw: str) -> Optional[datetime]:
    text = (raw or "").strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def _now_utc() -> datetime:
    tz_name = os.getenv("TZ", "America/Sao_Paulo").strip() or "America/Sao_Paulo"
    if ZoneInfo is not None:
        try:
            return datetime.now(ZoneInfo(tz_name)).astimezone(timezone.utc)
        except Exception:  # noqa: BLE001
            pass
    return datetime.now(timezone.utc)


def _budget_is_active(row: Any, now: datetime) -> bool:
    status = _enum_name(row.account_budget.status)
    if status in {"REMOVED", "CANCELLED"}:
        return False
    end_type = _enum_name(getattr(row.account_budget, "approved_end_time_type", None))
    if end_type == "FOREVER":
        return True
    end_raw = getattr(row.account_budget, "approved_end_date_time", None) or ""
    end_dt = _parse_ads_datetime(str(end_raw))
    if end_dt is None:
        return status in {"APPROVED", "ENABLED"}
    return end_dt >= now


def _remaining_from_budget_row(row: Any) -> Optional[Tuple[float, str, int]]:
    """Retorna (restante em moeda, status, id) ou None se orcamento nao for finito."""
    status = _enum_name(row.account_budget.status)
    limit_type = _enum_name(row.account_budget.adjusted_spending_limit_type)
    if limit_type == "INFINITE":
        return None

    adjusted = _micros_to_float(row.account_budget.adjusted_spending_limit_micros)
    if adjusted is None:
        approved = _micros_to_float(row.account_budget.approved_spending_limit_micros)
        adjusted = approved
    if adjusted is None:
        return None

    served = _micros_to_float(row.account_budget.amount_served_micros) or 0.0
    remaining = adjusted - served
    budget_id = int(getattr(row.account_budget, "id", 0) or 0)
    return remaining, status, budget_id


def _pick_best_budget(candidates: List[Tuple[float, str, int]]) -> Optional[Tuple[float, str, int]]:
    """
    Escolhe o orcamento com maior saldo restante positivo (mais proximo do 'Saldo' da UI).
    Ignora orcamentos esgotados/negativos de periodos antigos.
    """
    if not candidates:
        return None
    positives = [c for c in candidates if c[0] >= 0]
    if positives:
        return max(positives, key=lambda item: item[0])
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
          account_budget.id,
          account_budget.status,
          account_budget.adjusted_spending_limit_micros,
          account_budget.adjusted_spending_limit_type,
          account_budget.approved_spending_limit_micros,
          account_budget.amount_served_micros,
          account_budget.approved_end_time_type,
          account_budget.approved_end_date_time
        FROM account_budget
    """

    now = _now_utc()
    candidates: List[Tuple[float, str, int]] = []
    had_negative_only = False

    try:
        for row in _iter_gaql_rows(ga_service, client, cid, q_budget):
            if not _budget_is_active(row, now):
                continue
            parsed = _remaining_from_budget_row(row)
            if parsed is None:
                continue
            remaining, status, budget_id = parsed
            if remaining < 0:
                had_negative_only = True
                continue
            candidates.append((remaining, status, budget_id))
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

    best = _pick_best_budget(candidates)
    if best is None:
        if had_negative_only:
            return GoogleAdsBalanceRow(
                customer_id=cid,
                name=name,
                currency=currency,
                balance=None,
                status="indisponivel",
                message=(
                    "Orcamentos API esgotados ou negativos; o saldo prepaid da interface "
                    "(ex.: R$ 329) nao e exposto pela API Google Ads neste tipo de conta. "
                    "Valide manualmente em Faturamento ou use faturamento mensal."
                ),
                source="account_budget",
            )
        return GoogleAdsBalanceRow(
            customer_id=cid,
            name=name,
            currency=currency,
            balance=None,
            status="indisponivel",
            message="Sem orcamento account_budget utilizavel (conta pode ser faturamento automatico).",
            source="",
        )

    remaining, status, budget_id = best
    return GoogleAdsBalanceRow(
        customer_id=cid,
        name=name,
        currency=currency,
        balance=float(remaining),
        status="ok",
        message="",
        source=f"account_budget({status},id={budget_id},adjusted-served)",
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
