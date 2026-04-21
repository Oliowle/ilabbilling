#!/usr/bin/env python3
"""
auto_learn.py — Automatischer Lernregel-Generator
==================================================
Analysiert die Verify-Ergebnisse und schlägt Lernregeln vor, die
wiederkehrende Engine-Fehler korrigieren.

Workflow:
    1. Lädt die echten Rechnungen aus der CSV
    2. Generiert für jede Rechnung die Engine-Positionen
    3. Vergleicht erwartete vs. generierte Positionen
    4. Aggregiert Fehler nach (Kürzel × Position × Aktion)
    5. Generiert Lernregel-Vorschläge ab N Vorkommen
    6. Speichert sie in data/auto_korrekturen_pending.json
       ODER wendet sie direkt an (--apply)

Verwendung:
    python auto_learn.py                    # Vorschläge anzeigen
    python auto_learn.py --apply            # Direkt in korrekturen.json speichern
    python auto_learn.py --threshold 3      # Mindestens 3× Vorkommen (default: 5)
    python auto_learn.py --abdruck          # Abdruck-Workflow testen
"""

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from datetime import datetime

from billing_engine import generate_invoice, parse_arbeitsart, KNOWN_KUERZEL
from billing_prices import PriceLoader
from billing_learning import LearningStore
from verify_invoices import parse_csv, get_expected_positions, DEFAULT_CSV, DEFAULT_PRICES


PENDING_FILE = Path(__file__).parent / "data" / "auto_korrekturen_pending.json"
KORREKTUREN_FILE = Path(__file__).parent / "data" / "korrekturen.json"


def get_main_kuerzel(arbeitsart: str) -> str | None:
    """Extrahiere das Haupt-Kürzel aus der Arbeitsart-Zeile."""
    parsed = parse_arbeitsart(arbeitsart)
    for kuerzel, _ in parsed:
        if kuerzel in KNOWN_KUERZEL:
            return kuerzel
    return None


def analyze_invoices(csv_path: Path, prices_path: Path, abdruck: bool):
    """Vergleiche jede Rechnung und sammle Fehler-Statistiken.

    Returns:
        dict: {
            (kuerzel, position, aktion): {
                "count": int,
                "alter_wert_examples": [...],
                "neuer_wert_examples": [...],
                "rechnungen": [invoice_num, ...],
            }
        }
    """
    invoices = parse_csv(csv_path)
    loader = PriceLoader(str(prices_path))

    fehler = defaultdict(lambda: {
        "count": 0,
        "alter_wert_examples": [],
        "neuer_wert_examples": [],
        "rechnungen": [],
        "praxen": set(),
    })

    for inv in invoices:
        arbeitsart = inv.get("arbeitsart", "").strip()
        praxis = inv.get("praxis", "").strip()
        if not arbeitsart or not praxis:
            continue

        kuerzel = get_main_kuerzel(arbeitsart)
        if not kuerzel:
            continue

        praxis_norm = loader.normalize_praxis(praxis)
        try:
            praxis_preise = loader.get_praxis_prices(praxis_norm)
            result = generate_invoice(
                arbeitsart=arbeitsart,
                praxis=praxis_norm,
                kasse=False,
                abdruck=abdruck,
                gesichtsbogen=False,
                praxis_preise=praxis_preise,
            )
        except Exception:
            continue

        generated = {p["nummer"]: p["menge"] for p in result["positionen"]}
        expected = get_expected_positions(inv)

        relevant = ["*0001", "*0051", "*0201", "*0202", "*0301", "*0600", "*3000", "*3002", "*5500", "*5504"]

        for pos in relevant:
            exp_qty = expected.get(pos)
            gen_qty = generated.get(pos)
            invoice_num = inv.get("invoice_num", "?")

            if exp_qty is None and gen_qty is not None:
                # Engine generiert zuviel → entfernen
                key = (kuerzel, pos, "entfernen")
                fehler[key]["count"] += 1
                fehler[key]["alter_wert_examples"].append(gen_qty)
                fehler[key]["rechnungen"].append(invoice_num)
                fehler[key]["praxen"].add(praxis_norm)

            elif exp_qty is not None and gen_qty is None:
                # Engine generiert zu wenig → hinzufügen
                key = (kuerzel, pos, "hinzufuegen")
                fehler[key]["count"] += 1
                fehler[key]["neuer_wert_examples"].append(exp_qty)
                fehler[key]["rechnungen"].append(invoice_num)
                fehler[key]["praxen"].add(praxis_norm)

            elif exp_qty is not None and gen_qty is not None and exp_qty != gen_qty:
                # Falsche Menge
                key = (kuerzel, pos, "menge_aendern")
                fehler[key]["count"] += 1
                fehler[key]["alter_wert_examples"].append(gen_qty)
                fehler[key]["neuer_wert_examples"].append(exp_qty)
                fehler[key]["rechnungen"].append(invoice_num)
                fehler[key]["praxen"].add(praxis_norm)

    return fehler, len(invoices)


def most_common(values):
    """Gibt den häufigsten Wert in einer Liste zurück."""
    if not values:
        return None
    counts = defaultdict(int)
    for v in values:
        counts[v] += 1
    return max(counts.items(), key=lambda x: x[1])[0]


