"""API T06 para experimentar concurrencia real y ocupacion de pools Oracle.

Ruta exclusiva de laboratorio, accesible solo desde loopback. Las peticiones
son SINCRONAS (``def``), de forma que FastAPI las ejecuta en su threadpool.
Si varias llamadas se solapan, cada una puede adquirir una conexion del pool.

El limite de segundos es corto para reducir impacto en la instancia Oracle.
La espera se realiza en BD, no mediante ``time.sleep`` en Python: de otro
modo NO ocuparia una conexion Oracle y la prueba seria erronea.
"""
from __future__ import annotations

from ipaddress import ip_address
from typing import Annotated

from fastapi import APIRouter, HTTPException, Request, Depends
from pydantic import BaseModel, Field, StringConstraints

from module.concurrency_service import ConcurrencyLabError, ConcurrencyService

router = APIRouter(prefix="/api/v1/lab/concurrency", tags=["Laboratorio - Concurrencia T06"])

RunId = Annotated[str, StringConstraints(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")]


class HoldRequest(BaseModel):
    """Carga limitada; el run_id solo identifica la campana de prueba."""
    run_id: RunId
    segundos: float = Field(default=2.0, ge=0.1, le=5.0)


class HoldResponse(BaseModel):
    success: bool
    run_id: str
    pid: int
    segundos_solicitados: float
    duracion_total_ms: float
    espera_pool_ms: float | None
    duracion_operacion_oracle_ms: float | None


def get_concurrency_service(request: Request) -> ConcurrencyService:
    """Usa la instancia de OracleClient inicializada por ``main.lifespan``."""
    remote = request.client.host if request.client else ""
    try:
        is_local = ip_address(remote).is_loopback
    except ValueError:
        is_local = False
    if not is_local:
        raise HTTPException(status_code=403, detail="Pruebas T06 disponibles solo desde loopback")
    client = getattr(request.app.state, "oracle_client", None)
    if client is None:
        raise HTTPException(status_code=503, detail="OracleClient no inicializado")
    return ConcurrencyService(client)


@router.post("/hold", response_model=HoldResponse)
def hold_connection(payload: HoldRequest, service: ConcurrencyService = Depends(get_concurrency_service)):
    """Retiene la conexion Oracle durante 0.1..5 segundos sin cambiar tablas."""
    try:
        return service.hold(run_id=payload.run_id, segundos=payload.segundos)
    except ConcurrencyLabError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
