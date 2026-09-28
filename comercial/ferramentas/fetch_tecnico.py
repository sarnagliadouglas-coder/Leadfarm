"""
fetch_tecnico.py — Camada B (Verificação) do Agente 1 (COMERCIAL)

Faz verificação comportamental do site do lead com JavaScript renderizado
(Playwright), separado por dispositivo (mobile / desktop). Responde sempre
"funciona ou não funciona" — nunca "quão rápido". Medição de performance
(PSI) não é responsabilidade do COMERCIAL — decisão D11: chega pronta em
`lead["psi"]` do contrato, medida pelo QUALIFICADOR. Este script não
interpreta nada — apenas observa e registra fatos crus, que alimentam o
Agente 1 como `fatos_tecnicos_pre_computados` (ver agents/01_investigacao/agent.md).

Por que existe, e por que não repete o QUALIFICADOR nem o Playwright MCP do A1:
- O fetch do QUALIFICADOR (que produz `evidencias_qualificador.sinais_site`
  no contrato — ver EQC\\contracts\\CONTRACT.md) não renderiza JavaScript —
  um CTA ou formulário montado no cliente dá falso negativo lá. O contrato
  atual entrega esses sinais crus diretamente ao COMERCIAL (sem o filtro de
  planilha que existia no pipeline legado), mas eles continuam sendo dado
  sem JS renderizado — não substituem esta camada.
- Tudo que é checagem estrutural determinística (presença de link, contagem
  de erro, clique num seletor conhecido) fica aqui, em Python — não no
  Playwright MCP que o Agente 1 (LLM) usa. O MCP fica reservado para o que
  exige leitura ou julgamento (coerência de conteúdo, perfis sociais
  "vivos"). Ver decisão registrada em agents/01_investigacao/agent.md.

LIMITE OBRIGATÓRIO: este script nunca submete formulários. Verifica apenas
estrutura (campos, action, validação client-side). Enviar dados de teste
geraria um contato falso na caixa de entrada de um negócio que ainda não
foi abordado comercialmente.

Uso:
    python fetch_tecnico.py --output fatos_tecnicos/
        Roda o lote inteiro (todos os leads COMPLETO_COM_SITE) — mais
        recente de COMERCIAL_INPUT_DIR (ver contrato_loader.py).
    python fetch_tecnico.py --input leads_qualificados_20260906-201042_v1.1.0.json --output fatos_tecnicos/
        Usa um arquivo de lote explícito do contrato (útil para teste/reprocesso).
    python fetch_tecnico.py --place-id ChIJ... --output fatos_tecnicos/
        Roda só o lead indicado (D5 — o A1 decide quando chamar esta
        ferramenta, por lead, não em lote; é o modo usado durante a
        investigação de um lead específico).

A entrada é sempre um lote no formato do contrato QUALIFICADOR -> COMERCIAL
(ver EQC\\contracts\\CONTRACT.md), lido exclusivamente via
`ferramentas/contrato_loader.py` — nunca lido diretamente deste script.
`lead_id` internamente é o `place_id` do contrato. Leads da trilha
COMPLETO_SEM_SITE (sem `presenca_digital.website_url` confirmado) são
pulados — não é erro, é uma trilha válida — e contados separadamente na
saída, distinguindo CONFIRMADO_AUSENTE ("QUALIFICADOR checou, não tem site")
de NAO_VERIFICADO ("QUALIFICADOR não checou").

Saída: um arquivo <place_id>.json por lead processado em --output, mais
screenshots em --output/screenshots/.

Requisitos:
    pip install -r requirements.txt
    playwright install chromium
"""

import argparse
import json
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import contrato_loader

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PlaywrightTimeout
from playwright.sync_api import sync_playwright

