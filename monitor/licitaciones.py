"""Licitaciones del Tesoro: instrumentos dólar linked adjudicados.

Lee los comunicados de resultados de la Secretaría de Finanzas
(argentina.gob.ar/economia/finanzas/noticias) y guarda, por licitación y por
instrumento vinculado al dólar, el valor nominal ofrecido y adjudicado (en
millones de USD) y el valor efectivo adjudicado (en millones de pesos). Es la
demanda de cobertura cambiaria que absorbe el Tesoro.

    python -m monitor.licitaciones            # revisa las últimas páginas
    python -m monitor.licitaciones --todas    # rearma la historia (desde 2019)

Sólo licitaciones por efectivo: los canjes y conversiones no son demanda nueva
de cobertura y se dejan afuera.
"""
from __future__ import annotations

import argparse
import html
import logging
import re
import time

import pandas as pd
import requests

from . import config

log = logging.getLogger(__name__)

BASE = "https://www.argentina.gob.ar"
NOTICIAS = BASE + "/economia/finanzas/noticias"
COLUMNAS = ["fecha", "tipo", "ticker", "instrumento", "vno_ofertado_usd", "vno_adjudicado_usd",
            "ve_adjudicado_ars", "url"]
_UA = {"User-Agent": "monitor-dolarizacion/1.0 (+https://github.com/elibman36/dolarizacion)"}
_MESES = {m: i + 1 for i, m in enumerate(
    "enero febrero marzo abril mayo junio julio agosto septiembre octubre noviembre diciembre".split())}
_DL = re.compile(r"VINCULAD[AO]S? AL D[ÓO]LAR|D[ÓO]LAR LINKED|DOLLAR LINKED|LELINK", re.I)
_EXCLUIR = re.compile(r"conversi[oó]n|canje", re.I)


def _get(url: str, intentos: int = 3) -> str:
    for k in range(intentos):
        try:
            r = requests.get(url, headers=_UA, timeout=40)
            r.raise_for_status()
            return r.text
        except Exception as exc:  # noqa: BLE001 - se reintenta
            if k == intentos - 1:
                raise
            log.info("licitaciones: reintento %s (%s)", url, exc)
            time.sleep(4)
    return ""


def listar(paginas: range) -> list[str]:
    """URLs de los comunicados de resultados en esas páginas de noticias."""
    urls: list[str] = []
    for p in paginas:
        t = _get(f"{NOTICIAS}?page={p}")
        for h in re.findall(r'href="(/noticias/[^"]*resultado[^"]*)"', t):
            if h not in urls and not _EXCLUIR.search(h):
                urls.append(h)
        time.sleep(0.4)
    return urls


def _lineas(t: str) -> list[str]:
    i = t.find("<article")
    s = t[i:] if i > 0 else t
    j = s.find("Descargas")
    s = s[:j] if j > 0 else s
    s = re.sub(r"<(script|style).*?</\1>", "", s, flags=re.S)
    s = re.sub(r"<br\s*/?>", "\n", s)
    s = re.sub(r"</(p|td|th|tr|li|h\d|div)>", "\n", s)
    txt = html.unescape(re.sub(r"<[^>]+>", "", s))
    return [re.sub(r"\s+", " ", l).strip() for l in txt.splitlines() if l.strip()]


def _num(x: str) -> float | None:
    try:
        return float(x.replace(".", "").replace(",", "."))
    except ValueError:
        return None


