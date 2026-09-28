import inspect
import json

import main as main_mod
import wave2_scoring
import website_analyzer


def _config_teste(batch_size=20, max_retry_attempts=3):
    import copy
    config = copy.deepcopy(wave2_scoring.CONFIG_DEFAULT)
    config["batch_size"] = batch_size
    config["max_retry_attempts"] = max_retry_attempts
    config["max_runtime_seconds"] = 300
    return config


def _lead_com_site(nome="Empresa", website="https://empresa.es", place_id=None):
    return {"nome": nome, "website": website, "nicho": "Fisioterapeuta", "cidade": "Sevilla",
            "nota_google": 4.5, "review_count": 20, "reputation_signal": "moderate",
            "telefone": "612345678", "email": None, "instagram": None, "facebook": None,
            "place_id": place_id}


def _resultado_sucesso():
    return {
        "website_analysis": {"status": "ok", "signals_available": True, "signals": {}, "facts": {}, "error": None, "error_type": None, "checked_at": "x", "url_original": "x"},
        "commercial_fit": {"score": 70, "reasons": []},
        "website_opportunity": {"score": 50, "reasons": ["sem meta viewport"]},
        "priority_score": 60, "priority_label": "media", "wave2_evaluated_at": "x",
    }


def _resultado_falha():
    return {
        "website_analysis": {"status": "unavailable", "signals_available": False, "signals": None, "facts": {}, "error": "timeout", "error_type": "timeout", "checked_at": "x", "url_original": "x"},
        "commercial_fit": {"score": 40, "reasons": []},
        "website_opportunity": None, "priority_score": None, "priority_label": "needs_review", "wave2_evaluated_at": "x",
    }


def _preparar(tmp_path, monkeypatch, leads, batch_size=20, max_retry_attempts=3):
    caminho = tmp_path / "leads_com_site.json"
    caminho.write_text(json.dumps(leads), encoding="utf-8")
    monkeypatch.setattr(main_mod, "PATH_COM_SITE", str(caminho))
    monkeypatch.setattr(wave2_scoring, "carregar_config_wave2", lambda: _config_teste(batch_size, max_retry_attempts))
    monkeypatch.setattr(main_mod.lead_qualification, "carregar_icp", lambda: dict(main_mod.lead_qualification.ICP_DEFAULT))
    return caminho


def test_fase_wave2_muda_status_para_analyzed_em_sucesso(tmp_path, monkeypatch):
    leads = [{"dados_empresa": _lead_com_site(place_id="p1"), "status": "queued_future"}]
    caminho = _preparar(tmp_path, monkeypatch, leads)
    monkeypatch.setattr(wave2_scoring, "avaliar_lead", lambda lead, icp, config: _resultado_sucesso())

    main_mod.fase_wave2()

    salvo = json.loads(caminho.read_text(encoding="utf-8"))
    assert salvo[0]["status"] == "analyzed"
    assert salvo[0]["website_analysis"]["attempts"] == 1


def test_fase_wave2_muda_status_para_needs_review_em_falha(tmp_path, monkeypatch):
    leads = [{"dados_empresa": _lead_com_site(place_id="p1"), "status": "queued_future"}]
    caminho = _preparar(tmp_path, monkeypatch, leads, max_retry_attempts=3)
    monkeypatch.setattr(wave2_scoring, "avaliar_lead", lambda lead, icp, config: _resultado_falha())

    main_mod.fase_wave2()

    salvo = json.loads(caminho.read_text(encoding="utf-8"))
    assert salvo[0]["status"] == "needs_review"
    assert salvo[0]["website_analysis"]["attempts"] == 1


