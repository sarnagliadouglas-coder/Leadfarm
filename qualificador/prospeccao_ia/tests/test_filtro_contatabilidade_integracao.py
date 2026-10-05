"""Integração do filtro de contatabilidade (lead_qualification.filtrar_contactabilidade_onda1)
dentro de fase_qualify: o lead sem canal precisa sair da fila, ir pra leads_reprovados.json com
o motivo certo, NUNCA chegar na Qualification, e não ser reavaliado na rodada seguinte.
"""
import json

import main as main_mod


def _isolar_paths(tmp_path, monkeypatch):
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


def _ler(caminho):
    if not caminho.exists():
        return []
    conteudo = caminho.read_text(encoding="utf-8").strip()
    return json.loads(conteudo) if conteudo else []


def _lead_sem_canal(**overrides):
    lead = {
        "place_id": "sem_canal_1", "nome": "Dental Ficticia S L", "nicho": "Dentista",
        "cidade": None, "telefone": "960000104", "email": None,
        "instagram": None, "facebook": None,
        "nota_google": 4.5, "review_count": 20, "website": None,
    }
    lead.update(overrides)
    return lead


def _lead_com_movel(**overrides):
    lead = {
        "place_id": "com_movel_1", "nome": "Clínica Ejemplo", "nicho": "Dentista",
        "cidade": "Sevilla", "telefone": "612345678", "email": None,
        "instagram": None, "facebook": None,
        "nota_google": 4.8, "review_count": 40, "website": None,
    }
    lead.update(overrides)
    return lead


def test_lead_sem_canal_nunca_chega_na_qualification(tmp_path, monkeypatch):
    caminhos = _isolar_paths(tmp_path, monkeypatch)
    caminhos["PATH_COLETADOS"].write_text(json.dumps([
        {"dados_empresa": _lead_sem_canal(), "status": "eligible"}
    ]), encoding="utf-8")

    metricas = main_mod.fase_qualify()

    assert metricas["total_reprovados_contato"] == 1
    assert metricas["chamadas_qualification"] == 0  # nem chegou na Qualification
    assert _ler(caminhos["PATH_QUALIFICADOS"]) == []

    reprovados = _ler(caminhos["PATH_REPROVADOS"])
    assert len(reprovados) == 1
    assert reprovados[0]["rejection_reason"] == "sem_canal_de_contato"
    assert reprovados[0]["dados_empresa"]["place_id"] == "sem_canal_1"


def test_lead_com_celular_e_qualificado_normalmente(tmp_path, monkeypatch):
    caminhos = _isolar_paths(tmp_path, monkeypatch)
    caminhos["PATH_COLETADOS"].write_text(json.dumps([
        {"dados_empresa": _lead_com_movel(), "status": "eligible"}
    ]), encoding="utf-8")

    metricas = main_mod.fase_qualify()

    assert metricas["total_reprovados_contato"] == 0
    assert metricas["chamadas_qualification"] == 1
    assert _ler(caminhos["PATH_REPROVADOS"]) == []
    assert len(_ler(caminhos["PATH_QUALIFICADOS"])) == 1


def test_lead_excluido_nao_e_reavaliado_na_rodada_seguinte(tmp_path, monkeypatch):
    """Regressão-alvo: sem incluir os reprovados por contatabilidade em `chaves_tratadas`, o
    lead continuaria marcado 'eligible' em leads_coletados.json e seria reprocessado (e
    reexcluído) a cada rodada, para sempre."""
    caminhos = _isolar_paths(tmp_path, monkeypatch)
    caminhos["PATH_COLETADOS"].write_text(json.dumps([
        {"dados_empresa": _lead_sem_canal(), "status": "eligible"}
    ]), encoding="utf-8")

    main_mod.fase_qualify()
    pendentes = _ler(caminhos["PATH_COLETADOS"])
    assert pendentes == [], "o lead excluído não pode continuar pendente"

    # Rodada seguinte: fila vazia, nada mais a avaliar -- não deveria reprocessar nada.
    metricas_2 = main_mod.fase_qualify()
    assert metricas_2 is None
    assert len(_ler(caminhos["PATH_REPROVADOS"])) == 1  # continua com 1 só, não duplicou


def test_filtro_roda_depois_do_icp_e_antes_da_qualification(tmp_path, monkeypatch):
    """Um lead excluído pelo pré-filtro ICP não deve, além disso, ser contado como excluído
    por falta de canal -- os dois filtros são independentes e cada lead cai em só um."""
    caminhos = _isolar_paths(tmp_path, monkeypatch)
    icp_customizado = {
        "rating_minimo": 4.0, "reviews_minimo": 0, "cidades_prioritarias": [],
        "sinais_valorizados": {},
    }
    # carregar_icp(caminho=CAMINHO_ICP) tem o default resolvido na definição da função --
    # monkeypatch no atributo de módulo não alcançaria o default já vinculado. Substituir a
    # função inteira é o jeito direto de injetar o ICP customizado neste teste.
    monkeypatch.setattr(main_mod.lead_qualification, "carregar_icp", lambda *a, **k: dict(icp_customizado))

    lead_excluido_por_icp = _lead_sem_canal(place_id="icp_1", nicho="Dentista", nota_google=3.0)
    caminhos["PATH_COLETADOS"].write_text(json.dumps([
        {"dados_empresa": lead_excluido_por_icp, "status": "eligible"}
    ]), encoding="utf-8")

    metricas = main_mod.fase_qualify()

    assert metricas["total_reprovados_icp"] == 1
    assert metricas["total_reprovados_contato"] == 0  # nunca chegou no segundo filtro
    reprovados = _ler(caminhos["PATH_REPROVADOS"])
    assert reprovados[0]["rejection_reason"] == "icp_rating_abaixo_minimo"