def build_suggestions(fehler: dict, threshold: int):
    """Konvertiere Fehler-Statistiken in Lernregel-Vorschläge."""
    suggestions = []
    for (kuerzel, position, aktion), data in fehler.items():
        if data["count"] < threshold:
            continue

        suggestion = {
            "kuerzel": kuerzel,
            "position": position,
            "aktion": aktion,
            "vorkommen": data["count"],
            "praxen_count": len(data["praxen"]),
            "rechnungen_sample": data["rechnungen"][:5],
            "erklaerung": f"Auto-erkannt: {data['count']}× in echten Rechnungen "
                          f"({len(data['praxen'])} Praxen)",
        }

        if aktion == "menge_aendern":
            suggestion["alter_wert"] = most_common(data["alter_wert_examples"])
            suggestion["neuer_wert"] = most_common(data["neuer_wert_examples"])
        elif aktion == "hinzufuegen":
            suggestion["neuer_wert"] = most_common(data["neuer_wert_examples"]) or 1
        elif aktion == "entfernen":
            suggestion["alter_wert"] = most_common(data["alter_wert_examples"])

        suggestions.append(suggestion)

    suggestions.sort(key=lambda x: -x["vorkommen"])
    return suggestions


def save_pending(suggestions, abdruck: bool, total_invoices: int):
    """Speichere Vorschläge in pending-Datei zur Review."""
    PENDING_FILE.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generiert_am": datetime.now().isoformat(timespec="seconds"),
        "workflow": "abdruck" if abdruck else "scan",
        "rechnungen_analysiert": total_invoices,
        "vorschlaege": suggestions,
    }
    with open(PENDING_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def apply_suggestions(suggestions, store_path: Path):
    """Wende Vorschläge direkt im LearningStore an."""
    store = LearningStore(str(store_path))
    angewandt = 0
    for s in suggestions:
        try:
            store.add_correction(
                kuerzel=s["kuerzel"],
                position=s["position"],
                aktion=s["aktion"],
                neuer_wert=s.get("neuer_wert"),
                alter_wert=s.get("alter_wert"),
                erklaerung=s["erklaerung"],
            )
            angewandt += 1
        except ValueError:
            continue
    return angewandt


def print_suggestions(suggestions, abdruck: bool, total_invoices: int):
    """Gibt Vorschläge tabellarisch aus."""
    print("=" * 76)
    print(f"AUTO-LERN-VORSCHLÄGE  (Workflow: {'Abdruck' if abdruck else 'Scan'}, "
          f"{total_invoices} Rechnungen analysiert)")
    print("=" * 76)
    if not suggestions:
        print("  Keine Vorschläge oberhalb des Schwellwerts.")
        return

    aktion_label = {
        "menge_aendern": "Menge ändern",
        "hinzufuegen":   "Hinzufügen   ",
        "entfernen":     "Entfernen    ",
    }

    print(f"  {'#':>3s}  {'Kürzel':>7s}  {'Pos':>7s}  {'Aktion':<14s} "
          f"{'Vorkommen':>10s}  {'Alt→Neu':<12s}  Praxen")
    print(f"  {'-'*3}  {'-'*7}  {'-'*7}  {'-'*14} {'-'*10}  {'-'*12}  {'-'*7}")

    for i, s in enumerate(suggestions, 1):
        alt = s.get("alter_wert", "-")
        neu = s.get("neuer_wert", "-")
        change = f"{alt} → {neu}"
        print(f"  {i:>3d}  {s['kuerzel']:>7s}  {s['position']:>7s}  "
              f"{aktion_label.get(s['aktion'], s['aktion']):<14s} "
              f"{s['vorkommen']:>10d}  {change:<12s}  {s['praxen_count']}")

    print()
    print("  → Speichere in:", PENDING_FILE)
    print("  → Übernehmen mit:  python auto_learn.py --apply")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", default=str(DEFAULT_CSV))
    parser.add_argument("--prices", default=str(DEFAULT_PRICES))
    parser.add_argument("--abdruck", action="store_true",
                        help="Abdruck-Workflow (default: Scan)")
    parser.add_argument("--threshold", type=int, default=5,
                        help="Mindestanzahl Vorkommen für Vorschlag (default: 5)")
    parser.add_argument("--apply", action="store_true",
                        help="Direkt in korrekturen.json speichern (sonst nur pending)")
    parser.add_argument("--store", default=str(KORREKTUREN_FILE),
                        help="Pfad zur korrekturen.json")
    args = parser.parse_args()

    csv_path = Path(args.csv)
    if not csv_path.exists():
        print(f"FEHLER: CSV nicht gefunden: {csv_path}")
        sys.exit(1)

    fehler, total = analyze_invoices(csv_path, Path(args.prices), args.abdruck)
    suggestions = build_suggestions(fehler, args.threshold)

    print_suggestions(suggestions, args.abdruck, total)

    save_pending(suggestions, args.abdruck, total)

    if args.apply and suggestions:
        n = apply_suggestions(suggestions, Path(args.store))
        print(f"\n  ✓ {n} Lernregeln in {args.store} gespeichert.")


if __name__ == "__main__":
    main()
