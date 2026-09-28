import gzip
import socket
import ssl
import urllib.error

import website_analyzer as wa


HTML_SAUDAVEL = """
<html lang="es">
<head>
<title>Clinica Ejemplo - Fisioterapia en Sevilla</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="description" content="Clinica de fisioterapia en Sevilla con atencion personalizada.">
</head>
<body>
<script src="a.js"></script>
<img src="foto.jpg" alt="Sala de tratamiento">
<form><input type="text"></form>
<a href="tel:+34600000000">Llamar</a>
<a href="/aviso-legal">Aviso legal</a>
<button>Reservar cita</button>
</body>
</html>
"""

HTML_POBRE = """
<html>
<head></head>
<body>
<img src="foto.jpg">
<img src="foto2.jpg">
</body>
</html>
"""


def _raw(url_final="https://example.es/", http_status=200, content_type="text/html; charset=utf-8",
         body=HTML_SAUDAVEL, response_time_ms=120.0, content_truncated=False):
    return wa._RawResponse(url_final, http_status, content_type, body.encode("utf-8"), response_time_ms, content_truncated)


def test_site_saudavel_extrai_todos_sinais_positivos(monkeypatch):
    monkeypatch.setattr(wa, "_fetch_raw", lambda url, timeout, max_bytes, user_agent: _raw())
    resultado = wa.analisar_site("https://example.es")

    assert resultado["status"] == "ok"
    s = resultado["signals"]
    assert s["has_viewport_meta"] is True
    assert s["has_title"] is True
    assert s["has_meta_description"] is True
    assert s["has_form"] is True
    assert s["has_tel_link"] is True
    assert s["has_legal_page_link"] is True
    assert s["has_lang_attribute"] is True
    assert s["html_lang"] == "es"
    assert s["has_cta_keyword"] is True
    assert s["images_missing_alt_count"] == 0


def test_site_sem_viewport_nem_meta_description(monkeypatch):
    monkeypatch.setattr(wa, "_fetch_raw", lambda url, timeout, max_bytes, user_agent: _raw(body=HTML_POBRE))
    resultado = wa.analisar_site("https://example.es")
    s = resultado["signals"]
    assert s["has_viewport_meta"] is False
    assert s["has_meta_description"] is False
    assert s["has_title"] is False


def test_imagens_sem_alt_sao_contadas(monkeypatch):
    monkeypatch.setattr(wa, "_fetch_raw", lambda url, timeout, max_bytes, user_agent: _raw(body=HTML_POBRE))
    resultado = wa.analisar_site("https://example.es")
    assert resultado["signals"]["images_missing_alt_count"] == 2


def test_conteudo_truncado_e_reportado(monkeypatch):
    monkeypatch.setattr(wa, "_fetch_raw", lambda url, timeout, max_bytes, user_agent: _raw(content_truncated=True))
    resultado = wa.analisar_site("https://example.es")
    assert resultado["facts"]["content_truncated"] is True


def test_timeout_vira_unavailable(monkeypatch):
    def _lanca(url, timeout, max_bytes, user_agent):
        raise socket.timeout("timed out")
    monkeypatch.setattr(wa, "_fetch_raw", _lanca)
    resultado = wa.analisar_site("https://example.es")
    assert resultado["status"] == "unavailable"
    assert resultado["error_type"] == "timeout"
    assert resultado["signals_available"] is False


def test_ssl_error_vira_unavailable(monkeypatch):
    def _lanca(url, timeout, max_bytes, user_agent):
        raise ssl.SSLError("certificate verify failed")
    monkeypatch.setattr(wa, "_fetch_raw", _lanca)
    resultado = wa.analisar_site("https://example.es")
    assert resultado["error_type"] == "ssl_error"


def test_http_403_guarda_status(monkeypatch):
    def _lanca(url, timeout, max_bytes, user_agent):
        raise urllib.error.HTTPError(url, 403, "Forbidden", hdrs=None, fp=None)
    monkeypatch.setattr(wa, "_fetch_raw", _lanca)
    resultado = wa.analisar_site("https://example.es")
    assert resultado["error_type"] == "http_error"
    assert resultado["facts"]["http_status"] == 403


def test_dns_falha_vira_connection_error(monkeypatch):
    def _lanca(url, timeout, max_bytes, user_agent):
        raise urllib.error.URLError("Name or service not known")
    monkeypatch.setattr(wa, "_fetch_raw", _lanca)
    resultado = wa.analisar_site("https://naoexiste.invalid")
    assert resultado["error_type"] == "connection_error"


def test_redirect_detectado(monkeypatch):
    monkeypatch.setattr(wa, "_fetch_raw", lambda url, timeout, max_bytes, user_agent: _raw(url_final="https://www.example.es/home"))
    resultado = wa.analisar_site("https://example.es")
    assert resultado["facts"]["redirected"] is True


def test_redirect_http_para_https_detectado(monkeypatch):
    monkeypatch.setattr(wa, "_fetch_raw", lambda url, timeout, max_bytes, user_agent: _raw(url_final="https://example.es/"))
    resultado = wa.analisar_site("http://example.es")
    assert resultado["facts"]["redirect_http_to_https"] is True


def test_sem_redirect_quando_url_final_igual(monkeypatch):
    monkeypatch.setattr(wa, "_fetch_raw", lambda url, timeout, max_bytes, user_agent: _raw(url_final="https://example.es"))
    resultado = wa.analisar_site("https://example.es")
    assert resultado["facts"]["redirected"] is False


def test_url_invalida_ou_vazia_nunca_bate_rede(monkeypatch):
    chamou = {"sim": False}

    def _lanca(url, timeout, max_bytes, user_agent):
        chamou["sim"] = True
        return _raw()

    monkeypatch.setattr(wa, "_fetch_raw", _lanca)
    resultado = wa.analisar_site("")
    assert resultado["status"] == "unavailable"
    assert resultado["error_type"] == "invalid_url"
    assert chamou["sim"] is False

    resultado_none = wa.analisar_site(None)
    assert resultado_none["error_type"] == "invalid_url"


def test_excecao_inesperada_nunca_escapa(monkeypatch):
    def _lanca(url, timeout, max_bytes, user_agent):
        raise ValueError("algo bem inesperado")
    monkeypatch.setattr(wa, "_fetch_raw", _lanca)
    resultado = wa.analisar_site("https://example.es")  # não deve lançar
    assert resultado["status"] == "unavailable"
    assert resultado["error_type"] == "unknown"


def test_gzip_e_decodificado_quando_content_encoding_presente(monkeypatch):
    """Testa _fetch_raw() de verdade (não mockado), só trocando urlopen por uma resposta falsa
    com corpo gzip -- exercita o gzip.decompress() real dentro da função."""
    comprimido = gzip.compress(HTML_SAUDAVEL.encode("utf-8"))

    class _FakeHeaders(dict):
        def get(self, key, default=None):
            return dict.get(self, key, default)

    class _FakeResp:
        def __init__(self):
            self.headers = _FakeHeaders({"Content-Type": "text/html; charset=utf-8", "Content-Encoding": "gzip"})
            self.status = 200

        def read(self, n=-1):
            return comprimido

        def geturl(self):
            return "https://example.es/"

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    import urllib.request as urlreq
    monkeypatch.setattr(urlreq, "urlopen", lambda req, timeout: _FakeResp())

    raw = wa._fetch_raw("https://example.es", timeout=5, max_bytes=300_000, user_agent="x")
    assert raw.body_bytes.decode("utf-8") == HTML_SAUDAVEL
