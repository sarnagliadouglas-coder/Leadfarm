"""Único ponto de contato com a rede na Onda 2. Contrato deliberadamente diferente do resto do
projeto: NUNCA lança exceção — falha de site de terceiro é esperada e frequente (403, Cloudflare,
SSL inválido, offline, lento). Sempre devolve um dict bem formado (status='ok'|'unavailable'),
nunca chama LLM, nunca decide prioridade (isso é trabalho de wave2_scoring.py)."""
import gzip
import re
import socket
import ssl
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

DEFAULT_TIMEOUT_SECONDS = 8
DEFAULT_MAX_BYTES = 300_000
DEFAULT_USER_AGENT = "Mozilla/5.0 (compatible; ProspeccaoBot/1.0)"

_VIEWPORT_RE = re.compile(r'<meta[^>]+name=["\']viewport["\']', re.IGNORECASE)
_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_META_DESC_RE = re.compile(r'<meta[^>]+name=["\']description["\'][^>]+content=["\'](.*?)["\']', re.IGNORECASE | re.DOTALL)
_SCRIPT_RE = re.compile(r"<script\b", re.IGNORECASE)
_IMG_RE = re.compile(r"<img\b[^>]*>", re.IGNORECASE)
_IMG_ALT_RE = re.compile(r'\balt\s*=\s*["\'][^"\']*["\']', re.IGNORECASE)
_FORM_RE = re.compile(r"<form\b", re.IGNORECASE)
_TEL_RE = re.compile(r'href=["\']tel:', re.IGNORECASE)
_WHATSAPP_RE = re.compile(r"(wa\.me/|api\.whatsapp\.com)", re.IGNORECASE)
_EMAIL_LINK_RE = re.compile(r'href=["\']mailto:', re.IGNORECASE)
_LEGAL_RE = re.compile(r"aviso[\s-]?legal|pol[ií]tica[\s-]?de[\s-]?privacidad|cookies|t[ée]rminos[\s-]?y[\s-]?condiciones", re.IGNORECASE)
_LANG_RE = re.compile(r"<html[^>]+lang=[\"']([a-zA-Z-]+)[\"']", re.IGNORECASE)
_CTA_RE = re.compile(r"reservar|agendar|contactar|solicitar|pedir\s+cita|ll[aá]manos|escr[ií]benos|presupuesto", re.IGNORECASE)


class _RawResponse:
    def __init__(self, url_final, http_status, content_type, body_bytes, response_time_ms, content_truncated):
        self.url_final = url_final
        self.http_status = http_status
        self.content_type = content_type
        self.body_bytes = body_bytes
        self.response_time_ms = response_time_ms
        self.content_truncated = content_truncated


def _normalizar_url(url):
    if not url or not isinstance(url, str):
        return None
    url = url.strip()
    if not url:
        return None
    if not re.match(r"^https?://", url, re.IGNORECASE):
        url = "http://" + url
    if not re.match(r"^https?://[^\s]+\.[^\s]+", url, re.IGNORECASE):
        return None
    return url


