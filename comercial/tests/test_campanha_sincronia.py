"""Sincronia das regras de campanha ativa entre COMERCIAL e QUALIFICADOR (diretor, 06/10/2026).

Os dois módulos leem o mesmo `EQC/config/campanha_ativa.json`, cada um com a própria cópia
da validação (`comercial/ferramentas/campanha.py` e `qualificador/prospeccao_ia/campanha.py`)
-- os módulos não importam código um do outro. Este teste é a rede, no mesmo padrão de
`test_fixture_do_schema_bate_com_o_contrato_instalado`: roda a MESMA bateria de arquivos de
campanha (válidos, campo faltando, tipo errado, vazio, JSON inválido, arquivo ausente) pelas
duas cópias e falha se uma aceitar o que a outra recusa, ou se recusarem por motivos
diferentes. O QUALIFICADOR só é LIDO (código-fonte carregado em módulo isolado, com um
`contrato` de mentira: só `caminho_campanha` o usa, e ele não é exercitado aqui).

A prova de que o teste derruba uma divergência (cópia alterada no scratchpad) está no
relatório da tarefa 2C; `comparar_validacoes` é a função usada nas duas pontas.
"""

from __future__ import annotations

import copy
import importlib.util
import json
import sys
import types
from pathlib import Path

import pytest

_COMERCIAL_CAMPANHA = Path(__file__).resolve().parent.parent / "ferramentas" / "campanha.py"
_QUALIFICADOR_CAMPANHA = (
    Path(__file__).resolve().parent.parent.parent / "qualificador" / "prospeccao_ia" / "campanha.py"
)

_VALIDA = {
    "id": "teste-sincronia",
    "nicho": "Teste",
    "cidade": "Alicante",
    "categorias_aceitas": ["teste"],
    "categorias_excluidas": [],
}
_CAMPOS = tuple(_VALIDA)


def carregar_modulo_isolado(caminho: Path, nome: str):
    """Carrega um `campanha.py` pelo caminho, sem tocar `sys.modules` de fora: o import de
    `contrato`/`eqc` que o arquivo faz recebe um módulo de mentira só durante a carga."""
    falsos = {}
    for dep in ("contrato", "eqc"):
        falso = types.ModuleType(dep)
        falso.eqc_root = lambda: Path("EQC-de-mentira")
        falsos[dep] = falso
    guardados = {k: sys.modules.get(k) for k in falsos}
    sys.modules.update(falsos)
    try:
        spec = importlib.util.spec_from_file_location(nome, caminho)
        modulo = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(modulo)
    finally:
        for k, v in guardados.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v
    return modulo


def _casos():
    """(nome, conteúdo) -- conteúdo dict/list = JSON; bytes = arquivo cru; None = arquivo ausente."""
    casos = [("valida", _VALIDA), ("valida com campo extra", {**_VALIDA, "copy": {"x": 1}}),
             ("excluidas com termos", {**_VALIDA, "categorias_excluidas": ["a", "b"]})]
    for campo in _CAMPOS:
        sem = dict(_VALIDA)
        del sem[campo]
        casos.append((f"sem {campo}", sem))
        for rotulo, valor in (("None", None), ("int", 7), ("texto vazio", ""), ("espaços", "   "),
                              ("lista vazia", []), ("lista com vazio", ["ok", ""]),
                              ("lista com int", ["ok", 3]), ("objeto", {"a": 1})):
            casos.append((f"{campo} = {rotulo}", {**_VALIDA, campo: copy.deepcopy(valor)}))
    casos += [
        ("raiz é lista", [_VALIDA]),
        ("raiz é texto", "campanha"),
        ("JSON inválido", b"{ isto nao e json"),
        ("não UTF-8", b"\xff\xfe\x00{"),
        ("arquivo ausente", None),
    ]
    return casos


def _resultado(modulo, caminho: Path):
    """("aceita", dados) ou ("recusa", motivo-normalizado). Para recusa por validação de
    campo, o motivo é a lista de problemas (sem a origem nem o fecho de cada módulo)."""
    try:
        return ("aceita", modulo.carregar_campanha(str(caminho)))
    except Exception as e:  # a classe é conferida pelo nome, não pela identidade
        if type(e).__name__ != "CampanhaInvalidaError":
            return ("erro inesperado", f"{type(e).__name__}: {e}")
        texto = str(e)
        if "campanha ativa inválida --" in texto:
            return ("recusa", texto.split("campanha ativa inválida --", 1)[1].strip().rstrip("."))
        if "deve ser um objeto JSON" in texto:
            return ("recusa", "não é objeto JSON")
        if "não encontrada" in texto:
            return ("recusa", "arquivo ausente")
        if "não é JSON válido" in texto:
            return ("recusa", "JSON inválido")
        return ("recusa", "motivo não classificado: " + texto)


