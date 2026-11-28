"""Control de los datos diarios después de cada actualización.

    python -m monitor.control            # informa
    python -m monitor.control --estricto # además termina con error si algo falla

Revisa en data/monitor.json:
- que todas las fuentes hayan respondido (sources_status == "ok");
- que el riesgo país, el oficial, el MEP y el CCL tengan dato del último día
  hábil con mercado (el más reciente entre esas series) y que ese día no sea
  de hace más de 5 días corridos (fines de semana largos incluidos);
- que el MEP y el CCL no repitan exacto el valor del día anterior (fuente
  trabada).

En GitHub Actions escribe el resultado en el resumen de la corrida. Con
--estricto, un problema hace fallar la corrida y GitHub avisa por mail a la
dueña del repositorio.
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timedelta, timezone

from . import config

SERIES = {"riesgo_pais": "Riesgo país", "tc_oficial_ref": "Dólar oficial (A3500)",
          "usd_mep": "Dólar MEP", "usd_ccl": "Dólar CCL"}
SIN_REPETIDOS = ("usd_mep", "usd_ccl")
MAX_DIAS = 5


def revisar(d: dict, hoy: datetime | None = None) -> tuple[list[str], list[str]]:
    """Devuelve (problemas, resumen)."""
    hoy = (hoy or datetime.now(timezone(timedelta(hours=-3)))).date()
    problemas, resumen = [], []
    caidas = {k: v for k, v in (d.get("sources_status") or {}).items() if not str(v).startswith("ok")}
    for k, v in caidas.items():
        problemas.append(f"La fuente de {k} no respondió: {v}")
    series = d.get("series") or {}
    ultimas = {k: series.get(k, {}).get("last_date") for k in SERIES}
    fechas = [f for f in ultimas.values() if f]
    if not fechas:
        return ["No hay datos de las series diarias."], resumen
    ref = max(fechas)
    if (hoy - datetime.fromisoformat(ref).date()).days > MAX_DIAS:
        problemas.append(f"El último dato de mercado es del {ref}: hace más de {MAX_DIAS} días.")
    for k, nombre in SERIES.items():
        s = series.get(k) or {}
        datos = [x for x in (s.get("data") or []) if x[1] is not None]
        f = s.get("last_date")
        resumen.append(f"{nombre}: {datos[-1][1] if datos else '–'} ({f or 'sin dato'})")
        if f != ref:
            problemas.append(f"{nombre}: el último dato es del {f}, falta el del {ref}.")
        if k in SIN_REPETIDOS and len(datos) >= 2 and datos[-1][1] == datos[-2][1]:
            problemas.append(f"{nombre}: repite el valor del día anterior ({datos[-1][1]}); la fuente puede estar trabada.")
    h = d.get("headline") or {}
    if h.get("indice") is not None:
        resumen.insert(0, f"Índice de Dolarización al {h.get('date')}: {h['indice']:.1f}")
    return problemas, resumen


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--estricto", action="store_true", help="terminar con error si hay problemas")
    a = ap.parse_args()
    d = json.loads(config.OUTPUT_JSON.read_text(encoding="utf-8"))
    problemas, resumen = revisar(d)
    texto = "## Control de datos\n\n" + "\n".join(f"- {x}" for x in resumen)
    texto += "\n\n" + ("**Problemas:**\n" + "\n".join(f"- {p}" for p in problemas) if problemas else "Todo en orden.")
    print(texto)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
            f.write(texto + "\n")
    if problemas and a.estricto:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
