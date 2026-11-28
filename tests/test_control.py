from datetime import datetime

from monitor import control, enviar


def _datos(mep=(1500.0, 1510.0), fecha="2026-11-27", ok=True):
    def serie(v0, v1, f=fecha):
        return {"last_date": f, "data": [["2026-11-26", v0], [f, v1]]}
    return {
        "sources_status": {"ambito": "ok" if ok else "error: 500"},
        "headline": {"indice": 50.5, "date": fecha},
        "series": {"riesgo_pais": serie(950, 960), "tc_oficial_ref": serie(1450, 1455),
                   "usd_mep": serie(*mep), "usd_ccl": serie(1740, 1754)},
    }


HOY = datetime(2026, 11, 28)


def test_control_todo_en_orden():
    problemas, resumen = control.revisar(_datos(), HOY)
    assert problemas == []
    assert resumen[0].startswith("Índice de Dolarización")


def test_control_detecta_problemas():
    d = _datos(mep=(1510.0, 1510.0), ok=False)
    d["series"]["riesgo_pais"]["last_date"] = "2026-11-26"
    problemas, _ = control.revisar(d, HOY)
    texto = " ".join(problemas)
    assert "no respondió" in texto and "Riesgo país" in texto and "repite" in texto


def test_control_dato_viejo():
    problemas, _ = control.revisar(_datos(), datetime(2026, 12, 10))
    assert any("hace más de" in p for p in problemas)


def test_registro_de_envios(tmp_path, monkeypatch):
    monkeypatch.setattr(enviar, "ENVIOS", tmp_path / "envios.json")
    assert enviar.ya_enviada("2026-11-27") is None
    enviar.registrar_envio("2026-11-27")
    assert enviar.ya_enviada("2026-11-27")
    assert enviar.ya_enviada("2026-12-04") is None
