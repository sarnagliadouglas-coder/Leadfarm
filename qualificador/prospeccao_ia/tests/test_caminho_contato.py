"""Caminho de contato (Etapa C, passo C4b) -- correcao do falso positivo medido em C5: 4 de 12
sites saiam "sem contato" com telefone/email/agendamento escritos como TEXTO ou atras de um link
de menu, sem link estrutural (tel:/mailto:/wa) na pagina inicial.

Duas familias, como em test_site_renderizado.py:
  - PURAS (sem navegador): as regex de telefone/email, o carregador da config, a escolha de
    candidatos e a regra de dominio. Rodam sempre.
  - COM NAVEGADOR (Chromium local, servidor em 127.0.0.1): os 4 padroes reais reproduzidos
    (`servidor_local.py`) + um controle "sem contato" genuino. PULADAS com motivo se nao houver
    navegador (fixture `medir`, em conftest.py).
"""
import copy
import json

import pytest

import site_renderizado as sr

REGRAS = sr.carregar_caminho_contato()


# ==================================================================================================
# PURAS -- regex de telefone e email
# ==================================================================================================

@pytest.mark.parametrize("texto", [
    "860 000 109", "600 000 108", "960000107", "Llama al 960 00 01 07",
    "+34 612 345 678", "912-345-678", "Tel: 912345678.", "912.34.56.78",
    "Reserva tu cita en el telefono 860 000 109 o envia Whatsapp al 600 000 108",
])
def test_telefone_deve_casar(texto):
    assert sr.TELEFONE_ES_RE.search(texto) is not None


@pytest.mark.parametrize("texto", [
    "CIF: B12345678",              # CIF (letra + 8 digitos)
    "NIF 12345678Z",               # NIF (8 digitos + letra) -- so 8 digitos puros, nao 9
    "30202",                       # codigo postal (5 digitos)
    "Copyright 2024",              # ano (4 digitos)
    "49,99€",                      # preco
    "1.234,56 €",                  # preco com milhar
    "ES91 2100 0418 4502 0005 1332",  # IBAN (grupos de 4)
    "Pedido nº 202609201234567",   # referencia longa (>9 digitos corridos)
    "12345 34567",                 # dois numeros curtos concatenados
    "Horario: 09:00 a 20:00, de lunes a viernes",
])
def test_telefone_nao_deve_casar(texto):
    assert sr.TELEFONE_ES_RE.search(texto) is None


def test_telefone_nao_casa_dentro_de_numero_mais_longo_regressao():
    """Nao-vacuidade do limite de fronteira: um numero de 12 digitos corridos, comecando em 6-9,
    NAO pode virar um "telefone" de 9 pegando so os 9 primeiros."""
    assert sr.TELEFONE_ES_RE.search("620945123456789") is None


@pytest.mark.parametrize("texto", [
    "contacto@fisioficticia-catorce.es",
    "Escribenos a info@clinicaficticia-quince.es hoy",
    "contacto@fisioficticia-dieciseis.es",
    "Email: primero.segundo@dominio.co.uk.",
])
def test_email_deve_casar(texto):
    assert sr.EMAIL_RE.search(texto) is not None


@pytest.mark.parametrize("texto", [
    "usuario @ dominio . com",     # espacado
    "no-reply@",                   # incompleto
    "@dominio.com",                # sem usuario
    "texto sin arroba en el medio",
    "precio@2x.png (nombre de archivo)",   # nome de arquivo retina, nao email
    "logo@3x.jpg",
])
def test_email_nao_deve_casar(texto):
    assert sr.EMAIL_RE.search(texto) is None


def test_tem_contato_no_texto_duas_pontas():
    assert sr._tem_contato_no_texto("Llamanos al 860 000 109") == (True, False)
    assert sr._tem_contato_no_texto("Escribe a contacto@fisioficticia-catorce.es") == (False, True)
    assert sr._tem_contato_no_texto("CIF B12345678, precio 49,99€") == (False, False)
    assert sr._tem_contato_no_texto("") == (False, False)
    assert sr._tem_contato_no_texto(None) == (False, False)


# ==================================================================================================
# PURAS -- dominio
# ==================================================================================================

