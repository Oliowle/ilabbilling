#!/usr/bin/env python3
"""
verify_invoices.py — Self-Verification Workflow
================================================
Vergleicht echte Rechnungen aus 2025 mit den von der Engine generierten
Positionen und Mengen. Zeigt die Trefferquote pro Position.

Verwendung:
    python verify_invoices.py [--api URL] [--csv PATH]

Standard nutzt die lokale Engine (kein API-Call).
Mit --api wird gegen die Live-API getestet.
"""

import csv
import json
import sys
import argparse
import urllib.request
import urllib.error
from pathlib import Path
from collections import defaultdict

from billing_engine import generate_invoice
from billing_prices import PriceLoader

DEFAULT_CSV = Path(__file__).parent.parent / "ANALYSIS_Bridge_Crown_Invoices_May_Sep_2025.csv"
DEFAULT_PRICES = Path(__file__).parent / "abrechnungslogik_preisgruppen.json"


def parse_csv(path: Path):
    """Parse die Rechnungs-CSV in eine Liste von Dicts."""
    invoices = []
    with open(path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            invoices.append(row)
    return invoices


def get_expected_positions(row):
    """Extrahiere die erwarteten Positionen + Mengen aus einer CSV-Zeile."""
    expected = {}
    mapping = {
        "qty_3000": "*3000",
        "qty_3002": "*3002",
        "qty_5504": "*5504",
        "qty_0301": "*0301",
        "qty_0600": "*0600",
        "qty_5500": "*5500",
    }
    for col, pos_nr in mapping.items():
        try:
            qty = float(row.get(col, 0) or 0)
            if qty > 0:
                expected[pos_nr] = int(qty) if qty == int(qty) else qty
        except (ValueError, TypeError):
            pass

    bool_cols = {
        "has_5500": "*5500",
        "has_0201": "*0201",
        "has_0202": "*0202",
        "has_0051": "*0051",
        "has_0001": "*0001",
        "has_3000": "*3000",
    }
    for col, pos_nr in bool_cols.items():
        if str(row.get(col, "")).lower() == "true" and pos_nr not in expected:
            expected[pos_nr] = 1

    return expected


def call_api(api_url, arbeitsart, praxis, abdruck):
    """POST gegen die Live-API."""
    payload = json.dumps({
        "arbeitsart": arbeitsart,
        "praxis": praxis,
        "kasse": False,
        "abdruck": abdruck,
        "gesichtsbogen": False,
    }).encode("utf-8")
    req = urllib.request.Request(
        f"{api_url.rstrip('/')}/generate",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))


