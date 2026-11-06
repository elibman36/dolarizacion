"""Arma la versión del monitor que se publica como página de claude.ai.

Toma index.html, los datos y el último reporte, y deja en --salida:

- monitor-dolarizacion.html: el tablero, con el botón "Reporte semanal"
  apuntando a la versión HTML del reporte (el visor no abre PDFs) y un botón
  "Descargar PDF" que usa la capacidad de descargas de la página.
- data/monitor.json, reportes/ultimo.pdf y reportes/ultimo.html: los archivos
  que se publican junto a la página.

Variantes: "ar" (índice publicado, promedio de 20 días) y "prom5" (versión
paralela con promedio de 5 días; correr antes `python -m monitor.prom5`).

    python -m monitor.artefacto --variante ar --salida /ruta/artifact
"""
from __future__ import annotations

import argparse
import re
import shutil
from pathlib import Path

from . import config
from .report import DASHBOARD_URL

VARIANTES = {
    "ar": {"data": "data", "reportes": "reportes", "titulo": None},
    "prom5": {"data": "data/prom5", "reportes": "reportes/prom5", "titulo": "promedio de 5 días"},
}

ENLACE_PDF = '<a class="btn" id="lnk-pdf" href="reportes/ultimo.pdf" target="_blank" rel="noopener">Reporte semanal (PDF)</a>'
ENLACE_ART = ('<a class="btn" id="lnk-pdf" href="reportes/ultimo.html">Reporte semanal</a>'
              '<button class="btn" id="dl-pdf" type="button" hidden>Descargar PDF</button>')

BARRA_REPORTE = ('<meta name="viewport" content="width=device-width,initial-scale=1"><style>@media screen { body { '
                 'max-width: 820px; margin: 0 auto; padding: 16px; background: #fff; } .barra-art { display: flex; '
                 'gap: 8px; margin-bottom: 16px; font-family: "Helvetica Neue", Helvetica, Arial, sans-serif; '
                 'font-size: 13px; } .barra-art a, .barra-art button { border: 1px solid #ccc; border-radius: 99px; '
                 'padding: 6px 13px; background: #fff; color: #161615; text-decoration: none; cursor: pointer; '
                 'font: inherit; } }</style>')


def _descarga(ruta_pdf: str, nombre: str) -> str:
    return ('<script>(async () => {\n'
            '  const b = document.getElementById("dl-pdf"); if (!b || !window.claude) return;\n'
            '  const dl = await window.claude.use("downloads"); if (!dl) return;\n'
            '  b.hidden = false;\n'
            '  b.addEventListener("click", async () => {\n'
            f'    try {{ const blob = await (await fetch("{ruta_pdf}")).blob(); '
            f'await dl.save({{ filename: "{nombre}", data: blob }}); }} catch (e) {{}}\n'
            '  });\n'
            '})();</script>')


def armar(variante: str, salida: Path) -> Path:
    v = VARIANTES[variante]
    raiz = config.ROOT
    rep = raiz / v["reportes"]
    semanales = sorted(rep.glob("reporte-semanal-*.pdf"))
    if not semanales or not (rep / "ultimo.html").exists():
        raise SystemExit(f"Falta el reporte en {rep}: generalo antes (monitor.report o monitor.prom5).")
    nombre_pdf = semanales[-1].name

    t = (raiz / "index.html").read_text(encoding="utf-8")
    # El visor arma su propio <head>: se publica desde el <title>, sin <html>/<head>/<body>.
    t = t[t.index("<title>"):]
    t = re.sub(r'<meta name="description"[^>]*>\n?', "", t)
    t = t.replace("</head>\n<body>\n", "")
    if ENLACE_PDF not in t:
        raise SystemExit("No encontré el botón del reporte en index.html.")
    t = t.replace(ENLACE_PDF, ENLACE_ART)
    if v["titulo"]:
        t = t.replace("<title>Monitor de Dolarización</title>", f"<title>Monitor de Dolarización ({v['titulo'].split()[-2]} días)</title>", 1)
        t = t.replace("<h1>Monitor de Dolarización</h1>", f"<h1>Monitor de Dolarización · {v['titulo']}</h1>", 1)
    t = t.replace("</body>\n</html>", _descarga("reportes/ultimo.pdf", nombre_pdf) + "\n</body></html>")

    (salida / "data").mkdir(parents=True, exist_ok=True)
    (salida / "reportes").mkdir(parents=True, exist_ok=True)
    pagina = salida / "monitor-dolarizacion.html"
    pagina.write_text(t, encoding="utf-8")
    shutil.copyfile(raiz / v["data"] / "monitor.json", salida / "data" / "monitor.json")
    shutil.copyfile(rep / "ultimo.pdf", salida / "reportes" / "ultimo.pdf")

    r = (rep / "ultimo.html").read_text(encoding="utf-8")
    r = r.replace('<head><meta charset="utf-8">', "<head>" + BARRA_REPORTE + '<meta charset="utf-8">', 1)
    r = r.replace("<body>", '<body><div class="barra-art"><a href="../index.html">← Volver al monitor</a>'
                  '<button id="dl-pdf" type="button" hidden>Descargar PDF</button></div>', 1)
    r = r.replace(f'href="{DASHBOARD_URL}"', 'href="../index.html"')
    r = r.replace("</body></html>", _descarga("ultimo.pdf", nombre_pdf) + "</body></html>")
    (salida / "reportes" / "ultimo.html").write_text(r, encoding="utf-8")
    return pagina


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--variante", choices=sorted(VARIANTES), default="ar")
    ap.add_argument("--salida", required=True, type=Path)
    a = ap.parse_args()
    print(armar(a.variante, a.salida))


if __name__ == "__main__":
    main()
