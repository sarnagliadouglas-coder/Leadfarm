"""Filtro de contatabilidade da Onda 1 (decisão do Douglas): um lead sem email, sem rede social
e sem celular espanhol (WhatsApp) não tem nenhum canal alcançável -- entraria na esteira, seria
qualificado, ganharia copy, e não haveria como enviar nada. Exclusivo da Onda 1 -- a Onda 2 tem
o site como canal próprio e não usa este filtro.
"""
import lead_qualification as lq


def _lead(**overrides):
    base = {"nome": "Clínica Ejemplo", "telefone": None, "email": None,
            "instagram": None, "facebook": None}
    base.update(overrides)
    return base


# --- normalização do telefone ---------------------------------------------------------------

def test_normaliza_formatos_variados_do_mesmo_numero():
    variantes = ["612345678", "612 34 56 78", "612-345-678", "+34 612345678",
                 "+34612345678", "0034612345678", "0034 612 34 56 78"]
    for v in variantes:
        assert lq._numero_nacional_espanhol(v) == "612345678", v


def test_numero_vazio_ou_ausente_normaliza_pra_string_vazia():
    assert lq._numero_nacional_espanhol(None) == ""
    assert lq._numero_nacional_espanhol("") == ""
    assert lq._numero_nacional_espanhol("   ") == ""


# --- prefixo móvel (6 e 7) --------------------------------------------------------------------

def test_prefixo_6_e_movel():
    assert lq._e_movel_espanhol("612345678") is True
    assert lq._e_movel_espanhol("+34 612 34 56 78") is True


def test_prefixo_7_tambem_e_movel():
    """Faixa liberada pro celular em 2021 -- números reais na base ('722...', '744...')
    recebem WhatsApp normalmente. Excluí-los seria descartar lead alcançável."""
    assert lq._e_movel_espanhol("700000102") is True
    assert lq._e_movel_espanhol("700000103") is True


def test_prefixo_8_e_9_sao_fixo_nao_movel():
    assert lq._e_movel_espanhol("960000105") is False
    assert lq._e_movel_espanhol("860000105") is False


def test_telefone_ausente_nao_e_movel():
    assert lq._e_movel_espanhol(None) is False
    assert lq._e_movel_espanhol("") is False


# --- a decisão de excluir ----------------------------------------------------------------------

def test_sem_nenhum_canal_e_fixo_e_excluido():
    lead = _lead(telefone="960000105")
    aprovados, reprovados = lq.filtrar_contactabilidade_onda1([lead])
    assert aprovados == []
    assert len(reprovados) == 1
    assert reprovados[0]["rejection_reason"] == "sem_canal_de_contato"


def test_sem_telefone_nenhum_e_excluido():
    lead = _lead()
    _, reprovados = lq.filtrar_contactabilidade_onda1([lead])
    assert len(reprovados) == 1


def test_com_email_e_mantido_mesmo_com_telefone_fixo():
    lead = _lead(telefone="960000105", email="contacto@ejemplo.es")
    aprovados, reprovados = lq.filtrar_contactabilidade_onda1([lead])
    assert aprovados == [lead]
    assert reprovados == []


def test_com_instagram_e_mantido_sem_telefone_nenhum():
    lead = _lead(instagram="@ejemplo")
    aprovados, _ = lq.filtrar_contactabilidade_onda1([lead])
    assert aprovados == [lead]


def test_com_facebook_e_mantido():
    lead = _lead(facebook="fb.com/ejemplo")
    aprovados, _ = lq.filtrar_contactabilidade_onda1([lead])
    assert aprovados == [lead]


def test_celular_6_sem_outro_canal_e_mantido():
    lead = _lead(telefone="612345678")
    aprovados, reprovados = lq.filtrar_contactabilidade_onda1([lead])
    assert aprovados == [lead]
    assert reprovados == []


def test_celular_7_sem_outro_canal_e_mantido():
    lead = _lead(telefone="700000102")
    aprovados, _ = lq.filtrar_contactabilidade_onda1([lead])
    assert aprovados == [lead]


def test_lote_misto_separa_corretamente():
    mantem_email = _lead(nome="A", email="a@a.es")
    mantem_movel = _lead(nome="B", telefone="612345678")
    exclui_fixo = _lead(nome="C", telefone="960000105")
    exclui_sem_tel = _lead(nome="D")

    aprovados, reprovados = lq.filtrar_contactabilidade_onda1(
        [mantem_email, mantem_movel, exclui_fixo, exclui_sem_tel]
    )

    assert {l["nome"] for l in aprovados} == {"A", "B"}
    assert {l["nome"] for l in reprovados} == {"C", "D"}
    assert all(l["rejection_reason"] == "sem_canal_de_contato" for l in reprovados)
