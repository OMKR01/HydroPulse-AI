"""Central Pollution Control Board (CPCB) NWMP Water Quality loader and validator.

Validates river water quality records against physical ranges (pH, DO, BOD, COD, conductivity,
turbidity, fecal coliform) using Pydantic and stores them with provenance tagging.
"""

from __future__ import annotations

import csv
import logging
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from src.hydropulse.ingest.storage import record_audit, upsert_wq_records

logger = logging.getLogger(__name__)


class CPCBWaterQualityItem(BaseModel):
    """Pydantic validation schema for CPCB NWMP monthly water quality observations."""

    station_id: str = Field(..., min_length=2, description="Target station identifier")
    date: str = Field(
        ..., pattern=r"^\d{4}-\d{2}-\d{2}$", description="Sampling date in YYYY-MM-DD"
    )
    ph: float | None = Field(default=None, ge=0.0, le=14.0, description="pH units (0-14)")
    dissolved_oxygen_mg_l: float | None = Field(
        default=None, ge=0.0, le=30.0, description="Dissolved Oxygen in mg/L"
    )
    bod_mg_l: float | None = Field(
        default=None, ge=0.0, le=500.0, description="Biochemical Oxygen Demand in mg/L"
    )
    cod_mg_l: float | None = Field(
        default=None, ge=0.0, le=2000.0, description="Chemical Oxygen Demand in mg/L"
    )
    conductivity_us_cm: float | None = Field(
        default=None, ge=0.0, le=50000.0, description="Electrical Conductivity in µS/cm"
    )
    turbidity_ntu: float | None = Field(
        default=None, ge=0.0, le=10000.0, description="Turbidity in NTU"
    )
    fecal_coliform_mpn_100ml: float | None = Field(
        default=None, ge=0.0, description="Fecal Coliform count in MPN/100mL"
    )
    provenance: Literal["observed", "synthetic"] = Field(
        default="observed", description="Data provenance classification"
    )

    @field_validator(
        "ph",
        "dissolved_oxygen_mg_l",
        "bod_mg_l",
        "cod_mg_l",
        "conductivity_us_cm",
        "turbidity_ntu",
        "fecal_coliform_mpn_100ml",
        mode="before",
    )
    @classmethod
    def parse_optional_float(cls, v: Any) -> float | None:
        if v is None or v == "" or str(v).strip().lower() in ("null", "none", "nan", "-"):
            return None
        return float(v)


def load_and_validate_cpcb_csv(csv_path: str | Path) -> list[dict[str, Any]]:
    """Parse and validate a CPCB/JSPCB water quality CSV file.

    Raises:
        FileNotFoundError: If the CSV path does not exist.
        pydantic.ValidationError: If any row fails physical schema constraints.
    """
    path = Path(csv_path)
    if not path.exists():
        raise FileNotFoundError(f"Water quality CSV not found at {path}")

    validated_records: list[dict[str, Any]] = []

    with open(path, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row_idx, row in enumerate(reader, start=2):
            try:
                # Normalize keys (strip whitespace and lower)
                clean_row = {k.strip(): v for k, v in row.items() if k}
                item = CPCBWaterQualityItem(**clean_row)
                validated_records.append(item.model_dump())
            except Exception as err:
                logger.error("Validation error in %s at row %d: %s", path.name, row_idx, err)
                raise err

    return validated_records


def ingest_cpcb_directory(
    directory_path: str | Path,
    db_target: str | Path | None = None,
) -> int:
    """Scan directory for *.csv water quality files, validate and upsert them to storage."""
    target_dir = Path(directory_path)
    if not target_dir.exists():
        logger.warning("Directory %s does not exist; skipping WQ ingestion.", target_dir)
        return 0

    total_ingested = 0
    csv_files = list(target_dir.glob("*.csv"))

    for csv_file in csv_files:
        try:
            records = load_and_validate_cpcb_csv(csv_file)
            count = upsert_wq_records(records, db_target=db_target)
            total_ingested += count
            record_audit(
                source_name="cpcb_wq",
                status="success",
                records_ingested=count,
                error_message=f"File: {csv_file.name}",
                db_target=db_target,
            )
            logger.info("Ingested %d WQ records from %s", count, csv_file.name)
        except Exception as exc:
            record_audit(
                source_name="cpcb_wq",
                status="failed",
                records_ingested=0,
                error_message=f"{csv_file.name}: {exc}",
                db_target=db_target,
            )
            logger.error("Failed to ingest %s: %s", csv_file.name, exc)

    return total_ingested
