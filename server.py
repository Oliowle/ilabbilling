"""
Dental OS - FastAPI Backend mit Abrechnungsintelligenz
======================================================
Zahntechnik Oliver Krieger, Nürnberg

Integriert:
- billing_engine.py (95.1% Positionsgenauigkeit)
- billing_prices.py (Praxis-spezifische Preise)
- billing_learning.py (Korrektursystem)

Endpoints:
    GET  /                           → dental_os.html
    POST /api/generate               → Rechnung aus Arbeitsart-Zeile generieren
    POST /api/korrektur              → Korrektur speichern
    GET  /api/korrekturen            → Aktive Korrekturen auflisten
    GET  /api/praxen                 → Alle Praxen mit Preisgruppen
    GET  /api/kuerzel                → Alle bekannten Kürzel
    GET  /api/stats                  → Korrektur-Statistiken

Starten:
    uvicorn server:app --host 0.0.0.0 --port 8000 --reload
"""

import os
import json
import re
import sqlite3
from datetime import datetime
from typing import Any, Optional, List, Dict
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from billing_engine import generate_invoice, parse_arbeitsart, KNOWN_KUERZEL, KUERZEL_ALIAS, KUERZEL_POS
from billing_prices import PriceLoader
from billing_learning import LearningStore

BASE_DIR = Path(__file__).parent
HTML_FILE = BASE_DIR / "dental_os.html"
PRICES_FILE = BASE_DIR / "abrechnungslogik_preisgruppen.json"
KORREKTUREN_FILE = BASE_DIR / "data" / "korrekturen.json"
HEALTH_HISTORY_FILE = BASE_DIR / "data" / "health_history.json"
UI_DB_FILE = BASE_DIR / "data" / "dental_os.sqlite3"

os.makedirs(BASE_DIR / "data", exist_ok=True)

price_loader = PriceLoader(str(PRICES_FILE))
learning_store = LearningStore(str(KORREKTUREN_FILE))


# ─── Pydantic Models ─────────────────────────────────────────────────────────

class GenerateRequest(BaseModel):
    arbeitsart: str
    praxis: Optional[str] = None
    kasse: bool = False
    abdruck: bool = True
    gesichtsbogen: bool = False

class KorrekturRequest(BaseModel):
    kuerzel: str
    position: str
    aktion: str
    neuer_wert: Optional[Any] = None
    alter_wert: Optional[Any] = None
    praxis: Optional[str] = None
    kasse: Optional[bool] = None
    erklaerung: str = ""
    status: str = "aktiv"
    test_mode: bool = False
    created_by: str = "ui"

class KorrekturStatusRequest(BaseModel):
    status: str
    grund: str = ""


class KVARequest(BaseModel):
    id: str
    praxis: Optional[str] = ""
    patient: Optional[str] = ""
    versicherung: Optional[str] = "privat"
    gesichtsbogen: Optional[str] = "ohne"
    arbeitsart: Optional[str] = ""
    kuerzel: Optional[str] = None
    zaehne: List[Any] = []
    positions: List[Dict[str, Any]] = []
    korrektionen: List[Dict[str, Any]] = []
    gesamtbetrag: Optional[float] = 0
    timestamp: Optional[str] = None
    korrekturen_count: int = 0
    status: Optional[str] = "korrekt"


class PraxisOverrideRequest(BaseModel):
    code: str
    name: str
    preisliste: int = 0
    telefon: str = ""
    email: str = ""
    notizen: str = ""


class LeistungOverrideRequest(BaseModel):
    nr: str
    bez: str
    kat: str
    preise: List[float]


def connect_ui_db():
    conn = sqlite3.connect(str(UI_DB_FILE))
    conn.row_factory = sqlite3.Row
    return conn


