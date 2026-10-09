"""Bloco de copy, Fase 1 (decisões do diretor, 08/10/2026, duas rodadas):
ordem ATIVA da Nata e-mail de modelo -> contato -> lentidão com número;
`poucas_avaliacoes`, lentidão moderada e lentidão sem número desligadas pela
config (os textos ficam guardados); texto da Direta pelo nicho da campanha;
nenhum termo de saúde em abogados e arquitectos (inclusive nos modelos
neutros); nenhum modelo cita o nome do negócio ("su web", "su ficha"); e a
apresentação "Soy Douglas, diseño webs." logo depois da saudação.

Usa a config REAL de `config/` (é ela que se prova) e leads fictícios. Cada
regra tem um caso que passa e um controle negativo (~/.claude/CLAUDE.md §4) --
para os ângulos desligados, o controle é religar pela config e ver voltar."""

import copy
import re
import unicodedata

import pytest

from contrato_loader import LeadQualificado

import angulo_mensagem as am
import validador_mensagem

_REGRAS = am.carregar_regras_angulo()
_MENSAGENS = am.carregar_mensagens_angulo()
_APRESENTACAO = am.carregar_apresentacao()
_CONFIG_VALIDACAO = validador_mensagem.carregar_config()

_ABERTURA = "Hola, buenas. Soy Douglas, diseño webs. "


def _lead(
    place_id="p1", campanha_nicho="Abogados", nome="Bufete Ficticio Alameda", nicho_google="Abogado",
    email=None, telefone_na_pagina=None, nota=None, avaliacoes=None, lcp_ms=None, rodadas=2, cidade="Murcia",
):
    def ev(valor):
        return {"valor": valor, "estado": "CONFIRMADO_PRESENTE" if valor not in (None, "") else "NAO_VERIFICADO"}

    return LeadQualificado({
        "place_id": place_id,
        "campanha_nicho": ev(campanha_nicho),
        "campanha_cidade": ev(cidade),
        "identidade": {"nome": nome, "nicho": nicho_google, "cidade": None, "endereco": None, "google_maps_url": None},
        "contato": {"whatsapp_apto": True, "email": ev(email)},
        "analise_tecnica_site": {
            "status": "ok", "error_type": None, "avaliado_em": None, "telefone_na_pagina": ev(telefone_na_pagina),
        },
        "reputacao": {"nota_google": ev(nota), "review_count": ev(avaliacoes)},
        "problema_vendavel": [],
        "psi": (
            {"estado": "CONFIRMADO_PRESENTE", "lcp_ms": lcp_ms, "motivo": None, "medido_em": None, "rodadas": rodadas}
            if lcp_ms is not None else None
        ),
    })


def _com_concorrente(lead, campanha_nicho="Abogados"):
    """Lote com um concorrente do mesmo nicho do Google e 10x+ avaliações."""
    concorrente = _lead(place_id="p2", campanha_nicho=campanha_nicho, nota=4.3, avaliacoes=200)
    return [lead, concorrente]


def _escolher(lead, lote=None, regras=None):
    return am.escolher_angulo_nata(lead, lote or [lead], regras or _REGRAS)


def _regras(**religar):
    """Config real com chaves trocadas: `religar={"poucas_avaliacoes": {"ativo": True}}`."""
    regras = copy.deepcopy(_REGRAS)
    for chave, valores in religar.items():
        regras[chave].update(valores)
    return regras


_POUCAS = dict(nota=4.8, avaliacoes=6)


# --- ordem ATIVA da Nata: e-mail de modelo -> contato -> lentidão com número -----------


@pytest.mark.parametrize("sinais,esperado", [
    (dict(email="info@tudominio.com", telefone_na_pagina="texto", lcp_ms=15000, **_POUCAS), "defeito_visivel"),
    (dict(telefone_na_pagina="texto", lcp_ms=15000, **_POUCAS), "contato"),
    (dict(lcp_ms=15000, **_POUCAS), "lentidao"),
    (dict(**_POUCAS), am.SEM_ANGULO),  # poucas avaliações desligada
    (dict(), am.SEM_ANGULO),
])
def test_ordem_ativa_dos_angulos_da_nata(sinais, esperado):
    lead = _lead(**sinais)
    assert _escolher(lead, _com_concorrente(lead)) == esperado


def test_angulos_nata_declara_a_ordem():
    assert am.ANGULOS_NATA[:4] == ("defeito_visivel", "contato", "lentidao", "poucas_avaliacoes")


