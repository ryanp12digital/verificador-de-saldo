"""Limites de saldo para disparo de alertas (alerta e faixa de atencao)."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from db import (
    get_monitor_thresholds_config,
    is_database_configured,
    migrate,
    upsert_monitor_thresholds_config,
)

DEFAULT_ALERT_THRESHOLD = 200.0
DEFAULT_NEAR_THRESHOLD = 120.0


def default_thresholds() -> Dict[str, float]:
    return {
        "alert_threshold": DEFAULT_ALERT_THRESHOLD,
        "near_threshold": DEFAULT_NEAR_THRESHOLD,
    }


def _thresholds_json_path(repo_root: Optional[Path] = None) -> Path:
    root = repo_root or Path(__file__).resolve().parent.parent
    rel = (
        os.getenv("MONITOR_THRESHOLDS_PATH", "config/monitor_thresholds.json").strip()
        or "config/monitor_thresholds.json"
    )
    return root / rel


def _float_from_env(name: str) -> Optional[float]:
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def sanitize_thresholds(payload: Any) -> Dict[str, float]:
    base = default_thresholds()
    if not isinstance(payload, dict):
        return base

    alert = payload.get("alert_threshold", payload.get("alert"))
    near = payload.get("near_threshold", payload.get("near"))

    try:
        alert_f = float(alert) if alert is not None else base["alert_threshold"]
    except (TypeError, ValueError):
        alert_f = base["alert_threshold"]

    try:
        near_f = float(near) if near is not None else base["near_threshold"]
    except (TypeError, ValueError):
        near_f = base["near_threshold"]

    if alert_f <= 0:
        alert_f = DEFAULT_ALERT_THRESHOLD
    if near_f <= 0:
        near_f = DEFAULT_NEAR_THRESHOLD
    if near_f > alert_f:
        near_f = min(near_f, alert_f)

    return {
        "alert_threshold": round(alert_f, 2),
        "near_threshold": round(near_f, 2),
    }


def load_thresholds(repo_root: Optional[Path] = None) -> Dict[str, float]:
    merged = default_thresholds()

    env_alert = _float_from_env("ALERT_THRESHOLD")
    env_near = _float_from_env("NEAR_THRESHOLD")
    if env_alert is not None:
        merged["alert_threshold"] = env_alert
    if env_near is not None:
        merged["near_threshold"] = env_near

    path = _thresholds_json_path(repo_root)
    if path.exists():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            merged = sanitize_thresholds({**merged, **raw})
        except (json.JSONDecodeError, OSError):
            pass

    if is_database_configured():
        migrate()
        db_cfg = get_monitor_thresholds_config()
        if db_cfg:
            merged = sanitize_thresholds({**merged, **db_cfg})

    return sanitize_thresholds(merged)


def load_threshold_pair(repo_root: Optional[Path] = None) -> Tuple[float, float]:
    t = load_thresholds(repo_root)
    return t["alert_threshold"], t["near_threshold"]


def save_thresholds_to_file(cfg: Dict[str, float], repo_root: Optional[Path] = None) -> None:
    path = _thresholds_json_path(repo_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(sanitize_thresholds(cfg), ensure_ascii=True, indent=2),
        encoding="utf-8",
    )


def persist_thresholds(cfg: Dict[str, Any], repo_root: Optional[Path] = None) -> str:
    clean = sanitize_thresholds(cfg)
    if is_database_configured():
        migrate()
        upsert_monitor_thresholds_config(clean)
        save_thresholds_to_file(clean, repo_root)
        return "postgres"
    save_thresholds_to_file(clean, repo_root)
    return "json"
