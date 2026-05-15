"""Requisicoes HTTP com retentativas (compartilhado por integracoes)."""

from __future__ import annotations

import time
from typing import Any, Optional

import requests


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
