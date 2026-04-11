#!/usr/bin/env python3
"""
billing_prices.py — Preis-Loader & Praxis-Verwaltung
=====================================================
Zahntechnik Oliver Krieger, Nürnberg

Dieses Modul lädt Preise aus abrechnungslogik_preisgruppen.json
und stellt sie pro Praxis bereit.

Kernprinzip: Preise werden EXAKT so verwendet wie auf echten Rechnungen.
Kein Mitteln, kein Runden, kein Schätzen.

Preis-Hierarchie:
    1. Praxis-spezifischer Preis (aus echten Rechnungen dieser Praxis)
    2. Preisgruppen-Fallback (Median der Gruppe, falls Praxis keine Daten hat)
    3. None (kein Preis bekannt → muss manuell eingetragen werden)

2026er Preise haben Vorrang vor 2025er Preisen (bereits in der JSON so gespeichert).

Sonderfall Gazaev: Komplett separate Preise, nicht in Preisgruppen.

Verwendung:
    from billing_prices import PriceLoader
    loader = PriceLoader("abrechnungslogik_preisgruppen.json")

    # Preis für eine Position bei einer Praxis
    preis = loader.get_price("Röder u. Kollegen", "*5504")  # → 35.0

    # Alle Preise einer Praxis als Dict (für billing_engine.generate_invoice)
    preise = loader.get_praxis_prices("Röder u. Kollegen")  # → {"*5504": 35.0, ...}

    # Praxis normalisieren (Kurzname → offizieller Name)
    name = loader.normalize_praxis("Röder")  # → "Röder u. Kollegen"
"""

import json
import unicodedata
from typing import Dict, Optional, List, Tuple
from pathlib import Path
from collections import defaultdict


__version__ = "1.0"


# ============================================================================
# PRAXIS-MERGE (Kurzformen → offizieller Name)
# ============================================================================
PRAXIS_MERGE = {
    "MVZ Phönixsee": "MVZ Phönixsee",
    "Phönixsee": "MVZ Phönixsee",
    "Röder u. Kollegen": "Röder u. Kollegen",
    "Röder": "Röder u. Kollegen",
    "Paul Seemann": "Paul Seemann",
    "Seemann": "Paul Seemann",
    "Dr. Lex": "Dr. Lex",
    "Lex": "Dr. Lex",
    "Dr. Gabriele Schmidt": "Dr. Gabriele Schmidt",
    "Schmidt": "Dr. Gabriele Schmidt",
    "Dr. Schmidt": "Dr. Gabriele Schmidt",
    "Gabriele Schmidt": "Dr. Gabriele Schmidt",
    "Dr. Peter Krauß": "Dr. Peter Krauß",
    "Dr. Krauß": "Dr. Peter Krauß",
    "Krauss": "Dr. Peter Krauß",
    "Krauß": "Dr. Peter Krauß",
    "Martmöller u. Kollegen": "Martmöller u. Kollegen",
    "Martmöller": "Martmöller u. Kollegen",
    "Martmöller - Königsplatz": "Martmöller u. Kollegen",
    "Berns Dental": "Berns Dentaltechnik",
    "Berns": "Berns Dentaltechnik",
    "Das Hugo": "Das Hugo",
    "Dr. Susan Neuffer": "Dr. Susan Neuffer",
    "Neuffer": "Dr. Susan Neuffer",
    "Helm": "Helm",
    "Wojahn Zahnmedizin": "Wojahn Zahnmedizin",
    "Wojahn": "Wojahn Zahnmedizin",
    "Zahnärzte am Königsplatz": "Zahnärzte am Königsplatz",
    "Dr. Kersting": "Dr. Kersting",
    "Kersting": "Dr. Kersting",
    "Dr. Daut": "Dr. Daut",
    "Daut": "Dr. Daut",
}


def _nfc(s: str) -> str:
    """Unicode NFC-Normalisierung (wichtig für ö, ü, ß etc.)."""
    return unicodedata.normalize("NFC", s) if s else s


