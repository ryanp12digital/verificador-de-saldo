"""
Templates de mensagem de alerta (WhatsApp / Evolution).

Placeholders usam chaves duplas, por exemplo {{datetime}}, {{timezone}},
{{alert_threshold}}, {{near_threshold}}, {{level}}, {{name}}, {{balance}},
{{currency}}, e no Google: {{source}}, {{customer_id}}.

No texto, para um cifrao literal antes do valor, escreva R$ seguido de {{balance}}
(ex.: Saldo: R${{balance}} {{currency}}).
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from db import (
    get_alert_message_style,
    is_database_configured,
    migrate,
    sanitize_style_payload,
    upsert_alert_message_style,
)

DEFAULT_META: Dict[str, str] = {
    "title": "🚨 *Alerta de Saldo - Meta Ads*",
    "reference_line": "🕒 Referencia: {{datetime}} ({{timezone}})",
    "criterion_line": "🎯 Criterio: saldo <= R${{alert_threshold}}",
    "account_line": "- {{level}} | {{name}} - Saldo: R${{balance}} {{currency}}",
    "footer": (
        "✅ Acao recomendada: avaliar recarga das contas listadas.\n"
        "🔗 Pagamento Meta: https://business.facebook.com/billing_hub/accounts/details/"
    ),
}

DEFAULT_GOOGLE: Dict[str, str] = {
    "title": "🚨 *Alerta de Saldo - Google Ads*",
    "reference_line": "🕒 Referencia: {{datetime}} ({{timezone}})",
    "criterion_line": "🎯 Criterio: saldo/orcamento restante <= {{alert_threshold}} (moeda da conta)",
    "account_line": "- {{level}} | {{name}} - Saldo: {{balance}} {{currency}} ({{source}})",
    "footer": (
        "✅ Acao recomendada: revisar pagamentos / orcamentos das contas listadas.\n"
        "🔗 Google Ads: https://ads.google.com/"
    ),
}

_PLACEHOLDER = re.compile(r"\{\{(\w+)\}\}")


def _subst(text: str, ctx: Dict[str, Any]) -> str:
    def repl(m: re.Match[str]) -> str:
        key = m.group(1)
        if key not in ctx:
            return m.group(0)
        return str(ctx[key])

    return _PLACEHOLDER.sub(repl, text)


def style_json_path(repo_root: Optional[Path] = None) -> Path:
    root = repo_root or Path(__file__).resolve().parent.parent
    rel = (
        os.getenv("ALERT_MESSAGE_STYLE_PATH", "config/alert_message_style.json").strip()
        or "config/alert_message_style.json"
    )
    return root / rel


def load_style_from_file(provider: str, repo_root: Optional[Path] = None) -> Dict[str, str]:
    path = style_json_path(repo_root)
    base = dict(DEFAULT_META if provider == "meta" else DEFAULT_GOOGLE)
    if not path.exists():
        return base
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return base
    block = raw.get(provider)
    if not isinstance(block, dict):
        return base
    for k, v in block.items():
        if isinstance(v, str) and k in base:
            base[k] = v
        elif isinstance(v, str):
            base[k] = v
    return base


def load_style_from_db(provider: str) -> Optional[Dict[str, str]]:
    if not is_database_configured():
        return None
    migrate()
    return get_alert_message_style(provider)


def load_merged_style(provider: str, repo_root: Optional[Path] = None) -> Dict[str, str]:
    merged = load_style_from_file(provider, repo_root)
    db_block = load_style_from_db(provider)
    if db_block:
        merged = {**merged, **db_block}
    return merged


def merge_style_with_override(
    provider: str,
    override: Optional[Dict[str, Any]],
    repo_root: Optional[Path] = None,
) -> Dict[str, str]:
    base = load_merged_style(provider, repo_root)
    if not override:
        return base
    extra = sanitize_style_payload(override)
    return {**base, **extra}


def persist_styles(
    meta: Dict[str, Any],
    google: Dict[str, Any],
    repo_root: Optional[Path] = None,
) -> str:
    m_full = {**DEFAULT_META, **sanitize_style_payload(meta)}
    g_full = {**DEFAULT_GOOGLE, **sanitize_style_payload(google)}
    if is_database_configured():
        migrate()
        upsert_alert_message_style("meta", m_full)
        upsert_alert_message_style("google", g_full)
        return "postgres"
    save_styles_to_file(m_full, g_full, repo_root)
    return "json"


def save_styles_to_file(
    meta: Dict[str, str],
    google: Dict[str, str],
    repo_root: Optional[Path] = None,
) -> None:
    path = style_json_path(repo_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"meta": meta, "google": google}
    path.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")


def build_meta_whatsapp_message(
    *,
    low_balances: List[Any],
    alert_threshold: float,
    near_threshold: float,
    tz_name: str,
    now_str: str,
    style: Optional[Dict[str, str]] = None,
) -> str:
    st = style or dict(DEFAULT_META)
    lines: List[str] = []

    title = (st.get("title") or DEFAULT_META["title"]).strip()
    if title:
        lines.append(_subst(title, {}))

    ref = (st.get("reference_line") or "").strip()
    if ref:
        lines.append(
            _subst(
                ref,
                {"datetime": now_str, "timezone": tz_name},
            )
        )

    crit = (st.get("criterion_line") or "").strip()
    if crit:
        lines.append(
            _subst(
                crit,
                {
                    "alert_threshold": f"{alert_threshold:.2f}",
                    "near_threshold": f"{near_threshold:.2f}",
                    "datetime": now_str,
                    "timezone": tz_name,
                },
            )
        )

    if lines and lines[-1] != "":
        lines.append("")

    acc_tpl = (st.get("account_line") or DEFAULT_META["account_line"]).strip()
    for account in sorted(low_balances, key=lambda item: item.balance_brl):
        if account.balance_brl <= 100:
            level = "🔴 CRITICO"
        elif account.balance_brl <= near_threshold:
            level = "🟠 ATENCAO (proximo de R$100)"
        else:
            level = "🟡 ALERTA"

        ctx = {
            "level": level,
            "name": str(account.name),
            "balance": f"{account.balance_brl:.2f}",
            "currency": str(account.currency),
            "account_id": str(account.account_id),
            "alert_threshold": f"{alert_threshold:.2f}",
            "near_threshold": f"{near_threshold:.2f}",
            "datetime": now_str,
            "timezone": tz_name,
        }
        lines.append(_subst(acc_tpl, ctx))

    foot = (st.get("footer") or "").strip()
    if foot:
        lines.append("")
        lines.append(foot)

    return "\n".join(lines).strip()


def build_google_whatsapp_message(
    *,
    low: List[Any],
    alert_threshold: float,
    near_threshold: float,
    tz_name: str,
    now_str: str,
    style: Optional[Dict[str, str]] = None,
) -> str:
    st = style or dict(DEFAULT_GOOGLE)
    lines: List[str] = []

    title = (st.get("title") or DEFAULT_GOOGLE["title"]).strip()
    if title:
        lines.append(_subst(title, {}))

    ref = (st.get("reference_line") or "").strip()
    if ref:
        lines.append(_subst(ref, {"datetime": now_str, "timezone": tz_name}))

    crit = (st.get("criterion_line") or "").strip()
    if crit:
        lines.append(
            _subst(
                crit,
                {
                    "alert_threshold": f"{alert_threshold:.2f}",
                    "near_threshold": f"{near_threshold:.2f}",
                    "datetime": now_str,
                    "timezone": tz_name,
                },
            )
        )

    if lines and lines[-1] != "":
        lines.append("")

    acc_tpl = (st.get("account_line") or DEFAULT_GOOGLE["account_line"]).strip()
    for item in sorted(low, key=lambda x: x.balance):
        if item.balance <= 100:
            level = "🔴 CRITICO"
        elif item.balance <= near_threshold:
            level = "🟠 ATENCAO (proximo de 100)"
        else:
            level = "🟡 ALERTA"

        ctx = {
            "level": level,
            "name": str(item.name or item.customer_id),
            "balance": f"{item.balance:.2f}",
            "currency": str(item.currency),
            "customer_id": str(item.customer_id),
            "source": str(item.source),
            "alert_threshold": f"{alert_threshold:.2f}",
            "near_threshold": f"{near_threshold:.2f}",
            "datetime": now_str,
            "timezone": tz_name,
        }
        lines.append(_subst(acc_tpl, ctx))

    foot = (st.get("footer") or "").strip()
    if foot:
        lines.append("")
        lines.append(foot)

    return "\n".join(lines).strip()


def get_full_style_payload(repo_root: Optional[Path] = None) -> Dict[str, Dict[str, str]]:
    meta = load_merged_style("meta", repo_root)
    google = load_merged_style("google", repo_root)
    return {"meta": meta, "google": google}


def keys_help() -> Dict[str, Any]:
    return {
        "placeholders": [
            "{{datetime}}",
            "{{timezone}}",
            "{{alert_threshold}}",
            "{{near_threshold}}",
            "{{level}}",
            "{{name}}",
            "{{balance}}",
            "{{currency}}",
            "{{account_id}}  (Meta)",
            "{{customer_id}}  (Google)",
            "{{source}}  (Google)",
        ],
        "note": "Use *texto* para negrito no WhatsApp. Ex.: Saldo: R${{balance}} {{currency}} (o R$ fica literal antes do placeholder).",
    }
