"""OpenAPI 3.0 specification and Swagger UI documentation endpoints."""

from __future__ import annotations

from flask import Blueprint, Response, jsonify

docs_bp = Blueprint("docs", __name__)

OPENAPI_SPEC = {
    "openapi": "3.0.3",
    "info": {
        "title": "HydroPulse AI — Jharkhand River Health & Early Warning API",
        "description": (
            "Operational API for multi-horizon river discharge forecasting (1-7 days), "
            "drought/low-flow monitoring, and water quality indexing across Jharkhand river basins "
            "(Damodar, Subarnarekha, Konar, Barakar, Kharkai).\n\n"
            "**Advisory Notice**: This system is advisory and experimental. Official warnings "
            "are issued by the Central Water Commission (CWC) and Jharkhand State Disaster "
            "Management Authority (JSDMA)."
        ),
        "version": "0.1.0",
        "contact": {
            "name": "Om Kumar (HydroPulse AI Team)",
            "email": "hydropulse-ai@amity.edu",
        },
        "license": {
            "name": "MIT",
        },
    },
    "servers": [
        {"url": "/", "description": "Current Environment"},
    ],
    "tags": [
        {"name": "Health", "description": "System health and operational diagnostic endpoints"},
        {"name": "Stations", "description": "Candidate and verified river monitoring stations"},
        {
            "name": "Forecasts",
            "description": "Multi-horizon discharge predictions (t+1..t+7) and uncertainty",
        },
        {
            "name": "Alerts & Risk",
            "description": "Early warning alert status and GeoJSON risk mapping",
        },
        {
            "name": "River Health",
            "description": "CPCB WQI water quality scoring and SPI drought outlook",
        },
        {"name": "Model Governance", "description": "Model metrics, provenance, and data cards"},
    ],
    "paths": {
        "/api/v1/health": {
            "get": {
                "tags": ["Health"],
                "summary": "System Health Status",
                "description": "Returns operational status, version, and ISO timestamp with data provenance flag.",
                "responses": {
                    "200": {
                        "description": "System healthy",
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/HealthResponse"}
                            }
                        },
                    }
                },
            }
        },
        "/api/v1/stations": {
            "get": {
                "tags": ["Stations"],
                "summary": "List Monitoring Stations",
                "description": "Returns all configured candidate and verified river monitoring stations.",
                "responses": {
                    "200": {
                        "description": "List of monitoring stations",
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "stations": {
                                            "type": "array",
                                            "items": {"$ref": "#/components/schemas/Station"},
                                        },
                                        "count": {"type": "integer"},
                                        "generated_at": {"type": "string", "format": "date-time"},
                                    },
                                }
                            }
                        },
                    }
                },
            }
        },
        "/api/v1/stations/{id}/forecast": {
            "get": {
                "tags": ["Forecasts"],
                "summary": "Multi-horizon River Discharge Forecast",
                "description": "Retrieve 1 to 7-day river discharge forecasts with P10/P50/P90 uncertainty intervals.",
                "parameters": [
                    {
                        "name": "id",
                        "in": "path",
                        "required": True,
                        "schema": {"type": "string"},
                        "description": "Station identifier (e.g., damodar_dhanbad)",
                    },
                    {
                        "name": "days",
                        "in": "query",
                        "schema": {"type": "integer", "default": 7, "maximum": 7, "minimum": 1},
                        "description": "Forecast horizon days",
                    },
                ],
                "responses": {
                    "200": {
                        "description": "Discharge forecast time series",
                    }
                },
            }
        },
        "/api/v1/stations/{id}/history": {
            "get": {
                "tags": ["Forecasts"],
                "summary": "Historical Discharge & Precipitation Time Series",
                "description": "Retrieve past discharge and weather observations for a given station.",
                "parameters": [
                    {
                        "name": "id",
                        "in": "path",
                        "required": True,
                        "schema": {"type": "string"},
                        "description": "Station identifier",
                    },
                    {
                        "name": "days",
                        "in": "query",
                        "schema": {"type": "integer", "default": 30, "maximum": 365, "minimum": 1},
                        "description": "Number of historical days to return",
                    },
                ],
                "responses": {
                    "200": {
                        "description": "Historical time series",
                    }
                },
            }
        },
        "/api/v1/risk/map": {
            "get": {
                "tags": ["Alerts & Risk"],
                "summary": "Basin Risk GeoJSON",
                "description": "GeoJSON FeatureCollection of river stations with current risk levels.",
                "responses": {
                    "200": {
                        "description": "GeoJSON FeatureCollection",
                    }
                },
            }
        },
        "/api/v1/alerts": {
            "get": {
                "tags": ["Alerts & Risk"],
                "summary": "Active River Alerts",
                "description": "Returns stations currently at Watch, Warning, or Danger levels with bilingual messages.",
                "responses": {
                    "200": {
                        "description": "Active alert list with English and Hindi advisories",
                    }
                },
            }
        },
        "/api/v1/water-quality/{id}": {
            "get": {
                "tags": ["River Health"],
                "summary": "Water Quality Index & CPCB Class",
                "description": "Weighted-arithmetic WQI score and designated-best-use classification (A-E).",
                "parameters": [
                    {"name": "id", "in": "path", "required": True, "schema": {"type": "string"}}
                ],
                "responses": {"200": {"description": "WQI score and parameters"}},
            }
        },
        "/api/v1/drought/{id}": {
            "get": {
                "tags": ["River Health"],
                "summary": "Drought & Low-Flow Index",
                "description": "SPI-1, SPI-3, SPI-6 indices and Q90 low-flow stress flag.",
                "parameters": [
                    {"name": "id", "in": "path", "required": True, "schema": {"type": "string"}}
                ],
                "responses": {"200": {"description": "Drought metrics"}},
            }
        },
        "/api/v1/model/metrics": {
            "get": {
                "tags": ["Model Governance"],
                "summary": "Model Evaluation Metrics",
                "description": "Evaluation metrics (NSE, KGE, RMSE, MAE, POD, FAR, CSI) from reports/metrics.json.",
                "responses": {"200": {"description": "Evaluation metrics"}},
            }
        },
    },
    "components": {
        "schemas": {
            "HealthResponse": {
                "type": "object",
                "properties": {
                    "status": {"type": "string", "example": "healthy"},
                    "service": {"type": "string", "example": "hydropulse-ai"},
                    "version": {"type": "string", "example": "0.1.0"},
                    "environment": {"type": "string", "example": "development"},
                    "generated_at": {"type": "string", "format": "date-time"},
                    "data_provenance": {"type": "string", "example": "observed"},
                    "is_stale": {"type": "boolean", "example": False},
                    "checks": {
                        "type": "object",
                        "properties": {
                            "api": {"type": "string", "example": "ok"},
                            "config": {"type": "string", "example": "loaded"},
                        },
                    },
                },
                "required": [
                    "status",
                    "service",
                    "version",
                    "generated_at",
                    "data_provenance",
                    "is_stale",
                ],
            },
            "Station": {
                "type": "object",
                "properties": {
                    "id": {"type": "string", "example": "damodar_bokaro"},
                    "name": {"type": "string", "example": "Damodar at Bokaro"},
                    "river": {"type": "string", "example": "Damodar"},
                    "basin": {"type": "string", "example": "Damodar"},
                    "state": {"type": "string", "example": "Jharkhand"},
                    "district": {"type": "string", "example": "Bokaro"},
                    "latitude": {"type": "number", "example": 23.78},
                    "longitude": {"type": "number", "example": 85.96},
                    "verified": {"type": "boolean", "example": False},
                    "snap_to_river": {"type": "boolean", "example": True},
                    "cwc_code": {"type": "string", "nullable": True},
                },
            },
        }
    },
}

