"""campanha.py — validação da campanha do lado do COMERCIAL (Etapa 2, 2.4; multicidade, 06/10/2026).

O formato é o MESMO que o QUALIFICADOR lê no import (`EQC/config/campanhas/*.json` e
`EQC/config/campanha_ativa.json`; formato em `EQC/INDEX.md` §3-C). Resolução do arquivo ativo
igual à de `qualificador/prospeccao_ia/campanha.py`, com a raiz do EQC vinda de
`eqc.eqc_root()` — nenhum caminho absoluto de máquina. A env `COMERCIAL_CAMPANHA` (caminho
final do arquivo) vence; existe para teste, não para a operação.

Desde o contrato 2.3.0 (multicidade) o COMERCIAL não precisa mais ler campanha para montar a
planilha: a cidade de cada lead chega no próprio lead (`campanha_cidade`, contrato na Nata e
CSV humano na Geral). Este módulo continua como a cópia do COMERCIAL da validação da
campanha (os módulos não importam código um do outro) — `tests/test_campanha_sincronia.py`
falha se ela divergir da do QUALIFICADOR.

Campanha ausente, JSON inválido ou campo mínimo faltando/errado => `CampanhaInvalidaError`
(falha alta, nunca um default silencioso). Os campos conferidos são os mesmos do
QUALIFICADOR (`id`, `nicho`, `cidade_padrao`, `categorias_aceitas`, `categorias_excluidas` e,
quando presente, `termos_de_busca`). Campos extras são aceitos e ignorados aqui. Só leitura;
$0, sem LLM.
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
    """Campanha ativa ausente ou inválida. Falha alta."""


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
    for campo in ("id", "nicho", "cidade_padrao"):
        _texto_obrigatorio(dados, campo, erros)
    _lista_de_termos(dados, "categorias_aceitas", erros, pode_ser_vazia=False)
    _lista_de_termos(dados, "categorias_excluidas", erros, pode_ser_vazia=True)
    if "termos_de_busca" in dados:
        _lista_de_termos(dados, "termos_de_busca", erros, pode_ser_vazia=False)
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
