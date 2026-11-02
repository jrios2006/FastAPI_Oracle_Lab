#!/usr/bin/env python3
"""Pruebas offline para el consolidador y automatizador T06 (sin Oracle).

Ejecutar desde la raiz del proyecto:
  python -m unittest discover -s tests -p test_t06_tools.py -v
"""
from __future__ import annotations

import csv
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


consolidate = load("consolidate_t06")
automate = load("run_t06_repetitions")


class TestsT06(unittest.TestCase):
    def test_historico_seis_campanas_y_cero_finales_b_a_f(self):
        rows = consolidate.load_reports(ROOT / "_resultados_sin_instalar_", include_history=True)
        self.assertEqual(len(rows), 6)
        states = {row["ronda"]: row for row in rows}
        self.assertEqual(states["A"]["last_valid_sample_sessions"], 5)
        for campaign in "BCDEF":
            self.assertEqual(states[campaign]["last_valid_sample_sessions"], 0)
            self.assertEqual(states[campaign]["status"], "APTO_PRELIMINAR")
        self.assertEqual(states["F"]["workers_configurados"], 8)
        self.assertEqual(states["F"]["peak_total_sessions"], 18)
        groups = consolidate.group_rows(rows)
        self.assertEqual(len(groups), 5)
        self.assertTrue(all(g["count"] >= 1 for g in groups))

    def test_local_tiene_prioridad_sobre_historico(self):
        with tempfile.TemporaryDirectory() as folder:
            local = Path(folder) / "LAB_T06_20261030_F"
            local.mkdir(parents=True)
            orig = ROOT / "data" / "t06_historico" / "LAB_T06_20261030_F" / "report.json"
            data = json.loads(orig.read_text())
            data["http"]["http_p95_ms"] = 2222.0
            (local / "report.json").write_text(json.dumps(data))
            rows = consolidate.load_reports(Path(folder))
            record = next(r for r in rows if r["ronda"] == "F")
            self.assertEqual(record["http_p95_ms"], 2222)
            self.assertEqual(len(rows), 6)

    def test_salidas_consolidado(self):
        rows = consolidate.load_reports(ROOT / "_sin_local_", include_history=True)
        with tempfile.TemporaryDirectory() as folder:
            consolidate.write_reports(rows, Path(folder))
            self.assertTrue((Path(folder) / "informe_consolidado.md").exists())
            with (Path(folder) / "campanas.csv").open() as f:
                self.assertEqual(len(list(csv.DictReader(f))), 6)
            text = (Path(folder) / "informe_consolidado.md").read_text()
            self.assertIn("La campaña A terminó", text)
            self.assertIn("LAB_T06_20261030_F", text)

    def test_run_id_distinto_y_parametros_validos(self):
        self.assertEqual(automate.parse_workers("2,4,8"), [2, 4, 8])
        with self.assertRaises(Exception):
            automate.parse_workers("2,2")
        args = automate.args_parser().parse_args(["--repeats", "3", "--prefix", "TEST_T06"])
        runs = automate.check_arguments(automate.args_parser(), args)
        self.assertEqual(len(runs), 9)
        self.assertEqual(len({r[2] for r in runs}), 9)

    def test_monitor_no_confunde_error_con_cero(self):
        with tempfile.TemporaryDirectory() as folder:
            dest = Path(folder) / "oracle_totals.csv"
            dest.write_text("sample,status,total\n0,ERROR,\n")
            self.assertFalse(automate.monitor_first_sample_ok(dest))
            dest.write_text("sample,status,total\n0,OK,0\n")
            self.assertTrue(automate.monitor_first_sample_ok(dest))

    def test_report_incoherente_no_se_consolida(self):
        with tempfile.TemporaryDirectory() as folder:
            local = Path(folder) / "RUN_VALIDO"
            local.mkdir(parents=True)
            (local / "report.json").write_text(json.dumps({"run_id": "RUN_VALIDO", "http": {"run_id": "OTRO"}}))
            with self.assertRaises(ValueError):
                consolidate.load_reports(Path(folder), include_history=False)


if __name__ == "__main__":
    unittest.main()
