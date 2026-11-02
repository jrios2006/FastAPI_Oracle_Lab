"""
router.diagnostics_api
======================

F3/F4 - Endpoints locales de inspeccion por PID, sin consultas Oracle.

NOTA MULTIWORKER: cada GET refleja UN worker, no una vista global.
Se protege el acceso a diagnostics desde loopback, incluso si alguien
configura por error el servidor para escuchar en todas las interfaces.
"""

from __future__ import annotations

from ipaddress import ip_address

from fastapi import APIRouter, Depends, HTTPException, Request

from module.diagnostics_service import DiagnosticsService

router = APIRouter(prefix="/api/v1/lab/diagnostics", tags=["Laboratorio - Diagnosticos"])


def get_diagnostics(request: Request) -> DiagnosticsService:
    """Recupera el monitor del worker sin crear pools."""
    remote = request.client.host if request.client else ""
    try:
        allowed = ip_address(remote).is_loopback
    except ValueError:
        allowed = False
    if not allowed:
        raise HTTPException(status_code=403, detail="Diagnosticos disponibles solo desde loopback")
    diagnostics = getattr(request.app.state, "diagnostics_service", None)
    if diagnostics is None:
        raise HTTPException(status_code=503, detail="Diagnosticos no inicializados")
    return diagnostics


@router.get("/worker")
def worker(diagnostics: DiagnosticsService = Depends(get_diagnostics)):
    """PID, PPID, versiones de Python/Oracle y huella del pool actual."""
    return diagnostics.worker()


@router.get("/pool")
def pool(diagnostics: DiagnosticsService = Depends(get_diagnostics)):
    """opened/busy/timeout por worker. Sin ejecutar SELECT ni acquire()."""
    return diagnostics.pool()
