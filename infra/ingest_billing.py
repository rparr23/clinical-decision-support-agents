"""Replace the demo fee schedule with a real one exported to CSV.

Expected columns: code, description, fee_nonrural, fee_rural, unit, coverage, limit_quantity, limit_days,
prior_auth_required (yes/no), prior_auth_note, category, keywords (semicolon separated).

    python infra/ingest_billing.py hca_respiratory.csv --extracted 2026-01-15 --source "WA HCA"
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

TARGET = Path(__file__).resolve().parents[1] / "cds" / "data" / "billing_respiratory_demo.json"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("csv", type=Path)
    ap.add_argument("--extracted", required=True, help="Date the fee schedule was extracted, YYYY-MM-DD")
    ap.add_argument("--source", default="WA HCA")
    args = ap.parse_args()
    doc = json.loads(TARGET.read_text())
    items = []
    with args.csv.open() as f:
        for r in csv.DictReader(f):
            items.append({
                "code": r["code"].strip().upper(), "description": r["description"].strip(),
                "fee_nonrural": float(r["fee_nonrural"]), "fee_rural": float(r.get("fee_rural") or r["fee_nonrural"]),
                "unit": r.get("unit", "each"), "coverage": r.get("coverage", "Covered"),
                "limit": {"quantity": int(r.get("limit_quantity") or 1), "days": int(r.get("limit_days") or 30)},
                "prior_auth_required": r.get("prior_auth_required", "").strip().lower() in ("yes", "y", "true", "1"),
                "prior_auth_note": r.get("prior_auth_note", ""), "category": r.get("category", "respiratory"),
                "keywords": [k.strip() for k in r.get("keywords", "").split(";") if k.strip()],
                "source": f"{args.source} (extracted {args.extracted})"})
    doc["items"] = items
    doc["source"].update({"extracted": args.extracted, "payer": args.source,
                          "note": f"Loaded from {args.csv.name}. Care plans reference codes; check they still exist."})
    TARGET.write_text(json.dumps(doc, indent=2))
    print(f"Wrote {len(items)} items to {TARGET}")


if __name__ == "__main__":
    main()
