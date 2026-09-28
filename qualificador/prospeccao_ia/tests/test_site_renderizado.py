"""Medicao do site com JavaScript (Etapa C, passo C2). SEM REDE: paginas locais servidas por um
servidor em 127.0.0.1 (nada sai da maquina).

Cada regra nova tem: um caso que deve passar (a regra dispara), um que deve falhar (nao dispara)
e controle negativo. Duas familias de teste:
  - PURAS (sem navegador): as decisoes -- estado da pagina, anti-bot, limites dos textos, lista de
    textos em dado, importacao tardia do Playwright. Rodam sempre.
  - COM NAVEGADOR (Chromium local): o fluxo inteiro por pagina. Se Playwright/Chromium nao existir
    no ambiente, sao PULADAS com o motivo explicito (fixture `pw`) -- nunca passam por omissao.
"""
import json
import re
import socket
import subprocess
import sys
from pathlib import Path

import pytest

import site_renderizado as sr

PACOTE = str(Path(sr.__file__).resolve().parent)
REGRAS = sr.carregar_antibot()


# ==================================================================================================
# PURAS
# ==================================================================================================

# --- Importacao tardia do Playwright ------------------------------------------------------------

def test_importar_o_modulo_nao_exige_playwright():
    """Duas pontas no mesmo processo: com Playwright BLOQUEADO o modulo importa (ponta 1) e
    abrir_playwright() falha com erro claro (ponta 2)."""
    codigo = (
        "import sys; sys.modules['playwright'] = None; sys.modules['playwright.sync_api'] = None\n"
        "import site_renderizado as sr\n"
        "print('importou')\n"
        "try:\n"
        "    sr.abrir_playwright()\n"
        "except sr.PlaywrightIndisponivelError as e:\n"
        "    print('indisponivel:', e)\n"
    )
    r = subprocess.run([sys.executable, "-c", codigo], cwd=PACOTE, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    assert "importou" in r.stdout
    assert "indisponivel:" in r.stdout


def test_nenhum_import_de_playwright_no_topo_do_modulo():
    fonte = Path(sr.__file__).read_text(encoding="utf-8")
    assert not [l for l in fonte.splitlines() if re.match(r"^(import|from)\s+playwright", l)]
    assert re.search(r"^\s+from playwright", fonte, re.M), "controle: o import tardio existe, dentro da funcao"


def test_o_fetch_sem_playwright_falha_com_erro_claro(monkeypatch):
    def sem_playwright():
        raise sr.PlaywrightIndisponivelError("simulado")
    monkeypatch.setattr(sr, "_api_playwright", sem_playwright)
    with pytest.raises(sr.PlaywrightIndisponivelError):
        sr._fetch_dispositivo(None, "http://x.es", "mobile", "id", Path("."))


# --- (a) estado da pagina: http_erro / anti_bot / ok ------------------------------------------

_TEXTO_NORMAL = "Clinica de fisioterapia. Pide cita. " * 10


@pytest.mark.parametrize("http_status, esperado", [
    (200, sr.STATUS_OK), (301, sr.STATUS_OK), (399, sr.STATUS_OK), (None, sr.STATUS_OK),   # deve passar como ok
    (400, sr.STATUS_HTTP_ERRO), (404, sr.STATUS_HTTP_ERRO), (500, sr.STATUS_HTTP_ERRO), (503, sr.STATUS_HTTP_ERRO),
])
def test_http_status_maior_ou_igual_a_400_e_estado_proprio(http_status, esperado):
    estado, casou = sr._estado_da_pagina(http_status, "Clinica", _TEXTO_NORMAL, len(_TEXTO_NORMAL), REGRAS)
    assert estado == esperado
    assert casou is None


def test_http_erro_e_distinto_de_ok_e_de_erro_de_rede():
    assert len({sr.STATUS_OK, sr.STATUS_HTTP_ERRO, sr.STATUS_ANTI_BOT, sr.STATUS_ERRO}) == 4


# --- (c) anti-bot: por casamento de texto, lista em dado -------------------------------------

@pytest.mark.parametrize("titulo, texto", [
    ("Just a moment...", "Enable JavaScript and cookies to continue"),        # titulo (Cloudflare)
    ("Attention Required! | Cloudflare", "x " * 400),                          # titulo em pagina LONGA: casa sempre
    ("Sitio", "Verifica que eres humano"),                                      # frase, espanhol
    ("Sitio", "VERIFICA QUE ERES HUMANO"),                                      # caixa
    ("Sitio", "Verificá que eres humano"),                                      # acento (accent-insensitive)
    ("Sitio", "Please verify you are human to continue"),                       # frase, ingles
    ("Comprobando su navegador", ""),                                           # titulo com acento
    ("Sitio", "Checking if the site connection is secure"),
    ("Sitio", "I\u2019m not a robot"),                                          # apostrofo tipografico
])
def test_antibot_deve_casar(titulo, texto):
    assert sr.detectar_antibot(titulo, texto, len(texto), REGRAS) is not None


@pytest.mark.parametrize("titulo, texto", [
    ("Clinica Ejemplo | Fisioterapia", _TEXTO_NORMAL),
    ("Contacto", ("Formulario de contacto. " * 100)                            # LONGO com aviso de reCAPTCHA:
     + "Este sitio esta protegido por reCAPTCHA. No soy un robot. Verifica que eres humano."),  # site NORMAL
    ("Sitio", ""),
    ("", ""),
    ("Sitio", "Solicita tu presupuesto"),                                        # CTA, nao desafio
    ("Captura de pantalla", "hola"),                                             # "captura" nao e "captcha"
])
def test_antibot_nao_deve_casar(titulo, texto):
    assert sr.detectar_antibot(titulo, texto, len(texto), REGRAS) is None


def test_antibot_frase_so_vale_em_pagina_curta_duas_pontas():
    frase = "verifica que eres humano"
    curto = frase
    longo = ("texto de relleno. " * 200) + frase
    assert len(longo) > REGRAS["limite_texto_curto"]
    assert sr.detectar_antibot("Sitio", curto, len(curto), REGRAS) is not None      # curta: casa
    assert sr.detectar_antibot("Sitio", longo, len(longo), REGRAS) is None          # longa: nao casa
    # o limite e sobre texto_chars quando informado (a amostra so guarda 5000 chars)
    assert sr.detectar_antibot("Sitio", curto, 10_000, REGRAS) is None


def test_anti_bot_e_estado_proprio_e_nao_ok():
    estado, casou = sr._estado_da_pagina(200, "Just a moment...", "x", 1, REGRAS)
    assert estado == sr.STATUS_ANTI_BOT != sr.STATUS_OK
    assert casou.startswith("titulo:")


def test_anti_bot_tem_precedencia_sobre_http_erro():
    """Desafios chegam com 403/503: NAO e 'site fora do ar'."""
    assert sr._estado_da_pagina(403, "Just a moment...", "x", 1, REGRAS)[0] == sr.STATUS_ANTI_BOT
    assert sr._estado_da_pagina(503, "Sitio", "verifica que eres humano", 24, REGRAS)[0] == sr.STATUS_ANTI_BOT
    assert sr._estado_da_pagina(403, "Forbidden", "Forbidden", 9, REGRAS)[0] == sr.STATUS_HTTP_ERRO   # controle


def test_lista_antibot_real_e_dado_versionado_com_proveniencia():
    bruto = json.load(open(sr.CAMINHO_ANTIBOT, encoding="utf-8"))
    assert bruto["fontes"]["lista_inicial_c2"]["calibrada"] is False       # dito no proprio arquivo
    assert bruto["fontes"]["lista_inicial_c2"]["copiado_em"]
    assert len(REGRAS["titulos"]) >= 5 and len(REGRAS["frases"]) >= 10
    for entrada in REGRAS["titulos"] + REGRAS["frases"]:
        assert entrada == sr._normalizar(entrada)


def test_regras_nao_estao_espalhadas_no_codigo():
    """A lista mora em dado: nenhuma frase de desafio aparece como literal no modulo."""
    fonte = Path(sr.__file__).read_text(encoding="utf-8")
    assert "verifica que eres humano" not in fonte.lower()
    assert "just a moment" not in fonte.lower()


def _valida():
    return {
        "limite_texto_curto": 100,
        "fontes": {"x": {"origem": "teste", "copiado_em": "2026-09-20"}},
        "titulos": ["just a moment"],
        "frases": ["verifica que eres humano"],
    }


def _escreve(tmp_path, dados, nome):
    p = tmp_path / nome
    p.write_text(json.dumps(dados), encoding="utf-8")
    return str(p)


def test_lista_valida_de_teste_carrega(tmp_path):
    regras = sr.carregar_antibot(_escreve(tmp_path, _valida(), "ok.json"))
    assert regras["limite_texto_curto"] == 100


@pytest.mark.parametrize("quebra", [
    lambda d: d.pop("fontes"),
    lambda d: d.update(fontes={}),
    lambda d: d["fontes"]["x"].pop("origem"),
    lambda d: d.update(limite_texto_curto=0),
    lambda d: d.update(limite_texto_curto="100"),
    lambda d: d.update(titulos=[]),
    lambda d: d.update(frases="verifica"),
    lambda d: d.update(frases=["Verifica Que Eres Humano"]),       # nao normalizada: nunca casaria
    lambda d: d.update(frases=["verificá que eres humano"]),       # acento
    lambda d: d.update(titulos=["just a moment", "just a moment"]),
    lambda d: d.update(titulos=[""]),
], ids=range(11))
def test_lista_antibot_invalida_falha_alto(tmp_path, quebra):
    dados = _valida()
    quebra(dados)
    with pytest.raises(sr.ConfigAntibotInvalidaError):
        sr.carregar_antibot(_escreve(tmp_path, dados, f"ruim{id(quebra)}.json"))


def test_lista_antibot_ausente_ou_quebrada_falha_alto(tmp_path):
    with pytest.raises(sr.ConfigAntibotInvalidaError):
        sr.carregar_antibot(str(tmp_path / "nao-existe.json"))
    ruim = tmp_path / "quebrado.json"
    ruim.write_text("{nao e json", encoding="utf-8")
    with pytest.raises(sr.ConfigAntibotInvalidaError):
        sr.carregar_antibot(str(ruim))


# --- (b) textos visiveis: limites ---------------------------------------------------------------

def test_textos_limitados_em_quantidade():
    brutos = [f"Botón {i}" for i in range(200)]
    assert len(sr._limitar_textos(brutos)) == sr.MAX_TEXTOS
    assert len(sr._limitar_textos(brutos[:5])) == 5                   # controle: abaixo do teto nao corta


def test_textos_limitados_em_tamanho():
    assert len(sr._limitar_textos(["x" * 300])[0]) == sr.MAX_CHARS_TEXTO
    assert sr._limitar_textos(["Pedir cita"]) == ["Pedir cita"]      # controle: curto passa inteiro


def test_textos_normalizados_sem_vazios_e_sem_repetidos():
    assert sr._limitar_textos(["  Pedir \n  cita ", "Pedir cita", "", "   ", None, "Llamar"]) == ["Pedir cita", "Llamar"]
    assert sr._limitar_textos(None) == []


# --- Resultado: nao medido != nenhum; coletado_em ---------------------------------------------

def test_resultado_novo_nao_medido_e_none_e_nao_lista_vazia():
    r = sr.ResultadoDispositivo()
    assert r.status == sr.STATUS_ERRO
    assert r.botoes_textos is None and r.links_acao_textos is None
    assert r.has_form is None and r.has_tel_link is None and r.coletado_em is None


def test_preencher_sinais_grava_os_textos_limitados():
    sinais = {
        "html_lang": "es", "has_form": True, "form_action": "/e", "has_tel_link": True,
        "has_whatsapp_link": False, "has_email_link": False, "body_text_sample": "reserva tu cita",
        "imagens_total": 3, "imagens_quebradas": 1,
        "botoes_brutos": [f"B{i}" for i in range(60)], "links_acao_brutos": ["Llámanos", "Llámanos"],
    }
    r = sr.ResultadoDispositivo()
    sr._preencher_sinais(r, sinais, 4, [{"url": "u", "status": 404}], "abre", ["e1", "e2", "e3", "e4"], ["x"])
    assert len(r.botoes_textos) == sr.MAX_TEXTOS and r.links_acao_textos == ["Llámanos"]
    assert r.has_cta_keyword is True and r.links_internos_quebrados_count == 1
    assert r.console_erros_amostra == ["e1", "e2", "e3"] and r.js_excecoes_count == 1


def test_agora_utc_e_iso_com_z_e_e_utc():
    from datetime import datetime, timezone
    valor = sr._agora_utc()
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", valor)
    dt = datetime.strptime(valor, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    assert abs((datetime.now(timezone.utc) - dt).total_seconds()) < 5


# --- Nucleo copiado: as partes puras ----------------------------------------------------------

@pytest.mark.parametrize("mensagem, tipo", [
    ("net::ERR_NAME_NOT_RESOLVED at http://x", "dns_error"),
    ("net::ERR_CONNECTION_REFUSED", "conexao_recusada"),
    ("net::ERR_CERT_DATE_INVALID", "certificado_invalido"),
    ("algo inesperado", "erro_desconhecido"),                          # controle: nao casa nada
])
def test_classificar_erro_de_rede(mensagem, tipo):
    assert sr._classificar_erro(mensagem) == tipo


def test_cta_keyword():
    assert sr._tem_cta_keyword("reserva tu cita ahora") is True
    assert sr._tem_cta_keyword("hola mundo") is False
    assert sr._tem_cta_keyword(None) is False and sr._tem_cta_keyword("") is False


def test_dois_dispositivos_com_os_viewports_do_original():
    assert set(sr.DISPOSITIVOS) == {"mobile", "desktop"}
    assert sr.DISPOSITIVOS["mobile"]["viewport"] == {"width": 390, "height": 844}
    assert sr.DISPOSITIVOS["desktop"]["viewport"] == {"width": 1440, "height": 900}


def test_modulo_nao_faz_rede_alem_do_navegador_nem_usa_llm():
    fonte = Path(sr.__file__).read_text(encoding="utf-8")
    proibidos = ("urllib.request", "socket", "http.client", "requests", "anthropic", "openai")
    for linha in fonte.splitlines():
        if linha.strip().startswith(("import ", "from ")):
            for termo in proibidos:
                assert not re.search(rf"\b{re.escape(termo)}\b", linha), linha


# ==================================================================================================
# COM NAVEGADOR — servidor local + Chromium
# ==================================================================================================

# `medir` (fixture de sessao) mora em conftest.py -- compartilhada com test_caminho_contato.py.

# --- Nucleo copiado, ponta a ponta ------------------------------------------------------------

def test_pagina_normal_e_ok_com_os_sinais_do_dom_renderizado(medir):
    r = medir("/ok")
    assert r["status"] == sr.STATUS_OK and r["http_status"] == 200 and r["erro_tipo"] is None
    assert r["has_form"] is True and r["has_tel_link"] is True
    assert r["has_whatsapp_link"] is True and r["has_email_link"] is True
    assert r["has_cta_keyword"] is True and r["html_lang"] == "es"
    assert r["imagens_total_count"] == 1 and r["imagens_quebradas_count"] == 1
    assert r["links_internos_quebrados_count"] == 1                     # /roto -> 404
    assert r["links_internos_quebrados_amostra"][0]["status"] == 404
    assert r["antibot_casou"] is None and r["tentativas"] == 1


def test_screenshot_e_gravado(medir):
    assert Path(medir("/ok")["screenshot_ref"]).is_file()


def test_menu_hamburguer_abre_no_mobile_e_nao_se_aplica_no_desktop(medir):
    assert medir("/ok", "mobile")["menu_hamburguer"] == "abre"
    assert medir("/ok", "desktop")["menu_hamburguer"] == "nao_aplicavel"
    assert medir("/js", "mobile")["menu_hamburguer"] == "nao_testavel"    # controle: sem seletor conhecido


def test_sinais_vem_do_dom_renderizado_nao_do_html_estatico(medir):
    """A razao de existir da camada: o botao montado por JS so existe depois do render."""
    r = medir("/js")
    assert "Agendar por JS" in r["botoes_textos"]
    assert r["has_form"] is False                                       # controle: nada estatico aparece de graca


# --- (a) http_erro ----------------------------------------------------------------------------

@pytest.mark.parametrize("rota, codigo", [("/404", 404), ("/500", 500)])
def test_pagina_de_erro_http_e_estado_proprio_nao_ok(medir, rota, codigo):
    r = medir(rota)
    assert r["status"] == sr.STATUS_HTTP_ERRO
    assert r["http_status"] == codigo
    assert r["erro_tipo"] is None                                       # nao e erro de rede
    assert r["antibot_casou"] is None


def test_http_erro_nao_grava_sinal_de_uma_pagina_que_nao_e_o_site(medir):
    """A /404 TEM <form> e <button>, mas o sinal fica desconhecido (None), nao True."""
    r = medir("/404")
    assert r["has_form"] is None and r["has_tel_link"] is None
    assert r["botoes_textos"] is None and r["links_acao_textos"] is None
    assert r["menu_hamburguer"] is None and r["links_internos_verificados_count"] is None


def test_erro_de_rede_continua_sendo_erro_e_nao_http_erro(pw, base_url, tmp_path, monkeypatch):
    monkeypatch.setattr(sr, "ESPERA_ENTRE_TENTATIVAS_S", 0)
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        porta_fechada = s.getsockname()[1]
    r = sr._fetch_dispositivo(pw, f"http://127.0.0.1:{porta_fechada}/", "desktop", "recusada", tmp_path)
    assert r.status == sr.STATUS_ERRO and r.erro_tipo == "conexao_recusada"
    assert r.http_status is None and r.tentativas == sr.MAX_TENTATIVAS
    assert r.coletado_em is not None


# --- (a) repetição em 404/5xx (achado real FISIOFICTICIA, 24/09/2026) --------------------------------
#
# Antes desta correção, exceção de rede (timeout/DNS/conexão recusada/certificado inválido) já
# repetia (teste acima); resposta HTTP 404/5xx com o goto() bem-sucedido NUNCA repetia -- o
# `_fetch_dispositivo` devolvia na primeira tentativa. Os dois passam a repetir pela mesma regra
# (`sr.indica_falha_dispositivo`).

@pytest.mark.parametrize("rota, codigo", [("/404", 404), ("/500", 500)])
def test_404_e_5xx_persistentes_repetem_ate_max_tentativas(pw, base_url, tmp_path, monkeypatch, rota, codigo):
    monkeypatch.setattr(sr, "ESPERA_ENTRE_TENTATIVAS_S", 0)
    r = sr._fetch_dispositivo(pw, base_url + rota, "desktop", f"persistente{codigo}", tmp_path)
    assert r.status == sr.STATUS_HTTP_ERRO and r.http_status == codigo
    assert r.tentativas == sr.MAX_TENTATIVAS  # antes da correção: sempre 1, nunca repetia


def test_403_anti_bot_nunca_repete_mesmo_persistente(pw, base_url, tmp_path, monkeypatch):
    """Controle negativo central da regra: 403/anti_bot nunca conta como falha -- não deve
    gastar uma segunda tentativa à toa."""
    monkeypatch.setattr(sr, "ESPERA_ENTRE_TENTATIVAS_S", 0)
    r = sr._fetch_dispositivo(pw, base_url + "/desafio403", "desktop", "persistente403", tmp_path)
    assert r.status == sr.STATUS_ANTI_BOT and r.http_status == 403
    assert r.tentativas == 1


# --- indica_falha_dispositivo / avaliar_estabilidade (puras, sem navegador) ------------------------

@pytest.mark.parametrize("http_status, erro_tipo, esperado", [
    (404, None, True),
    (500, None, True),
    (599, None, True),
    (403, None, False),
    (200, None, False),
    (None, "timeout", True),
    (None, "dns_error", True),
    (None, "conexao_recusada", True),
    (None, "certificado_invalido", True),
    (None, "erro_desconhecido", False),
    (None, None, False),
])
def test_indica_falha_dispositivo(http_status, erro_tipo, esperado):
    assert sr.indica_falha_dispositivo(http_status, erro_tipo) is esperado


def test_avaliar_estabilidade_nenhum_falhou_e_consistente_ok():
    por_dispositivo = {
        "mobile": {"http_status": 200, "erro_tipo": None},
        "desktop": {"http_status": 200, "erro_tipo": None},
    }
    assert sr.avaliar_estabilidade(por_dispositivo) == sr.ESTABILIDADE_OK


def test_avaliar_estabilidade_um_falhou_e_instavel_caso_fisioficticia():
    """Reprodução exata do achado real: celular ok, desktop com timeout -- "instavel", não
    "consistente_falha"."""
    por_dispositivo = {
        "mobile": {"http_status": 200, "erro_tipo": None},
        "desktop": {"http_status": None, "erro_tipo": "timeout"},
    }
    assert sr.avaliar_estabilidade(por_dispositivo) == sr.ESTABILIDADE_INSTAVEL


def test_avaliar_estabilidade_os_dois_falharam_e_consistente_falha():
    por_dispositivo = {
        "mobile": {"http_status": 404, "erro_tipo": None},
        "desktop": {"http_status": None, "erro_tipo": "timeout"},
    }
    assert sr.avaliar_estabilidade(por_dispositivo) == sr.ESTABILIDADE_FALHA


def test_avaliar_estabilidade_anti_bot_nunca_conta_como_falha():
    """Controle negativo: 403 num dispositivo + falha real no outro -- só 1 falha real, é
    "instavel", não "consistente_falha"."""
    por_dispositivo = {
        "mobile": {"http_status": 403, "erro_tipo": None},
        "desktop": {"http_status": None, "erro_tipo": "timeout"},
    }
    assert sr.avaliar_estabilidade(por_dispositivo) == sr.ESTABILIDADE_INSTAVEL


def test_avaliar_estabilidade_dict_vazio_e_consistente_ok():
    assert sr.avaliar_estabilidade({}) == sr.ESTABILIDADE_OK


# --- (c) anti_bot -----------------------------------------------------------------------------

def test_desafio_com_403_e_anti_bot_e_nao_http_erro(medir):
    r = medir("/desafio403")
    assert r["status"] == sr.STATUS_ANTI_BOT and r["http_status"] == 403
    assert r["antibot_casou"].startswith("titulo:") and r["titulo_pagina"] == "Just a moment..."


def test_desafio_por_frase_em_pagina_curta_e_anti_bot(medir):
    r = medir("/desafio200")
    assert r["status"] == sr.STATUS_ANTI_BOT and r["http_status"] == 200
    assert r["antibot_casou"] == "frase:verifica que eres humano"


def test_anti_bot_nao_grava_sinal_falso(medir):
    r = medir("/desafio403")
    assert r["has_form"] is None and r["has_cta_keyword"] is None and r["botoes_textos"] is None
    assert Path(r["screenshot_ref"]).is_file()                          # a evidencia do obstaculo fica


def test_site_normal_com_aviso_de_recaptcha_nao_e_anti_bot(medir):
    """Controle negativo do falso positivo mais provavel: formulario de contato com reCAPTCHA."""
    r = medir("/recaptcha")
    assert r["status"] == sr.STATUS_OK and r["antibot_casou"] is None
    assert r["texto_visivel_chars"] > sr.carregar_antibot()["limite_texto_curto"]
    assert r["has_form"] is True


# --- (b) textos visiveis de botoes e links de acao ---------------------------------------------

def test_textos_de_botoes_e_links_de_acao_sao_gravados(medir):
    r = medir("/ok")
    for esperado in ("Pedir cita", "Reservar ahora", "Enviar consulta", "Menu"):
        assert esperado in r["botoes_textos"], esperado
    assert {"Llámanos", "WhatsApp", "Escríbenos"} <= set(r["links_acao_textos"])


def test_botao_oculto_nao_entra_nos_textos(medir):
    r = medir("/ok")
    assert "Boton oculto" not in r["botoes_textos"]
    assert "Boton invisible" not in r["botoes_textos"]


def test_link_comum_nao_e_link_de_acao(medir):
    assert "Enlace roto" not in medir("/ok")["links_acao_textos"]
    assert "Inicio" not in medir("/ok")["links_acao_textos"]


def test_textos_respeitam_os_limites_de_quantidade_e_tamanho(medir):
    r = medir("/limites")
    assert r["status"] == sr.STATUS_OK
    assert len(r["botoes_textos"]) == sr.MAX_TEXTOS                     # 61 botoes na pagina, 25 gravados
    assert len(r["botoes_textos"][0]) == sr.MAX_CHARS_TEXTO             # o de 300 chars foi cortado em 80
    assert all(len(t) <= sr.MAX_CHARS_TEXTO for t in r["botoes_textos"])


# --- coletado_em por dispositivo ---------------------------------------------------------------

def test_coletado_em_por_dispositivo_no_lead_processado(pw, base_url, tmp_path):
    ficha = sr.processar_lead(pw, "lead_ok", base_url + "/ok", tmp_path)
    assert set(ficha) == {"lead_id", "website", "gerado_em", "por_dispositivo"}
    mobile, desktop = ficha["por_dispositivo"]["mobile"], ficha["por_dispositivo"]["desktop"]
    for r in (mobile, desktop):
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", r["coletado_em"])
    assert mobile["coletado_em"] <= desktop["coletado_em"] <= ficha["gerado_em"]
    assert mobile["status"] == desktop["status"] == sr.STATUS_OK


# ==================================================================================================
# PASSO C4 — chave de habilitacao, sonda do navegador, estado do lead, CAPTURA LIMPA
# ==================================================================================================

@pytest.mark.parametrize("valor, esperado", [
    (None, False), ("", False), ("  ", False), ("0", False), ("false", False), ("no", False), ("off", False),
    ("1", True), ("true", True), ("TRUE", True), (" yes ", True), ("on", True),
])
def test_a_fase_e_desligada_por_padrao_e_so_liga_com_valor_explicito(monkeypatch, valor, esperado):
    monkeypatch.delenv(sr.ENV_HABILITAR, raising=False)
    if valor is not None:
        monkeypatch.setenv(sr.ENV_HABILITAR, valor)
    assert sr.esta_habilitado() is esperado


class _Navegador:
    def __init__(self):
        self.fechado = False

    def close(self):
        self.fechado = True


class _Chromium:
    def __init__(self, falha=None):
        self.falha, self.navegador = falha, _Navegador()

    def launch(self, headless=True):
        if self.falha:
            raise self.falha
        return self.navegador


class _PW:
    def __init__(self, falha=None):
        self.chromium = _Chromium(falha)


def test_sonda_do_navegador_ok_abre_e_fecha():
    pw_falso = _PW()
    assert sr.verificar_navegador(pw_falso) is None
    assert pw_falso.chromium.navegador.fechado is True


def test_sonda_do_navegador_ausente_levanta_erro_proprio_com_so_a_primeira_linha():
    msg = "BrowserType.launch: Executable doesn't exist at C:/x/chrome.exe\n╔═══╗\n║ Looks like Playwright ║"
    with pytest.raises(sr.NavegadorIndisponivelError) as e:
        sr.verificar_navegador(_PW(falha=RuntimeError(msg)))
    assert str(e.value).startswith("BrowserType.launch: Executable doesn't exist")
    assert "\n" not in str(e.value) and len(str(e.value)) <= 200


def test_sonda_do_navegador_com_erro_sem_mensagem_usa_o_nome_do_tipo():
    with pytest.raises(sr.NavegadorIndisponivelError, match="RuntimeError"):
        sr.verificar_navegador(_PW(falha=RuntimeError("")))


def _d(status, **kw):
    return {"status": status, "http_status": kw.get("http_status"), "erro_tipo": kw.get("erro_tipo"),
            "antibot_casou": kw.get("antibot_casou")}


@pytest.mark.parametrize("mobile, desktop, esperado", [
    (_d("ok"), _d("ok"), ("medido", None)),                                             # so aqui e "medido"
    (_d("ok"), _d("erro", erro_tipo="timeout"), ("nao_verificado", "erro:timeout")),   # metade vista != medido
    (_d("erro", erro_tipo="dns_error"), _d("erro", erro_tipo="dns_error"), ("nao_verificado", "erro:dns_error")),
    (_d("ok"), _d("http_erro", http_status=404), ("http_erro", "http_erro:404")),
    (_d("http_erro", http_status=503), _d("erro", erro_tipo="timeout"), ("http_erro", "http_erro:503")),
    (_d("ok"), _d("anti_bot", antibot_casou="titulo:just a moment"), ("anti_bot", "anti_bot:titulo:just a moment")),
    (_d("http_erro", http_status=403), _d("anti_bot", antibot_casou="frase:x"), ("anti_bot", "anti_bot:frase:x")),
    (_d("ok"), _d("estado-que-nao-existe"), ("nao_verificado", "sem_resultado")),       # desconhecido nunca vira medido
])
def test_estado_do_lead_a_partir_dos_dois_dispositivos(mobile, desktop, esperado):
    assert sr.resumir_estado_do_lead({"mobile": mobile, "desktop": desktop}) == esperado


def test_estado_do_lead_sem_resultado_nunca_e_medido():
    assert sr.resumir_estado_do_lead({}) == ("nao_verificado", "sem_resultado")


# --- CAPTURA LIMPA: antes de qualquer interacao (RUMO 3.5) -------------------------------------



def _rgb_central(playwright, png):
    import base64
    b64 = base64.b64encode(Path(png).read_bytes()).decode()
    navegador = playwright.chromium.launch(headless=True)
    try:
        pagina = navegador.new_page()
        pagina.set_content(f'<img id="i" src="data:image/png;base64,{b64}">')
        pagina.wait_for_function("document.getElementById('i').complete")
        return pagina.evaluate("""() => {
            const i = document.getElementById('i'); const c = document.createElement('canvas');
            c.width = i.naturalWidth; c.height = i.naturalHeight;
            const x = c.getContext('2d'); x.drawImage(i, 0, 0);
            return Array.from(x.getImageData(Math.floor(c.width / 2), Math.floor(c.height / 2), 1, 1).data).slice(0, 3);
        }""")
    finally:
        navegador.close()


def test_a_captura_mobile_sai_limpa_sem_o_menu_aberto(medir, pw):
    r = medir("/menu-vermelho", "mobile")
    assert r["menu_hamburguer"] in ("abre", "nao_abre"), "o clique de teste do menu aconteceu (nao e 'nao_testavel')"
    assert _rgb_central(pw, r["screenshot_ref"]) == [255, 255, 255]     # a pagina limpa, nao a tela vermelha do menu


def test_controle_o_detector_de_pixel_ve_a_pagina_depois_do_clique(pw, base_url, tmp_path):
    """Sem isto o teste acima poderia passar sem discriminar nada: aqui a mesma pagina, clicada ANTES da
    foto (a ordem do original), sai vermelha."""
    navegador = pw.chromium.launch(headless=True)
    try:
        pagina = navegador.new_page(viewport={"width": 390, "height": 844})
        pagina.goto(base_url + "/menu-vermelho")
        pagina.click(".navbar-toggler")
        destino = tmp_path / "depois_do_clique.png"
        pagina.screenshot(path=str(destino))
    finally:
        navegador.close()
    assert _rgb_central(pw, destino) == [255, 0, 0]


def test_ordem_das_chamadas_captura_antes_de_links_e_menu_e_uma_so_por_dispositivo(pw, base_url, tmp_path, monkeypatch):
    from playwright.sync_api import Page
    ordem = []
    original_shot, original_menu, original_links = Page.screenshot, sr._testar_menu_hamburguer, sr._verificar_links_internos

    def espiao_shot(self, *a, **k):
        ordem.append("captura")
        return original_shot(self, *a, **k)

    def espiao_menu(page):
        ordem.append("menu")
        return original_menu(page)

    def espiao_links(page, links):
        ordem.append("links")
        return original_links(page, links)

    monkeypatch.setattr(Page, "screenshot", espiao_shot)
    monkeypatch.setattr(sr, "_testar_menu_hamburguer", espiao_menu)
    monkeypatch.setattr(sr, "_verificar_links_internos", espiao_links)
    r = sr._fetch_dispositivo(pw, base_url + "/ok", "mobile", "ordem", tmp_path)
    assert r.status == sr.STATUS_OK
    assert ordem == ["captura", "links", "menu"]


def test_nome_do_arquivo_de_captura_e_seguro_contra_place_id_estranho(pw, base_url, tmp_path):
    r = sr._fetch_dispositivo(pw, base_url + "/ok", "desktop", "../evil:id", tmp_path)
    arquivos = list(tmp_path.glob("*.png"))
    assert [a.name for a in arquivos] == [".._evil_id_desktop.png"]
    assert Path(r.screenshot_ref).parent == tmp_path                       # ficou dentro da pasta pedida
    assert not (tmp_path.parent / "evil:id_desktop.png").exists()


# --- texto_site (Etapa 3a, 24/09/2026): normalização e config ----------------------------------

@pytest.mark.parametrize("bruto, esperado", [
    ("  Olá   mundo  ", "Olá mundo"),
    ("Linha 1\n\nLinha 2\t\tLinha 3", "Linha 1 Linha 2 Linha 3"),
    ("", ""),
    (None, ""),
    ("SemEspacoNenhum", "SemEspacoNenhum"),
])
def test_normalizar_espacos(bruto, esperado):
    assert sr._normalizar_espacos(bruto) == esperado


def test_texto_visivel_normalizado_e_gravado_para_pagina_ok(medir):
    r = medir("/ok")
    assert r["texto_visivel_normalizado"]
    assert "\n" not in r["texto_visivel_normalizado"]
    assert "  " not in r["texto_visivel_normalizado"]


def test_texto_visivel_normalizado_e_none_para_pagina_de_erro(medir):
    """Controle: página que não é o site (404) não grava texto -- mesmo
    princípio de `_preencher_sinais` para os outros sinais."""
    assert medir("/404")["texto_visivel_normalizado"] is None


def test_carregar_config_texto_site_le_o_arquivo_real():
    assert sr.carregar_config_texto_site() == 4000


def test_carregar_config_texto_site_arquivo_ausente_levanta_erro_claro(tmp_path):
    with pytest.raises(sr.ConfigTextoSiteInvalidaError):
        sr.carregar_config_texto_site(str(tmp_path / "nao-existe.json"))


def test_carregar_config_texto_site_limite_invalido_levanta_erro_claro(tmp_path):
    caminho = tmp_path / "texto_site.json"
    caminho.write_text('{"limite_chars": -5}', encoding="utf-8")
    with pytest.raises(sr.ConfigTextoSiteInvalidaError):
        sr.carregar_config_texto_site(str(caminho))