def test_os_tres_angulos_desligados_vem_desligados_na_config_real():
    assert _REGRAS["poucas_avaliacoes"]["ativo"] is False
    assert _REGRAS["lentidao_moderada"]["ativo"] is False
    assert _REGRAS["lentidao"]["sem_numero_ativo"] is False


@pytest.mark.parametrize("sinais", [
    dict(**_POUCAS),                    # só poucas avaliações
    dict(lcp_ms=7500, rodadas=3),       # só lentidão moderada
    dict(lcp_ms=15000, rodadas=1),      # só lentidão sem número (uma medição)
    dict(lcp_ms=15000, rodadas=1, **_POUCAS),
])
def test_lead_cujo_unico_angulo_esta_desligado_fica_sem_angulo(sinais):
    lead = _lead(**sinais)
    assert _escolher(lead, _com_concorrente(lead)) == am.SEM_ANGULO


def test_lentidao_com_numero_continua_ativa():
    assert _escolher(_lead(lcp_ms=10000, rodadas=2)) == "lentidao"
    assert _escolher(_lead(lcp_ms=9999, rodadas=2)) == am.SEM_ANGULO  # controle: abaixo do corte


def test_religar_a_lentidao_sem_numero_e_so_a_config():
    regras = _regras(lentidao={"sem_numero_ativo": True})
    lead = _lead(lcp_ms=15000, rodadas=1)
    assert _escolher(lead, regras=regras) == "lentidao"
    mensagem, entrada = am.montar_mensagem_nata(
        "lentidao", lead, [lead], apresentacao=_APRESENTACAO, regras=regras, mensagens=_MENSAGENS,
    )
    assert "segundos" not in mensagem and entrada == {}


def test_religar_a_lentidao_moderada_volta_logo_depois_da_lentidao():
    regras = _regras(lentidao_moderada={"ativo": True})
    lead = _lead(lcp_ms=7500, **_POUCAS)
    assert _escolher(lead, _com_concorrente(lead), regras) == "lentidao_moderada"


def test_religar_poucas_avaliacoes_volta_depois_da_lentidao():
    regras = _regras(poucas_avaliacoes={"ativo": True})
    lead = _lead(**_POUCAS)
    assert _escolher(lead, _com_concorrente(lead), regras) == "poucas_avaliacoes"
    lento = _lead(lcp_ms=15000, **_POUCAS)
    assert _escolher(lento, _com_concorrente(lento), regras) == "lentidao"


# --- poucas_avaliacoes religada: fora dos psicólogos -----------------------------------


@pytest.mark.parametrize("campanha_nicho,esperado", [
    ("Abogados", "poucas_avaliacoes"),
    ("Arquitectos", "poucas_avaliacoes"),
    ("Psicólogos", am.SEM_ANGULO),
    ("psicologos", am.SEM_ANGULO),  # sem acento e minúscula: mesmo nicho
    ("Fontaneros", am.SEM_ANGULO),  # nicho não reconhecido também fica de fora
    (None, am.SEM_ANGULO),
])
def test_poucas_avaliacoes_religada_continua_fora_dos_psicologos(campanha_nicho, esperado):
    regras = _regras(poucas_avaliacoes={"ativo": True})
    lead = _lead(campanha_nicho=campanha_nicho, **_POUCAS)
    assert _escolher(lead, _com_concorrente(lead, campanha_nicho or "Abogados"), regras) == esperado


def test_exclusao_dos_psicologos_vem_da_config():
    assert _REGRAS["poucas_avaliacoes"]["nichos_excluidos"] == ["psicologos"]
    regras = _regras(poucas_avaliacoes={"ativo": True, "nichos_excluidos": []})
    lead = _lead(campanha_nicho="Psicólogos", **_POUCAS)
    assert _escolher(lead, _com_concorrente(lead, "Psicólogos"), regras) == "poucas_avaliacoes"


@pytest.mark.parametrize("campanha_nicho,palavra", [("Abogados", "despacho"), ("Arquitectos", "estudio")])
def test_texto_guardado_de_poucas_avaliacoes_usa_a_palavra_do_nicho(campanha_nicho, palavra):
    lead = _lead(campanha_nicho=campanha_nicho, **_POUCAS)
    lote = _com_concorrente(lead, campanha_nicho)
    mensagem, entrada = am.montar_mensagem_nata(
        "poucas_avaliacoes", lead, lote, apresentacao=_APRESENTACAO, regras=_REGRAS, mensagens=_MENSAGENS,
    )
    assert f"sale otro {palavra} con muchas más" in mensagem
    assert am.validar_mensagem_angulo(
        mensagem, "poucas_avaliacoes", entrada, nome_negocio=lead["identidade"]["nome"],
        config_validacao=_CONFIG_VALIDACAO,
    ).valido


