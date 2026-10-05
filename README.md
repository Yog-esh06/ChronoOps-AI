# ChronosOps AI

### Operational intelligence for multivariate time-series data

**ChronosOps AI** is a local-first analytics workbench for teams that operate software, infrastructure, manufacturing lines, energy systems, and IoT fleets. Upload a timestamped CSV and receive a compact intelligence brief covering data health, forecasting, anomalies, and likely contributors.

> Built and maintained by **YOGESH R MEHTA**  
> Repository: [github.com/Yog-esh06/ChronoOps-AI](https://github.com/Yog-esh06/ChronoOps-AI)

## Why it exists

Most operational dashboards tell you what happened. ChronosOps is designed to help answer what is likely to happen next and which signals deserve attention first. It favors transparent baselines and interpretable evidence over an opaque, one-model demo.

## What is included

- **Dataset intelligence** — timestamp detection, numeric/categorical schema discovery, missing values, duplicates, irregular sampling, outlier summaries, correlations, and a quality score.
- **Time-series diagnostics** — trend slope, seasonality index, stationarity testing, autocorrelation, and approximate change-point detection.
- **Forecast benchmark** — naive baseline, moving average, exponential smoothing, linear lag model, and gradient boosting where the data supports it.
- **Model selection** — validation metrics include MAE, RMSE, MAPE, sMAPE, and R²; the lowest validation RMSE leads the brief.
- **Exception field** — statistical z-score anomaly detection with observed value, expected value, deviation, severity, method, and confidence.
- **Root-cause ranking** — correlation-based contributor ranking around the selected target signal.
- **Flashy operations UI** — a responsive graphite, acid-lime, coral, and warm-paper interface with interactive Plotly charts. It intentionally avoids the common blue/purple AI dashboard palette.
- **Dark mode** — a persistent light/dark theme toggle with system preference detection and chart-aware colors.

## Quick start

### 1. Create an environment

Windows:

```powershell
python -m venv .venv
.venv\Scripts\activate
```

macOS / Linux:

```bash
python -m venv .venv
source .venv/bin/activate
```

### 2. Install dependencies

```bash
python -m pip install -r requirements.txt
```

### 3. Run the app

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Open [http://localhost:8000](http://localhost:8000).

## CSV contract

The upload endpoint accepts `.csv` files. The recommended shape is one timestamp column plus one or more numeric signals:

```csv
timestamp,cpu_usage,memory_usage,request_latency,error_rate,network_io
2026-01-01 00:00,43.2,61.3,120,0.2,32.1
2026-01-01 00:05,45.1,62.0,124,0.3,35.7
```

The timestamp column is detected from common names such as `timestamp`, `time`, `date`, and `ts`. You can optionally enter a numeric target column and choose a forecast horizon in the UI.

## API surface

| Method | Route | Purpose |
| --- | --- | --- |
| `GET` | `/` | Web workbench |
| `GET` | `/api/health` | Service health and version |
| `POST` | `/api/upload` | Analyze a CSV (`file`, optional `target_column`, optional `forecast_horizon`) |

## Project layout

```text
app/
  analytics.py       # Profiling, diagnostics, forecasting, anomalies, contributors
  main.py            # FastAPI application and upload endpoint
static/
  app.js             # Dashboard state, charts, upload UX
  styles.css         # ChronosOps visual system
templates/
  index.html         # Workbench shell
tests/
  test_analytics.py  # Analytics regression smoke test
```

## Validate locally

```bash
python -m pytest -q
```

The test suite exercises the end-to-end analytics result shape on a representative multivariate signal.

## Scope and limitations

ChronosOps AI is a practical portfolio-grade product prototype, not a hosted multi-tenant service. Uploaded data is processed in the running application and is not persisted. Forecasts are benchmarked with interpretable models; deep neural forecasting, authentication, durable storage, scheduled retraining, and production observability are intentionally outside the current scope.

## Author

**YOGESH R MEHTA**  
[ChronosOps-AI on GitHub](https://github.com/Yog-esh06/ChronoOps-AI)
