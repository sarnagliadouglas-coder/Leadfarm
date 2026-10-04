"""Testes dos novos templates e ângulos (decisão do diretor, 01/10/2026):
`lentidao` e `sem_site` com texto novo, `lentidao_moderada`, `defeito_visivel`
(desligado até aprovar os padrões), `{nombre}`, setor de saúde e as exceções
POR MODELO do validador.

Usa a copy real de `config/` (os textos aprovados são o que se prova) e
leads sintéticos. Cada regra tem um caso que passa e um controle negativo
(~/.claude/CLAUDE.md §4)."""

import copy
import json

import pytest

from contrato_loader import LeadQualificado

import angulo_mensagem as am
import validador_mensagem

_REGRAS = am.carregar_regras_angulo()
_MENSAGENS = am.carregar_mensagens_angulo()
_APRESENTACAO = am.carregar_apresentacao()
_CONFIG_VALIDACAO = validador_mensagem.carregar_config()

_APRES_NOVA = "Soy Douglas, hago webs aquí en Alicante."
_PADRAO_EMAIL = {"tipo": "email", "regex": r"[\w.+-]+@(?:website|example)\.com"}


@pytest.fixture(autouse=True)
def _cidade_fixa(monkeypatch):
    monkeypatch.setattr(am, "carregar_cidade_busca", lambda *a, **k: "Alicante")


def _regras(**over):
    r = copy.deepcopy(_REGRAS)
    r.update(over)
    return r


def _regras_com_defeito(ativo=True, padroes=None):
    return _regras(defeito_visivel={"ativo": ativo, "padroes": [_PADRAO_EMAIL] if padroes is None else padroes})


def _lead(
    place_id="p1", nome="Clínica Dental Sol", nicho="Clínica dental", lcp_ms=None, rodadas=2,
    email=None, telefone_na_pagina=None,
):
    return LeadQualificado({
        "place_id": place_id,
        "identidade": {"nome": nome, "nicho": nicho, "cidade": None, "endereco": None, "google_maps_url": None},
        "contato": {
            "whatsapp_apto": True,
            "email": {"valor": email, "estado": "CONFIRMADO_PRESENTE" if email else "NAO_VERIFICADO"},
        },
        "analise_tecnica_site": {
            "status": "ok", "error_type": None, "avaliado_em": None,
            "telefone_na_pagina": {"valor": telefone_na_pagina, "estado": "CONFIRMADO_PRESENTE" if telefone_na_pagina else "NAO_VERIFICADO"},
        },
        "reputacao": {
            "nota_google": {"valor": None, "estado": "NAO_VERIFICADO"},
            "review_count": {"valor": None, "estado": "NAO_VERIFICADO"},
        },
        "problema_vendavel": [],
        "psi": (
            {"estado": "CONFIRMADO_PRESENTE", "lcp_ms": lcp_ms, "motivo": None, "medido_em": None, "rodadas": rodadas}
            if lcp_ms is not None else None
        ),
    })


def _escolher(lead, regras=None):
    return am.escolher_angulo_nata(lead, [lead], regras or _REGRAS)


def _montar(angulo, lead, regras=None):
    return am.montar_mensagem_nata(
        angulo, lead, [lead], apresentacao=_APRESENTACAO, regras=regras or _REGRAS, mensagens=_MENSAGENS,
    )


def _validar(mensagem, angulo, entrada, nome):
    return am.validar_mensagem_angulo(mensagem, angulo, entrada, nome_negocio=nome, config_validacao=_CONFIG_VALIDACAO)


# --- textos aprovados, palavra por palavra ------------------------------------


def test_lentidao_texto_aprovado():
    lead = _lead(lcp_ms=12400)
    mensagem, entrada = _montar("lentidao", lead)
    assert mensagem == (
        "Hola, buenas. Soy Douglas, hago webs aquí en Alicante. Abrí la web de Clínica Dental Sol desde el móvil "
        "y tardó unos 12 segundos en mostrar el contenido. Mucha gente que busca desde el móvil no espera tanto "
        "y pasa al siguiente resultado de Google. Le he apuntado lo que vi y algunas ideas para mejorarlo. "
        "¿Se lo paso por aquí?"
    )
    assert _validar(mensagem, "lentidao", entrada, lead["identidade"]["nome"]).valido


