"""Medicao do site COM JavaScript renderizado (Etapa C, passo C2). Copia do nucleo de
comercial/ferramentas/fetch_tecnico.py (o original foi aposentado em 28/09/2026 e esta no backup), mais as regras
que ele nao tem. Quem o chama e main.fase_render (passo C4), DESLIGADA por padrao (RENDER_ENABLED).

Verificacao comportamental por dispositivo (mobile/desktop): presenca estrutural de formulario,
telefone, WhatsApp e e-mail no DOM renderizado, palavra de CTA, imagens e links quebrados, menu
hamburguer, erros de console, screenshot. Sinal cru: nao interpreta nada, nao pontua, nao decide
pista (isso vem depois). Nunca submete formulario.

Playwright e IMPORTADO TARDE: importar este modulo NAO exige Playwright instalado. Sem ele,
abrir_playwright() e _fetch_dispositivo() levantam PlaywrightIndisponivelError com mensagem clara.
Dependencia OPCIONAL (requirements.txt, decisao do diretor de 20/09/2026). Instalacao:
    pip install -r requirements.txt
    playwright install chromium     # o pacote nao traz o navegador

DIFERENCAS DO ORIGINAL (LEVANTAMENTO-ETAPA-C.md secao 1.1), todas de proposito:
  1. ESTADO da pagina, em vez de "ok" para tudo o que renderizou. status e um de:
       "ok"        renderizou, sem desafio e http_status < 400 (ou desconhecido);
       "http_erro" renderizou com http_status >= 400 (404/500...): e uma pagina de erro, nao a
                   home do negocio -- distinto de "ok" e de erro de rede;
       "anti_bot"  tela de verificacao/CAPTCHA reconhecida por texto (config/antibot_textos.json);
       "erro"      falha de rede/navegador (timeout, DNS, conexao, certificado), como no original.
     "anti_bot" tem precedencia sobre "http_erro" (desafios costumam vir com 403/503). Nos estados
     que nao sao "ok" os SINAIS ficam None (desconhecido), nao False: medir uma pagina que nao e o
     site produz sinal falso ("sem formulario" numa tela de desafio). Sem nova tentativa nesses dois
     estados (repetir nao muda a pagina).
  2. TEXTOS visiveis de botoes e de links de acao (botoes_textos, links_acao_textos), com limite
     de quantidade (MAX_TEXTOS) e de tamanho (MAX_CHARS_TEXTO). O original descartava.
  3. Deteccao de anti-bot por casamento de texto conhecido, com a lista em DADO
     (config/antibot_textos.json). Lista inicial, nao calibrada contra paginas reais.
  4. coletado_em (UTC) por dispositivo. Campos extras de evidencia: titulo_pagina,
     texto_visivel_chars, antibot_casou.
  5. CAPTURA LIMPA (passo C4, RUMO-COMERCIAL-2026-09 3.5): o screenshot e tirado ANTES de qualquer
     interacao com a pagina -- antes do teste de links e do clique no menu hamburguer. O original
     (fetch_tecnico.py:325-328) clicava no menu e so entao fotografava: a captura mobile saia com o
     menu aberto, imprestavel para a triagem visual. Existe UMA captura por dispositivo (a limpa);
     a captura pos-clique deixou de existir neste modulo (o resultado do clique continua em
     `menu_hamburguer`). O original, no COMERCIAL, nao foi alterado.
  6. CAMINHO DE CONTATO (passo C4b, 22/09/2026 -- correcao de falso positivo medido em C5: 4 de 12
     sites saiam "sem contato" com telefone/email escritos como TEXTO no centro da pagina, sem
     link tel:/mailto:, porque a checagem so via link estrutural). Alem de link estrutural, agora:
       a) telefone e email sao procurados tambem no TEXTO visivel da pagina inicial, por regex
          (`TELEFONE_ES_RE`, `EMAIL_RE`) -- nao so em `href`;
       b) se a pagina inicial nao tiver contato via LINK estrutural (o caso mais forte), a
          ferramenta segue ate 2 links/botoes visiveis cujo texto indique contato ou agendamento
          (lista em `config/caminho_contato.json`, nao no codigo) e procura contato la, com as
          MESMAS regras. So abre link do mesmo dominio do site ou de um dominio de agendamento
          conhecido (mesma config). Nunca envia formulario, nunca clica em mais nada.
       c) um botao/link de agendamento conta como caminho de contato mesmo sem ser aberto (mesmo
          levando a um sistema externo fora da lista conhecida) -- a presenca do botao ja e sinal.
       d) `contato_origens` registra ONDE achou (`link_na_inicial` / `texto_na_inicial` /
          `pagina_de_contato` / `botao_de_agendamento`, pode ter mais de um); `contato_visivel` e
          `bool(contato_origens)` -- so fica "sem contato visivel" quando a lista fica vazia.
          `telefone_clicavel` distingue "tem link tel:" (True) de "so aparece como texto" (False);
          `None` quando nenhum telefone foi encontrado por nenhum caminho.
     `MAX_LINKS_INTERNOS_VERIFICADOS` cai de 15 para 5 (decisao do diretor, 22/09): o tempo
     liberado da checagem de links vai para este passo.
  Fora isso, o comportamento e o do original. NAO copiado: main()/CLI, que le o handoff do EQC via
  contrato_loader.
"""
import json
import os
import re
import time
import unicodedata
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import urlsplit

CAMINHO_ANTIBOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config", "antibot_textos.json")
CAMINHO_CONTATO_CONFIG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config", "caminho_contato.json")
CAMINHO_TEXTO_SITE_CONFIG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config", "texto_site.json")

