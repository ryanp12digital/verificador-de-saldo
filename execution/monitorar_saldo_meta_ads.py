import argparse
import json
import os
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

import requests
from dotenv import load_dotenv

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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Monitora saldo de contas de anuncio do Meta Ads e envia alerta "
            "para grupo no Evolution quando necessario."
        )
    )
    parser.add_argument(
        "--alert-threshold",
        type=float,
        default=200.0,
        help="Dispara alerta quando saldo for menor ou igual a esse valor.",
    )
    parser.add_argument(
        "--near-threshold",
        type=float,
        default=120.0,
        help="Faixa para marcar saldo como proximo de R$100.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Nao envia mensagem no grupo. Apenas imprime a mensagem gerada.",
    )
    return parser.parse_args()


def env_required(name: str) -> str:
    value = os.getenv(name)
    if value is None or not value.strip():
        raise ValueError(f"Variavel obrigatoria ausente no .env: {name}")
    return value.strip()


def env_int(name: str, default: int) -> int:
    raw = os.getenv(name, str(default)).strip()
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"Variavel {name} deve ser inteira. Valor atual: {raw}") from exc


def get_now_in_timezone(tz_name: str) -> datetime:
    try:
        return datetime.now(ZoneInfo(tz_name))
    except Exception:  # noqa: BLE001
        if tz_name == "America/Sao_Paulo":
            return datetime.now(timezone.utc) - timedelta(hours=3)
        return datetime.now()


def safe_print(text: str) -> None:
    try:
        print(text)
    except UnicodeEncodeError:
        sys.stdout.buffer.write(text.encode("utf-8", errors="replace") + b"\n")


def log_info(message: str) -> None:
    safe_print(f"ℹ️  {message}")


def log_success(message: str) -> None:
    safe_print(f"✅ {message}")


def log_warn(message: str) -> None:
    safe_print(f"⚠️  {message}")


def log_error(message: str) -> None:
    safe_print(f"❌ {message}")


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

    # Formato: "133=Cliente A;535=Cliente B"
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


def request_with_retry(
    session: requests.Session,
    method: str,
    url: str,
    *,
    max_retries: int,
    retry_delay_seconds: int,
    **kwargs: Any,
) -> requests.Response:
    last_error: Optional[Exception] = None
    for attempt in range(1, max_retries + 1):
        try:
            response = session.request(method, url, timeout=30, **kwargs)
            if response.ok:
                return response
            last_error = RuntimeError(
                f"HTTP {response.status_code} em {url}: {response.text}"
            )
        except requests.RequestException as exc:
            last_error = exc

        if attempt < max_retries:
            time.sleep(retry_delay_seconds)

    if last_error:
        raise RuntimeError(f"Falha apos {max_retries} tentativas: {last_error}")
    raise RuntimeError("Falha desconhecida ao executar requisicao HTTP.")


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

    # Exemplo: "Saldo disponível (R$220,39 BRL)"
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


def build_alert_message(
    low_balances: List[AdAccountBalance],
    *,
    alert_threshold: float,
    near_threshold: float,
    tz_name: str,
) -> str:
    now = get_now_in_timezone(tz_name).strftime("%d/%m/%Y %H:%M")
    lines = [
        "🚨 *Alerta de Saldo - Meta Ads*",
        f"🕒 Referencia: {now} ({tz_name})",
        f"🎯 Criterio: saldo <= R${alert_threshold:.2f}",
        "",
    ]

    for account in sorted(low_balances, key=lambda item: item.balance_brl):
        if account.balance_brl <= 100:
            level = "🔴 CRITICO"
        elif account.balance_brl <= near_threshold:
            level = "🟠 ATENCAO (proximo de R$100)"
        else:
            level = "🟡 ALERTA"

        lines.append(
            f"- {level} | {account.name} "
            f"- Saldo: R${account.balance_brl:.2f} {account.currency}"
        )

    lines.append("")
    lines.append("✅ Acao recomendada: avaliar recarga das contas listadas.")
    lines.append("🔗 Pagamento Meta: https://business.facebook.com/billing_hub/accounts/details/")
    return "\n".join(lines)