@pytest.mark.parametrize("url, esperado", [
    ("https://www.Clinica.ES/x", "clinica.es"),
    ("https://sub.clinica.es/x", "sub.clinica.es"),
    ("http://127.0.0.1:8080/x", "127.0.0.1"),
    ("nao-e-url", ""),
])
def test_host(url, esperado):
    assert sr._host(url) == esperado


def test_mesmo_dominio_exato_e_subdominio():
    assert sr._mesmo_dominio_ou_conhecido("https://clinica.es/contacto", "clinica.es", []) is True
    assert sr._mesmo_dominio_ou_conhecido("https://reservas.clinica.es/x", "clinica.es", []) is True


def test_mesmo_dominio_nao_e_substring_solto():
    """Mesma armadilha de site_classificacao.py: 'clinica.es' nao pode casar 'outraclinica.es'."""
    assert sr._mesmo_dominio_ou_conhecido("https://outraclinica.es/x", "clinica.es", []) is False


def test_dominio_conhecido_de_agendamento():
    assert sr._mesmo_dominio_ou_conhecido("https://calendly.com/x", "clinica.es", ["calendly.com"]) is True
    assert sr._mesmo_dominio_ou_conhecido(
        "https://clinica.calendly.com/x", "clinica.es", ["calendly.com"]) is True


def test_dominio_desconhecido_e_recusado():
    assert sr._mesmo_dominio_ou_conhecido(
        "https://facebook.com/clinica", "clinica.es", ["calendly.com"]) is False


def test_dominio_ausente_ou_invalido_nunca_e_permitido():
    assert sr._mesmo_dominio_ou_conhecido("", "clinica.es", ["calendly.com"]) is False
    assert sr._mesmo_dominio_ou_conhecido("https://clinica.es/x", None, []) is False


# ==================================================================================================
# PURAS -- escolha de candidatos (sem navegador, sem rede)
# ==================================================================================================

def _ancora(texto, href):
    return {"texto": texto, "href": href}


def test_candidato_de_contato_mesmo_dominio_e_selecionado():
    ancoras = [_ancora("Contacto", "https://clinica.es/contacto")]
    agendamento, candidatos = sr._candidatos_de_contato(ancoras, "clinica.es", REGRAS)
    assert agendamento is False
    assert candidatos == ["https://clinica.es/contacto"]


def test_candidato_agendamento_e_contado_mesmo_sem_dominio_permitido():
    """Requisito C4b-3: o botao conta como caminho de agendamento MESMO se o link nao for seguido."""
    ancoras = [_ancora("Reservar cita", "https://sistema-externo.invalido/x")]
    agendamento, candidatos = sr._candidatos_de_contato(ancoras, "clinica.es", REGRAS)
    assert agendamento is True
    assert candidatos == []              # NAO seguido: dominio desconhecido


def test_candidato_agendamento_em_dominio_conhecido_e_seguido():
    regras = {**REGRAS, "dominios_agendamento_conhecidos": ("calendly.com",)}
    ancoras = [_ancora("Reservar cita", "https://calendly.com/clinica")]
    agendamento, candidatos = sr._candidatos_de_contato(ancoras, "clinica.es", regras)
    assert agendamento is True
    assert candidatos == ["https://calendly.com/clinica"]


def test_texto_sem_palavra_de_contato_nao_e_candidato():
    ancoras = [_ancora("Sobre nosotros", "https://clinica.es/sobre"), _ancora("Facebook", "https://facebook.com/x")]
    agendamento, candidatos = sr._candidatos_de_contato(ancoras, "clinica.es", REGRAS)
    assert agendamento is False and candidatos == []


def test_palavra_curta_nao_casa_dentro_de_palavra_maior_regressao():
    """Achado pelo proprio teste: "book" (agendamento) casava substring dentro de "Facebook", e
    "cita" dentro de "explicita" -- a mesma armadilha de site_classificacao.py, agora para frases."""
    assert sr._casa_frase("facebook", "book") is False
    assert sr._casa_frase("nuestra oferta es muy explicita", "cita") is False
    assert sr._casa_frase("pedir cita previa", "cita") is True             # controle: ainda casa isolado
    ancoras = [_ancora("Facebook", "https://facebook.com/clinica")]
    agendamento, candidatos = sr._candidatos_de_contato(ancoras, "clinica.es", REGRAS)
    assert agendamento is False and candidatos == []