# --- Parametros operacionais (copiados de fetch_tecnico.py:74-85) --------------------------------
NAVEGACAO_TIMEOUT_MS = 15_000
MAX_TENTATIVAS = 2
ESPERA_ENTRE_TENTATIVAS_S = 3
# 1a tentativa mais rigorosa (networkidle), 2a mais tolerante (load): sites com beacons/chat nunca
# ficam "idle".
ESTRATEGIAS_ESPERA = ["networkidle", "load"]
MAX_LINKS_INTERNOS_VERIFICADOS = 5  # era 15 (decisao do diretor, 22/09): tempo liberado -> caminho de contato
LINK_CHECK_TIMEOUT_MS = 5_000

# --- Caminho de contato (passo C4b) ---------------------------------------------------------------
MAX_PAGINAS_CONTATO_SEGUIDAS = 2
NAVEGACAO_CONTATO_TIMEOUT_MS = 10_000
MAX_CHARS_TEXTO_COMPLETO = 20_000  # so para procurar telefone/email por regex; nao e gravado no resultado

ORIGEM_LINK_INICIAL = "link_na_inicial"
ORIGEM_TEXTO_INICIAL = "texto_na_inicial"
ORIGEM_PAGINA_CONTATO = "pagina_de_contato"
ORIGEM_BOTAO_AGENDAMENTO = "botao_de_agendamento"
ORDEM_ORIGENS = (ORIGEM_LINK_INICIAL, ORIGEM_TEXTO_INICIAL, ORIGEM_PAGINA_CONTATO, ORIGEM_BOTAO_AGENDAMENTO)

# Telefone espanhol: 9 digitos (movel 6/7, fixo 8/9), separador opcional ANTES DE CADA digito (cobre
# qualquer agrupamento: 3-3-3, 2-2-2-2-1, sem separador...). Fronteira de digito (?<!\d)/(?!\d) nos
# dois lados evita casar dentro de CIF/NIF (letra junto), codigo postal (5 digitos), ano (4 digitos),
# preco (formatacao com , ou . decimais e simbolo), IBAN (grupos de 4) e referencias longas (>9
# digitos corridos) -- provado caso a caso em tests/test_site_renderizado.py.
TELEFONE_ES_RE = re.compile(r'(?<!\d)(?:\+34|0034)?[\s.\-]?[6789](?:[\s.\-]?\d){8}(?!\d)')
# Email: exige @ com host e TLD de 2+ letras; nega TLD que na verdade e extensao de arquivo/imagem
# (evita "logo@2x.png" ser lido como e-mail).
EMAIL_RE = re.compile(
    r'[A-Za-z0-9][A-Za-z0-9._%+\-]*@[A-Za-z0-9][A-Za-z0-9.\-]*\.'
    r'(?!(?:png|jpe?g|gif|svg|webp|ico|css|js)\b)[A-Za-z]{2,}'
)

# --- Novo: limites dos textos gravados -----------------------------------------------------------
MAX_TEXTOS = 25
MAX_CHARS_TEXTO = 80
MAX_CHARS_TITULO = 120

STATUS_OK = "ok"
STATUS_HTTP_ERRO = "http_erro"
STATUS_ANTI_BOT = "anti_bot"
STATUS_ERRO = "erro"

# Estado do LEAD (as duas paginas juntas) na fase de renderizacao. anti_bot e http_erro sao os
# mesmos nomes do status do dispositivo: sao estados proprios, nao "nao verificado".
ESTADO_MEDIDO = "medido"
ESTADO_PULADO = "pulado"
ESTADO_NAO_VERIFICADO = "nao_verificado"
MOTIVO_PLAYWRIGHT_INDISPONIVEL = "playwright_indisponivel"
MOTIVO_NAVEGADOR_INDISPONIVEL = "navegador_indisponivel"

# A fase de renderizacao e DESLIGADA por padrao (mesmo desenho de PSI_ENABLED, psi_client.py).
ENV_HABILITAR = "RENDER_ENABLED"
_LIGADO = {"1", "true", "yes", "on"}

DISPOSITIVOS = {
    "mobile": {
        "viewport": {"width": 390, "height": 844},
        "user_agent": (
            "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
            "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 "
            "Mobile/15E148 Safari/604.1"
        ),
        "is_mobile": True,
    },
    "desktop": {
        "viewport": {"width": 1440, "height": 900},
        "user_agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        ),
        "is_mobile": False,
    },
}

# CTA em castellano da Espanha (copiado sem alteracao de fetch_tecnico.py:111-115).
CTA_KEYWORDS_ES = [
    "reservar", "reserva tu", "agendar", "pedir cita", "pide cita",
    "solicitar", "solicita", "contactar", "contáctanos", "contacta",
    "llamar", "llámanos", "escríbenos", "presupuesto", "consulta gratuita",
]

# Heuristico: quando nenhum seletor casa, o resultado e "nao_testavel", nunca "nao_abre".
HAMBURGER_SELECTORS = [
    'button[aria-label*="menu" i]',
    'button[aria-label*="navegación" i]',
    'button[aria-label*="navigation" i]',
    'button.navbar-toggler',
    '.hamburger', '.hamburger-menu', '.menu-toggle', '.nav-toggle',
    '[class*="burger" i]',
    'button[aria-controls][aria-expanded]',
]

ERRO_PADROES = {
    "dns_error": ["ERR_NAME_NOT_RESOLVED", "ERR_ADDRESS_UNREACHABLE"],
    "conexao_recusada": ["ERR_CONNECTION_REFUSED", "ERR_CONNECTION_RESET",
                          "ERR_CONNECTION_CLOSED", "ERR_CONNECTION_TIMED_OUT"],
    "certificado_invalido": ["ERR_CERT_", "ERR_SSL_"],
}

# Achado real (supervisão, 24/09/2026): FISIOFICTICIA entrou na nata como fora_do_ar por UM
# timeout no desktop, com o celular abrindo normal (status ok, 3,5s) e PSI normal. A regra
# antiga de output_json.py contava qualquer dispositivo com falha -- esta lista e as duas
# funções abaixo são a fonte única do que conta como "falha de dispositivo" para as duas
# pontas do defeito: quando repetir a medição (`_fetch_dispositivo`) e quando derivar
# fora_do_ar/instavel (`output_json._problemas_vendaveis`). anti_bot e 403 NUNCA contam --
# são desafio, não site fora do ar.
ERROS_RETENTAVEIS = frozenset({"timeout", "dns_error", "conexao_recusada", "certificado_invalido"})

