"""Campanha ativa -- lida no import, carimbada em cada lead, fonte das categorias aceitas.

O arquivo vive no EQC (camada compartilhada), porque o COMERCIAL lê o mesmo arquivo:
`<eqc_root>/config/campanha_ativa.json`. Formato e local documentados em `EQC/INDEX.md`.
Uma campanha ativa por vez. Sem caminho absoluto de máquina: a raiz vem de
`contrato.eqc_root()`; a env `QUALIFICADOR_CAMPANHA` (caminho final do arquivo) vence.

Campos mínimos: `id`, `nicho` (rótulo humano), `cidade`, `categorias_aceitas` (lista com
pelo menos um termo), `categorias_excluidas` (lista, pode ser vazia). Campos extras são
aceitos e ignorados aqui (o COMERCIAL acrescenta vocabulário de copy por nicho).

Arquivo ausente, JSON inválido ou campo mínimo faltando/errado => `CampanhaInvalidaError`,
levantado ANTES de o import gravar qualquer coisa (main.importar_csv). $0, sem LLM.
"""
import json
import os
import unicodedata

import contrato

ENV_CAMINHO = "QUALIFICADOR_CAMPANHA"
_CAMPANHA_REL = ("config", "campanha_ativa.json")

MOTIVO_FORA_DO_PERFIL = "icp_categoria_fora_do_perfil"
MOTIVO_EXCLUIDA = "icp_categoria_excluida"


class CampanhaInvalidaError(Exception):
    """Campanha ativa ausente ou inválida. Falha alta: o import não grava nada."""


def caminho_campanha() -> str:
    """`QUALIFICADOR_CAMPANHA` (caminho final) tem precedência; senão
    `<eqc_root>/config/campanha_ativa.json`. Lê o ambiente a cada chamada."""
    return (os.environ.get(ENV_CAMINHO) or "").strip() or str(contrato.eqc_root().joinpath(*_CAMPANHA_REL))


def normalizar(texto) -> str:
    """Sem acento e sem maiúscula -- base de toda comparação de categoria e de marca."""
    decomposto = unicodedata.normalize("NFKD", texto or "")
    return "".join(c for c in decomposto if not unicodedata.combining(c)).lower().strip()


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


def carregar_campanha(caminho=None) -> dict:
    """Lê e valida a campanha ativa. Nunca cai em default: sem campanha válida, o import para."""
    caminho = caminho or caminho_campanha()
    if not os.path.isfile(caminho):
        raise CampanhaInvalidaError(
            f"Campanha ativa não encontrada em '{caminho}'. Crie o arquivo (formato em EQC/INDEX.md) "
            f"ou aponte {ENV_CAMINHO} para ele. Nada foi importado.")
    try:
        with open(caminho, "r", encoding="utf-8") as f:
            dados = json.load(f)
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise CampanhaInvalidaError(f"Campanha ativa em '{caminho}' não é JSON válido ({e}). Nada foi importado.")
    return validar_campanha(dados, origem=caminho)


def carimbo(campanha) -> dict:
    """Campos gravados em `dados_empresa` de cada lead importado sob esta campanha."""
    return {"campanha_id": campanha["id"], "campanha_nicho": campanha["nicho"]}


def motivo_categoria(nicho, campanha):
    """(motivo, termo) do corte de categoria, ou None se o lead está no perfil da campanha.

    Termo contido na categoria do Google (`nicho`, já corrigido nas linhas deslocadas),
    sem acento e sem maiúscula. Excluída vence aceita. `termo` é o termo excluído que bateu
    (None no corte por fora do perfil)."""
    categoria = normalizar(nicho)
    for termo in campanha.get("categorias_excluidas") or []:
        if normalizar(termo) in categoria:
            return MOTIVO_EXCLUIDA, termo
    if not any(normalizar(t) in categoria for t in campanha.get("categorias_aceitas") or []):
        return MOTIVO_FORA_DO_PERFIL, None
    return None
