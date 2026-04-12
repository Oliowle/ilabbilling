#!/usr/bin/env python3
"""
billing_engine.py — Kern-Logik der Abrechnungsintelligenz
=========================================================
Zahntechnik Oliver Krieger, Nürnberg

Dieses Modul enthält:
- KUERZEL_POS: Welche BEB/BEL-Positionen gehören zu welchem Kürzel
- KUERZEL_ALIAS: Alte Schreibweisen → einheitliche Kürzel
- Parser für Arbeitsart-Zeilen (Zähne + Kürzel)
- FDI-Zahnbogen-Parser (Bereiche wie "15-23" korrekt auflösen)
- Positions-Generator (Kürzel + Zähne → vollständige Positionsliste)
- Kasse-Erkennung

Datengrundlage: 501 Rechnungen (Jan 2025 – Feb 2026), ~€525K Umsatz
Testgenauigkeit v4: 95.1% Positionen, 87.3% Preise, 87.0% Mengen

Verwendung:
    from billing_engine import generate_invoice
    result = generate_invoice("11,21 ZKV; 25 ZBR", praxis="Röder u. Kollegen")
"""

import re
from collections import defaultdict
from typing import List, Dict, Tuple, Optional

__version__ = "4.0"

# ============================================================================
# KÜRZEL-ALIAS: Alte Schreibweisen → einheitliche Kürzel
# ============================================================================
# Wenn du ein neues Kürzel einführst, trage es hier NICHT ein.
# Hier stehen nur ALTE Varianten, die auf das Standardkürzel gemappt werden.

KUERZEL_ALIAS = {
    # Kronen
    "ZKM": "ZKV", "ZBM": "ZKV", "KM": "ZKV",
    "K": "ZK", "K Zi": "ZK", "K ZI": "ZK", "K zi": "ZK",
    "Zi K": "ZK", "Zi Krone": "ZK", "Krone": "ZK",
    "MK Zirkon": "ZKV",
    "K Emax": "EMX", "K EMax": "EMX", "K emax": "EMX", "Emax": "EMX",
    "Lithium-Disilikat Kronen": "EMX",
    "PKV": "PK", "PKM": "PK",
    "V": "VEN", "Veneer": "VEN", "Veneers": "VEN",
    "Inl.": "INL", "Inl": "INL", "INL.": "INL",
    "ZB": "ZBR",
    "TK": "TKR",
    # Implantate
    "IMPL": "SKM",
    "Impl. Kronen vollverbl., verblockt": "SKM",
    "Impl.Kronen vollverbl., verblockt": "SKM",
    "Implantat Provisorium": "SKM",
    # Schienen
    "Adjust. Schiene": "SCH",
    "Adjust.Schiene": "SCH",
    "Adjustierte Aufbisschiene": "SCH",
    "Adjustierte Aufbissschiene": "SCH",
    "Aufbissschiene": "SCH",
    "SCH Schnarcherschiene": "SCHS",
    "Schnarcherschiene": "SCHS",
    "Miniplastschiene": "MINI",
    "Jig-Schiene": "JIG",
    "Jig Schiene": "JIG",
    "Sportschutzschiene": "SPORT",
    # Planung/Design
    "Smile Design, Flowable Injection": "SMIL",
    "Digitales SmileDesign": "SMIL",
    "SmileDesign": "SMIL",
    "Smile Design": "SMIL",
    "Flowable Inj.": "SMIL",
    "Flowable Injection": "SMIL",
    "WaxUp": "MOCK", "Waxup": "MOCK", "Wax Up": "MOCK",
    "MockUp": "MOCK", "Mockup": "MOCK", "Mock up": "MOCK",
    "WaxUp, MockUp": "MOCK",
    "MockUp Einprobe": "MOCK",
    # Sonstige
    "LZP": "LZP",
    "LZPB": "LZP",
    "Zirkonkäppchen": "ZKAP",
    "GB": "GB",
    "Gesichtsbogen": "GB",
    "Zeramex": "_SKIP",
    "Interimsprothese": "INT",
    "Interims": "INT",
    "Münchner Konzept": "MUE",
    "3D-Modelle": "3DM",
    "3D Modelle": "3DM",
    "Modell 3D": "3DM",
    "Digitale Planung & Konstruktion": "DPK",
    "Funktionsanalyse": "FAL",
    "Kiefergelenkanalyse": "FAL",
    "Unterfütterung": "UFT",
}

# ============================================================================
# KUERZEL_POS — Positionen MIT korrektem Prefix
# ============================================================================
# Format: (kuerzel, position_mit_prefix, ist_pflicht, standard_menge, mengen_formel, bedingung)
#
# Regeln:
# - BEB-Positionen: mit * Prefix (z.B. "*3002")
# - BEL-Positionen: ohne * Prefix (z.B. "9330")
# - ist_pflicht=1: Position erscheint auf ≥70% der Rechnungen dieses Kürzel-Typs
# - ist_pflicht=0: Position erscheint auf <70% (optional)
# - mengen_formel: "fix" = feste Menge, "pro_zahn" = Menge × Anzahl Zähne
# - bedingung: None, "kasse", "privat", "gesichtsbogen", "kein_gb_privat"
#
# Datengrundlage: 79 Rechnungen aus 2026, analysiert mit analyse_fehlend.py
# ============================================================================

