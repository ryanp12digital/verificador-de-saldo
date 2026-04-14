#!/usr/bin/env sh
set -eu

CRON_SCHEDULE="${CRON_SCHEDULE:-0 8,18 * * *}"
CRON_FILE="/tmp/crontab"

echo "🚀 [START] Container de monitoramento Meta Ads iniciado"
echo "⏰ [CRON] Agendamento configurado: ${CRON_SCHEDULE}"

cat > "${CRON_FILE}" <<EOF
${CRON_SCHEDULE} /app/scripts/run_monitor_container.sh
EOF

# Executa uma vez ao iniciar para validar configuracao
echo "🧪 [CHECK] Executando teste inicial do monitor..."
/app/scripts/run_monitor_container.sh || true

echo "🕒 [RUNNING] Supercronic ativo. Aguardando proximas execucoes..."
exec /usr/local/bin/supercronic "${CRON_FILE}"
