import lead_qualification as lq


def _item(score, priority="alta", review_count=100, nome="Lead"):
    return {
        "dados_empresa": {"nome": nome, "review_count": review_count},
        "qualificacao": {"score": score, "priority": priority},
        "status": "qualified_pending_copy",
    }


def test_ranquear_ordena_por_score_desc():
    itens = [_item(50), _item(90), _item(70)]
    ranqueados = lq.ranquear(itens)
    assert [i["qualificacao"]["score"] for i in ranqueados] == [90, 70, 50]


def test_ranquear_desempata_por_prioridade():
    itens = [_item(80, priority="baixa"), _item(80, priority="alta"), _item(80, priority="media")]
    ranqueados = lq.ranquear(itens)
    assert [i["qualificacao"]["priority"] for i in ranqueados] == ["alta", "media", "baixa"]


def test_ranquear_desempata_por_review_count():
    itens = [_item(80, review_count=10), _item(80, review_count=200)]
    ranqueados = lq.ranquear(itens)
    assert ranqueados[0]["dados_empresa"]["review_count"] == 200


def test_ranquear_nunca_filtra_nem_recalcula_score():
    itens = [_item(10), _item(99)]
    ranqueados = lq.ranquear(itens)
    assert len(ranqueados) == 2
    assert {i["qualificacao"]["score"] for i in ranqueados} == {10, 99}


def test_separar_top_n_faz_slicing_puro():
    itens = [_item(90), _item(80), _item(70), _item(60)]
    top, resto = lq.separar_top_n(itens, 2)
    assert len(top) == 2 and len(resto) == 2
    assert top + resto == itens


def test_separar_top_n_com_menos_itens_que_o_limite():
    itens = [_item(90)]
    top, resto = lq.separar_top_n(itens, 10)
    assert len(top) == 1 and resto == []
