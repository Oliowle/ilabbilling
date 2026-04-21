#!/bin/bash
#
# run_test.sh — One-Click-Test mit Baseline-Vergleich
# ====================================================
# Führt Verify lokal + gegen Live-API aus und vergleicht
# mit data/baseline.json.
#
# Verwendung:
#   bash run_test.sh                    # Standard-Test
#   bash run_test.sh --update-baseline  # Baseline auf neue Werte setzen
#   bash run_test.sh --skip-api         # Nur lokal testen
#

set -e
cd "$(dirname "$0")"

UPDATE_BASELINE=0
SKIP_API=0
API_URL="${API_URL:-https://www.ilabdashboard.com/billing/api}"

for arg in "$@"; do
    case $arg in
        --update-baseline) UPDATE_BASELINE=1 ;;
        --skip-api)        SKIP_API=1 ;;
        --api=*)           API_URL="${arg#*=}" ;;
    esac
done

echo "============================================================"
echo "  DENTAL OS — Self-Verification Test Runner"
echo "============================================================"
echo "  Datum:  $(date '+%Y-%m-%d %H:%M:%S')"
echo "  CSV:    $(python3 -c 'from verify_invoices import DEFAULT_CSV; print(DEFAULT_CSV)')"
echo

# ─── Lokaler Test (Abdruck) ─────────────────────────────────────
echo ">>> Lokal — Abdruck-Workflow"
LOCAL_ABDRUCK=$(python3 verify_invoices.py --abdruck --json 2>&1 | tail -n +3)
echo "$LOCAL_ABDRUCK"
LOCAL_ABDRUCK_RATE=$(echo "$LOCAL_ABDRUCK" | python3 -c "import json,sys; print(json.load(sys.stdin)['match_rate'])")
echo

# ─── Lokaler Test (Scan) ────────────────────────────────────────
echo ">>> Lokal — Scan-Workflow"
LOCAL_SCAN=$(python3 verify_invoices.py --json 2>&1 | tail -n +3)
echo "$LOCAL_SCAN"
LOCAL_SCAN_RATE=$(echo "$LOCAL_SCAN" | python3 -c "import json,sys; print(json.load(sys.stdin)['match_rate'])")
echo

# ─── Live-API ───────────────────────────────────────────────────
API_RATE="-"
if [ "$SKIP_API" -eq 0 ]; then
    echo ">>> Live-API ($API_URL/health)"
    API_HEALTH=$(curl -s --max-time 10 "$API_URL/health" || echo '{"status":"error"}')
    echo "$API_HEALTH" | python3 -m json.tool 2>/dev/null || echo "$API_HEALTH"
    API_RATE=$(echo "$API_HEALTH" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('match_rate', '-'))" 2>/dev/null || echo "-")
    echo
fi

# ─── Baseline-Vergleich ─────────────────────────────────────────
echo "============================================================"
echo "  BASELINE-VERGLEICH"
echo "============================================================"

python3 - <<PYEOF
import json
from pathlib import Path
baseline = json.loads(Path("data/baseline.json").read_text())

cur_abdruck = $LOCAL_ABDRUCK_RATE
cur_scan    = $LOCAL_SCAN_RATE
base_abdruck = baseline["abdruck"]["match_rate"]
base_scan    = baseline["scan"]["match_rate"]
min_rate     = baseline["min_acceptable_rate"]

def fmt(cur, base):
    diff = cur - base
    if diff > 0.01:
        return f"  {cur:6.2f}%  (Baseline: {base:6.2f}%, +{diff:.2f}%)  ✓ besser"
    if diff < -0.01:
        return f"  {cur:6.2f}%  (Baseline: {base:6.2f}%, {diff:.2f}%)  ✗ schlechter"
    return f"  {cur:6.2f}%  (Baseline: {base:6.2f}%, gleich)"

print(f"  Abdruck-Workflow: {fmt(cur_abdruck, base_abdruck)}")
print(f"  Scan-Workflow:    {fmt(cur_scan, base_scan)}")
print()

# Pass/Fail
fail = False
if cur_abdruck < min_rate:
    print(f"  ✗ FAIL — Abdruck-Rate {cur_abdruck:.2f}% < Mindest {min_rate}%")
    fail = True
if cur_abdruck < base_abdruck - 1.0:
    print(f"  ✗ FAIL — Abdruck-Regression: {cur_abdruck:.2f}% < {base_abdruck:.2f}% - 1.0%")
    fail = True

if not fail:
    print(f"  ✓ PASS — Match-Rate über Baseline")

if fail:
    exit(1)
PYEOF
RC=$?

# ─── Baseline aktualisieren ─────────────────────────────────────
if [ "$UPDATE_BASELINE" -eq 1 ]; then
    echo
    echo "  Aktualisiere Baseline auf aktuelle Werte..."
    python3 - <<PYEOF
import json
from pathlib import Path
from datetime import datetime

baseline_file = Path("data/baseline.json")
baseline = json.loads(baseline_file.read_text())

abdruck = json.loads('''$LOCAL_ABDRUCK''')
scan    = json.loads('''$LOCAL_SCAN''')

baseline["letzte_aktualisierung"] = datetime.now().isoformat(timespec="seconds")
baseline["abdruck"] = {k: abdruck[k] for k in ("match_rate", "qty_diffs", "missing", "extra")}
baseline["scan"]    = {k: scan[k]    for k in ("match_rate", "qty_diffs", "missing", "extra")}

baseline_file.write_text(json.dumps(baseline, indent=2, ensure_ascii=False))
print(f"  ✓ Baseline gespeichert: Abdruck={abdruck['match_rate']}%, Scan={scan['match_rate']}%")
PYEOF
fi

echo
exit $RC