KUERZEL_POS = [
    # ─── ZK — Zirkonkrone vollanatomisch ──────────────────────────────────
    ("ZK", "*0001", 1, 1, "fix", None),
    ("ZK", "*0301", 1, 1, "fix", None),
    ("ZK", "*3002", 1, 1, "pro_zahn", None),
    ("ZK", "*5504", 1, 1, "pro_zahn", None),
    ("ZK", "*5602", 1, 1, "pro_zahn", None),
    ("ZK", "*5603", 1, 1, "pro_zahn", None),
    ("ZK", "*5604", 1, 1, "pro_zahn", None),
    ("ZK", "*Z100", 1, 1, "pro_zahn", None),
    ("ZK", "*0600", 1, 1, "pro_zahn", None),
    ("ZK", "*9022", 0, 1, "fix", None),
    ("ZK", "*9025", 0, 2, "fix", None),
    ("ZK", "*9027", 0, 1, "pro_zahn", None),
    ("ZK", "*9030", 0, 1, "fix", None),
    ("ZK", "*8000", 0, 2, "fix", "privat"),
    ("ZK", "9330", 0, 2, "fix", "kasse"),
    ("ZK", "*0010", 0, 1, "fix", "kein_gb_privat"),
    ("ZK", "*0051", 0, 1, "fix", "gesichtsbogen"),
    ("ZK", "*0200", 0, 1, "fix", "gesichtsbogen"),
    ("ZK", "*0201", 0, 1, "fix", None),
    ("ZK", "*0202", 0, 1, "fix", None),
    ("ZK", "*9100", 0, 1, "fix", "privat"),

    # ─── ZKV — Zirkonkrone mit Verblendung ────────────────────────────────
    ("ZKV", "*0001", 1, 1, "fix", None),
    ("ZKV", "*0301", 1, 1, "fix", None),
    ("ZKV", "*0600", 1, 1, "pro_zahn", None),
    ("ZKV", "*5504", 1, 1, "pro_zahn", None),
    ("ZKV", "*5603", 1, 1, "pro_zahn", None),
    ("ZKV", "*5604", 1, 1, "pro_zahn", None),
    ("ZKV", "*Z100", 1, 1, "pro_zahn", None),
    ("ZKV", "*5500", 1, 1, "pro_zahn", None),
    ("ZKV", "*3000", 1, 1, "pro_zahn", None),
    ("ZKV", "*0201", 1, 1, "fix", None),
    ("ZKV", "*0202", 1, 1, "fix", None),
    ("ZKV", "*0051", 0, 1, "fix", None),
    ("ZKV", "*5602", 0, 1, "pro_zahn", None),
    ("ZKV", "*5601", 0, 1, "pro_zahn", None),
    ("ZKV", "*8000", 0, 2, "fix", "privat"),
    ("ZKV", "*0012", 0, 1, "fix", None),
    ("ZKV", "*5502", 0, 1, "fix", None),
    ("ZKV", "9330", 0, 2, "fix", "kasse"),
    ("ZKV", "*0010", 0, 1, "fix", "kein_gb_privat"),
    ("ZKV", "*0014", 0, 1, "fix", None),
    ("ZKV", "*9025", 0, 2, "fix", None),
    ("ZKV", "*9030", 0, 1, "fix", None),
    ("ZKV", "*9027", 0, 1, "pro_zahn", None),
    ("ZKV", "*9022", 0, 1, "fix", None),
    ("ZKV", "*0016", 0, 1, "fix", None),
    ("ZKV", "*9100", 0, 1, "fix", "privat"),
    ("ZKV", "*0200", 0, 1, "fix", "gesichtsbogen"),

    # ─── PK — Presskeramik ────────────────────────────────────────────────
    ("PK", "*0001", 1, 1, "fix", None),
    ("PK", "*0301", 1, 1, "fix", None),
    ("PK", "*5504", 1, 1, "pro_zahn", None),
    ("PK", "*5603", 1, 1, "pro_zahn", None),
    ("PK", "*5604", 1, 1, "pro_zahn", None),
    ("PK", "*5003", 1, 1, "pro_zahn", None),
    ("PK", "*5602", 1, 1, "pro_zahn", None),
    ("PK", "*E001", 1, 1, "pro_zahn", None),
    ("PK", "*9025", 0, 2, "fix", None),
    ("PK", "*9027", 0, 1, "pro_zahn", None),
    ("PK", "*9030", 0, 1, "fix", None),
    ("PK", "*8000", 0, 2, "fix", "privat"),
    ("PK", "*0201", 0, 1, "fix", None),
    ("PK", "*0202", 0, 1, "fix", None),
    ("PK", "*5001", 0, 1, "pro_zahn", None),
    ("PK", "*5500", 0, 1, "pro_zahn", None),
    ("PK", "*5601", 0, 1, "pro_zahn", None),
    ("PK", "*0600", 0, 1, "pro_zahn", None),
    ("PK", "*9022", 0, 1, "fix", None),
    ("PK", "9330", 0, 2, "fix", "kasse"),
    ("PK", "*0010", 0, 1, "fix", "kein_gb_privat"),
    ("PK", "*0051", 0, 1, "fix", "gesichtsbogen"),
    ("PK", "*0200", 0, 1, "fix", "gesichtsbogen"),
    ("PK", "*E060", 0, 1, "pro_zahn", None),

    # ─── SKM — Suprakonstruktion / Implantat ──────────────────────────────
    ("SKM", "*0001", 1, 1, "fix", None),
    ("SKM", "*0070", 1, 1, "fix", None),
    ("SKM", "*0301", 1, 1, "fix", None),
    ("SKM", "*1000", 1, 1, "pro_zahn", None),
    ("SKM", "*1010", 1, 1, "pro_zahn", None),
    ("SKM", "*1011", 1, 1, "pro_zahn", None),
    ("SKM", "*5504", 1, 1, "pro_zahn", None),
    ("SKM", "*5603", 1, 1, "pro_zahn", None),
    ("SKM", "*5604", 1, 1, "pro_zahn", None),
    ("SKM", "*I614", 1, 1, "pro_zahn", None),
    ("SKM", "*5602", 1, 1, "pro_zahn", None),
    ("SKM", "*Z100", 1, 1, "pro_zahn", None),
    ("SKM", "*I201", 1, 1, "pro_zahn", None),
    ("SKM", "9330", 1, 2, "fix", "kasse"),
    ("SKM", "*0016", 0, 1, "fix", None),
    ("SKM", "*0600", 0, 1, "pro_zahn", None),
    ("SKM", "*9025", 0, 2, "fix", None),
    ("SKM", "*9030", 0, 1, "fix", None),
    ("SKM", "*3003", 0, 1, "pro_zahn", None),
    ("SKM", "*5500", 0, 1, "pro_zahn", None),
    ("SKM", "*9024", 0, 1, "fix", None),
    ("SKM", "*0201", 0, 1, "fix", None),
    ("SKM", "*0202", 0, 1, "fix", None),
    ("SKM", "*9022", 0, 1, "fix", None),
    ("SKM", "*3002", 0, 1, "pro_zahn", None),
    ("SKM", "*0030", 0, 1, "fix", None),
    ("SKM", "*I200", 0, 1, "pro_zahn", None),
    ("SKM", "*0051", 0, 1, "fix", "gesichtsbogen"),
    ("SKM", "*0010", 0, 1, "fix", "kein_gb_privat"),
    ("SKM", "*8000", 0, 2, "fix", "privat"),
    ("SKM", "*0200", 0, 1, "fix", "gesichtsbogen"),
    ("SKM", "*9100", 0, 1, "fix", "privat"),

    # ─── EMX — E.Max / Lithium-Disilikat ──────────────────────────────────
    ("EMX", "*0001", 1, 1, "fix", None),
    ("EMX", "*0301", 1, 1, "fix", None),
    ("EMX", "*0600", 1, 1, "pro_zahn", None),
    ("EMX", "*5001", 1, 1, "pro_zahn", None),
    ("EMX", "*5500", 1, 1, "pro_zahn", None),
    ("EMX", "*5504", 1, 1, "pro_zahn", None),
    ("EMX", "*5601", 1, 1, "pro_zahn", None),
    ("EMX", "*5603", 1, 1, "pro_zahn", None),
    ("EMX", "*5604", 1, 1, "pro_zahn", None),
    ("EMX", "*E001", 1, 1, "pro_zahn", None),
    ("EMX", "*8000", 0, 2, "fix", None),
    ("EMX", "*9022", 0, 1, "fix", None),
    ("EMX", "*9025", 0, 2, "fix", None),
    ("EMX", "*9027", 0, 1, "pro_zahn", None),
    ("EMX", "*9030", 0, 1, "fix", None),
    ("EMX", "*0201", 0, 1, "fix", None),
    ("EMX", "*0010", 0, 1, "fix", "kein_gb_privat"),
    ("EMX", "*0051", 0, 1, "fix", "gesichtsbogen"),
    ("EMX", "*0200", 0, 1, "fix", "gesichtsbogen"),

    # ─── VEN — Veneer ─────────────────────────────────────────────────────
    ("VEN", "*0001", 1, 1, "fix", None),
    ("VEN", "*0301", 1, 1, "fix", None),
    ("VEN", "*5001", 1, 1, "pro_zahn", None),
    ("VEN", "*5500", 1, 1, "pro_zahn", None),
    ("VEN", "*5504", 1, 1, "pro_zahn", None),
    ("VEN", "*5601", 1, 1, "pro_zahn", None),
    ("VEN", "*5602", 1, 1, "pro_zahn", None),
    ("VEN", "*5603", 1, 1, "pro_zahn", None),
    ("VEN", "*5604", 1, 1, "pro_zahn", None),
    ("VEN", "*E001", 1, 1, "pro_zahn", None),
    ("VEN", "*Z100", 0, 1, "pro_zahn", None),
    ("VEN", "*0600", 0, 1, "pro_zahn", None),
    ("VEN", "*8000", 0, 2, "fix", None),
    ("VEN", "*9022", 0, 1, "fix", None),
    ("VEN", "*9025", 0, 2, "fix", None),
    ("VEN", "*9027", 0, 1, "pro_zahn", None),
    ("VEN", "*9030", 0, 1, "fix", None),
    ("VEN", "*0201", 0, 1, "fix", None),
    ("VEN", "*0202", 0, 1, "fix", None),
    ("VEN", "*0010", 0, 1, "fix", "kein_gb_privat"),
    ("VEN", "*0051", 0, 1, "fix", "gesichtsbogen"),
    ("VEN", "*0200", 0, 1, "fix", "gesichtsbogen"),

    # ─── INL — Inlay ──────────────────────────────────────────────────────
    ("INL", "*0001", 1, 1, "fix", None),
    ("INL", "*0301", 1, 1, "fix", None),
    ("INL", "*5200", 1, 1, "pro_zahn", None),
    ("INL", "*5003", 1, 1, "pro_zahn", None),
    ("INL", "*5504", 1, 1, "pro_zahn", None),
    ("INL", "*5602", 1, 1, "pro_zahn", None),
    ("INL", "*5603", 1, 1, "pro_zahn", None),
    ("INL", "*5604", 1, 1, "pro_zahn", None),
    ("INL", "*E001", 1, 1, "pro_zahn", None),
    ("INL", "*9030", 1, 1, "fix", None),
    ("INL", "*8000", 0, 2, "fix", None),
    ("INL", "*9022", 0, 1, "fix", None),
    ("INL", "*9025", 0, 2, "fix", None),
    ("INL", "*9027", 0, 1, "pro_zahn", None),
    ("INL", "*0201", 0, 1, "fix", None),
    ("INL", "*0202", 0, 1, "fix", None),
    ("INL", "*0010", 0, 1, "fix", "kein_gb_privat"),
    ("INL", "*0051", 0, 1, "fix", "gesichtsbogen"),
    ("INL", "*0200", 0, 1, "fix", "gesichtsbogen"),

    # ─── TKR — Teilkrone ──────────────────────────────────────────────────
    ("TKR", "*0001", 1, 1, "fix", None),
    ("TKR", "*0301", 1, 1, "fix", None),
    ("TKR", "*5001", 1, 1, "pro_zahn", None),
    ("TKR", "*5500", 1, 1, "pro_zahn", None),
    ("TKR", "*5504", 1, 1, "pro_zahn", None),
    ("TKR", "*5601", 1, 1, "pro_zahn", None),
    ("TKR", "*5602", 1, 1, "pro_zahn", None),
    ("TKR", "*5603", 1, 1, "pro_zahn", None),
    ("TKR", "*5604", 1, 1, "pro_zahn", None),
    ("TKR", "*E001", 1, 1, "pro_zahn", None),
    ("TKR", "*Z100", 0, 1, "pro_zahn", None),
    ("TKR", "*9022", 0, 1, "fix", None),
    ("TKR", "*9025", 0, 2, "fix", None),
    ("TKR", "*9027", 0, 1, "pro_zahn", None),
    ("TKR", "*9030", 0, 1, "fix", None),
    ("TKR", "*8000", 0, 2, "fix", None),

    # ─── ZBR — Zirkon-Brücke (Brückenglied) ──────────────────────────────
    ("ZBR", "*0001", 1, 1, "fix", None),
    ("ZBR", "*0301", 1, 1, "fix", None),
    ("ZBR", "*3000", 1, 1, "pro_zahn", None),
    ("ZBR", "*5500", 1, 1, "pro_zahn", None),
    ("ZBR", "*5504", 1, 1, "pro_zahn", None),
    ("ZBR", "*5601", 1, 1, "pro_zahn", None),
    ("ZBR", "*5602", 1, 1, "pro_zahn", None),
    ("ZBR", "*5603", 1, 1, "pro_zahn", None),
    ("ZBR", "*5604", 1, 1, "pro_zahn", None),
    ("ZBR", "*Z100", 1, 1, "pro_zahn", None),
    ("ZBR", "*I614", 0, 1, "pro_zahn", None),
    ("ZBR", "*0600", 0, 1, "pro_zahn", None),
    ("ZBR", "*8000", 0, 2, "fix", None),
    ("ZBR", "*9022", 0, 1, "fix", None),
    ("ZBR", "*9025", 0, 2, "fix", None),
    ("ZBR", "*0201", 0, 1, "fix", None),
    ("ZBR", "*0202", 0, 1, "fix", None),

    # ─── LZP — Langzeitprovisorium ────────────────────────────────────────
    ("LZP", "*0001", 1, 1, "fix", None),
    ("LZP", "*0600", 1, 1, "pro_zahn", None),
    ("LZP", "*0805", 1, 1, "pro_zahn", None),
    ("LZP", "*8000", 0, 2, "fix", None),
    ("LZP", "*9022", 0, 1, "fix", None),
    ("LZP", "*9025", 0, 2, "fix", None),
    ("LZP", "*9027", 0, 1, "pro_zahn", None),
    ("LZP", "*9030", 0, 1, "fix", None),

    # ─── SCH — Aufbissschiene ─────────────────────────────────────────────
    ("SCH", "*0001", 1, 1, "fix", "privat"),
    ("SCH", "*0250", 1, 1, "fix", "privat"),
    ("SCH", "*0850", 1, 1, "fix", "privat"),
    ("SCH", "*0851", 1, 2, "fix", "privat"),
    ("SCH", "*9022", 0, 1, "fix", None),
    ("SCH", "*9025", 0, 2, "fix", None),
    ("SCH", "*8000", 0, 1, "fix", "privat"),
    ("SCH", "*0207", 0, 1, "fix", "privat"),
    ("SCH", "*9032", 0, 1, "fix", None),
    ("SCH", "*S405", 0, 1, "fix", "privat"),
    ("SCH", "*0010", 0, 1, "fix", "kein_gb_privat"),
    ("SCH", "*0200", 0, 1, "fix", "gesichtsbogen"),
    ("SCH", "*0201", 0, 1, "fix", "gesichtsbogen"),
    ("SCH", "*0202", 0, 1, "fix", "gesichtsbogen"),
    # Kasse
    ("SCH", "4010", 1, 1, "fix", "kasse"),
    ("SCH", "7100", 1, 2, "fix", "kasse"),
    ("SCH", "9330", 1, 2, "fix", "kasse"),
    ("SCH", "0120", 0, 1, "fix", "kasse"),
    ("SCH", "0010", 0, 1, "fix", "kasse"),
    ("SCH", "0021", 0, 1, "fix", "kasse"),

    # ─── SCHS — Schnarcherschiene (immer BEL) ────────────────────────────
    ("SCHS", "0125", 1, 1, "fix", None),
    ("SCHS", "1003", 1, 1, "fix", None),
    ("SCHS", "5010", 1, 1, "fix", None),
    ("SCHS", "5100", 1, 2, "fix", None),
    ("SCHS", "5110", 1, 1, "fix", None),
    ("SCHS", "5200", 1, 4, "fix", None),
    ("SCHS", "9335", 1, 2, "fix", None),

    # ─── MOCK — WaxUp/MockUp ─────────────────────────────────────────────
    ("MOCK", "*0001", 1, 1, "fix", None),
    ("MOCK", "*0600", 1, 1, "pro_zahn", None),
    ("MOCK", "*0611", 1, 2, "fix", None),
    ("MOCK", "*0501", 1, 1, "fix", None),
    ("MOCK", "*9022", 0, 1, "fix", None),
    ("MOCK", "*8000", 0, 2, "fix", "privat"),
    ("MOCK", "9330", 0, 2, "fix", "kasse"),

    # ─── SMIL — SmileDesign ───────────────────────────────────────────────
    ("SMIL", "*0001", 1, 1, "fix", None),
    ("SMIL", "*0600", 1, 1, "pro_zahn", None),
    ("SMIL", "*0804", 1, 1, "fix", None),
    ("SMIL", "*0611", 1, 2, "fix", None),
    ("SMIL", "*0501", 1, 1, "fix", None),
    ("SMIL", "*9022", 0, 1, "fix", None),
    ("SMIL", "*8000", 0, 2, "fix", None),
    ("SMIL", "*9025", 0, 2, "fix", None),

    # ─── MINI — Miniplastschiene (Kasse) ──────────────────────────────────
    ("MINI", "4021", 1, 1, "fix", None),
    ("MINI", "9330", 1, 2, "fix", None),

    # ─── JIG — Jig-Schiene ───────────────────────────────────────────────
    ("JIG", "*0001", 1, 1, "fix", None),
    ("JIG", "*0250", 1, 1, "fix", None),
    ("JIG", "*9022", 0, 1, "fix", None),
    ("JIG", "*9025", 0, 2, "fix", None),
    ("JIG", "*8000", 0, 1, "fix", None),

    # ─── ZKAP — Zirkonkäppchen ───────────────────────────────────────────
    ("ZKAP", "*3002", 1, 1, "pro_zahn", None),
    ("ZKAP", "*Z100", 1, 1, "pro_zahn", None),
    ("ZKAP", "*8000", 0, 2, "fix", "privat"),
    ("ZKAP", "9330", 0, 2, "fix", "kasse"),
]

