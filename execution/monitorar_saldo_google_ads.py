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


def build_alert_message(
    low: List[LowGoogleAccount],
    *,
    alert_threshold: float,
    near_threshold: float,
    tz_name: str,
) -> str:
    now = get_now_in_timezone(tz_name).strftime("%d/%m/%Y %H:%M")
    lines = [
        "🚨 *Alerta de Saldo - Google Ads*",
        f"🕒 Referencia: {now} ({tz_name})",
        f"🎯 Criterio: saldo/orcamento restante <= {alert_threshold:.2f} (moeda da conta)",
        "",
    ]

    for item in sorted(low, key=lambda x: x.balance):
        if item.balance <= 100:
            level = "🔴 CRITICO"
        elif item.balance <= near_threshold:
            level = "🟠 ATENCAO (proximo de 100)"
        else:
            level = "🟡 ALERTA"

        lines.append(
            f"- {level} | {item.name or item.customer_id} "
            f"- Saldo: {item.balance:.2f} {item.currency} ({item.source})"
        )

    lines.append("")
    lines.append("✅ Acao recomendada: revisar pagamentos / orcamentos das contas listadas.")
    lines.append("🔗 Google Ads: https://ads.google.com/")
    return "\n".join(lines)


def main() -> int:
    load_dotenv()
    args = parse_args()
    log_info("Iniciando rotina de monitoramento Google Ads")

    try:
        evolution_base_url = env_required("EVOLUTION_SERVER_URL")
        evolution_api_key = env_required("EVOLUTION_API_KEY")
        evolution_instance = env_required("EVOLUTION_INSTANCE")
        evolution_group_id = env_required("EVOLUTION_GROUP_ID")
        max_retries = env_int("MAX_RETRIES", 3)
        retry_delay_seconds = env_int("RETRY_DELAY_SECONDS", 300)
        tz_name = os.getenv("TZ", "America/Sao_Paulo").strip() or "America/Sao_Paulo"
        json_path = (
            os.getenv("GOOGLE_ACCOUNTS_JSON_PATH", "config/google_ad_accounts.json").strip()
            or "config/google_ad_accounts.json"
        )
    except ValueError as exc:
        log_error(f"Erro de configuracao: {exc}")
        return 2

    try:
        accounts_cfg, source_accounts, strict_whitelist = load_google_accounts_for_monitor(
            json_path
        )
    except Exception as exc:  # noqa: BLE001
        log_error(f"Erro ao carregar lista de contas Google: {exc}")
        return 2

    log_info(
        f"Configuracao carregada | fonte={source_accounts} | "
        f"limite_alerta={args.alert_threshold:.2f} | limite_proximo={args.near_threshold:.2f}"
    )

    if strict_whitelist and not accounts_cfg:
        log_warn("Nenhuma conta Google habilitada no Postgres. Encerrando sem varredura.")
        return 0

    if not strict_whitelist and not accounts_cfg:
        log_warn("Nenhuma conta Google configurada (JSON ausente ou vazio). Encerrando.")
        return 0

    try:
        from google_ads_balance import build_client_config

        build_client_config()
    except ValueError as exc:
        log_error(f"Google Ads nao configurado: {exc}")
        return 2

    low: List[LowGoogleAccount] = []
    errors = 0

    for entry in accounts_cfg:
        cid = entry["customer_id"]
        label = entry.get("name") or cid
        row = fetch_balance_for_customer(cid)
        if row.status == "erro":
            log_error(f"{label} ({cid}): {row.message}")
            errors += 1
            continue
        if row.status == "indisponivel":
            log_warn(f"{label} ({cid}): {row.message}")
            continue
        if row.balance is None:
            continue
        if row.balance <= args.alert_threshold:
            low.append(
                LowGoogleAccount(
                    customer_id=cid,
                    name=row.name or label,
                    currency=row.currency or "?",
                    balance=row.balance,
                    source=row.source,
                )
            )

    summary = {
        "contas_configuradas": len(accounts_cfg),
        "contas_com_alerta": len(low),
        "erros_consulta": errors,
        "limite_alerta": args.alert_threshold,
    }
    log_info("Resumo da varredura:")
    safe_print(json.dumps(summary, ensure_ascii=True, indent=2))

    if not low:
        log_success("Nenhuma conta abaixo do limite. Nenhuma mensagem enviada ao grupo.")
        return 0

    message = build_alert_message(
        low,
        alert_threshold=args.alert_threshold,
        near_threshold=args.near_threshold,
        tz_name=tz_name,
    )

    if args.dry_run:
        log_info("MODO DRY-RUN ativo. Mensagem sera exibida, sem envio ao grupo.")
        safe_print(message)
        return 0

    session = requests.Session()
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
