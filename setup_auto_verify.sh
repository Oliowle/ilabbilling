#!/bin/bash
# setup_auto_verify.sh — Einrichtung der täglichen Auto-Verification
# Wird einmal auf dem Server ausgeführt: sudo bash setup_auto_verify.sh

set -e

SYSTEMD_DIR="/etc/systemd/system"
SOURCE_DIR="/var/www/ilabbilling/systemd"
LOG_FILE="/var/log/dental-os-verify.log"

if [ "$EUID" -ne 0 ]; then
    echo "Bitte mit sudo ausführen: sudo bash $0"
    exit 1
fi

echo "=== Dental OS — Auto-Verify Setup ==="

echo "1. Log-Datei vorbereiten..."
touch "$LOG_FILE"
chmod 644 "$LOG_FILE"
echo "   OK ($LOG_FILE)"

echo "2. Systemd-Units installieren..."
cp "$SOURCE_DIR/dental-os-verify.service" "$SYSTEMD_DIR/"
cp "$SOURCE_DIR/dental-os-verify.timer"   "$SYSTEMD_DIR/"
echo "   OK"

echo "3. Systemd reload + Timer aktivieren..."
systemctl daemon-reload
systemctl enable dental-os-verify.timer
systemctl start dental-os-verify.timer
echo "   OK"

echo "4. Initialer Check..."
systemctl start dental-os-verify.service
sleep 3
echo "   OK"

echo
echo "=== Setup abgeschlossen ==="
echo "Timer-Status:    sudo systemctl status dental-os-verify.timer"
echo "Letzter Run:     sudo systemctl status dental-os-verify.service"
echo "Log:             tail -20 $LOG_FILE"
echo "Manuell starten: sudo systemctl start dental-os-verify.service"
echo
tail -5 "$LOG_FILE" 2>/dev/null || true
