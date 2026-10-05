from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

import pandas as pd
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.requests import Request

from app.analytics import analyze_dataset

app = FastAPI(title="ChronosOps AI", version="1.0.0")
BASE_DIR = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


@app.get("/")
async def index(request: Request):
    return templates.TemplateResponse(request=request, name="index.html", context={})


@app.get("/api/health")
async def health() -> Dict[str, Any]:
    return {"status": "ok", "service": "ChronosOps AI", "version": "1.0.0"}


@app.post("/api/upload")
async def upload_dataset(file: UploadFile = File(...), target_column: Optional[str] = Form(None), forecast_horizon: int = Form(12)):
    if not file.filename or not file.filename.endswith(".csv"):
        raise HTTPException(status_code=400, detail="Please upload a CSV file.")

    try:
        contents = await file.read()
        csv_buffer = pd.read_csv(pd.io.common.BytesIO(contents))
    except Exception as exc:  # pragma: no cover
        raise HTTPException(status_code=400, detail=f"Unable to parse CSV: {exc}") from exc

    try:
        result = analyze_dataset(csv_buffer, target_column=target_column, forecast_horizon=int(forecast_horizon))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return JSONResponse(content=result)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