def comparar_validacoes(modulo_a, modulo_b, diretorio: Path) -> list:
    """Divergências (lista vazia = em sincronia) entre duas cópias da validação."""
    divergencias = []
    for i, (nome, conteudo) in enumerate(_casos()):
        caminho = Path(diretorio) / f"caso_{i}.json"
        if conteudo is None:
            caminho = Path(diretorio) / f"ausente_{i}.json"
        elif isinstance(conteudo, bytes):
            caminho.write_bytes(conteudo)
        else:
            caminho.write_text(json.dumps(conteudo, ensure_ascii=False), encoding="utf-8")
        a, b = _resultado(modulo_a, caminho), _resultado(modulo_b, caminho)
        if a != b:
            divergencias.append(f"{nome}: {a!r} != {b!r}")
    return divergencias


def test_bateria_tem_casos_que_aceitam_e_que_recusam(tmp_path):
    """A bateria exercita as duas pontas: há caso aceito e caso recusado em cada motivo."""
    comercial = carregar_modulo_isolado(_COMERCIAL_CAMPANHA, "_campanha_comercial")
    tipos = set()
    for i, (nome, conteudo) in enumerate(_casos()):
        caminho = tmp_path / f"c{i}.json"
        if isinstance(conteudo, bytes):
            caminho.write_bytes(conteudo)
        elif conteudo is not None:
            caminho.write_text(json.dumps(conteudo, ensure_ascii=False), encoding="utf-8")
        status, motivo = _resultado(comercial, caminho)
        assert status != "erro inesperado", (nome, motivo)
        tipos.add(status if status == "aceita" else motivo.split(" ")[0] if motivo.startswith("'") else motivo)
    assert "aceita" in tipos
    assert {"arquivo ausente", "JSON inválido", "não é objeto JSON"} <= tipos
    assert any(t.startswith("'") for t in tipos)  # recusa por campo


def test_regras_de_campanha_do_comercial_e_do_qualificador_estao_em_sincronia(tmp_path):
    if not _QUALIFICADOR_CAMPANHA.is_file():
        pytest.skip("qualificador/prospeccao_ia/campanha.py não existe nesta árvore")
    comercial = carregar_modulo_isolado(_COMERCIAL_CAMPANHA, "_campanha_comercial")
    qualificador = carregar_modulo_isolado(_QUALIFICADOR_CAMPANHA, "_campanha_qualificador")
    divergencias = comparar_validacoes(comercial, qualificador, tmp_path)
    assert not divergencias, (
        "comercial/ferramentas/campanha.py e qualificador/prospeccao_ia/campanha.py divergem na "
        "validação da campanha ativa -- alinhe as duas cópias (decisão do diretor):\n"
        + "\n".join(divergencias)
    )


def test_controle_negativo_regra_divergente_e_detectada(tmp_path):
    """Uma cópia com UMA regra diferente (categorias_excluidas deixa de ser obrigatória)
    tem de ser pega pela mesma comparação."""
    fonte = _COMERCIAL_CAMPANHA.read_text(encoding="utf-8")
    alvo = '_lista_de_termos(dados, "categorias_excluidas", erros, pode_ser_vazia=True)'
    assert fonte.count(alvo) == 1
    copia = tmp_path / "campanha_divergente.py"
    copia.write_text(
        fonte.replace(alvo, 'dados.get("categorias_excluidas") is None or ' + alvo), encoding="utf-8",
    )
    comercial = carregar_modulo_isolado(_COMERCIAL_CAMPANHA, "_campanha_comercial")
    divergente = carregar_modulo_isolado(copia, "_campanha_divergente")
    casos_dir = tmp_path / "casos"
    casos_dir.mkdir()
    divergencias = comparar_validacoes(comercial, divergente, casos_dir)
    assert any(d.startswith("sem categorias_excluidas") for d in divergencias)
    assert any(d.startswith("categorias_excluidas = None") for d in divergencias)