def test_no_maximo_dois_candidatos_e_sem_repetir_href():
    ancoras = [
        _ancora("Contacto", "https://clinica.es/a"),
        _ancora("Contacto", "https://clinica.es/a"),   # mesmo href, nao conta 2x
        _ancora("Reserva", "https://clinica.es/b"),
        _ancora("Pedir cita", "https://clinica.es/c"),  # 3o candidato: fica de fora
    ]
    agendamento, candidatos = sr._candidatos_de_contato(ancoras, "clinica.es", REGRAS)
    assert len(candidatos) == sr.MAX_PAGINAS_CONTATO_SEGUIDAS == 2
    assert candidatos == ["https://clinica.es/a", "https://clinica.es/b"]


def test_href_tel_mailto_javascript_nunca_vira_candidato_de_pagina():
    ancoras = [_ancora("Contacto", "tel:+34960000107"), _ancora("Contacto", "mailto:a@b.es"),
               _ancora("Contacto", "javascript:void(0)"), _ancora("Contacto", "#")]
    agendamento, candidatos = sr._candidatos_de_contato(ancoras, "clinica.es", REGRAS)
    assert candidatos == []


def test_so_http_https_ainda_que_o_host_da_url_bata_com_o_dominio():
    """Discrimina de verdade a checagem de esquema: um href ftp:// com host IGUAL ao do site (o
    filtro de dominio sozinho deixaria passar) so e barrado pela checagem de http(s)."""
    ancoras = [_ancora("Contacto", "ftp://clinica.es/contacto")]
    agendamento, candidatos = sr._candidatos_de_contato(ancoras, "clinica.es", REGRAS)
    assert candidatos == []


def test_ancoras_vazias_ou_ausentes_nao_quebra():
    assert sr._candidatos_de_contato([], "clinica.es", REGRAS) == (False, [])
    assert sr._candidatos_de_contato(None, "clinica.es", REGRAS) == (False, [])


# ==================================================================================================
# PURAS -- config: proveniencia e falha alta
# ==================================================================================================

def test_config_real_carrega_com_as_tres_chaves():
    regras = sr.carregar_caminho_contato()
    assert set(regras) == {"palavras_contato", "palavras_agendamento", "dominios_agendamento_conhecidos"}
    assert regras["palavras_contato"] and regras["palavras_agendamento"] and regras["dominios_agendamento_conhecidos"]


def test_toda_palavra_de_agendamento_tambem_e_palavra_de_contato_na_pratica():
    """Nao e exigencia estrutural do JSON, mas se nao fosse assim um botao de agendamento puro
    deixaria de ser candidato a seguir quando o dominio permitisse -- confirma o comportamento
    hoje da lista real."""
    for palavra in sr.carregar_caminho_contato()["palavras_agendamento"]:
        ancoras = [_ancora(palavra, "https://clinica.es/x")]
        _, candidatos = sr._candidatos_de_contato(ancoras, "clinica.es", REGRAS)
        assert candidatos == ["https://clinica.es/x"], palavra


def test_cada_fonte_tem_origem_e_data():
    bruto = json.load(open(sr.CAMINHO_CONTATO_CONFIG, encoding="utf-8"))
    for id_fonte, fonte in bruto["fontes"].items():
        assert fonte["origem"] and fonte["copiado_em"], id_fonte


def _base_valida():
    return json.loads(json.dumps({
        "fontes": {"x": {"origem": "teste", "copiado_em": "2026-09-22"}},
        "palavras_contato": ["contacto"],
        "palavras_agendamento": ["reserva"],
        "dominios_agendamento_conhecidos": ["calendly.com"],
    }))


def _escreve(tmp_path, dados, nome="cfg.json"):
    p = tmp_path / nome
    p.write_text(json.dumps(dados), encoding="utf-8")
    return str(p)


