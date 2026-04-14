#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"

echo "[1/5] Verificando pre-requisitos"
command -v "${PYTHON_BIN}" >/dev/null 2>&1 || {
  echo "[ERRO] ${PYTHON_BIN} nao encontrado no servidor." >&2
  exit 1
}

if [[ ! -f "${ROOT_DIR}/.env" ]]; then
  echo "[ERRO] Arquivo .env nao encontrado em ${ROOT_DIR}" >&2
  echo "Copie .env.example para .env e preencha os dados antes de continuar." >&2
  exit 1
fi

echo "[2/5] Criando ambiente virtual"
"${PYTHON_BIN}" -m venv "${ROOT_DIR}/.venv"

echo "[3/5] Instalando dependencias"
"${ROOT_DIR}/.venv/bin/pip" install --upgrade pip
"${ROOT_DIR}/.venv/bin/pip" install -r "${ROOT_DIR}/requirements.txt"

echo "[4/5] Preparando diretorio temporario"
mkdir -p "${ROOT_DIR}/.tmp"

echo "[5/5] Testando script em dry-run"
TZ="${TZ:-America/Sao_Paulo}" \
  "${ROOT_DIR}/.venv/bin/python" "${ROOT_DIR}/execution/monitorar_saldo_meta_ads.py" --dry-run

echo ""
echo "Setup concluido com sucesso."
echo "Proximo passo: executar scripts/install_cron.sh"
