import io
import json
import os
import urllib.error

import pytest

import psi_client as psi

_FIXTURE_REAL = os.path.join(os.path.dirname(__file__), "fixtures", "psi_response_real.json")


@pytest.fixture(autouse=True)
def _sem_espera_real(monkeypatch):
    """O delay entre tentativas é real em produção (3s), mas a suíte não pode pagar isso --
    cada teste de falha transiente custaria 3s de relógio à toa."""
    monkeypatch.setattr(psi, "DELAY_ENTRE_TENTATIVAS_SEGUNDOS", 0)


def _payload_ok(score=0.42):
    return {
        "lighthouseResult": {
            "categories": {"performance": {"score": score}},
            "audits": {
                "largest-contentful-paint": {"numericValue": 4123.7},
                "cumulative-layout-shift": {"numericValue": 0.2134},
                "total-blocking-time": {"numericValue": 890.0},
            },
        },
        "loadingExperience": {"metrics": {"LARGEST_CONTENTFUL_PAINT_MS": {}}},
    }


def _resposta(payload):
    return io.BytesIO(json.dumps(payload).encode("utf-8"))


def _http_error(code):
    return urllib.error.HTTPError("https://x.es", code, "erro", {}, None)


def _sequencia(monkeypatch, *acoes):
    """urlopen que consome 'acoes' em ordem: exceção -> levanta; dict -> devolve como resposta.
    Devolve a lista de chamadas registradas, pra contar quantas saíram de fato."""
    chamadas = []

    def _fake(*a, **k):
        acao = acoes[len(chamadas)]
        chamadas.append(acao)
        if isinstance(acao, Exception):
            raise acao
        return _resposta(acao)

    monkeypatch.setattr(psi.urllib.request, "urlopen", _fake)
    return chamadas


def test_desabilitado_por_padrao_retorna_nao_verificado(monkeypatch):
    monkeypatch.delenv("PSI_ENABLED", raising=False)
    r = psi.medir("https://x.es")
    assert r["estado"] == "NAO_VERIFICADO"
    assert "PSI_ENABLED" in r["motivo"]
    assert r["performance_score"] is None


def test_habilitado_sem_chave_e_nao_verificado(monkeypatch):
    monkeypatch.setenv("PSI_ENABLED", "1")
    monkeypatch.delenv("PSI_API_KEY", raising=False)
    r = psi.medir("https://x.es")
    assert r["estado"] == "NAO_VERIFICADO"
    assert "PSI_API_KEY" in r["motivo"]


def test_habilitado_sem_url_e_nao_verificado(monkeypatch):
    monkeypatch.setenv("PSI_ENABLED", "1")
    monkeypatch.setenv("PSI_API_KEY", "k")
    r = psi.medir(None)
    assert r["estado"] == "NAO_VERIFICADO"
    assert "URL" in r["motivo"]


def test_sucesso_extrai_metricas(monkeypatch):
    monkeypatch.setenv("PSI_ENABLED", "1")
    monkeypatch.setenv("PSI_API_KEY", "k")
    payload = {
        "lighthouseResult": {
            "categories": {"performance": {"score": 0.42}},
            "audits": {
                "largest-contentful-paint": {"numericValue": 4123.7},
                "cumulative-layout-shift": {"numericValue": 0.2134},
                "total-blocking-time": {"numericValue": 890.0},
            },
        },
        "loadingExperience": {"metrics": {"LARGEST_CONTENTFUL_PAINT_MS": {}}},
    }
    monkeypatch.setattr(psi.urllib.request, "urlopen",
                        lambda *a, **k: io.BytesIO(json.dumps(payload).encode("utf-8")))
    r = psi.medir("https://x.es")
    assert r["estado"] == "CONFIRMADO_PRESENTE"
    assert r["performance_score"] == 42
    assert r["lcp_ms"] == 4124
    assert r["cls"] == 0.213
    assert r["tbt_ms"] == 890
    assert r["origem"] == "field"


def test_parsing_contra_resposta_real_da_api(monkeypatch):
    """Prova o parsing de lighthouseResult contra uma resposta BRUTA de verdade da API do PSI
    v5 (fixtures/psi_response_real.json, capturada em 2026-09-08, Lighthouse 13.4.1, strategy
    mobile), não só contra o dict fabricado de _payload_ok(). Se o formato v5 mudar de novo --
    caminho de 'categories.performance.score', ids dos audits ('largest-contentful-paint',
    'cumulative-layout-shift', 'total-blocking-time'), 'loadingExperience.metrics' -- este
    teste pega. Continua offline: lê a fixture do disco, não a rede."""
    monkeypatch.setenv("PSI_ENABLED", "1")
    monkeypatch.setenv("PSI_API_KEY", "k")
    with open(_FIXTURE_REAL, "rb") as f:
        bruto = f.read()
    monkeypatch.setattr(psi.urllib.request, "urlopen", lambda *a, **k: io.BytesIO(bruto))

    r = psi.medir("https://www.fisioficticia-once.es/")

    assert r["estado"] == "CONFIRMADO_PRESENTE"
    assert r["estrategia"] == "mobile"
    # Valores conferidos na fixture: perf 0.62, LCP 7786.35ms, CLS 0.00060918, TBT 120ms.
    assert r["performance_score"] == 62
    assert r["lcp_ms"] == 7786
    assert r["cls"] == 0.001
    assert r["tbt_ms"] == 120
    # Esta resposta não traz loadingExperience.metrics (só lab, sem dados de campo).
    assert r["origem"] == "lab"
    assert r["falha_transiente"] is False


