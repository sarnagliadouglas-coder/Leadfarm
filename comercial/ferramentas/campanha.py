"""campanha.py — leitura da campanha ativa do lado do COMERCIAL (Etapa 2, 2.4).

O arquivo é o MESMO que o QUALIFICADOR lê no import: `<eqc_root>/config/campanha_ativa.json`
(configuração compartilhada, formato em `EQC/INDEX.md` §3-C). Resolução igual à de
`qualificador/prospeccao_ia/campanha.py`, com a raiz do EQC vinda de `eqc.eqc_root()` —
nenhum caminho absoluto de máquina. A env `COMERCIAL_CAMPANHA` (caminho final do arquivo)
vence; existe para teste apontar uma campanha em `tmp_path`, não para a operação.

Substitui `config/cidade_da_busca.json` (aposentado na Etapa 2): a cidade usada no nome
curto (`angulo_mensagem.nome_curto_seguro`) e nas palavras genéricas do validador passa a
ser a `cidade` da campanha ativa. Trocar de cidade = trocar a campanha ativa, sem tocar o
COMERCIAL.

Campanha ausente, JSON inválido ou campo mínimo faltando/errado => `CampanhaInvalidaError`
(falha alta, nunca um default silencioso). Os campos mínimos conferidos são os mesmos do
QUALIFICADOR (`id`, `nicho`, `cidade`, `categorias_aceitas`, `categorias_excluidas`), para
que os dois lados nunca discordem sobre o que é uma campanha válida. Campos extras são
aceitos e ignorados aqui. Só leitura; $0, sem LLM.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

try:
    import eqc
except ModuleNotFoundError:  # pragma: no cover - bootstrap de sys.path
    import sys as _sys

    _sys.path.insert(0, str(Path(__file__).resolve().parent))
    import eqc

ENV_CAMINHO = "COMERCIAL_CAMPANHA"
_CAMPANHA_REL = ("config", "campanha_ativa.json")


class CampanhaInvalidaError(Exception):
    """Campanha ativa ausente ou inválida. Falha alta: nenhuma mensagem é montada sem ela."""


def caminho_campanha() -> Path:
    """`COMERCIAL_CAMPANHA` (caminho final) tem precedência; senão
    `<eqc_root>/config/campanha_ativa.json`. Lê o ambiente a cada chamada."""
    override = (os.environ.get(ENV_CAMINHO) or "").strip()
    return Path(override) if override else eqc.eqc_root().joinpath(*_CAMPANHA_REL)


def _texto_obrigatorio(dados, campo, erros):
    valor = dados.get(campo)
    if not isinstance(valor, str) or not valor.strip():
        erros.append(f"'{campo}' ausente ou vazio (texto obrigatório)")


def _lista_de_termos(dados, campo, erros, pode_ser_vazia):
    if campo not in dados:
        erros.append(f"'{campo}' ausente (lista obrigatória)")
        return
    valor = dados[campo]
    if not isinstance(valor, list) or not all(isinstance(t, str) and t.strip() for t in valor):
        erros.append(f"'{campo}' deve ser uma lista de textos não vazios")
    elif not valor and not pode_ser_vazia:
        erros.append(f"'{campo}' precisa de pelo menos um termo")


def validar_campanha(dados, origem="campanha") -> dict:
    """Devolve a própria campanha se válida; senão levanta listando TODOS os problemas."""
    if not isinstance(dados, dict):
        raise CampanhaInvalidaError(f"{origem}: o conteúdo deve ser um objeto JSON.")
    erros = []
    for campo in ("id", "nicho", "cidade"):
        _texto_obrigatorio(dados, campo, erros)
    _lista_de_termos(dados, "categorias_aceitas", erros, pode_ser_vazia=False)
    _lista_de_termos(dados, "categorias_excluidas", erros, pode_ser_vazia=True)
    if erros:
        raise CampanhaInvalidaError(f"{origem}: campanha ativa inválida -- " + "; ".join(erros) + ".")
    return dados


def carregar_campanha(caminho: Optional[Path] = None) -> dict:
    """Lê e valida a campanha ativa. Nunca cai em default."""
    caminho = Path(caminho) if caminho else caminho_campanha()
    if not caminho.is_file():
        raise CampanhaInvalidaError(
            f"Campanha ativa não encontrada em '{caminho}'. O COMERCIAL lê a mesma campanha do "
            f"QUALIFICADOR (EQC/config/campanha_ativa.json, formato em EQC/INDEX.md); troque a "
            f"campanha pelo atalho do QUALIFICADOR ou aponte {ENV_CAMINHO} para o arquivo (só teste)."
        )
    try:
        dados = json.loads(caminho.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise CampanhaInvalidaError(f"Campanha ativa em '{caminho}' não é JSON válido ({e}).") from e
    return validar_campanha(dados, origem=str(caminho))


def cidade_da_campanha(caminho: Optional[Path] = None) -> str:
    """`cidade` da campanha ativa (texto não vazio -- garantido pela validação)."""
    return carregar_campanha(caminho)["cidade"].strip()