def parse(t: str, url: str = "") -> list[dict]:
    """Instrumentos dólar linked de un comunicado de resultados."""
    L = _lineas(t)
    fecha = None
    for l in L[:15]:
        m = re.search(r"(\d{1,2}) de ([a-z]+) de (\d{4})", l)
        if m and m.group(2) in _MESES:
            fecha = f"{m.group(3)}-{_MESES[m.group(2)]:02d}-{int(m.group(1)):02d}"
            break
    if fecha is None:
        return []
    # Algunos comunicados suman, después de la licitación por efectivo, una
    # conversión de títulos: se corta ahí.
    for k, l in enumerate(L[8:], start=8):
        if re.match(r"^([A-Z0-9]\)|\d\.)?\s*(Resultado de la )?Licitaci[oó]n (por|de|para) (la )?conversi", l, re.I):
            L = L[:k]
            break
    out = []
    for i, l in enumerate(L):
        if len(l) < 25 or not _DL.search(l) or not re.match(r"(LETRA|BONO|LELINK)", l, re.I):
            continue
        vals = []
        for k in range(i + 1, min(i + 16, len(L))):
            if re.match(r"(LETRA|BONO|\(\*|[a-h]\))", L[k]):
                break
            vals.append(L[k])
        # Las columnas vienen siempre en el mismo orden: VNO ofrecido y
        # adjudicado (millones de USD), valor efectivo adjudicado (millones
        # de pesos), precio... El rótulo de moneda cambió según la época
        # (USD, U$S, $ o nada), así que se toman por posición.
        nums = [0.0 if re.fullmatch(r"Desiert[oa]", v, re.I) else _num(m.group(1)) for v in vals
                for m in [re.fullmatch(r"(?:USD|U\$S|\$)?\s*([\d\.]+(?:,\d+)?)\s*(?:USD)?\s*(?:\((?:\*+|\d)\))?|Desiert[oa]", v, re.I)] if m]
        if len(nums) < 3:
            continue
        usd, pes = nums[:2], nums[2:3]
        if usd[1] == 0:  # desierta: no hay valor efectivo adjudicado
            pes = [0.0]
        # Control: el valor efectivo en pesos sobre el VNO en USD tiene que
        # parecerse a un tipo de cambio; si no, el formato no es el esperado.
        if usd[1] and pes[0] and not (10 < pes[0] / usd[1] < 5000):
            log.warning("licitaciones: montos raros en %s (%s)", url or fecha, l[:60])
            continue
        par = " ".join(re.findall(r"\(([^)]*)\)", l))
        tk = re.search(r"\b(?!OPCI)([A-Z][A-Z0-9]{3,5})\b", par.replace("OPCION", ""))
        tk = tk.group(1) if tk and re.search(r"\d", tk.group(1)) else ""
        if not tk:
            m = re.search(r"VENCIMIENTO (\d{1,2}) DE ([A-ZÁÉÍÓÚ]+) DE (\d{4})", l.upper())
            tk = f"vto {m.group(1)}-{m.group(2).lower()[:3]}-{m.group(3)}" if m else ""
        tipo = "dual" if re.search(r"DUAL", l, re.I) else "dl"
        out.append({"fecha": fecha, "tipo": tipo, "ticker": tk, "instrumento": l[:200],
                    "vno_ofertado_usd": usd[0], "vno_adjudicado_usd": usd[1],
                    "ve_adjudicado_ars": pes[0] if pes else None, "url": url})
    if not out:
        # Formato de 2020: un solo bono, con los totales en dólares (no en
        # millones) en el texto.
        txt = " || ".join(L)
        of = re.search(r"Total VNO Ofertado en USD \|\| ([\d\.]+)", txt)
        ad = re.search(r"Total VNO Adjudicado en USD \|\| ([\d\.]+)", txt)
        bono = next((l for l in L if _DL.search(l) and re.match(r"BONO", l, re.I)), None)
        if of and ad and bono:
            m = re.search(r"VENCIMIENTO (\d{1,2}) DE ([A-ZÁÉÍÓÚ]+) DE (\d{4})", bono.upper())
            out.append({"fecha": fecha, "tipo": "dl", "ticker": f"vto {m.group(1)}-{m.group(2).lower()[:3]}-{m.group(3)}" if m else "",
                        "instrumento": bono[:200], "vno_ofertado_usd": _num(of.group(1)) / 1e6,
                        "vno_adjudicado_usd": _num(ad.group(1)) / 1e6, "ve_adjudicado_ars": None, "url": url})
    return out


def _cache():
    return config.SERIES_DIR / "licitaciones_dl.csv"


def cargar() -> pd.DataFrame:
    if _cache().exists():
        return pd.read_csv(_cache(), dtype={"fecha": str})
    return pd.DataFrame(columns=COLUMNAS)


def actualizar(paginas: range = range(0, 3)) -> pd.DataFrame:
    """Agrega al CSV los comunicados nuevos de esas páginas de noticias."""
    previo = cargar()
    vistos = set(previo["url"]) if not previo.empty else set()
    filas = []
    for h in listar(paginas):
        if h in vistos:
            continue
        try:
            filas += parse(_get(BASE + h), h)
        except Exception as exc:  # noqa: BLE001 - un comunicado roto no frena el resto
            log.warning("licitaciones: no se pudo leer %s (%s)", h, exc)
        time.sleep(0.4)
    if not filas:
        return previo
    nuevo = pd.concat([previo, pd.DataFrame(filas)], ignore_index=True)
    nuevo = nuevo.drop_duplicates(["fecha", "ticker", "instrumento"], keep="last").sort_values(["fecha", "ticker"])
    config.SERIES_DIR.mkdir(parents=True, exist_ok=True)
    nuevo[COLUMNAS].to_csv(_cache(), index=False)
    log.info("licitaciones: %d instrumentos dólar linked nuevos", len(filas))
    return nuevo


def por_licitacion(df: pd.DataFrame | None = None) -> pd.DataFrame:
    """Totales por licitación: ofrecido y adjudicado en dólar linked (M USD)."""
    df = cargar() if df is None else df
    if df.empty:
        return pd.DataFrame(columns=["fecha", "ofertado_usd", "adjudicado_usd", "instrumentos"])
    df = df[df["tipo"].fillna("dl") == "dl"]
    g = df.groupby("fecha").agg(ofertado_usd=("vno_ofertado_usd", "sum"),
                                adjudicado_usd=("vno_adjudicado_usd", "sum"),
                                instrumentos=("ticker", lambda s: ", ".join(x for x in s if isinstance(x, str) and x)))
    return g.reset_index()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--todas", action="store_true", help="recorre todas las páginas de noticias")
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    df = actualizar(range(0, 110) if a.todas else range(0, 3))
    print(por_licitacion(df).tail(12).to_string(index=False))


if __name__ == "__main__":
    main()
