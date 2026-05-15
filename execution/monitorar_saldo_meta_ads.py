import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from typing import List
from zoneinfo import ZoneInfo

import requests
from dotenv import load_dotenv

from accounts_config import load_meta_allowlist_for_monitor
from evolution_notify import send_group_message
from meta_ads_balance import (
    AdAccountBalance,
    fetch_accounts,
    normalize_account_id,
    normalize_accounts,
)


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
        allowed_account_ids, account_labels, source_accounts, strict_whitelist = (
            load_meta_allowlist_for_monitor(json_accounts_path)
        )
    except Exception as exc:  # noqa: BLE001
        log_error(f"Erro ao carregar lista de contas: {exc}")
        return 2

    log_info(
        f"Configuracao carregada | timezone={tz_name} | "
        f"limite_alerta={args.alert_threshold:.2f} | "
        f"limite_proximo_100={args.near_threshold:.2f}"
    )

    if source_accounts == "postgres":
        log_info(f"Contas carregadas do PostgreSQL | contas={len(allowed_account_ids)}")
    elif source_accounts == "json":
        log_info(
            "Contas carregadas por JSON | "
            f"arquivo={json_accounts_path} | contas={len(allowed_account_ids)}"
        )
    elif source_accounts == "env":
        log_info("Contas carregadas por variaveis .env (modo legado).")
    else:
        log_warn("Nenhum filtro de contas definido. Todas as contas serao avaliadas.")

    if strict_whitelist and not allowed_account_ids:
        log_warn("Nenhuma conta Meta habilitada no Postgres. Encerrando sem varredura.")
        return 0

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
    if strict_whitelist:
        accounts = [
            item
            for item in accounts
            if normalize_account_id(item.account_id) in allowed_account_ids
        ]
    elif allowed_account_ids:
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
