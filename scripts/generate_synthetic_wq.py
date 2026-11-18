"""Generate realistic multi-year synthetic monthly water quality data for Jharkhand basins.

Adheres strictly to AGENTS.md integrity rules:
- Carries provenance: "synthetic"
- Encodes physical river phenomena:
  - Monsoon dilution (July-Oct): higher DO, lower conductivity, lower BOD, higher turbidity from runoff.
  - Pre-monsoon summer (March-May): lower DO, higher BOD, concentrated conductivity from industrial and municipal discharge.
  - Mining & industrial belt elevation: Bokaro & Dhanbad show elevated BOD, COD, and conductivity compared to upper Ramgarh.
"""

from __future__ import annotations

import csv
from pathlib import Path

import numpy as np
import pandas as pd


def generate_station_wq(
    station_id: str,
    base_bod: float,
    base_cod: float,
    base_cond: float,
    base_do: float,
    seed: int = 42,
) -> list[dict]:
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2019-01-15", "2023-12-15", freq="MS") + pd.Timedelta(days=14)

    rows = []
    for d in dates:
        month = d.month
        # Monsoon factor: peaks in Aug (month 8)
        is_monsoon = 6 <= month <= 10
        monsoon_intensity = np.sin((month - 5) / 5.0 * np.pi) if is_monsoon else 0.0

        # DO: higher in winter/monsoon, lower in hot pre-monsoon
        do = (
            base_do
            + (1.2 * monsoon_intensity)
            - (0.8 if 3 <= month <= 5 else 0.0)
            + rng.normal(0, 0.3)
        )
        do = float(np.clip(do, 1.5, 9.5))

        # BOD: diluted in monsoon, concentrated in summer
        bod = (
            base_bod
            - (1.2 * monsoon_intensity)
            + (1.0 if 3 <= month <= 5 else 0.0)
            + rng.normal(0, 0.4)
        )
        bod = float(np.clip(bod, 0.8, 25.0))

        # COD: roughly 3-5x BOD
        cod = base_cod + (bod * 3.5) - (5.0 * monsoon_intensity) + rng.normal(0, 2.0)
        cod = float(np.clip(cod, 5.0, 150.0))

        # Conductivity: lower during high runoff, higher during lean flow
        cond = (
            base_cond
            - (180.0 * monsoon_intensity)
            + (120.0 if 3 <= month <= 5 else 0.0)
            + rng.normal(0, 30.0)
        )
        cond = float(np.clip(cond, 100.0, 3000.0))

        # Turbidity: higher during monsoon runoff
        turb = 4.0 + (12.0 * monsoon_intensity) + rng.normal(0, 1.5)
        turb = float(np.clip(turb, 1.0, 80.0))

        # pH: mildly alkaline
        ph = 7.3 + (0.2 if is_monsoon else -0.1) + rng.normal(0, 0.15)
        ph = float(np.clip(ph, 6.2, 8.8))

        # Fecal Coliform
        fc = (
            (400.0 if base_bod < 3.0 else 1800.0)
            + (600.0 * monsoon_intensity)
            + rng.normal(0, 100.0)
        )
        fc = float(np.clip(fc, 50.0, 8000.0))

        rows.append(
            {
                "station_id": station_id,
                "date": d.strftime("%Y-%m-%d"),
                "ph": round(ph, 2),
                "dissolved_oxygen_mg_l": round(do, 2),
                "bod_mg_l": round(bod, 2),
                "cod_mg_l": round(cod, 2),
                "conductivity_us_cm": round(cond, 1),
                "turbidity_ntu": round(turb, 1),
                "fecal_coliform_mpn_100ml": round(fc, 1),
                "provenance": "synthetic",
            }
        )
    return rows


def main() -> None:
    stations = [
        ("damodar_ramgarh", 2.4, 15.0, 420.0, 6.8, 101),
        ("damodar_bokaro", 4.2, 28.0, 680.0, 5.4, 102),  # Industrial hotspot stretch
        ("damodar_dhanbad", 4.8, 35.0, 780.0, 5.1, 103),  # Jharia coalfield stretch
        ("subarnarekha_jamshedpur", 3.2, 22.0, 510.0, 6.2, 104),
        ("barakar_maithon", 2.1, 14.0, 390.0, 7.1, 105),
    ]

    all_rows = []
    for sid, bod, cod, cond, do, seed in stations:
        all_rows.extend(generate_station_wq(sid, bod, cod, cond, do, seed))

    out_path = Path("data/raw/wq/historical_monthly_wq_synthetic.csv")
    out_path.parent.mkdir(parents=True, exist_ok=True)

    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(all_rows[0].keys()))
        writer.writeheader()
        writer.writerows(all_rows)

    print(f"Generated {len(all_rows)} rows across {len(stations)} stations at {out_path}")


if __name__ == "__main__":
    main()
