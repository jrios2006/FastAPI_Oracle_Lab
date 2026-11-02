# Anexo W4-R01 frente a W4-R02 — Integración

Este ZIP contiene **archivos incrementales**, sin credenciales ni cambios en `OracleClient`:

- `reports/consolidado/T06/informe_consolidado.md`: informe completo actualizado con el anexo integrado.
- `docs/anexos/T06_W4_R01_vs_R02.md`: copia independiente del anexo y sus fuentes.
- `scripts/integrate_t06_annex.py`: función idempotente para actualizar el anexo si vuelve a generarse el consolidado.

Desde el directorio padre del proyecto, extraiga el ZIP con `unzip -o` (el único archivo de informe que reemplaza es el consolidado Markdown, que conviene respaldar). Si se regenera el consolidado con `python scripts/consolidate_t06.py`, ejecute después:

```bash
python scripts/integrate_t06_annex.py
```

El programa añadirá o reemplazará el anexo una sola vez, sin duplicar secciones. No realiza conexiones a Oracle ni ejecuta pruebas de carga.

Se recomienda conservar los CSV de R01 y R02 en sus rutas de resultados originales para mantener la trazabilidad.
