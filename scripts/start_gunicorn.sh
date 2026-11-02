#!/usr/bin/env bash
# FastAPI_Oracle_Lab - F5: arranque Gunicorn con uvicorn-worker.
# 1, 2, 4 y 8 workers son los escenarios previstos; se permiten 1..8.
# Uso: ./scripts/start_gunicorn.sh [NUM_WORKERS] [--dry-run]
# Ejemplo: ./scripts/start_gunicorn.sh 4
# NUNCA se usa --preload: cada pool pertenece a un worker independiente.
set -Eeuo pipefail

PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
cd "$PROJECT_ROOT"
PYTHON="${LAB_PYTHON:-$PROJECT_ROOT/.venv/bin/python}"

if [[ ! -x "$PYTHON" ]]; then
    printf 'ERROR: Python no ejecutable: %s\nActiva o crea .venv e instala requirements.txt.\n' "$PYTHON" >&2
    exit 1
fi

WORKERS_OVERRIDE=""
DRY_RUN=0
for ARG in "$@"; do
    case "$ARG" in
        --dry-run)
            DRY_RUN=1
            ;;
        --help|-h)
            printf 'Uso: %s [NUM_WORKERS: 1..8] [--dry-run]\n' "$0"
            exit 0
            ;;
        *)
            if [[ -n "$WORKERS_OVERRIDE" || ! "$ARG" =~ ^[1-8]$ ]]; then
                printf 'ERROR: numero de workers invalido: %s (permitido 1..8)\n' "$ARG" >&2
                exit 2
            fi
            WORKERS_OVERRIDE="$ARG"
            ;;
    esac
done

# LAB_WORKERS se interpreta en gunicorn.conf.py; no modifica config.json.
if [[ -n "$WORKERS_OVERRIDE" ]]; then
    export LAB_WORKERS="$WORKERS_OVERRIDE"
fi

# Comprobar en el MISMO proceso de Python los parametros efectivos del
# fichero gunicorn.conf.py; no importa main ni crea conexiones Oracle.
SUMMARY="$("$PYTHON" -c '
import runpy
conf = runpy.run_path("gunicorn.conf.py")
print(conf["bind"], conf["workers"], conf["worker_class"], conf["preload_app"])
')" || { printf 'ERROR: gunicorn.conf.py o config/config.json invalidos\n' >&2; exit 1; }
read -r BIND WORKERS WORKER_CLASS PRELOAD <<< "$SUMMARY"

printf '[F5] Gunicorn | bind=%s | workers=%s | worker_class=%s | preload=%s\n' "$BIND" "$WORKERS" "$WORKER_CLASS" "$PRELOAD"
printf '[F5] python=%s | pools por worker en main.lifespan\n' "$PYTHON"

if [[ "$DRY_RUN" -eq 1 ]]; then
    printf '[DRY RUN] LAB_WORKERS=%q ' "${LAB_WORKERS:-$WORKERS}"
    printf '%q ' "$PYTHON" -m gunicorn --config "$PROJECT_ROOT/gunicorn.conf.py" main:app
    printf '\n'
    exit 0
fi

exec "$PYTHON" -m gunicorn \
    --config "$PROJECT_ROOT/gunicorn.conf.py" \
    main:app