# ============================================================================
# INDIZES (automatisch aufgebaut)
# ============================================================================

# kuerzel → [(pos, ist_pflicht, standard_menge, mengen_formel, bedingung)]
KPOS_INDEX: Dict[str, list] = defaultdict(list)
for k, pos, pfl, menge, formel, bed in KUERZEL_POS:
    KPOS_INDEX[k].append((pos, pfl, menge, formel, bed))

# Positionen die nur 1x pro Rechnung vorkommen
FIX_POSITIONEN = {
    "*8000", "*9022", "*9025", "*9030", "*0001", "*0010", "*0051",
    "*0200", "*0201", "*0202", "*0301", "*0030", "*0012", "*0014",
    "9330", "0120", "0010", "0021", "4010", "7100",
}

ANALOG_POSITIONEN = {"*0010", "*0051", "*0200", "*0201", "*0202", "*0301"}
DIGITAL_POSITIONEN = {"*9022", "*9025", "*9027", "*9030"}

# Alle bekannten Kürzel
KNOWN_KUERZEL = set(KPOS_INDEX.keys())

# ============================================================================
# FDI ZAHNBOGEN
# ============================================================================
UPPER_ARCH = [18, 17, 16, 15, 14, 13, 12, 11, 21, 22, 23, 24, 25, 26, 27, 28]
LOWER_ARCH = [48, 47, 46, 45, 44, 43, 42, 41, 31, 32, 33, 34, 35, 36, 37, 38]