def test_falha_de_rede_nunca_lanca(monkeypatch):
    monkeypatch.setenv("PSI_ENABLED", "1")
    monkeypatch.setenv("PSI_API_KEY", "k")

    def _boom(*a, **k):
        raise OSError("conexão recusada")

    monkeypatch.setattr(psi.urllib.request, "urlopen", _boom)
    r = psi.medir("https://x.es")
    assert r["estado"] == "NAO_VERIFICADO"
    assert "falha na chamada PSI" in r["motivo"]


def test_resposta_inesperada_nunca_lanca(monkeypatch):
    monkeypatch.setenv("PSI_ENABLED", "1")
    monkeypatch.setenv("PSI_API_KEY", "k")
    monkeypatch.setattr(psi.urllib.request, "urlopen",
                        lambda *a, **k: io.BytesIO(b'{"unexpected": true}'))
    r = psi.medir("https://x.es")
    assert r["estado"] == "NAO_VERIFICADO"
    assert "inesperada" in r["motivo"]


# --- retry por falha transiente --------------------------------------------------------
# Base empírica: a MESMA URL deu HTTP 500 numa execução e passou na seguinte (e vice-versa,
# noutro site) -- falha por-chamada, não por configuração. Ver comentário em psi_client.

@pytest.fixture
def _habilitado(monkeypatch):
    monkeypatch.setenv("PSI_ENABLED", "1")
    monkeypatch.setenv("PSI_API_KEY", "k")


def test_sucesso_de_primeira_gasta_uma_tentativa_so(_habilitado, monkeypatch):
    chamadas = _sequencia(monkeypatch, _payload_ok())
    r = psi.medir("https://x.es")
    assert r["estado"] == "CONFIRMADO_PRESENTE"
    assert r["tentativas"] == 1
    assert len(chamadas) == 1


def test_http_500_e_retentado_e_segunda_tentativa_vale(_habilitado, monkeypatch):
    chamadas = _sequencia(monkeypatch, _http_error(500), _payload_ok(0.77))
    r = psi.medir("https://x.es")
    assert r["estado"] == "CONFIRMADO_PRESENTE"
    assert r["performance_score"] == 77
    assert r["tentativas"] == 2
    assert len(chamadas) == 2


def test_timeout_e_retentado(_habilitado, monkeypatch):
    chamadas = _sequencia(monkeypatch, TimeoutError("timed out"), _payload_ok())
    r = psi.medir("https://x.es")
    assert r["estado"] == "CONFIRMADO_PRESENTE"
    assert r["tentativas"] == 2
    assert len(chamadas) == 2


def test_duas_falhas_transientes_viram_nao_verificado_com_motivo(_habilitado, monkeypatch):
    chamadas = _sequencia(monkeypatch, _http_error(500), TimeoutError("timed out"))
    r = psi.medir("https://x.es")
    assert r["estado"] == "NAO_VERIFICADO"
    assert "falha na chamada PSI" in r["motivo"]
    assert r["tentativas"] == 2
    assert len(chamadas) == 2


def test_http_400_nao_e_retentado(_habilitado, monkeypatch):
    """URL inválida é determinística -- repetir só gastaria outra chamada pro mesmo erro."""
    chamadas = _sequencia(monkeypatch, _http_error(400), _payload_ok())
    r = psi.medir("https://x.es")
    assert r["estado"] == "NAO_VERIFICADO"
    assert r["tentativas"] == 1
    assert len(chamadas) == 1


def test_http_403_quota_estourada_nao_e_retentado(_habilitado, monkeypatch):
    """Repetir com quota do dia estourada não recupera nada e ainda consome outra chamada."""
    chamadas = _sequencia(monkeypatch, _http_error(403), _payload_ok())
    r = psi.medir("https://x.es")
    assert r["estado"] == "NAO_VERIFICADO"
    assert r["tentativas"] == 1
    assert len(chamadas) == 1


def test_http_429_e_retentado(_habilitado, monkeypatch):
    chamadas = _sequencia(monkeypatch, _http_error(429), _payload_ok())
    r = psi.medir("https://x.es")
    assert r["estado"] == "CONFIRMADO_PRESENTE"
    assert r["tentativas"] == 2
    assert len(chamadas) == 2


def test_resposta_inesperada_nao_e_retentada(_habilitado, monkeypatch):
    """200 com formato estranho não é instabilidade: repetir tende a dar o mesmo."""
    chamadas = _sequencia(monkeypatch, {"unexpected": True}, _payload_ok())
    r = psi.medir("https://x.es")
    assert r["estado"] == "NAO_VERIFICADO"
    assert "inesperada" in r["motivo"]
    assert r["tentativas"] == 1
    assert len(chamadas) == 1


def test_espera_entre_tentativas_acontece_de_fato(_habilitado, monkeypatch):
    esperas = []
    monkeypatch.setattr(psi.time, "sleep", lambda s: esperas.append(s))
    _sequencia(monkeypatch, _http_error(500), _payload_ok())
    psi.medir("https://x.es", delay_entre_tentativas=2.5)
    assert esperas == [2.5], "deve esperar exatamente uma vez, antes da 2ª tentativa"


def test_nao_espera_depois_da_ultima_tentativa(_habilitado, monkeypatch):
    """Esperar depois da última falha é tempo jogado fora -- ninguém vai usar essa espera."""
    esperas = []
    monkeypatch.setattr(psi.time, "sleep", lambda s: esperas.append(s))
    _sequencia(monkeypatch, _http_error(500), _http_error(500))
    psi.medir("https://x.es")
    assert len(esperas) == 1


def test_tentativas_zero_quando_nenhuma_chamada_sai(monkeypatch):
    monkeypatch.delenv("PSI_ENABLED", raising=False)
    assert psi.medir("https://x.es")["tentativas"] == 0