def init_ui_db():
    with connect_ui_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS kvas (
                id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                praxis TEXT,
                patient TEXT,
                status TEXT,
                payload_json TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS praxis_overrides (
                code TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                preisliste INTEGER NOT NULL DEFAULT 0,
                telefon TEXT NOT NULL DEFAULT '',
                email TEXT NOT NULL DEFAULT '',
                notizen TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL,
                payload_json TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS leistung_overrides (
                nr TEXT PRIMARY KEY,
                bez TEXT NOT NULL,
                kat TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                payload_json TEXT NOT NULL
            )
        """)


def decode_payload(row: sqlite3.Row) -> dict:
    return json.loads(row["payload_json"])


def validate_kva_payload(payload: dict) -> dict:
    kva_id = (payload.get("id") or "").strip()
    if not kva_id:
        raise HTTPException(status_code=400, detail="KVA-ID darf nicht leer sein")
    payload["id"] = kva_id
    payload["timestamp"] = payload.get("timestamp") or datetime.now().isoformat(timespec="seconds")
    payload["positions"] = payload.get("positions") or []
    payload["korrektionen"] = payload.get("korrektionen") or []
    payload["zaehne"] = payload.get("zaehne") or []
    return payload


def validate_praxis_payload(payload: dict) -> dict:
    code = (payload.get("code") or "").strip().upper()
    name = (payload.get("name") or "").strip()
    if not code:
        raise HTTPException(status_code=400, detail="Praxis-Code darf nicht leer sein")
    if not name:
        raise HTTPException(status_code=400, detail="Praxis-Name darf nicht leer sein")
    try:
        preisliste = int(payload.get("preisliste", 0))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Preisliste muss numerisch sein")
    if preisliste < 0 or preisliste > 4:
        raise HTTPException(status_code=400, detail="Preisliste muss zwischen 0 und 4 liegen")
    payload["code"] = code
    payload["name"] = name
    payload["preisliste"] = preisliste
    payload["telefon"] = str(payload.get("telefon") or "")
    payload["email"] = str(payload.get("email") or "")
    payload["notizen"] = str(payload.get("notizen") or "")
    return payload


def validate_leistung_payload(payload: dict) -> dict:
    nr = (payload.get("nr") or "").strip()
    bez = (payload.get("bez") or "").strip()
    kat = (payload.get("kat") or "").strip()
    if not nr:
        raise HTTPException(status_code=400, detail="Leistungsnummer darf nicht leer sein")
    known_numbers = {row[1].lstrip("*") for row in KUERZEL_POS}
    if nr.lstrip("*") not in known_numbers:
        raise HTTPException(status_code=400, detail=f"Unbekannte Leistungsnummer: {nr}")
    if not bez:
        raise HTTPException(status_code=400, detail="Leistungsbezeichnung darf nicht leer sein")
    if kat not in {"leistung", "material"}:
        raise HTTPException(status_code=400, detail="Kategorie muss 'leistung' oder 'material' sein")
    preise = payload.get("preise")
    if not isinstance(preise, list) or len(preise) != 5:
        raise HTTPException(status_code=400, detail="Es müssen genau 5 Preislistenwerte übergeben werden")
    try:
        normalized_prices = [round(float(price), 2) for price in preise]
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Preise müssen numerisch sein")
    if any(price < 0 for price in normalized_prices):
        raise HTTPException(status_code=400, detail="Preise dürfen nicht negativ sein")
    payload["nr"] = nr.lstrip("*")
    payload["bez"] = bez
    payload["kat"] = kat
    payload["preise"] = normalized_prices
    return payload


def normalize_position_number(position: str) -> str:
    """Normalisiere UI-Positionsnummern auf Engine-Format."""
    pos = (position or "").strip().upper()
    if not pos:
        raise HTTPException(status_code=400, detail="Position darf nicht leer sein")
    if not re.match(r"^\*?[A-Z0-9]+$", pos):
        raise HTTPException(status_code=400, detail="Ungültiges Positionsformat")
    known_positions = {row[1].upper() for row in KUERZEL_POS}
    if pos not in known_positions and not pos.startswith("*") and ("*" + pos) in known_positions:
        pos = "*" + pos
    if pos not in known_positions:
        raise HTTPException(status_code=400, detail=f"Unbekannte Position: {pos}")
    return pos


def validate_korrektur_request(req: KorrekturRequest):
    kuerzel = (req.kuerzel or "").strip().upper()
    if not kuerzel:
        raise HTTPException(status_code=400, detail="Kürzel ist für Lernkorrekturen erforderlich")
    kuerzel = KUERZEL_ALIAS.get(kuerzel, kuerzel)
    if kuerzel not in KNOWN_KUERZEL:
        raise HTTPException(status_code=400, detail=f"Unbekanntes Kürzel: {kuerzel}")
    if req.aktion not in {"hinzufuegen", "entfernen", "menge_aendern", "preis_aendern", "kategorie_aendern"}:
        raise HTTPException(status_code=400, detail=f"Unbekannte Aktion: {req.aktion}")
    if req.status not in {"vorgeschlagen", "aktiv", "deaktiviert", "ersetzt"}:
        raise HTTPException(status_code=400, detail=f"Unbekannter Status: {req.status}")
    if req.aktion in {"menge_aendern", "hinzufuegen"}:
        try:
            if req.neuer_wert is not None and float(req.neuer_wert) <= 0:
                raise HTTPException(status_code=400, detail="Menge muss größer als 0 sein")
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="Menge muss numerisch sein")
    if req.aktion == "preis_aendern":
        try:
            if req.neuer_wert is not None and float(req.neuer_wert) < 0:
                raise HTTPException(status_code=400, detail="Preis darf nicht negativ sein")
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="Preis muss numerisch sein")
    if req.aktion == "kategorie_aendern" and req.neuer_wert not in {"leistung", "material"}:
        raise HTTPException(status_code=400, detail="Kategorie muss 'leistung' oder 'material' sein")
    return kuerzel, normalize_position_number(req.position)


def validate_generate_request(req: GenerateRequest):
    if not (req.arbeitsart or "").strip():
        raise HTTPException(status_code=400, detail="Arbeitsart darf nicht leer sein")


def api_envelope(data: dict) -> dict:
    return {
        "api_version": app.version,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        **data,
    }


# ─── FastAPI App ──────────────────────────────────────────────────────────────

app = FastAPI(title="Dental OS API", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

init_ui_db()


# ─── Routes ───────────────────────────────────────────────────────────────────

@app.get("/")
async def root():
    if HTML_FILE.exists():
        return FileResponse(str(HTML_FILE))
    return {"message": "Dental OS API v2.0"}


@app.post("/api/generate")
def api_generate(req: GenerateRequest):
    """Generiere eine vollständige Rechnung aus einer Arbeitsart-Zeile.

    Beispiel:
        POST /api/generate
        {"arbeitsart": "11,21 ZKV; 25 ZBR", "praxis": "Röder"}
    """
    validate_generate_request(req)
    praxis_norm = price_loader.normalize_praxis(req.praxis) if req.praxis else None
    praxis_preise = price_loader.get_praxis_prices(praxis_norm) if praxis_norm else None

    result = generate_invoice(
        arbeitsart=req.arbeitsart,
        praxis=praxis_norm,
        kasse=req.kasse,
        abdruck=req.abdruck,
        gesichtsbogen=req.gesichtsbogen,
        praxis_preise=praxis_preise,
        correction_store=learning_store,
    )

    preis_details = {}
    if praxis_norm:
        for pos in result["positionen"]:
            num = pos["nummer"]
            preis, quelle = price_loader.get_price_with_source(praxis_norm, num)
            preis_details[num] = {"preis": preis, "quelle": quelle}
            if preis is not None and pos.get("preis") is None:
                pos["preis"] = preis
            pos["price_missing"] = pos.get("preis") is None
            pos.setdefault("reasons", []).append(f"Preisquelle: {quelle or 'kein Preisprofil'}")
    else:
        for pos in result["positionen"]:
            pos["price_missing"] = pos.get("preis") is None

    total = sum(
        (p.get("preis") or 0) * p.get("menge", 1)
        for p in result["positionen"]
    )

    return api_envelope({
        **result,
        "praxis_norm": praxis_norm,
        "preis_details": preis_details,
        "total": round(total, 2),
        "validation": {
            "price_missing_count": sum(1 for p in result["positionen"] if p.get("price_missing")),
            "needs_review_count": sum(1 for p in result["positionen"] if p.get("needs_review")),
        },
    })


@app.post("/api/korrektur")
def api_korrektur(req: KorrekturRequest):
    """Speichere eine Korrektur von Oliver."""
    kuerzel, position = validate_korrektur_request(req)
    praxis_norm = price_loader.normalize_praxis(req.praxis) if req.praxis else None
    korrektur = learning_store.add_correction(
        kuerzel=kuerzel,
        position=position,
        aktion=req.aktion,
        neuer_wert=req.neuer_wert,
        alter_wert=req.alter_wert,
        praxis=praxis_norm,
        kasse=req.kasse,
        erklaerung=req.erklaerung,
        status=req.status,
        test_mode=req.test_mode,
        quelle="api",
        created_by=req.created_by,
    )
    return api_envelope({"status": "ok", "korrektur": korrektur})


@app.get("/api/korrekturen")
def api_korrekturen(kuerzel: Optional[str] = None):
    """Liste aktive Korrekturen."""
    return learning_store.list_active(kuerzel)


@app.get("/api/korrekturen/all")
def api_korrekturen_all(kuerzel: Optional[str] = None, include_tests: bool = True):
    """Liste alle Lernregeln inklusive deaktivierter Regeln."""
    return api_envelope({
        "korrekturen": learning_store.list_all(kuerzel=kuerzel, include_tests=include_tests),
        "stats": learning_store.stats(),
    })


@app.post("/api/korrekturen/{korrektur_id}/status")
def api_korrektur_status(korrektur_id: int, req: KorrekturStatusRequest):
    """Aktiviere, deaktiviere oder markiere eine Lernregel."""
    try:
        ok = learning_store.set_status(korrektur_id, req.status, req.grund)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if not ok:
        raise HTTPException(status_code=404, detail=f"Korrektur {korrektur_id} nicht gefunden")
    return api_envelope({"status": "ok", "korrektur_id": korrektur_id, "neuer_status": req.status})


@app.get("/api/stats")
def api_stats():
    """Korrektur-Statistiken."""
    return learning_store.stats()


@app.get("/api/verify/historical")
def api_verify_historical(limit: Optional[int] = None, abdruck: bool = True):
    """Staging/Admin-Check gegen historische Rechnungen."""
    from verify_invoices import DEFAULT_CSV, parse_csv, verify_single

    if not DEFAULT_CSV.exists():
        raise HTTPException(
            status_code=404,
            detail="Historische CSV ist auf diesem Server nicht vorhanden. Bitte verify_invoices.py --api gegen Staging ausführen.",
        )

    rows = parse_csv(DEFAULT_CSV)
    if limit:
        rows = rows[:limit]

    results = []
    errors = []
    for row in rows:
        result = verify_single(row, price_loader, abdruck=abdruck, correction_store=learning_store)
        if not result:
            continue
        if "error" in result:
            errors.append(result)
        else:
            results.append(result)

    total_expected = sum(r["expected_count"] for r in results)
    total_matches = sum(r["match_count"] for r in results)
    match_rate = round(100 * total_matches / total_expected, 2) if total_expected else 0
    return {
        "rechnungen": len(results),
        "expected": total_expected,
        "matches": total_matches,
        "match_rate": match_rate,
        "qty_diffs": sum(len(r["qty_diffs"]) for r in results),
        "missing": sum(len(r["missing"]) for r in results),
        "extra": sum(len(r["extra"]) for r in results),
        "formula_diffs": sum(len(r["formula_diffs"]) for r in results),
        "errors": len(errors),
        "passed": match_rate >= 92.0,
    }


@app.get("/api/praxen")
def api_praxen():
    """Alle bekannten Praxen mit Preisgruppen-Info."""
    result = []
    for name in price_loader.list_praxen():
        info = price_loader.get_praxis_info(name) or {}
        result.append({
            "name": name,
            "preisgruppe": info.get("preisgruppe", ""),
            "rechnungen_2026": info.get("rechnungen_2026", 0),
            "umsatz_gesamt": info.get("umsatz_gesamt", 0),
        })
    return result


@app.get("/api/kvas")
def api_kvas():
    """Alle dauerhaft gespeicherten KVAs aus SQLite."""
    with connect_ui_db() as conn:
        rows = conn.execute("SELECT payload_json FROM kvas ORDER BY created_at ASC").fetchall()
    return api_envelope({"kvas": [decode_payload(row) for row in rows]})


@app.get("/api/kvas/{kva_id}")
def api_kva_detail(kva_id: str):
    with connect_ui_db() as conn:
        row = conn.execute("SELECT payload_json FROM kvas WHERE id = ?", (kva_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail=f"KVA {kva_id} nicht gefunden")
    return api_envelope({"kva": decode_payload(row)})


@app.post("/api/kvas")
def api_save_kva(req: KVARequest):
    """Speichere oder aktualisiere einen KVA dauerhaft."""
    payload = validate_kva_payload(req.dict())
    now = datetime.now().isoformat(timespec="seconds")
    created_at = payload.get("timestamp") or now
    payload_json = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    with connect_ui_db() as conn:
        conn.execute("""
            INSERT INTO kvas (id, created_at, updated_at, praxis, patient, status, payload_json)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                updated_at = excluded.updated_at,
                praxis = excluded.praxis,
                patient = excluded.patient,
                status = excluded.status,
                payload_json = excluded.payload_json
        """, (
            payload["id"],
            created_at,
            now,
            payload.get("praxis"),
            payload.get("patient"),
            payload.get("status"),
            payload_json,
        ))
    return api_envelope({"status": "ok", "kva": payload})


@app.get("/api/praxen/overrides")
def api_praxis_overrides():
    """UI-Stammdaten zu Praxen, die dauerhaft geändert wurden."""
    with connect_ui_db() as conn:
        rows = conn.execute("SELECT payload_json FROM praxis_overrides ORDER BY name ASC").fetchall()
    return api_envelope({"praxen": [decode_payload(row) for row in rows]})


@app.post("/api/praxen/overrides")
def api_save_praxis_override(req: PraxisOverrideRequest):
    """Speichere UI-Stammdaten einer Praxis dauerhaft."""
    payload = validate_praxis_payload(req.dict())
    now = datetime.now().isoformat(timespec="seconds")
    payload["updated_at"] = now
    payload_json = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    with connect_ui_db() as conn:
        conn.execute("""
            INSERT INTO praxis_overrides (code, name, preisliste, telefon, email, notizen, updated_at, payload_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(code) DO UPDATE SET
                name = excluded.name,
                preisliste = excluded.preisliste,
                telefon = excluded.telefon,
                email = excluded.email,
                notizen = excluded.notizen,
                updated_at = excluded.updated_at,
                payload_json = excluded.payload_json
        """, (
            payload["code"],
            payload["name"],
            payload["preisliste"],
            payload["telefon"],
            payload["email"],
            payload["notizen"],
            now,
            payload_json,
        ))
    return api_envelope({"status": "ok", "praxis": payload})


@app.get("/api/leistungen/overrides")
def api_leistung_overrides():
    """UI-Änderungen an Leistungen und Preislisten aus SQLite."""
    with connect_ui_db() as conn:
        rows = conn.execute("SELECT payload_json FROM leistung_overrides ORDER BY nr ASC").fetchall()
    return api_envelope({"leistungen": [decode_payload(row) for row in rows]})


@app.post("/api/leistungen/overrides")
def api_save_leistung_override(req: LeistungOverrideRequest):
    """Speichere eine UI-Änderung an einer Leistung dauerhaft."""
    payload = validate_leistung_payload(req.dict())
    now = datetime.now().isoformat(timespec="seconds")
    payload["updated_at"] = now
    payload_json = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    with connect_ui_db() as conn:
        conn.execute("""
            INSERT INTO leistung_overrides (nr, bez, kat, updated_at, payload_json)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(nr) DO UPDATE SET
                bez = excluded.bez,
                kat = excluded.kat,
                updated_at = excluded.updated_at,
                payload_json = excluded.payload_json
        """, (
            payload["nr"],
            payload["bez"],
            payload["kat"],
            now,
            payload_json,
        ))
    return api_envelope({"status": "ok", "leistung": payload})


@app.get("/api/kuerzel")
def api_kuerzel():
    """Alle bekannten Kürzel."""
    return sorted(KNOWN_KUERZEL)


@app.get("/api/aliase")
def api_aliase():
    """Kürzel-Aliase (alte Schreibweisen → Standard)."""
    return KUERZEL_ALIAS


@app.get("/api/preise/{praxis}")
def api_preise(praxis: str):
    """Alle Preise einer Praxis."""
    praxis_norm = price_loader.normalize_praxis(praxis)
    preise = price_loader.get_praxis_prices(praxis_norm)
    if not preise:
        raise HTTPException(status_code=404, detail=f"Praxis '{praxis}' nicht gefunden")
    return {"praxis": praxis_norm, "preise": preise}


@app.get("/api/engine-updates")
def api_engine_updates():
    """Korrekturen die häufig genug sind für Base-Rule-Updates."""
    return learning_store.export_for_engine_update()


@app.get("/api/health")
def api_health():
    """Health-Check + Self-Verification gegen Test-Rechnungen.

    Prüft die Engine gegen 10 Beispiel-Rechnungen und liefert die Trefferquote.
    Status:
        - "ok": >= 70% Trefferquote
        - "warning": 50-70% Trefferquote
        - "critical": < 50% Trefferquote
    """
    test_cases = [
        {"arbeitsart": "46 ZK", "praxis": "Dr. Gabriele Schmidt", "expected": ["*0001", "*0301", "*0600", "*3002", "*5504"]},
        {"arbeitsart": "16 ZK", "praxis": "Dr. Gabriele Schmidt", "expected": ["*0001", "*0301", "*0600", "*3002", "*5504"]},
        {"arbeitsart": "37 PK", "praxis": "Röder u. Kollegen", "expected": ["*0001", "*0301", "*5504", "*5003"]},
        {"arbeitsart": "11,21 ZKV", "praxis": "Röder u. Kollegen", "expected": ["*0001", "*5500", "*5504"]},
        {"arbeitsart": "25,27 ZKV; 26 ZBR", "praxis": "Röder u. Kollegen", "expected": ["*3000", "*5500", "*5504"]},
        {"arbeitsart": "12-22 EMX", "praxis": "Dr. Lex", "expected": ["*5001", "*5500"]},
        {"arbeitsart": "SCH", "praxis": "Dr. Neuffer", "expected": ["*0250", "*0850"]},
        {"arbeitsart": "11 VEN", "praxis": "Das Hugo", "expected": ["*5001", "*5500"]},
        {"arbeitsart": "36 INL", "praxis": "Helm", "expected": ["*5200", "*5504"]},
        {"arbeitsart": "44,46 SKM; 45 ZBR", "praxis": "MVZ Phönixsee", "expected": ["*1000", "*5500"]},
    ]

    total_expected = 0
    total_matches = 0
    failed_cases = []

    for case in test_cases:
        try:
            praxis_norm = price_loader.normalize_praxis(case["praxis"])
            praxis_preise = price_loader.get_praxis_prices(praxis_norm)
            result = generate_invoice(
                arbeitsart=case["arbeitsart"],
                praxis=praxis_norm,
                kasse=False,
                abdruck=True,
                gesichtsbogen=False,
                praxis_preise=praxis_preise,
            )
            generated = {p["nummer"] for p in result["positionen"]}
            matches = sum(1 for p in case["expected"] if p in generated)
            total_expected += len(case["expected"])
            total_matches += matches
            if matches < len(case["expected"]):
                missing = [p for p in case["expected"] if p not in generated]
                failed_cases.append({
                    "arbeitsart": case["arbeitsart"],
                    "praxis": case["praxis"],
                    "missing": missing,
                })
        except Exception as e:
            failed_cases.append({
                "arbeitsart": case["arbeitsart"],
                "praxis": case["praxis"],
                "error": str(e),
            })

    rate = round(100 * total_matches / total_expected, 2) if total_expected else 0
    if rate >= 70:
        status = "ok"
    elif rate >= 50:
        status = "warning"
    else:
        status = "critical"

    history = _load_health_history()
    trend_7days = [h.get("match_rate") for h in history[-7:]]
    last_rate = history[-1]["match_rate"] if history else None
    alert = bool(last_rate is not None and rate < last_rate - 5.0)

    _append_health_history({
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "match_rate": rate,
        "status": status,
        "korrekturen_aktiv": len(learning_store.list_active()),
    })

    return {
        "status": status,
        "match_rate": rate,
        "test_cases": len(test_cases),
        "expected_positions": total_expected,
        "matched_positions": total_matches,
        "failed_cases": failed_cases,
        "korrekturen_aktiv": len(learning_store.list_active()),
        "praxen_geladen": len(price_loader.list_praxen()),
        "kuerzel_bekannt": len(KNOWN_KUERZEL),
        "trend_7days": trend_7days,
        "alert": alert,
        "alert_reason": (
            f"Match-Rate gefallen von {last_rate}% auf {rate}%" if alert else None
        ),
    }


def _load_health_history() -> List[dict]:
    """Lädt die History-Liste (max. 100 Einträge)."""
    if not HEALTH_HISTORY_FILE.exists():
        return []
    try:
        return json.loads(HEALTH_HISTORY_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []


def _append_health_history(entry: dict, max_entries: int = 100):
    """Hängt einen Eintrag an die History an. Überspringt Duplikate (gleiche Stunde)."""
    history = _load_health_history()
    cur_hour = entry["timestamp"][:13]
    if history and history[-1]["timestamp"][:13] == cur_hour:
        history[-1] = entry
    else:
        history.append(entry)
    history = history[-max_entries:]
    HEALTH_HISTORY_FILE.write_text(
        json.dumps(history, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


@app.get("/api/health/history")
def api_health_history(limit: int = 30):
    """Gibt die letzten N Health-Check-Einträge zurück (für Trend-Charts)."""
    history = _load_health_history()
    return {
        "entries": history[-limit:],
        "total": len(history),
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
