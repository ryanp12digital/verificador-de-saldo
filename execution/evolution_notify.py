"""Envio de mensagens ao grupo via Evolution API."""

from __future__ import annotations

from typing import Optional

import requests

from http_util import request_with_retry


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
