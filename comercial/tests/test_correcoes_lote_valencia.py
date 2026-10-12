"""Correções do primeiro lote 2.3.0 real (decisões do diretor, 12/10/2026):

a) lentidão com número só quando a segunda medição do QUALIFICADOR concordou
   (`psi.segunda_medicao.concorda` true: as duas medições >= 10 s; `lcp_ms` é
   o menor dos dois) -- `rodadas` sozinho não basta, porque conta também a
   rodada que falhou;
b) o e-mail de modelo citado pelo `defeito_visivel` ("tu@email.com") não é
   lido como tuteo pelo validador; o mesmo e-mail fora do `defeito_visivel`
   continua recusado;
c) o ângulo `contato` (telefone não clicável) não é usado quando o sinal
   estático achou link de WhatsApp no site; sinal ausente/falso/não medido não
   bloqueia (D15: ausência no HTML estático não prova nada).

Config REAL de `config/`, leads fictícios; cada regra com controle negativo."""

import pytest

from contrato_loader import LeadQualificado

import angulo_mensagem as am
import validador_mensagem

_REGRAS = am.carregar_regras_angulo()
_MENSAGENS = am.carregar_mensagens_angulo()
_APRESENTACAO = am.carregar_apresentacao()
_CONFIG_VALIDACAO = validador_mensagem.carregar_config()

_NOME = "Psicología Ficticio Sur"
_SEM_BLOCO = object()


def _lead(email=None, telefone_na_pagina=None, lcp_ms=None, rodadas=2, segunda=_SEM_BLOCO, sinais_site=_SEM_BLOCO):
    def ev(valor):
        return {"valor": valor, "estado": "CONFIRMADO_PRESENTE" if valor not in (None, "") else "NAO_VERIFICADO"}

    psi = None
    if lcp_ms is not None:
        psi = {"estado": "CONFIRMADO_PRESENTE", "lcp_ms": lcp_ms, "motivo": None, "medido_em": None, "rodadas": rodadas}
        if segunda is not _SEM_BLOCO:
            psi["segunda_medicao"] = segunda
    dados = {
        "place_id": "p1",
        "campanha_nicho": ev("Psicólogos"),
        "campanha_cidade": ev("Murcia"),
        "identidade": {"nome": _NOME, "nicho": "Psicólogo", "cidade": None, "endereco": None, "google_maps_url": None},
        "contato": {"whatsapp_apto": True, "email": ev(email)},
        "analise_tecnica_site": {
            "status": "ok", "error_type": None, "avaliado_em": None, "telefone_na_pagina": ev(telefone_na_pagina),
        },
        "reputacao": {"nota_google": ev(None), "review_count": ev(None)},
        "problema_vendavel": [],
        "psi": psi,
    }
    if sinais_site is not _SEM_BLOCO:
        dados["evidencias_qualificador"] = {"fatos": [], "sinais_site": sinais_site}
    return LeadQualificado(dados)


def _escolher(lead):
    return am.escolher_angulo_nata(lead, [lead], _REGRAS)


def _montar_e_validar(lead):
    angulo = _escolher(lead)
    mensagem, entrada = am.montar_mensagem_nata(
        angulo, lead, [lead], apresentacao=_APRESENTACAO, regras=_REGRAS, mensagens=_MENSAGENS,
    )
    resultado = am.validar_mensagem_angulo(
        mensagem, angulo, entrada, nome_negocio=_NOME, config_validacao=_CONFIG_VALIDACAO,
    )
    return angulo, mensagem, entrada, resultado


def _segunda(concorda, lcp_ms=12000, lcp_ms_primeira=14000):
    """Mesma forma do bloco que `main._com_segunda_medicao` do QUALIFICADOR grava."""
    return {"estado": "CONFIRMADO_PRESENTE" if lcp_ms is not None else "NAO_VERIFICADO", "motivo": None,
            "medido_em": "2026-10-12T10:00:00+00:00", "lcp_ms": lcp_ms, "lcp_ms_primeira": lcp_ms_primeira,
            "limiar_ms": 10000, "concorda": concorda, "falha_transiente": False, "tentativas": 1, "rodadas": 1}


# --- a) segunda medição ----------------------------------------------------------------


def test_lentidao_com_segunda_medicao_concordante_cita_o_menor():
    # o QUALIFICADOR já gravou lcp_ms = min(14000, 12000)
    lead = _lead(lcp_ms=12000, segunda=_segunda(True))
    angulo, mensagem, _, resultado = _montar_e_validar(lead)
    assert angulo == "lentidao"
    assert "unos 12 segundos" in mensagem
    assert resultado.valido, resultado.motivos


