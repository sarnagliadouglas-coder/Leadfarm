"""Contrato EXTRATOR -> QUALIFICADOR.

O EXTRATOR emite, ao lado de cada CSV, um sidecar `<mesmo-nome-base>.meta.json` com
`schema_version`, plataforma, config, linhas_totais, linhas_com_deep_scrape,
extensao_versao. Este módulo valida o CSV contra esse contrato ANTES de importar qualquer
coisa. 100% Python, $0, sem LLM.

schema_version 1: as 30 colunas do formato atual do EXTRATOR (plataforma google,
extensão 1.x). Lista conferida contra o CSV real em
EQC/pipeline/extrator-output/extrator_20260906-021834_v1.csv.

schema_version 2 (extensão 1.2.0, Tarefa 3, diretor 06/10/2026): o MESMO CSV de 30
colunas (o nome do arquivo continua `_v1`); o sidecar ganha `termo_busca` (texto ou null)
e `termo_busca_origem` ("url", "caixa_de_busca" ou "ausente"), usados para escolher a
campanha no import (campanha.escolher_campanha).
"""
import json
import os

SCHEMA_VERSOES_SUPORTADAS = (1, 2)
# Versão do conjunto de colunas do CSV -- não mudou no meta v2.
VERSAO_COLUNAS_CSV = 1
ORIGENS_TERMO = ("url", "caixa_de_busca", "ausente")

# Header esperado do CSV do EXTRATOR, schema_version 1. Ordem = ordem real do arquivo.
# Todas obrigatórias -- o EXTRATOR sempre emite as 30. Coluna a mais = aviso, não erro.
COLUNAS_OBRIGATORIAS_V1 = [
    "Name", "Phone", "Phones", "Website", "Domain", "Email", "Emails",
    "Instagram", "Facebook", "LinkedIn", "Fulladdress", "Street", "Municipality",
    "Categories", "Opportunity", "Review Count", "Average Rating", "Place Id",
    "Latitude", "Longitude", "Google Maps URL", "Review URL", "Claimed",
    "Detail Scraped", "Opening Hours", "Description", "Price Range", "Plus Code",
    "Owner", "Featured Image",
]


class ContratoCsvInvalido(Exception):
    """Falha alta: o CSV não cumpre o contrato EXTRATOR -> QUALIFICADOR. Nada é importado.
    É "pare e conserte o EXTRATOR", não "este arquivo específico está corrompido"."""


def caminho_sidecar(caminho_csv: str) -> str:
    base, _ext = os.path.splitext(caminho_csv)
    return base + ".meta.json"


def validar_sidecar(caminho_csv: str):
    """Lê o sidecar do EXTRATOR ao lado do CSV. Devolve (sidecar: dict | None, avisos: list[str]).

    - schema_version incompatível  -> ContratoCsvInvalido (mensagem clara).
    - sidecar ilegível             -> ContratoCsvInvalido.
    - sidecar ausente              -> (None, [aviso]); segue (CSVs antigos não têm sidecar).
    """
    sc = caminho_sidecar(caminho_csv)
    if not os.path.exists(sc):
        return None, [
            f"sidecar do EXTRATOR ausente ({os.path.basename(sc)}) -- CSV sem contrato "
            f"declarado; seguindo sem checar schema_version."
        ]
    try:
        with open(sc, "r", encoding="utf-8") as f:
            dados = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        raise ContratoCsvInvalido(f"sidecar '{os.path.basename(sc)}' ilegível: {e}")

    versao = dados.get("schema_version")
    if isinstance(versao, bool) or versao not in SCHEMA_VERSOES_SUPORTADAS:
        raise ContratoCsvInvalido(
            f"CSV declara schema_version={versao!r}, este QUALIFICADOR suporta "
            f"{' ou '.join(map(str, SCHEMA_VERSOES_SUPORTADAS))}. Atualize o QUALIFICADOR ou use um "
            f"CSV compatível."
        )
    if versao >= 2:
        _validar_termo_busca(dados, os.path.basename(sc))
    return dados, []


def _validar_termo_busca(dados, nome_sidecar):
    """Meta v2: `termo_busca` (texto não vazio ou null) e `termo_busca_origem` coerentes.
    Sidecar v2 sem os dois campos, ou com valores fora do contrato, é falha alta -- a escolha
    da campanha depende deles e nunca adivinha."""
    erros = []
    if "termo_busca" not in dados or "termo_busca_origem" not in dados:
        erros.append("faltam 'termo_busca' e/ou 'termo_busca_origem'")
    else:
        termo, origem = dados["termo_busca"], dados["termo_busca_origem"]
        if origem not in ORIGENS_TERMO:
            erros.append(f"termo_busca_origem={origem!r} fora de {ORIGENS_TERMO}")
        if termo is not None and (not isinstance(termo, str) or not termo.strip()):
            erros.append(f"termo_busca={termo!r} deve ser texto não vazio ou null")
        elif (termo is None) != (origem == "ausente"):
            erros.append(f"termo_busca={termo!r} incoerente com termo_busca_origem={origem!r}")
    if erros:
        raise ContratoCsvInvalido(f"sidecar '{nome_sidecar}' (schema_version 2) inválido: " + "; ".join(erros) + ".")


def validar_header(colunas_csv) -> list[str]:
    """colunas_csv = fieldnames do csv.DictReader (ordem preservada). Devolve avisos.

    Coluna obrigatória ausente -> ContratoCsvInvalido, listando TODAS as que faltaram.
    Coluna extra não declarada -> aviso, segue normalmente.
    """
    colunas = [c for c in (colunas_csv or []) if c]
    presentes = set(colunas)

    faltando = [c for c in COLUNAS_OBRIGATORIAS_V1 if c not in presentes]
    if faltando:
        raise ContratoCsvInvalido(
            "coluna(s) obrigatória(s) ausente(s) no header do CSV (contrato schema_version "
            f"{VERSAO_COLUNAS_CSV}): {', '.join(faltando)}. Nada foi importado."
        )

    extras = [c for c in colunas if c not in COLUNAS_OBRIGATORIAS_V1]
    if extras:
        return [f"coluna(s) extra não declarada(s) no contrato (aceitas e ignoradas): {', '.join(extras)}"]
    return []