def fdi_range(start: int, end: int) -> List[int]:
    """Generiere FDI-Zahnnummern entlang des Zahnbogens.

    '15-23' → [15,14,13,12,11,21,22,23]  (8 Zähne über die Mitte)
    '13-11' → [13,12,11]                 (Brücke: 12 ist Brückenglied)
    """
    sq = start // 10
    eq = end // 10
    if sq in (1, 2) and eq in (1, 2):
        arch = UPPER_ARCH
    elif sq in (3, 4) and eq in (3, 4):
        arch = LOWER_ARCH
    else:
        return [start, end]
    try:
        si = arch.index(start)
        ei = arch.index(end)
    except ValueError:
        return [start, end]
    if si <= ei:
        return arch[si:ei + 1]
    else:
        return arch[ei:si + 1]


def parse_zaehne(zaehne_str: str) -> List[int]:
    """Parse Zahnangaben nach FDI-Nummern. Toleriert Buchstaben wie '14B'."""
    zaehne = []
    clean = re.sub(r'(\d+)[A-Za-z]', r'\1', zaehne_str)
    parts = re.split(r'[,\s]+', clean)
    for part in parts:
        part = part.strip()
        if not part:
            continue
        if '-' in part:
            try:
                start_s, end_s = part.split('-')
                s = int(start_s.strip())
                e_str = end_s.strip()
                if e_str == '':
                    zaehne.append(s)
                else:
                    e = int(e_str)
                    if s > 0 and e > 0:
                        zaehne.extend(fdi_range(s, e))
                    else:
                        zaehne.extend([s, e])
            except ValueError:
                pass
        else:
            try:
                zaehne.append(int(part))
            except ValueError:
                pass
    return zaehne


