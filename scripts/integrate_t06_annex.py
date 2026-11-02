#!/usr/bin/env python3
"""Integra o actualiza el anexo W4-R01/R02 en el consolidado T06.

Este auxiliar NO modifica OracleClient ni los scripts de ejecucion. Permite
reaplicar el anexo despues de generar un nuevo consolidado con consolidate_t06.py.

Uso:
    python scripts/integrate_t06_annex.py
    python scripts/integrate_t06_annex.py --report reports/consolidado/T06/informe_consolidado.md
"""

from __future__ import annotations

import argparse
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPORT = ROOT / "reports" / "consolidado" / "T06" / "informe_consolidado.md"
DEFAULT_ANNEX = ROOT / "docs" / "anexos" / "T06_W4_R01_vs_R02.md"
START = "<!-- T06_ANEXO_W4_R01_R02_INICIO -->"
END = "<!-- T06_ANEXO_W4_R01_R02_FIN -->"


def integrate(report: Path, annex: Path) -> bool:
    """Inserta el anexo sin duplicarlo; True si modifica el informe."""
    if not report.is_file():
        raise FileNotFoundError(f"No existe el informe: {report}")
    if not annex.is_file():
        raise FileNotFoundError(f"No existe el anexo: {annex}")

    original = report.read_text(encoding="utf-8")
    if original.count(START) != original.count(END):
        raise ValueError("Marcadores de anexo incompletos; revise el informe")
    if original.count(START) > 1 or original.count(END) > 1:
        raise ValueError("Marcadores duplicados; revise el informe")

    body = annex.read_text(encoding="utf-8").strip()
    if not body.startswith("## Anexo A."):
        raise ValueError("El anexo no comienza con el encabezado esperado")
    content = f"{START}\n\n{body}\n\n{END}"

    if START in original:
        beginning = original.index(START)
        ending = original.index(END) + len(END)
        updated = original[:beginning] + content + original[ending:]
    else:
        updated = original.rstrip() + "\n\n---\n\n" + content + "\n"

    if updated == original:
        return False

    report.write_text(updated, encoding="utf-8")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--annex", type=Path, default=DEFAULT_ANNEX)
    args = parser.parse_args()
    changed = integrate(args.report, args.annex)
    print(f"[T06] Anexo {'integrado/actualizado' if changed else 'ya vigente'}: {args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
