#!/usr/bin/env bash
# FastAPI_Oracle_Lab - F5: arranque Uvicorn, linea base con UN worker.
# Lee host y puerto de config/config.json; NO modifica ese fichero.
# El pool se crea en main.lifespan, dentro del worker.
# Uso: ./scripts/start_uvicorn.sh [--dry-run]
set -Eeuo pipefail

PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
cd "$PROJECT_ROOT"
PYTHON="${LAB_PYTHON:-$PROJECT_ROOT/.venv/bin/python}"

if [[ ! -x "$PYTHON" ]]; then
    printf 'ERROR: Python no ejecutable: %s\nActiva o crea .venv e instala requirements.txt.\n' "$PYTHON" >&2
    exit 1
fi

if [[ $# -gt 1 || ( $# -eq 1 && "$1" != "--dry-run" ) ]]; then
    printf 'Uso: %s [--dry-run]\n' "$0" >&2
    exit 2
fi

# La salida solo contiene host y puerto; el JSON nunca se imprime entero.
SERVER_CONFIG="$("$PYTHON" -c '
import json
from pathlib import Path
config = json.loads(Path("config/config.json").read_text(encoding="utf-8"))
server = config["servidor"]
host, port = str(server["host"]), int(server["puerto"])
if host != "127.0.0.1" or not 1024 <= port <= 65535:
    raise SystemExit("ERROR: F5 requiere host=127.0.0.1 y puerto entre 1024 y 65535")
print(host, port)
')" || { printf 'ERROR: config/config.json invalido\n' >&2; exit 1; }
read -r HOST PORT <<< "$SERVER_CONFIG"

printf '[F5] Uvicorn | host=%s | puerto=%s | workers=1 | PID por worker en logs\n' "$HOST" "$PORT"
printf '[F5] python=%s | OracleClient se inicializa exclusivamente en lifespan\n' "$PYTHON"

if [[ "${1:-}" == "--dry-run" ]]; then
    printf '[DRY RUN] '
    printf '%q ' "$PYTHON" -m uvicorn main:app --host "$HOST" --port "$PORT" --workers 1 --log-level info
    printf '\n'
    exit 0
fi

exec "$PYTHON" -m uvicorn main:app \
    --host "$HOST" \
    --port "$PORT" \
    --workers 1 \
    --log-level info
