#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUNNER="${ROOT_DIR}/scripts/run_monitor.sh"
TMP_CRON="$(mktemp)"
MARKER_BEGIN="# >>> monitor-meta-ads >>>"
MARKER_END="# <<< monitor-meta-ads <<<"

if [[ ! -x "${RUNNER}" ]]; then
  echo "[ERRO] Runner nao executavel: ${RUNNER}" >&2
  echo "Execute: chmod +x scripts/*.sh" >&2
  exit 1
fi

crontab -l 2>/dev/null \
  | sed "/${MARKER_BEGIN}/,/${MARKER_END}/d" > "${TMP_CRON}"

{
  echo "${MARKER_BEGIN}"
  echo "0 8,18 * * * ${RUNNER}"
  echo "${MARKER_END}"
} >> "${TMP_CRON}"

crontab "${TMP_CRON}"
rm -f "${TMP_CRON}"

echo "CRON instalado com sucesso."
echo "Agendamentos ativos:"
crontab -l | sed -n "/${MARKER_BEGIN}/,/${MARKER_END}/p"
