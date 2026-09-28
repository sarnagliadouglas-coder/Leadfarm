import lead_qualification as lq


def _icp(**overrides):
    icp = dict(lq.ICP_DEFAULT)
    icp.update(overrides)
    return icp


def test_defaults_sao_totalmente_permissivos(lead_excelente_sem_site, lead_ruim_sem_site):
    icp = _icp()
    aprovados, reprovados = lq.filtrar_icp([lead_excelente_sem_site, lead_ruim_sem_site], icp)
    assert len(aprovados) == 2
    assert reprovados == []


def test_categoria_desejada_filtra_fora_do_perfil(lead_excelente_sem_site):
    icp = _icp(categorias_desejadas=["psicolog"])
    aprovados, reprovados = lq.filtrar_icp([lead_excelente_sem_site], icp)
    assert aprovados == []
    assert reprovados[0]["rejection_reason"] == "icp_categoria_fora_do_perfil"


def test_categoria_desejada_aceita_match_por_substring(lead_excelente_sem_site):
    icp = _icp(categorias_desejadas=["fisioterap"])
    aprovados, reprovados = lq.filtrar_icp([lead_excelente_sem_site], icp)
    assert len(aprovados) == 1
    assert reprovados == []


def test_categoria_excluida_reprova(lead_excelente_sem_site):
    icp = _icp(categorias_excluidas=["fisioterap"])
    aprovados, reprovados = lq.filtrar_icp([lead_excelente_sem_site], icp)
    assert aprovados == []
    assert reprovados[0]["rejection_reason"] == "icp_categoria_excluida"


def test_rating_minimo_desligado_por_padrao_nao_corta_lead_ruim(lead_ruim_sem_site):
    icp = _icp()  # rating_minimo=0
    aprovados, _ = lq.filtrar_icp([lead_ruim_sem_site], icp)
    assert len(aprovados) == 1


def test_rating_minimo_ligado_corta_valor_conhecido_abaixo(lead_ruim_sem_site):
    icp = _icp(rating_minimo=4.0)
    aprovados, reprovados = lq.filtrar_icp([lead_ruim_sem_site], icp)
    assert aprovados == []
    assert reprovados[0]["rejection_reason"] == "icp_rating_abaixo_minimo"


def test_rating_minimo_ligado_nunca_corta_por_ausencia_de_dado(lead_dados_ausentes):
    icp = _icp(rating_minimo=4.0)
    aprovados, reprovados = lq.filtrar_icp([lead_dados_ausentes], icp)
    assert len(aprovados) == 1
    assert reprovados == []


def test_reviews_minimo_ligado_corta_valor_conhecido_abaixo(lead_ruim_sem_site):
    icp = _icp(reviews_minimo=20)
    aprovados, reprovados = lq.filtrar_icp([lead_ruim_sem_site], icp)
    assert aprovados == []
    assert reprovados[0]["rejection_reason"] == "icp_reviews_abaixo_minimo"


def test_carregar_icp_sem_arquivo_usa_defaults(tmp_path):
    icp = lq.carregar_icp(str(tmp_path / "nao_existe.json"))
    assert icp == lq.ICP_DEFAULT


def test_carregar_icp_malformado_usa_defaults(tmp_path):
    caminho = tmp_path / "icp.json"
    caminho.write_text("{ isso nao é json", encoding="utf-8")
    icp = lq.carregar_icp(str(caminho))
    assert icp == lq.ICP_DEFAULT


def test_icp_tem_filtro_ativo_falso_com_config_padrao():
    """Config padrao nao corta ninguem -- o relatorio precisa poder dizer isso em vez de
    deixar parecer que o pre-filtro falhou."""
    assert lq.icp_tem_filtro_ativo(dict(lq.ICP_DEFAULT)) is False


def test_icp_tem_filtro_ativo_verdadeiro_com_categoria_excluida():
    assert lq.icp_tem_filtro_ativo(_icp(categorias_excluidas=["dental"])) is True


def test_icp_tem_filtro_ativo_verdadeiro_com_rating_minimo():
    assert lq.icp_tem_filtro_ativo(_icp(rating_minimo=4.0)) is True
