#!/usr/bin/env sh
set -eu

TZ_VALUE="${TZ:-America/Sao_Paulo}"

THRESHOLDS="$(python -c "
import sys
sys.path.insert(0, '/app/execution')
from monitor_thresholds import load_threshold_pair
a, n = load_threshold_pair()
print(a, n)
" 2>/dev/null || echo "200 120")"
ALERT_THRESHOLD="$(echo "$THRESHOLDS" | awk '{print $1}')"
NEAR_THRESHOLD="$(echo "$THRESHOLDS" | awk '{print $2}')"

META_ENABLED=1
GOOGLE_ENABLED=1
FLAGS="$(python -c "
import sys
sys.path.insert(0, '/app/execution')
from monitor_schedule import load_schedule
s = load_schedule()
print(int(bool(s.get('meta_enabled', True))), int(bool(s.get('google_enabled', True))))
" 2>/dev/null || echo "1 1")"
META_ENABLED="$(echo "$FLAGS" | awk '{print $1}')"
GOOGLE_ENABLED="$(echo "$FLAGS" | awk '{print $2}')"

echo "📊 [JOB] Iniciando monitoramento agendado"
echo "⚙️  [CONFIG] TZ=${TZ_VALUE} | ALERT=${ALERT_THRESHOLD} | NEAR=${NEAR_THRESHOLD} | META=${META_ENABLED} | GOOGLE=${GOOGLE_ENABLED}"

EXIT=0

if [ "${META_ENABLED}" = "1" ]; then
  echo "📊 [META] Monitor Meta Ads"
  TZ="${TZ_VALUE}" python /app/execution/monitorar_saldo_meta_ads.py \
    --alert-threshold "${ALERT_THRESHOLD}" \
    --near-threshold "${NEAR_THRESHOLD}" \
    --force-send || EXIT=$?
fi

if [ "${GOOGLE_ENABLED}" = "1" ]; then
  echo "📊 [GOOGLE] Monitor Google Ads"
  TZ="${TZ_VALUE}" python /app/execution/monitorar_saldo_google_ads.py \
    --alert-threshold "${ALERT_THRESHOLD}" \
    --near-threshold "${NEAR_THRESHOLD}" \
    --force-send || EXIT=$?
fi

exit "${EXIT}"
