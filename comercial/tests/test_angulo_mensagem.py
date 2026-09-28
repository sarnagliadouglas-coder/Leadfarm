"""Testes de angulo_mensagem.py — MVP de primeira mensagem por modelo fixo
(mudança de rumo, decisão do diretor, 24/09/2026; sexta rodada no mesmo dia
renomeou "reputacao" para "poucas_avaliacoes", subiu o multiplicador do
concorrente de 5x para 10x, baixou a nota mínima de 4,5 para 4,0, dividiu a
mensagem em duas faixas de avaliações, trocou "doctoralia" por "portal"
genérico, e amarrou o número de segundos da lentidão a uma medição
consistente). Nenhuma chamada de LLM. Cada regra de ângulo ganha um caso que
escolhe, um que não escolhe, e onde fizer sentido um controle negativo
adicional."""

import pytest

from contrato_loader import LeadQualificado

import angulo_mensagem as am

_REGRAS = {
    "poucas_avaliacoes": {
        "nota_minima": 4.0, "avaliacoes_minimo": 1, "avaliacoes_maximo": 30,
        "multiplicador_concorrente_minimo": 10,
    },
    "lentidao": {"lcp_minimo_ms": 10000, "rodadas_minimas_para_citar_numero": 2},
}

def _m(fato, consequencia, cta):
    return {"fato": fato, "consequencia": consequencia, "cta": cta}


_C_AVAL = "Cuando alguien compara varias consultas en Google, puede encontrarse con otras que tienen muchas más reseñas."
_C_AVAL_1 = "Cuando alguien compara varias consultas en Google, puede encontrarse con otra que tiene muchas más reseñas."
_CTA_AVAL = "¿Suelen pedir a los pacientes que les dejen una reseña?"
_C_LENT = "Para alguien que entra desde el móvil, esa espera puede resultar una fricción."
_C_SITE = "Si alguien quiere ampliar información, hoy tiene que hacerlo por otros canales."
_C_REDE = "Para alguien que quiere saber qué tratan, puede resultar menos directo que una web propia."
_C_CONS = "Para alguien que quiere volver a encontrarles, una dirección propia puede ser más fácil de recordar."

# Blocos fato -> consequência -> CTA (decisão do diretor, 27/09/2026). Fixture
# própria, não a copy real de config/mensagens_angulo.json.
_MENSAGENS = {
    "saudacao": "Hola, buenas.",
    "contato": _m("entré en su web desde el móvil y el teléfono no se puede pulsar para llamar.",
                  "Añade una fricción justo cuando alguien quiere contactar.", "¿se la envío?"),
    "poucas_avaliacoes_5_30": _m("vi su ficha de Google, un {nota} de media, pero con solo {n} reseñas.", _C_AVAL, _CTA_AVAL),
    "poucas_avaliacoes_5_30_singular": _m("vi su ficha de Google, un {nota} de media, pero con solo {n} reseñas.", _C_AVAL_1, _CTA_AVAL),
    "poucas_avaliacoes_1_4": _m("vi su ficha de Google, que todavía tiene solo {n} {reseñas_palavra}.", _C_AVAL, _CTA_AVAL),
    "poucas_avaliacoes_1_4_singular": _m("vi su ficha de Google, que todavía tiene solo {n} {reseñas_palavra}.", _C_AVAL_1, _CTA_AVAL),
    "lentidao": _m("abrí su web y estuve unos {s} segundos esperando.", _C_LENT, "¿se lo envío?"),
    "lentidao_sem_numero": _m("abrí su web desde el móvil y estuve bastante rato esperando.", _C_LENT, "¿se lo envío?"),
    "sem_site": _m("vi su ficha de Google, un {nota} con {n} reseñas, enhorabuena.", _C_SITE, "¿Le llegan más por Google?"),
    "sem_site_sem_reputacao": _m("vi su ficha de Google y no tiene web propia.", _C_SITE, "¿Le llegan más por Google?"),
    "portal": _m("vi su ficha de Google, un {nota} con {n} reseñas, y el enlace lleva a {portal}.", None, "¿Les llegan muchos por {portal}?"),
    "portal_sem_reputacao": _m("vi su ficha de Google y el enlace lleva a {portal}.", None, "¿Les llegan muchos por {portal}?"),
    "rede_social": _m("vi su ficha de Google, un {nota} con {n} reseñas, y el enlace lleva a {rede}.", _C_REDE, "¿Les escriben por {rede}?"),
    "rede_social_sem_reputacao": _m("vi su ficha de Google y el enlace lleva a {rede}.", _C_REDE, "¿Les escriben por {rede}?"),
    "construtor": _m("vi su ficha de Google, un {nota} con {n} reseñas, y su web está en una dirección de {constructor}, sin dominio propio.", _C_CONS, "¿La montaron ustedes mismos?"),
    "construtor_sem_reputacao": _m("vi su ficha de Google y su web está en una dirección de {constructor}, sin dominio propio.", _C_CONS, "¿La montaron ustedes mismos?"),
    "nomes_portal": {"doctoralia.es": "Doctoralia", "topdoctors.es": "Top Doctors"},
    "nomes_rede": {"instagram.com": "Instagram", "facebook.com": "Facebook", "tiktok.com": "TikTok"},
    "nomes_construtor": {"wordpress.com": "WordPress", "wixsite.com": "Wix"},
}


