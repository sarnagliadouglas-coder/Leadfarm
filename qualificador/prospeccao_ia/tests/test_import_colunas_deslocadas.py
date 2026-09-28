"""Recuperação da categoria em linhas de CSV com colunas deslocadas.

Em negócios com 0 avaliações a ferramenta de extração desloca as colunas: o texto "sem
avaliação" ocupa `Categories` e a categoria REAL cai em `Fulladdress`/`Street`, com
`Municipality` vazio. O `CATEGORIA_INVALIDA_RE` já detectava o lixo, mas descartava a categoria
junto -- o lead ficava com "categoría sin especificar" e, com isso, escapava do filtro comercial
(que só é checado contra o nicho) e perdia o nicho na copy. Medido nos CSVs já importados:
9 linhas afetadas, 9 recuperadas, 333 linhas íntegras intocadas.
"""
from agent_coletor import AgentColetor


def _linha_integra(**overrides):
    linha = {
        "Name": "Clínica Ejemplo", "Phone": "960000107", "Website": "", "Email": "",
        "Fulladdress": "C/ Ficticia, 1, 03000 Alacant, Alicante",
        "Street": "C/ Ficticia", "Municipality": "83, 03013 Alacant, Alicante",
        "Categories": "Centro médico público", "Review Count": "116", "Average Rating": "5.0",
        "Place Id": "place_ok", "Google Maps URL": "https://maps.google.com/?cid=1",
    }
    linha.update(overrides)
    return linha


def _linha_deslocada(categoria_real="Clínica de Fisioterapia", **overrides):
    """Reproduz o deslocamento real observado no CSV: categoria em Fulladdress/Street,
    Municipality vazio, "Nenhuma avaliação" em Categories e em Review Count."""
    linha = _linha_integra(
        Name="Fisioterapia Ficticia Diez",
        Fulladdress=categoria_real, Street=categoria_real, Municipality="",
        Categories="Nenhuma avaliação", **{"Review Count": "Nenhumaavaliação"},
        **{"Average Rating": ""}, **{"Place Id": "place_deslocado"},
    )
    linha.update(overrides)
    return linha


def test_categoria_real_e_recuperada_da_coluna_deslocada():
    lead = AgentColetor._montar_lead(_linha_deslocada("Clínica de Fisioterapia"))
    assert lead["nicho"] == "Clínica de Fisioterapia"


def test_endereco_nao_guarda_a_categoria_recuperada():
    """O que estava em Fulladdress era a categoria -- gravar aquilo como endereço seria
    persistir dado errado (e ele vai pra planilha)."""
    lead = AgentColetor._montar_lead(_linha_deslocada())
    assert lead["endereco"] is None
    assert lead["cidade"] is None  # Municipality vem vazio: esse dado se perdeu na origem


def test_recupera_qualquer_categoria_sem_lista_por_nicho():
    for categoria in ("Fisioterapeuta", "Dentista", "Centro médico", "Abogado", "Peluquería"):
        lead = AgentColetor._montar_lead(_linha_deslocada(categoria))
        assert lead["nicho"] == categoria


def test_linha_integra_nao_e_alterada():
    """Regressão crítica: a recuperação não pode promover o endereço de uma linha boa a
    categoria."""
    lead = AgentColetor._montar_lead(_linha_integra())
    assert lead["nicho"] == "Centro médico público"
    assert lead["endereco"] == "C/ Ficticia, 1, 03000 Alacant, Alicante"


def test_endereco_de_verdade_nunca_vira_categoria():
    """Endereço espanhol sempre tem número e quase sempre vírgula; categoria do Google nunca
    tem. É esse teste que separa os dois casos."""
    linha = _linha_deslocada()
    linha["Fulladdress"] = "C/ Mayor, 12"
    linha["Street"] = "C/ Mayor"          # sem número, mas ainda é rua
    lead = AgentColetor._montar_lead(linha)
    assert lead["nicho"] == "categoría sin especificar"
    assert lead["endereco"] == "C/ Mayor, 12"


def test_sem_candidato_algum_continua_sem_categoria():
    linha = _linha_deslocada()
    linha["Fulladdress"] = ""
    linha["Street"] = ""
    lead = AgentColetor._montar_lead(linha)
    assert lead["nicho"] == "categoría sin especificar"


def test_lixo_nas_duas_colunas_nao_vira_categoria():
    linha = _linha_deslocada()
    linha["Fulladdress"] = "Nenhuma avaliação"
    linha["Street"] = "No hay reseñas"
    lead = AgentColetor._montar_lead(linha)
    assert lead["nicho"] == "categoría sin especificar"
