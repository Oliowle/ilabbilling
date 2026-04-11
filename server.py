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
from typing import Optional, List
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from billing_engine import generate_invoice, parse_arbeitsart, KNOWN_KUERZEL, KUERZEL_ALIAS
from billing_prices import PriceLoader
from billing_learning import LearningStore

BASE_DIR = Path(__file__).parent
HTML_FILE = BASE_DIR / "dental_os.html"
PRICES_FILE = BASE_DIR / "abrechnungslogik_preisgruppen.json"
KORREKTUREN_FILE = BASE_DIR / "data" / "korrekturen.json"

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
    neuer_wert: Optional[float] = None
    alter_wert: Optional[float] = None
    praxis: Optional[str] = None
    kasse: Optional[bool] = None
    erklaerung: str = ""


# ─── FastAPI App ──────────────────────────────────────────────────────────────

app = FastAPI(title="Dental OS API", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


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
    praxis_norm = price_loader.normalize_praxis(req.praxis) if req.praxis else None
    praxis_preise = price_loader.get_praxis_prices(praxis_norm) if praxis_norm else None

    result = generate_invoice(
        arbeitsart=req.arbeitsart,
        praxis=praxis_norm,
        kasse=req.kasse,
        abdruck=req.abdruck,
        gesichtsbogen=req.gesichtsbogen,
        praxis_preise=praxis_preise,
    )

    for kuerzel, zaehne in result["parsed"]:
        if "UNBEKANNT" in kuerzel or kuerzel == "_SKIP":
            continue
        result["positionen"] = learning_store.apply_corrections(
            result["positionen"],
            kuerzel=kuerzel,
            praxis=praxis_norm,
            kasse=req.kasse,
        )

    preis_details = {}
    if praxis_norm:
        for pos in result["positionen"]:
            num = pos["nummer"]
            preis, quelle = price_loader.get_price_with_source(praxis_norm, num)
            preis_details[num] = {"preis": preis, "quelle": quelle}
            if preis is not None and pos.get("preis") is None:
                pos["preis"] = preis

    total = sum(
        (p.get("preis") or 0) * p.get("menge", 1)
        for p in result["positionen"]
    )

    return {
        **result,
        "praxis_norm": praxis_norm,
        "preis_details": preis_details,
        "total": round(total, 2),
    }


@app.post("/api/korrektur")
def api_korrektur(req: KorrekturRequest):
    """Speichere eine Korrektur von Oliver."""
    praxis_norm = price_loader.normalize_praxis(req.praxis) if req.praxis else None
    korrektur = learning_store.add_correction(
        kuerzel=req.kuerzel,
        position=req.position,
        aktion=req.aktion,
        neuer_wert=req.neuer_wert,
        alter_wert=req.alter_wert,
        praxis=praxis_norm,
        kasse=req.kasse,
        erklaerung=req.erklaerung,
    )
    return {"status": "ok", "korrektur": korrektur}


@app.get("/api/korrekturen")
def api_korrekturen(kuerzel: Optional[str] = None):
    """Liste aktive Korrekturen."""
    return learning_store.list_active(kuerzel)


@app.get("/api/stats")
def api_stats():
    """Korrektur-Statistiken."""
    return learning_store.stats()


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


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
