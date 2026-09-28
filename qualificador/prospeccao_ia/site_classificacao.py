"""Classe do site de um lead, a partir da URL que a ficha do Maps declarou (Etapa C, passo C1).

url -> proprio | portal | construtor | rede_social | superficie_google | sem_site

So olha o HOST da URL, contra a lista de dominios em config/dominios_site.json. Sem rede, sem
LLM, sem julgamento de conteudo: o resultado e funcao pura da string.

Casamento por host exato ou subdominio ("dominios") e por sufixo de subdominio ("sufixos", o
apex nao casa) -- nunca por substring solta ("x.com" nao bate em "ficticiotex.com"; ver
agent_coletor.py, a armadilha ja documentada la). "proprio" e o que sobra: um construtor com
DOMINIO PROPRIO (Wix num .es do cliente) sai como "proprio" -- limite aceito pelo diretor
(Q6, 20/09/2026), a triagem visual do COMERCIAL recupera esse caso.

Esta classe e dado INTERNO. Nao roteia Onda 1/2 (quem roteia e website_status, em
agent_coletor.py), nao entra em peso e nao atravessa a fronteira do contrato.

URL ausente ou sem host utilizavel (vazia, "N/A", sem ponto, "mailto:", "tel:", "file:",
"javascript:", host malformado) vira "sem_site": nunca "proprio", porque "proprio" abre a porta
da analise do site e da nata.
"""
import json
import os
import re
from urllib.parse import urlsplit

CAMINHO_CONFIG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config", "dominios_site.json")

PROPRIO = "proprio"
PORTAL = "portal"
CONSTRUTOR = "construtor"
REDE_SOCIAL = "rede_social"
SUPERFICIE_GOOGLE = "superficie_google"
SEM_SITE = "sem_site"

# Categorias que vem da lista, na ordem de precedencia (a lista atual nao tem host em duas).
CATEGORIAS_DA_LISTA = (REDE_SOCIAL, PORTAL, CONSTRUTOR, SUPERFICIE_GOOGLE)
CLASSES = CATEGORIAS_DA_LISTA + (PROPRIO, SEM_SITE)


class ConfigDominiosInvalidaError(ValueError):
    """A lista de dominios esta ausente, malformada ou inconsistente. Falha alta de proposito:
    lista silenciosamente vazia classificaria tudo como 'proprio'."""


# --- Host da URL ------------------------------------------------------------------------------

_ESQUEMA_RE = re.compile(r"^[a-z][a-z0-9+.\-]*://", re.IGNORECASE)
# "mailto:", "tel:", "javascript:" -- esquema sem barras. Nao pega "dominio.es:8080/x" (porta).
_ESQUEMA_SEM_BARRAS_RE = re.compile(r"^[a-z][a-z0-9+.\-]*:(?!//)(?!\d+(?:[/?#]|$))", re.IGNORECASE)
_HOST_RE = re.compile(r"[^\s./:@?#\\]+(?:\.[^\s./:@?#\\]+)+")


def _host(url):
    if not isinstance(url, str):
        return None
    bruto = url.strip()
    if not bruto:
        return None
    if _ESQUEMA_RE.match(bruto):
        if not bruto.lower().startswith(("http://", "https://")):
            return None
    elif bruto.startswith("//"):
        bruto = "http:" + bruto
    elif _ESQUEMA_SEM_BARRAS_RE.match(bruto):
        return None
    else:
        bruto = "http://" + bruto
    try:
        host = urlsplit(bruto).hostname
    except ValueError:
        return None
    if not host:
        return None
    host = host.lower().rstrip(".")
    if host.startswith("www."):
        host = host[4:]
    return host if _HOST_RE.fullmatch(host) else None


def _casa_dominio(host, dominio):
    return host == dominio or host.endswith("." + dominio)


def _casa_sufixo(host, sufixo):
    # `sufixo` ja comeca com "."; o apex (host == sufixo sem o ponto) nao casa.
    return len(host) > len(sufixo) and host.endswith(sufixo)


# --- Lista de dominios ------------------------------------------------------------------------

_cache = {}