ESTABILIDADE_OK = "consistente_ok"
ESTABILIDADE_INSTAVEL = "instavel"
ESTABILIDADE_FALHA = "consistente_falha"


def indica_falha_dispositivo(http_status, erro_tipo):
    """True quando `http_status`/`erro_tipo` (o estado FINAL de um dispositivo, depois de
    qualquer repetição) é uma falha de rede ou servidor: `timeout`, `dns_error`,
    `conexao_recusada`, `certificado_invalido`, `404`, ou `5xx`. `anti_bot` e `403` devolvem
    `False` sempre -- desafio não é falha do site."""
    if erro_tipo in ERROS_RETENTAVEIS:
        return True
    if http_status == 404:
        return True
    if isinstance(http_status, int) and 500 <= http_status <= 599:
        return True
    return False


def avaliar_estabilidade(por_dispositivo: dict) -> str:
    """Compara o estado FINAL (pós-repetição) dos dispositivos medidos:
    - `ESTABILIDADE_OK` -- nenhum falhou.
    - `ESTABILIDADE_INSTAVEL` -- só ALGUNS falharam (não todos) -- sinal de instabilidade
      pontual, registrado na medição, mas NUNCA vira `problema_vendavel` (`fora_do_ar`).
    - `ESTABILIDADE_FALHA` -- TODOS os dispositivos medidos falharam -- essa, sim, é a
      condição para `fora_do_ar` em `output_json._problemas_vendaveis`.
    Dict vazio (nada medido) conta como `ESTABILIDADE_OK` -- ausência de dado não é falha."""
    if not por_dispositivo:
        return ESTABILIDADE_OK
    falhas = sum(
        1 for r in por_dispositivo.values()
        if indica_falha_dispositivo(r.get("http_status"), r.get("erro_tipo"))
    )
    if falhas == 0:
        return ESTABILIDADE_OK
    if falhas == len(por_dispositivo):
        return ESTABILIDADE_FALHA
    return ESTABILIDADE_INSTAVEL


class PlaywrightIndisponivelError(RuntimeError):
    """Playwright nao esta instalado neste ambiente."""


class NavegadorIndisponivelError(RuntimeError):
    """Playwright esta instalado, mas o navegador nao inicia (ex.: `playwright install chromium` nao rodou)."""


class ConfigAntibotInvalidaError(ValueError):
    """A lista de textos anti-bot esta ausente ou malformada. Falha alta: lista vazia em silencio
    deixaria uma tela de desafio passar como site medido."""


class ConfigCaminhoContatoInvalidaError(ValueError):
    """A lista de palavras/dominios do caminho de contato esta ausente ou malformada. Falha alta:
    lista vazia em silencio faria a ferramenta nunca seguir nenhum link de contato."""


class ConfigTextoSiteInvalidaError(ValueError):
    """`config/texto_site.json` ausente, ilegivel ou sem 'limite_chars' inteiro positivo."""


# --- Playwright, importacao tardia ---------------------------------------------------------------

def _api_playwright():
    try:
        from playwright.sync_api import Error as PlaywrightError
        from playwright.sync_api import TimeoutError as PlaywrightTimeout
        from playwright.sync_api import sync_playwright
    except ImportError as e:
        raise PlaywrightIndisponivelError(
            "Playwright nao esta instalado (pip install playwright && playwright install chromium)") from e
    return sync_playwright, PlaywrightError, PlaywrightTimeout


def abrir_playwright():
    """Uso: `with abrir_playwright() as playwright: processar_lead(playwright, ...)`."""
    return _api_playwright()[0]()


def esta_habilitado():
    return os.environ.get(ENV_HABILITAR, "").strip().lower() in _LIGADO


def verificar_navegador(playwright):
    """Sonda: abre e fecha o navegador uma vez. Sem ela, um Chromium ausente viraria "erro do site" em
    cada lead (e consumiria as tentativas dele), quando o defeito e do ambiente."""
    try:
        navegador = playwright.chromium.launch(headless=True)
        navegador.close()
    except Exception as e:
        linhas = [l for l in str(e).splitlines() if l.strip()]
        raise NavegadorIndisponivelError((linhas[0] if linhas else type(e).__name__)[:200]) from e


# --- Lista de textos anti-bot (dado) -------------------------------------------------------------

def _normalizar(texto):
    """Minusculas, sem acento, espacos simples, apostrofo tipografico -> reto."""
    texto = unicodedata.normalize("NFKD", texto or "")
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    return " ".join(texto.replace("’", "'").lower().split())


_cache_antibot = {}


def _lista(bruto, chave):
    itens = bruto.get(chave)
    if not isinstance(itens, list) or not itens:
        raise ConfigAntibotInvalidaError(f"'{chave}' deve ser lista nao vazia")
    for item in itens:
        if not isinstance(item, str) or not item.strip():
            raise ConfigAntibotInvalidaError(f"'{chave}': entrada invalida {item!r}")
        if item != _normalizar(item):
            raise ConfigAntibotInvalidaError(
                f"'{chave}': '{item}' nao esta normalizada (minuscula, sem acento, espacos simples) e nunca casaria")
    if len(set(itens)) != len(itens):
        raise ConfigAntibotInvalidaError(f"'{chave}' tem entrada repetida")
    return tuple(itens)


