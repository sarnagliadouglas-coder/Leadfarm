"""Municípios oficiais da Espanha (INE, "Relación de municipios") -- reconhecer a cidade do
termo da busca (Tarefa 3, multicidade, diretor 06/10/2026).

A lista vive em `config/municipios_ine.json`, gerada por `gerar_municipios_ine.py` a partir
do arquivo oficial do INE (fonte e data no bloco `fonte` do próprio JSON). Cada município
traz `formas`: as grafias oficiais aceitáveis (as duas partes de um nome bilíngue, como
"Alicante" e "Alacant", e o artigo posposto também na frente, como "Las Rozas de Madrid").

`procurar(texto)` compara sem acento, sem maiúscula e sem espaço repetido, contra o texto
INTEIRO (nunca pedaço de nome), e devolve um item por município que casou, com a forma
oficial que casou. Zero ou mais de um resultado é decisão de quem chama -- aqui nada é
adivinhado. Env `QUALIFICADOR_MUNICIPIOS` (caminho do JSON) existe só para teste.
$0, sem LLM.
"""
import json
import os
import unicodedata

ENV_CAMINHO = "QUALIFICADOR_MUNICIPIOS"
_PADRAO = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config", "municipios_ine.json")

_cache = {}


class ListaMunicipiosInvalidaError(Exception):
    """`municipios_ine.json` ausente, ilegível ou fora do formato."""


def caminho_lista() -> str:
    return (os.environ.get(ENV_CAMINHO) or "").strip() or _PADRAO


def chave(texto) -> str:
    """Sem acento, sem maiúscula, espaços internos colapsados."""
    decomposto = unicodedata.normalize("NFKD", texto or "")
    sem_acento = "".join(c for c in decomposto if not unicodedata.combining(c))
    return " ".join(sem_acento.lower().split())


def carregar(caminho=None) -> dict:
    """`{"fonte": ..., "indice": {chave: [municipio, ...]}}`, em cache por caminho e mtime.
    Município = `{"codigo_ine", "nombre", "forma"}` (a forma oficial daquela chave)."""
    caminho = caminho or caminho_lista()
    try:
        mtime = os.path.getmtime(caminho)
    except OSError as e:
        raise ListaMunicipiosInvalidaError(f"Lista de municípios do INE não encontrada em '{caminho}'.") from e
    if _cache.get(caminho, (None,))[0] == mtime:
        return _cache[caminho][1]
    try:
        with open(caminho, "r", encoding="utf-8") as f:
            dados = json.load(f)
    except (json.JSONDecodeError, UnicodeDecodeError, OSError) as e:
        raise ListaMunicipiosInvalidaError(f"Lista de municípios do INE ilegível em '{caminho}': {e}") from e

    municipios = dados.get("municipios") if isinstance(dados, dict) else None
    if not isinstance(municipios, list) or not municipios or not isinstance(dados.get("fonte"), dict):
        raise ListaMunicipiosInvalidaError(f"'{caminho}': faltam 'fonte' ou 'municipios' (lista não vazia).")
    indice = {}
    for i, m in enumerate(municipios):
        formas = m.get("formas") if isinstance(m, dict) else None
        if (not isinstance(formas, list) or not formas or not isinstance(m.get("codigo_ine"), str)
                or not isinstance(m.get("nombre"), str)
                or not all(isinstance(fm, str) and fm.strip() for fm in formas)):
            raise ListaMunicipiosInvalidaError(f"'{caminho}': município na posição {i} fora do formato.")
        vistas = set()
        for forma in formas:
            k = chave(forma)
            if k in vistas:
                continue
            vistas.add(k)
            indice.setdefault(k, []).append({"codigo_ine": m["codigo_ine"], "nombre": m["nombre"], "forma": forma})
    resultado = {"fonte": dados["fonte"], "indice": indice}
    _cache[caminho] = (mtime, resultado)
    return resultado


def procurar(texto, caminho=None) -> list:
    """Municípios cujo nome (alguma forma oficial) é exatamente `texto`, comparado por
    `chave`. Lista vazia = não reconhecido; mais de um = ambíguo."""
    k = chave(texto)
    if not k:
        return []
    return list(carregar(caminho)["indice"].get(k, []))
