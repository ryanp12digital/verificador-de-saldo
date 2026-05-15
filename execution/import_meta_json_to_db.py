"""
Importa config/meta_ad_accounts.json para a tabela monitored_accounts (provider=meta).

Requer PostgreSQL configurado (DATABASE_URL ou POSTGRES_*).
Uso:
  python execution/import_meta_json_to_db.py
"""

from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv

from db import is_database_configured, migrate, replace_accounts
from meta_ads_balance import load_accounts_from_json


def main() -> int:
    load_dotenv()
    if not is_database_configured():
        print("PostgreSQL nao configurado.", file=sys.stderr)
        return 2

    json_path = (
        os.getenv("META_ACCOUNTS_JSON_PATH", "config/meta_ad_accounts.json").strip()
        or "config/meta_ad_accounts.json"
    )
    path = Path(json_path)
    if not path.exists():
        print(f"Arquivo nao encontrado: {path}", file=sys.stderr)
        return 2

    migrate()
    allowed, labels = load_accounts_from_json(str(path))
    rows = []
    for acc_id in sorted(allowed):
        rows.append((acc_id, labels.get(acc_id, ""), True))

    replace_accounts("meta", rows)
    print(f"Importadas {len(rows)} contas Meta para o Postgres (provider=meta).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
