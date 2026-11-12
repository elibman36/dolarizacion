"""Versión paralela del índice, para comparar: suma las licitaciones dólar
linked del Tesoro al subíndice de dolarización de portafolios.

    python -m monitor.variante_licit --ventana 30

El componente nuevo es lo adjudicado en instrumentos dólar linked en las
licitaciones de los últimos `--ventana` días corridos (millones de USD de
valor nominal; con licitaciones cada quince días, suele sumar dos), medido
como su distancia al promedio de los 12 meses anteriores, igual que las
compras de dólares de personas humanas. Más cobertura colocada que lo
habitual suma presión. Empieza en octubre de 2020: antes, el subíndice usa
sólo sus otros componentes. Recalcula con las series guardadas y deja todo en
data/licit_dl_<ventana>/.
"""
from __future__ import annotations

import argparse
import copy
import logging

import pandas as pd

from . import build, config, indicators, licitaciones

COMPONENTE = "licit_dl"


def serie_diaria(ventana: int) -> pd.Series:
    """Adjudicado dólar linked en los últimos `ventana` días corridos, por día."""
    g = licitaciones.por_licitacion()
    s = pd.Series(g["adjudicado_usd"].to_numpy(), index=pd.to_datetime(g["fecha"])).groupby(level=0).sum()
    dias = pd.date_range(s.index.min(), pd.Timestamp.today().normalize(), freq="D")
    return s.reindex(dias, fill_value=0.0).rolling(f"{ventana}D").sum()


def preparar(ventana: int) -> None:
    datos = config.DATA_DIR / f"licit_dl_{ventana}"
    b = copy.deepcopy(config.IPD_BLOCKS)
    b["dolarizacion"]["components"][COMPONENTE] = {
        "transform": "desvio_12m", "sign": +1, "weight": 1.0,
        "label": "Dólar linked adjudicado por el Tesoro",
        "frases": ("el Tesoro colocó más dólar linked que lo habitual (más demanda de cobertura)",
                   "el Tesoro colocó menos dólar linked que lo habitual"),
    }
    config.IPD_BLOCKS = b
    config.DATA_DIR = datos
    config.OUTPUT_JSON = datos / "monitor.json"
    datos.mkdir(parents=True, exist_ok=True)

    serie = serie_diaria(ventana)
    original = indicators.derived_series

    def con_licitaciones(*args, **kwargs):
        out = original(*args, **kwargs)
        out[COMPONENTE] = serie.reindex(out.index, method="ffill")
        return out

    build.indicators.derived_series = con_licitaciones


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ventana", type=int, default=30, help="días corridos de licitaciones que se suman")
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    preparar(a.ventana)
    build.run(offline=True)


if __name__ == "__main__":
    main()
