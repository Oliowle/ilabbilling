#!/usr/bin/env python3
"""
Kleine Regression-Suite fuer DENTAL OS.

Prueft repraesentative Arbeitsarten gegen lokale Engine oder Staging-API.
"""

import argparse
import json
import sys
import urllib.request
from pathlib import Path

from billing_engine import generate_invoice
from billing_prices import PriceLoader


DEFAULT_API = "https://staging.ilabdashboard.com/billing/api"
DEFAULT_REPORT = Path(__file__).parent / "data" / "billing-regression-report.json"
DEFAULT_PRICES = Path(__file__).parent / "abrechnungslogik_preisgruppen.json"

CASES = [
    {
        "name": "einzelkrone_zk",
        "arbeitsart": "11 ZK",
        "praxis": "MVZ Phönixsee",
        "abdruck": False,
        "expected": {"*0001": 1, "*3002": 1, "*5504": 1},
    },
    {
        "name": "veneers_front",
        "arbeitsart": "13-23 VEN",
        "praxis": "Das Hugo",
        "abdruck": False,
        "expected": {"*5001": 6, "*5500": 6},
    },
    {
        "name": "bruecke_zirkon",
        "arbeitsart": "25,27 ZKV; 26 ZBR",
        "praxis": "Röder u. Kollegen",
        "abdruck": True,
        "expected": {"*3000": 3, "*5500": 3, "*5504": 3},
    },
    {
        "name": "implantat_mischfall",
        "arbeitsart": "44,46 SKM; 45 ZBR",
        "praxis": "MVZ Phönixsee",
        "abdruck": True,
        "expected": {"*1000": 2, "*1010": 2, "*5500": 3},
    },
    {
        "name": "schiene",
        "arbeitsart": "SCH",
        "praxis": "Dr. Neuffer",
        "abdruck": True,
        "expected": {"*0250": 1, "*0850": 1},
    },
]


def call_api(api_url: str, case: dict) -> dict:
    payload = json.dumps({
        "arbeitsart": case["arbeitsart"],
        "praxis": case["praxis"],
        "kasse": False,
        "abdruck": case["abdruck"],
        "gesichtsbogen": False,
    }).encode("utf-8")
    req = urllib.request.Request(
        f"{api_url.rstrip('/')}/generate",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode("utf-8"))


def call_local(case: dict, loader: PriceLoader) -> dict:
    praxis_norm = loader.normalize_praxis(case["praxis"])
    return generate_invoice(
        arbeitsart=case["arbeitsart"],
        praxis=praxis_norm,
        kasse=False,
        abdruck=case["abdruck"],
        gesichtsbogen=False,
        praxis_preise=loader.get_praxis_prices(praxis_norm),
    )


def compare(case: dict, result: dict) -> dict:
    generated = {p["nummer"]: p for p in result.get("positionen", [])}
    missing = []
    qty_diff = []
    for number, expected_qty in case["expected"].items():
        pos = generated.get(number)
        if not pos:
            missing.append({"nummer": number, "expected": expected_qty})
            continue
        if pos.get("menge") != expected_qty:
            qty_diff.append({"nummer": number, "expected": expected_qty, "generated": pos.get("menge")})
    price_missing = [p["nummer"] for p in generated.values() if p.get("price_missing")]
    return {
        "name": case["name"],
        "arbeitsart": case["arbeitsart"],
        "praxis": case["praxis"],
        "passed": not missing and not qty_diff and not price_missing,
        "missing": missing,
        "qty_diff": qty_diff,
        "price_missing": price_missing,
        "generated_count": len(generated),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--api", default=None, help=f"API-Basis, z.B. {DEFAULT_API}")
    parser.add_argument("--report", default=str(DEFAULT_REPORT))
    parser.add_argument("--prices", default=str(DEFAULT_PRICES))
    args = parser.parse_args()

    loader = PriceLoader(args.prices)
    results = []
    for case in CASES:
        try:
            result = call_api(args.api, case) if args.api else call_local(case, loader)
            results.append(compare(case, result))
        except Exception as exc:
            results.append({
                "name": case["name"],
                "arbeitsart": case["arbeitsart"],
                "praxis": case["praxis"],
                "passed": False,
                "error": str(exc),
            })

    passed = sum(1 for r in results if r["passed"])
    report = {
        "source": args.api or "local",
        "total": len(results),
        "passed": passed,
        "failed": len(results) - passed,
        "passed_all": passed == len(results),
        "results": results,
    }
    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps(report, ensure_ascii=False, indent=2))
    sys.exit(0 if report["passed_all"] else 1)


if __name__ == "__main__":
    main()