def _lead(
    place_id="p1", nicho="Fisioterapia", telefone_na_pagina=None, nota_estado=None, nota_valor=None,
    avaliacoes_estado=None, avaliacoes_valor=None, lcp_ms=None, psi_estado="CONFIRMADO_PRESENTE", rodadas=1,
):
    return LeadQualificado({
        "place_id": place_id,
        "identidade": {"nome": "Clínica Ejemplo", "nicho": nicho, "cidade": None, "endereco": None, "google_maps_url": None},
        "contato": {"whatsapp_apto": True},
        "analise_tecnica_site": (
            {"status": "ok", "error_type": None, "avaliado_em": None,
             "telefone_na_pagina": {"valor": telefone_na_pagina, "estado": "CONFIRMADO_PRESENTE" if telefone_na_pagina else "NAO_VERIFICADO"}}
        ),
        "reputacao": {
            "nota_google": {"valor": nota_valor, "estado": nota_estado or "NAO_VERIFICADO"},
            "review_count": {"valor": avaliacoes_valor, "estado": avaliacoes_estado or "NAO_VERIFICADO"},
        },
        "problema_vendavel": [],
        "psi": (
            {"estado": psi_estado, "lcp_ms": lcp_ms, "motivo": None, "medido_em": None, "rodadas": rodadas}
            if lcp_ms is not None or psi_estado != "CONFIRMADO_PRESENTE" else None
        ),
    })


# --- ângulo "contato" --------------------------------------------------------


def test_angulo_contato_quando_telefone_na_pagina_e_texto():
    lead = _lead(telefone_na_pagina="texto")
    assert am.escolher_angulo_nata(lead, [lead], _REGRAS) == "contato"


def test_angulo_nao_e_contato_quando_telefone_e_link():
    """Controle negativo: link clicável não é o defeito -- só texto puro."""
    lead = _lead(telefone_na_pagina="link")
    assert am.escolher_angulo_nata(lead, [lead], _REGRAS) != "contato"


def test_angulo_contato_tem_prioridade_sobre_poucas_avaliacoes_e_lentidao():
    lead = _lead(telefone_na_pagina="texto", nota_estado="CONFIRMADO_PRESENTE", nota_valor=4.8,
                 avaliacoes_estado="CONFIRMADO_PRESENTE", avaliacoes_valor=10, lcp_ms=15000)
    assert am.escolher_angulo_nata(lead, [lead], _REGRAS) == "contato"


# --- ângulo "poucas_avaliacoes" ----------------------------------------------


def _lead_e_concorrente(avaliacoes_proprias, avaliacoes_concorrente, nicho="Fisioterapia", nicho_concorrente="Fisioterapia", nota_propria=4.8):
    lead = _lead(place_id="p1", nicho=nicho, nota_estado="CONFIRMADO_PRESENTE", nota_valor=nota_propria,
                 avaliacoes_estado="CONFIRMADO_PRESENTE", avaliacoes_valor=avaliacoes_proprias)
    concorrente = _lead(place_id="p2", nicho=nicho_concorrente, nota_estado="CONFIRMADO_PRESENTE", nota_valor=4.0,
                        avaliacoes_estado="CONFIRMADO_PRESENTE", avaliacoes_valor=avaliacoes_concorrente)
    return lead, concorrente


def test_angulo_poucas_avaliacoes_quando_nota_boa_poucas_avaliacoes_e_concorrente_10x():
    lead, concorrente = _lead_e_concorrente(avaliacoes_proprias=10, avaliacoes_concorrente=100)
    assert am.escolher_angulo_nata(lead, [lead, concorrente], _REGRAS) == "poucas_avaliacoes"


def test_angulo_nao_e_poucas_avaliacoes_sem_concorrente_10x():
    """Controle negativo central: concorrente existe, mas só bate 9x, não
    o novo corte de 10x."""
    lead, concorrente = _lead_e_concorrente(avaliacoes_proprias=10, avaliacoes_concorrente=90)
    assert am.escolher_angulo_nata(lead, [lead, concorrente], _REGRAS) != "poucas_avaliacoes"


def test_angulo_poucas_avaliacoes_concorrente_exatamente_9x_nao_qualifica_mas_10x_sim():
    """Prova direta do corte 10x (era 5x): 9x não qualifica, 10x exato
    qualifica."""
    lead9, c9 = _lead_e_concorrente(avaliacoes_proprias=10, avaliacoes_concorrente=89)
    assert am.escolher_angulo_nata(lead9, [lead9, c9], _REGRAS) != "poucas_avaliacoes"
    lead10, c10 = _lead_e_concorrente(avaliacoes_proprias=10, avaliacoes_concorrente=100)
    assert am.escolher_angulo_nata(lead10, [lead10, c10], _REGRAS) == "poucas_avaliacoes"