def carregar_antibot(caminho=CAMINHO_ANTIBOT):
    """{"limite_texto_curto": int, "titulos": (...), "frases": (...)}. Cacheada por caminho."""
    if caminho in _cache_antibot:
        return _cache_antibot[caminho]
    try:
        with open(caminho, "r", encoding="utf-8") as f:
            bruto = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        raise ConfigAntibotInvalidaError(f"nao consegui ler '{caminho}': {e}") from e
    if not isinstance(bruto, dict):
        raise ConfigAntibotInvalidaError("raiz deve ser objeto")
    fontes = bruto.get("fontes")
    if not isinstance(fontes, dict) or not fontes or not all(
            isinstance(f, dict) and f.get("origem") and f.get("copiado_em") for f in fontes.values()):
        raise ConfigAntibotInvalidaError("'fontes' ausente: cada fonte precisa de 'origem' e 'copiado_em'")
    limite = bruto.get("limite_texto_curto")
    if not isinstance(limite, int) or isinstance(limite, bool) or limite <= 0:
        raise ConfigAntibotInvalidaError("'limite_texto_curto' deve ser inteiro positivo")
    resultado = {"limite_texto_curto": limite, "titulos": _lista(bruto, "titulos"), "frases": _lista(bruto, "frases")}
    _cache_antibot[caminho] = resultado
    return resultado


def carregar_config_texto_site(caminho=CAMINHO_TEXTO_SITE_CONFIG):
    """`{"limite_chars": int positivo}` — limite do campo `texto_site` do contrato (2.1.0).
    Nunca cacheada (arquivo pequeno, lido uma vez por rodada de saída)."""
    try:
        with open(caminho, "r", encoding="utf-8") as f:
            bruto = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        raise ConfigTextoSiteInvalidaError(f"nao consegui ler '{caminho}': {e}") from e
    limite = bruto.get("limite_chars") if isinstance(bruto, dict) else None
    if not isinstance(limite, int) or isinstance(limite, bool) or limite <= 0:
        raise ConfigTextoSiteInvalidaError("'limite_chars' deve ser inteiro positivo")
    return limite


def detectar_antibot(titulo, texto, texto_chars=None, regras=None):
    """O que casou ("titulo:..." / "frase:...") ou None. Titulo casa sempre; frase so em pagina
    curta -- pagina normal de contato traz "protegido por reCAPTCHA" no meio de muito texto."""
    regras = regras or carregar_antibot()
    t = _normalizar(titulo)
    for x in regras["titulos"]:
        if x in t:
            return f"titulo:{x}"
    n = texto_chars if texto_chars is not None else len(texto or "")
    if n > regras["limite_texto_curto"]:
        return None
    corpo = _normalizar(texto)
    for f in regras["frases"]:
        if f in corpo:
            return f"frase:{f}"
    return None


_cache_caminho_contato = {}


def _lista_normalizada_nao_vazia(bruto, chave, tipo="ValueError"):
    itens = bruto.get(chave)
    if not isinstance(itens, list) or not itens:
        raise ConfigCaminhoContatoInvalidaError(f"'{chave}' deve ser lista nao vazia")
    for item in itens:
        if not isinstance(item, str) or not item.strip():
            raise ConfigCaminhoContatoInvalidaError(f"'{chave}': entrada invalida {item!r}")
        if item != _normalizar(item):
            raise ConfigCaminhoContatoInvalidaError(
                f"'{chave}': '{item}' nao esta normalizada (minuscula, sem acento, espacos simples)")
    if len(set(itens)) != len(itens):
        raise ConfigCaminhoContatoInvalidaError(f"'{chave}' tem entrada repetida")
    return tuple(itens)


def carregar_caminho_contato(caminho=CAMINHO_CONTATO_CONFIG):
    """{"palavras_contato": (...), "palavras_agendamento": (...), "dominios_agendamento_conhecidos": (...)}.
    Cacheada por caminho."""
    if caminho in _cache_caminho_contato:
        return _cache_caminho_contato[caminho]
    try:
        with open(caminho, "r", encoding="utf-8") as f:
            bruto = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        raise ConfigCaminhoContatoInvalidaError(f"nao consegui ler '{caminho}': {e}") from e
    if not isinstance(bruto, dict):
        raise ConfigCaminhoContatoInvalidaError("raiz deve ser objeto")
    fontes = bruto.get("fontes")
    if not isinstance(fontes, dict) or not fontes or not all(
            isinstance(f, dict) and f.get("origem") and f.get("copiado_em") for f in fontes.values()):
        raise ConfigCaminhoContatoInvalidaError("'fontes' ausente: cada fonte precisa de 'origem' e 'copiado_em'")
    dominios = bruto.get("dominios_agendamento_conhecidos")
    if not isinstance(dominios, list) or not dominios:
        raise ConfigCaminhoContatoInvalidaError("'dominios_agendamento_conhecidos' deve ser lista nao vazia")
    for d in dominios:
        if not isinstance(d, str) or not d.strip() or d != d.strip().lower() or d.startswith("www."):
            raise ConfigCaminhoContatoInvalidaError(f"'dominios_agendamento_conhecidos': dominio invalido {d!r}")
    if len(set(dominios)) != len(dominios):
        raise ConfigCaminhoContatoInvalidaError("'dominios_agendamento_conhecidos' tem entrada repetida")
    resultado = {
        "palavras_contato": _lista_normalizada_nao_vazia(bruto, "palavras_contato"),
        "palavras_agendamento": _lista_normalizada_nao_vazia(bruto, "palavras_agendamento"),
        "dominios_agendamento_conhecidos": tuple(dominios),
    }
    _cache_caminho_contato[caminho] = resultado
    return resultado


def _host(url):
    try:
        h = (urlsplit(url).hostname or "").lower()
    except ValueError:
        return None
    return h[4:] if h.startswith("www.") else h


def _mesmo_dominio_ou_conhecido(href, dominio_site, dominios_conhecidos):
    h = _host(href)
    if not h or not dominio_site:
        return False
    if h == dominio_site or h.endswith("." + dominio_site):
        return True
    return any(h == d or h.endswith("." + d) for d in dominios_conhecidos)


