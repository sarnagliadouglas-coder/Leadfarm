r"""
eqc.py — localização em runtime da árvore EQC (camada transversal do LeadFarm),
do lado do COMERCIAL.

Espelha o padrão já adotado no QUALIFICADOR (`prospeccao_ia/contrato.py`,
função `eqc_root()`): NENHUM caminho absoluto de máquina fica fixo no código.
A raiz do EQC (`.../EQC`) é resolvida a cada chamada, cobrindo o layout atual
(EQC como pasta irmã, um nível acima do repositório do COMERCIAL) e o layout
futuro do LeadFarm:

    Desktop\Projetos\LeadFarm\{EQC, EXTRATOR, QUALIFICADOR, COMERCIAL}

Ordem de resolução da RAIZ do EQC (`eqc_root()`):

  1. env COMERCIAL_EQC_ROOT  — aponta direto para a pasta ".../EQC".
  2. env LEADFARM_ROOT       — raiz do ecossistema; o EQC é <LEADFARM_ROOT>/EQC.
  3. descoberta: subindo a partir da raiz do projeto COMERCIAL, o 1º ancestral
     que tiver um filho "EQC/contracts/leads_qualificados.schema.json"
     (cobre os dois layouts, atual e LeadFarm).
  4. fallback: <pasta-que-contém-o-projeto>/EQC (layout de módulos irmãos),
     ainda que não exista — serve para a mensagem de erro apontar um lugar
     plausível.
  5. quem consome (`contrato_loader`) levanta erro claro quando o arquivo
     resolvido não existe de fato — ver `descrever_resolucao()`.

As env de CAMINHO FINAL têm precedência sobre a raiz, cada uma no seu ponto
(mesmo princípio de `QUALIFICADOR_CONTRACT_SCHEMA` / `QUALIFICADOR_OUTPUT_DIR`):

  - COMERCIAL_CONTRACT_SCHEMA  → caminho do JSON Schema do contrato.
  - COMERCIAL_INPUT_DIR        → diretório dos lotes leads_qualificados_*.json.

Este módulo NÃO copia o schema do EQC para dentro do projeto, NÃO move pastas
e NÃO cria arquivos — só resolve caminhos.
"""

from __future__ import annotations

import os
from pathlib import Path

# ferramentas/eqc.py → _REPO_DIR = .../COMERCIAL/ferramentas
#                      _PROJECT_ROOT = .../COMERCIAL (raiz do projeto)
_REPO_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _REPO_DIR.parent

# Sub-rotas dentro da árvore EQC, relativas à raiz do EQC resolvida.
_SCHEMA_REL = ("contracts", "leads_qualificados.schema.json")
_INPUT_REL = ("pipeline", "qualificador-output")
# Mesmo caminho relativo que qualificador/prospeccao_ia/saida_humana.py usa do lado de lá
# (_SAIDA_HUMANA_REL) -- pasta oficial dos CSVs humanos (pistas Direta/Espera), consumida
# pela Etapa E2b (planilha de envio). Só leitura deste lado -- COMERCIAL nunca escreve aqui.
_SAIDA_HUMANA_REL = ("pipeline", "saidas-humanas")

# Capturas de tela do QUALIFICADOR (fase de renderização, main.py:fase_render,
# `<place_id>_<dispositivo>.png`) -- FORA da árvore EQC (não é contrato,
# não atravessa a fronteira formal); resolvida a partir da raiz do LeadFarm
# (irmã do EQC), nunca um caminho absoluto de máquina. Só leitura deste lado
# -- COMERCIAL nunca escreve nem apaga nada em qualificador/.
_CAPTURAS_REL = ("qualificador", "prospeccao_ia", "data", "capturas_site")

# Nomes das variáveis de ambiente — públicos: docs, .env.example e testes
# referenciam por estes atributos, nunca pela string literal.
ENV_EQC_ROOT = "COMERCIAL_EQC_ROOT"
ENV_LEADFARM_ROOT = "LEADFARM_ROOT"
ENV_CONTRACT_SCHEMA = "COMERCIAL_CONTRACT_SCHEMA"
ENV_INPUT_DIR = "COMERCIAL_INPUT_DIR"
ENV_SAIDA_HUMANA_DIR = "COMERCIAL_SAIDA_HUMANA_DIR"
ENV_CAPTURAS_DIR = "COMERCIAL_CAPTURAS_DIR"


class EQCNaoLocalizadoError(Exception):
    """Nenhuma estratégia de resolução encontrou uma árvore EQC utilizável.

    Reservado para chamadas que exigem uma raiz que exista. As rotas de
    caminho final (`caminho_schema_contrato()` etc.) NÃO levantam isto —
    devolvem o caminho resolvido (mesmo do fallback) e deixam o consumidor
    (`contrato_loader`) reportar o arquivo faltante com contexto.
    """


def _env(nome: str) -> str:
    return (os.environ.get(nome) or "").strip()


