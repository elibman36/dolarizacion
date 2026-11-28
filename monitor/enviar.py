"""Envío por email de las claves de la semana del Dolarómetro (SMTP).

    python -m monitor.enviar                  # a REPORTE_PARA
    python -m monitor.enviar --para a@x.com   # prueba a otra lista
    python -m monitor.enviar --dry-run        # arma el mail y lo guarda, sin enviar

Variables de entorno (en GitHub, secretos del repositorio):
  SMTP_USER       cuenta que envía (p. ej. elibman@fund.ar)
  SMTP_PASSWORD   contraseña de aplicación de esa cuenta
  REPORTE_PARA    destinatarios separados por coma
  SMTP_HOST       por defecto smtp.gmail.com (Google Workspace)
  SMTP_PORT       por defecto 587 (STARTTLS)

El mail sale de data/monitor.json: las claves de la última semana cerrada, el
índice y los subíndices al viernes, el texto de la semana si lo hay
(reportes/textos/AAAA-MM-DD.md) y un enlace al tablero. No lleva adjuntos.
Los destinatarios van en copia oculta para no exponer la lista.
"""
from __future__ import annotations

import argparse
import html
import json
import logging
import os
import re
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import make_msgid
from pathlib import Path

from . import config

log = logging.getLogger(__name__)

TABLERO = "https://elibman36.github.io/dolarizacion/"
SUSCRIPCION = "elibman@fund.ar"
ASSETS = Path(__file__).parent / "assets"
ICONO = ASSETS / "icono_fundar_blanco.png"
LOGO_NEGRO = ASSETS / "logo_fundar_negro.png"
# Formato de los envíos de Fundar (monitor de empresas, precios relativos):
# banda negra con el ícono, columna angosta en blanco, cifras en rosa,
# gráfico en tarjeta beige, botón con borde y pie negro.
INK, INK2, MUTED, BEIGE, ROSA = "#161615", "#3A3A38", "#8C8B86", "#ECEAE3", "#E46E6B"
FUENTE = "Helvetica Neue,Helvetica,Arial,sans-serif"
ANCHO = 480


def _n(v: float, dec: int = 0) -> str:
    return f"{v:,.{dec}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _tramo(v: float) -> str:
    for desde, hasta, _, label in config.INDICE_TRAMOS:
        if desde <= v < hasta:
            return label
    return ""


def _signo(v: float, dec: int = 1) -> str:
    return ("+" if v > 0 else "−" if v < 0 else "") + _n(abs(v), dec)


def _texto_plano(t: str) -> str:
    t = t.replace("</p>", "\n\n").replace("</li>", "\n").replace("<li>", "- ").replace("</h3>", "\n")
    return html.unescape(re.sub(r"<[^>]+>", "", t)).strip()