def test_angulo_poucas_avaliacoes_nota_4_0_exata_qualifica():
    """Prova direta do corte de nota (era 4,5, agora 4,0): exatamente 4,0
    qualifica."""
    lead, concorrente = _lead_e_concorrente(avaliacoes_proprias=10, avaliacoes_concorrente=100, nota_propria=4.0)
    assert am.escolher_angulo_nata(lead, [lead, concorrente], _REGRAS) == "poucas_avaliacoes"


def test_angulo_nao_e_poucas_avaliacoes_quando_nota_abaixo_de_4_0():
    """Prova direta do corte de nota: 3,9 NUNCA qualifica, mesmo com
    concorrente 10x."""
    lead, concorrente = _lead_e_concorrente(avaliacoes_proprias=10, avaliacoes_concorrente=200, nota_propria=3.9)
    assert am.escolher_angulo_nata(lead, [lead, concorrente], _REGRAS) != "poucas_avaliacoes"


def test_angulo_nao_e_poucas_avaliacoes_quando_avaliacoes_acima_do_maximo():
    lead = _lead(nota_estado="CONFIRMADO_PRESENTE", nota_valor=4.8, avaliacoes_estado="CONFIRMADO_PRESENTE", avaliacoes_valor=31)
    concorrente = _lead(place_id="p2", nota_estado="CONFIRMADO_PRESENTE", nota_valor=4.0, avaliacoes_estado="CONFIRMADO_PRESENTE", avaliacoes_valor=400)
    assert am.escolher_angulo_nata(lead, [lead, concorrente], _REGRAS) != "poucas_avaliacoes"


def test_angulo_nao_e_poucas_avaliacoes_com_zero_avaliacoes():
    """Controle negativo: 0 avaliações fica fora da faixa 1-30 -- o texto
    "todavía tiene solo 0 reseñas" não faz sentido."""
    lead = _lead(nota_estado="CONFIRMADO_PRESENTE", nota_valor=4.8, avaliacoes_estado="CONFIRMADO_PRESENTE", avaliacoes_valor=0)
    concorrente = _lead(place_id="p2", nota_estado="CONFIRMADO_PRESENTE", nota_valor=4.0, avaliacoes_estado="CONFIRMADO_PRESENTE", avaliacoes_valor=400)
    assert am.escolher_angulo_nata(lead, [lead, concorrente], _REGRAS) != "poucas_avaliacoes"


def test_angulo_nao_e_poucas_avaliacoes_concorrente_de_outro_nicho_nao_qualifica():
    lead, concorrente = _lead_e_concorrente(avaliacoes_proprias=10, avaliacoes_concorrente=200, nicho_concorrente="Odontología")
    assert am.escolher_angulo_nata(lead, [lead, concorrente], _REGRAS) != "poucas_avaliacoes"


def test_angulo_nao_e_poucas_avaliacoes_sem_nota_ou_avaliacoes_confirmadas():
    lead = _lead(nota_estado="NAO_VERIFICADO", avaliacoes_estado="CONFIRMADO_PRESENTE", avaliacoes_valor=10)
    concorrente = _lead(place_id="p2", nota_estado="CONFIRMADO_PRESENTE", nota_valor=4.0, avaliacoes_estado="CONFIRMADO_PRESENTE", avaliacoes_valor=200)
    assert am.escolher_angulo_nata(lead, [lead, concorrente], _REGRAS) != "poucas_avaliacoes"


def test_arredondar_para_baixo_estrito_dezena():
    assert am._arredondar_para_baixo_estrito(47) == 40


def test_arredondar_para_baixo_estrito_multiplo_exato_desce_mais_um_passo():
    assert am._arredondar_para_baixo_estrito(40) == 30


def test_arredondar_para_baixo_estrito_centena():
    assert am._arredondar_para_baixo_estrito(347) == 300


def test_montar_mensagem_poucas_avaliacoes_5_30_cita_a_nota():
    lead = _lead(place_id="p1", nota_estado="CONFIRMADO_PRESENTE", nota_valor=4.8, avaliacoes_estado="CONFIRMADO_PRESENTE", avaliacoes_valor=10)
    c1 = _lead(place_id="p2", nota_estado="CONFIRMADO_PRESENTE", nota_valor=4.0, avaliacoes_estado="CONFIRMADO_PRESENTE", avaliacoes_valor=110)
    c2 = _lead(place_id="p3", nota_estado="CONFIRMADO_PRESENTE", nota_valor=4.0, avaliacoes_estado="CONFIRMADO_PRESENTE", avaliacoes_valor=150)
    mensagem, entrada = am.montar_mensagem_nata(
        "poucas_avaliacoes", lead, [lead, c1, c2], apresentacao="", regras=_REGRAS, mensagens=_MENSAGENS,
    )
    assert "4,8" in mensagem
    assert "otras" in mensagem
    # décima rodada (27/09/2026): o concorrente escolhe o ângulo, mas a
    # mensagem não cita mais o número dele nem categoria/cidade
    assert "n_concorrente" not in entrada
    assert "100" not in mensagem and "150" not in mensagem