SWAGGER_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>HydroPulse AI — API Documentation & Interactive Testbench</title>
  <meta name="theme-color" content="#13140e">

  <!-- INVERSA Fonts: Inter & JetBrains Mono -->
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&family=JetBrains+Mono:wght@400;500;600;700&display=swap" rel="stylesheet">

  <!-- Swagger UI 5.11.0 Base Styles -->
  <link rel="stylesheet" type="text/css" href="https://unpkg.com/swagger-ui-dist@5.11.0/swagger-ui.css">

  <style>
    /* ==========================================================================
       INVERSA DESIGN SYSTEM — TOPOGRAPHIC FIELD TERMINAL (API DOCS)
       Obsidian Loam (#13140e) canvas, Bone Vellum (#f4f3e8) editorial text,
       Iron Filings (#404040) hairline borders, Lime Surveyor (#ebfc72) neon accents.
       Utilitarian, shadowless, 3.6px radii, JetBrains Mono telemetry.
       ========================================================================== */

    :root {
      --color-obsidian-loam: #13140e;
      --color-bone-vellum: #f4f3e8;
      --color-iron-filings: #404040;
      --color-drift-ash: #84837b;
      --color-lime-surveyor: #ebfc72;
      --color-marsh-olive: #bacd31;
      --color-panel-bg: #161710;
      --color-elevated-bg: #181912;
      --color-code-bg: #0d0e0a;
      --color-subtle-border: #282920;
      --color-alert-danger: #ef4444;
      --color-alert-warn: #f59e0b;
      --radius-sm: 3.6px;
      --font-sans: 'Inter', -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      --font-mono: 'JetBrains Mono', ui-monospace, Menlo, Monaco, Consolas, monospace;
    }

    *, *::before, *::after {
      box-sizing: border-box;
      margin: 0;
      padding: 0;
    }

    html, body {
      background-color: var(--color-obsidian-loam);
      color: var(--color-bone-vellum);
      font-family: var(--font-sans);
      font-size: 14px;
      line-height: 1.5;
      -webkit-font-smoothing: antialiased;
      -moz-osx-font-smoothing: grayscale;
      min-height: 100vh;
      display: flex;
      flex-direction: column;
    }

    /* ── Terminal Navigation Header ────────────────────────────────────────── */
    .terminal-header {
      background: var(--color-obsidian-loam);
      border-bottom: 1px solid var(--color-iron-filings);
      position: sticky;
      top: 0;
      z-index: 1000;
    }

    .header-container {
      max-width: 1380px;
      margin: 0 auto;
      padding: 14px 24px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
      flex-wrap: wrap;
    }

    .brand-section {
      display: flex;
      align-items: center;
      gap: 14px;
    }

    .brand-emblem {
      width: 34px;
      height: 34px;
      background: var(--color-panel-bg);
      border: 1px solid var(--color-iron-filings);
      border-radius: var(--radius-sm);
      display: flex;
      align-items: center;
      justify-content: center;
      color: var(--color-lime-surveyor);
    }

    .brand-title-wrap {
      display: flex;
      flex-direction: column;
    }

    .brand-title {
      font-size: 1.15rem;
      font-weight: 800;
      letter-spacing: -0.025em;
      color: var(--color-bone-vellum);
      display: flex;
      align-items: center;
      gap: 8px;
      text-decoration: none;
    }

    .brand-accent {
      color: var(--color-lime-surveyor);
    }

    .badge-terminal {
      font-family: var(--font-mono);
      font-size: 0.68rem;
      font-weight: 700;
      padding: 2px 7px;
      border-radius: var(--radius-sm);
      background: rgba(235, 252, 114, 0.1);
      color: var(--color-lime-surveyor);
      border: 1px solid rgba(235, 252, 114, 0.35);
      letter-spacing: 0.04em;
      text-transform: uppercase;
    }

    .brand-subtitle {
      font-family: var(--font-mono);
      font-size: 0.72rem;
      color: var(--color-drift-ash);
      letter-spacing: 0.02em;
      text-transform: uppercase;
      margin-top: 1px;
    }

    .header-actions {
      display: flex;
      align-items: center;
      gap: 12px;
      flex-wrap: wrap;
    }

    .telemetry-pill {
      display: inline-flex;
      align-items: center;
      gap: 7px;
      padding: 5px 11px;
      background: var(--color-panel-bg);
      border: 1px solid var(--color-iron-filings);
      border-radius: var(--radius-sm);
      font-family: var(--font-mono);
      font-size: 0.73rem;
      color: var(--color-bone-vellum);
      letter-spacing: 0.03em;
    }

    .pulse-dot {
      width: 7px;
      height: 7px;
      border-radius: 50%;
      background: var(--color-lime-surveyor);
      box-shadow: 0 0 6px var(--color-lime-surveyor);
      animation: pulseAnim 2s infinite ease-in-out;
    }

    @keyframes pulseAnim {
      0%, 100% { opacity: 1; transform: scale(1); }
      50% { opacity: 0.45; transform: scale(0.85); }
    }

    .clock-pill {
      font-family: var(--font-mono);
      font-size: 0.73rem;
      font-weight: 600;
      color: var(--color-lime-surveyor);
      background: var(--color-panel-bg);
      border: 1px solid var(--color-iron-filings);
      border-radius: var(--radius-sm);
      padding: 5px 11px;
      min-width: 96px;
      text-align: center;
    }

    .action-btn {
      display: inline-flex;
      align-items: center;
      gap: 7px;
      padding: 6px 14px;
      border-radius: var(--radius-sm);
      font-family: var(--font-mono);
      font-size: 0.76rem;
      font-weight: 700;
      text-decoration: none;
      transition: all 0.15s ease;
      letter-spacing: 0.03em;
    }

    .action-btn.return-btn {
      background: var(--color-lime-surveyor);
      color: var(--color-obsidian-loam);
      border: 1px solid var(--color-lime-surveyor);
    }

    .action-btn.return-btn:hover {
      background: var(--color-marsh-olive);
      border-color: var(--color-marsh-olive);
    }

    .action-btn.spec-btn {
      background: var(--color-panel-bg);
      color: var(--color-bone-vellum);
      border: 1px solid var(--color-iron-filings);
    }

    .action-btn.spec-btn:hover {
      border-color: var(--color-lime-surveyor);
      color: var(--color-lime-surveyor);
    }

    /* ── Statutory Advisory Banner ─────────────────────────────────────────── */
    .advisory-banner {
      background: #0f100b;
      border-top: 1px solid var(--color-subtle-border);
      border-bottom: 1px solid var(--color-iron-filings);
      padding: 7px 24px;
      display: flex;
      align-items: center;
      justify-content: center;
      gap: 10px;
      font-size: 0.76rem;
      line-height: 1.4;
      text-align: center;
    }

    .advisory-icon {
      color: var(--color-alert-warn);
      flex-shrink: 0;
    }

    .advisory-text {
      color: var(--color-drift-ash);
    }

    .advisory-text strong {
      color: var(--color-bone-vellum);
    }

    /* ── Swagger UI Native INVERSA Styles ──────────────────────────────────── */
    .doc-container {
      max-width: 1380px;
      margin: 0 auto;
      padding: 24px;
      flex: 1;
      width: 100%;
    }

    .swagger-ui {
      font-family: var(--font-sans) !important;
      color: var(--color-bone-vellum) !important;
    }

    .swagger-ui .wrapper {
      padding: 0 !important;
      max-width: 100% !important;
    }

    .swagger-ui .topbar {
      display: none !important;
    }

    /* Info Header Block */
    .swagger-ui .info {
      margin: 10px 0 28px !important;
      padding-bottom: 22px !important;
      border-bottom: 1px solid var(--color-iron-filings) !important;
    }

    .swagger-ui .info .title {
      font-family: var(--font-sans) !important;
      color: var(--color-bone-vellum) !important;
      font-weight: 800 !important;
      font-size: 1.85rem !important;
      letter-spacing: -0.035em !important;
      line-height: 1.2 !important;
    }

    .swagger-ui .info .title small {
      background: var(--color-panel-bg) !important;
      border: 1px solid var(--color-lime-surveyor) !important;
      color: var(--color-lime-surveyor) !important;
      border-radius: var(--radius-sm) !important;
      font-family: var(--font-mono) !important;
      font-size: 0.72rem !important;
      font-weight: 700 !important;
      padding: 3px 8px !important;
      margin-left: 10px !important;
      vertical-align: middle !important;
    }

    .swagger-ui .info .title small.version-stamp {
      background: var(--color-panel-bg) !important;
    }

    .swagger-ui .info .description {
      color: var(--color-drift-ash) !important;
      font-size: 0.94rem !important;
      line-height: 1.65 !important;
      margin-top: 14px !important;
    }

    .swagger-ui .info .description p {
      color: var(--color-drift-ash) !important;
      margin-bottom: 10px !important;
    }

    .swagger-ui .info .description strong {
      color: var(--color-bone-vellum) !important;
    }

    .swagger-ui .info a {
      color: var(--color-lime-surveyor) !important;
      text-decoration: underline !important;
      text-underline-offset: 3px !important;
    }

    /* Scheme / Server Container */
    .swagger-ui .scheme-container {
      background: var(--color-panel-bg) !important;
      border: 1px solid var(--color-iron-filings) !important;
      border-radius: var(--radius-sm) !important;
      box-shadow: none !important;
      padding: 14px 20px !important;
      margin: 0 0 24px !important;
    }

    .swagger-ui .schemes-title,
    .swagger-ui .servers-title {
      color: var(--color-bone-vellum) !important;
      font-family: var(--font-mono) !important;
      font-size: 0.78rem !important;
      font-weight: 700 !important;
      text-transform: uppercase !important;
      letter-spacing: 0.04em !important;
    }

    .swagger-ui .servers > label select {
      background: var(--color-obsidian-loam) !important;
      color: var(--color-bone-vellum) !important;
      border: 1px solid var(--color-iron-filings) !important;
      border-radius: var(--radius-sm) !important;
      padding: 6px 12px !important;
      font-family: var(--font-mono) !important;
      font-size: 0.82rem !important;
      margin-left: 10px !important;
      outline: none !important;
    }

    .swagger-ui .servers > label select:focus {
      border-color: var(--color-lime-surveyor) !important;
    }

    /* Filter Bar */
    .swagger-ui .filter {
      margin: 0 0 24px !important;
      padding: 0 !important;
    }

    .swagger-ui .filter .operation-filter-input {
      background: var(--color-panel-bg) !important;
      color: var(--color-bone-vellum) !important;
      border: 1px solid var(--color-iron-filings) !important;
      border-radius: var(--radius-sm) !important;
      padding: 9px 14px !important;
      font-family: var(--font-mono) !important;
      font-size: 0.84rem !important;
      width: 100% !important;
      max-width: 420px !important;
      box-shadow: none !important;
    }

    .swagger-ui .filter .operation-filter-input:focus {
      border-color: var(--color-lime-surveyor) !important;
      outline: none !important;
    }

    .swagger-ui .filter .operation-filter-input::placeholder {
      color: #5e5d56 !important;
    }

    /* Section Tag Headers */
    .swagger-ui .opblock-tag-section {
      margin-bottom: 24px !important;
    }

    .swagger-ui .opblock-tag {
      color: var(--color-bone-vellum) !important;
      font-family: var(--font-sans) !important;
      font-weight: 800 !important;
      font-size: 1.22rem !important;
      letter-spacing: -0.025em !important;
      border-bottom: 1px solid var(--color-iron-filings) !important;
      padding: 14px 0 10px !important;
      margin-bottom: 12px !important;
    }

    .swagger-ui .opblock-tag:hover {
      background: transparent !important;
      color: var(--color-lime-surveyor) !important;
    }

    .swagger-ui .opblock-tag small {
      color: var(--color-drift-ash) !important;
      font-family: var(--font-mono) !important;
      font-size: 0.78rem !important;
      font-weight: 500 !important;
      margin-left: 14px !important;
    }

    .swagger-ui .opblock-tag svg {
      fill: var(--color-drift-ash) !important;
    }

    /* Operation Blocks */
    .swagger-ui .opblock {
      background: var(--color-panel-bg) !important;
      border: 1px solid var(--color-iron-filings) !important;
      border-radius: var(--radius-sm) !important;
      box-shadow: none !important;
      margin: 0 0 10px !important;
      transition: border-color 0.15s ease !important;
    }

    .swagger-ui .opblock:hover {
      border-color: var(--color-drift-ash) !important;
    }

    .swagger-ui .opblock.is-open {
      border-color: var(--color-lime-surveyor) !important;
    }

    .swagger-ui .opblock .opblock-summary {
      padding: 10px 16px !important;
      display: flex !important;
      align-items: center !important;
      border-color: transparent !important;
    }

    /* Method Badges */
    .swagger-ui .opblock .opblock-summary-method {
      font-family: var(--font-mono) !important;
      font-weight: 700 !important;
      font-size: 0.74rem !important;
      min-width: 68px !important;
      padding: 5px 0 !important;
      border-radius: var(--radius-sm) !important;
      text-align: center !important;
      text-shadow: none !important;
      letter-spacing: 0.05em !important;
    }

    .swagger-ui .opblock.opblock-get .opblock-summary-method {
      background: var(--color-elevated-bg) !important;
      color: var(--color-lime-surveyor) !important;
      border: 1px solid var(--color-lime-surveyor) !important;
    }

    .swagger-ui .opblock.opblock-post .opblock-summary-method {
      background: var(--color-elevated-bg) !important;
      color: var(--color-marsh-olive) !important;
      border: 1px solid var(--color-marsh-olive) !important;
    }

    .swagger-ui .opblock.opblock-put .opblock-summary-method {
      background: var(--color-elevated-bg) !important;
      color: var(--color-alert-warn) !important;
      border: 1px solid var(--color-alert-warn) !important;
    }

    .swagger-ui .opblock.opblock-delete .opblock-summary-method {
      background: var(--color-elevated-bg) !important;
      color: var(--color-alert-danger) !important;
      border: 1px solid var(--color-alert-danger) !important;
    }

    /* Path and Descriptions */
    .swagger-ui .opblock .opblock-summary-path {
      color: var(--color-bone-vellum) !important;
      font-family: var(--font-mono) !important;
      font-size: 0.90rem !important;
      font-weight: 600 !important;
      padding: 0 12px !important;
    }

    .swagger-ui .opblock .opblock-summary-path a {
      color: var(--color-bone-vellum) !important;
    }

    .swagger-ui .opblock .opblock-summary-description {
      color: var(--color-drift-ash) !important;
      font-family: var(--font-sans) !important;
      font-size: 0.84rem !important;
    }

    .swagger-ui .opblock .arrow {
      fill: var(--color-drift-ash) !important;
    }

    /* Operation Body (Expanded) */
    .swagger-ui .opblock-body {
      background: var(--color-obsidian-loam) !important;
      border-top: 1px solid var(--color-iron-filings) !important;
      padding: 20px !important;
    }

    .swagger-ui .opblock-section-header {
      background: var(--color-panel-bg) !important;
      border: 1px solid var(--color-iron-filings) !important;
      border-radius: var(--radius-sm) !important;
      box-shadow: none !important;
      padding: 8px 14px !important;
      margin-bottom: 14px !important;
    }

    .swagger-ui .opblock-section-header h4 {
      color: var(--color-bone-vellum) !important;
      font-family: var(--font-mono) !important;
      font-size: 0.76rem !important;
      font-weight: 700 !important;
      text-transform: uppercase !important;
      letter-spacing: 0.05em !important;
    }

    .swagger-ui .opblock-description-wrapper p {
      color: var(--color-bone-vellum) !important;
      font-size: 0.88rem !important;
      line-height: 1.55 !important;
    }

    /* Buttons */
    .swagger-ui .btn {
      font-family: var(--font-mono) !important;
      border-radius: var(--radius-sm) !important;
      font-weight: 700 !important;
      box-shadow: none !important;
      transition: all 0.15s ease !important;
    }

    .swagger-ui .btn.try-out__btn {
      background: var(--color-panel-bg) !important;
      border: 1px solid var(--color-lime-surveyor) !important;
      color: var(--color-lime-surveyor) !important;
      padding: 5px 14px !important;
      font-size: 0.74rem !important;
      text-transform: uppercase !important;
      letter-spacing: 0.04em !important;
    }

    .swagger-ui .btn.try-out__btn:hover {
      background: var(--color-lime-surveyor) !important;
      color: var(--color-obsidian-loam) !important;
    }

    .swagger-ui .btn.try-out__btn.cancel {
      border-color: var(--color-alert-warn) !important;
      color: var(--color-alert-warn) !important;
    }

    .swagger-ui .btn.try-out__btn.cancel:hover {
      background: var(--color-alert-warn) !important;
      color: var(--color-obsidian-loam) !important;
    }

    .swagger-ui .btn.execute {
      background: var(--color-lime-surveyor) !important;
      color: var(--color-obsidian-loam) !important;
      border: 1px solid var(--color-lime-surveyor) !important;
      font-weight: 800 !important;
      font-size: 0.82rem !important;
      padding: 9px 28px !important;
      text-transform: uppercase !important;
      letter-spacing: 0.06em !important;
    }

    .swagger-ui .btn.execute:hover {
      background: var(--color-marsh-olive) !important;
      border-color: var(--color-marsh-olive) !important;
    }

    .swagger-ui .btn-clear {
      background: transparent !important;
      border: 1px solid var(--color-drift-ash) !important;
      color: var(--color-drift-ash) !important;
      font-size: 0.74rem !important;
      text-transform: uppercase !important;
      padding: 5px 12px !important;
    }

    .swagger-ui .btn-clear:hover {
      border-color: var(--color-bone-vellum) !important;
      color: var(--color-bone-vellum) !important;
    }

    /* Tables */
    .swagger-ui table {
      border-collapse: collapse !important;
      width: 100% !important;
    }

    .swagger-ui table thead tr th {
      color: var(--color-drift-ash) !important;
      font-family: var(--font-mono) !important;
      font-size: 0.70rem !important;
      font-weight: 700 !important;
      text-transform: uppercase !important;
      letter-spacing: 0.06em !important;
      border-bottom: 1px solid var(--color-iron-filings) !important;
      padding: 10px 8px !important;
    }

    .swagger-ui table tbody tr td {
      border-bottom: 1px solid var(--color-subtle-border) !important;
      padding: 12px 8px !important;
      color: var(--color-bone-vellum) !important;
      vertical-align: top !important;
    }

    .swagger-ui .parameters-container,
    .swagger-ui .responses-wrapper {
      background: transparent !important;
    }

    .swagger-ui .parameter__name {
      color: var(--color-lime-surveyor) !important;
      font-family: var(--font-mono) !important;
      font-size: 0.82rem !important;
      font-weight: 700 !important;
    }

    .swagger-ui .parameter__name.required::after {
      content: " [REQUIRED]" !important;
      color: var(--color-alert-danger) !important;
      font-size: 0.68rem !important;
      font-weight: 700 !important;
    }

    .swagger-ui .parameter__type {
      color: var(--color-drift-ash) !important;
      font-family: var(--font-mono) !important;
      font-size: 0.72rem !important;
      margin-top: 2px !important;
    }

    .swagger-ui .parameter__in {
      color: #5e5d56 !important;
      font-family: var(--font-mono) !important;
      font-size: 0.70rem !important;
    }

    /* Inputs, Textareas, Selects */
    .swagger-ui input[type="text"],
    .swagger-ui select,
    .swagger-ui textarea {
      background: var(--color-panel-bg) !important;
      border: 1px solid var(--color-iron-filings) !important;
      color: var(--color-bone-vellum) !important;
      border-radius: var(--radius-sm) !important;
      font-family: var(--font-mono) !important;
      font-size: 0.82rem !important;
      padding: 7px 10px !important;
      box-shadow: none !important;
    }

    .swagger-ui input[type="text"]:focus,
    .swagger-ui select:focus,
    .swagger-ui textarea:focus {
      border-color: var(--color-lime-surveyor) !important;
      outline: none !important;
    }

    /* Response Blocks */
    .swagger-ui .response-col_status {
      font-family: var(--font-mono) !important;
      font-weight: 700 !important;
      font-size: 0.92rem !important;
      color: var(--color-lime-surveyor) !important;
    }

    .swagger-ui .response-col_description {
      color: var(--color-bone-vellum) !important;
      font-size: 0.85rem !important;
    }

    .swagger-ui .response-col_links {
      color: var(--color-drift-ash) !important;
      font-family: var(--font-mono) !important;
      font-size: 0.76rem !important;
    }

    .swagger-ui .responses-inner h4,
    .swagger-ui .responses-inner h5 {
      color: var(--color-bone-vellum) !important;
      font-family: var(--font-mono) !important;
      font-size: 0.76rem !important;
      text-transform: uppercase !important;
      letter-spacing: 0.04em !important;
    }

    .swagger-ui .response-control-media-type__title {
      color: var(--color-drift-ash) !important;
      font-family: var(--font-mono) !important;
      font-size: 0.74rem !important;
    }

    /* Code Pre & Highlight Blocks */
    .swagger-ui .microlight,
    .swagger-ui pre,
    .swagger-ui .highlight-code pre {
      background: var(--color-code-bg) !important;
      border: 1px solid #33342b !important;
      border-radius: var(--radius-sm) !important;
      color: var(--color-bone-vellum) !important;
      font-family: var(--font-mono) !important;
      font-size: 0.80rem !important;
      line-height: 1.55 !important;
      padding: 14px 16px !important;
    }

    .swagger-ui .curl-command {
      background: var(--color-code-bg) !important;
      border: 1px solid #33342b !important;
      border-radius: var(--radius-sm) !important;
      margin-bottom: 12px !important;
    }

    .swagger-ui .curl-command pre {
      background: transparent !important;
      border: none !important;
      padding: 12px 14px !important;
    }

    .swagger-ui .request-url pre {
      background: var(--color-code-bg) !important;
      border: 1px solid #33342b !important;
      border-radius: var(--radius-sm) !important;
      color: var(--color-lime-surveyor) !important;
      font-family: var(--font-mono) !important;
      padding: 10px 14px !important;
    }

    .swagger-ui .copy-to-clipboard,
    .swagger-ui .download-contents {
      background: var(--color-panel-bg) !important;
      border: 1px solid var(--color-iron-filings) !important;
      color: var(--color-drift-ash) !important;
      border-radius: var(--radius-sm) !important;
      padding: 4px 10px !important;
      font-family: var(--font-mono) !important;
      font-size: 0.70rem !important;
      font-weight: 600 !important;
    }

    .swagger-ui .copy-to-clipboard:hover,
    .swagger-ui .download-contents:hover {
      border-color: var(--color-lime-surveyor) !important;
      color: var(--color-lime-surveyor) !important;
    }

    /* Tabs */
    .swagger-ui .tab {
      color: var(--color-drift-ash) !important;
      font-family: var(--font-mono) !important;
      font-size: 0.74rem !important;
    }

    .swagger-ui .tab.active {
      color: var(--color-lime-surveyor) !important;
      font-weight: 700 !important;
    }

    /* Models / Schemas Accordion */
    .swagger-ui section.models {
      background: var(--color-panel-bg) !important;
      border: 1px solid var(--color-iron-filings) !important;
      border-radius: var(--radius-sm) !important;
      box-shadow: none !important;
      margin-top: 36px !important;
    }

    .swagger-ui section.models h4 {
      color: var(--color-bone-vellum) !important;
      font-family: var(--font-mono) !important;
      font-size: 0.88rem !important;
      font-weight: 700 !important;
      text-transform: uppercase !important;
      letter-spacing: 0.05em !important;
      border-bottom: 1px solid var(--color-iron-filings) !important;
      padding: 14px 18px !important;
    }

    .swagger-ui section.models h4 svg {
      fill: var(--color-drift-ash) !important;
    }

    .swagger-ui .model-container {
      background: var(--color-obsidian-loam) !important;
      border-bottom: 1px solid var(--color-subtle-border) !important;
      padding: 14px 18px !important;
    }

    .swagger-ui .model-title {
      color: var(--color-lime-surveyor) !important;
      font-family: var(--font-mono) !important;
      font-size: 0.84rem !important;
      font-weight: 700 !important;
    }

    .swagger-ui .model-box {
      background: transparent !important;
    }

    .swagger-ui .property {
      color: var(--color-lime-surveyor) !important;
      font-family: var(--font-mono) !important;
    }

    .swagger-ui .prop-type {
      color: var(--color-drift-ash) !important;
      font-family: var(--font-mono) !important;
      font-size: 0.76rem !important;
    }

    .swagger-ui .model-hint {
      color: #5e5d56 !important;
    }

    .swagger-ui label {
      color: var(--color-drift-ash) !important;
      font-family: var(--font-mono) !important;
      font-size: 0.74rem !important;
    }

    .swagger-ui .loading-container {
      padding: 50px 0 !important;
      text-align: center !important;
    }

    .swagger-ui .loading-container .loading::after {
      color: var(--color-lime-surveyor) !important;
      font-family: var(--font-mono) !important;
      font-size: 0.88rem !important;
    }

    /* ── Terminal Footer ───────────────────────────────────────────────────── */
    .terminal-footer {
      background: var(--color-obsidian-loam);
      border-top: 1px solid var(--color-iron-filings);
      padding: 18px 24px;
      margin-top: auto;
    }

    .footer-container {
      max-width: 1380px;
      margin: 0 auto;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
      flex-wrap: wrap;
    }

    .footer-attribution {
      font-family: var(--font-mono);
      font-size: 0.75rem;
      color: var(--color-bone-vellum);
    }

    .footer-links {
      display: flex;
      align-items: center;
      gap: 12px;
      font-family: var(--font-mono);
      font-size: 0.73rem;
    }

    .footer-links a {
      color: var(--color-drift-ash);
      text-decoration: none;
      transition: color 0.15s ease;
    }

    .footer-links a:hover {
      color: var(--color-lime-surveyor);
    }

    .footer-links .divider {
      color: var(--color-iron-filings);
    }
  </style>
