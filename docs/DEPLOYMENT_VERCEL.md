# HydroPulse AI — Vercel Serverless Deployment Guide

This document describes how to deploy HydroPulse AI to [Vercel](https://vercel.com/) as a production-grade, zero-configuration Python serverless application.

---

## 1. Architectural Overview

```
                      ┌──────────────────────────────────────┐
                      │          Incoming HTTP Request       │
                      └──────────────────┬───────────────────┘
                                         │
                                         ▼
                      ┌──────────────────────────────────────┐
                      │      Vercel Edge Network Proxy       │
                      │   - Caches /static/* at CDN edge     │
                      │   - Rewrites /(.*) -> /api/index     │
                      └──────────────────┬───────────────────┘
                                         │
                                         ▼
                      ┌──────────────────────────────────────┐
                      │   Vercel Serverless Function         │
                      │         (api/index.py)               │
                      │  - Injects project root into path    │
                      │  - VercelPathCorrectionMiddleware    │
                      └──────────────────┬───────────────────┘
                                         │
                                         ▼
                      ┌──────────────────────────────────────┐
                      │        Flask 3 Application           │
                      │   - Blueprints: /api/v1/*            │
                      │   - Dashboard UI: /dashboard         │
                      │   - Interactive Docs: /docs          │
                      │   - In-memory TTL cache & rate limit │
                      └──────────────────────────────────────┘
```

HydroPulse AI uses Vercel's native Python runtime (`python:3.12`). Standard Flask routes, API blueprints, static assets, and Jinja templates execute seamlessly inside AWS Lambda-backed microVMs.

---

## 2. Configuration Files Summary

| File | Purpose |
|---|---|
| [`vercel.json`](file:///vercel.json) | Configures URL rewrites to `/api/index`, CDN caching headers for `/static/*`, and sets function execution timeout (`maxDuration: 30s`). |
| [`api/index.py`](file:///api/index.py) | Serverless WSGI entrypoint with `VercelPathCorrectionMiddleware` to normalize forwarded request paths and query parameters. |
| [`.vercelignore`](file:///.vercelignore) | Prevents tests, dev notebooks, caches, and training artifacts from bloating the deployment bundle, keeping it under Vercel's 250 MB limit. |
| [`.python-version`](file:///.python-version) | Explicitly targets Python 3.12 for maximum compatibility with Vercel's build environment. |
| [`requirements.txt`](file:///requirements.txt) | Lean runtime dependencies (Flask, Pandas, Scikit-learn, Pydantic, SQLAlchemy, PyYAML). Heavy offline training dependencies (PyTorch, SHAP) are segregated in `requirements-ml.txt`. |
| [`wsgi.py`](file:///wsgi.py) | Universal root WSGI entrypoint for local testing and container parity. |

---

## 3. Step-by-Step Deployment Instructions

### Method A: Deploy via GitHub (Recommended)

1. Push your repository to GitHub:
   ```bash
   git add .
   git commit -m "feat: add vercel serverless deployment configuration"
   git push origin main
   ```
2. Log in to [vercel.com](https://vercel.com/) and click **"Add New Project"**.
3. Import your **HydroPulse-AI** repository.
4. Keep the default settings:
   - **Framework Preset**: *Other* (automatically detected)
   - **Root Directory**: `./`
5. *(Optional)* Add Environment Variables in the project settings (see Section 4).
6. Click **Deploy**.

Vercel will detect `api/index.py`, install `requirements.txt`, package the application, and provide a live production URL (e.g., `https://hydropulse-ai.vercel.app`).

---

### Method B: Deploy via Vercel CLI

1. Install the Vercel CLI (requires Node.js):
   ```bash
   npm install -g vercel
   ```
2. Authenticate:
   ```bash
   vercel login
   ```
3. Run preview deployment:
   ```bash
   vercel
   ```
4. Deploy directly to production:
   ```bash
   vercel --prod
   ```

---

## 4. Environment Variables

All settings have built-in safe defaults in `config/settings.py`, but you can customize them in the Vercel Dashboard under **Project Settings → Environment Variables**:

| Variable | Recommended Value | Description |
|---|---|---|
| `FLASK_ENV` | `production` | Enables production mode and disables debug tracebacks. |
| `SECRET_KEY` | *(Random 32+ character string)* | Session encryption key for Flask. |
| `MAPBOX_ACCESS_TOKEN` | *(Your Mapbox public token)* | Mapbox vector map tile token for the Leaflet dashboard. |
| `CORS_ORIGINS` | `*` (or your domain) | Allowed Cross-Origin Resource Sharing domains. |
| `CACHE_TTL_SECONDS` | `300` | In-memory API response cache lifetime (seconds). |
| `RATE_LIMIT_PER_MINUTE` | `60` | Request rate limiter threshold per IP address. |

---

## 5. Verification Checklist

Once deployed, verify the endpoints on your Vercel deployment URL:

- [ ] **Root Landing**: `GET https://your-deployment.vercel.app/` (returns JSON for API clients, HTML for browsers)
- [ ] **Interactive Dashboard**: `GET https://your-deployment.vercel.app/dashboard`
- [ ] **System Health Check**: `GET https://your-deployment.vercel.app/api/v1/health`
- [ ] **Station Registry**: `GET https://your-deployment.vercel.app/api/v1/stations`
- [ ] **7-Day Forecast**: `GET https://your-deployment.vercel.app/api/v1/stations/damodar_ramgarh/forecast?days=7`
- [ ] **Risk GeoJSON**: `GET https://your-deployment.vercel.app/api/v1/risk/map`
- [ ] **Bilingual Alerts**: `GET https://your-deployment.vercel.app/api/v1/alerts`
- [ ] **Water Quality Index**: `GET https://your-deployment.vercel.app/api/v1/water-quality/damodar_ramgarh`
- [ ] **Drought Assessment**: `GET https://your-deployment.vercel.app/api/v1/drought/damodar_ramgarh`
- [ ] **OpenAPI / Swagger Docs**: `GET https://your-deployment.vercel.app/docs`
- [ ] **Static Assets**: `GET https://your-deployment.vercel.app/static/css/dashboard.css`
