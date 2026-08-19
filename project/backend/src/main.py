"""API del Planificador Autónomo de Operaciones Críticas.

POST /api/solve  ->  ejecuta uniform_cost_search sobre un escenario recibido
en el body (o sobre scenarios/scenario.json si el body no trae "scenario"),
y devuelve la respuesta en el formato exacto de CONTRATO.md §2.

Ejecutar (desde backend/):  uvicorn main:app --app-dir src --port 8000
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from demo_plan import build_plan

app = FastAPI(title="Emergency Control - Planificador Autónomo", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class SolveRequest(BaseModel):
    scenario: Optional[Dict[str, Any]] = None
    scenario_path: Optional[str] = None


@app.post("/api/solve")
def solve(payload: SolveRequest = SolveRequest()) -> Dict[str, Any]:
    try:
        return build_plan(scenario_path=payload.scenario_path, scenario_raw=payload.scenario)
    except (FileNotFoundError, KeyError) as exc:
        raise HTTPException(status_code=400, detail=f"Escenario inválido: {exc}") from exc


@app.get("/api/health")
def health() -> Dict[str, str]:
    return {"status": "ok"}