def test_fase_wave2_marca_unavailable_permanent_apos_max_retry_attempts(tmp_path, monkeypatch):
    lead = _lead_com_site(place_id="p1")
    leads = [{"dados_empresa": lead, "status": "needs_review",
              "website_analysis": {"attempts": 2}}]
    caminho = _preparar(tmp_path, monkeypatch, leads, max_retry_attempts=3)
    monkeypatch.setattr(wave2_scoring, "avaliar_lead", lambda l, icp, config: _resultado_falha())

    main_mod.fase_wave2()

    salvo = json.loads(caminho.read_text(encoding="utf-8"))
    assert salvo[0]["status"] == "unavailable_permanent"
    assert salvo[0]["website_analysis"]["attempts"] == 3


def test_fase_wave2_respeita_batch_size(tmp_path, monkeypatch):
    leads = [{"dados_empresa": _lead_com_site(nome=f"Empresa {i}", place_id=f"p{i}"), "status": "queued_future"} for i in range(10)]
    caminho = _preparar(tmp_path, monkeypatch, leads, batch_size=3)
    monkeypatch.setattr(wave2_scoring, "avaliar_lead", lambda lead, icp, config: _resultado_sucesso())

    main_mod.fase_wave2()

    salvo = json.loads(caminho.read_text(encoding="utf-8"))
    analisados = [l for l in salvo if l["status"] == "analyzed"]
    assert len(analisados) == 3


def test_selecionar_lote_prioriza_queued_future_antes_de_needs_review():
    leads = [
        {"dados_empresa": _lead_com_site(nome="Retry", place_id="r1"), "status": "needs_review", "website_analysis": {"attempts": 1}},
        {"dados_empresa": _lead_com_site(nome="Novo", place_id="n1"), "status": "queued_future"},
    ]
    lote = main_mod._selecionar_lote_wave2(leads, batch_size=1, max_retry_attempts=3)
    assert lote[0]["dados_empresa"]["nome"] == "Novo"


def test_selecionar_lote_nunca_inclui_unavailable_permanent():
    leads = [{"dados_empresa": _lead_com_site(place_id="p1"), "status": "unavailable_permanent", "website_analysis": {"attempts": 3}}]
    lote = main_mod._selecionar_lote_wave2(leads, batch_size=10, max_retry_attempts=3)
    assert lote == []


def test_erro_de_um_lead_nao_impede_processamento_do_proximo(tmp_path, monkeypatch):
    leads = [
        {"dados_empresa": _lead_com_site(nome="Quebra", place_id="p1"), "status": "queued_future"},
        {"dados_empresa": _lead_com_site(nome="OK", place_id="p2"), "status": "queued_future"},
    ]
    caminho = _preparar(tmp_path, monkeypatch, leads)

    chamadas = {"n": 0}

    def _avaliar(lead, icp, config):
        chamadas["n"] += 1
        if lead.get("nome") == "Quebra":
            raise RuntimeError("bug inesperado no scoring")
        return _resultado_sucesso()

    monkeypatch.setattr(wave2_scoring, "avaliar_lead", _avaliar)

    main_mod.fase_wave2()

    salvo = json.loads(caminho.read_text(encoding="utf-8"))
    status_por_nome = {l["dados_empresa"]["nome"]: l["status"] for l in salvo}
    assert status_por_nome["Quebra"] == "needs_review"
    assert status_por_nome["OK"] == "analyzed"


def test_dados_empresa_nunca_e_alterado_por_wave2(tmp_path, monkeypatch):
    lead_original = _lead_com_site(place_id="p1")
    leads = [{"dados_empresa": dict(lead_original), "status": "queued_future"}]
    caminho = _preparar(tmp_path, monkeypatch, leads)
    monkeypatch.setattr(wave2_scoring, "avaliar_lead", lambda lead, icp, config: _resultado_sucesso())

    main_mod.fase_wave2()

    salvo = json.loads(caminho.read_text(encoding="utf-8"))
    assert salvo[0]["dados_empresa"] == lead_original


def test_imprimir_top_sites_onda2_nao_quebra_com_lista_vazia(capsys):
    main_mod.imprimir_top_sites_onda2([], wave2_scoring.CONFIG_DEFAULT)
    assert "TOP SITES PARA REVISÃO" not in capsys.readouterr().out


