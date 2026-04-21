#!/bin/bash
# Dental OS Server Setup - Hetzner
# Ausführen als: sudo bash setup_server.sh

set -e

BILLING_DIR="/var/www/ilabbilling"
VENV_DIR="$BILLING_DIR/.venv"
DATA_DIR="$BILLING_DIR/data"
SERVICE_NAME="dental-os"

echo "=== Dental OS Server Setup ==="

# 1. Git Pull
echo ""
echo "1. Git Pull..."
cd "$BILLING_DIR"
git config --global --add safe.directory "$BILLING_DIR" 2>/dev/null || true
git pull origin main
echo "   OK"

# 2. Python venv
echo ""
echo "2. Python venv erstellen..."
python3 -m venv "$VENV_DIR"
"$VENV_DIR/bin/pip" install --upgrade pip
"$VENV_DIR/bin/pip" install fastapi uvicorn
echo "   OK"

# 3. Data-Verzeichnis
echo ""
echo "3. Data-Verzeichnis..."
mkdir -p "$DATA_DIR"
chown -R deploy:www-data "$DATA_DIR"
chmod 775 "$DATA_DIR"
echo "   OK"

# 4. Systemd Service
echo ""
echo "4. Systemd Service..."
cat > /etc/systemd/system/${SERVICE_NAME}.service << 'UNIT'
[Unit]
Description=Dental OS Billing API
After=network.target

[Service]
Type=simple
User=deploy
Group=www-data
WorkingDirectory=/var/www/ilabbilling
ExecStart=/var/www/ilabbilling/.venv/bin/uvicorn server:app --host 127.0.0.1 --port 8100
Restart=always
RestartSec=5
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
UNIT

systemctl daemon-reload
systemctl enable ${SERVICE_NAME}
systemctl restart ${SERVICE_NAME}
sleep 2
systemctl status ${SERVICE_NAME} --no-pager
echo "   OK"

# 5. Apache Proxy
echo ""
echo "5. Apache Proxy konfigurieren..."
a2enmod proxy proxy_http 2>/dev/null || true

if ! grep -q "ProxyPass.*8100" /etc/apache2/conf-available/billing.conf 2>/dev/null; then
    cat > /etc/apache2/conf-available/billing.conf << 'CONF'
Alias /billing /var/www/ilabbilling
<Directory /var/www/ilabbilling>
    Options -Indexes
    AllowOverride None
    Require all granted
    DirectoryIndex dental_os.html
</Directory>

# API Proxy zu FastAPI
ProxyPass /billing/api http://127.0.0.1:8100/api
ProxyPassReverse /billing/api http://127.0.0.1:8100/api
CONF
    a2enconf billing 2>/dev/null || true
fi

systemctl reload apache2
echo "   OK"

# 6. Test
echo ""
echo "6. API Test..."
sleep 1
RESPONSE=$(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8100/api/kuerzel)
if [ "$RESPONSE" = "200" ]; then
    echo "   API antwortet mit HTTP 200 - ALLES OK!"
else
    echo "   WARNUNG: API antwortet mit HTTP $RESPONSE"
    echo "   Logs prüfen: journalctl -u dental-os -n 20"
fi

echo ""
echo "=== Setup abgeschlossen ==="
echo "API lokal: http://127.0.0.1:8100/api/kuerzel"
echo "API extern: https://www.ilabdashboard.com/billing/api/kuerzel"