# --- texto da Direta pelo nicho da campanha --------------------------------------------


@pytest.mark.parametrize("campanha_nicho,chave,trecho", [
    ("Psicólogos", "sem_site__psicologos", "primera sesión"),
    ("Abogados", "sem_site__abogados", "sus especialidades"),
    ("Arquitectos", "sem_site__arquitectos", "obra realizada"),
    ("ARQUITECTOS", "sem_site__arquitectos", "obra realizada"),
])
def test_direta_escolhe_o_texto_pelo_nicho_da_campanha(campanha_nicho, chave, trecho):
    linha = {"nome": "Estudio Ficticio Norte", "nicho": "Psicólogo", "classe_site": "sem_site", "nota": "4.9",
             "avaliacoes": "23", "campanha_cidade": "Murcia", "campanha_nicho": campanha_nicho}
    mensagem, _ = am.montar_mensagem_direta(
        "sem_site", linha, apresentacao=_APRESENTACAO, mensagens=_MENSAGENS, regras=_REGRAS,
    )
    assert trecho in mensagem
    assert _MENSAGENS[chave]["cta"] in mensagem
    # a categoria do Google ("Psicólogo") NÃO decide o nicho: só o da campanha
    if chave != "sem_site__psicologos":
        assert "primera sesión" not in mensagem


def test_cada_nicho_de_copy_tem_os_dois_modelos_e_o_vocabulario():
    nichos = {k for k in _REGRAS["nichos_copy"] if not k.startswith("_")}
    assert nichos == set(am.NICHOS_COPY)
    for nicho in nichos:
        assert f"sem_site__{nicho}" in _MENSAGENS and f"sem_site_sem_reputacao__{nicho}" in _MENSAGENS
        assert set(_MENSAGENS["vocabulario_nicho"][nicho]) == {"negocio", "negocios"}


def test_direta_fecha_com_o_exemplo_pronto_e_a_nata_com_a_captura():
    for chave in am.MODELOS_SEM_SITE:
        assert _MENSAGENS[chave]["cta"].startswith("¿Le preparo un ejemplo"), chave
    for chave in ("contato", "lentidao", "lentidao_sem_numero", "defeito_visivel"):
        assert _MENSAGENS[chave]["cta"].startswith("¿Le paso una captura"), chave
    textos = " ".join(
        str(_MENSAGENS[c].get(b) or "") for c in am.MODELOS for b in ("fato", "consequencia", "cta")
    ).lower()
    assert "versión renovada" not in textos and "revisión breve" not in textos


# --- sem nome do negócio: "su web" / "su ficha de Google" -------------------------------


@pytest.mark.parametrize("chave", am.MODELOS)
def test_nenhum_modelo_usa_o_nome_do_negocio(chave):
    modelo = _MENSAGENS[chave]
    for bloco in ("fato", "consequencia", "cta"):
        assert "{nombre}" not in (modelo.get(bloco) or ""), (chave, bloco)
    assert not (modelo.get("excecoes_validacao") or {}).get("nome_negocio"), chave


def test_neutros_no_perfeito_composto():
    for chave in ("portal", "portal_sem_reputacao", "rede_social", "rede_social_sem_reputacao",
                  "construtor", "construtor_sem_reputacao"):
        assert _MENSAGENS[chave]["fato"].startswith("he visto su ficha de Google"), chave
        assert not re.search(r"\bvi\b", _MENSAGENS[chave]["fato"]), chave


def test_validador_recusa_o_nome_do_negocio_em_qualquer_modelo():
    """Controle negativo: sem a exceção `nome_negocio`, o nome que vazasse num
    modelo seria recusado -- a regra continua de pé."""
    modelo = dict(_MENSAGENS["sem_site__abogados"], fato="he visto la ficha de Bufete Ficticio Alameda y no tiene web propia.")
    mensagem = am.compor_mensagem(modelo, _MENSAGENS["saudacao"], _APRESENTACAO)
    resultado = am.validar_mensagem_angulo(
        mensagem, "sem_site", {}, nome_negocio="Bufete Ficticio Alameda", config_validacao=_CONFIG_VALIDACAO,
    )
    assert any("nome do negócio" in m for m in resultado.motivos)