def _fetch_raw(url, timeout, max_bytes, user_agent):
    """Único ponto que efetivamente chama urllib.request.urlopen. Pode lançar
    (urllib.error.HTTPError, urllib.error.URLError, socket.timeout, ssl.SSLError,
    UnicodeDecodeError) — analisar_site() é quem captura. Separado só pra ser fácil de
    testar via monkeypatch, sem mexer no urllib de verdade."""
    inicio = time.time()
    req = urllib.request.Request(url, headers={"User-Agent": user_agent, "Accept": "text/html,*/*"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        content_type = resp.headers.get("Content-Type")
        content_encoding = resp.headers.get("Content-Encoding", "")
        raw = resp.read(max_bytes + 1)
        truncated = len(raw) > max_bytes
        raw = raw[:max_bytes]
        url_final = resp.geturl()
        http_status = resp.status
    response_time_ms = (time.time() - inicio) * 1000

    if "gzip" in content_encoding.lower():
        try:
            raw = gzip.decompress(raw)
        except OSError:
            pass  # corpo pode ter sido truncado no meio do stream — segue com o que tem

    return _RawResponse(url_final, http_status, content_type, raw, response_time_ms, truncated)


def _extrair_sinais(html):
    title_match = _TITLE_RE.search(html)
    title = re.sub(r"\s+", " ", title_match.group(1)).strip() if title_match else ""
    meta_desc_match = _META_DESC_RE.search(html)
    meta_desc = meta_desc_match.group(1).strip() if meta_desc_match else ""
    lang_match = _LANG_RE.search(html)

    imagens = _IMG_RE.findall(html)
    imagens_sem_alt = sum(1 for tag in imagens if not _IMG_ALT_RE.search(tag))

    return {
        "has_viewport_meta": bool(_VIEWPORT_RE.search(html)),
        "has_title": bool(title),
        "title_length": len(title),
        "has_meta_description": bool(meta_desc),
        "meta_description_length": len(meta_desc),
        "script_count": len(_SCRIPT_RE.findall(html)),
        "image_count": len(imagens),
        "images_missing_alt_count": imagens_sem_alt,
        "has_form": bool(_FORM_RE.search(html)),
        "has_tel_link": bool(_TEL_RE.search(html)),
        "has_whatsapp_link": bool(_WHATSAPP_RE.search(html)),
        "has_email_link": bool(_EMAIL_LINK_RE.search(html)),
        "has_legal_page_link": bool(_LEGAL_RE.search(html)),
        "has_lang_attribute": bool(lang_match),
        "html_lang": lang_match.group(1) if lang_match else None,
        "has_cta_keyword": bool(_CTA_RE.search(html)),
    }


def _now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _resultado_base(url_original, checked_at):
    return {
        "url_original": url_original,
        "checked_at": checked_at,
    }


def _resultado_falha(url_original, checked_at, error_type, error_msg, http_status=None):
    return {
        **_resultado_base(url_original, checked_at),
        "status": "unavailable",
        "error": error_msg,
        "error_type": error_type,
        "facts": {
            "url_final": None, "http_status": http_status, "https": None, "redirected": None,
            "redirect_http_to_https": None, "response_time_ms": None, "content_type": None,
            "page_size_bytes": None, "content_truncated": None,
        },
        "signals_available": False,
        "signals": None,
    }


def analisar_site(url, timeout=DEFAULT_TIMEOUT_SECONDS, max_bytes=DEFAULT_MAX_BYTES, user_agent=DEFAULT_USER_AGENT):
    """Nunca lança. Sempre devolve o schema documentado no plano (status='ok'|'unavailable')."""
    checked_at = _now_iso()
    url_normalizada = _normalizar_url(url)
    if not url_normalizada:
        return _resultado_falha(url, checked_at, "invalid_url", "URL ausente ou malformada")

    try:
        raw = _fetch_raw(url_normalizada, timeout, max_bytes, user_agent)
    except urllib.error.HTTPError as e:
        return _resultado_falha(url_normalizada, checked_at, "http_error", str(e), http_status=e.code)
    except (socket.timeout, TimeoutError) as e:
        return _resultado_falha(url_normalizada, checked_at, "timeout", str(e) or "tempo esgotado")
    except ssl.SSLError as e:
        return _resultado_falha(url_normalizada, checked_at, "ssl_error", str(e))
    except urllib.error.URLError as e:
        return _resultado_falha(url_normalizada, checked_at, "connection_error", str(e.reason))
    except Exception as e:
        # Rede de segurança final: literalmente nada pode derrubar o processo por causa
        # de um site de terceiro.
        return _resultado_falha(url_normalizada, checked_at, "unknown", str(e))

    try:
        html = raw.body_bytes.decode(_detectar_encoding(raw.content_type), errors="replace")
        sinais = _extrair_sinais(html)
    except Exception as e:
        return _resultado_falha(url_normalizada, checked_at, "unknown", f"falha ao interpretar conteúdo: {e}", http_status=raw.http_status)

    https = raw.url_final.lower().startswith("https://")
    redirected = raw.url_final.rstrip("/") != url_normalizada.rstrip("/")
    redirect_http_to_https = url_normalizada.lower().startswith("http://") and https

    return {
        **_resultado_base(url, checked_at),
        "status": "ok",
        "error": None,
        "error_type": None,
        "facts": {
            "url_final": raw.url_final,
            "http_status": raw.http_status,
            "https": https,
            "redirected": redirected,
            "redirect_http_to_https": redirect_http_to_https,
            "response_time_ms": round(raw.response_time_ms, 1),
            "content_type": raw.content_type,
            "page_size_bytes": len(raw.body_bytes),
            "content_truncated": raw.content_truncated,
        },
        "signals_available": True,
        "signals": sinais,
    }


def _detectar_encoding(content_type):
    if content_type:
        m = re.search(r"charset=([\w-]+)", content_type, re.IGNORECASE)
        if m:
            return m.group(1)
    return "utf-8"
