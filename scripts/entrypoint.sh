#!/usr/bin/env sh
set -eu

CRON_SCHEDULE="${CRON_SCHEDULE:-0 8,18 * * *}"
CRON_FILE="/tmp/crontab"

echo "[INFO] Iniciando container de monitoramento Meta Ads"
echo "[INFO] Agendamento: ${CRON_SCHEDULE}"

cat > "${CRON_FILE}" <<EOF
${CRON_SCHEDULE} /app/scripts/run_monitor_container.sh
EOF

# Executa uma vez ao iniciar para validar configuracao
/app/scripts/run_monitor_container.sh || true

exec /usr/local/bin/supercronic "${CRON_FILE}"