def test_montar_mensagem_poucas_avaliacoes_1_4_nao_cita_a_nota():
    lead, concorrente = _lead_e_concorrente(avaliacoes_proprias=3, avaliacoes_concorrente=100)
    mensagem, entrada = am.montar_mensagem_nata(
        "poucas_avaliacoes", lead, [lead, concorrente], apresentacao="", regras=_REGRAS, mensagens=_MENSAGENS,
    )
    assert "4,8" not in mensagem
    assert "todavía tiene solo 3 reseñas" in mensagem
    assert "nota_google" in entrada  # entrada ainda carrega a nota para o cruzamento -- só a MENSAGEM não cita


def test_montar_mensagem_poucas_avaliacoes_1_4_com_uma_avaliacao_usa_singular_resenha():
    lead, concorrente = _lead_e_concorrente(avaliacoes_proprias=1, avaliacoes_concorrente=100)
    mensagem, _ = am.montar_mensagem_nata(
        "poucas_avaliacoes", lead, [lead, concorrente], apresentacao="", regras=_REGRAS, mensagens=_MENSAGENS,
    )
    assert "todavía tiene solo 1 reseña" in mensagem
    assert "1 reseñas" not in mensagem


def test_montar_mensagem_poucas_avaliacoes_singular_com_um_concorrente():
    lead, concorrente = _lead_e_concorrente(avaliacoes_proprias=10, avaliacoes_concorrente=105)
    mensagem, entrada = am.montar_mensagem_nata(
        "poucas_avaliacoes", lead, [lead, concorrente], apresentacao="", regras=_REGRAS, mensagens=_MENSAGENS,
    )
    assert "con otra que tiene" in mensagem
    assert "con otras que tienen" not in mensagem
    assert "n_concorrente" not in entrada


# --- ângulo "lentidao" -------------------------------------------------------


def test_angulo_lentidao_quando_lcp_acima_do_minimo():
    lead = _lead(lcp_ms=12000)
    assert am.escolher_angulo_nata(lead, [lead], _REGRAS) == "lentidao"


def test_angulo_nao_e_lentidao_quando_lcp_abaixo_do_minimo():
    lead = _lead(lcp_ms=9000)
    assert am.escolher_angulo_nata(lead, [lead], _REGRAS) != "lentidao"


def test_angulo_nao_e_lentidao_sem_psi_confirmado():
    lead = _lead(psi_estado="NAO_VERIFICADO")
    assert am.escolher_angulo_nata(lead, [lead], _REGRAS) == am.SEM_ANGULO


def test_montar_mensagem_lentidao_com_2_rodadas_cita_o_numero():
    lead = _lead(lcp_ms=12400, rodadas=2)
    mensagem, entrada = am.montar_mensagem_nata(
        "lentidao", lead, [lead], apresentacao="", regras=_REGRAS, mensagens=_MENSAGENS,
    )
    assert "12 segundos" in mensagem
    assert entrada["segundos"] == 12


def test_montar_mensagem_lentidao_com_1_rodada_nao_cita_numero():
    """Prova central da regra nova: só 1 rodada medida -- o ângulo continua
    lentidao, mas sem número nenhum na mensagem."""
    lead = _lead(lcp_ms=12400, rodadas=1)
    mensagem, entrada = am.montar_mensagem_nata(
        "lentidao", lead, [lead], apresentacao="", regras=_REGRAS, mensagens=_MENSAGENS,
    )
    assert "12" not in mensagem
    assert "segundos" not in mensagem
    assert "bastante rato" in mensagem
    assert entrada == {}


def test_montar_mensagem_lentidao_angulo_nao_muda_so_o_numero_some():
    """O ângulo em si (LCP >= 10s) não muda -- só a citação do número."""
    lead_1_rodada = _lead(lcp_ms=12000, rodadas=1)
    lead_2_rodadas = _lead(lcp_ms=12000, rodadas=2)
    assert am.escolher_angulo_nata(lead_1_rodada, [lead_1_rodada], _REGRAS) == "lentidao"
    assert am.escolher_angulo_nata(lead_2_rodadas, [lead_2_rodadas], _REGRAS) == "lentidao"


# --- sem ângulo ---------------------------------------------------------------


def test_angulo_sem_angulo_quando_nenhuma_regra_bate():
    lead = _lead()
    assert am.escolher_angulo_nata(lead, [lead], _REGRAS) == am.SEM_ANGULO