def parse_arbeitsart(arbeitsart: str) -> List[Tuple[str, List[int]]]:
    """Parse die Arbeitsart-Zeile in [(kuerzel, [zaehne]), ...].

    Versteht:
    - "37 PK" → [("PK", [37])]
    - "11,21 ZKV; 25 ZBR" → [("ZKV", [11,21]), ("ZBR", [25])]
    - "SCH OK" → [("SCH", [])]
    - "12-22 K Emax" → [("EMX", [12,11,21,22])]
    - "Adjustierte Aufbissschiene" → [("SCH", [])]
    """
    art = arbeitsart.strip()

    # Sonderfall: Ganzer Text ist ein Alias
    art_lower = art.lower()
    for alias_text, kuerzel in KUERZEL_ALIAS.items():
        if art_lower == alias_text.lower():
            if kuerzel in ("GB", "_SKIP"):
                return [("_SKIP", [])]
            return [(kuerzel, [])]

    # "WaxUp, MockUp" etc. als Ganzes
    if re.match(r'(?i)wax\s*up.*mock\s*up|mock\s*up.*wax\s*up', art):
        return [("MOCK", [])]

    # Teile durch ";" oder ", " vor Ziffern trennen
    teile_semi = [t.strip() for t in art.split(";")]
    teile = []
    for teil in teile_semi:
        sub = re.split(r',\s+(?=\d)', teil)
        teile.extend(sub)

    ergebnis = []

    for teil in teile:
        teil = teil.strip()
        if not teil:
            continue

        teil_clean = re.sub(r'\b(OK|UK)\b', '', teil).strip()

        # Kürzel VOR Zähnen: "Digitales SmileDesign 12,11"
        match_rev = re.match(r'^([A-Za-zÄÖÜäöüß\s\.]+?)\s+([\d,\-\s]+)$', teil_clean)
        if match_rev:
            kuerzel_raw = match_rev.group(1).strip()
            zaehne_str = match_rev.group(2).strip()
            kuerzel = KUERZEL_ALIAS.get(kuerzel_raw, kuerzel_raw)
            if kuerzel in KNOWN_KUERZEL:
                ergebnis.append((kuerzel, parse_zaehne(zaehne_str)))
                continue

        # "x Zirkonkäppchen" / "x ZKAP" Format
        match_x = re.match(r'^(\d+)\s*x\s+(.+)$', teil_clean, re.IGNORECASE)
        if match_x:
            anzahl = int(match_x.group(1))
            kuerzel_raw = match_x.group(2).strip()
            kuerzel = KUERZEL_ALIAS.get(kuerzel_raw, kuerzel_raw)
            if kuerzel in KNOWN_KUERZEL:
                # Anzahl als "virtuelle Zähne" für pro_zahn-Formeln
                ergebnis.append((kuerzel, list(range(1, anzahl + 1))))
                continue

        # Standard: "Zähne Kürzel" z.B. "37 PK", "14 K Zi"
        match = re.match(r'^([\d,\-A-Za-z]+)\s+(.+)$', teil_clean)
        if match:
            zaehne_str = match.group(1).strip()
            rest = match.group(2).strip()

            # Ganzer Rest als Kürzel?
            kuerzel_voll = KUERZEL_ALIAS.get(rest, rest)
            if kuerzel_voll in KNOWN_KUERZEL:
                ergebnis.append((kuerzel_voll, parse_zaehne(zaehne_str)))
                continue

            # Multi-Kürzel: "SKM 36 ZB"
            multi_match = re.match(r'^(\w+)\s+([\d,\-\s]+)\s+(.+)$', rest)
            if multi_match:
                k1 = KUERZEL_ALIAS.get(multi_match.group(1).strip(), multi_match.group(1).strip())
                z2_str = multi_match.group(2).strip()
                k2 = KUERZEL_ALIAS.get(multi_match.group(3).strip(), multi_match.group(3).strip())
                if k1 in KNOWN_KUERZEL:
                    ergebnis.append((k1, parse_zaehne(zaehne_str)))
                if k2 in KNOWN_KUERZEL:
                    ergebnis.append((k2, parse_zaehne(z2_str)))
                continue

            kuerzel = KUERZEL_ALIAS.get(rest, rest)
            if kuerzel in KNOWN_KUERZEL:
                ergebnis.append((kuerzel, parse_zaehne(zaehne_str)))
            elif kuerzel not in ("_SKIP", "GB"):
                ergebnis.append(("UNBEKANNT:" + rest, parse_zaehne(zaehne_str)))
        else:
            # Nur Kürzel ohne Zähne
            kuerzel = KUERZEL_ALIAS.get(teil_clean, teil_clean)
            if kuerzel in KNOWN_KUERZEL:
                ergebnis.append((kuerzel, []))
            elif kuerzel in ("GB", "_SKIP"):
                continue
            else:
                ergebnis.append(("UNBEKANNT:" + teil_clean, []))

    return ergebnis


