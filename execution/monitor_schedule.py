"""Horarios de execucao do monitor (CRON / scheduler da dashboard)."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from db import get_monitor_schedule_config, is_database_configured, migrate, upsert_monitor_schedule_config

DEFAULT_TIMES: List[str] = ["08:00", "18:00"]
DEFAULT_TIMEZONE = "America/Sao_Paulo"
_TIME_RE = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")


def default_schedule() -> Dict[str, Any]:
    return {
        "times": list(DEFAULT_TIMES),
        "timezone": DEFAULT_TIMEZONE,
        "meta_enabled": True,
        "google_enabled": True,
    }


def _schedule_json_path(repo_root: Optional[Path] = None) -> Path:
    root = repo_root or Path(__file__).resolve().parent.parent
    rel = (
        os.getenv("MONITOR_SCHEDULE_PATH", "config/monitor_schedule.json").strip()
        or "config/monitor_schedule.json"
    )
    return root / rel


def sanitize_schedule(payload: Any) -> Dict[str, Any]:
    base = default_schedule()
    if not isinstance(payload, dict):
        return base

    times_in = payload.get("times")
    times: List[str] = []
    if isinstance(times_in, list):
        for item in times_in:
            if not isinstance(item, str):
                continue
            t = item.strip()
            if _TIME_RE.match(t):
                h, m = t.split(":")
                times.append(f"{int(h):02d}:{m}")
    if not times:
        times = list(DEFAULT_TIMES)
    times = sorted(set(times))

    tz = payload.get("timezone")
    timezone_name = (
        tz.strip() if isinstance(tz, str) and tz.strip() else DEFAULT_TIMEZONE
    )

    meta_enabled = payload.get("meta_enabled")
    google_enabled = payload.get("google_enabled")

    return {
        "times": times,
        "timezone": timezone_name,
        "meta_enabled": bool(meta_enabled) if meta_enabled is not None else True,
        "google_enabled": bool(google_enabled) if google_enabled is not None else True,
    }


def times_to_cron_expr(times: List[str]) -> str:
    """Converte ['08:00','18:00'] em expressao cron (minuto hora * * *)."""
    clean = sanitize_schedule({"times": times})["times"]
    hours: List[int] = []
    minutes: List[int] = []
    for t in clean:
        h_s, m_s = t.split(":")
        hours.append(int(h_s))
        minutes.append(int(m_s))
    if not hours:
        return "0 8,18 * * *"
    minute = minutes[0] if len(set(minutes)) == 1 else "*"
    hour_part = ",".join(str(h) for h in sorted(set(hours)))
    return f"{minute} {hour_part} * * *"


def load_schedule(repo_root: Optional[Path] = None) -> Dict[str, Any]:
    if is_database_configured():
        migrate()
        db_cfg = get_monitor_schedule_config()
        if db_cfg:
            return sanitize_schedule(db_cfg)

    path = _schedule_json_path(repo_root)
    if path.exists():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            return sanitize_schedule(raw)
        except (json.JSONDecodeError, OSError):
            pass
    return default_schedule()


def save_schedule_to_file(cfg: Dict[str, Any], repo_root: Optional[Path] = None) -> None:
    path = _schedule_json_path(repo_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(sanitize_schedule(cfg), ensure_ascii=True, indent=2),
        encoding="utf-8",
    )


def persist_schedule(cfg: Dict[str, Any], repo_root: Optional[Path] = None) -> str:
    clean = sanitize_schedule(cfg)
    if is_database_configured():
        migrate()
        upsert_monitor_schedule_config(clean)
        save_schedule_to_file(clean, repo_root)
        return "postgres"
    save_schedule_to_file(clean, repo_root)
    return "json"


def cron_expression(repo_root: Optional[Path] = None) -> str:
    sched = load_schedule(repo_root)
    return times_to_cron_expr(sched["times"])