# --- apresentação --------------------------------------------------------------


def test_apresentacao_vazia_nao_deixa_espaco_estranho():
    mensagem, _ = am.montar_mensagem_nata("contato", _lead(), [_lead()], apresentacao="", regras=_REGRAS, mensagens=_MENSAGENS)
    assert mensagem.startswith("Hola, buenas. Entré ")


def test_apresentacao_preenchida_ganha_espaco_e_ponto():
    mensagem, _ = am.montar_mensagem_nata(
        "contato", _lead(), [_lead()], apresentacao="Soy Douglas", regras=_REGRAS, mensagens=_MENSAGENS,
    )
    assert mensagem.startswith("Hola, buenas. Soy Douglas. Entré ")


def test_apresentacao_ja_pontuada_nao_ganha_ponto_duplo():
    mensagem, _ = am.montar_mensagem_nata(
        "contato", _lead(), [_lead()], apresentacao="Soy Douglas.", regras=_REGRAS, mensagens=_MENSAGENS,
    )
    assert " Soy Douglas. Entré " in mensagem
    assert "Douglas.." not in mensagem


# --- pista Direta -------------------------------------------------------------


def test_angulo_direta_sem_site():
    assert am.escolher_angulo_direta({"classe_site": "sem_site", "site": ""}) == "sem_site"


def test_angulo_direta_portal_por_classe_site():
    """Prova central: 'portal' é escolhido pela classe_site do QUALIFICADOR,
    não pelo domínio -- o lead do Top Doctors que ficava sem_angulo (domínio
    não batia com a regex antiga de doctoralia) agora tem mensagem."""
    assert am.escolher_angulo_direta({"classe_site": "portal", "site": "https://www.topdoctors.es/x"}) == "portal"
    assert am.escolher_angulo_direta({"classe_site": "portal", "site": "https://www.doctoralia.es/x"}) == "portal"


def test_angulo_direta_rede_social():
    assert am.escolher_angulo_direta({"classe_site": "rede_social", "site": "https://instagram.com/x"}) == "rede_social"


def test_angulo_direta_construtor():
    assert am.escolher_angulo_direta({"classe_site": "construtor", "site": "https://x.negocio.site"}) == "construtor"


def test_angulo_direta_superficie_google_reusa_sem_site():
    """superficie_google (página gratuita do Google) reusa o modelo de
    sem_site -- não é um ângulo à parte."""
    assert am.escolher_angulo_direta({"classe_site": "superficie_google", "site": ""}) == "sem_site"


def test_angulo_direta_classe_proprio_fica_sem_angulo():
    """Controle negativo central: com as 5 classes de "sem site próprio"
    (sem_site, superficie_google, portal, rede_social, construtor) todas
    cobertas, só "proprio" (que normalmente nem chega à pista Direta) fica
    sem_angulo neste MVP."""
    assert am.escolher_angulo_direta({"classe_site": "proprio", "site": "https://clinica.es"}) == am.SEM_ANGULO


def test_montar_mensagem_direta_sem_site_com_nota_e_avaliacoes():
    mensagem, entrada = am.montar_mensagem_direta(
        "sem_site", {"nota": "4.9", "avaliacoes": "12"}, apresentacao="", mensagens=_MENSAGENS,
    )
    assert "4,9" in mensagem
    assert entrada["avaliacoes_google"] == 12


# --- variantes "sem reputação" (decisão do diretor, 25/09/2026, sétima --
# rodada: na planilha real, leads do ângulo portal sem nota/avaliações
# confirmadas ficavam sem mensagem, Aviso "nota/avaliações não confirmada").


def test_montar_mensagem_sem_site_sem_nota_confirmada_usa_variante_sem_reputacao():
    """Controle central: sem nota/avaliações no CSV, a mensagem NÃO fica
    vazia -- usa a variante sem reputação, nunca inventa o número."""
    mensagem, entrada = am.montar_mensagem_direta(
        "sem_site", {"nota": "", "avaliacoes": ""}, apresentacao="", mensagens=_MENSAGENS,
    )
    assert mensagem != ""
    assert "reseñas" not in mensagem
    assert entrada == {}


def test_montar_mensagem_sem_site_com_reputacao_confirmada_usa_o_modelo_normal():
    """Controle positivo: com nota/avaliações confirmadas, continua o
    modelo COM reputação (não a variante)."""
    mensagem, entrada = am.montar_mensagem_direta(
        "sem_site", {"nota": "4.8", "avaliacoes": "12"}, apresentacao="", mensagens=_MENSAGENS,
    )
    assert "4,8" in mensagem
    assert entrada["avaliacoes_google"] == 12


def test_montar_mensagem_sem_site_com_zero_avaliacoes_usa_variante_sem_reputacao():
    """Prova central: 0 avaliações também cai na variante -- "0 reseñas"
    não é o texto certo."""
    mensagem, entrada = am.montar_mensagem_direta(
        "sem_site", {"nota": "4.8", "avaliacoes": "0"}, apresentacao="", mensagens=_MENSAGENS,
    )
    assert "reseñas" not in mensagem
    assert entrada == {}