def _tem_contato_no_texto(texto):
    """(telefone_encontrado, email_encontrado), por regex sobre texto visivel (nao lowered)."""
    return bool(TELEFONE_ES_RE.search(texto or "")), bool(EMAIL_RE.search(texto or ""))


def _casa_frase(texto_normalizado, frase):
    """Frase inteira, nao substring solta: "book" nao pode casar dentro de "facebook", nem "cita"
    dentro de "explicita" -- mesma armadilha que site_classificacao.py documenta para dominios.
    `texto_normalizado` e `frase` ja passaram por `_normalizar` (minusculas, sem acento)."""
    padrao = r"(?<!\w)" + re.escape(frase) + r"(?!\w)"
    return re.search(padrao, texto_normalizado) is not None


def _candidatos_de_contato(ancoras, dominio_site, regras):
    """(agendamento_achado, candidatos_a_seguir). agendamento_achado NAO depende de dominio (a
    presenca do botao ja e sinal, decisao C4b item 3); candidatos_a_seguir e filtrado por dominio,
    no maximo MAX_PAGINAS_CONTATO_SEGUIDAS, so http(s), sem repetir href."""
    agendamento_achado = False
    candidatos = []
    vistos = set()
    for a in ancoras or []:
        href = (a.get("href") or "").strip()
        texto = _normalizar(a.get("texto") or "")
        if not texto:
            continue
        eh_agendamento = any(_casa_frase(texto, p) for p in regras["palavras_agendamento"])
        eh_contato = eh_agendamento or any(_casa_frase(texto, p) for p in regras["palavras_contato"])
        if not eh_contato:
            continue
        if eh_agendamento:
            agendamento_achado = True
        if (not href.lower().startswith(("http://", "https://"))) or href in vistos:
            continue
        vistos.add(href)
        if len(candidatos) < MAX_PAGINAS_CONTATO_SEGUIDAS and _mesmo_dominio_ou_conhecido(
                href, dominio_site, regras["dominios_agendamento_conhecidos"]):
            candidatos.append(href)
    return agendamento_achado, candidatos


def _seguir_paginas_contato(page, candidatos):
    """Visita ate MAX_PAGINAS_CONTATO_SEGUIDAS candidatos (page.goto, nunca clique), procura contato
    pelas mesmas regras. Nunca envia formulario, nunca interage alem da navegacao. Pagina ruim so
    pula (best-effort) -- nao derruba a medicao do dispositivo."""
    achou = False
    telefone_clicavel = None
    for href in candidatos:
        try:
            page.goto(href, timeout=NAVEGACAO_CONTATO_TIMEOUT_MS, wait_until="load")
            page.wait_for_timeout(300)
            sinais = _extrair_sinais(page)
        except Exception:
            continue
        tem_link = sinais["has_tel_link"] or sinais["has_whatsapp_link"] or sinais["has_email_link"]
        tel_texto, email_texto = _tem_contato_no_texto(sinais.get("texto_completo"))
        if tem_link or tel_texto or email_texto:
            achou = True
        if sinais["has_tel_link"]:
            telefone_clicavel = True
        elif tel_texto and telefone_clicavel is None:
            telefone_clicavel = False
    return achou, telefone_clicavel


def _estado_da_pagina(http_status, titulo, texto, texto_chars, regras=None):
    """(status, o que casou). anti_bot antes de http_erro: desafio vem com 403/503 e nao e "site fora"."""
    casou = detectar_antibot(titulo, texto, texto_chars, regras)
    if casou:
        return STATUS_ANTI_BOT, casou
    if http_status is not None and http_status >= 400:
        return STATUS_HTTP_ERRO, None
    return STATUS_OK, None


def resumir_estado_do_lead(por_dispositivo):
    """(estado, motivo) do lead a partir dos resultados por dispositivo. Precedencia: anti_bot >
    http_erro > erro de rede > ok. So "medido" quando TODOS os dispositivos ficaram ok: um site que
    nao foi visto por inteiro nunca vira "medido e sem problema"."""
    itens = list(por_dispositivo.items())
    for _, r in itens:
        if r.get("status") == STATUS_ANTI_BOT:
            return STATUS_ANTI_BOT, f"anti_bot:{r.get('antibot_casou')}"
    for _, r in itens:
        if r.get("status") == STATUS_HTTP_ERRO:
            return STATUS_HTTP_ERRO, f"http_erro:{r.get('http_status')}"
    for _, r in itens:
        if r.get("status") == STATUS_ERRO:
            return ESTADO_NAO_VERIFICADO, f"erro:{r.get('erro_tipo') or 'desconhecido'}"
    if itens and all(r.get("status") == STATUS_OK for _, r in itens):
        return ESTADO_MEDIDO, None
    return ESTADO_NAO_VERIFICADO, "sem_resultado"


# --- Textos visiveis: limites (Python, testavel sem navegador) -----------------------------------

def _limitar_textos(brutos, max_itens=MAX_TEXTOS, max_chars=MAX_CHARS_TEXTO):
    vistos = []
    for bruto in brutos or []:
        texto = " ".join(str(bruto or "").split())[:max_chars].strip()
        if texto and texto not in vistos:
            vistos.append(texto)
            if len(vistos) >= max_itens:
                break
    return vistos


def _agora_utc():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _classificar_erro(mensagem: str) -> str:
    for tipo, padroes in ERRO_PADROES.items():
        if any(p in mensagem for p in padroes):
            return tipo
    return "erro_desconhecido"


def _tem_cta_keyword(texto: Optional[str]) -> bool:
    if not texto:
        return False
    return any(kw in texto for kw in CTA_KEYWORDS_ES)


# --- Extracao no navegador -----------------------------------------------------------------------