# --- Parâmetros operacionais (espelhados em config/config.md) ---
NAVEGACAO_TIMEOUT_MS = 15_000
MAX_TENTATIVAS = 2
ESPERA_ENTRE_TENTATIVAS_S = 3
# Estratégia de espera por tentativa: a primeira é mais rigorosa (networkidle),
# a segunda mais tolerante (load) — sites com beacons/chat widgets nunca
# ficam "idle" e travariam sempre na mesma estratégia.
ESTRATEGIAS_ESPERA = ["networkidle", "load"]

# Verificação de links internos: limitada por design (ver seção 8 da decisão
# arquitetural — nada de crawl completo nesta etapa). Cobre só a homepage.
MAX_LINKS_INTERNOS_VERIFICADOS = 15
LINK_CHECK_TIMEOUT_MS = 5_000

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

# CTA em castellano da Espanha — mercado real da Onda 2 (ver
# referencias/insumos_sistema_qualificacao.md, seção "Idioma e mercado").
# Sinal estrutural cru: só marca presença de palavra-chave, não avalia
# se o CTA faz sentido — isso é julgamento do Agente 1.
CTA_KEYWORDS_ES = [
    "reservar", "reserva tu", "agendar", "pedir cita", "pide cita",
    "solicitar", "solicita", "contactar", "contáctanos", "contacta",
    "llamar", "llámanos", "escríbenos", "presupuesto", "consulta gratuita",
]

# Seletores comuns de botão de menu hambúrguer. Heurístico por natureza —
# cobre padrões frequentes (aria-label, classes convencionais, Bootstrap),
# não garante achar todo site. Quando nenhum seletor casa, o resultado é
# "nao_testavel", nunca "nao_abre" — ausência de seletor conhecido não é
# prova de que o menu não funciona.
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


def _classificar_erro(mensagem: str) -> str:
    for tipo, padroes in ERRO_PADROES.items():
        if any(p in mensagem for p in padroes):
            return tipo
    return "erro_desconhecido"


def _extrair_sinais(page) -> dict:
    """Roda no contexto da página já carregada. Presença estrutural, sem julgamento."""
    return page.evaluate(
        """
        () => {
            const html = document.documentElement;
            const bodyText = (document.body ? document.body.innerText : "").toLowerCase();
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

            return {
                html_lang: html.getAttribute("lang"),
                has_form: forms.length > 0,
                form_count: forms.length,
                form_action: forms.length > 0 ? (forms[0].getAttribute("action") || null) : null,
                has_tel_link: telLinks.length > 0,
                has_whatsapp_link: waLinks.length > 0,
                has_email_link: emailLinks.length > 0,
                body_text_sample: bodyText.slice(0, 5000),
                imagens_total: imgs.length,
                imagens_quebradas: imagensQuebradas,
                links_internos: linksInternosUnicos,
            };
        }
        """
    )


def _tem_cta_keyword(texto: Optional[str]) -> bool:
    if not texto:
        return False
    return any(kw in texto for kw in CTA_KEYWORDS_ES)


def _verificar_links_internos(page, links: list) -> tuple:
    """Confere status HTTP dos links internos da homepage. Escopo limitado
    por design (só homepage, teto de MAX_LINKS_INTERNOS_VERIFICADOS) — não
    é um crawl do site."""
    amostra = links[:MAX_LINKS_INTERNOS_VERIFICADOS]
    quebrados = []
    for link in amostra:
        try:
            resp = page.request.head(link, timeout=LINK_CHECK_TIMEOUT_MS)
            if resp.status >= 400:
                # Alguns servidores não implementam HEAD corretamente — confirma com GET antes de acusar
                resp_get = page.request.get(link, timeout=LINK_CHECK_TIMEOUT_MS)
                if resp_get.status >= 400:
                    quebrados.append({"url": link, "status": resp_get.status})
        except Exception as e:
            quebrados.append({"url": link, "status": None, "erro": str(e)[:120]})
    return len(amostra), quebrados


