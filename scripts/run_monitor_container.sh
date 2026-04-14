#!/usr/bin/env sh
set -eu

ALERT_THRESHOLD="${ALERT_THRESHOLD:-200}"
NEAR_THRESHOLD="${NEAR_THRESHOLD:-120}"
TZ_VALUE="${TZ:-America/Sao_Paulo}"

echo "📊 [JOB] Iniciando monitoramento Meta Ads"
echo "⚙️  [CONFIG] TZ=${TZ_VALUE} | ALERT_THRESHOLD=${ALERT_THRESHOLD} | NEAR_THRESHOLD=${NEAR_THRESHOLD}"
TZ="${TZ_VALUE}" python /app/execution/monitorar_saldo_meta_ads.py \
  --alert-threshold "${ALERT_THRESHOLD}" \
  --near-threshold "${NEAR_THRESHOLD}"