@pytest.mark.parametrize("cidade", [None, ""])
def test_lead_sem_cidade_recebe_mensagem_nata_e_direta(cidade):
    """Sem {nombre} em nenhum modelo, a cidade só servia para limpar o nome:
    lead sem `campanha_cidade` deixou de sair REVISAR NOME."""
    lead = _lead(lcp_ms=12000, cidade=cidade)
    mensagem, _ = am.montar_mensagem_nata(
        "lentidao", lead, [lead], apresentacao=_APRESENTACAO, regras=_REGRAS, mensagens=_MENSAGENS,
    )
    assert mensagem.startswith(_ABERTURA)
    linha = {"nome": "Bufete Ficticio Alameda", "classe_site": "sem_site", "nota": "", "avaliacoes": "",
             "campanha_nicho": "Abogados", "campanha_cidade": cidade}
    direta, _ = am.montar_mensagem_direta(
        "sem_site", linha, apresentacao=_APRESENTACAO, mensagens=_MENSAGENS, regras=_REGRAS,
    )
    assert direta.startswith(_ABERTURA)


def test_nome_curto_ainda_pede_revisao_para_modelo_que_use_nombre():
    """Controle: o mecanismo continua no código -- um modelo com {nombre} e lead
    sem cidade ainda sai REVISAR NOME."""
    mensagens = copy.deepcopy(_MENSAGENS)
    mensagens["lentidao"]["fato"] = "he probado la web de {nombre} y tarda unos {segundos} segundos."
    lead = _lead(lcp_ms=12000, cidade=None)
    with pytest.raises(am.LinhaPedeRevisaoError, match="REVISAR NOME"):
        am.montar_mensagem_nata("lentidao", lead, [lead], apresentacao=_APRESENTACAO, regras=_REGRAS,
                                mensagens=mensagens)


# --- nada de saúde em abogados, arquitectos e nos modelos neutros ----------------------


_TERMOS_SAUDE = (
    "paciente", "pacientes", "consulta", "consultas", "cita", "citas", "terapia", "sesión", "sesiones",
    "tratamiento", "tratamientos", "salud", "sanitario", "clínica", "clínicas", "psicólogo", "psicóloga",
    "médico", "doctor",
)


