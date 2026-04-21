#!/bin/bash
# Post-Deploy Health Check
# Wird nach jedem 'systemctl restart dental-os' ausgeführt
# Prüft die Live-API und meldet Probleme

API_URL="${1:-http://127.0.0.1:8100/api/health}"

echo "Checking $API_URL ..."
sleep 2

RESPONSE=$(curl -s -w "\n%{http_code}" "$API_URL")
HTTP_CODE=$(echo "$RESPONSE" | tail -n1)
BODY=$(echo "$RESPONSE" | sed '$d')

if [ "$HTTP_CODE" != "200" ]; then
    echo "FEHLER: HTTP $HTTP_CODE"
    echo "$BODY"
    exit 1
fi

STATUS=$(echo "$BODY" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['status'])")
RATE=$(echo "$BODY" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['match_rate'])")

echo "Status: $STATUS  ($RATE% Trefferquote)"

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
