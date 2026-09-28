"""Qualification da Onda 1 -- antes era um LLM, hoje é lead_qualification.qualificar_onda1,
100% Python/$0 (decisão tomada com o Douglas: o texto livre do LLM não alimentava o template,
só o relatório, e as regras já eram threshold sobre reputação/reviews/sinais). Nenhum destes
testes chama API."""
import lead_qualification as lq

ICP_PERMISSIVO = dict(lq.ICP_DEFAULT)


def _signal(nota):
    """Mesma classificação de agent_coletor.py::_classificar_reputacao -- em produção,
    'reputation_signal' já vem preenchido no lead pelo coletor; aqui replicamos só pra manter
    o fixture de teste realista (commercial_fit_score lê 'reputation_signal', não recalcula de
    nota_google)."""
    if nota is None:
        return "unknown"
    if nota < 3.5:
        return "weak"
    if nota < 4.5:
        return "moderate"
    return "strong"


def _lead(**overrides):
    base = {
        "nome": "Clínica Ejemplo", "cidade": "Alicante", "nota_google": 4.8, "review_count": 180,
        "telefone": "960000110", "email": "contacto@ejemplo.es", "instagram": "@ejemplo",
        "facebook": None, "nicho": "Fisioterapeuta",
    }
    base.update(overrides)
    base.setdefault("reputation_signal", _signal(base["nota_google"]))
    return base


def test_lead_sem_nenhum_sinal_e_desqualificado():
    """Caso real: Dental Ficticia (ontem) -- nota, reviews e redes todos ausentes, mesmo com
    telefone. Mesma regra do skill antigo: 'dados quase todos ausentes ... nenhuma evidência de
    que é um negócio ativo'."""
    lead = _lead(nota_google=None, review_count=None, instagram=None, facebook=None)
    resultado = lq.qualificar_onda1(lead, ICP_PERMISSIVO)
    assert resultado["qualified"] is False
    assert resultado["reason_to_contact"] == ""


def test_lead_com_reputacao_e_qualificado():
    lead = _lead(nota_google=4.9, review_count=250, instagram="@fisio")
    resultado = lq.qualificar_onda1(lead, ICP_PERMISSIVO)
    assert resultado["qualified"] is True
    assert resultado["reason_to_contact"] != ""
    assert "sem site" in resultado["reason_to_contact"]


def test_lead_sem_reputacao_mas_com_rede_social_e_qualificado():
    """Sinal de atividade (rede social) já basta pra não reprovar, mesmo sem nota/reviews --
    a regra é 'nenhum sinal', não 'sem reputação'."""
    lead = _lead(nota_google=None, review_count=None, instagram="@ativo")
    resultado = lq.qualificar_onda1(lead, ICP_PERMISSIVO)
    assert resultado["qualified"] is True


def test_score_alto_vira_prioridade_alta():
    lead = _lead(nota_google=4.9, review_count=250, instagram="@fisio", facebook="fb.com/fisio")
    resultado = lq.qualificar_onda1(lead, ICP_PERMISSIVO)
    assert resultado["priority"] == "alta"


def test_qualificacao_devolve_uma_dimensao_so():
    """commercial_fit e website_opportunity saíram: vinham do mesmo score com os mesmos
    cortes que priority e davam o mesmo valor em 27 de 27 leads reais, só em vocabulários
    diferentes. Na planilha pareciam três medidas independentes e não eram."""
    resultado = lq.qualificar_onda1(_lead(), ICP_PERMISSIVO)
    assert "commercial_fit" not in resultado
    assert "website_opportunity" not in resultado


def test_score_baixo_vira_prioridade_baixa():
    lead = _lead(nota_google=3.0, review_count=2, instagram=None, facebook=None, cidade=None,
                 email=None, telefone="960000110")
    resultado = lq.qualificar_onda1(lead, ICP_PERMISSIVO)
    assert resultado["priority"] == "baixa"


def test_limiares_cabem_no_range_real_da_onda1():
    """O corte 65/40 herdado da Onda 2 deixava "alta" inalcançável: sem site pra analisar,
    o teto real de score da Onda 1 é 60. Um lead com sinal máximo tem que conseguir
    chegar em "alta", senão o bucket é decoração."""
    lead = _lead(nota_google=5.0, review_count=500, instagram="@fisio", facebook="fb.com/f",
                 telefone="960000110", email="a@b.es")
    resultado = lq.qualificar_onda1(lead, ICP_PERMISSIVO)
    assert resultado["priority"] == "alta"
    assert lq.LIMIARES_QUALIFICACAO_ONDA1["alta"] <= 60


def test_enums_batem_com_vocabulario_esperado():
    lead = _lead()
    resultado = lq.qualificar_onda1(lead, ICP_PERMISSIVO)
    assert resultado["priority"] in ("alta", "media", "baixa")
    assert resultado["contactability"] in ("alta", "media", "baixa")
    assert isinstance(resultado["score"], int)
    assert 0 <= resultado["score"] <= 100
    assert isinstance(resultado["reasons"], list)
    assert isinstance(resultado["evidence"], list)
    assert isinstance(resultado["risks"], list)


def test_contactability_alta_com_telefone_e_mais_um_sinal():
    lead = _lead(telefone="960000110", email="x@x.com", instagram="@x")
    resultado = lq.qualificar_onda1(lead, ICP_PERMISSIVO)
    assert resultado["contactability"] == "alta"


def test_contactability_media_so_com_telefone():
    lead = _lead(telefone="960000110", email=None, instagram=None, facebook=None)
    resultado = lq.qualificar_onda1(lead, ICP_PERMISSIVO)
    assert resultado["contactability"] == "media"


def test_evidence_nunca_inclui_interpretacao_so_fato():
    lead = _lead(nota_google=4.9, review_count=250)
    resultado = lq.qualificar_onda1(lead, ICP_PERMISSIVO)
    assert any("4.9" in e for e in resultado["evidence"])
    assert "nenhum site vinculado à ficha do Google Maps" in resultado["evidence"]


def test_risks_sinaliza_poucos_dados_quando_poucas_reviews():
    lead = _lead(nota_google=4.5, review_count=3)
    resultado = lq.qualificar_onda1(lead, ICP_PERMISSIVO)
    assert any("genérica" in r for r in resultado["risks"])


def test_icp_exclusao_zera_score_mas_nao_derruba_o_pipeline():
    """qualificar_onda1 roda DEPOIS do filtrar_icp no funil real, então isso nunca deveria
    acontecer na prática -- mas se acontecer, não pode quebrar (reaproveita a mesma checagem
    defensiva que commercial_fit_score já tem)."""
    icp = dict(lq.ICP_DEFAULT, categorias_excluidas=["fisioterap"])
    lead = _lead(nicho="Fisioterapeuta")
    resultado = lq.qualificar_onda1(lead, icp)
    assert resultado["score"] == 0
