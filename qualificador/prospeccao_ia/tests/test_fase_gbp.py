import json

import main as main_mod


def _isolar(tmp_path, monkeypatch):
    caminhos = {}
    for nome, arquivo in [
        ("PATH_COLETADOS", "coletados.json"),
        ("PATH_QUALIFICADOS", "qualificados.json"),
        ("PATH_REPROVADOS", "reprovados.json"),
        ("PATH_COM_SITE", "com_site.json"),
    ]:
        caminho = tmp_path / arquivo
        caminhos[nome] = caminho
        monkeypatch.setattr(main_mod, nome, str(caminho))
    monkeypatch.setattr(main_mod, "DATA_DIR", str(tmp_path))
    return caminhos


def _empresa(**gbp):
    base = {
        "place_id": "p1", "nome": "Clínica X", "nicho": "Fisioterapeuta",
        "gbp_detalhe_scraped": "YES", "gbp_reivindicada": "NO",
        "gbp_horario": None, "gbp_foto_destaque": "http://x/f.jpg",
        "gbp_descricao": "desc", "gbp_faixa_preco": "€€",
        "gbp_plus_code": "8CGX+2M", "gbp_dono": None,
    }
    base.update(gbp)
    return base


def test_fase_gbp_anota_diagnostico_nos_tres_arquivos(tmp_path, monkeypatch):
    caminhos = _isolar(tmp_path, monkeypatch)
    caminhos["PATH_COLETADOS"].write_text(json.dumps([
        {"dados_empresa": _empresa(place_id="c1"), "status": "eligible"}
    ]), encoding="utf-8")
    caminhos["PATH_COM_SITE"].write_text(json.dumps([
        {"dados_empresa": _empresa(place_id="s1"), "status": "queued_future"}
    ]), encoding="utf-8")
    caminhos["PATH_QUALIFICADOS"].write_text(json.dumps([
        {"dados_empresa": _empresa(place_id="q1"), "qualificacao": {}, "status": "qualified"}
    ]), encoding="utf-8")

    resultado = main_mod.fase_gbp()

    assert resultado["diagnosticados"] == 3
    for chave in ("PATH_COLETADOS", "PATH_COM_SITE", "PATH_QUALIFICADOS"):
        registros = json.loads(caminhos[chave].read_text(encoding="utf-8"))
        diag = registros[0]["gbp_diagnostico"]
        assert diag["detail_scraped"] is True
        # gbp_reivindicada=NO + gbp_horario=None => duas lacunas pontuadas
        assert diag["score_completude"] == 28 + 24
        assert diag["sinais"]["ficha_reivindicada"]["estado"] == "CONFIRMADO_AUSENTE"


def test_fase_gbp_sem_leads_retorna_none(tmp_path, monkeypatch):
    _isolar(tmp_path, monkeypatch)
    assert main_mod.fase_gbp() is None


def test_fase_gbp_e_idempotente(tmp_path, monkeypatch):
    caminhos = _isolar(tmp_path, monkeypatch)
    caminhos["PATH_COLETADOS"].write_text(json.dumps([
        {"dados_empresa": _empresa(), "status": "eligible"}
    ]), encoding="utf-8")

    main_mod.fase_gbp()
    primeiro = json.loads(caminhos["PATH_COLETADOS"].read_text(encoding="utf-8"))
    main_mod.fase_gbp()
    segundo = json.loads(caminhos["PATH_COLETADOS"].read_text(encoding="utf-8"))

    assert primeiro == segundo


def test_fase_gbp_diagnostico_viaja_pro_qualificados_no_fase_qualify(tmp_path, monkeypatch):
    caminhos = _isolar(tmp_path, monkeypatch)
    lead = _empresa(place_id="c1", telefone="612345678", nota_google=4.8, review_count=100,
                    instagram="@x", email=None, facebook=None)
    caminhos["PATH_COLETADOS"].write_text(json.dumps([
        {"dados_empresa": lead, "status": "eligible"}
    ]), encoding="utf-8")

    main_mod.fase_gbp()
    main_mod.fase_qualify()

    qualificados = json.loads(caminhos["PATH_QUALIFICADOS"].read_text(encoding="utf-8"))
    assert len(qualificados) == 1
    assert "gbp_diagnostico" in qualificados[0]
    assert qualificados[0]["gbp_diagnostico"]["sinais"]["ficha_reivindicada"]["estado"] == "CONFIRMADO_AUSENTE"