def _extrair_sinais(page) -> dict:
    """Roda no contexto da pagina ja carregada. Presenca estrutural, sem julgamento. Copiado de
    fetch_tecnico.py:147-191, mais titulo, texto_chars, os textos visiveis de botoes e links de
    acao, e (C4b) texto_completo/ancoras_visiveis para o caminho de contato. O teto de
    texto_completo (20000) e literal aqui -- deve bater com MAX_CHARS_TEXTO_COMPLETO."""
    return page.evaluate(
        """
        () => {
            const html = document.documentElement;
            const bodyTextBruto = document.body ? document.body.innerText : "";
            const bodyText = bodyTextBruto.toLowerCase();
            const forms = document.querySelectorAll("form");
            const telLinks = document.querySelectorAll('a[href^="tel:"]');
            const waLinks = document.querySelectorAll(
                'a[href*="wa.me"], a[href*="api.whatsapp.com"], a[href*="whatsapp.com/send"]'
            );
            const emailLinks = document.querySelectorAll('a[href^="mailto:"]');
            const imgs = Array.from(document.querySelectorAll("img"));
            const imagensQuebradas = imgs.filter(
                img => img.complete && img.naturalWidth === 0
            ).length;

            const origin = window.location.origin;
            const linksInternos = Array.from(document.querySelectorAll("a[href]"))
                .map(a => a.href)
                .filter(href => {
                    try {
                        const u = new URL(href);
                        return u.origin === origin && !href.startsWith("javascript:") && !href.startsWith("#");
                    } catch (e) { return false; }
                });
            const linksInternosUnicos = Array.from(new Set(linksInternos));

            const visivel = el => {
                const r = el.getBoundingClientRect();
                const s = window.getComputedStyle(el);
                return r.width > 0 && r.height > 0 && s.display !== "none"
                    && s.visibility !== "hidden" && s.opacity !== "0";
            };
            const textoDe = el => (el.innerText || el.value || el.getAttribute("aria-label")
                                   || el.getAttribute("title") || "");
            const coletar = seletor => Array.from(document.querySelectorAll(seletor))
                .filter(visivel).map(textoDe).slice(0, 200);
            const ancorasVisiveis = Array.from(document.querySelectorAll("a[href]"))
                .filter(visivel)
                .map(a => ({ href: a.href, texto: textoDe(a) }))
                .slice(0, 150);

            return {
                html_lang: html.getAttribute("lang"),
                titulo: document.title || "",
                texto_completo: bodyTextBruto.slice(0, 20000),
                ancoras_visiveis: ancorasVisiveis,
                has_form: forms.length > 0,
                form_count: forms.length,
                form_action: forms.length > 0 ? (forms[0].getAttribute("action") || null) : null,
                has_tel_link: telLinks.length > 0,
                has_whatsapp_link: waLinks.length > 0,
                has_email_link: emailLinks.length > 0,
                body_text_sample: bodyText.slice(0, 5000),
                texto_chars: bodyTextBruto.length,
                imagens_total: imgs.length,
                imagens_quebradas: imagensQuebradas,
                links_internos: linksInternosUnicos,
                botoes_brutos: coletar(
                    'button, [role="button"], input[type="submit"], input[type="button"], '
                    + 'a[role="button"], a[class*="btn" i], a[class*="button" i], a[class*="cta" i]'
                ),
                links_acao_brutos: coletar(
                    'a[href^="tel:"], a[href^="mailto:"], a[href*="wa.me"], '
                    + 'a[href*="api.whatsapp.com"], a[href*="whatsapp.com/send"]'
                ),
            };
        }
        """
    )


def _verificar_links_internos(page, links: list) -> tuple:
    """Confere status HTTP dos links internos da homepage (copiado de fetch_tecnico.py:200-216).
    Escopo limitado por design (so homepage, teto MAX_LINKS_INTERNOS_VERIFICADOS) — nao e crawl."""
    amostra = links[:MAX_LINKS_INTERNOS_VERIFICADOS]
    quebrados = []
    for link in amostra:
        try:
            resp = page.request.head(link, timeout=LINK_CHECK_TIMEOUT_MS)
            if resp.status >= 400:
                # Alguns servidores nao implementam HEAD corretamente — confirma com GET antes de acusar
                resp_get = page.request.get(link, timeout=LINK_CHECK_TIMEOUT_MS)
                if resp_get.status >= 400:
                    quebrados.append({"url": link, "status": resp_get.status})
        except Exception as e:
            quebrados.append({"url": link, "status": None, "erro": str(e)[:120]})
    return len(amostra), quebrados


def _testar_menu_hamburguer(page) -> str:
    """Best-effort (copiado de fetch_tecnico.py:219-258). 'abre' | 'nao_abre' | 'nao_testavel'."""
    for seletor in HAMBURGER_SELECTORS:
        try:
            locator = page.locator(seletor).first
            if locator.count() == 0 or not locator.is_visible():
                continue

            estado_antes = page.evaluate(
                """
                () => {
                    const visiveis = Array.from(document.querySelectorAll('nav a, header a, [role="navigation"] a'))
                        .filter(a => a.offsetParent !== null).length;
                    const expandido = document.querySelector('[aria-expanded="true"]') !== null;
                    return { visiveis, expandido };
                }
                """
            )
            locator.click(timeout=3000)
            page.wait_for_timeout(400)
            estado_depois = page.evaluate(
                """
                () => {
                    const visiveis = Array.from(document.querySelectorAll('nav a, header a, [role="navigation"] a'))
                        .filter(a => a.offsetParent !== null).length;
                    const expandido = document.querySelector('[aria-expanded="true"]') !== null;
                    return { visiveis, expandido };
                }
                """
            )
            mudou = (
                estado_depois["visiveis"] > estado_antes["visiveis"]
                or (estado_depois["expandido"] and not estado_antes["expandido"])
            )
            return "abre" if mudou else "nao_abre"
        except Exception:
            continue
    return "nao_testavel"


# --- Resultado -----------------------------------------------------------------------------------

