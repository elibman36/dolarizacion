"""Versión paralela del índice, para comparar: cantidades normalizadas en cero.

    python -m monitor.mixto --dias 20 --fecha 2026-11-02

Igual al índice publicado, pero las cantidades que hoy van por su nivel frente
a los dos años anteriores pasan a contar por su movimiento, centrado en cero:
los futuros vendidos por el BCRA (vender más siempre suma, desarmar siempre
resta) y la posición abierta en futuros (más contratos, más demanda de
cobertura, siempre suma). Los precios y la tensión (brecha, canje,
volatilidades, devaluación implícita) y las compras de personas humanas siguen
como en el publicado. `--dias` = días hábiles del promedio del índice (20 o 5).
Recalcula con las series guardadas y deja todo en data/mixto<dias>/ y
reportes/mixto<dias>/.
"""
from __future__ import annotations

import argparse
import copy
import logging
from datetime import date

from . import build, config, report

CAMBIOS = {
    "posicion_bcra": {},
    "futuros_oi": {"transform": "dlog"},
}


def bloques() -> dict:
    b = copy.deepcopy(config.IPD_BLOCKS)
    for blk in b.values():
        for c, spec in blk["components"].items():
            if c in CAMBIOS:
                spec.update(CAMBIOS[c])
                spec["centro_cero"] = True
    return b


def preparar(dias: int) -> dict:
    datos = config.DATA_DIR / f"mixto{dias}"
    config.IPD_BLOCKS = bloques()
    config.INDICE_SUAVIZADO = dias
    config.DATA_DIR = datos
    config.OUTPUT_JSON = datos / "monitor.json"
    datos.mkdir(parents=True, exist_ok=True)
    return {
        **report.PERFIL_AR,
        "blocks": config.IPD_BLOCKS,
        "titulo": f" · futuros en cero, {dias} días",
        "panel": datos / "panel_diario.csv", "json": datos / "monitor.json",
        "salida": config.ROOT / "reportes" / f"mixto{dias}",
        "aviso": ("<section class='section card' style='border-color:#e0a030;background:#fff8ea'><b>Versión paralela, "
                  f"para comparar.</b> Futuros vendidos por el BCRA y posición abierta en futuros cuentan por su "
                  f"movimiento, centrado en cero. Promedio de {dias} días hábiles. No es el índice publicado.</section>"),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dias", type=int, default=20, help="días hábiles del promedio del índice")
    ap.add_argument("--fecha", help="fecha de referencia AAAA-MM-DD (se informa la semana anterior)")
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    pf = preparar(a.dias)
    build.run(offline=True)
    report.PERFILES["mixto"] = lambda: pf
    report.generar(date.fromisoformat(a.fecha) if a.fecha else date.today(), "mixto")


if __name__ == "__main__":
    main()