def verify_single(row, loader, abdruck=True, api_url=None):
    """Verifiziere eine einzelne Rechnung."""
    arbeitsart = row.get("arbeitsart", "").strip()
    praxis = row.get("praxis", "").strip()

    if not arbeitsart or not praxis:
        return None

    praxis_norm = loader.normalize_praxis(praxis)

    try:
        if api_url:
            result = call_api(api_url, arbeitsart, praxis_norm, abdruck)
        else:
            praxis_preise = loader.get_praxis_prices(praxis_norm)
            result = generate_invoice(
                arbeitsart=arbeitsart,
                praxis=praxis_norm,
                kasse=False,
                abdruck=abdruck,
                gesichtsbogen=False,
                praxis_preise=praxis_preise,
            )
    except Exception as e:
        return {"error": str(e), "arbeitsart": arbeitsart, "praxis": praxis}

    generated = {p["nummer"]: p["menge"] for p in result["positionen"]}
    expected = get_expected_positions(row)

    matches = []
    qty_diffs = []
    missing = []
    extra = []

    for pos, exp_qty in expected.items():
        if pos in generated:
            gen_qty = generated[pos]
            if gen_qty == exp_qty:
                matches.append(pos)
            else:
                qty_diffs.append((pos, exp_qty, gen_qty))
        else:
            missing.append((pos, exp_qty))

    relevant_extras = ["*3000", "*3002", "*5500", "*5504", "*0001", "*0051", "*0201", "*0202", "*0301", "*0600"]
    for pos in relevant_extras:
        if pos in generated and pos not in expected:
            extra.append((pos, generated[pos]))

    return {
        "invoice_num": row.get("invoice_num"),
        "praxis": praxis,
        "arbeitsart": arbeitsart,
        "matches": matches,
        "qty_diffs": qty_diffs,
        "missing": missing,
        "extra": extra,
        "expected_count": len(expected),
        "generated_count": len(generated),
        "match_count": len(matches),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", default=str(DEFAULT_CSV))
    parser.add_argument("--prices", default=str(DEFAULT_PRICES))
    parser.add_argument("--limit", type=int, default=None, help="Nur N Rechnungen testen")
    parser.add_argument("--verbose", action="store_true", help="Details pro Rechnung")
    parser.add_argument("--abdruck", action="store_true", help="Abdruck-Workflow (default: Scan)")
    parser.add_argument("--api", default=None, help="Live-API URL (z.B. https://www.ilabdashboard.com/billing/api)")
    parser.add_argument("--json", action="store_true", help="Output als JSON")
    args = parser.parse_args()

    csv_path = Path(args.csv)
    if not csv_path.exists():
        print(f"FEHLER: CSV nicht gefunden: {csv_path}")
        sys.exit(1)

    print(f"Lade Rechnungen aus: {csv_path}")
    invoices = parse_csv(csv_path)
    if args.limit:
        invoices = invoices[: args.limit]
    print(f"  {len(invoices)} Rechnungen geladen\n")

    loader = PriceLoader(args.prices)

    results = []
    errors = []
    for inv in invoices:
        r = verify_single(inv, loader, abdruck=args.abdruck, api_url=args.api)
        if not r:
            continue
        if "error" in r:
            errors.append(r)
            continue
        results.append(r)

    total_expected = sum(r["expected_count"] for r in results)
    total_matches = sum(r["match_count"] for r in results)
    total_diffs = sum(len(r["qty_diffs"]) for r in results)
    total_missing = sum(len(r["missing"]) for r in results)
    total_extra = sum(len(r["extra"]) for r in results)

    if args.json:
        summary = {
            "source": args.api or "local",
            "workflow": "abdruck" if args.abdruck else "scan",
            "rechnungen": len(results),
            "expected": total_expected,
            "matches": total_matches,
            "match_rate": round(100 * total_matches / total_expected, 2) if total_expected else 0,
            "qty_diffs": total_diffs,
            "missing": total_missing,
            "extra": total_extra,
            "errors": len(errors),
        }
        print(json.dumps(summary, indent=2))
        sys.exit(0 if summary["match_rate"] >= 70 else 1)

    print("=" * 70)
    print(f"GESAMT-ERGEBNIS  ({'API: ' + args.api if args.api else 'LOKAL'})")
    print("=" * 70)
    print(f"  Rechnungen geprueft:  {len(results)}")
    print(f"  Erwartete Positionen: {total_expected}")
    print(f"  Korrekte Matches:     {total_matches}  ({100*total_matches/total_expected:.1f}%)")
    print(f"  Mengen-Abweichungen:  {total_diffs}")
    print(f"  Fehlende Positionen:  {total_missing}")
    print(f"  Extra Positionen:     {total_extra}  (in Engine, nicht in echter Rechnung)")
    print(f"  Parse-Fehler:         {len(errors)}")
    print()

    pos_stats = defaultdict(lambda: {"matches": 0, "diffs": 0, "missing": 0, "extra": 0})
    for r in results:
        for p in r["matches"]:
            pos_stats[p]["matches"] += 1
        for p, _, _ in r["qty_diffs"]:
            pos_stats[p]["diffs"] += 1
        for p, _ in r["missing"]:
            pos_stats[p]["missing"] += 1
        for p, _ in r["extra"]:
            pos_stats[p]["extra"] += 1

    print("=" * 70)
    print(f"DETAILS PRO POSITION")
    print("=" * 70)
    print(f"  {'Position':10s} {'OK':>5s} {'Mengen-Diff':>12s} {'Fehlt':>7s} {'Zuviel':>8s}")
    print(f"  {'-'*10} {'-'*5} {'-'*12} {'-'*7} {'-'*8}")
    for pos in sorted(pos_stats.keys()):
        s = pos_stats[pos]
        print(f"  {pos:10s} {s['matches']:>5d} {s['diffs']:>12d} {s['missing']:>7d} {s['extra']:>8d}")

    if args.verbose:
        print()
        print("=" * 70)
        print("PROBLEM-RECHNUNGEN (mit Abweichungen)")
        print("=" * 70)
        for r in results:
            problems = r["qty_diffs"] or r["missing"] or r["extra"]
            if not problems:
                continue
            print(f"\n  Rechnung #{r['invoice_num']} | {r['praxis']} | '{r['arbeitsart']}'")
            for pos, exp, gen in r["qty_diffs"]:
                print(f"    {pos}: erwartet x{exp}, generiert x{gen}")
            for pos, exp in r["missing"]:
                print(f"    {pos}: FEHLT (erwartet x{exp})")
            for pos, gen in r["extra"]:
                print(f"    {pos}: ZUVIEL (generiert x{gen}, nicht in echter Rechnung)")

    if errors:
        print()
        print("=" * 70)
        print(f"PARSE-FEHLER ({len(errors)})")
        print("=" * 70)
        for e in errors:
            print(f"  '{e['arbeitsart']}' ({e['praxis']}): {e['error']}")


if __name__ == "__main__":
    main()
