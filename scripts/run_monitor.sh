#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_PYTHON="${ROOT_DIR}/.venv/bin/python"
LOCK_FILE="${ROOT_DIR}/.tmp/monitor.lock"
LOG_FILE="${ROOT_DIR}/.tmp/monitor_meta_ads.log"

if [[ ! -f "${ROOT_DIR}/.env" ]]; then
  echo "[ERRO] Arquivo .env nao encontrado em ${ROOT_DIR}" >&2
  exit 2
fi

if [[ ! -x "${VENV_PYTHON}" ]]; then
  echo "[ERRO] Python do venv nao encontrado em ${VENV_PYTHON}" >&2
  exit 2
fi

mkdir -p "${ROOT_DIR}/.tmp"

# shellcheck disable=SC1091
source "${ROOT_DIR}/.env"

TZ_VALUE="${TZ:-America/Sao_Paulo}"
THRESHOLDS="$("${VENV_PYTHON}" -c "
import sys
sys.path.insert(0, '${ROOT_DIR}/execution')
from monitor_thresholds import load_threshold_pair
a, n = load_threshold_pair('${ROOT_DIR}')
print(a, n)
" 2>/dev/null || echo "200 120")"
ALERT_THRESHOLD="$(echo "${THRESHOLDS}" | awk '{print $1}')"
NEAR_THRESHOLD="$(echo "${THRESHOLDS}" | awk '{print $2}')"

{
  if command -v flock >/dev/null 2>&1; then
    flock -n 9 || {
      echo "[$(date '+%Y-%m-%d %H:%M:%S')] Execucao ignorada: processo ja em andamento."
      exit 0
    }
  fi

  echo "[$(date '+%Y-%m-%d %H:%M:%S')] Iniciando monitoramento Meta Ads"
  set +e
  TZ="${TZ_VALUE}" "${VENV_PYTHON}" "${ROOT_DIR}/execution/monitorar_saldo_meta_ads.py" \
    --alert-threshold "${ALERT_THRESHOLD}" \
    --near-threshold "${NEAR_THRESHOLD}"
  EXIT_CODE=$?
  set -e
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] Finalizado com exit_code=${EXIT_CODE}"
  exit "${EXIT_CODE}"
} 9>"${LOCK_FILE}" >> "${LOG_FILE}" 2>&1
