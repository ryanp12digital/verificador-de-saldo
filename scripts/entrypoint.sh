#!/usr/bin/env sh
set -eu

CRON_SCHEDULE="${CRON_SCHEDULE:-0 8,18 * * *}"
CRON_FILE="/tmp/crontab"

echo "🚀 [START] Container de monitoramento Meta Ads iniciado"
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
