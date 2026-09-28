"""PageSpeed Insights (PSI) -- a ÚNICA dependência externa opcional do sistema. É o que torna
o "$0 de custo, sempre" do SISTEMA.md desatualizado: com PSI_ENABLED ligado, passa a
"≈$0; PSI opcional em free-tier do Google".

Degrada graciosamente (mesmo padrão do antigo validators/humanization.py, que tratava a skill
externa como opcional): sem PSI_ENABLED, ou sem PSI_API_KEY, toda medição vira NAO_VERIFICADO
e o pipeline segue 100% offline. NUNCA lança -- falha de rede/quota/resposta inesperada vira
NAO_VERIFICADO com o motivo registrado.

Fase própria (fase_psi em main.py), DEPOIS de fase_wave2 -- de propósito fora de
website_analyzer/wave2_scoring, que continuam puros, offline e $0. O performance_score NÃO
entra no priority_score da Onda 2: vai cru pro output e o Sistema 2 decide o peso, usando
'medido_em' pra decidir se revalida antes de usar.
"""
import json
import os
import socket
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

PSI_ENDPOINT = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"
# 30s é curto demais: um Lighthouse "a frio" (URL ainda não cacheada pelo Google) passa disso
# com frequência -- medido em validação real: 17-29s pros sites mais rápidos, e mais alguns
# segundos de margem pros lentos. 60s é a folga usual recomendada pra rodadas de PSI a frio.
DEFAULT_TIMEOUT_SECONDS = 60
DEFAULT_STRATEGY = "mobile"

# Retry por falha transiente. Base empírica (não hipótese): medindo os MESMOS 10 sites duas
# vezes, um deles falhou com HTTP 500 isolado e passou emendado, e outro fez o inverso -- mesma
# URL, resultado diferente por tentativa, não por configuração. Já foram testadas e descartadas
# as duas explicações estruturais: teto de espera (nenhuma das 10 chamadas passou de 53.2s, com
# teto de 120s) e falta de espaçamento (emendado deu a mesma taxa que espaçado). Sobra falha
# transiente por-chamada, que é o que retry resolve diretamente.
DEFAULT_TENTATIVAS = 2
# Pequeno, só pra não repetir no mesmo instante ruim -- não é backoff de rate-limit (o teste
# emendado mostrou que espaçamento não muda a taxa de falha).
DELAY_ENTRE_TENTATIVAS_SEGUNDOS = 3

NAO_VERIFICADO = "NAO_VERIFICADO"
CONFIRMADO_PRESENTE = "CONFIRMADO_PRESENTE"

_LIGADO = {"1", "true", "yes", "on"}


def _now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def esta_habilitado():
    return os.environ.get("PSI_ENABLED", "").strip().lower() in _LIGADO


def _api_key():
    return (os.environ.get("PSI_API_KEY") or "").strip() or None


def _nao_verificado(motivo, tentativas=0, falha_transiente=False):
    return {
        "estado": NAO_VERIFICADO,
        "motivo": motivo,
        "medido_em": _now_iso(),
        "estrategia": None,
        "performance_score": None,
        "lcp_ms": None,
        "cls": None,
        "tbt_ms": None,
        "origem": None,
        # 0 = nenhuma chamada chegou a sair (desabilitado / sem chave / sem URL).
        "tentativas": tentativas,
        # Quem decide se a falha vale nova tentativa é aqui, onde a exceção é conhecida --
        # gravado no resultado pra que o orquestrador possa reagendar o lead numa rodada futura
        # sem ter que adivinhar o tipo de falha fazendo parsing do texto de 'motivo'.
        "falha_transiente": falha_transiente,
    }


def _audit_ms(audits, chave):
    v = (audits.get(chave) or {}).get("numericValue")
    return round(v) if isinstance(v, (int, float)) else None


def _audit_num(audits, chave):
    v = (audits.get(chave) or {}).get("numericValue")
    return round(v, 3) if isinstance(v, (int, float)) else None


def _uma_tentativa(url, strategy, timeout, chave):
    """Uma única chamada à API. Devolve (resultado, vale_repetir).

    'vale_repetir' separa falha transiente de falha determinística -- repetir um 4xx só gastaria
    outra chamada pro mesmo erro (URL inválida, chave ruim, quota do dia estourada), e no caso de
    quota estourada ainda pioraria a situação."""
    params = urllib.parse.urlencode({
        "url": url, "key": chave, "strategy": strategy, "category": "performance",
    })
    try:
        req = urllib.request.Request(f"{PSI_ENDPOINT}?{params}", headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            dados = json.loads(resp.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as e:
        # 5xx = instabilidade do lado do Google; 429 = excesso momentâneo. Ambos transientes.
        transiente = e.code >= 500 or e.code == 429
        return _nao_verificado(f"falha na chamada PSI: {e}", falha_transiente=transiente), transiente
    except (urllib.error.URLError, socket.timeout, TimeoutError, ssl.SSLError, ValueError, OSError) as e:
        # Timeout, DNS, conexão derrubada, corpo truncado -- transientes por natureza.
        return _nao_verificado(f"falha na chamada PSI: {e}", falha_transiente=True), True

    try:
        lighthouse = dados["lighthouseResult"]
        audits = lighthouse.get("audits") or {}
        perf = (lighthouse.get("categories") or {}).get("performance", {}).get("score")
        experiencia = dados.get("loadingExperience") or {}
        return {
            "estado": CONFIRMADO_PRESENTE,
            "motivo": None,
            "medido_em": _now_iso(),
            "estrategia": strategy,
            "performance_score": round(perf * 100) if isinstance(perf, (int, float)) else None,
            "lcp_ms": _audit_ms(audits, "largest-contentful-paint"),
            "cls": _audit_num(audits, "cumulative-layout-shift"),
            "tbt_ms": _audit_ms(audits, "total-blocking-time"),
            "origem": "field" if experiencia.get("metrics") else "lab",
            "falha_transiente": False,
        }, False
    except (KeyError, TypeError) as e:
        # 200 com formato inesperado não é instabilidade: repetir tende a dar o mesmo.
        return _nao_verificado(f"resposta PSI inesperada: {e}"), False


def medir(url, strategy=DEFAULT_STRATEGY, timeout=DEFAULT_TIMEOUT_SECONDS,
          tentativas=DEFAULT_TENTATIVAS, delay_entre_tentativas=None):
    """Nunca lança. Sem habilitar / sem chave / sem URL -> NAO_VERIFICADO. Sucesso ->
    CONFIRMADO_PRESENTE + métricas (performance_score 0-100, LCP/CLS/TBT).

    Repete só falha transiente (ver _uma_tentativa), até 'tentativas' no total. O campo
    'tentativas' no resultado registra quantas chamadas foram gastas -- é o que permite medir
    depois se o retry está resolvendo de fato ou só mascarando falha sistemática."""
    if not esta_habilitado():
        return _nao_verificado("PSI desabilitado (PSI_ENABLED)")
    chave = _api_key()
    if not chave:
        return _nao_verificado("PSI_API_KEY não configurada")
    if not url:
        return _nao_verificado("lead sem URL de site")

    if delay_entre_tentativas is None:
        delay_entre_tentativas = DELAY_ENTRE_TENTATIVAS_SEGUNDOS
    total = max(1, tentativas)

    for tentativa in range(1, total + 1):
        resultado, vale_repetir = _uma_tentativa(url, strategy, timeout, chave)
        resultado["tentativas"] = tentativa
        if resultado["estado"] == CONFIRMADO_PRESENTE or not vale_repetir:
            return resultado
        if tentativa < total:
            time.sleep(delay_entre_tentativas)
    return resultado