def test_nenhuma_copy_e_gerada_nem_impressa(tmp_path, monkeypatch, capsys):
    leads = [{"dados_empresa": _lead_com_site(place_id="p1"), "status": "queued_future"}]
    _preparar(tmp_path, monkeypatch, leads)
    monkeypatch.setattr(wave2_scoring, "avaliar_lead", lambda lead, icp, config: _resultado_sucesso())

    main_mod.fase_wave2()

    saida = capsys.readouterr().out
    assert "whatsapp" not in saida.lower()
    assert "abordagem_email" not in saida.lower()


def test_wave2_nao_importa_anthropic():
    """Salvaguarda estática: a Onda 2 nunca deve reintroduzir uma chamada de LLM. Só olha as
    linhas de import (não o módulo inteiro) pra não disparar em comentários que mencionam a
    própria regra."""
    for modulo in (website_analyzer, wave2_scoring):
        linhas_import = [l for l in inspect.getsource(modulo).splitlines() if l.strip().startswith(("import ", "from "))]
        for linha in linhas_import:
            assert "anthropic" not in linha.lower()
            assert "claude_client" not in linha.lower()


def test_fase_wave2_grava_checkpoint_no_meio_do_lote(tmp_path, monkeypatch):
    """Antes, fase_wave2 só salvava DEPOIS do loop inteiro: uma queda no meio de um lote grande
    jogava fora a rodada toda (~2s de rede por site; 500 sites = ~17min de trabalho). Agora grava
    a cada CHECKPOINT_WAVE2_A_CADA análises. KeyboardInterrupt (BaseException) escapa do
    try/except do loop e do save final -- é exatamente o Ctrl+C que o checkpoint precisa cobrir."""
    leads = [{"dados_empresa": _lead_com_site(nome=f"Empresa {i}", place_id=f"p{i}"), "status": "queued_future"}
             for i in range(6)]
    caminho = _preparar(tmp_path, monkeypatch, leads)
    monkeypatch.setattr(main_mod, "CHECKPOINT_WAVE2_A_CADA", 2)

    chamadas = {"n": 0}

    def avaliar(lead, icp, config):
        chamadas["n"] += 1
        if chamadas["n"] > 4:
            raise KeyboardInterrupt("simulando Ctrl+C no meio do lote")
        return _resultado_sucesso()

    monkeypatch.setattr(wave2_scoring, "avaliar_lead", avaliar)

    try:
        main_mod.fase_wave2()
    except KeyboardInterrupt:
        pass

    salvo = json.loads(caminho.read_text(encoding="utf-8"))
    analisados = [l for l in salvo if l["status"] == "analyzed"]
    assert len(analisados) == 4, "o trabalho já feito tem que estar em disco apesar da interrupção"
    assert len(salvo) == 6, "o checkpoint grava a lista COMPLETA, não só o lote"


def test_fase_wave2_checkpoint_nao_perde_leads_fora_do_lote(tmp_path, monkeypatch):
    """O checkpoint escreve `leads` inteiro (o loop sobrescreve in-place via indice_por_chave),
    então nenhum lead fora do lote pode sumir do arquivo."""
    leads = [{"dados_empresa": _lead_com_site(nome=f"Empresa {i}", place_id=f"p{i}"), "status": "queued_future"}
             for i in range(5)]
    leads.append({"dados_empresa": _lead_com_site(nome="Já analisada", place_id="p99"), "status": "analyzed"})
    caminho = _preparar(tmp_path, monkeypatch, leads, batch_size=2)
    monkeypatch.setattr(main_mod, "CHECKPOINT_WAVE2_A_CADA", 1)
    monkeypatch.setattr(wave2_scoring, "avaliar_lead", lambda lead, icp, config: _resultado_sucesso())

    main_mod.fase_wave2()

    salvo = json.loads(caminho.read_text(encoding="utf-8"))
    assert len(salvo) == 6
    assert {l["dados_empresa"]["place_id"] for l in salvo} == {"p0", "p1", "p2", "p3", "p4", "p99"}