def _testar_menu_hamburguer(page) -> str:
    """Best-effort. Retorna 'abre' | 'nao_abre' | 'nao_testavel'.
    'nao_testavel' quando nenhum seletor conhecido casa — ausência de
    seletor não é prova de ausência de menu funcional."""
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


@dataclass
class ResultadoDispositivo:
    status: str = "erro"  # "ok" | "erro"
    http_status: Optional[int] = None
    https: Optional[bool] = None
    url_final: Optional[str] = None
    redirecionado: Optional[bool] = None
    tempo_carregamento_ms: Optional[float] = None
    html_lang: Optional[str] = None
    has_form: Optional[bool] = None
    form_action: Optional[str] = None
    has_tel_link: Optional[bool] = None
    has_whatsapp_link: Optional[bool] = None
    has_email_link: Optional[bool] = None
    has_cta_keyword: Optional[bool] = None
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


def _fetch_dispositivo(
    playwright, url: str, dispositivo: str, lead_id: str, screenshot_dir: Path
) -> ResultadoDispositivo:
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

            sinais = _extrair_sinais(page)

            n_verificados, links_quebrados = _verificar_links_internos(page, sinais["links_internos"])

            menu_status = _testar_menu_hamburguer(page) if dispositivo == "mobile" else "nao_aplicavel"

            screenshot_path = screenshot_dir / f"{lead_id}_{dispositivo}.png"
            page.screenshot(path=str(screenshot_path), full_page=False)

            resultado.status = "ok"
            resultado.http_status = response.status if response else None
            resultado.url_final = page.url
            resultado.https = page.url.startswith("https://")
            resultado.redirecionado = page.url.rstrip("/") != url.rstrip("/")
            resultado.tempo_carregamento_ms = round(tempo_ms, 1)
            resultado.html_lang = sinais["html_lang"]
            resultado.has_form = sinais["has_form"]
            resultado.form_action = sinais["form_action"]
            resultado.has_tel_link = sinais["has_tel_link"]
            resultado.has_whatsapp_link = sinais["has_whatsapp_link"]
            resultado.has_email_link = sinais["has_email_link"]
            resultado.has_cta_keyword = _tem_cta_keyword(sinais["body_text_sample"])
            resultado.screenshot_ref = str(screenshot_path)
            resultado.console_erros_count = len(console_erros)
            resultado.console_erros_amostra = console_erros[:3]
            resultado.js_excecoes_count = len(js_excecoes)
            resultado.imagens_total_count = sinais["imagens_total"]
            resultado.imagens_quebradas_count = sinais["imagens_quebradas"]
            resultado.links_internos_verificados_count = n_verificados
            resultado.links_internos_quebrados_count = len(links_quebrados)
            resultado.links_internos_quebrados_amostra = links_quebrados[:5]
            resultado.menu_hamburguer = menu_status
            resultado.erro_tipo = None
            resultado.erro_detalhe = None

            context.close()
            browser.close()
            return resultado

        except PlaywrightTimeout as e:
            resultado.status = "erro"
            resultado.erro_tipo = "timeout"
            resultado.erro_detalhe = str(e)[:200]
        except PlaywrightError as e:
            resultado.status = "erro"
            msg = str(e)
            resultado.erro_tipo = _classificar_erro(msg)
            resultado.erro_detalhe = msg[:200]
        except Exception as e:
            resultado.status = "erro"
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

    return resultado


