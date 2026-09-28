"""Contrato EXTRATOR -> QUALIFICADOR.

O EXTRATOR emite, ao lado de cada CSV, um sidecar `<mesmo-nome-base>.meta.json` com
`schema_version` (hoje = 1), plataforma, config, linhas_totais, linhas_com_deep_scrape,
extensao_versao. Este módulo valida o CSV contra esse contrato ANTES de importar qualquer
coisa. 100% Python, $0, sem LLM.

schema_version 1: as 30 colunas do formato atual do EXTRATOR (plataforma google,
extensão 1.x). Lista conferida contra o CSV real em
EQC/pipeline/extrator-output/extrator_20260906-021834_v1.csv.
"""
import json
import os

SCHEMA_VERSION_SUPORTADA = 1

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
    if versao != SCHEMA_VERSION_SUPORTADA:
        raise ContratoCsvInvalido(
            f"CSV declara schema_version={versao!r}, este QUALIFICADOR suporta "
            f"{SCHEMA_VERSION_SUPORTADA}. Atualize o QUALIFICADOR ou use um CSV compatível."
        )
    return dados, []


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
            f"{SCHEMA_VERSION_SUPORTADA}): {', '.join(faltando)}. Nada foi importado."
        )

    extras = [c for c in colunas if c not in COLUNAS_OBRIGATORIAS_V1]
    if extras:
        return [f"coluna(s) extra não declarada(s) no contrato (aceitas e ignoradas): {', '.join(extras)}"]
    return []
