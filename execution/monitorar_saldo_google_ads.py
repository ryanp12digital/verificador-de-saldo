import argparse
import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import List
from zoneinfo import ZoneInfo

import requests
from dotenv import load_dotenv

from accounts_config import load_google_accounts_for_monitor
from alert_message_style import build_google_whatsapp_message, load_merged_style
from evolution_notify import send_group_message
from google_ads_balance import fetch_balance_for_customer


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Monitora saldo/orcamento Google Ads (account_budget) e envia alerta "
            "para grupo no Evolution quando necessario."
        )
    )
    parser.add_argument(
        "--alert-threshold",
        type=float,
        default=200.0,
        help="Dispara alerta quando saldo for menor ou igual a esse valor (na moeda da conta).",
    )
    parser.add_argument(
        "--near-threshold",
        type=float,
        default=120.0,
        help="Faixa para marcar saldo como proximo de 100 (mesma unidade do saldo).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Nao envia mensagem no grupo. Apenas imprime a mensagem gerada.",
    )
    parser.add_argument(
        "--force-send",
        action="store_true",
        help="Envia relatorio com todas as contas monitoradas, mesmo acima do limite.",
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


@dataclass
class LowGoogleAccount:
    customer_id: str
    name: str
    currency: str
    balance: float
    source: str


def main() -> int:
    load_dotenv()
    args = parse_args()
    log_info("Iniciando rotina de monitoramento Google Ads")
    if args.force_send:
        log_warn("Modo force-send: todas as contas monitoradas entram na mensagem.")

    from monitor_runner import run_google_monitor

    result = run_google_monitor(
        force_send=args.force_send,
        dry_run=args.dry_run,
        alert_threshold=args.alert_threshold,
        near_threshold=args.near_threshold,
    )

    log_info("Resumo da varredura:")
    safe_print(json.dumps(result.summary, ensure_ascii=True, indent=2))

    if result.error:
        log_error(result.error)
        return result.exit_code

    if not result.message and not result.sent:
        log_success("Nenhuma conta para alertar. Nenhuma mensagem enviada ao grupo.")
        return 0

    if args.dry_run and result.message:
        log_info("MODO DRY-RUN ativo. Mensagem sera exibida, sem envio ao grupo.")
        safe_print(result.message)
        return 0

    if result.sent:
        log_success("Mensagem enviada com sucesso para o grupo.")
        return 0

    return result.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
