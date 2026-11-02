"""Versión paralela del índice, para comparar: todo normalizado en cero.

    python -m monitor.cero --fecha 2026-11-02

En el índice publicado, el tipo de cambio, las reservas, la BADLAR, los
depósitos y el riesgo país cuentan por su movimiento de 5 días, centrado en
cero, y el resto por su nivel frente a los dos años anteriores. Acá todos
cuentan por su movimiento centrado en cero: si una variable sube (en el
sentido de más presión), suma; si baja, resta, cualquiera sea su nivel. Las
volatilidades, la brecha, el canje y la devaluación implícita, por su cambio en
5 días; la posición abierta en futuros, por su variación % en 5 días; las
compras de personas humanas y los futuros vendidos por el BCRA (mensuales), por
su cambio en el mes. Se mantiene el promedio de 20 días del índice. Recalcula
con las series guardadas y deja los resultados en data/cero/ y reportes/cero/.
"""
from __future__ import annotations

import argparse
import copy
import logging
from datetime import date

from . import build, config, report

DATA_DIR = config.DATA_DIR / "cero"
SALIDA = config.ROOT / "reportes" / "cero"

# Cómo pasa a entrar cada componente que en el índice publicado va por nivel.
CAMBIOS = {
    "vol_oficial": {"transform": "diff"},
    "brecha_mep": {"transform": "diff"},
    "deval_implicita": {"transform": "diff"},
    "canje": {"transform": "diff"},
    "vol_ccl": {"transform": "diff"},
    "futuros_oi": {"transform": "dlog"},
    "compras_ph": {"transform": "diff", "horizonte": 21},
    "posicion_bcra": {},
}


def bloques() -> dict:
    b = copy.deepcopy(config.IPD_BLOCKS)
    for blk in b.values():
        for c, spec in blk["components"].items():
            if c in CAMBIOS:
                spec.update(CAMBIOS[c])
                spec["centro_cero"] = True
    return b


def perfil() -> dict:
    return {
        **report.PERFIL_AR,
        "blocks": bloques(),
        "titulo": " · todo normalizado en cero",
        "panel": DATA_DIR / "panel_diario.csv", "json": DATA_DIR / "monitor.json", "salida": SALIDA,
        "aviso": ("<section class='section card' style='border-color:#e0a030;background:#fff8ea'><b>Versión paralela, "
                  "para comparar.</b> Todas las variables cuentan por su movimiento, centrado en cero: si suben (más "
                  "presión), suman; si bajan, restan, cualquiera sea su nivel. Promedio de 20 días, como el índice "
                  "publicado. No es el índice publicado; el apéndice describe el publicado.</section>"),
    }


def preparar() -> None:
    config.IPD_BLOCKS = bloques()
    config.DATA_DIR = DATA_DIR
    config.OUTPUT_JSON = DATA_DIR / "monitor.json"
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--fecha", help="fecha de referencia AAAA-MM-DD (se informa la semana anterior)")
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    preparar()
    build.run(offline=True)
    report.PERFILES["cero"] = perfil
    report.generar(date.fromisoformat(a.fecha) if a.fecha else date.today(), "cero")


if __name__ == "__main__":
    main()
