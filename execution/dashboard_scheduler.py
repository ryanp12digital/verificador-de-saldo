"""Agendador em background quando a dashboard esta ativa."""

from __future__ import annotations

import logging
import os
import threading
import time
from datetime import datetime
from typing import Dict, Optional, Set
from zoneinfo import ZoneInfo

from monitor_runner import run_google_monitor, run_meta_monitor
from monitor_schedule import load_schedule

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_last_runs: Set[str] = set()
_thread: Optional[threading.Thread] = None
_started = False


def _scheduler_enabled() -> bool:
    flag = (os.getenv("DASHBOARD_SCHEDULER_ENABLED", "true") or "").strip().lower()
    return flag not in ("0", "false", "no", "off")


def _tick_key(when: datetime, slot: str, platform: str) -> str:
    return f"{when.strftime('%Y-%m-%d')}:{slot}:{platform}"


def _should_run_slot(now: datetime, times: list[str]) -> Optional[str]:
    current = now.strftime("%H:%M")
    for slot in times:
        if slot == current:
            return slot
    return None


def _run_scheduled_job(slot: str, sched: Dict) -> None:
    meta_on = bool(sched.get("meta_enabled", True))
    google_on = bool(sched.get("google_enabled", True))
    tz_name = str(sched.get("timezone") or "America/Sao_Paulo")

    try:
        now = datetime.now(ZoneInfo(tz_name))
    except Exception:  # noqa: BLE001
        now = datetime.now()

    if meta_on:
        key = _tick_key(now, slot, "meta")
        run_meta = False
        with _lock:
            if key not in _last_runs:
                _last_runs.add(key)
                run_meta = True
        if run_meta:
            logger.info("Scheduler: executando monitor Meta (%s)", slot)
            result = run_meta_monitor(force_send=True, dry_run=False)
            logger.info(
                "Scheduler Meta: sent=%s exit=%s motivo=%s",
                result.sent,
                result.exit_code,
                result.summary.get("motivo"),
            )

    if google_on:
        key = _tick_key(now, slot, "google")
        run_google = False
        with _lock:
            if key not in _last_runs:
                _last_runs.add(key)
                run_google = True
        if run_google:
            logger.info("Scheduler: executando monitor Google (%s)", slot)
            result = run_google_monitor(force_send=True, dry_run=False)
            logger.info(
                "Scheduler Google: sent=%s exit=%s motivo=%s",
                result.sent,
                result.exit_code,
                result.summary.get("motivo"),
            )


def _loop() -> None:
    while True:
        try:
            sched = load_schedule()
            tz_name = str(sched.get("timezone") or "America/Sao_Paulo")
            try:
                now = datetime.now(ZoneInfo(tz_name))
            except Exception:  # noqa: BLE001
                now = datetime.now()

            slot = _should_run_slot(now, list(sched.get("times") or []))
            if slot:
                _run_scheduled_job(slot, sched)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Scheduler tick falhou: %s", exc)
        time.sleep(30)


def start_dashboard_scheduler() -> None:
    global _started, _thread  # noqa: PLW0603
    if _started or not _scheduler_enabled():
        return
    _started = True
    _thread = threading.Thread(target=_loop, name="dashboard-scheduler", daemon=True)
    _thread.start()
    logger.info("Dashboard scheduler iniciado (intervalo 30s)")