def _normalizar(texto):
    sem = "".join(c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn")
    return sem.lower()


def _termos_de_saude(texto):
    t = _normalizar(texto)
    return [termo for termo in _TERMOS_SAUDE if re.search(rf"\b{re.escape(_normalizar(termo))}\b", t)]


@pytest.mark.parametrize("chave", [c for c in am.MODELOS if not c.endswith("__psicologos")])
def test_nenhum_termo_de_saude_nos_modelos_fora_dos_psicologos(chave):
    """Abogados, arquitectos e todos os modelos que servem a qualquer nicho."""
    modelo = _MENSAGENS[chave]
    texto = " ".join(str(modelo.get(b) or "") for b in ("fato", "consequencia", "cta", "apresentacao"))
    assert _termos_de_saude(texto) == [], chave


@pytest.mark.parametrize("nicho", ["abogados", "arquitectos"])
def test_vocabulario_do_nicho_sem_termos_de_saude(nicho):
    assert _termos_de_saude(" ".join(_MENSAGENS["vocabulario_nicho"][nicho].values())) == []


def test_o_detector_de_termos_de_saude_pega_o_que_deve():
    """Controle negativo do próprio teste: o texto dos psicólogos TEM termos de
    saúde, e "solicita"/"recita" não contam como "cita"."""
    assert "sesión" in _termos_de_saude(_MENSAGENS["sem_site__psicologos"]["consequencia"])
    assert "consulta" in _termos_de_saude(_MENSAGENS["sem_site__psicologos"]["cta"])
    assert _termos_de_saude("Se solicita una recita.") == []


@pytest.mark.parametrize("campanha_nicho", ["Abogados", "Arquitectos"])
def test_mensagens_montadas_de_abogados_e_arquitectos_sem_saude_e_sem_nome(campanha_nicho):
    """As mensagens prontas de cada ângulo ATIVO, montadas da config real."""
    nome = "Estudio Ficticio Norte" if campanha_nicho == "Arquitectos" else "Bufete Ficticio Alameda"
    mensagens = []
    for sinais in (dict(email="info@tudominio.com"), dict(telefone_na_pagina="texto"), dict(lcp_ms=12000)):
        lead = _lead(campanha_nicho=campanha_nicho, nome=nome, **sinais)
        angulo = _escolher(lead)
        assert angulo != am.SEM_ANGULO
        mensagem, _ = am.montar_mensagem_nata(
            angulo, lead, [lead], apresentacao=_APRESENTACAO, regras=_REGRAS, mensagens=_MENSAGENS,
        )
        mensagens.append(mensagem)
    for classe, site in (("sem_site", ""), ("portal", "https://www.doctoralia.es/x"),
                         ("rede_social", "https://instagram.com/x"), ("construtor", "https://x.wixsite.com/y")):
        for nota, avaliacoes in (("4.8", "20"), ("", "")):
            linha = {"nome": nome, "nicho": "x", "classe_site": classe, "site": site, "nota": nota,
                     "avaliacoes": avaliacoes, "campanha_cidade": "Murcia", "campanha_nicho": campanha_nicho}
            mensagem, _ = am.montar_mensagem_direta(
                classe, linha, apresentacao=_APRESENTACAO, mensagens=_MENSAGENS, regras=_REGRAS,
            )
            mensagens.append(mensagem)
    assert len(mensagens) == 11
    for mensagem in mensagens:
        assert _termos_de_saude(mensagem) == [], mensagem
        assert nome.lower() not in mensagem.lower() and "Norte" not in mensagem and "Alameda" not in mensagem


# --- apresentação logo depois da saudação ----------------------------------------------


_VALORES = dict(nota="4,8", n=8, reseñas_palavra="reseñas", s=11, portal="Top Doctors", rede="Instagram",
                constructor="WordPress", segundos=11, texto_encontrado="info@website.com",
                negocio="estudio", negocios="estudios",
                portal_ref="Top Doctors", rede_ref="Instagram", constructor_ref="WordPress")


def test_apresentacao_real_e_a_curta():
    assert _APRESENTACAO == "Soy Douglas, diseño webs."


@pytest.mark.parametrize("chave", [c for c in am.MODELOS if c != "lentidao_moderada"])
def test_apresentacao_vem_logo_depois_da_saudacao_e_antes_da_observacao(chave):
    """"Hola, buenas. Soy Douglas, diseño webs." e só depois a observação.
    `lentidao_moderada` (desligada) mantém a apresentação própria, com o mesmo
    texto -- coberta pelo teste seguinte."""
    modelo = _MENSAGENS[chave]
    assert "apresentacao" not in modelo, chave  # usa a global, uma só
    mensagem = am.compor_mensagem(modelo, _MENSAGENS["saudacao"], _APRESENTACAO, **_VALORES)
    assert mensagem.startswith(_ABERTURA), mensagem
    fato = modelo["fato"].format(**_VALORES)
    assert mensagem[len(_ABERTURA):].lower().startswith(fato.lower()), mensagem
    assert mensagem.count("Soy Douglas") == 1


def test_apresentacao_da_moderada_e_a_mesma_global():
    assert _MENSAGENS["lentidao_moderada"]["apresentacao"] == _APRESENTACAO


def test_compor_mensagem_poe_a_apresentacao_antes_do_fato_controle():
    """Controle negativo: com outra apresentação, a abertura muda -- o teste
    acima olha a posição, não um texto fixo por acaso."""
    modelo = {"fato": "he visto algo.", "consequencia": None, "cta": "¿Sí?"}
    assert am.compor_mensagem(modelo, "Hola, buenas.", "Soy X.") == "Hola, buenas. Soy X. He visto algo. ¿Sí?"
    assert not am.compor_mensagem(modelo, "Hola, buenas.", "").startswith(_ABERTURA)


# --- todos os textos finais passam no validador ----------------------------------------


@pytest.mark.parametrize("chave", am.MODELOS)
def test_texto_final_dentro_do_limite_e_valido(chave):
    mensagem = am.compor_mensagem(_MENSAGENS[chave], _MENSAGENS["saudacao"], _APRESENTACAO, **_VALORES)
    resultado = am.validar_mensagem_angulo(
        mensagem, chave, {"nota_google": "4,8", "avaliacoes_google": 8, "segundos": 11,
                          "texto_encontrado": "info@website.com"},
        nome_negocio="Bufete Ficticio Alameda", config_validacao=_CONFIG_VALIDACAO,
    )
    assert resultado.valido, (mensagem, resultado.motivos)
    assert len(mensagem.split()) <= 80
