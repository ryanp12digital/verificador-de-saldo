#!/usr/bin/env sh
set -eu

CRON_FILE="/tmp/crontab"

if [ -f /app/config/monitor_schedule.json ]; then
  CRON_FROM_FILE="$(python -c "import sys; sys.path.insert(0,'/app/execution'); from monitor_schedule import cron_expression; print(cron_expression())" 2>/dev/null || true)"
  if [ -n "${CRON_FROM_FILE}" ]; then
    CRON_SCHEDULE="${CRON_FROM_FILE}"
  fi
fi
CRON_SCHEDULE="${CRON_SCHEDULE:-0 8,18 * * *}"

echo "🚀 [START] Container de monitoramento Meta/Google Ads iniciado"
echo "⏰ [CRON] Agendamento configurado: ${CRON_SCHEDULE}"

if [ "${DASHBOARD_ENABLED:-false}" = "true" ]; then
  echo "🖥️  [DASHBOARD] Iniciando servidor em background (DASHBOARD_HOST=${DASHBOARD_HOST:-127.0.0.1} PORT=${DASHBOARD_PORT:-5050})"
  python /app/execution/dashboard_server.py &
fi

cat > "${CRON_FILE}" <<EOF
${CRON_SCHEDULE} /app/scripts/run_monitor_container.sh
EOF

# Executa uma vez ao iniciar para validar configuracao
echo "🧪 [CHECK] Executando teste inicial do monitor..."
/app/scripts/run_monitor_container.sh || true

echo "🕒 [RUNNING] Supercronic ativo. Aguardando proximas execucoes..."
exec /usr/local/bin/supercronic "${CRON_FILE}"
