#!/usr/bin/env python3
"""
billing_learning.py — Korrektursystem / Feedback-Loop
======================================================
Zahntechnik Oliver Krieger, Nürnberg

3-Schichten-Architektur:
    1. Base Rules   → billing_engine.py (KUERZEL_POS, fix, pro_zahn, etc.)
    2. Korrekturen  → diese Datei (JSON-basierte Overrides)
    3. Auto-Learning → TODO: Muster aus vielen Korrekturen erkennen

Wenn Oliver in der App eine generierte Rechnung korrigiert (Position
hinzufügen, entfernen, Menge ändern, Preis ändern), wird die Korrektur
als JSON gespeichert. Bei der nächsten ähnlichen Rechnung wird die
Korrektur automatisch angewandt.

Match-Logik:
    Eine Korrektur wird angewandt wenn ALLE Felder übereinstimmen:
    - kuerzel (z.B. "ZKV")
    - praxis (optional — wenn gesetzt, gilt nur für diese Praxis)
    - kasse (optional — wenn gesetzt, nur für Kasse/Privat)

    Praxis-spezifische Korrekturen haben Vorrang vor allgemeinen.

Verwendung:
    from billing_learning import LearningStore
    store = LearningStore("korrekturen.json")

    # Korrektur speichern
    store.add_correction({
        "kuerzel": "ZKV",
        "praxis": "Röder u. Kollegen",
        "position": "*5502",
        "aktion": "menge_aendern",      # oder: "hinzufuegen", "entfernen", "preis_aendern"
        "alter_wert": 2,
        "neuer_wert": 1,
        "erklaerung": "Bei Röder immer nur 1x Modellation",
    })

    # Korrekturen auf generierte Positionen anwenden
    positionen = store.apply_corrections(positionen, kuerzel="ZKV", praxis="Röder", kasse=False)
"""

import json
import os
from datetime import datetime
from typing import List, Dict, Optional
from pathlib import Path


__version__ = "1.0"


# ============================================================================
# KORREKTUR-AKTIONEN
# ============================================================================
AKTIONEN = {
    "hinzufuegen",     # Position wird hinzugefügt (fehlte in der Basis-Logik)
    "entfernen",       # Position wird entfernt (war in der Basis-Logik, gehört nicht rein)
    "menge_aendern",   # Menge einer Position wird geändert
    "preis_aendern",   # Preis einer Position wird geändert
    "kategorie_aendern",  # Position wechselt zwischen Leistung und Material
}


