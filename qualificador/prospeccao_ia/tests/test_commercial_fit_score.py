import lead_qualification as lq


def _icp(**overrides):
    icp = dict(lq.ICP_DEFAULT)
    icp.update(overrides)
    return icp


def _lead(**overrides):
    base = {
        "nome": "Clínica X", "nicho": "Fisioterapeuta", "cidade": "Sevilla",
        "nota_google": 4.8, "review_count": 150, "reputation_signal": "strong",
        "telefone": "612345678", "email": "x@x.es", "instagram": "@x", "facebook": None,
    }
    base.update(overrides)
    return base


def test_lead_excluido_pelo_icp_zera_score():
    icp = _icp(rating_minimo=4.9)  # lead tem nota 4.8: corte por rating ainda zera o score
    score, razoes = lq.commercial_fit_score(_lead(), icp)
    assert score == 0
    assert "icp" in razoes[0].lower()


def test_icp_nao_zera_score_por_categoria():
    """Categoria saiu do ICP (04/10/2026): chave antiga esquecida no ICP é ignorada."""
    icp = _icp(categorias_excluidas=["fisioterap"], categorias_desejadas=["psicolog"])
    score, _ = lq.commercial_fit_score(_lead(), icp)
    assert score > 0


def test_reputacao_strong_pontua_mais_que_weak():
    icp = _icp()
    score_strong, _ = lq.commercial_fit_score(_lead(reputation_signal="strong"), icp)
    score_weak, _ = lq.commercial_fit_score(_lead(reputation_signal="weak"), icp)
    assert score_strong > score_weak


def test_reviews_faixa_alta_pontua_mais_que_faixa_baixa():
    icp = _icp()
    score_alto, _ = lq.commercial_fit_score(_lead(review_count=200), icp)
    score_baixo, _ = lq.commercial_fit_score(_lead(review_count=2), icp)
    assert score_alto > score_baixo


def test_sinal_valorizado_so_soma_quando_icp_valoriza_e_lead_tem():
    icp_valoriza = _icp(sinais_valorizados={"instagram_ativo": True, "facebook_ativo": False, "sem_site": True})
    com_instagram, _ = lq.commercial_fit_score(_lead(instagram="@x"), icp_valoriza)
    sem_instagram, _ = lq.commercial_fit_score(_lead(instagram=None), icp_valoriza)
    assert com_instagram > sem_instagram

    icp_nao_valoriza = _icp(sinais_valorizados={"instagram_ativo": False, "facebook_ativo": False, "sem_site": True})
    com_instagram_irrelevante, _ = lq.commercial_fit_score(_lead(instagram="@x"), icp_nao_valoriza)
    sem_instagram_irrelevante, _ = lq.commercial_fit_score(_lead(instagram=None), icp_nao_valoriza)
    assert com_instagram_irrelevante == sem_instagram_irrelevante


def test_cidade_prioritaria_soma_pontos():
    icp = _icp(cidades_prioritarias=["Sevilla"])
    score_prioritaria, _ = lq.commercial_fit_score(_lead(cidade="Sevilla"), icp)
    score_outra, _ = lq.commercial_fit_score(_lead(cidade="Madrid"), icp)
    assert score_prioritaria > score_outra


def test_contactabilidade_soma_pontos():
    icp = _icp()
    com_contato, _ = lq.commercial_fit_score(_lead(telefone="612345678", email="x@x.es"), icp)
    sem_contato, _ = lq.commercial_fit_score(_lead(telefone=None, email=None), icp)
    assert com_contato > sem_contato


def test_score_nunca_ultrapassa_100_nem_fica_negativo():
    icp = _icp(sinais_valorizados={"instagram_ativo": True, "facebook_ativo": True, "sem_site": True}, cidades_prioritarias=["Sevilla"])
    score, _ = lq.commercial_fit_score(_lead(instagram="@x", facebook="@x"), icp)
    assert 0 <= score <= 100


def test_ausencia_de_dado_nao_zera_score_quando_nao_e_gate_do_icp():
    icp = _icp()
    lead = _lead(reputation_signal="unknown", review_count=None, telefone=None, email=None, instagram=None, facebook=None)
    score, _ = lq.commercial_fit_score(lead, icp)
    assert score > 0