def grafico_png(d: dict, dias: int = 365) -> bytes | None:
    """El índice del último año en una tarjeta beige, con la marca Fundar al pie,
    como los gráficos de los otros envíos. PNG para incrustar en el mail."""
    try:
        import io
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import numpy as np
        import pandas as pd
        from matplotlib import font_manager
        from matplotlib.collections import LineCollection
    except ImportError:
        return None
    serie = pd.Series({pd.Timestamp(f): v for f, v in (d.get("ipd", {}).get("indice") or []) if v is not None}).sort_index()
    if serie.empty:
        return None
    serie = serie[serie.index >= serie.index[-1] - pd.Timedelta(days=dias)]
    fams = {f.name for f in font_manager.fontManager.ttflist}
    fuente = next((f for f in ("Helvetica Neue", "Inter", "Liberation Sans", "DejaVu Sans") if f in fams), "sans-serif")
    plt.rcParams.update({"font.family": fuente, "font.size": 9})
    colores = {k: c for k, c in [("aprec_fuerte", "#1F6B4E"), ("aprec", "#3B9E78"), ("neutral", "#8C8B86"),
                                 ("deprec", "#ED8688"), ("deprec_fuerte", "#C4505A")]}
    fig = plt.figure(figsize=(4.8, 4.2), dpi=200, facecolor=BEIGE)
    fig.text(0.05, 0.95, "¿Cómo viene la presión sobre el peso?", fontsize=10.5, fontweight="bold", color=INK, va="top")
    fig.text(0.05, 0.895, "Índice de Dolarización, de 0 a 100. Último año.", fontsize=8, color="#606060", va="top")
    fig.add_artist(plt.Line2D([0.05, 0.95], [0.86, 0.86], color="#B8B5AC", lw=0.6))
    ax = fig.add_axes([0.1, 0.2, 0.83, 0.62], facecolor=BEIGE)
    for desde, hasta, clave, _ in config.INDICE_TRAMOS:
        if clave != "neutral":
            ax.axhspan(desde, min(hasta, 100), color=colores[clave], alpha=0.08, lw=0)
    ax.axhline(50, color="#B8B5AC", lw=0.8)
    x = (serie.index - serie.index[0]).days.to_numpy()
    pts = np.column_stack([x, serie.to_numpy()]).reshape(-1, 1, 2)
    segs = np.concatenate([pts[:-1], pts[1:]], axis=1)
    def color_de(v):
        for desde, hasta, clave, _ in config.INDICE_TRAMOS:
            if desde <= v < hasta:
                return colores[clave]
        return colores["neutral"]
    ax.add_collection(LineCollection(segs, colors=[color_de(v) for v in serie.to_numpy()[1:]], linewidths=1.6))
    ax.set_xlim(0, x[-1] * 1.02 + 1)
    ax.set_ylim(0, 100)
    ax.set_yticks([0, 25, 50, 75, 100])
    meses = pd.date_range(serie.index[0], serie.index[-1], freq="2MS")
    ax.set_xticks([(m - serie.index[0]).days for m in meses])
    nombres = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]
    ax.set_xticklabels([f"{nombres[m.month - 1]}\n{m:%Y}" if m.month <= 2 else nombres[m.month - 1] for m in meses])
    ax.tick_params(colors="#606060", labelsize=7, length=0)
    for lado in ("top", "right", "left"):
        ax.spines[lado].set_visible(False)
    ax.spines["bottom"].set_color("#B8B5AC")
    ax.grid(axis="y", color="#D9D6CC", lw=0.5)
    ult = serie.iloc[-1]
    ax.scatter([x[-1]], [ult], s=14, color=INK, zorder=3)
    ax.annotate(f"{serie.index[-1].day} {nombres[serie.index[-1].month - 1]}\n{_n(ult, 1)}", (x[-1], ult),
                xytext=(-4, 10 if ult < 80 else -22), textcoords="offset points", ha="right", fontsize=7.5,
                fontweight="bold", color=INK)
    ax.text(0, 97, "presión", fontsize=6.5, color="#C4505A", va="top")
    ax.text(0, 3, "alivio", fontsize=6.5, color="#1F6B4E", va="bottom")
    fig.text(0.05, 0.085, "Fuente: elaboración propia con datos de BCRA, Ámbito, ArgentinaDatos, A3 Mercados y Secretaría de Finanzas.",
             fontsize=5.5, color="#606060")
    fig.add_artist(plt.Line2D([0.05, 0.95], [0.06, 0.06], color=INK, lw=1.6))
    fig.add_artist(plt.Line2D([0.05, 0.95], [0.045, 0.045], color=INK, lw=1.6))
    if LOGO_NEGRO.exists():
        logo = plt.imread(str(LOGO_NEGRO))
        lax = fig.add_axes([0.87, 0.005, 0.08, 0.035])
        lax.imshow(logo); lax.axis("off")
    buf = io.BytesIO()
    fig.savefig(buf, format="png", facecolor=BEIGE)
    plt.close(fig)
    return buf.getvalue()