def test_lentidao_moderada_texto_aprovado():
    lead = _lead(lcp_ms=6400)
    mensagem, entrada = _montar("lentidao_moderada", lead)
    assert mensagem == (
        "Hola, buenas. Soy Douglas, hago webs aquí en Alicante. Abrí la web de Clínica Dental Sol desde el móvil "
        "y tardó unos 6 segundos en cargar. No es grave, pero en el móvil se nota y suele tener arreglo fácil. "
        "Si quiere, le paso lo que vi. ¿Se lo envío?"
    )
    assert _validar(mensagem, "lentidao_moderada", entrada, lead["identidade"]["nome"]).valido


def test_defeito_visivel_texto_aprovado():
    lead = _lead(email="info@website.com")
    regras = _regras_com_defeito()
    mensagem, entrada = _montar("defeito_visivel", lead, regras)
    assert mensagem == (
        'Hola, buenas. Soy Douglas, hago webs aquí en Alicante. Revisando su web vi que aparece el correo '
        '"info@website.com", que parece un texto de la plantilla que quedó sin cambiar. Si un paciente intenta '
        'escribirles ahí, el correo no les llega. Se lo comento por si no lo sabían. Si quiere, le paso un par de '
        'detalles más que vi.'
    )
    assert _validar(mensagem, "defeito_visivel", entrada, lead["identidade"]["nome"]).valido


def _linha_csv(**over):
    base = {"nome": "Clínica Dental Sol", "site": "", "classe_site": "sem_site", "avaliacoes": "120", "nota": "4.8"}
    base.update(over)
    return base


def _montar_direta(linha, regras=None):
    return am.montar_mensagem_direta(
        "sem_site", linha, apresentacao=_APRESENTACAO, mensagens=_MENSAGENS, regras=regras or _REGRAS,
    )


def test_sem_site_texto_aprovado():
    linha = _linha_csv()
    mensagem, entrada = _montar_direta(linha)
    assert mensagem == (
        "Hola, buenas. Soy Douglas, hago webs aquí en Alicante. Vi su ficha en Google: un 4,8 con 120 reseñas, "
        "se nota que sus pacientes están contentos. Pero quien quiere ver tratamientos o cómo funciona la primera "
        "cita antes de llamar no tiene una web a la que ir. Le puedo enseñar un ejemplo de cómo quedaría una "
        "página sencilla para Clínica Dental Sol. ¿Le interesa verlo?"
    )
    assert _validar(mensagem, "sem_site", entrada, linha["nome"]).valido


# --- ângulo: faixas de LCP ------------------------------------------------------


@pytest.mark.parametrize("lcp,esperado", [
    (4999, am.SEM_ANGULO),
    (5000, "lentidao_moderada"),
    (9999, "lentidao_moderada"),
    (10000, "lentidao"),
    (24000, "lentidao"),
])
def test_faixas_de_lcp(lcp, esperado):
    assert _escolher(_lead(lcp_ms=lcp)) == esperado


def test_lentidao_moderada_sem_medicao_consistente_nao_sai():
    """Controle negativo: o texto cita os segundos e não tem variante sem
    número -- com 1 rodada medida o lead continua sem ângulo."""
    assert _escolher(_lead(lcp_ms=7000, rodadas=1)) == am.SEM_ANGULO


def test_lentidao_com_1_rodada_continua_no_texto_sem_numero_antigo():
    """A regra das rodadas não mudou: sem 2 rodadas o ângulo é `lentidao`,
    mas o texto é o `lentidao_sem_numero` (não foi trocado nesta rodada)."""
    lead = _lead(lcp_ms=14000, rodadas=1)
    assert _escolher(lead) == "lentidao"
    mensagem, entrada = _montar("lentidao", lead)
    assert "segundos" not in mensagem and _APRES_NOVA in mensagem  # apresentação unificada (03/10/2026)
    assert entrada == {}


def test_lentidao_moderada_ausente_da_config_nao_escolhe():
    regras = _regras()
    del regras["lentidao_moderada"]
    assert _escolher(_lead(lcp_ms=7000), regras) == am.SEM_ANGULO


# --- ângulo: defeito_visivel ----------------------------------------------------


def test_defeito_visivel_vem_ativo_na_config_real_e_o_desligado_nao_aciona():
    assert _REGRAS["defeito_visivel"]["ativo"] is True
    assert _escolher(_lead(email="info@website.com", lcp_ms=12000)) == "defeito_visivel"
    assert _escolher(_lead(email="info@website.com", lcp_ms=12000), _regras_com_defeito(ativo=False)) == "lentidao"


