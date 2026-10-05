"""Filtro de redes / multiunidade, aplicado no import (main.importar_csv). $0, sem LLM,
determinístico. Listas e limiar em `config/rede_multiunidade.json`, nunca no código.

1. Marca: nome do lead (sem acento, sem maiúscula) contém uma marca da lista como palavra
   inteira -> descarte `rede_ou_multiunidade`.
2. Grupos: fichas agrupadas por telefone normalizado (`telefone_utils.numero_nacional_espanhol`,
   9+ dígitos) e por domínio do site próprio (`site_classificacao`: só classe "proprio" forma
   grupo -- portal, construtor, rede social e superfície do Google não). O conjunto agrupado é
   o POOL inteiro do QUALIFICADOR (inclusive reprovados) mais os leads novos do import.
   - grupo com `limiar_rede` (3) ou mais fichas: todas descartadas `rede_ou_multiunidade`;
   - grupo menor, com 2 ou mais: nenhuma descartada; cada uma recebe o aviso
     `possivel_mesmo_negocio` com o place_id da(s) outra(s).

Este módulo só calcula; quem grava (e move registros já no pool) é main.importar_csv.
"""
import json
import os
import re

import campanha
import site_classificacao
import telefone_utils

CAMINHO_CONFIG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config", "rede_multiunidade.json")
MOTIVO = "rede_ou_multiunidade"
POR_TELEFONE = "telefone"
POR_DOMINIO = "dominio"
POR_MARCA = "marca"
_MIN_DIGITOS_TELEFONE = 9


class ConfigRedeInvalidaError(Exception):
    """config/rede_multiunidade.json ausente ou inválido. Falha alta: o import não grava nada."""


def carregar_config(caminho=None) -> dict:
    caminho = caminho or CAMINHO_CONFIG  # resolvido na chamada (teste isola via monkeypatch)
    if not os.path.isfile(caminho):
        raise ConfigRedeInvalidaError(f"Config de redes não encontrada em '{caminho}'. Nada foi importado.")
    try:
        with open(caminho, "r", encoding="utf-8") as f:
            config = json.load(f)
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise ConfigRedeInvalidaError(f"Config de redes em '{caminho}' não é JSON válido ({e}). Nada foi importado.")
    erros = []
    limiar = config.get("limiar_rede") if isinstance(config, dict) else None
    if not isinstance(limiar, int) or isinstance(limiar, bool) or limiar < 2:
        erros.append("'limiar_rede' deve ser inteiro >= 2")
    marcas = config.get("marcas") if isinstance(config, dict) else None
    if not isinstance(marcas, list) or not all(isinstance(m, str) and m.strip() for m in marcas):
        erros.append("'marcas' deve ser uma lista de textos não vazios")
    if erros:
        raise ConfigRedeInvalidaError(f"Config de redes em '{caminho}' inválida -- " + "; ".join(erros) + ".")
    return config


def marca_no_nome(emp, marcas):
    """Primeira marca da lista que aparece no nome como palavra inteira, ou None."""
    nome = campanha.normalizar(emp.get("nome"))
    for marca in marcas:
        if re.search(r"\b" + re.escape(campanha.normalizar(marca)) + r"\b", nome):
            return marca
    return None


def chave_telefone(emp):
    numero = telefone_utils.numero_nacional_espanhol(emp.get("telefone"))
    return numero if len(numero) >= _MIN_DIGITOS_TELEFONE else None


def chave_dominio(emp):
    website = emp.get("website")
    if site_classificacao.classificar_site(website) != site_classificacao.PROPRIO:
        return None
    return site_classificacao._host(website)


def agrupar(fichas, limiar):
    """`fichas`: lista de dicts de lead (`dados_empresa`), uma por ficha distinta.

    Devolve (descartes, avisos), ambos indexados pela posição da ficha na lista:
      descartes[i] = {"por", "chave", "tamanho_grupo"} -- o 1º grupo >= limiar da ficha
                     (telefone antes de domínio);
      avisos[i]    = [{"place_id", "por", "chave"}, ...] -- as outras fichas dos grupos
                     com 2 <= tamanho < limiar."""
    grupos = {}
    for i, emp in enumerate(fichas):
        for por, funcao in ((POR_TELEFONE, chave_telefone), (POR_DOMINIO, chave_dominio)):
            chave = funcao(emp)
            if chave:
                grupos.setdefault((por, chave), []).append(i)

    descartes, avisos = {}, {}
    # sorted estável: grupos de telefone primeiro, ordem de inserção mantida dentro de cada tipo.
    for (por, chave), membros in sorted(grupos.items(), key=lambda kv: kv[0][0] != POR_TELEFONE):
        if len(membros) < 2:
            continue
        if len(membros) >= limiar:
            for i in membros:
                descartes.setdefault(i, {"por": por, "chave": chave, "tamanho_grupo": len(membros)})
            continue
        for i in membros:
            for j in membros:
                if i != j:
                    avisos.setdefault(i, []).append(
                        {"place_id": fichas[j].get("place_id"), "por": por, "chave": chave})
    for i in descartes:
        avisos.pop(i, None)
    return descartes, avisos
