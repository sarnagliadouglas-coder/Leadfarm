"""Cidade do nome curto pela cidade CARIMBADA no lead (contrato 2.3.0, multicidade, diretor
06/10/2026): `campanha_cidade` -- no lead do contrato (aba Nata) e no CSV humano (aba Geral).
Nunca a cidade de uma campanha procurada por id, nunca adivinhada. Dados fictícios."""

import pytest

import angulo_mensagem as am
import contrato_loader as cl


def _evidencia(valor, estado):
    return cl.CampoEvidencia({"valor": valor, "estado": estado})


def test_cidade_do_lead_le_contrato_e_csv_humano():
    assert am.cidade_do_lead({"campanha_cidade": _evidencia("Murcia", cl.ESTADO_CONFIRMADO_PRESENTE)}) == "Murcia"
    assert am.cidade_do_lead({"campanha_cidade": _evidencia(None, cl.ESTADO_NAO_VERIFICADO)}) is None
    assert am.cidade_do_lead({"campanha_cidade": _evidencia("", cl.ESTADO_CONFIRMADO_AUSENTE)}) is None
    assert am.cidade_do_lead({"campanha_cidade": " Elche "}) == "Elche"
    assert am.cidade_do_lead({"campanha_cidade": "NAO_VERIFICADO"}) is None
    assert am.cidade_do_lead({"campanha_cidade": ""}) is None
    assert am.cidade_do_lead({}) is None


def test_nome_curto_corta_a_cidade_do_lead():
    assert am.nome_curto_seguro("Lunaria Murcia", {}, cidade="Murcia") == "Lunaria"
    assert am.nome_curto_seguro("Lunaria Alicante", {}, cidade="Murcia") == "Lunaria Alicante"  # controle


@pytest.mark.parametrize("cidade", [None, "", "   "])
def test_lead_sem_cidade_pede_revisao_nunca_adivinha(cidade):
    with pytest.raises(am.LinhaPedeRevisaoError) as exc:
        am.nome_curto_seguro("Lunaria Murcia", {}, cidade=cidade)
    assert "REVISAR NOME" in str(exc.value) and "campanha_cidade" in str(exc.value)


def test_mensagem_direta_usa_a_cidade_da_linha_do_csv():
    """Ponta da Geral: `montar_mensagem_direta` passa a `campanha_cidade` da linha do CSV humano."""
    mensagens = {"saudacao": "Hola, buenas.",
                 "sem_site_sem_reputacao": {"fato": "vi {nombre} en Google Maps.", "cta": "¿Hablamos?"}}
    linha = {"nome": "Lunaria Murcia", "nicho": "Teste", "campanha_cidade": "Murcia"}
    _, entrada = am.montar_mensagem_direta("sem_site", linha, apresentacao="", mensagens=mensagens)
    assert entrada["nombre"] == "Lunaria"
    linha_elche = {**linha, "campanha_cidade": "Elche"}
    _, entrada2 = am.montar_mensagem_direta("sem_site", linha_elche, apresentacao="", mensagens=mensagens)
    assert entrada2["nombre"] == "Lunaria Murcia"  # controle: outra cidade não corta "Murcia"
    sem_cidade = {k: v for k, v in linha.items() if k != "campanha_cidade"}
    with pytest.raises(am.LinhaPedeRevisaoError):
        am.montar_mensagem_direta("sem_site", sem_cidade, apresentacao="", mensagens=mensagens)