def test_montar_mensagem_portal_sem_reputacao_ainda_cita_o_portal():
    mensagem, entrada = am.montar_mensagem_direta(
        "portal", {"nota": "", "avaliacoes": "", "site": "https://www.doctoralia.es/x"},
        apresentacao="", mensagens=_MENSAGENS,
    )
    assert "Doctoralia" in mensagem
    assert "reseñas" not in mensagem
    assert entrada == {}


def test_montar_mensagem_portal_com_zero_avaliacoes_usa_variante_sem_reputacao():
    mensagem, entrada = am.montar_mensagem_direta(
        "portal", {"nota": "4.5", "avaliacoes": "0", "site": "https://www.doctoralia.es/x"},
        apresentacao="", mensagens=_MENSAGENS,
    )
    assert "reseñas" not in mensagem
    assert entrada == {}


def test_montar_mensagem_portal_com_reputacao_confirmada_usa_o_modelo_normal():
    mensagem, entrada = am.montar_mensagem_direta(
        "portal", {"nota": "4.5", "avaliacoes": "8", "site": "https://www.doctoralia.es/x"},
        apresentacao="", mensagens=_MENSAGENS,
    )
    assert "4,5" in mensagem
    assert entrada["avaliacoes_google"] == 8


def test_montar_mensagem_direta_portal_resolve_nome_conhecido():
    mensagem, entrada = am.montar_mensagem_direta(
        "portal", {"nota": "4.5", "avaliacoes": "8", "site": "https://www.doctoralia.es/x"},
        apresentacao="", mensagens=_MENSAGENS,
    )
    assert "Doctoralia" in mensagem
    assert "4,5" in mensagem
    assert entrada["avaliacoes_google"] == 8


def test_montar_mensagem_direta_portal_topdoctors():
    mensagem, _ = am.montar_mensagem_direta(
        "portal", {"nota": "4.5", "avaliacoes": "8", "site": "https://www.topdoctors.es/x"},
        apresentacao="", mensagens=_MENSAGENS,
    )
    assert "Top Doctors" in mensagem


def test_montar_mensagem_direta_portal_desconhecido_usa_dominio_cru():
    mensagem, _ = am.montar_mensagem_direta(
        "portal", {"nota": "4.5", "avaliacoes": "8", "site": "https://www.miportal.es/x"},
        apresentacao="", mensagens=_MENSAGENS,
    )
    assert "miportal.es" in mensagem
    assert "www." not in mensagem


# --- rede_social / construtor (decisão do diretor, 25/09/2026, go-live) -----
#
# Casos reais: "Laura Ficticia Ejemplo | Psicóloga en Alicante" (instagram) e
# "Gabinete de Psicología Ficticio" (psicologaficticia.wordpress.com).


def test_montar_mensagem_rede_social_com_reputacao_cita_nota_e_rede():
    mensagem, entrada = am.montar_mensagem_direta(
        "rede_social", {"nota": "4.9", "avaliacoes": "15", "site": "https://www.instagram.com/x"},
        apresentacao="", mensagens=_MENSAGENS,
    )
    assert "4,9" in mensagem
    assert "Instagram" in mensagem
    assert entrada["avaliacoes_google"] == 15


def test_montar_mensagem_rede_social_sem_reputacao_nao_cita_nota():
    mensagem, entrada = am.montar_mensagem_direta(
        "rede_social", {"nota": "", "avaliacoes": "", "site": "https://www.instagram.com/x"},
        apresentacao="", mensagens=_MENSAGENS,
    )
    assert "reseñas" not in mensagem
    assert "Instagram" in mensagem
    assert entrada == {}


def test_montar_mensagem_rede_social_com_zero_avaliacoes_usa_variante_sem_reputacao():
    mensagem, entrada = am.montar_mensagem_direta(
        "rede_social", {"nota": "4.9", "avaliacoes": "0", "site": "https://www.instagram.com/x"},
        apresentacao="", mensagens=_MENSAGENS,
    )
    assert "reseñas" not in mensagem
    assert entrada == {}


def test_montar_mensagem_rede_social_dominio_desconhecido_usa_dominio_cru():
    mensagem, _ = am.montar_mensagem_direta(
        "rede_social", {"nota": "", "avaliacoes": "", "site": "https://www.minhaRede.com/x"},
        apresentacao="", mensagens=_MENSAGENS,
    )
    assert "minharede.com" in mensagem.lower()