def armar_mensaje(remitente: str, para: list[str], datos: Path | None = None) -> EmailMessage:
    d = json.loads((datos or config.OUTPUT_JSON).read_text(encoding="utf-8"))
    cl = d.get("claves") or {}
    items = cl.get("items") or []
    if not items:
        raise SystemExit("No hay claves de la semana en los datos: corré monitor.build.")
    semana = cl.get("semana_txt") or cl.get("fecha", "")
    i1, i0 = cl.get("indice"), cl.get("indice_previo")

    # La bajada la puede escribir la usuaria en reportes/claves/<viernes>.md.
    intro = cl.get("bajada") or "Seguimos semana a semana la presión sobre el peso y la demanda de cobertura en dólares en la Argentina."

    m = EmailMessage()
    m["Subject"] = f"Dolarómetro · La semana del {semana}"
    m["From"] = remitente
    m["To"] = remitente
    m["Bcc"] = ", ".join(para)

    # Las cifras: el índice y los tres subíndices al viernes, con su cambio
    # contra el viernes anterior y los colores del tablero. Debajo, las claves.
    colores = {"cambiaria": "#1F6B4E", "dolarizacion": "#E46E6B", "extranjerizacion": "#5E97AB"}
    cifras = []
    if i1 is not None:
        cifras.append((_n(i1, 1), "Índice de Dolarización", i1 - i0 if i0 is not None else None, INK))
    for k, b in (cl.get("bloques") or {}).items():
        if b.get("v1") is not None:
            v0 = b.get("v0")
            cifras.append((_n(b["v1"], 1), b["label"], b["v1"] - v0 if v0 is not None else None, colores.get(k, INK)))
    claves = list(cl.get("noticias") or []) + items

    def _delta(dv):
        if dv is None:
            return "", MUTED
        if abs(dv) < 0.05:
            return "sin cambios", MUTED
        return f"{'↑' if dv > 0 else '↓'} {_n(abs(dv), 1)} pts", "#C4505A" if dv > 0 else "#2E8A66"

    plano = [f"DOLARÓMETRO · LA SEMANA DEL {semana.upper()}", "",
             intro, "", "Al cierre del viernes (de 0 a 100; 50 es neutral):"]
    for num, nombre, dv, _ in cifras:
        plano.append(f"- {nombre}: {num} ({_delta(dv)[0] or 's/d'} frente al viernes anterior)")
    plano.append("")
    for it in claves:
        plano += [f"• {it['titular']} {it['bajada']}", ""]
    if cl.get("texto"):
        plano += ["¿QUÉ PASÓ EN LA SEMANA?", "", _texto_plano(cl["texto"]), ""]
    plano += [f"Ver el Dolarómetro: {TABLERO}", "", "Fundar · Buenos Aires, Argentina"]
    m.set_content("\n".join(plano))

    icono_cid, graf_cid = make_msgid(domain="fund.ar"), make_msgid(domain="fund.ar")
    grafico = grafico_png(d)
    p = f"font-family:{FUENTE};margin:0"
    col = (100 // max(len(cifras), 1))
    cifras_html = "".join(
        f"<td valign='top' width='{col}%' style='padding:0 8px 0 0'>"
        f"<div style='height:4px;background:{color};margin-bottom:8px'></div>"
        f"<div style='{p};font-size:24px;font-weight:700;color:{color};line-height:1.1'>{html.escape(num)}</div>"
        f"<div style='{p};font-size:11px;font-weight:700;color:{INK};line-height:1.3;margin-top:6px'>{html.escape(nombre)}</div>"
        f"<div style='{p};font-size:11px;font-weight:700;color:{_delta(dv)[1]};line-height:1.3;margin-top:4px'>{_delta(dv)[0]}</div></td>"
        for num, nombre, dv, color in cifras)
    resto_html = (f"<p style='{p};font-size:10.5px;color:{MUTED};margin-top:10px'>Al cierre del viernes, de 0 a 100: 50 es neutral; "
                  f"arriba hay presión sobre el peso y abajo, alivio. El cambio es contra el viernes anterior.</p>"
                  + "".join(
        f"<p style='{p};font-size:12.5px;line-height:1.55;color:{INK2};margin-top:14px'><b style='color:{INK}'>{html.escape(it['titular'])}</b> {html.escape(it['bajada'])}</p>"
        for it in claves))
    texto_html = ""
    if cl.get("texto"):
        t = re.sub(r"<p>", f"<p style='{p};font-size:12px;line-height:1.55;color:{INK2};margin-bottom:10px'>", cl["texto"])
        t = re.sub(r"<h3>", f"<h3 style='{p};font-size:13px;color:{INK};margin:14px 0 6px'>", t)
        texto_html = (f"<tr><td style='padding:28px 0 0'><h2 style='{p};font-size:15px;font-weight:700;color:{INK};margin-bottom:12px'>"
                      f"¿Qué pasó en la semana?</h2>{t}</td></tr>")
    graf_html = ("" if grafico is None else
                 f"<tr><td align='center' style='padding:28px 0 0'><img src='cid:{graf_cid[1:-1]}' width='{ANCHO}' "
                 f"alt='Índice de Dolarización en el último año' style='display:block;width:100%;max-width:{ANCHO}px;border:0'></td></tr>")
    baja = f"mailto:{SUSCRIPCION}?subject=" + "Baja%20del%20Dolar%C3%B3metro"
    cuerpo = f"""<!doctype html><html lang="es"><body style="margin:0;padding:0;background:#FFFFFF">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#FFFFFF">
<tr><td align="center" style="padding:10px 12px 4px"><table role="presentation" width="{ANCHO}" cellpadding="0" cellspacing="0" style="max-width:{ANCHO}px;width:100%">
  <tr><td align="right" style="font-family:{FUENTE};font-size:10px"><a href="{TABLERO}#claves" style="color:{INK}">Ver en el explorador</a></td></tr></table></td></tr>
<tr><td align="center" style="background:#000000;padding:14px 12px 10px">
  <img src="cid:{icono_cid[1:-1]}" alt="Fundar" width="40" style="display:block;border:0;margin:0 auto"></td></tr>
<tr><td align="center" style="padding:28px 12px 32px">
<table role="presentation" width="{ANCHO}" cellpadding="0" cellspacing="0" style="max-width:{ANCHO}px;width:100%">
  <tr><td><h1 style="{p};font-size:19px;font-weight:700;color:{INK}">Dolarómetro</h1>
    <p style="{p};font-size:12px;font-weight:700;line-height:1.5;color:{INK};margin-top:14px">{html.escape(intro)}</p>
    <p style="{p};font-size:11.5px;line-height:1.55;color:{INK2};margin-top:10px">El Índice de Dolarización resume 14 indicadores del mercado de cambios, las reservas, la tasa en pesos, los futuros de dólar, los depósitos en dólares y la deuda en una escala de 0 a 100. Se calcula todos los días con datos del BCRA, Ámbito, ArgentinaDatos, A3 Mercados y la Secretaría de Finanzas.</p></td></tr>
  <tr><td style="padding:34px 0 18px"><h2 style="{p};font-size:16px;font-weight:700;color:{INK}">¿Qué nos dice la última semana ({html.escape(semana)})?</h2></td></tr>
  <tr><td><table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr>{cifras_html}</tr></table>{resto_html}</td></tr>
  {texto_html}
  {graf_html}
  <tr><td align="center" style="padding:26px 0 0">
    <a href="{TABLERO}" style="display:inline-block;font-family:{FUENTE};font-size:11px;color:{INK};text-decoration:none;border:1.5px solid {INK};border-radius:99px;padding:9px 38px;background:#F4F3EE">Ver → Dolarómetro</a></td></tr>
</table></td></tr>
<tr><td align="center" style="background:#000000;padding:22px 12px 20px">
<table role="presentation" width="{ANCHO}" cellpadding="0" cellspacing="0" style="max-width:{ANCHO}px;width:100%"><tr>
  <td valign="top" style="font-family:{FUENTE};font-size:11px;color:#FFFFFF;line-height:1.6"><b>Fundar</b><br><span style="font-size:10px">Buenos Aires, Argentina</span><br>
    <a href="https://fund.ar" style="color:#FFFFFF;font-size:10px">fund.ar</a></td>
  <td valign="bottom" align="right" style="font-family:{FUENTE};font-size:10px;line-height:1.8">
    <a href="mailto:{SUSCRIPCION}?subject=Preferencias%20del%20Dolar%C3%B3metro" style="color:#FFFFFF">Cambiar mis preferencias.</a><br>
    <a href="{baja}" style="color:#FFFFFF">Dejar de recibir el Dolarómetro.</a></td>
</tr></table></td></tr>
</table></body></html>"""
    m.add_alternative(cuerpo, subtype="html")
    rel = m.get_payload()[1]
    if ICONO.exists():
        rel.add_related(ICONO.read_bytes(), maintype="image", subtype="png", cid=icono_cid)
    if grafico is not None:
        rel.add_related(grafico, maintype="image", subtype="png", cid=graf_cid)
    return m


def enviar(m: EmailMessage, usuario: str, clave: str, host: str = "smtp.gmail.com", puerto: int = 587) -> None:
    with smtplib.SMTP(host, puerto, timeout=60) as s:
        s.starttls(context=ssl.create_default_context())
        s.login(usuario, clave)
        s.send_message(m)


ENVIOS = config.ROOT / "data" / "envios.json"
MINIMO_LISTA = 5  # un envío a 5 o más direcciones cuenta como el envío de la semana


def ya_enviada(fecha: str) -> str | None:
    """Cuándo salió la semana que cierra `fecha` a la lista completa, si salió."""
    try:
        return json.loads(ENVIOS.read_text(encoding="utf-8")).get(fecha)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def registrar_envio(fecha: str) -> None:
    try:
        reg = json.loads(ENVIOS.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        reg = {}
    from datetime import datetime, timezone
    reg[fecha] = datetime.now(timezone.utc).isoformat(timespec="minutes")
    ENVIOS.write_text(json.dumps(reg, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--para", help="destinatarios separados por coma (por defecto, REPORTE_PARA)")
    ap.add_argument("--dry-run", action="store_true", help="no envía: guarda el mail en reportes/ultimo.eml")
    ap.add_argument("--semanal", action="store_true",
                    help="envío automático del lunes: no manda si esa semana ya salió a la lista completa")
    ap.add_argument("--contar", action="store_true", help="sólo informa cuántos destinatarios hay (sin mostrarlos)")
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    usuario = os.environ.get("SMTP_USER", "")
    para = [x.strip() for x in (a.para or os.environ.get("REPORTE_PARA", "")).split(",") if x.strip()]
    if a.contar:
        print(f"Destinatarios configurados: {len(para)}")
        return
    if not para:
        raise SystemExit("Faltan destinatarios (--para o REPORTE_PARA).")
    fecha = (json.loads(config.OUTPUT_JSON.read_text(encoding="utf-8")).get("claves") or {}).get("fecha", "")
    if a.semanal and len(para) < MINIMO_LISTA:
        raise SystemExit(f"REPORTE_PARA tiene {len(para)} destinatarios y la lista semanal tiene que tener "
                         f"al menos {MINIMO_LISTA}: no se manda. Revisá el secreto en GitHub.")
    if a.semanal and fecha and ya_enviada(fecha):
        log.info("La semana que cierra el %s ya salió (%s): no se manda de nuevo.", fecha, ya_enviada(fecha))
        return
    m = armar_mensaje(usuario or "monitor@localhost", para)
    if a.dry_run:
        destino = config.ROOT / "reportes" / "ultimo.eml"
        destino.write_bytes(bytes(m))
        log.info("Mail armado (sin enviar): %s", destino)
        return
    clave = os.environ.get("SMTP_PASSWORD", "")
    if not usuario or not clave:
        raise SystemExit("Faltan SMTP_USER o SMTP_PASSWORD.")
    enviar(m, usuario, clave, os.environ.get("SMTP_HOST", "smtp.gmail.com"), int(os.environ.get("SMTP_PORT", "587")))
    log.info("Dolarómetro de la semana enviado a %d destinatarios.", len(para))
    if fecha and len(para) >= MINIMO_LISTA:
        registrar_envio(fecha)


if __name__ == "__main__":
    main()
