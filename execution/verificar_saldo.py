import argparse
import json
import os
import sys

from dotenv import load_dotenv


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Verifica se o saldo atual esta acima do limite minimo."
    )
    parser.add_argument(
        "--limite",
        type=float,
        required=True,
        help="Valor minimo de saldo esperado.",
    )
    return parser.parse_args()


def get_saldo_atual() -> float:
    saldo_bruto = os.getenv("SALDO_ATUAL")
    if saldo_bruto is None:
        raise ValueError("Variavel SALDO_ATUAL nao encontrada no .env.")
    try:
        return float(saldo_bruto)
    except ValueError as exc:
        raise ValueError("SALDO_ATUAL precisa ser numerico.") from exc


def main() -> int:
    load_dotenv()
    args = parse_args()

    if args.limite < 0:
        print("Erro: o limite nao pode ser negativo.", file=sys.stderr)
        return 2

    try:
        saldo_atual = get_saldo_atual()
    except ValueError as exc:
        print(f"Erro: {exc}", file=sys.stderr)
        return 1

    status = "ok" if saldo_atual >= args.limite else "abaixo_do_limite"
    resultado = {
        "saldo_atual": saldo_atual,
        "limite_minimo": args.limite,
        "status": status,
    }
    print(json.dumps(resultado, ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