class PriceLoader:
    """Lädt und verwaltet Praxispreise aus der JSON-Datei."""

    def __init__(self, filepath: str = "abrechnungslogik_preisgruppen.json"):
        self.filepath = Path(filepath)
        self._data = self._load()
        self._praxis_preise = self._data.get("praxis_preislisten", {})
        self._praxis_zuordnung = self._data.get("praxis_zuordnung", {})
        self._preisgruppen = self._data.get("preisgruppen_definition", {})

        # Gruppen-Index aufbauen: Preisgruppe → [Praxen]
        self._gruppen_praxen: Dict[str, List[str]] = defaultdict(list)
        for praxis, info in self._praxis_zuordnung.items():
            gruppe = info.get("preisgruppe", "")
            if gruppe:
                self._gruppen_praxen[gruppe].append(praxis)

    def _load(self) -> Dict:
        """Lade JSON-Daten."""
        if not self.filepath.exists():
            raise FileNotFoundError(
                f"Preisdatei nicht gefunden: {self.filepath}\n"
                f"Erwartet: abrechnungslogik_preisgruppen.json im selben Verzeichnis."
            )
        with open(self.filepath, "r", encoding="utf-8") as f:
            return json.load(f)

    # ────────────────────────────────────────────────────────────────────
    # PRAXIS-NORMALISIERUNG
    # ────────────────────────────────────────────────────────────────────

    def normalize_praxis(self, name: str) -> str:
        """Normalisiere Praxisname auf den offiziellen Namen.

        Versucht:
        1. Exakter Match in PRAXIS_MERGE
        2. NFC-normalisierter Match
        3. Case-insensitiver Substring-Match
        4. Original zurückgeben wenn nichts passt
        """
        if not name:
            return name

        name_nfc = _nfc(name.strip())

        # 1. Exakt
        if name_nfc in PRAXIS_MERGE:
            return PRAXIS_MERGE[name_nfc]

        # 2. NFC-Match gegen alle Keys
        for key, val in PRAXIS_MERGE.items():
            if _nfc(key) == name_nfc:
                return val

        # 3. Case-insensitiver Match
        name_lower = name_nfc.lower()
        for key, val in PRAXIS_MERGE.items():
            if _nfc(key).lower() == name_lower:
                return val

        # 4. Substring (z.B. "Phönix" → "MVZ Phönixsee")
        for key, val in PRAXIS_MERGE.items():
            if name_lower in _nfc(key).lower() or _nfc(key).lower() in name_lower:
                return val

        return name_nfc

    # ────────────────────────────────────────────────────────────────────
    # PREIS-ABFRAGEN
    # ────────────────────────────────────────────────────────────────────

    def get_price(
        self,
        praxis: str,
        position: str,
        fallback_gruppe: bool = True,
    ) -> Optional[float]:
        """Hole den Preis für eine Position bei einer Praxis.

        Args:
            praxis: Praxisname (wird normalisiert)
            position: Positionsnummer (z.B. "*5504", "9330")
            fallback_gruppe: True = Fallback auf Gruppenmedian

        Returns:
            Preis als float, oder None wenn unbekannt.
        """
        praxis_norm = self.normalize_praxis(praxis)

        # 1. Praxis-spezifischer Preis
        if praxis_norm in self._praxis_preise:
            pos_data = self._praxis_preise[praxis_norm].get(position)
            if pos_data:
                return pos_data.get("preis")

        # 2. Preisgruppen-Fallback
        if fallback_gruppe:
            gruppe = self._get_preisgruppe(praxis_norm)
            if gruppe:
                return self._gruppen_median(gruppe, position)

        return None

    def get_praxis_prices(
        self,
        praxis: str,
        fallback_gruppe: bool = True,
    ) -> Dict[str, float]:
        """Hole ALLE Preise einer Praxis als Dict (Position → Preis).

        Ideal für: billing_engine.generate_invoice(praxis_preise=...)
        """
        praxis_norm = self.normalize_praxis(praxis)
        result = {}

        # Praxis-eigene Preise
        if praxis_norm in self._praxis_preise:
            for pos, data in self._praxis_preise[praxis_norm].items():
                preis = data.get("preis")
                if preis is not None:
                    result[pos] = preis

        # Gruppen-Fallback für fehlende Positionen
        if fallback_gruppe:
            gruppe = self._get_preisgruppe(praxis_norm)
            if gruppe:
                for praxis_name in self._gruppen_praxen.get(gruppe, []):
                    if praxis_name == praxis_norm:
                        continue
                    if praxis_name in self._praxis_preise:
                        for pos, data in self._praxis_preise[praxis_name].items():
                            if pos not in result:
                                preis = data.get("preis")
                                if preis is not None:
                                    result[pos] = preis

        return result

    def get_price_with_source(
        self,
        praxis: str,
        position: str,
    ) -> Tuple[Optional[float], str]:
        """Hole Preis MIT Quellenangabe.

        Returns:
            (preis, quelle) — quelle ist z.B. "praxis", "gruppe", "unbekannt"
        """
        praxis_norm = self.normalize_praxis(praxis)

        # 1. Praxis-spezifisch
        if praxis_norm in self._praxis_preise:
            pos_data = self._praxis_preise[praxis_norm].get(position)
            if pos_data:
                return pos_data.get("preis"), "praxis"

        # 2. Gruppe
        gruppe = self._get_preisgruppe(praxis_norm)
        if gruppe:
            median = self._gruppen_median(gruppe, position)
            if median is not None:
                return median, f"gruppe:{gruppe}"

        return None, "unbekannt"

    # ────────────────────────────────────────────────────────────────────
    # PRAXIS-INFO
    # ────────────────────────────────────────────────────────────────────

    def get_praxis_info(self, praxis: str) -> Optional[Dict]:
        """Hole Metadaten einer Praxis (Preisgruppe, Score, Umsatz etc.)."""
        praxis_norm = self.normalize_praxis(praxis)
        return self._praxis_zuordnung.get(praxis_norm)

    def list_praxen(self) -> List[str]:
        """Liste aller bekannten Praxen (normalisierte Namen)."""
        return sorted(self._praxis_zuordnung.keys())

    def list_preisgruppen(self) -> Dict[str, List[str]]:
        """Preisgruppen mit zugeordneten Praxen."""
        return dict(self._gruppen_praxen)

    # ────────────────────────────────────────────────────────────────────
    # PREIS-UPDATES (für Learning-System)
    # ────────────────────────────────────────────────────────────────────

    def update_price(
        self,
        praxis: str,
        position: str,
        neuer_preis: float,
        bezeichnung: Optional[str] = None,
    ):
        """Aktualisiere den Preis einer Position für eine Praxis.

        Wird vom Learning-System aufgerufen wenn Oliver einen Preis korrigiert.
        Speichert als quelle_jahr="korrektur" damit klar ist, dass es kein
        Original-Rechnungspreis ist.
        """
        praxis_norm = self.normalize_praxis(praxis)

        if praxis_norm not in self._praxis_preise:
            self._praxis_preise[praxis_norm] = {}

        existing = self._praxis_preise[praxis_norm].get(position, {})
        self._praxis_preise[praxis_norm][position] = {
            "preis": neuer_preis,
            "bezeichnung": bezeichnung or existing.get("bezeichnung", ""),
            "quelle_jahr": "korrektur",
            "anzahl_belege": existing.get("anzahl_belege", 0),
        }

    def save(self):
        """Speichere aktualisierte Preise zurück in die JSON-Datei."""
        with open(self.filepath, "w", encoding="utf-8") as f:
            json.dump(self._data, f, ensure_ascii=False, indent=2)

    # ────────────────────────────────────────────────────────────────────
    # INTERNE HILFSFUNKTIONEN
    # ────────────────────────────────────────────────────────────────────

    def _get_preisgruppe(self, praxis_norm: str) -> Optional[str]:
        """Finde Preisgruppe einer Praxis."""
        info = self._praxis_zuordnung.get(praxis_norm)
        if info:
            return info.get("preisgruppe")
        return None

    def _gruppen_median(self, gruppe: str, position: str) -> Optional[float]:
        """Berechne den Median-Preis einer Position innerhalb einer Preisgruppe."""
        preise = []
        for praxis_name in self._gruppen_praxen.get(gruppe, []):
            if praxis_name in self._praxis_preise:
                pos_data = self._praxis_preise[praxis_name].get(position)
                if pos_data and pos_data.get("preis") is not None:
                    preise.append(pos_data["preis"])

        if not preise:
            return None

        preise.sort()
        n = len(preise)
        if n % 2 == 1:
            return preise[n // 2]
        else:
            return (preise[n // 2 - 1] + preise[n // 2]) / 2


# ============================================================================
# STANDALONE TEST
# ============================================================================
if __name__ == "__main__":
    import sys

    print("=" * 60)
    print("billing_prices.py — Standalone-Test")
    print("=" * 60)

    # Suche JSON-Datei
    base = Path(__file__).parent
    json_path = base / "abrechnungslogik_preisgruppen.json"

    if not json_path.exists():
        print(f"\n✗ Datei nicht gefunden: {json_path}")
        print("  Bitte im selben Verzeichnis wie dieses Skript ablegen.")
        sys.exit(1)

    loader = PriceLoader(str(json_path))

    # 1. Praxis-Normalisierung
    print("\n1. Praxis-Normalisierung:")
    tests = ["Röder", "Phönixsee", "Dr. Krauß", "Seemann", "Berns"]
    for t in tests:
        print(f"   '{t}' → '{loader.normalize_praxis(t)}'")

    # 2. Bekannte Praxen
    print(f"\n2. Bekannte Praxen ({len(loader.list_praxen())}):")
    for p in loader.list_praxen():
        info = loader.get_praxis_info(p)
        gruppe = info.get("preisgruppe", "?") if info else "?"
        r2026 = info.get("rechnungen_2026", 0) if info else 0
        print(f"   {p:30s}  {gruppe:15s}  2026: {r2026} Rechnungen")

    # 3. Preise abfragen
    print("\n3. Preisabfragen:")
    test_pairs = [
        ("Röder u. Kollegen", "*5504"),
        ("Röder u. Kollegen", "*Z100"),
        ("Dr. Lex", "*5504"),
        ("Das Hugo", "*5003"),
        ("MVZ Phönixsee", "9330"),
    ]
    for praxis, pos in test_pairs:
        preis, quelle = loader.get_price_with_source(praxis, pos)
        preis_str = f"€{preis:.2f}" if preis is not None else "unbekannt"
        print(f"   {praxis:25s}  {pos:8s} → {preis_str:>10s}  ({quelle})")

    # 4. Preisgruppen
    print("\n4. Preisgruppen:")
    for gruppe, praxen in loader.list_preisgruppen().items():
        print(f"   {gruppe}: {', '.join(praxen)}")

    # 5. Vollständige Preisliste einer Praxis
    print("\n5. Top-10 Preise für 'Röder u. Kollegen':")
    preise = loader.get_praxis_prices("Röder u. Kollegen")
    for pos, preis in sorted(preise.items())[:10]:
        print(f"   {pos:8s} → €{preis:.2f}")

    print(f"\n   ... insgesamt {len(preise)} Positionen mit Preis")
    print(f"\n✓ Test abgeschlossen")