@pytest.mark.parametrize("segunda", [
    _segunda(False, lcp_ms=9000),           # segunda abaixo de 10 s (o QUALIFICADOR já trocaria o lcp_ms)
    _segunda(False, lcp_ms=None),           # segunda falhou
    _SEM_BLOCO,                             # lote anterior à segunda medição
    None,
    {"concorda": "true"},                   # só o booleano true vale
])
def test_lentidao_sem_concordancia_nao_cita_numero(segunda):
    lead = _lead(lcp_ms=14000, segunda=segunda)
    assert _escolher(lead) == am.SEM_ANGULO  # lentidão sem número segue desligada


def test_concordancia_nao_dispensa_as_rodadas_minimas():
    assert _escolher(_lead(lcp_ms=12000, rodadas=1, segunda=_segunda(True))) == am.SEM_ANGULO
    assert _escolher(_lead(lcp_ms=12000, rodadas=2, segunda=_segunda(True))) == "lentidao"  # controle


# --- b) "tu@email.com" no defeito_visivel ----------------------------------------------


def test_email_de_modelo_tu_arroba_dispara_defeito_visivel_e_passa_no_validador():
    lead = _lead(email="tu@email.com", telefone_na_pagina="texto", lcp_ms=12000, segunda=_segunda(True))
    angulo, mensagem, entrada, resultado = _montar_e_validar(lead)
    assert angulo == "defeito_visivel"
    assert entrada["texto_encontrado"] == "tu@email.com"
    assert '"tu@email.com"' in mensagem
    assert resultado.valido, resultado.motivos


def _mensagem_com_email(email):
    return am.compor_mensagem(
        _MENSAGENS["defeito_visivel"], _MENSAGENS["saudacao"], _APRESENTACAO, texto_encontrado=email,
    )


def test_mesmo_email_fora_do_defeito_visivel_continua_recusado():
    mensagem = _mensagem_com_email("tu@email.com")
    resultado = am.validar_mensagem_angulo(
        mensagem, "defeito_visivel", {}, nome_negocio=_NOME, config_validacao=_CONFIG_VALIDACAO,
    )
    assert not resultado.valido
    motivos = " ".join(resultado.motivos)
    assert "domínio ou endereço" in motivos
    assert "tratamento informal" in motivos


def test_tuteo_fora_do_email_citado_continua_recusado():
    mensagem = _mensagem_com_email("tu@email.com").replace("¿Le paso", "¿Te paso una captura a tu móvil o le paso")
    resultado = am.validar_mensagem_angulo(
        mensagem, "defeito_visivel", {"texto_encontrado": "tu@email.com"},
        nome_negocio=_NOME, config_validacao=_CONFIG_VALIDACAO,
    )
    assert not resultado.valido
    assert any("tratamento informal" in m for m in resultado.motivos), resultado.motivos


def test_email_diferente_do_citado_continua_recusado():
    mensagem = _mensagem_com_email("tu@email.com") + " info@tuweb.es"
    resultado = am.validar_mensagem_angulo(
        mensagem, "defeito_visivel", {"texto_encontrado": "tu@email.com"},
        nome_negocio=_NOME, config_validacao=_CONFIG_VALIDACAO,
    )
    assert any("domínio ou endereço" in m for m in resultado.motivos), resultado.motivos


# --- c) telefone não clicável com WhatsApp no site -------------------------------------


def test_telefone_texto_com_whatsapp_no_site_nao_usa_contato():
    lead = _lead(telefone_na_pagina="texto", sinais_site={"has_whatsapp_link": True, "has_tel_link": False})
    assert _escolher(lead) == am.SEM_ANGULO


def test_telefone_texto_com_whatsapp_cai_para_a_lentidao():
    lead = _lead(telefone_na_pagina="texto", lcp_ms=12000, segunda=_segunda(True),
                 sinais_site={"has_whatsapp_link": True})
    assert _escolher(lead) == "lentidao"


@pytest.mark.parametrize("sinais_site", [
    {"has_whatsapp_link": False},
    {},                                     # sinal não medido
    None,                                   # sem sinais estáticos
    _SEM_BLOCO,                             # sem evidencias_qualificador
    {"has_whatsapp_link": "true"},          # só o booleano true bloqueia
])
def test_ausencia_do_sinal_de_whatsapp_nao_bloqueia_o_contato(sinais_site):
    lead = _lead(telefone_na_pagina="texto", sinais_site=sinais_site)
    assert _escolher(lead) == "contato"


def test_whatsapp_no_site_nao_bloqueia_o_defeito_visivel():
    lead = _lead(email="info@tudominio.com", telefone_na_pagina="texto", sinais_site={"has_whatsapp_link": True})
    assert _escolher(lead) == "defeito_visivel"