def _entradas(lista, categoria, tipo, fontes, vistos):
    if not isinstance(lista, list):
        raise ConfigDominiosInvalidaError(f"'{categoria}.{tipo}' deve ser lista")
    valores = []
    for item in lista:
        if not isinstance(item, dict) or not isinstance(item.get("valor"), str):
            raise ConfigDominiosInvalidaError(f"'{categoria}.{tipo}': entrada sem 'valor' texto: {item!r}")
        valor = item["valor"]
        origem = item.get("origem")
        if not isinstance(origem, list) or not origem or not all(o in fontes for o in origem):
            raise ConfigDominiosInvalidaError(
                f"'{categoria}.{tipo}' '{valor}': 'origem' deve listar ids existentes em 'fontes'")
        if valor != valor.strip().lower() or re.search(r"[\s/:@?#\\]", valor) or valor.startswith("www."):
            raise ConfigDominiosInvalidaError(
                f"'{categoria}.{tipo}' '{valor}': so o host, minusculo, sem esquema/caminho/'www.'")
        if tipo == "dominios":
            if valor.startswith(".") or "." not in valor:
                raise ConfigDominiosInvalidaError(f"'{categoria}.dominios' '{valor}': dominio invalido")
        elif not (valor.startswith(".") and "." in valor[1:]):
            raise ConfigDominiosInvalidaError(
                f"'{categoria}.sufixos' '{valor}': sufixo deve comecar com '.' e ter pelo menos dois rotulos")
        if valor in vistos:
            raise ConfigDominiosInvalidaError(
                f"'{valor}' repetido (em '{vistos[valor]}' e '{categoria}.{tipo}')")
        vistos[valor] = f"{categoria}.{tipo}"
        valores.append(valor)
    return tuple(valores)


def carregar_dominios(caminho=CAMINHO_CONFIG):
    """Le e valida a lista. {categoria: {"dominios": (...), "sufixos": (...)}}. Cacheada por caminho."""
    if caminho in _cache:
        return _cache[caminho]
    try:
        with open(caminho, "r", encoding="utf-8") as f:
            bruto = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        raise ConfigDominiosInvalidaError(f"nao consegui ler '{caminho}': {e}") from e
    if not isinstance(bruto, dict) or not isinstance(bruto.get("fontes"), dict) or not bruto["fontes"]:
        raise ConfigDominiosInvalidaError("'fontes' ausente: cada entrada precisa dizer de onde veio")
    for id_fonte, fonte in bruto["fontes"].items():
        if not isinstance(fonte, dict) or not all(fonte.get(c) for c in ("arquivo", "linhas", "copiado_em")):
            raise ConfigDominiosInvalidaError(f"fonte '{id_fonte}' sem arquivo/linhas/copiado_em")
    categorias = bruto.get("categorias")
    if not isinstance(categorias, dict) or set(categorias) != set(CATEGORIAS_DA_LISTA):
        raise ConfigDominiosInvalidaError(f"'categorias' deve ter exatamente {list(CATEGORIAS_DA_LISTA)}")
    vistos = {}
    resultado = {}
    for categoria in CATEGORIAS_DA_LISTA:
        bloco = categorias[categoria]
        if not isinstance(bloco, dict):
            raise ConfigDominiosInvalidaError(f"'{categoria}' deve ser objeto")
        resultado[categoria] = {
            "dominios": _entradas(bloco.get("dominios", []), categoria, "dominios", bruto["fontes"], vistos),
            "sufixos": _entradas(bloco.get("sufixos", []), categoria, "sufixos", bruto["fontes"], vistos),
        }
    _cache[caminho] = resultado
    return resultado


def classificar_site(url, caminho_config=CAMINHO_CONFIG):
    host = _host(url)
    if host is None:
        return SEM_SITE
    dominios = carregar_dominios(caminho_config)
    for categoria in CATEGORIAS_DA_LISTA:
        lista = dominios[categoria]
        if any(_casa_dominio(host, d) for d in lista["dominios"]):
            return categoria
        if any(_casa_sufixo(host, s) for s in lista["sufixos"]):
            return categoria
    return PROPRIO
