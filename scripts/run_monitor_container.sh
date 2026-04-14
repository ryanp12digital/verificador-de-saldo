#!/usr/bin/env sh
set -eu

ALERT_THRESHOLD="${ALERT_THRESHOLD:-200}"
NEAR_THRESHOLD="${NEAR_THRESHOLD:-120}"
TZ_VALUE="${TZ:-America/Sao_Paulo}"

echo "[INFO] Executando monitoramento Meta Ads (TZ=${TZ_VALUE})"
TZ="${TZ_VALUE}" python /app/execution/monitorar_saldo_meta_ads.py \
  --alert-threshold "${ALERT_THRESHOLD}" \
  --near-threshold "${NEAR_THRESHOLD}"