def _descobrir_eqc_root() -> Path | None:
    """Sobe a árvore a partir da raiz do projeto e devolve o 1º `<ancestral>/EQC`
    que contém o schema formal. `None` se nada for encontrado."""
    for ancestral in (_PROJECT_ROOT, *_PROJECT_ROOT.parents):
        candidato = ancestral / "EQC"
        if candidato.joinpath(*_SCHEMA_REL).is_file():
            return candidato
    return None


def eqc_root() -> Path:
    """Raiz do EQC (`.../EQC`), resolvida em runtime. Ver a ordem no topo do
    módulo. Devolve um `pathlib.Path` — pode não existir no caso do fallback."""
    if _env(ENV_EQC_ROOT):
        return Path(_env(ENV_EQC_ROOT))
    if _env(ENV_LEADFARM_ROOT):
        return Path(_env(ENV_LEADFARM_ROOT)) / "EQC"
    descoberto = _descobrir_eqc_root()
    if descoberto is not None:
        return descoberto
    return _PROJECT_ROOT.parent / "EQC"


def eqc_root_estrito() -> Path:
    """Como `eqc_root()`, mas levanta `EQCNaoLocalizadoError` se a raiz resolvida
    não contém `contracts/leads_qualificados.schema.json`."""
    raiz = eqc_root()
    if not raiz.joinpath(*_SCHEMA_REL).is_file():
        raise EQCNaoLocalizadoError(descrever_resolucao())
    return raiz


def _rota(env_final: str, *rel: str) -> Path:
    override = _env(env_final)
    if override:
        return Path(override)
    return eqc_root().joinpath(*rel)


def caminho_schema_contrato() -> Path:
    """JSON Schema do contrato QUALIFICADOR → COMERCIAL. `COMERCIAL_CONTRACT_SCHEMA`
    (caminho final) vence; senão `<eqc_root>/contracts/leads_qualificados.schema.json`."""
    return _rota(ENV_CONTRACT_SCHEMA, *_SCHEMA_REL)


def diretorio_lotes_entrada() -> Path:
    """Diretório onde o QUALIFICADOR grava os lotes. `COMERCIAL_INPUT_DIR` vence;
    senão `<eqc_root>/pipeline/qualificador-output`."""
    return _rota(ENV_INPUT_DIR, *_INPUT_REL)


def diretorio_saida_humana() -> Path:
    """Pasta oficial dos CSVs humanos do QUALIFICADOR (pistas Direta/Espera — a fonte da
    aba "Geral" da planilha de envio). `COMERCIAL_SAIDA_HUMANA_DIR` (caminho final) vence;
    senão `<eqc_root>/pipeline/saidas-humanas`."""
    return _rota(ENV_SAIDA_HUMANA_DIR, *_SAIDA_HUMANA_REL)


def diretorio_capturas() -> Path:
    """Pasta de capturas de tela do QUALIFICADOR (`<place_id>_mobile.png` /
    `_desktop.png`). `COMERCIAL_CAPTURAS_DIR` (caminho final) vence; senão
    `<eqc_root>/../qualificador/prospeccao_ia/data/capturas_site` -- a raiz
    do LeadFarm é a pasta-mãe da raiz do EQC (`eqc_root().parent`), mesmo
    princípio de resolução sem caminho absoluto do resto deste módulo."""
    override = _env(ENV_CAPTURAS_DIR)
    if override:
        return Path(override)
    return eqc_root().parent.joinpath(*_CAPTURAS_REL)


def descrever_resolucao() -> str:
    """Texto legível de como o EQC foi (ou seria) resolvido agora — para compor
    mensagens de erro acionáveis. Nunca levanta."""
    if _env(ENV_EQC_ROOT):
        origem = f"env {ENV_EQC_ROOT}={_env(ENV_EQC_ROOT)!r}"
    elif _env(ENV_LEADFARM_ROOT):
        origem = f"env {ENV_LEADFARM_ROOT}={_env(ENV_LEADFARM_ROOT)!r} (+ '/EQC')"
    elif _descobrir_eqc_root() is not None:
        origem = f"descoberta automática subindo a partir de {_PROJECT_ROOT}"
    else:
        origem = (
            f"fallback (nenhuma env definida e nada encontrado subindo a árvore "
            f"a partir de {_PROJECT_ROOT})"
        )
    return (
        f"EQC resolvido por: {origem}\n"
        f"  raiz EQC        : {eqc_root()}\n"
        f"  schema contrato : {caminho_schema_contrato()}\n"
        f"  lotes de entrada: {diretorio_lotes_entrada()}\n"
        f"Para apontar o EQC explicitamente, defina uma destas variáveis de "
        f"ambiente: {ENV_CONTRACT_SCHEMA} (caminho do schema), {ENV_EQC_ROOT} "
        f"(pasta .../EQC) ou {ENV_LEADFARM_ROOT} (raiz do LeadFarm)."
    )
