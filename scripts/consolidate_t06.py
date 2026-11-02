#!/usr/bin/env python3
"""Consolidacion de las campanas T06: informes JSON -> Markdown, CSV y JSON.

No conecta a Oracle, no modifica los informes originales y utiliza solo stdlib.
Las capturas historicas del paquete sirven de respaldo cuando el informe local
no existe; si hay un report.json local con el mismo run_id, tiene prioridad.

Uso desde la raiz del laboratorio:
    python scripts/consolidate_t06.py
    python scripts/consolidate_t06.py --out-dir reports/consolidado/T06
    python scripts/consolidate_t06.py --no-bundled-history
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import statistics
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HISTORY_DIR = ROOT / "data" / "t06_historico"
RESULTS_DIR = ROOT / "reports" / "resultados"
OUTPUT_DIR = ROOT / "reports" / "consolidado" / "T06"

# Identidades de campaña registradas durante las pruebas; NO deducir el numero
# de workers a partir del numero de PID que aparecen en respuestas HTTP.
BASELINE = {
    "LAB_T06_20261030_A": {"workers": 2, "round": "A", "origen": "historico"},
    "LAB_T06_20261030_B": {"workers": 2, "round": "B", "origen": "historico"},
    "LAB_T06_20261030_C": {"workers": 2, "round": "C", "origen": "historico"},
    "LAB_T06_20261030_D": {"workers": 2, "round": "D", "origen": "historico"},
    "LAB_T06_20261030_E": {"workers": 4, "round": "E", "origen": "historico"},
    "LAB_T06_20261030_F": {"workers": 8, "round": "F", "origen": "historico"},
}
COLUMNS = (
    "run_id", "ronda", "workers_configurados", "driver_version", "concurrency_http", "requests",
    "successful", "failed", "oracle_sleep_seconds", "wall_seconds",
    "http_p95_ms", "max_reported_pool_wait_ms", "peak_total_sessions",
    "peak_active_sessions", "peak_inactive_sessions", "last_valid_sample_sessions",
    "peak_opened_observed", "peak_busy_observed", "workers_observed",
    "samples_ok", "samples_error", "status", "source_path",
)


def _num(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


def _fmt(value, precision=2):
    if value is None:
        return "ND"
    if isinstance(value, float):
        return f"{value:.{precision}f}"
    return str(value)


def _read_json(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"JSON no es un objeto: {path}")
    return data


def _get_workers(run_id: str, path: Path, results_dir: Path):
    """Leer metadata explicita, nunca contar PIDs como sustituto."""
    meta = path.parent / "campaign.json"
    if meta.is_file():
        value = _read_json(meta).get("workers")
        if isinstance(value, int) and 1 <= value <= 8:
            return value
        raise ValueError(f"campaign.json workers invalido: {meta}")
    return BASELINE.get(run_id, {}).get("workers")


def _driver_version(run_id: str, path: Path):
    """Control de comparabilidad: no mezclar versiones del driver."""
    meta = path.parent / "campaign.json"
    if meta.is_file():
        value = _read_json(meta).get("driver_version")
        return str(value) if value else "DESCONOCIDO"
    if run_id in BASELINE:
        return "26.1.0"
    return "DESCONOCIDO"


def load_reports(results_dir: Path, include_history: bool = True, history_dir: Path = HISTORY_DIR):
    """Deduplicar por run_id y preferir informes locales sobre capturas."""
    candidates = []
    if include_history and history_dir.exists():
        candidates.extend((0, p) for p in sorted(history_dir.glob("*/report.json")))
    if results_dir.exists():
        candidates.extend((1, p) for p in sorted(results_dir.glob("*/report.json")))
    unique = {}
    for priority, path in candidates:
        obj = _read_json(path)
        run_id = obj.get("run_id")
        if not isinstance(run_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", run_id):
            raise ValueError(f"run_id invalido en {path}")
        # Misma ruta de run_id para todas las salidas, evitando mezclas de datos.
        if path.parent.name != run_id:
            raise ValueError(f"run_id no coincide con directorio: {path}")
        if run_id not in unique or priority > unique[run_id][0]:
            unique[run_id] = (priority, path, obj)
        elif priority == unique[run_id][0]:
            raise ValueError(f"Dos resultados con el mismo run_id: {run_id}")
    rows = []
    for run_id, (_, path, d) in sorted(unique.items()):
        h, o, p = (d.get("http") or {}), (d.get("oracle") or {}), (d.get("pools_http") or {})
        if h.get("run_id") != run_id:
            raise ValueError(f"http.run_id incompatible: {path}")
        row = {
            "run_id": run_id,
            "ronda": BASELINE.get(run_id, {}).get("round", "repeticion"),
            "workers_configurados": _get_workers(run_id, path, results_dir),
            "driver_version": _driver_version(run_id, path),
            "concurrency_http": h.get("concurrency_http"),
            "requests": h.get("requests"),
            "successful": h.get("successful"),
            "failed": h.get("failed"),
            "oracle_sleep_seconds": h.get("oracle_sleep_seconds"),
            "wall_seconds": h.get("wall_seconds"),
            "http_p95_ms": h.get("http_p95_ms"),
            "max_reported_pool_wait_ms": h.get("max_reported_pool_wait_ms"),
            "peak_total_sessions": o.get("peak_total_sessions"),
            "peak_active_sessions": o.get("peak_active_sessions"),
            "peak_inactive_sessions": o.get("peak_inactive_sessions"),
            "last_valid_sample_sessions": o.get("last_valid_sample_sessions"),
            "peak_opened_observed": p.get("peak_opened_observed"),
            "peak_busy_observed": p.get("peak_busy_observed"),
            "workers_observed": p.get("workers_observed"),
            "samples_ok": o.get("samples_ok"),
            "samples_error": o.get("samples_error"),
            "status": d.get("status", "SIN_ESTADO"),
            "source_path": (str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path)),
        }
        rows.append(row)
    return rows


def group_rows(rows: list[dict]) -> list[dict]:
    """Agrupar solamente escenarios realmente comparables."""
    groups = defaultdict(list)
    for row in rows:
        key = (row["driver_version"], row["workers_configurados"],
               row["concurrency_http"], row["requests"], row["oracle_sleep_seconds"])
        groups[key].append(row)
    result = []
    for key, values in sorted(groups.items(), key=lambda x: (x[0][0],
          x[0][1] if x[0][1] is not None else 999, x[0][2] or 0, x[0][3] or 0, x[0][4] or 0)):
        def metric(name):
            arr = [_num(v[name]) for v in values]
            return [n for n in arr if n is not None]
        wall = metric("wall_seconds")
        p95 = metric("http_p95_ms")
        wait = metric("max_reported_pool_wait_ms")
        peak = metric("peak_total_sessions")
        item = {
            "driver_version": key[0], "workers": key[1],
            "concurrency": key[2], "requests": key[3],
            "oracle_sleep_seconds": key[4], "count": len(values),
            "run_ids": [v["run_id"] for v in values],
            "wall_median_s": statistics.median(wall) if wall else None,
            "p95_median_ms": statistics.median(p95) if p95 else None,
            "p95_mean_ms": statistics.mean(p95) if p95 else None,
            "p95_stdev_ms": statistics.stdev(p95) if len(p95) > 1 else None,
            "pool_wait_max_ms": max(wait) if wait else None,
            "peak_sessions_max": int(max(peak)) if peak else None,
            "zero_sessions_final": sum(v["last_valid_sample_sessions"] == 0 for v in values),
            "all_http_ok": all(v["failed"] == 0 and v["successful"] == v["requests"] for v in values),
        }
        result.append(item)
    return result


def render_markdown(rows: list[dict], groups: list[dict], generated: str) -> str:
    lines = [
        "# FastAPI_Oracle_Lab — Informe consolidado F5/F6/F7-T06", "",
        f"**Generado:** {generated}  ",
        f"**Campañas incluidas:** {len(rows)}. **Fuente:** `report.json` de cada campaña.", "",
        "## 1. Alcance y método", "",
        "- Laboratorio Oracle 19c, FastAPI/Gunicorn, `OracleClient` 1.6.2 sin modificaciones, `python-oracledb` 26.1.0 Thin (campañas históricas A–F).",
        "- F5: los escenarios secuenciales de 1, 2, 4 y 8 workers se validaron manualmente en la conversación; no hay métricas F5 normalizadas en estos `report.json`.",
        "- F6: monitor externo de `V$SESSION` separado de la cuenta de API; F7/T06: `DBMS_SESSION.SLEEP` bloquea una conexión en cada solicitud.",
        "- Los picos son máximos de muestras, no sumas de máximos por PID tomadas en instantes distintos.",
        "- `pool_max=5` es un límite por worker, no por servidor Gunicorn completo.",
        "", "## 2. Campañas individuales", "",
        "| Campaña | Workers | Driver | HTTP conc. | Correctas | P95 (ms) | Espera máx. pool (ms) | Sesiones pico | ACTIVE pico | Sesiones finales | Estado |",
        "|---|---:|---|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for r in rows:
        succ = f"{_fmt(r['successful'])}/{_fmt(r['requests'])}"
        lines.append("| " + " | ".join([
            r["run_id"], _fmt(r["workers_configurados"]), r["driver_version"], _fmt(r["concurrency_http"]),
            succ, _fmt(r["http_p95_ms"]), _fmt(r["max_reported_pool_wait_ms"]),
            _fmt(r["peak_total_sessions"]), _fmt(r["peak_active_sessions"]),
            _fmt(r["last_valid_sample_sessions"]), str(r["status"]),
        ]) + " |")
    lines += [
        "", "## 3. Comparaciones homogéneas y repeticiones", "",
        "Solo se agrupan campañas con **igual** versión del driver, número de workers, concurrencia HTTP, solicitudes y duración Oracle.",
        "La mediana y desviación típica son descriptivas; con menos de tres repeticiones no sirven para certificar una diferencia de rendimiento.",
        "", "| Driver | Workers | Concurrencia | Solicitudes | Reps. | Mediana P95 (ms) | Desv. típica P95 (ms) | Pico sesiones | Finales a cero |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for g in groups:
        lines.append("| " + " | ".join([
            str(g["driver_version"]), _fmt(g["workers"]), _fmt(g["concurrency"]), _fmt(g["requests"]),
            _fmt(g["count"]), _fmt(g["p95_median_ms"]), _fmt(g["p95_stdev_ms"]),
            _fmt(g["peak_sessions_max"]), f"{g['zero_sessions_final']}/{g['count']}",
        ]) + " |")
    lines += [
        "", "## 4. Lectura técnica", "",
        "- Las campañas B–F observaron cero sesiones en su última muestra y ausencia de infracciones de pool en los informes disponibles.",
        "- La campaña A terminó con cinco sesiones en la última muestra (`INCONCLUSO_O_REVISAR`); después se verificó manualmente ausencia de sesiones y `opened=0` en ambos pools, **fuera del periodo del monitor**.",
        "- En D (2 workers, concurrencia 12), ambos pools alcanzaron cinco conexiones; las esperas de adquisición y P95 fueron altas.",
        "- E (4 workers, misma carga) no mejoró sustancialmente frente a D en una sola campaña; hubo reparto desigual de peticiones.",
        "- F (8 workers, misma carga) presentó menor P95 y menor espera máxima; es un **resultado de una muestra**, no una garantía de escalado.",
        "- La existencia de 18 sesiones físicas con concurrencia HTTP 12 es compatible con conexiones inactivas retenidas temporalmente por los pools.",
        "", "## 5. Criterios y limitaciones", "",
        "- `APTO_PRELIMINAR` es el estado del analizador, no una certificación de producción ni de ausencia universal de fugas.",
        "- Una última muestra con cero sesiones no prueba el comportamiento de todas las ejecuciones futuras.",
        "- Los diagnósticos de pool por HTTP son muestras aleatorias de workers; `peak_busy_observed` es un pico individual y **no** representa el máximo agregado simultáneo.",
        "- `DBMS_SESSION.SLEEP` no reproduce la lógica clínica real, los procedimientos originales ni los diferentes tiempos WAN de producción.",
        "- Las comparaciones de rendimiento deben repetirse y documentar distribución temporal, driver, servidor Oracle y presión externa.",
        "- La comparación con `python-oracledb` 1.2.1 está **pendiente**; no se ha establecido que el driver explique las 40 sesiones de `pisuerga`.",
        "", "## 6. Próximos ensayos", "",
        "1. Ejecutar al menos tres repeticiones por configuración (2/4/8 workers; concurrencia 12, 24 solicitudes, 3 segundos).",
        "2. Exigir monitorización completa de 240 segundos por repetición y guardar sus archivos por `run_id` único.",
        "3. Analizar dispersión de P95, espera máxima y picos por worker; no elegir configuración a partir de una sola campaña.",
        "4. Planificar comparación de versiones del driver en entornos equivalentes y sin modificar `OracleClient` original.",
        "", "## 7. Procedencia de datos", "",
    ]
    for r in rows:
        lines.append(f"- `{r['run_id']}`: `{r['source_path']}`")
    lines.append("")
    return "\n".join(lines)


def write_reports(rows: list[dict], out_dir: Path):
    out_dir.mkdir(parents=True, exist_ok=True)
    groups = group_rows(rows)
    generated = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with (out_dir / "campanas.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(rows)
    with (out_dir / "grupos.csv").open("w", encoding="utf-8", newline="") as f:
        fields = list(groups[0]) if groups else ["workers", "concurrency", "requests", "count"]
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(groups)
    (out_dir / "consolidado.json").write_text(json.dumps({
        "generated_utc": generated, "total_campanas": len(rows), "campanas": rows,
        "grupos_comparables": groups,
    }, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (out_dir / "informe_consolidado.md").write_text(render_markdown(rows, groups, generated), encoding="utf-8")
    return groups


def main(argv=None):
    p = argparse.ArgumentParser(description="Consolidar resultados T06 existentes y repeticiones")
    p.add_argument("--results-dir", type=Path, default=RESULTS_DIR,
                   help="Carpeta con subdirectorios RUN_ID/report.json")
    p.add_argument("--out-dir", type=Path, default=OUTPUT_DIR)
    p.add_argument("--no-bundled-history", action="store_true",
                   help="No incorporar las copias de A-F aportadas en el paquete")
    args = p.parse_args(argv)
    try:
        rows = load_reports(args.results_dir, not args.no_bundled_history)
        if not rows:
            p.error("No hay informes report.json disponibles")
        groups = write_reports(rows, args.out_dir)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        p.exit(1, f"ERROR consolidacion: {exc}\n")
    print(f"[T06] Consolidado: {len(rows)} campanas, {len(groups)} grupos comparables")
    print(f"[T06] Informe: {args.out_dir / 'informe_consolidado.md'}")
    print(f"[T06] Datos:   {args.out_dir / 'campanas.csv'} y consolidado.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
