# Water Quality Data Repository (CPCB NWMP / JSPCB)

## 1. Official Data Acquisition
Official river water quality monitoring in Jharkhand is conducted under the **National Water Quality Monitoring Programme (NWMP)** administered by the **Central Pollution Control Board (CPCB)** and the **Jharkhand State Pollution Control Board (JSPCB)**.

To download authentic monitoring bulletins and reports:
1. **CPCB Environmental Data Portal**: [https://cpcb.nic.in/water-quality-data/](https://cpcb.nic.in/water-quality-data/)
2. **India-WRIS Water Quality Module**: [https://indiawris.gov.in/wris/#/waterQuality](https://indiawris.gov.in/wris/#/waterQuality)
3. **Jharkhand SPCB Annual Reports**: [https://jspcb.nic.in](https://jspcb.nic.in)

Format files as CSV matching the columns below and place them in this directory.

---

## 2. CSV Schema Definition

Every CSV file ingested must adhere to the following schema:

| Column | Type | Unit | Range / Constraints | Description |
|---|---|---|---|---|
| `station_id` | string | — | Must match station in `config/stations.yaml` | Target monitoring station ID |
| `date` | string | — | `YYYY-MM-DD` | Date of water sampling |
| `ph` | float | pH units | 0.0 – 14.0 | Potential of Hydrogen |
| `dissolved_oxygen_mg_l` | float | mg/L | 0.0 – 30.0 | Dissolved Oxygen |
| `bod_mg_l` | float | mg/L | 0.0 – 500.0 | Biochemical Oxygen Demand (3-day, 27°C) |
| `cod_mg_l` | float | mg/L | 0.0 – 2000.0 | Chemical Oxygen Demand |
| `conductivity_us_cm` | float | µS/cm | 0.0 – 50000.0 | Electrical Conductivity |
| `turbidity_ntu` | float | NTU | 0.0 – 10000.0 | Nephelometric Turbidity |
| `fecal_coliform_mpn_100ml` | float | MPN/100mL | ≥ 0.0 | Most Probable Number of Fecal Coliforms |
| `provenance` | string | — | `observed` or `synthetic` | Non-negotiable provenance tag |

---

## 3. Synthetic Demo Notice
In strict compliance with **AGENTS.md Integrity Rule 2**, synthetic data is allowed ONLY for unit tests and local demonstrations. Any synthetic dataset must carry `provenance: synthetic`.