def test_montar_mensagem_construtor_com_reputacao_cita_nota_e_nome_do_construtor():
    """Caso real, 25/09/2026: "Gabinete de Psicología Ficticio"
    (psicologaficticia.wordpress.com) -- domínio conhecido (`nomes_construtor`)
    vira o nome legível, não o host cru."""
    mensagem, entrada = am.montar_mensagem_direta(
        "construtor", {"nota": "4.5", "avaliacoes": "8", "site": "https://psicologaficticia.wordpress.com"},
        apresentacao="", mensagens=_MENSAGENS,
    )
    assert "4,5" in mensagem
    assert "WordPress" in mensagem
    assert "psicologaficticia" not in mensagem
    assert entrada["constructor"] == "WordPress"
    assert entrada["avaliacoes_google"] == 8


def test_montar_mensagem_construtor_sem_reputacao_nao_cita_nota_mas_cita_construtor():
    mensagem, entrada = am.montar_mensagem_direta(
        "construtor", {"nota": "", "avaliacoes": "", "site": "https://psicologaficticia.wordpress.com"},
        apresentacao="", mensagens=_MENSAGENS,
    )
    assert "reseñas" not in mensagem
    assert "WordPress" in mensagem
    assert entrada == {"constructor": "WordPress"}


def test_montar_mensagem_construtor_com_zero_avaliacoes_usa_variante_sem_reputacao():
    mensagem, entrada = am.montar_mensagem_direta(
        "construtor", {"nota": "4.5", "avaliacoes": "0", "site": "https://site247.negocio.site"},
        apresentacao="", mensagens=_MENSAGENS,
    )
    assert "reseñas" not in mensagem
    assert entrada == {"constructor": "site247.negocio.site"}


def test_montar_mensagem_construtor_dominio_desconhecido_usa_dominio_cru():
    """Controle negativo do mapeamento: domínio fora de `nomes_construtor`
    usa o próprio host, sem "https://" nem "www." (a checagem de URL, regra
    4, não pode rejeitar o texto -- {constructor} nunca carrega nenhum dos
    dois)."""
    mensagem, _ = am.montar_mensagem_direta(
        "construtor", {"nota": "4.5", "avaliacoes": "8", "site": "https://www.site247.negocio.site"},
        apresentacao="", mensagens=_MENSAGENS,
    )
    assert "https://" not in mensagem
    assert "www." not in mensagem
    assert "site247.negocio.site" in mensagem


def test_validar_mensagem_angulo_construtor_numero_do_dominio_passa():
    """Prova central: dígitos que vêm do domínio (ex.: "site247") contam
    como fato da entrada -- a checagem de "número fora da entrada" (regra
    7) não pode rejeitar o próprio domínio citado."""
    mensagem, entrada = am.montar_mensagem_direta(
        "construtor", {"nota": "4.5", "avaliacoes": "8", "site": "https://site247.negocio.site"},
        apresentacao="", mensagens=_MENSAGENS,
    )
    resultado = am.validar_mensagem_angulo(mensagem, "construtor", entrada, config_validacao=_CONFIG_VALIDACAO)
    assert resultado.valido, resultado.motivos


# --- verificação (reuso de validador_mensagem.py) ---------------------------


_CONFIG_VALIDACAO = {
    "max_palavras_mensagem_1": 80,
    "simbolos_moeda": ["€"],
    "palavras_preco": ["precio", "tarifa"],
    "marcas_informais_es": ["tú", "tu", "te", "tienes", "puedes"],
    "saudacao_fixa": "Hola, buenas",
    "termos_proibidos": [
        "está perdiendo", "pierde pacientes", "perder pacientes", "se van a la competencia", "se van a otra",
        "todas las reseñas son de 5 estrellas", "casi todas",
    ],
}


def test_validar_mensagem_angulo_passa_para_mensagem_valida():
    mensagem, entrada = am.montar_mensagem_nata(
        "lentidao", _lead(lcp_ms=12000, rodadas=2), [_lead(lcp_ms=12000, rodadas=2)],
        apresentacao="", regras=_REGRAS, mensagens=_MENSAGENS,
    )
    resultado = am.validar_mensagem_angulo(mensagem, "lentidao", entrada, config_validacao=_CONFIG_VALIDACAO)
    assert resultado.valido, resultado.motivos


def test_validar_mensagem_angulo_pega_frase_de_consequencia_proibida():
    mensagem = "Hola, buenas. Si no actúa, sus pacientes se van a otra clínica. ¿le interesa?"
    resultado = am.validar_mensagem_angulo(mensagem, "lentidao", {}, config_validacao=_CONFIG_VALIDACAO)
    assert not resultado.valido
    assert any("termo proibido" in m for m in resultado.motivos)


def test_validar_mensagem_angulo_pega_todas_las_resenas_son_de_5_estrellas():
    mensagem = "Hola, buenas. Parece que todas las reseñas son de 5 estrellas. ¿le interesa?"
    resultado = am.validar_mensagem_angulo(mensagem, "poucas_avaliacoes", {}, config_validacao=_CONFIG_VALIDACAO)
    assert not resultado.valido
    assert any("termo proibido" in m for m in resultado.motivos)