class LearningStore:
    """Verwaltet Korrekturen als JSON-Datei.

    Datei-Struktur:
    {
        "version": "1.0",
        "letzte_aenderung": "2026-04-11T14:30:00",
        "korrekturen": [
            {
                "id": 1,
                "datum": "2026-04-11T14:30:00",
                "kuerzel": "ZKV",
                "praxis": "Röder u. Kollegen",   # oder null für alle
                "kasse": null,                     # oder true/false
                "position": "*5502",
                "aktion": "menge_aendern",
                "alter_wert": 2,
                "neuer_wert": 1,
                "erklaerung": "Bei Röder immer nur 1x",
                "aktiv": true,
                "angewandt_count": 0
            },
            ...
        ]
    }
    """

    def __init__(self, filepath: str = "korrekturen.json"):
        self.filepath = Path(filepath)
        self.data = self._load()

    def _load(self) -> Dict:
        """Lade Korrekturen aus JSON, oder erstelle neue Datei."""
        if self.filepath.exists():
            with open(self.filepath, "r", encoding="utf-8") as f:
                return json.load(f)
        return {
            "version": __version__,
            "letzte_aenderung": None,
            "korrekturen": [],
        }

    def _save(self):
        """Speichere Korrekturen als JSON."""
        self.data["letzte_aenderung"] = datetime.now().isoformat(timespec="seconds")
        with open(self.filepath, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)

    @property
    def korrekturen(self) -> List[Dict]:
        return self.data.get("korrekturen", [])

    def _next_id(self) -> int:
        if not self.korrekturen:
            return 1
        return max(k.get("id", 0) for k in self.korrekturen) + 1

    # ────────────────────────────────────────────────────────────────────
    # KORREKTUR HINZUFÜGEN
    # ────────────────────────────────────────────────────────────────────

    def add_correction(
        self,
        kuerzel: str,
        position: str,
        aktion: str,
        neuer_wert=None,
        alter_wert=None,
        praxis: Optional[str] = None,
        kasse: Optional[bool] = None,
        erklaerung: str = "",
    ) -> Dict:
        """Speichere eine neue Korrektur.

        Args:
            kuerzel: Standardkürzel (z.B. "ZKV")
            position: BEB/BEL-Positionsnummer (z.B. "*5502")
            aktion: Eine aus AKTIONEN
            neuer_wert: Neuer Wert (Menge oder Preis)
            alter_wert: Bisheriger Wert (für Protokoll)
            praxis: Praxisname (None = gilt für alle Praxen)
            kasse: True/False/None (None = gilt für beide)
            erklaerung: Freitext-Erklärung von Oliver

        Returns:
            Die gespeicherte Korrektur als Dict.
        """
        if aktion not in AKTIONEN:
            raise ValueError(f"Unbekannte Aktion: {aktion}. Erlaubt: {AKTIONEN}")

        korrektur = {
            "id": self._next_id(),
            "datum": datetime.now().isoformat(timespec="seconds"),
            "kuerzel": kuerzel,
            "praxis": praxis,
            "kasse": kasse,
            "position": position,
            "aktion": aktion,
            "alter_wert": alter_wert,
            "neuer_wert": neuer_wert,
            "erklaerung": erklaerung,
            "aktiv": True,
            "angewandt_count": 0,
        }

        # Prüfe ob es eine identische aktive Korrektur gibt → ersetzen
        for i, existing in enumerate(self.korrekturen):
            if (existing.get("aktiv")
                    and existing["kuerzel"] == kuerzel
                    and existing["position"] == position
                    and existing["aktion"] == aktion
                    and existing.get("praxis") == praxis
                    and existing.get("kasse") == kasse):
                # Deaktiviere alte, behalte aber im Log
                self.korrekturen[i]["aktiv"] = False
                self.korrekturen[i]["ersetzt_durch"] = korrektur["id"]
                break

        self.korrekturen.append(korrektur)
        self._save()
        return korrektur

    # ────────────────────────────────────────────────────────────────────
    # KORREKTUREN ANWENDEN
    # ────────────────────────────────────────────────────────────────────

    def find_matching(
        self,
        kuerzel: str,
        praxis: Optional[str] = None,
        kasse: Optional[bool] = None,
    ) -> List[Dict]:
        """Finde alle aktiven Korrekturen die auf diesen Kontext passen.

        Reihenfolge (Priorität):
        1. Praxis-spezifisch + kasse-spezifisch
        2. Praxis-spezifisch + kasse=null
        3. Allgemein (praxis=null) + kasse-spezifisch
        4. Allgemein (praxis=null) + kasse=null

        Bei Konflikten gewinnt die spezifischere Korrektur.
        """
        matches = []
        for k in self.korrekturen:
            if not k.get("aktiv", True):
                continue
            if k["kuerzel"] != kuerzel:
                continue

            # Praxis-Filter
            k_praxis = k.get("praxis")
            if k_praxis is not None and k_praxis != praxis:
                continue

            # Kasse-Filter
            k_kasse = k.get("kasse")
            if k_kasse is not None and kasse is not None and k_kasse != kasse:
                continue

            # Spezifitätsscore berechnen
            score = 0
            if k_praxis is not None:
                score += 2  # Praxis-spezifisch = höhere Prio
            if k_kasse is not None:
                score += 1  # Kasse-spezifisch = etwas höhere Prio

            matches.append((score, k))

        # Sortiere nach Spezifität (höchste zuerst)
        matches.sort(key=lambda x: -x[0])

        # Dedupliziere: Pro Position+Aktion gewinnt die spezifischste
        seen = set()
        result = []
        for score, k in matches:
            key = (k["position"], k["aktion"])
            if key not in seen:
                seen.add(key)
                result.append(k)

        return result

    def apply_corrections(
        self,
        positionen: List[Dict],
        kuerzel: str,
        praxis: Optional[str] = None,
        kasse: Optional[bool] = None,
    ) -> List[Dict]:
        """Wende passende Korrekturen auf eine Positionsliste an.

        Args:
            positionen: Liste von {"nummer", "menge", "ist_pflicht", "preis"}
            kuerzel: Das Kürzel dieser Arbeit
            praxis: Praxisname
            kasse: True wenn Kassenrechnung

        Returns:
            Korrigierte Positionsliste (neues List-Objekt).
        """
        korrekturen = self.find_matching(kuerzel, praxis, kasse)
        if not korrekturen:
            return positionen  # Keine Korrekturen → unverändert

        # Arbeitskopie
        pos_dict = {p["nummer"]: dict(p) for p in positionen}

        for korr in korrekturen:
            pos_nr = korr["position"]
            aktion = korr["aktion"]

            if aktion == "entfernen":
                if pos_nr in pos_dict:
                    del pos_dict[pos_nr]
                    korr["angewandt_count"] = korr.get("angewandt_count", 0) + 1

            elif aktion == "hinzufuegen":
                if pos_nr not in pos_dict:
                    pos_dict[pos_nr] = {
                        "nummer": pos_nr,
                        "menge": korr.get("neuer_wert", 1) if isinstance(korr.get("neuer_wert"), (int, float)) else 1,
                        "ist_pflicht": 0,
                        "preis": None,
                    }
                    korr["angewandt_count"] = korr.get("angewandt_count", 0) + 1

            elif aktion == "menge_aendern":
                if pos_nr in pos_dict and korr.get("neuer_wert") is not None:
                    pos_dict[pos_nr]["menge"] = korr["neuer_wert"]
                    korr["angewandt_count"] = korr.get("angewandt_count", 0) + 1

            elif aktion == "preis_aendern":
                if pos_nr in pos_dict and korr.get("neuer_wert") is not None:
                    pos_dict[pos_nr]["preis"] = korr["neuer_wert"]
                    korr["angewandt_count"] = korr.get("angewandt_count", 0) + 1

            elif aktion == "kategorie_aendern":
                if pos_nr in pos_dict and korr.get("neuer_wert") in {"leistung", "material"}:
                    pos_dict[pos_nr]["kategorie"] = korr["neuer_wert"]
                    korr["angewandt_count"] = korr.get("angewandt_count", 0) + 1

        # Zähler speichern
        self._save()

        return sorted(pos_dict.values(), key=lambda x: x["nummer"])

    # ────────────────────────────────────────────────────────────────────
    # VERWALTUNG
    # ────────────────────────────────────────────────────────────────────

    def deactivate(self, korrektur_id: int):
        """Deaktiviere eine Korrektur (bleibt im Log)."""
        for k in self.korrekturen:
            if k["id"] == korrektur_id:
                k["aktiv"] = False
                self._save()
                return True
        return False

    def list_active(self, kuerzel: Optional[str] = None) -> List[Dict]:
        """Liste alle aktiven Korrekturen (optional gefiltert)."""
        result = []
        for k in self.korrekturen:
            if not k.get("aktiv", True):
                continue
            if kuerzel and k["kuerzel"] != kuerzel:
                continue
            result.append(k)
        return result

    def stats(self) -> Dict:
        """Statistiken über gespeicherte Korrekturen."""
        aktive = [k for k in self.korrekturen if k.get("aktiv", True)]
        inaktive = [k for k in self.korrekturen if not k.get("aktiv", True)]
        by_aktion = {}
        by_kuerzel = {}
        for k in aktive:
            a = k["aktion"]
            by_aktion[a] = by_aktion.get(a, 0) + 1
            kz = k["kuerzel"]
            by_kuerzel[kz] = by_kuerzel.get(kz, 0) + 1

        total_angewandt = sum(k.get("angewandt_count", 0) for k in aktive)

        return {
            "gesamt": len(self.korrekturen),
            "aktiv": len(aktive),
            "inaktiv": len(inaktive),
            "nach_aktion": by_aktion,
            "nach_kuerzel": by_kuerzel,
            "gesamt_angewandt": total_angewandt,
        }

    def export_for_engine_update(self) -> List[Dict]:
        """Exportiere häufig angewandte Korrekturen als Vorschläge
        für ein Update der Base Rules in billing_engine.py.

        Korrekturen die ≥5x angewandt wurden und allgemein sind
        (keine Praxis-Einschränkung) sind Kandidaten für Base Rules.
        """
        kandidaten = []
        for k in self.korrekturen:
            if not k.get("aktiv", True):
                continue
            if k.get("praxis") is not None:
                continue  # Praxis-spezifisch → bleibt hier
            if k.get("angewandt_count", 0) >= 5:
                kandidaten.append(k)
        return kandidaten