@pytest.mark.parametrize("email", [
    "info@website.com", "info@example.es", "x@yourdomain.com", "tuemail@gmail.com", "nombre@clinica.es",
    "usuario@dominio.com", "info@tudominio.es",
])
def test_padroes_de_email_aprovados_acionam(email):
    assert _escolher(_lead(email=email)) == "defeito_visivel"


@pytest.mark.parametrize("email", ["info@clinicasol.es", "recepcion@clinicadentalnombre.com", "dr.test@gmail.com"])
def test_email_normal_nao_aciona_nos_padroes_reais(email):
    """Controle negativo na config real."""
    assert _escolher(_lead(email=email)) == am.SEM_ANGULO


def test_defeito_nao_email_so_e_detectado_nunca_vira_mensagem():
    lead = _lead(lcp_ms=12000)
    lead = LeadQualificado({**dict(lead.items()), "analise_tecnica_site": {
        **lead["analise_tecnica_site"], "texto_site": {"texto": "Lorem ipsum dolor sit amet"}}})
    assert am.defeitos_nao_email(lead, _REGRAS) == ["lorem_ipsum: 'Lorem ipsum'"]
    assert _escolher(lead) == "lentidao"  # segue o ângulo normal, sem mensagem de defeito
    assert am.defeitos_nao_email(lead, _regras_com_defeito(ativo=False)) == []


def test_defeito_visivel_ligado_tem_prioridade_sobre_lentidao():
    lead = _lead(email="info@website.com", lcp_ms=12000)
    assert _escolher(lead, _regras_com_defeito()) == "defeito_visivel"
    moderada = _lead(email="info@website.com", lcp_ms=7000)
    assert _escolher(moderada, _regras_com_defeito()) == "defeito_visivel"


def test_defeito_visivel_tem_prioridade_total_ate_sobre_contato():
    lead = _lead(email="info@website.com", telefone_na_pagina="texto")
    assert _escolher(lead, _regras_com_defeito()) == "defeito_visivel"


def test_defeito_visivel_email_normal_nao_aciona():
    assert _escolher(_lead(email="info@clinicasol.es", lcp_ms=12000), _regras_com_defeito()) == "lentidao"


def test_defeito_visivel_ligado_sem_padroes_nao_aciona():
    assert _escolher(_lead(email="info@website.com"), _regras_com_defeito(padroes=[])) == am.SEM_ANGULO


def test_defeito_visivel_padrao_que_nao_e_email_nao_aciona():
    """Só e-mail aciona -- "el correo no les llega" não vale para outros tipos
    de placeholder, que esperam variação de texto aprovada."""
    regras = _regras_com_defeito(padroes=[{"tipo": "telefone", "regex": r"info@website\.com"}])
    assert _escolher(_lead(email="info@website.com"), regras) == am.SEM_ANGULO


# --- exceções do validador valem SÓ para o modelo que as declara -----------------


def test_validador_sem_excecoes_continua_recusando_nome_dos_e_falta_de_pergunta():
    """Controle negativo central: o mesmo texto aprovado, sem as exceções,
    é recusado pelas três checagens -- elas não foram removidas."""
    mensagem, entrada = _montar("defeito_visivel", _lead(email="info@website.com"), _regras_com_defeito())
    texto = json.dumps(
        {"estrategia": "x", "canal_sugerido": "whatsapp", "mensagem_1": str(mensagem), "fato_usado": "x"},
        ensure_ascii=False,
    )
    sem_excecao = validador_mensagem.validar_mensagem(texto, entrada, config=_CONFIG_VALIDACAO)
    assert any("não termina com '?'" in m for m in sem_excecao.motivos)

    lead = _lead(lcp_ms=12400)
    mensagem, entrada = _montar("lentidao", lead)
    texto = json.dumps(
        {"estrategia": "x", "canal_sugerido": "whatsapp", "mensagem_1": str(mensagem), "fato_usado": "x"},
        ensure_ascii=False,
    )
    sem_excecao = validador_mensagem.validar_mensagem(
        texto, entrada, config=_CONFIG_VALIDACAO, nome_negocio=lead["identidade"]["nome"],
    )
    assert any("nome do negócio" in m for m in sem_excecao.motivos)