def test_config_minima_valida_carrega(tmp_path):
    regras = sr.carregar_caminho_contato(_escreve(tmp_path, _base_valida()))
    assert regras["palavras_contato"] == ("contacto",)


@pytest.mark.parametrize("quebra", [
    lambda d: d.pop("fontes"),
    lambda d: d.update(fontes={}),
    lambda d: d["fontes"]["x"].pop("origem"),
    lambda d: d.update(palavras_contato=[]),
    lambda d: d.update(palavras_agendamento="reserva"),
    lambda d: d.update(palavras_contato=["Contacto"]),        # nao normalizada (maiuscula)
    lambda d: d.update(palavras_contato=["contácto"]),        # nao normalizada (acento)
    lambda d: d.update(palavras_contato=["contacto", "contacto"]),  # repetida
    lambda d: d.update(dominios_agendamento_conhecidos=[]),
    lambda d: d.update(dominios_agendamento_conhecidos=["Calendly.com"]),   # maiuscula
    lambda d: d.update(dominios_agendamento_conhecidos=["www.calendly.com"]),  # com www.
    lambda d: d.update(dominios_agendamento_conhecidos=["calendly.com", "calendly.com"]),  # repetido
], ids=range(12))
def test_config_invalida_falha_alto(tmp_path, quebra):
    dados = copy.deepcopy(_base_valida())
    quebra(dados)
    with pytest.raises(sr.ConfigCaminhoContatoInvalidaError):
        sr.carregar_caminho_contato(_escreve(tmp_path, dados, f"ruim{id(quebra)}.json"))


def test_config_ausente_ou_json_quebrado_falha_alto(tmp_path):
    with pytest.raises(sr.ConfigCaminhoContatoInvalidaError):
        sr.carregar_caminho_contato(str(tmp_path / "nao-existe.json"))
    ruim = tmp_path / "quebrado.json"
    ruim.write_text("{nao e json", encoding="utf-8")
    with pytest.raises(sr.ConfigCaminhoContatoInvalidaError):
        sr.carregar_caminho_contato(str(ruim))


def test_fetch_dispositivo_falha_alto_sem_tocar_playwright_se_config_de_contato_ruim(monkeypatch, tmp_path):
    """Falha da config de caminho de contato acontece ANTES de usar o playwright (aqui, `None`,
    que quebraria com AttributeError se o codigo tentasse `.chromium` antes) -- mesmo padrao de
    `carregar_antibot` em `_fetch_dispositivo`."""
    def sempre_falha(caminho=None):
        raise sr.ConfigCaminhoContatoInvalidaError("simulado")
    monkeypatch.setattr(sr, "carregar_caminho_contato", sempre_falha)
    with pytest.raises(sr.ConfigCaminhoContatoInvalidaError):
        sr._fetch_dispositivo(None, "http://x.es", "desktop", "id", tmp_path)


# ==================================================================================================
# COM NAVEGADOR — os 4 padroes reais + controle "sem contato" genuino
# ==================================================================================================

def test_fisioficticia_texto_sem_link_e_achado_por_texto(medir):
    """Padrao 1 (fisioficticia, C5): telefone/WhatsApp/email como texto, sem link nenhum."""
    r = medir("/fisioficticia-texto")
    assert r["contato_visivel"] is True
    assert r["contato_origens"] == ["texto_na_inicial"]
    assert r["telefone_clicavel"] is False           # achado so como texto, nunca por link
    assert r["has_tel_link"] is False and r["has_whatsapp_link"] is False and r["has_email_link"] is False


def test_irene_like_menu_leva_a_pagina_com_contato(medir):
    """Padrao 2 (Ana Ficticia, C5): menu 'RESERVA CITA'/'CONTACTO' + botao 'RESERVA', sem contato
    na inicial; a pagina de contato de verdade tem telefone clicavel."""
    r = medir("/irene-like")
    assert r["contato_visivel"] is True
    assert set(r["contato_origens"]) == {"pagina_de_contato", "botao_de_agendamento"}
    assert r["telefone_clicavel"] is True
    assert r["has_tel_link"] is False                 # a inicial em si NAO tem link (fica correto)