def send_group_message(
    session: requests.Session,
    *,
    base_url: str,
    api_key: str,
    instance: str,
    group_id: str,
    message: str,
    max_retries: int,
    retry_delay_seconds: int,
) -> None:
    base_url = base_url.rstrip("/")
    endpoint = f"{base_url}/message/sendText/{instance}"

    headers_candidates = [
        {"apikey": api_key, "Content-Type": "application/json"},
        {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
    ]
    body_candidates = [
        {"number": group_id, "text": message},
        {"number": group_id, "textMessage": {"text": message}},
        {"jid": group_id, "text": message},
    ]

    last_error: Optional[Exception] = None
    for headers in headers_candidates:
        for body in body_candidates:
            try:
                response = request_with_retry(
                    session,
                    "POST",
                    endpoint,
                    headers=headers,
                    json=body,
                    max_retries=max_retries,
                    retry_delay_seconds=retry_delay_seconds,
                )
                if response.ok:
                    return
            except Exception as exc:  # noqa: BLE001
                last_error = exc

    raise RuntimeError(f"Nao foi possivel enviar mensagem ao grupo: {last_error}")


def main() -> int:
    load_dotenv()
    args = parse_args()
    log_info("Iniciando rotina de monitoramento de saldo Meta Ads")

    try:
        access_token = env_required("META_ACCESS_TOKEN")
        business_id = env_required("META_BUSINESS_ID")
        evolution_base_url = env_required("EVOLUTION_SERVER_URL")
        evolution_api_key = env_required("EVOLUTION_API_KEY")
        evolution_instance = env_required("EVOLUTION_INSTANCE")
        evolution_group_id = env_required("EVOLUTION_GROUP_ID")
        max_retries = env_int("MAX_RETRIES", 3)
        retry_delay_seconds = env_int("RETRY_DELAY_SECONDS", 300)
        treat_as_cents = os.getenv("META_BALANCE_IS_CENTS", "true").lower() == "true"
        tz_name = os.getenv("TZ", "America/Sao_Paulo").strip() or "America/Sao_Paulo"
        json_accounts_path = (
            os.getenv("META_ACCOUNTS_JSON_PATH", "config/meta_ad_accounts.json").strip()
            or "config/meta_ad_accounts.json"
        )
    except ValueError as exc:
        log_error(f"Erro de configuracao: {exc}")
        return 2

    try:
        allowed_ids_from_json, labels_from_json = load_accounts_from_json(json_accounts_path)
    except Exception as exc:  # noqa: BLE001
        log_error(f"Erro ao ler arquivo de contas ({json_accounts_path}): {exc}")
        return 2

    allowed_ids_from_env = parse_allowed_account_ids(os.getenv("META_ALLOWED_ACCOUNT_IDS", ""))
    labels_from_env = parse_account_labels(os.getenv("META_ACCOUNT_LABELS", ""))

    allowed_account_ids = allowed_ids_from_json or allowed_ids_from_env
    account_labels = labels_from_json or labels_from_env

    log_info(
        f"Configuracao carregada | timezone={tz_name} | "
        f"limite_alerta={args.alert_threshold:.2f} | "
        f"limite_proximo_100={args.near_threshold:.2f}"
    )
    if allowed_ids_from_json:
        log_info(
            "Contas carregadas por JSON | "
            f"arquivo={json_accounts_path} | contas={len(allowed_ids_from_json)}"
        )
    elif allowed_ids_from_env:
        log_info("Contas carregadas por variaveis .env (modo legado).")
    else:
        log_warn("Nenhum filtro de contas definido. Todas as contas serao avaliadas.")

    if allowed_account_ids:
        log_info(
            "Filtro por whitelist ativo | "
            f"contas_monitoradas={len(allowed_account_ids)}"
        )

    session = requests.Session()

    try:
        log_info("Consultando contas no Meta Ads...")
        accounts_raw = fetch_accounts(
            session,
            business_id=business_id,
            access_token=access_token,
            max_retries=max_retries,
            retry_delay_seconds=retry_delay_seconds,
        )
        accounts = normalize_accounts(accounts_raw, treat_as_cents=treat_as_cents)
    except Exception as exc:  # noqa: BLE001
        log_error(f"Erro ao consultar contas do Meta Ads: {exc}")
        return 1

    total_before_filter = len(accounts)
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

    low_balances = [
        account for account in accounts if account.balance_brl <= args.alert_threshold
    ]

    result = {
        "total_contas_encontradas": total_before_filter,
        "total_contas_apos_filtro": len(accounts),
        "contas_abaixo_ou_igual_alerta": len(low_balances),
        "limite_alerta": args.alert_threshold,
        "limite_proximo_100": args.near_threshold,
    }
    log_info("Resumo da varredura:")
    safe_print(json.dumps(result, ensure_ascii=True, indent=2))

    if not low_balances:
        log_success("Nenhuma conta abaixo do limite. Nenhuma mensagem enviada ao grupo.")
        return 0

    top_low = sorted(low_balances, key=lambda item: item.balance_brl)[:3]
    preview = ", ".join(
        f"{item.name}: R${item.balance_brl:.2f} ({item.balance_source})" for item in top_low
    )
    log_warn(f"Contas abaixo do limite detectadas: {len(low_balances)}")
    log_info(f"Top saldos baixos: {preview}")

    message = build_alert_message(
        low_balances,
        alert_threshold=args.alert_threshold,
        near_threshold=args.near_threshold,
        tz_name=tz_name,
    )

    if args.dry_run:
        log_info("MODO DRY-RUN ativo. Mensagem sera exibida, sem envio ao grupo.")
        safe_print(message)
        return 0

    try:
        log_info("Enviando alerta para o grupo no WhatsApp...")
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
        log_error(f"Erro ao enviar mensagem para o grupo: {exc}")
        return 1

    log_success("Mensagem enviada com sucesso para o grupo.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
