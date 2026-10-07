"""Versões e localização do contrato de saída do QUALIFICADOR.

- CONTRACT_VERSION: versão do CONTRATO com o COMERCIAL (o que o consumidor deve
  checar). Muda quando a forma dos blocos `leads[*]` / `descartados[*]` /
  `stats` muda de um jeito que o consumidor precise saber.
- QUALIFICADOR_VERSION: versão do próprio pré-processador (código). Informativa,
  vai só no sidecar .meta.json.
- SCHEMA_VERSION_INTERNO: versão do formato de trabalho interno do output_json.
  Continua existindo no JSON como `schema_version` por compatibilidade; NÃO é o
  que o COMERCIAL deve usar para decidir compatibilidade.

Localização do EQC (LeadFarm): este módulo NÃO guarda nenhum caminho absoluto de
máquina. A raiz do EQC é resolvida em tempo de execução -- ver `eqc_root()`.
"""
import json
import os
from pathlib import Path

# 2.0.0: separa nata/candidatos_triagem e transporta sinais renderizados do site.
# 2.1.0: acrescenta o campo opcional texto_site (MINOR, aditivo -- CONTRACT.md).
# 2.2.0: acrescenta campanha_id, campanha_nicho e possivel_mesmo_negocio por lead, e
#        campanha_id/campanha_nicho por descartado (CONTRACT.md, histórico de versões).
# 2.3.0: acrescenta campanha_cidade por lead e por descartado (multicidade: cidade do termo
#        da busca validada pela lista do INE, ou cidade_padrao em lista sem termo).
CONTRACT_VERSION = "2.3.0"
QUALIFICADOR_VERSION = "1.1.0"
SCHEMA_VERSION_INTERNO = "2.0"

# --- Localização do EQC (camada transversal do LeadFarm) -----------------------------
# O EQC é irmão dos módulos EXTRATOR / QUALIFICADOR / COMERCIAL dentro do LeadFarm.
# Layout futuro aprovado:   <...>/Projetos/LeadFarm/{EQC, EXTRATOR, QUALIFICADOR, COMERCIAL}
# Layout atual:             o EQC fica um nível acima do repo do QUALIFICADOR.
# Nenhum dos dois é fixado no código. Ordem de resolução da RAIZ do EQC (`eqc_root`):
#   1. env QUALIFICADOR_EQC_ROOT  -- aponta direto para a pasta ".../EQC".
#   2. env LEADFARM_ROOT          -- raiz do ecossistema; o EQC é <LEADFARM_ROOT>/EQC.
#   3. descoberta: subindo a partir desta pasta, o 1o ancestral que tiver um filho
#      "EQC/contracts/leads_qualificados.schema.json" (cobre os dois layouts).
#   4. fallback: <pasta-pai-do-repo>/EQC  (layout de modulos irmaos), ainda que nao
#      exista -- serve para a mensagem de erro apontar um lugar plausivel.
# As env de CAMINHO FINAL (QUALIFICADOR_CONTRACT_SCHEMA, QUALIFICADOR_OUTPUT_DIR)
# continuam tendo precedencia sobre tudo isso, cada uma no seu ponto.

_REPO_DIR = Path(__file__).resolve().parent
_SCHEMA_REL = ("contracts", "leads_qualificados.schema.json")
_OUTPUT_REL = ("pipeline", "qualificador-output")


def _env(nome):
    return (os.environ.get(nome) or "").strip()


def _descobrir_eqc_root():
    """Sobe a arvore a partir de `_REPO_DIR` e devolve o 1o `<ancestral>/EQC` que
    contem o schema formal. None se nada for encontrado."""
    for ancestral in (_REPO_DIR, *_REPO_DIR.parents):
        candidato = ancestral / "EQC"
        if candidato.joinpath(*_SCHEMA_REL).is_file():
            return candidato
    return None


def eqc_root():
    """Raiz do EQC (.../EQC), resolvida em runtime. Ver a ordem no topo do modulo.
    Devolve um `pathlib.Path` (pode nao existir no caso do fallback)."""
    if _env("QUALIFICADOR_EQC_ROOT"):
        return Path(_env("QUALIFICADOR_EQC_ROOT"))
    if _env("LEADFARM_ROOT"):
        return Path(_env("LEADFARM_ROOT")) / "EQC"
    descoberto = _descobrir_eqc_root()
    if descoberto is not None:
        return descoberto
    return _REPO_DIR.parent / "EQC"


def output_dir() -> str:
    """Diretório onde o contrato de saída é gravado. `QUALIFICADOR_OUTPUT_DIR`
    (caminho final) tem precedência; senão, `<eqc_root>/pipeline/qualificador-output`.
    Lê o ambiente a cada chamada (para testes isolarem via monkeypatch.setenv)."""
    return _env("QUALIFICADOR_OUTPUT_DIR") or str(eqc_root().joinpath(*_OUTPUT_REL))


def contract_schema_path() -> str:
    """Caminho do JSON Schema do contrato -- autoridade estrutural, vive no EQC.
    `QUALIFICADOR_CONTRACT_SCHEMA` (caminho final) tem precedência; senão,
    `<eqc_root>/contracts/leads_qualificados.schema.json`. Lê o ambiente a cada
    chamada (mesmo padrão de `output_dir`)."""
    return _env("QUALIFICADOR_CONTRACT_SCHEMA") or str(eqc_root().joinpath(*_SCHEMA_REL))


# Retrocompat: nomes citados pela documentação (CLAUDE.md §2) e por chamadas antigas.
# Agora são DERIVADOS da raiz do EQC resolvida na importação -- sem caminho absoluto
# fixo no código e sem considerar as env de caminho final (QUALIFICADOR_CONTRACT_SCHEMA
# / QUALIFICADOR_OUTPUT_DIR). Preferir as funções acima: estas constantes não veem
# env vars definidas depois do import.
OUTPUT_DIR_DEFAULT = str(eqc_root().joinpath(*_OUTPUT_REL))
CONTRACT_SCHEMA_DEFAULT = str(eqc_root().joinpath(*_SCHEMA_REL))


def carregar_schema() -> dict:
    with open(contract_schema_path(), "r", encoding="utf-8") as f:
        return json.load(f)


def validar(doc: dict) -> None:
    """Valida o dict do contrato contra o JSON Schema (Draft 2020-12), ANTES de gravar.

    Falha alto: levanta jsonschema.exceptions.ValidationError (path do campo + motivo)
    no primeiro erro. Quem chama (fase_saida) não deve gravar nada se isto levantar.
    `jsonschema` é a primeira e única dependência externa de runtime do projeto -- ver
    requirements.txt e a nota no PR."""
    import jsonschema  # import tardio: só a fase de saída precisa

    validador = jsonschema.Draft202012Validator(carregar_schema())
    erros = sorted(validador.iter_errors(doc), key=lambda e: list(e.absolute_path))
    if not erros:
        return
    e = erros[0]
    caminho = "/".join(str(p) for p in e.absolute_path) or "(raiz)"
    extra = f"  (+{len(erros) - 1} outro(s) erro(s) de validação)" if len(erros) > 1 else ""
    raise jsonschema.exceptions.ValidationError(
        f"contrato inválido em '{caminho}': {e.message}{extra}  "
        f"[schema: {contract_schema_path()}]"
    )