@dataclass
class ResultadoDispositivo:
    status: str = STATUS_ERRO  # "ok" | "http_erro" | "anti_bot" | "erro"
    http_status: Optional[int] = None
    https: Optional[bool] = None
    url_final: Optional[str] = None
    redirecionado: Optional[bool] = None
    tempo_carregamento_ms: Optional[float] = None
    coletado_em: Optional[str] = None            # novo: UTC, por dispositivo
    titulo_pagina: Optional[str] = None          # novo
    texto_visivel_chars: Optional[int] = None    # novo
    texto_visivel_normalizado: Optional[str] = None  # Etapa 3a (24/09/2026): innerText, espaços colapsados
    antibot_casou: Optional[str] = None          # novo: "titulo:..." | "frase:..."
    html_lang: Optional[str] = None
    has_form: Optional[bool] = None
    form_action: Optional[str] = None
    has_tel_link: Optional[bool] = None
    has_whatsapp_link: Optional[bool] = None
    has_email_link: Optional[bool] = None
    has_cta_keyword: Optional[bool] = None
    botoes_textos: Optional[list] = None         # novo: None = nao medido; [] = medido, nenhum
    links_acao_textos: Optional[list] = None     # novo
    contato_origens: list = field(default_factory=list)  # C4b: subset de ORDEM_ORIGENS; [] = sem contato visivel
    contato_visivel: Optional[bool] = None       # C4b: None = nao medido (fora de STATUS_OK); senao bool(contato_origens)
    telefone_clicavel: Optional[bool] = None     # C4b: None = telefone nao encontrado; True/False caso encontrado
    screenshot_ref: Optional[str] = None
    console_erros_count: Optional[int] = None
    console_erros_amostra: list = field(default_factory=list)
    js_excecoes_count: Optional[int] = None
    imagens_total_count: Optional[int] = None
    imagens_quebradas_count: Optional[int] = None
    links_internos_verificados_count: Optional[int] = None
    links_internos_quebrados_count: Optional[int] = None
    links_internos_quebrados_amostra: list = field(default_factory=list)
    menu_hamburguer: Optional[str] = None  # "abre" | "nao_abre" | "nao_testavel" | "nao_aplicavel"
    erro_tipo: Optional[str] = None
    erro_detalhe: Optional[str] = None
    tentativas: int = 0


def _normalizar_espacos(texto: str) -> str:
    """Colapsa qualquer sequência de espaço/tab/quebra de linha num único
    espaço e tira as pontas. Nunca HTML -- entrada já é `innerText`
    (`sinais["texto_completo"]`, JS), não markup."""
    return re.sub(r"\s+", " ", texto or "").strip()


def _preencher_sinais(resultado, sinais, n_verificados, links_quebrados, menu_status, console_erros, js_excecoes):
    """So para status 'ok': nos outros estados os sinais ficam None (a pagina nao e o site)."""
    resultado.html_lang = sinais["html_lang"]
    resultado.texto_visivel_normalizado = _normalizar_espacos(sinais.get("texto_completo")) or None
    resultado.has_form = sinais["has_form"]
    resultado.form_action = sinais["form_action"]
    resultado.has_tel_link = sinais["has_tel_link"]
    resultado.has_whatsapp_link = sinais["has_whatsapp_link"]
    resultado.has_email_link = sinais["has_email_link"]
    resultado.has_cta_keyword = _tem_cta_keyword(sinais["body_text_sample"])
    resultado.botoes_textos = _limitar_textos(sinais.get("botoes_brutos"))
    resultado.links_acao_textos = _limitar_textos(sinais.get("links_acao_brutos"))
    resultado.console_erros_count = len(console_erros)
    resultado.console_erros_amostra = console_erros[:3]
    resultado.js_excecoes_count = len(js_excecoes)
    resultado.imagens_total_count = sinais["imagens_total"]
    resultado.imagens_quebradas_count = sinais["imagens_quebradas"]
    resultado.links_internos_verificados_count = n_verificados
    resultado.links_internos_quebrados_count = len(links_quebrados)
    resultado.links_internos_quebrados_amostra = links_quebrados[:5]
    resultado.menu_hamburguer = menu_status


def _detectar_caminho_contato(resultado, sinais, page, regras_caminho):
    """So chamada com estado==STATUS_OK. Mutila `resultado` (contato_origens, contato_visivel,
    telefone_clicavel). Ver docstring do modulo, item 6 (C4b)."""
    origens = set()
    if resultado.has_tel_link or resultado.has_whatsapp_link or resultado.has_email_link:
        origens.add(ORIGEM_LINK_INICIAL)
    tel_texto, email_texto = _tem_contato_no_texto(sinais.get("texto_completo"))
    if tel_texto or email_texto:
        origens.add(ORIGEM_TEXTO_INICIAL)
    telefone_clicavel = True if resultado.has_tel_link else (False if tel_texto else None)

    dominio_site = _host(resultado.url_final)
    agendamento_achado, candidatos = _candidatos_de_contato(
        sinais.get("ancoras_visiveis"), dominio_site, regras_caminho)
    if agendamento_achado:
        origens.add(ORIGEM_BOTAO_AGENDAMENTO)

    # So segue link se a pagina inicial NAO tiver contato por link estrutural -- a evidencia mais
    # forte ja existe; seguir mais paginas so custaria tempo sem mudar a conclusao.
    if ORIGEM_LINK_INICIAL not in origens and candidatos:
        achou_subpagina, telefone_clicavel_sub = _seguir_paginas_contato(page, candidatos)
        if achou_subpagina:
            origens.add(ORIGEM_PAGINA_CONTATO)
        if telefone_clicavel_sub is True:
            telefone_clicavel = True
        elif telefone_clicavel_sub is False and telefone_clicavel is None:
            telefone_clicavel = False

    resultado.contato_origens = [o for o in ORDEM_ORIGENS if o in origens]
    resultado.contato_visivel = bool(origens)
    resultado.telefone_clicavel = telefone_clicavel


