import json

import main as main_mod


def test_chave_dedup_prioridade_place_id():
    lead = {"place_id": "abc", "website": "https://x.com", "telefone": "600000000", "nome": "X", "cidade": "Y"}
    assert main_mod.chave_dedup(lead) == "place_id:abc"


def test_chave_dedup_fallback_dominio():
    lead = {"place_id": None, "website": "https://Exemplo.es/pagina", "telefone": "600000000"}
    assert main_mod.chave_dedup(lead) == "dominio:exemplo.es"


def test_chave_dedup_fallback_telefone():
    lead = {"place_id": None, "website": None, "telefone": "+34 600 00 00 00"}
    assert main_mod.chave_dedup(lead) == "telefone:+34600000000"


def test_chave_dedup_fallback_nome_cidade():
    lead = {"place_id": None, "website": None, "telefone": None, "nome": "Clinica X", "cidade": "Sevilla"}
    assert main_mod.chave_dedup(lead) == "nome_cidade:clinica x|sevilla"


def test_todas_chaves_conhecidas_inclui_leads_qualificados(tmp_path, monkeypatch):
    """Regressão-alvo (seção 22 do plano): sem essa inclusão, reimportar um CSV poderia
    duplicar um lead que já está em leads_qualificados.json."""
    monkeypatch.setattr(main_mod, "PATH_COLETADOS", str(tmp_path / "coletados.json"))
    monkeypatch.setattr(main_mod, "PATH_COM_SITE", str(tmp_path / "com_site.json"))
    monkeypatch.setattr(main_mod, "PATH_REPROVADOS", str(tmp_path / "reprovados.json"))
    caminho_qualificados = tmp_path / "qualificados.json"
    monkeypatch.setattr(main_mod, "PATH_QUALIFICADOS", str(caminho_qualificados))

    caminho_qualificados.write_text(json.dumps([
        {"dados_empresa": {"place_id": "abc"}, "qualificacao": {}, "status": "qualified"}
    ]), encoding="utf-8")

    conhecidas = main_mod._todas_chaves_conhecidas()
    assert "place_id:abc" in conhecidas


def test_mover_para_reprovados_extrai_motivo_pro_nivel_do_registro(tmp_path, monkeypatch):
    monkeypatch.setattr(main_mod, "PATH_REPROVADOS", str(tmp_path / "reprovados.json"))
    lead = {"place_id": "xyz", "nome": "Fora do perfil", "rejection_reason": "icp_categoria_excluida"}

    n = main_mod._mover_para_reprovados([lead])

    assert n == 1
    salvo = json.loads((tmp_path / "reprovados.json").read_text(encoding="utf-8"))
    assert salvo[0]["status"] == "rejected"
    assert salvo[0]["rejection_reason"] == "icp_categoria_excluida"
    assert "rejection_reason" not in salvo[0]["dados_empresa"]


def test_mover_para_reprovados_vazio_nao_escreve_arquivo(tmp_path, monkeypatch):
    monkeypatch.setattr(main_mod, "PATH_REPROVADOS", str(tmp_path / "reprovados.json"))
    n = main_mod._mover_para_reprovados([])
    assert n == 0
    assert not (tmp_path / "reprovados.json").exists()


def test_imprimir_qualificados_onda1_nao_quebra_com_lista_vazia(capsys):
    main_mod.imprimir_qualificados_onda1([])
    assert capsys.readouterr().out == ""


def test_imprimir_qualificados_onda1_nao_quebra_com_campos_parciais(capsys):
    registro = {
        "dados_empresa": {"nome": "Empresa X"},
        "qualificacao": {"score": 88, "priority": "alta"},
        "status": "qualified",
    }
    main_mod.imprimir_qualificados_onda1([registro])
    saida = capsys.readouterr().out
    assert "Empresa X" in saida
    assert "alta" in saida


def test_imprimir_metricas_nao_quebra(capsys):
    m = {
        "total_avaliados_pre_filtro": 10, "total_reprovados_icp": 1, "chamadas_qualification": 9,
        "qualificados": 5, "desqualificados": 4,
        "custo_total_usd": 0.0,
    }
    main_mod.imprimir_metricas(m)
    assert "MÉTRICAS" in capsys.readouterr().out