</head>
<body>
  <!-- Top Navigation Header -->
  <header class="terminal-header" role="banner">
    <div class="header-container">
      <div class="brand-section">
        <div class="brand-emblem" aria-hidden="true">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M12 2.69l5.66 5.66a8 8 0 1 1-11.31 0z"></path>
            <path d="M12 12c.5-1 1.5-1.5 2.5-1.5 1.5 0 2.5 1 2.5 2.5 0 1.5-1 2.5-2.5 2.5-.5 0-1.5-.5-2.5-1.5"></path>
          </svg>
        </div>
        <div class="brand-title-wrap">
          <a href="/dashboard" class="brand-title">
            <span><span class="brand-accent">HydroPulse</span> AI</span>
            <span class="badge-terminal">REST v1</span>
          </a>
          <span class="brand-subtitle">Jharkhand River Basins • API Reference & Testbench</span>
        </div>
      </div>

      <div class="header-actions">
        <!-- Live Telemetry Pill -->
        <div class="telemetry-pill" title="Operational status of API services">
          <span class="pulse-dot"></span>
          <span>9 ENDPOINTS ONLINE</span>
        </div>

        <!-- Live Clock Pill (IST) -->
        <div class="clock-pill" id="live-ist-clock" title="Current Indian Standard Time (IST)">
          --:--:-- IST
        </div>

        <!-- Dashboard Navigation Button -->
        <a href="/dashboard" class="action-btn return-btn" title="Return to Interactive River Dashboard">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.3" stroke-linecap="round" stroke-linejoin="round">
            <line x1="19" y1="12" x2="5" y2="12"></line>
            <polyline points="12 19 5 12 12 5"></polyline>
          </svg>
          <span>DASHBOARD</span>
        </a>

        <!-- Raw OpenAPI Spec Button -->
        <a href="/api/v1/openapi.json" target="_blank" rel="noopener" class="action-btn spec-btn" title="Inspect raw OpenAPI 3.0 JSON specification">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <polyline points="16 18 22 12 16 6"></polyline>
            <polyline points="8 6 2 12 8 18"></polyline>
          </svg>
          <span>OPENAPI.JSON</span>
        </a>
      </div>
    </div>

    <!-- Statutory Advisory Disclaimer Banner (Rule 2.7) -->
    <div class="advisory-banner" role="alert">
      <span class="advisory-icon" aria-hidden="true">⚠️</span>
      <div class="advisory-text">
        <strong>STATUTORY ADVISORY:</strong>
        HydroPulse AI is an advisory decision-support system. Official flood warnings, discharge alerts, and reservoir releases are issued exclusively by the <strong>Central Water Commission (CWC)</strong> and <strong>Jharkhand State Disaster Management Authority (JSDMA)</strong>.
      </div>
    </div>
  </header>

  <!-- Interactive Swagger Mount -->
  <main class="doc-container" role="main">
    <div id="swagger-ui"></div>
  </main>

  <!-- Accessible Field Terminal Footer -->
  <footer class="terminal-footer" role="contentinfo">
    <div class="footer-container">
      <div class="footer-attribution">
        <span>HydroPulse AI • Developed by Om Kumar</span>
      </div>
      <div class="footer-links">
        <a href="/dashboard">← Live Dashboard</a>
        <span class="divider">/</span>
        <a href="/api/v1/model/metrics" target="_blank" rel="noopener">Model Metrics</a>
        <span class="divider">/</span>
        <a href="/api/v1/openapi.json" target="_blank" rel="noopener">OpenAPI Specification</a>
      </div>
    </div>
  </footer>

  <script src="https://unpkg.com/swagger-ui-dist@5.11.0/swagger-ui-bundle.js"></script>
  <script>
    // Live Indian Standard Time (IST) Clock
    function updateClock() {
      const el = document.getElementById('live-ist-clock');
      if (!el) return;
      const now = new Date();
      const timeStr = now.toLocaleTimeString('en-IN', {
        timeZone: 'Asia/Kolkata',
        hour12: false,
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit'
      });
      el.textContent = timeStr + ' IST';
    }
    setInterval(updateClock, 1000);
    updateClock();

    // Mount Swagger UI 5.x Interactive Testbench
    window.onload = function() {
      SwaggerUIBundle({
        url: "/api/v1/openapi.json",
        dom_id: '#swagger-ui',
        deepLinking: true,
        presets: [
          SwaggerUIBundle.presets.apis,
          SwaggerUIBundle.SwaggerUIStandalonePreset
        ],
        layout: "BaseLayout",
        defaultModelsExpandDepth: 1,
        defaultModelExpandDepth: 1,
        docExpansion: "list",
        displayRequestDuration: true,
        filter: true,
        tryItOutEnabled: true
      });
    };
  </script>
</body>
</html>
"""


@docs_bp.route("/api/v1/openapi.json", methods=["GET"])
def get_openapi_spec():
    """Return the raw OpenAPI 3.0 JSON specification."""
    return jsonify(OPENAPI_SPEC)


@docs_bp.route("/docs", methods=["GET"])
@docs_bp.route("/api/v1/docs", methods=["GET"])
def get_swagger_ui():
    """Render interactive Swagger UI."""
    return Response(SWAGGER_HTML, mimetype="text/html")