def processar_lead(playwright, lead_id: str, website: str, screenshot_dir: Path) -> dict:
    resultados = {}
    for dispositivo in DISPOSITIVOS:
        resultado = _fetch_dispositivo(playwright, website, dispositivo, lead_id, screenshot_dir)
        resultados[dispositivo] = asdict(resultado)

    return {
        "lead_id": lead_id,
        "website": website,
        "gerado_em": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "por_dispositivo": resultados,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--input", type=Path, default=None,
        help="Arquivo de lote do contrato (leads_qualificados_*.json). "
             "Se omitido, usa o mais recente de COMERCIAL_INPUT_DIR (ver contrato_loader.py).",
    )
    parser.add_argument(
        "--schema", type=Path, default=None,
        help="Schema do contrato. Se omitido, usa COMERCIAL_CONTRACT_SCHEMA ou o caminho padrão.",
    )
    parser.add_argument(
        "--place-id", type=str, default=None,
        help="Roda só o lead com este place_id, em vez do lote inteiro (D5 — "
             "invocação por lead). Erro alto se o place_id não existir no lote "
             "ou não estiver na trilha COMPLETO_COM_SITE.",
    )
    parser.add_argument("--output", required=True, type=Path, help="Diretório de saída para fatos_tecnicos_pre_computados")
    args = parser.parse_args()

    args.output.mkdir(parents=True, exist_ok=True)
    screenshot_dir = args.output / "screenshots"
    screenshot_dir.mkdir(exist_ok=True)

    lote = contrato_loader.carregar_lote(caminho=args.input, schema=args.schema)
    print(f"[fetch_tecnico] lote {lote.origem.name} — {len(lote)} lead(s) no contrato")

    leads_a_processar = lote.leads
    if args.place_id is not None:
        leads_a_processar = [lead for lead in lote.leads if lead["place_id"] == args.place_id]
        if not leads_a_processar:
            print(
                f"[fetch_tecnico] ERRO: place_id {args.place_id!r} não encontrado em {lote.origem.name}",
                file=sys.stderr,
            )
            sys.exit(1)
        print(f"[fetch_tecnico] filtrado para place_id={args.place_id} (1 de {len(lote)} leads do lote)")

    processados = 0
    sem_place_id = 0
    sem_site_confirmado_ausente = 0
    sem_site_nao_verificado = 0

    with sync_playwright() as playwright:
        for i, lead in enumerate(leads_a_processar, 1):
            lead_id = lead["place_id"]
            if lead_id is None:
                # Não inventamos um id substituto — ver relatório de
                # reconciliação sobre place_id nulo. Reportado como contagem,
                # não silenciado.
                sem_place_id += 1
                print(f"[fetch_tecnico] ({i}/{len(leads_a_processar)}) SEM place_id — pulando", file=sys.stderr)
                continue

            website_campo = lead["presenca_digital"]["website_url"]
            if not website_campo.presente():
                # Lead sem site não é erro — é a trilha COMPLETO_SEM_SITE do
                # contrato. CONFIRMADO_AUSENTE ("QUALIFICADOR checou, não tem
                # site") e NAO_VERIFICADO ("QUALIFICADOR não checou") são
                # contados separadamente — não são a mesma coisa.
                if website_campo.confirmado_ausente():
                    sem_site_confirmado_ausente += 1
                else:
                    sem_site_nao_verificado += 1
                print(
                    f"[fetch_tecnico] ({i}/{len(leads_a_processar)}) {lead_id} — sem site "
                    f"confirmado ({website_campo.estado}, trilha {lead['estagio_analise']}), pulando"
                )
                continue

            website = website_campo.valor_confirmado
            print(f"[fetch_tecnico] ({i}/{len(leads_a_processar)}) {lead_id} — {website}")
            try:
                resultado = processar_lead(playwright, lead_id, website, screenshot_dir)
            except Exception as e:
                print(f"[fetch_tecnico]   ERRO ao processar {lead_id}: {e}", file=sys.stderr)
                continue

            destino = args.output / f"{lead_id}.json"
            destino.write_text(json.dumps(resultado, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"[fetch_tecnico]   -> {destino}")
            processados += 1

    print(
        f"[fetch_tecnico] concluído — {processados} processado(s), "
        f"{sem_site_confirmado_ausente} sem site (confirmado ausente), "
        f"{sem_site_nao_verificado} sem site (não verificado), "
        f"{sem_place_id} sem place_id"
    )


if __name__ == "__main__":
    main()