# ============================================================================
# STANDALONE TEST
# ============================================================================
if __name__ == "__main__":
    import tempfile

    print("=" * 60)
    print("billing_learning.py — Standalone-Test")
    print("=" * 60)

    # Temporäre Datei für den Test
    test_file = os.path.join(tempfile.gettempdir(), "test_korrekturen.json")
    store = LearningStore(test_file)

    # 1. Korrekturen hinzufügen
    print("\n1. Korrekturen hinzufügen:")

    k1 = store.add_correction(
        kuerzel="ZKV",
        position="*5502",
        aktion="menge_aendern",
        alter_wert=2,
        neuer_wert=1,
        erklaerung="Bei allen Praxen: Modellation immer nur 1x",
    )
    print(f"   → Korrektur #{k1['id']}: ZKV *5502 Menge 2→1 (allgemein)")

    k2 = store.add_correction(
        kuerzel="ZKV",
        position="*5502",
        aktion="menge_aendern",
        alter_wert=2,
        neuer_wert=3,
        praxis="Röder u. Kollegen",
        erklaerung="Bei Röder: 3x Modellation wegen Brücke",
    )
    print(f"   → Korrektur #{k2['id']}: ZKV *5502 Menge 2→3 (nur Röder)")

    k3 = store.add_correction(
        kuerzel="SCH",
        position="*0250",
        aktion="hinzufuegen",
        neuer_wert=1,
        erklaerung="SCH braucht immer *0250",
    )
    print(f"   → Korrektur #{k3['id']}: SCH +*0250 (allgemein)")

    # 2. Matching testen
    print("\n2. Matching testen:")

    # Röder → praxis-spezifische gewinnt
    matches_roeder = store.find_matching("ZKV", praxis="Röder u. Kollegen")
    print(f"   ZKV + Röder: {len(matches_roeder)} Korrekturen")
    for m in matches_roeder:
        print(f"     #{m['id']} {m['position']} {m['aktion']} → {m['neuer_wert']} (praxis={m.get('praxis', 'alle')})")

    # Andere Praxis → allgemeine gewinnt
    matches_lex = store.find_matching("ZKV", praxis="Dr. Lex")
    print(f"   ZKV + Dr. Lex: {len(matches_lex)} Korrekturen")
    for m in matches_lex:
        print(f"     #{m['id']} {m['position']} {m['aktion']} → {m['neuer_wert']} (praxis={m.get('praxis', 'alle')})")

    # 3. Korrekturen anwenden
    print("\n3. Korrekturen anwenden:")
    test_positionen = [
        {"nummer": "*5504", "menge": 2, "ist_pflicht": 1, "preis": 35.0},
        {"nummer": "*5502", "menge": 2, "ist_pflicht": 0, "preis": 45.0},
        {"nummer": "*0301", "menge": 1, "ist_pflicht": 1, "preis": 4.5},
    ]

    korrigiert = store.apply_corrections(test_positionen, "ZKV", praxis="Röder u. Kollegen")
    print(f"   Vorher: *5502 Menge={test_positionen[1]['menge']}")
    korr_5502 = next((p for p in korrigiert if p["nummer"] == "*5502"), None)
    print(f"   Nachher (Röder): *5502 Menge={korr_5502['menge'] if korr_5502 else 'entfernt'}")

    korrigiert2 = store.apply_corrections(test_positionen, "ZKV", praxis="Dr. Lex")
    korr2_5502 = next((p for p in korrigiert2 if p["nummer"] == "*5502"), None)
    print(f"   Nachher (Dr. Lex): *5502 Menge={korr2_5502['menge'] if korr2_5502 else 'entfernt'}")

    # 4. Statistik
    print("\n4. Statistik:")
    s = store.stats()
    print(f"   Gesamt: {s['gesamt']}, Aktiv: {s['aktiv']}, Angewandt: {s['gesamt_angewandt']}x")
    print(f"   Nach Aktion: {s['nach_aktion']}")
    print(f"   Nach Kürzel: {s['nach_kuerzel']}")

    # Aufräumen
    os.remove(test_file)
    print(f"\n✓ Test abgeschlossen (Temp-Datei gelöscht)")