def _fetch_dispositivo(
    playwright, url: str, dispositivo: str, lead_id: str, screenshot_dir: Path, regras_antibot=None,
    regras_caminho_contato=None,
) -> ResultadoDispositivo:
    _, PlaywrightError, PlaywrightTimeout = _api_playwright()
    regras = regras_antibot or carregar_antibot()  # falha alto ANTES de abrir navegador
    regras_caminho = regras_caminho_contato or carregar_caminho_contato()  # idem
    config = DISPOSITIVOS[dispositivo]
    resultado = ResultadoDispositivo()

    for tentativa in range(1, MAX_TENTATIVAS + 1):
        resultado.tentativas = tentativa
        estrategia = ESTRATEGIAS_ESPERA[min(tentativa - 1, len(ESTRATEGIAS_ESPERA) - 1)]
        browser = None
        try:
            browser = playwright.chromium.launch(headless=True)
            context = browser.new_context(
                viewport=config["viewport"],
                user_agent=config["user_agent"],
                is_mobile=config["is_mobile"],
                locale="es-ES",
            )
            page = context.new_page()

            console_erros = []
            js_excecoes = []
            page.on("console", lambda msg: console_erros.append(msg.text[:200]) if msg.type == "error" else None)
            page.on("pageerror", lambda exc: js_excecoes.append(str(exc)[:200]))

            inicio = time.monotonic()
            response = page.goto(url, timeout=NAVEGACAO_TIMEOUT_MS, wait_until=estrategia)
            page.wait_for_timeout(500)  # margem para JS tardio
            tempo_ms = (time.monotonic() - inicio) * 1000

            # CAPTURA LIMPA: antes de extrair, de verificar links e de clicar no menu (diferenca 5).
            nome_arquivo = re.sub(r"[^\w.-]", "_", lead_id)
            screenshot_path = screenshot_dir / f"{nome_arquivo}_{dispositivo}.png"
            page.screenshot(path=str(screenshot_path), full_page=False)

            sinais = _extrair_sinais(page)
            http_status = response.status if response else None
            estado, casou = _estado_da_pagina(
                http_status, sinais["titulo"], sinais["body_text_sample"], sinais["texto_chars"], regras)

            n_verificados, links_quebrados, menu_status = 0, [], None
            if estado == STATUS_OK:
                n_verificados, links_quebrados = _verificar_links_internos(page, sinais["links_internos"])
                menu_status = _testar_menu_hamburguer(page) if dispositivo == "mobile" else "nao_aplicavel"

            resultado.status = estado
            resultado.http_status = http_status
            resultado.url_final = page.url
            resultado.https = page.url.startswith("https://")
            resultado.redirecionado = page.url.rstrip("/") != url.rstrip("/")
            resultado.tempo_carregamento_ms = round(tempo_ms, 1)
            resultado.titulo_pagina = " ".join((sinais["titulo"] or "").split())[:MAX_CHARS_TITULO]
            resultado.texto_visivel_chars = sinais["texto_chars"]
            resultado.antibot_casou = casou
            resultado.screenshot_ref = str(screenshot_path)
            resultado.erro_tipo = None
            resultado.erro_detalhe = None
            if estado == STATUS_OK:
                _preencher_sinais(resultado, sinais, n_verificados, links_quebrados, menu_status,
                                  console_erros, js_excecoes)
                # Ultima interacao na pagina (C4b): pode navegar para ate 2 paginas de contato. Depois
                # disso resultado.url_final/https/etc JA estao fixados acima -- nao mudam.
                _detectar_caminho_contato(resultado, sinais, page, regras_caminho)
            resultado.coletado_em = _agora_utc()

            context.close()
            browser.close()

            # Falha HTTP retentável (404/5xx) -- diferente da exceção (timeout/DNS/etc, já
            # tratada nos excepts abaixo), o goto() TEVE SUCESSO aqui, só a resposta é ruim.
            # Sem isto, 404/5xx nunca repetiam -- achado real (FISIOFICTICIA, 24/09/2026):
            # exceção já repetia, resposta HTTP ruim não. 403/anti_bot nunca entram aqui
            # (indica_falha_dispositivo devolve False para eles).
            if indica_falha_dispositivo(http_status, None) and tentativa < MAX_TENTATIVAS:
                time.sleep(ESPERA_ENTRE_TENTATIVAS_S)
                continue
            return resultado

        except PlaywrightTimeout as e:
            resultado.status = STATUS_ERRO
            resultado.erro_tipo = "timeout"
            resultado.erro_detalhe = str(e)[:200]
        except PlaywrightError as e:
            resultado.status = STATUS_ERRO
            msg = str(e)
            resultado.erro_tipo = _classificar_erro(msg)
            resultado.erro_detalhe = msg[:200]
        except Exception as e:
            resultado.status = STATUS_ERRO
            resultado.erro_tipo = "erro_desconhecido"
            resultado.erro_detalhe = str(e)[:200]
        finally:
            if browser:
                try:
                    browser.close()
                except Exception:
                    pass

        if tentativa < MAX_TENTATIVAS:
            time.sleep(ESPERA_ENTRE_TENTATIVAS_S)

    resultado.coletado_em = _agora_utc()
    return resultado


def processar_lead(playwright, lead_id: str, website: str, screenshot_dir: Path, regras_antibot=None,
                    regras_caminho_contato=None) -> dict:
    resultados = {}
    for dispositivo in DISPOSITIVOS:
        resultado = _fetch_dispositivo(playwright, website, dispositivo, lead_id, screenshot_dir,
                                        regras_antibot, regras_caminho_contato)
        resultados[dispositivo] = asdict(resultado)

    return {
        "lead_id": lead_id,
        "website": website,
        "gerado_em": _agora_utc(),
        "por_dispositivo": resultados,
    }