def detect_kasse(positionen: List[Dict]) -> bool:
    """Erkennt ob eine Rechnung Kasse ist anhand vorhandener Positionen."""
    bel_kasse = {"4010", "7100", "0120", "0021", "4021"}
    for p in positionen:
        num = p.get("nummer", "")
        if num in bel_kasse:
            return True
    hat_beb = any(p.get("nummer", "").startswith("*") for p in positionen)
    if not hat_beb and len(positionen) > 0:
        return True
    return False


def resolve_positionen(
    kuerzel: str,
    zaehne: List[int],
    kasse: bool = False,
    gesichtsbogen: bool = False,
    abdruck: bool = True,
) -> List[Dict]:
    """Generiere Positionsliste für ein Kürzel.

    Args:
        kuerzel: Standardkürzel (z.B. "ZKV")
        zaehne: Liste der FDI-Zahnnummern
        kasse: True wenn Kassenrechnung
        gesichtsbogen: True wenn Gesichtsbogen vorhanden
        abdruck: True = Gipsmodelle (2x Desinfektion), False = Scan (1x)

    Returns:
        Liste von {"nummer": str, "menge": int, "ist_pflicht": int}
    """
    if kuerzel not in KPOS_INDEX:
        return []

    anzahl_zaehne = max(len(zaehne), 1)
    positionen = []

    for pos, ist_pflicht, standard_menge, formel, bedingung in KPOS_INDEX[kuerzel]:
        # Bedingungen prüfen
        if bedingung == "kasse" and not kasse:
            continue
        if bedingung == "privat" and kasse:
            continue
        if bedingung == "gesichtsbogen" and not gesichtsbogen:
            continue
        if bedingung == "kein_gb_privat" and (gesichtsbogen or kasse):
            continue
        if pos in ANALOG_POSITIONEN and not abdruck:
            continue
        if pos in DIGITAL_POSITIONEN and abdruck:
            continue

        # Menge berechnen
        if formel == "pro_zahn":
            menge = standard_menge * anzahl_zaehne
        elif formel == "pro_glied":
            menge = max(anzahl_zaehne - 2, 1) if anzahl_zaehne > 2 else 0
        else:
            menge = standard_menge

        # Desinfektion: Abdruck = 2x, Scan = 1x
        if pos == "*0001":
            menge = 2 if abdruck else 1

        # Versand: Abdruck = 2x, Scan = 1x
        if pos == "*8000":
            menge = 2 if abdruck else 1

        if menge > 0:
            positionen.append({
                "nummer": pos,
                "menge": menge,
                "ist_pflicht": ist_pflicht,
            })

    return positionen