def test_excecao_numeros_por_extenso_nao_libera_outros_numeros():
    """"dos" fica liberado, "tres" não."""
    texto = json.dumps(
        {"estrategia": "x", "canal_sugerido": "whatsapp", "fato_usado": "x",
         "mensagem_1": "Hola, buenas. Dos cosas y tres más. ¿Sí?"},
        ensure_ascii=False,
    )
    r = validador_mensagem.validar_mensagem(texto, {}, config=_CONFIG_VALIDACAO, excecoes={"numeros_por_extenso": ["dos"]})
    assert r.motivos == ["mensagem_1 cita número fora da entrada: ['3']"]


def test_modelo_sem_excecao_nao_herda_a_dos_novos():
    """O ângulo `rede_social` (não mexido) continua recusado se o nome do
    negócio vazar no texto -- a exceção é do modelo, não do validador."""
    mensagem = am.MensagemComposta("Hola, buenas. Vi la web de Clínica Dental Sol en Instagram. ¿Les escriben?")
    resultado = _validar(mensagem, "rede_social", {}, "Clínica Dental Sol")
    assert any("nome do negócio" in m for m in resultado.motivos)


def test_excecoes_so_dos_modelos_novos_na_config_real():
    com_excecao = {k for k, v in _MENSAGENS.items() if isinstance(v, dict) and v.get("excecoes_validacao")}
    assert com_excecao == {"lentidao", "lentidao_moderada", "defeito_visivel", "sem_site"}


def test_carga_recusa_consequencia_que_afirma_resultado_mesmo_com_excecao():
    mensagens = copy.deepcopy(_MENSAGENS)
    mensagens["lentidao_moderada"]["consequencia"] = "Esa espera hace que los pacientes abandonen la web."
    problemas = am.problemas_de_estrutura(mensagens, _CONFIG_VALIDACAO["afirmacao"])
    assert any(p.startswith("lentidao_moderada.consequencia") for p in problemas)


def test_carga_recusa_cta_sem_pergunta_em_modelo_sem_excecao():
    mensagens = copy.deepcopy(_MENSAGENS)
    mensagens["contato"]["cta"] = "Se lo paso."
    problemas = am.problemas_de_estrutura(mensagens, _CONFIG_VALIDACAO["afirmacao"])
    assert any(p.startswith("contato.cta") for p in problemas)


# --- {nombre} -------------------------------------------------------------------


@pytest.mark.parametrize("nome,esperado", [
    ("Dental Brisa - Clínica Dental en Alicante", "Dental Brisa"),
    ("Clínica Dental Sol", "Clínica Dental Sol"),
    ("Dra. Ana Ficticia - Clínica Odontoficticia Alicante", "Dra. Ana Ficticia"),
    ("Lunaria Alicante", "Lunaria"),
    ("Ferrox alicante", "Ferrox"),
    ("Lunaria - Alicante", "Lunaria"),
    ("Lunaria | ALICANTE", "Lunaria"),
    ("Lunaria en Alicante", "Lunaria"),
    ("Velia Clínica Dental Alicante | Dentista en Alicante", "Velia Clínica Dental"),
])
def test_nome_curto_seguro_limpa(nome, esperado):
    assert am.nome_curto_seguro(nome, _REGRAS) == esperado


@pytest.mark.parametrize("nome,trecho", [
    ("Alicante, España", "cidade da busca"),
    ("Clínica Alicante Centro Dental", "cidade da busca"),
    ("Reformas en Alicante", "genéricas"),
    ("Clínica dental - Alicante", "genéricas"),
    ("ALICANTE", "vazio"),
    ("Clínica Dental Ficticia 🦷 Su Sonrisa", "símbolo"),
    ("Clínica Dental del Doctor Fulano de Tal y Asociados", "longo demais"),
    ("Dentix…", "truncado"),
    ("Dental / Estética", "separador"),
    ("", "vazio"),
])
def test_nome_curto_inseguro_pede_revisao(nome, trecho):
    with pytest.raises(am.LinhaPedeRevisaoError, match=trecho):
        am.nome_curto_seguro(nome, _REGRAS)


def test_nome_inseguro_nao_gera_mensagem_pronta():
    lead = _lead(lcp_ms=12400, nome="Clínica Dental Ficticia 🦷 Su Sonrisa")
    with pytest.raises(am.LinhaPedeRevisaoError, match="REVISAR NOME"):
        _montar("lentidao", lead)