def test_jesus_like_menu_e_botoes_levam_a_pagina_com_whatsapp(medir):
    """Padrao 3 (Luis Ficticio, C5): 'Contacto' no menu, botao flutuante e 'Pedir cita previa'."""
    r = medir("/jesus-like")
    assert r["contato_visivel"] is True
    assert "pagina_de_contato" in r["contato_origens"]
    assert r["has_whatsapp_link"] is False             # a inicial em si nao tem


def test_fictx_like_dominio_externo_desconhecido_fica_sem_contato(medir):
    """Padrao 4 (FICTX, C5): 'Contacto' e Facebook levam a dominio externo DESCONHECIDO -- correto
    continuar 'sem contato visivel', porque nao ha prova de contato real, so um link de rede
    social. Controle de restricao de dominio: nenhuma rede real foi tentada (dominio .invalido)."""
    r = medir("/fictx-like")
    assert r["contato_visivel"] is False
    assert r["contato_origens"] == []
    assert r["telefone_clicavel"] is None


def test_agendamento_externo_desconhecido_conta_sem_ser_seguido(medir):
    """Requisito C4b-3, ponta a ponta: link de agendamento para sistema externo desconhecido conta
    como caminho de contato mesmo sem a ferramenta abrir a pagina (dominio .invalido = nunca
    resolvido de verdade)."""
    r = medir("/agendamento-externo-desconhecido")
    assert r["contato_visivel"] is True
    assert r["contato_origens"] == ["botao_de_agendamento"]


def test_precos_e_cif_no_texto_nao_disparam_falso_positivo(medir):
    """Controle negativo de regex dentro de pagina renderizada de verdade (nao so regex isolada)."""
    r = medir("/precos-cif")
    assert r["contato_visivel"] is False
    assert r["contato_origens"] == []


def test_link_na_inicial_impede_seguir_mesmo_havendo_candidato_valido(medir):
    """Discrimina de verdade (diferente do teste com /ok): a subpagina candidata TEM contato
    proprio -- se a ferramenta a seguisse por engano, 'pagina_de_contato' apareceria. So nao
    aparece se o codigo realmente parar em link_na_inicial."""
    r = medir("/ja-tem-link")
    assert r["contato_origens"] == ["link_na_inicial"]
    assert "pagina_de_contato" not in r["contato_origens"]


def test_pagina_ok_com_link_estrutural_nao_precisa_seguir_nada(medir):
    """Controle: quando a inicial ja tem link_na_inicial (a evidencia mais forte), a ferramenta
    NAO segue paginas -- mas o botao de agendamento da propria inicial ('Reservar ahora') ainda
    conta, porque essa deteccao nao depende de seguir link nenhum."""
    r = medir("/ok")
    assert r["contato_visivel"] is True
    assert "link_na_inicial" in r["contato_origens"]
    assert "pagina_de_contato" not in r["contato_origens"]
    assert "botao_de_agendamento" in r["contato_origens"]      # "Reservar ahora"
    assert r["telefone_clicavel"] is True


def test_http_erro_e_anti_bot_nao_medem_contato(medir):
    """Fora de STATUS_OK os campos de contato ficam None/vazio -- igual aos outros sinais (medido
    ja garante isso por construcao; aqui so confirma para os campos novos)."""
    r = medir("/404")
    assert r["contato_visivel"] is None
    assert r["contato_origens"] == []
    assert r["telefone_clicavel"] is None

    r2 = medir("/desafio403")
    assert r2["contato_visivel"] is None
    assert r2["contato_origens"] == []


def test_teto_de_links_internos_caiu_de_15_para_5(medir):
    """Requisito C4b-6, ponta a ponta: pagina com 7 links internos so pode examinar 5 (nao 15)."""
    r = medir("/muitos-links")
    assert r["links_internos_verificados_count"] == 5 == sr.MAX_LINKS_INTERNOS_VERIFICADOS


def test_seguir_pagina_ruim_nao_derruba_a_medicao(medir):
    """Best-effort: um candidato cujo destino nao existe (404) nao impede o resto -- so nao acusa
    pagina_de_contato para aquele candidato."""
    r = medir("/agendamento-externo-desconhecido")  # ja provado acima que nao quebra
    assert r["status"] == sr.STATUS_OK
