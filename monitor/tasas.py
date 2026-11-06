"""Versión paralela del índice, para comparar: otra tasa en lugar de la BADLAR.

    python -m monitor.tasas --tasa pases_1d --suavizado 5

Igual al índice publicado, pero el componente de tasa usa la tasa de pases
entre terceros a 1 día (la referencia de la caución) o el call interbancario
(BAIBAR), con la BADLAR sólo antes de que empiece esa serie. `--suavizado`
promedia la tasa en N días hábiles antes de medir su movimiento, para que los
saltos de fin de mes no metan ruido. Recalcula con las series guardadas y deja
todo en data/tasa_<tasa>_<suavizado>/ (y el reporte en reportes/, si se pide).
"""
from __future__ import annotations

import argparse
import logging
from datetime import date

from . import build, config, report


def preparar(tasa: str, suavizado: int) -> dict:
    nombre = f"tasa_{tasa}_{suavizado}"
    datos = config.DATA_DIR / nombre
    config.TASA_FUENTE = tasa
    config.TASA_SUAVIZADO_DIAS = suavizado
    config.DATA_DIR = datos
    config.OUTPUT_JSON = datos / "monitor.json"
    datos.mkdir(parents=True, exist_ok=True)
    etiqueta = config.BCRA_VARIABLES[tasa]["label"]
    return {
        **report.PERFIL_AR,
        "titulo": f" · {etiqueta}",
        "panel": datos / "panel_diario.csv", "json": datos / "monitor.json",
        "salida": config.ROOT / "reportes" / nombre,
        "aviso": ("<section class='section card' style='border-color:#e0a030;background:#fff8ea'><b>Versión paralela, "
                  f"para comparar.</b> La tasa del índice es la {etiqueta} (promedio de {suavizado} días hábiles) en "
                  "lugar de la BADLAR. No es el índice publicado.</section>"),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tasa", default="pases_1d", choices=["pases_1d", "baibar", "tamar"])
    ap.add_argument("--suavizado", type=int, default=1, help="días hábiles del promedio de la tasa")
    ap.add_argument("--reporte", help="fecha de referencia AAAA-MM-DD para generar también el reporte")
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    pf = preparar(a.tasa, a.suavizado)
    build.run(offline=True)
    if a.reporte:
        report.PERFILES["tasa"] = lambda: pf
        report.generar(date.fromisoformat(a.reporte), "tasa")


if __name__ == "__main__":
    main()
