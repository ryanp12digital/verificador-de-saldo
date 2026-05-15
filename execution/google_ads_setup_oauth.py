"""
Fluxo OAuth2 (uma vez) para obter GOOGLE_ADS_REFRESH_TOKEN.

Pre-requisitos no .env:
  GOOGLE_ADS_CLIENT_ID
  GOOGLE_ADS_CLIENT_SECRET

Uso:
  python execution/google_ads_setup_oauth.py
"""

from __future__ import annotations

import os
import sys

from dotenv import load_dotenv

SCOPES = ["https://www.googleapis.com/auth/adwords"]


def env_required(name: str) -> str:
    value = os.getenv(name)
    if value is None or not str(value).strip():
        raise ValueError(f"Variavel obrigatoria ausente no .env: {name}")
    return str(value).strip()


def main() -> int:
    load_dotenv()
    try:
        client_id = env_required("GOOGLE_ADS_CLIENT_ID")
        client_secret = env_required("GOOGLE_ADS_CLIENT_SECRET")
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 2

    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError as exc:
        print("Instale dependencias: pip install google-auth-oauthlib", file=sys.stderr)
        print(exc, file=sys.stderr)
        return 2

    client_config = {
        "installed": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": ["http://localhost", "urn:ietf:wg:oauth:2.0:oob"],
        }
    }

    flow = InstalledAppFlow.from_client_config(client_config, scopes=SCOPES)
    creds = flow.run_local_server(port=0, prompt="consent")
    token = getattr(creds, "refresh_token", None)
    if not token:
        print("Nenhum refresh_token retornado. Tente revogar acesso em myaccount.google.com/permissions.", file=sys.stderr)  # noqa: E501
        return 1

    print("\n--- Cole no .env ---\n")
    print(f"GOOGLE_ADS_REFRESH_TOKEN={token}")
    print("\n--------------------\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
