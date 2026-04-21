#!/bin/bash
# Post-Deploy Health Check
# Wird nach jedem 'systemctl restart dental-os' ausgeführt
# Prüft die Live-API und meldet Probleme

API_URL="${1:-http://127.0.0.1:8100/api/health}"
LOG_FILE="${LOG_FILE:-/var/log/dental-os-verify.log}"

echo "Checking $API_URL ..."
sleep 2

RESPONSE=$(curl -s -w "\n%{http_code}" --max-time 30 "$API_URL")
HTTP_CODE=$(echo "$RESPONSE" | tail -n1)
BODY=$(echo "$RESPONSE" | sed '$d')

if [ "$HTTP_CODE" != "200" ]; then
    echo "FEHLER: HTTP $HTTP_CODE"
    echo "$BODY"
    exit 1
fi

STATUS=$(echo "$BODY" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['status'])")
RATE=$(echo "$BODY" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['match_rate'])")
ALERT=$(echo "$BODY" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('alert', False))")
TREND=$(echo "$BODY" | python3 -c "import json,sys; d=json.load(sys.stdin); print(', '.join(str(r) for r in d.get('trend_7days', [])))")

echo "Status: $STATUS  ($RATE% Trefferquote)"
if [ -n "$TREND" ]; then
    echo "Trend (letzte 7): $TREND"
fi

# Log-Eintrag (für tägliches Tracking)
TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S')
LOG_LINE="$TIMESTAMP | status=$STATUS | rate=$RATE% | alert=$ALERT"
if [ -w "$(dirname "$LOG_FILE")" ] || [ -w "$LOG_FILE" ]; then
    echo "$LOG_LINE" >> "$LOG_FILE" 2>/dev/null || true
fi

if [ "$ALERT" = "True" ]; then
    REASON=$(echo "$BODY" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('alert_reason', ''))")
    echo ""
    echo "ALERT: $REASON"
fi

if [ "$STATUS" = "critical" ]; then
    echo ""
    echo "=== FEHLGESCHLAGENE TESTS ==="
    echo "$BODY" | python3 -m json.tool
    exit 1
elif [ "$STATUS" = "warning" ]; then
    echo "Warnung: Trefferquote unter 70%"
    exit 0
else
    echo "OK"
    exit 0
fi
