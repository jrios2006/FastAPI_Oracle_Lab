"""
router.test_api
===============

F3/F4 - Contrato HTTP CRUD y procedimiento del laboratorio Oracle.

Todas las escrituras requieren RUN_ID. PUT es una sustitucion completa de los
campos funcionales, no un PATCH. Un ID de otro RUN_ID siempre responde 404.
Se registran los errores Oracle en el servidor; la API no expone credenciales.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request
from pydantic import BaseModel, Field, field_validator

from module.test_service import LabServiceError, TestService

router = APIRouter(prefix="/api/v1/lab", tags=["Laboratorio - CRUD Oracle"])

RecordId = Annotated[int, Path(ge=1, description="Identidad del registro Oracle")]
RunIdQuery = Annotated[str, Query(min_length=1, max_length=64)]
Valor = Annotated[Decimal, Field(max_digits=18, decimal_places=4)]


class RegistroEntrada(BaseModel):
    """Campos de INSERT y PUT, que conserva RUN_ID como propiedad inmutable."""

    run_id: str = Field(..., min_length=1, max_length=64)
    codigo: str = Field(..., min_length=1, max_length=80)
    descripcion: str | None = Field(default=None, max_length=500)
    valor: Valor = Decimal("0")
    estado: Literal["ACTIVO", "INACTIVO"] = "ACTIVO"

    @field_validator("run_id", "codigo")
    @classmethod
    def no_blancos(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("El valor no puede ser blanco")
        return cleaned


class ProcedimientoEntrada(BaseModel):
    run_id: str = Field(..., min_length=1, max_length=64)
    nuevo_valor: Valor

    @field_validator("run_id")
    @classmethod
    def no_blancos(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("run_id obligatorio")
        return cleaned


class RegistroSalida(BaseModel):
    id: int
    run_id: str
    codigo: str
    descripcion: str | None
    valor: Decimal
    estado: str
    fcreacion: str
    fmodificacion: str | None


class RegistroRespuesta(BaseModel):
    success: bool
    registro: RegistroSalida


class ListaRespuesta(BaseModel):
    success: bool
    run_id: str
    limit: int
    offset: int
    registros: list[RegistroSalida]


class EliminacionRespuesta(BaseModel):
    success: bool
    id: int
    run_id: str
    filas_afectadas: int


class ProcedimientoRespuesta(EliminacionRespuesta):
    resultado: str
    registro: RegistroSalida


def get_service(request: Request) -> TestService:
    """Devuelve el servicio creado en lifespan, NO crea un pool por peticion."""
    service = getattr(request.app.state, "test_service", None)
    if service is None:
        raise HTTPException(status_code=503, detail="Servicio Oracle no inicializado")
    return service


def _call(operation, *args, **kwargs):
    try:
        return operation(*args, **kwargs)
    except LabServiceError as error:
        raise HTTPException(status_code=error.status_code, detail=error.detail) from error


@router.post("/registros", status_code=201, response_model=RegistroRespuesta)
def crear_registro(payload: RegistroEntrada, service: TestService = Depends(get_service)):
    """INSERT real sobre LAB_POOL_REGISTROS. Devuelve el ID creado."""
    return _call(service.crear, **payload.model_dump())


@router.get("/registros", response_model=ListaRespuesta)
def listar_registros(
    run_id: RunIdQuery,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
    service: TestService = Depends(get_service),
):
    """SELECT paginado exclusivamente para el RUN_ID solicitado."""
    return _call(service.listar, run_id, limit=limit, offset=offset)


@router.get("/registros/{record_id}", response_model=RegistroRespuesta)
def consultar_registro(
    record_id: RecordId,
    run_id: RunIdQuery,
    service: TestService = Depends(get_service),
):
    """SELECT por clave primaria, limitado al RUN_ID solicitado."""
    return {"success": True, "registro": _call(service.obtener, record_id, run_id)}


@router.put("/registros/{record_id}", response_model=RegistroRespuesta)
def actualizar_registro(
    record_id: RecordId,
    payload: RegistroEntrada,
    service: TestService = Depends(get_service),
):
    """UPDATE completo, sin modificar el RUN_ID del registro."""
    return _call(service.actualizar, record_id, **payload.model_dump())


@router.delete("/registros/{record_id}", response_model=EliminacionRespuesta)
def eliminar_registro(
    record_id: RecordId,
    run_id: RunIdQuery,
    service: TestService = Depends(get_service),
):
    """DELETE fisico de una fila; nunca borra toda la campana."""
    return _call(service.eliminar, record_id, run_id)


@router.post("/registros/{record_id}/procedimiento", response_model=ProcedimientoRespuesta)
def procedimiento_registro(
    record_id: RecordId,
    payload: ProcedimientoEntrada,
    service: TestService = Depends(get_service),
):
    """Invoca SP_LAB_POOL_OPERACION, lee sus dos OUT y verifica la fila."""
    return _call(service.ejecutar_procedimiento, record_id, **payload.model_dump())