def generate_invoice(
    arbeitsart: str,
    praxis: Optional[str] = None,
    kasse: bool = False,
    abdruck: bool = True,
    gesichtsbogen: bool = False,
    praxis_preise: Optional[Dict[str, float]] = None,
) -> Dict:
    """Generiere eine vollständige Rechnung aus einer Arbeitsart-Zeile.

    Args:
        arbeitsart: z.B. "11,21 ZKV; 25 ZBR"
        praxis: Praxisname (für Preiszuordnung)
        kasse: True wenn Kassenrechnung
        abdruck: True wenn Gipsmodelle (2x Desinfektion)
        gesichtsbogen: True wenn Gesichtsbogen verwendet
        praxis_preise: Dict von Position → Preis (optional)

    Returns:
        {
            "arbeitsart": str,
            "parsed": [(kuerzel, zaehne), ...],
            "positionen": [{"nummer", "menge", "ist_pflicht", "preis"}, ...],
            "kasse": bool,
            "abdruck": bool,
            "fehler": [str, ...],  # Parse-Fehler etc.
        }
    """
    parsed = parse_arbeitsart(arbeitsart)

    fehler = []
    for k, z in parsed:
        if "UNBEKANNT" in k:
            fehler.append(f"Unbekanntes Kürzel: {k}")

    # Positionen generieren
    gen_pos = {}
    for kuerzel, zaehne in parsed:
        if "UNBEKANNT" in kuerzel or kuerzel == "_SKIP":
            continue
        resolved = resolve_positionen(
            kuerzel, zaehne, kasse=kasse,
            gesichtsbogen=gesichtsbogen, abdruck=abdruck,
        )
        for rp in resolved:
            num = rp["nummer"]
            if num in FIX_POSITIONEN and num in gen_pos:
                continue  # Fix-Positionen nur 1x pro Rechnung
            if num in gen_pos:
                gen_pos[num]["menge"] += rp["menge"]
                if rp["ist_pflicht"]:
                    gen_pos[num]["ist_pflicht"] = 1
            else:
                gen_pos[num] = {
                    "nummer": num,
                    "menge": rp["menge"],
                    "ist_pflicht": rp["ist_pflicht"],
                }

    # Preise einsetzen
    if praxis_preise:
        for num, data in gen_pos.items():
            if num in praxis_preise:
                data["preis"] = praxis_preise[num]
            else:
                data["preis"] = None
    else:
        for data in gen_pos.values():
            data["preis"] = None

    positionen = sorted(gen_pos.values(), key=lambda x: x["nummer"])

    return {
        "arbeitsart": arbeitsart,
        "parsed": [(k, z) for k, z in parsed],
        "positionen": positionen,
        "kasse": kasse,
        "abdruck": abdruck,
        "fehler": fehler,
    }


# ============================================================================
# STANDALONE TEST
# ============================================================================
if __name__ == "__main__":
    # Schnelltest
    tests = [
        "11,21 ZKV; 25 ZBR",
        "37 PK",
        "SCH OK",
        "12-22 K Emax",
        "45,46 SKM; 47 ZK",
        "15-23,25-28 ZKM",
        "SCH Schnarcherschiene",
        "UK Miniplastschiene",
        "23 x ZKAP",
    ]
    for t in tests:
        result = generate_invoice(t)
        parsed_str = ", ".join(f"{k}({len(z)}Z)" for k, z in result["parsed"])
        pos_count = len(result["positionen"])
        pflicht = sum(1 for p in result["positionen"] if p["ist_pflicht"])
        print(f"  '{t}' → {parsed_str} → {pos_count} Pos ({pflicht} Pflicht)")
        if result["fehler"]:
            print(f"    FEHLER: {result['fehler']}")