def test_nome_com_digitos_entra_na_entrada_derivada():
    """O validador confere número contra a entrada: um dígito do nome
    ("24") tem que estar nela, ou a mensagem seria recusada."""
    lead = _lead(lcp_ms=12400, nome="Clínica Dental 24")
    mensagem, entrada = _montar("lentidao", lead)
    assert "Clínica Dental 24" in mensagem
    assert _validar(mensagem, "lentidao", entrada, lead["identidade"]["nome"]).valido


# --- setor de saúde -------------------------------------------------------------


@pytest.mark.parametrize("nicho,nome", [
    ("Dentista", "X"), ("Clínica dental", "X"), ("Ortodoncista", "X"), ("", "Nadir Clinic"), ("", "Fisioterapia Sol"),
])
def test_setor_saude_reconhece(nicho, nome):
    assert am.setor_e_saude(nicho, nome, _REGRAS)


@pytest.mark.parametrize("nicho,nome", [
    ("Empresa constructora", "Arcofic"), ("Reformas", "Manitas"), ("Arquitecto", "Residencia Sol"), ("", ""),
])
def test_setor_saude_nao_reconhece_outros(nicho, nome):
    """Controle negativo: "residencia" contém "dent" mas não começa com ele."""
    assert not am.setor_e_saude(nicho, nome, _REGRAS)


def test_setor_sem_config_levanta_em_vez_de_assumir_saude():
    regras = _regras()
    del regras["setor_saude"]
    with pytest.raises(ValueError):
        am.setor_e_saude("Dentista", "X", regras)


def test_sem_site_fora_da_saude_pede_revisao():
    with pytest.raises(am.LinhaPedeRevisaoError, match="REVISAR SETOR"):
        _montar_direta(_linha_csv(nome="Constructora Sol"))


def test_defeito_visivel_diz_cliente_fora_da_saude_e_paciente_na_saude():
    fora = _lead(email="info@website.com", nome="Constructora Sol", nicho="Empresa constructora")
    mensagem, _ = _montar("defeito_visivel", fora, _regras_com_defeito())
    assert "Si un cliente intenta escribirles" in mensagem
    saude, _ = _montar("defeito_visivel", _lead(email="info@website.com"), _regras_com_defeito())
    assert "Si un paciente intenta escribirles" in saude


def test_lentidao_nao_exige_setor_saude():
    """O texto de lentidão não fala de paciente: serve a qualquer setor."""
    lead = _lead(lcp_ms=12400, nome="Constructora Sol", nicho="Empresa constructora")
    mensagem, _ = _montar("lentidao", lead)
    assert "Constructora Sol" in mensagem


# --- sem_site: quando o elogio se sustenta ---------------------------------------


@pytest.mark.parametrize("nota,avaliacoes,usa_texto_novo", [
    ("4.8", "120", True),
    ("4.0", "5", True),
    ("3.9", "120", False),
    ("4.8", "4", False),
    ("", "", False),
    ("4.8", "0", False),
])
def test_sem_site_so_elogia_com_nota_e_avaliacoes_que_sustentem(nota, avaliacoes, usa_texto_novo):
    mensagem, _ = _montar_direta(_linha_csv(nota=nota, avaliacoes=avaliacoes))
    assert ("se nota que sus pacientes están contentos" in mensagem) is usa_texto_novo
    if not usa_texto_novo:
        # cai no texto sem elogio, mas com a apresentação unificada (03/10/2026)
        assert _APRES_NOVA in mensagem and "ayudo a negocios locales" not in mensagem


def test_apresentacao_dos_demais_modelos_e_a_mesma_dos_novos():
    """Desde 03/10/2026 (diretor) a apresentação é uma só: os modelos sem
    `apresentacao` própria herdam a global, que agora é o texto novo. Antes,
    só os quatro modelos novos a traziam (o resto mantinha a antiga)."""
    assert _APRESENTACAO == _APRES_NOVA
    mensagem, _ = am.montar_mensagem_direta(
        "rede_social", _linha_csv(site="https://instagram.com/x"), apresentacao=_APRESENTACAO, mensagens=_MENSAGENS,
    )
    assert _APRES_NOVA in mensagem and "ayudo a negocios locales" not in mensagem
