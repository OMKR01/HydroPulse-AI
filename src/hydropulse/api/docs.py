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
  <title>HydroPulse AI — API Documentation</title>
  <link rel="stylesheet" type="text/css" href="https://unpkg.com/swagger-ui-dist@5.11.0/swagger-ui.css">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
  <style>
    body {
      margin: 0;
      background: #0b1120;
      color: #f1f5f9;
      font-family: 'Outfit', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    }
    .top-banner {
      background: linear-gradient(135deg, #0f172a 0%, #1e293b 100%);
      border-bottom: 1px solid #334155;
      padding: 18px 32px;
      display: flex;
      align-items: center;
      justify-content: space-between;
    }
    .brand-title {
      font-size: 1.4rem;
      font-weight: 700;
      letter-spacing: -0.02em;
      color: #38bdf8;
      display: flex;
      align-items: center;
      gap: 12px;
    }
    .brand-badge {
      font-size: 0.72rem;
      font-weight: 600;
      padding: 3px 10px;
      border-radius: 9999px;
      background: rgba(56, 189, 248, 0.15);
      color: #38bdf8;
      border: 1px solid rgba(56, 189, 248, 0.3);
      text-transform: uppercase;
      letter-spacing: 0.05em;
    }
    .advisory-badge {
      font-size: 0.78rem;
      color: #94a3b8;
    }
    /* Swagger Dark Theme Enhancements */
    .swagger-ui {
      filter: invert(88%) hue-rotate(180deg);
      max-width: 1200px;
      margin: 0 auto;
      padding: 20px;
    }
    .swagger-ui .topbar { display: none; }
    .swagger-ui .info { margin: 20px 0; }
  </style>
</head>
<body>
  <div class="top-banner">
    <div class="brand-title">
      <span>🌊 HydroPulse AI</span>
      <span class="brand-badge">Jharkhand Basins v0.1.0</span>
    </div>
    <div class="advisory-badge">
      Advisory System · Damodar & Subarnarekha River Health Monitoring
    </div>
  </div>
  <div id="swagger-ui"></div>
  <script src="https://unpkg.com/swagger-ui-dist@5.11.0/swagger-ui-bundle.js"></script>
  <script>
    window.onload = function() {
      SwaggerUIBundle({
        url: "/api/v1/openapi.json",
        dom_id: '#swagger-ui',
        deepLinking: true,
        presets: [
          SwaggerUIBundle.presets.apis,
          SwaggerUIBundle.SwaggerUIStandalonePreset
        ],
        layout: "BaseLayout"
      });
    }
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