def test_validar_mensagem_angulo_pega_casi_todas():
    mensagem = "Hola, buenas. Casi todas sus reseñas son positivas. ¿le interesa?"
    resultado = am.validar_mensagem_angulo(mensagem, "poucas_avaliacoes", {}, config_validacao=_CONFIG_VALIDACAO)
    assert not resultado.valido
    assert any("termo proibido" in m for m in resultado.motivos)


def test_validar_mensagem_angulo_plataforma_compartida_passa():
    """Confirmação pedida pela supervisão: a frase "plataforma compartida
    con otros profesionales" não é bloqueada -- é texto do modelo, não
    número nem consequência proibida."""
    mensagem, entrada = am.montar_mensagem_direta(
        "portal", {"nota": "4.8", "avaliacoes": "20", "site": "https://doctoralia.es/x"},
        apresentacao="", mensagens=_MENSAGENS,
    )
    mensagem_completa = mensagem.replace(
        "¿Le enseño cómo sería una web solo suya?",
        "Es decir, quien le busca termina en una plataforma compartida con otros profesionales. ¿Le enseño cómo sería una web solo suya?",
    )
    resultado = am.validar_mensagem_angulo(mensagem_completa, "portal", entrada, config_validacao=_CONFIG_VALIDACAO)
    assert resultado.valido, resultado.motivos


def test_validar_mensagem_angulo_rejeita_nome_do_negocio():
    resultado = am.validar_mensagem_angulo(
        "Hola, buenas. Vi Clínica Ejemplo en Google. ¿le interesa?", "contato", {},
        nome_negocio="Clínica Ejemplo", config_validacao=_CONFIG_VALIDACAO,
    )
    assert not resultado.valido
    assert any("nome do negócio" in m for m in resultado.motivos)


# --- palavras_genericas_nome (falso positivo, decisão do diretor, --------
# 25/09/2026): "Psicólogo en Alicante - Pedro Ficticio" -- nome limpo é só
# nicho + cidade da busca + conectoras, e o modelo de poucas_avaliacoes
# legitimamente cita "quien busca psicólogo en Alicante".


def test_palavras_genericas_nome_junta_frases_e_ignora_vazias():
    assert am.palavras_genericas_nome("Fisioterapia", None, "", "Alicante") == ["Fisioterapia", "Alicante"]


def test_validar_mensagem_angulo_com_palavras_genericas_nao_rejeita_nicho_e_cidade():
    resultado = am.validar_mensagem_angulo(
        "Hola, buenas. Quien busca psicólogo en Alicante compara antes. ¿le interesa?", "poucas_avaliacoes", {},
        nome_negocio="Psicólogo en Alicante - Pedro Ficticio",
        palavras_genericas_nome=am.palavras_genericas_nome("Psicólogo", "Alicante"),
        config_validacao=_CONFIG_VALIDACAO,
    )
    assert resultado.valido, resultado.motivos


def test_validar_mensagem_angulo_nome_proprio_continua_rejeitando_com_genericas():
    resultado = am.validar_mensagem_angulo(
        "Hola, buenas. Vi Clínica Ficticia Nueve en Google. ¿le interesa?", "poucas_avaliacoes", {},
        nome_negocio="Clínica Ficticia Nueve",
        palavras_genericas_nome=am.palavras_genericas_nome("Fisioterapia", "Alicante"),
        config_validacao=_CONFIG_VALIDACAO,
    )
    assert not resultado.valido
    assert any("nome do negócio" in m for m in resultado.motivos)


# --- config loaders ------------------------------------------------------------


def test_carregar_regras_angulo_le_o_arquivo_real():
    config = am.carregar_regras_angulo()
    assert "poucas_avaliacoes" in config and "lentidao" in config


def test_carregar_mensagens_angulo_le_o_arquivo_real():
    config = am.carregar_mensagens_angulo()
    for chave in am._CHAVES_MENSAGENS_OBRIGATORIAS:
        assert chave in config


def test_carregar_cidade_busca_le_o_arquivo_real():
    assert isinstance(am.carregar_cidade_busca(), str)


def test_carregar_regras_angulo_arquivo_ausente_levanta_erro_claro(tmp_path):
    with pytest.raises(am.ConfigAnguloInvalidaError, match="não encontrada"):
        am.carregar_regras_angulo(tmp_path / "nao-existe.json")


def test_carregar_mensagens_angulo_sem_chaves_exigidas_levanta_erro(tmp_path):
    caminho = tmp_path / "m.json"
    caminho.write_text("{}", encoding="utf-8")
    with pytest.raises(am.ConfigMensagensAnguloInvalidaError):
        am.carregar_mensagens_angulo(caminho)


def test_carregar_cidade_busca_arquivo_ausente_levanta_erro_claro(tmp_path):
    with pytest.raises(am.ConfigCidadeBuscaInvalidaError, match="não encontrada"):
        am.carregar_cidade_busca(tmp_path / "nao-existe.json")
