"""Atalho de troca de campanha (trocar_campanha.py). Tudo em tmp_path: nunca toca o
campanha_ativa.json real. Em todo erro, o arquivo ativo fica byte a byte igual."""
import io
import json

import pytest

import campanha
import trocar_campanha

CAMPANHAS = {
    "psicologos.json": {"id": "psicologos-x", "nicho": "Psicólogos", "cidade_padrao": "Alicante",
                        "categorias_aceitas": ["psicólog"], "categorias_excluidas": []},
    "abogados.json": {"id": "abogados-x", "nicho": "Abogados", "cidade_padrao": "Alicante",
                      "categorias_aceitas": ["abogad", "bufete"], "categorias_excluidas": []},
    "arquitectos.json": {"id": "arquitectos-x", "nicho": "Arquitectos", "cidade_padrao": "Elche",
                         "categorias_aceitas": ["arquitect"], "categorias_excluidas": []},
}
ATIVA_INICIAL = (b'{"id": "antiga", "nicho": "Antigo", "cidade_padrao": "Lugar", '
                 b'"categorias_aceitas": ["x"], "categorias_excluidas": []}\n')


@pytest.fixture
def ambiente(tmp_path, monkeypatch):
    pasta = tmp_path / "campanhas"
    pasta.mkdir()
    for nome, dados in CAMPANHAS.items():
        (pasta / nome).write_text(json.dumps(dados, ensure_ascii=False), encoding="utf-8")
    ativa = tmp_path / "campanha_ativa.json"
    ativa.write_bytes(ATIVA_INICIAL)
    monkeypatch.setenv(trocar_campanha.ENV_DIR_CAMPANHAS, str(pasta))
    monkeypatch.setenv(campanha.ENV_CAMINHO, str(ativa))
    return pasta, ativa


def _rodar(escolha):
    saida = io.StringIO()
    codigo = trocar_campanha.executar(io.StringIO(escolha), saida)
    return codigo, saida.getvalue()


# ordem alfabética dos arquivos: 1 abogados, 2 arquitectos, 3 psicologos
@pytest.mark.parametrize("opcao,nome", [("1", "abogados.json"), ("2", "arquitectos.json"),
                                        ("3", "psicologos.json")])
def test_escolhe_cada_campanha(ambiente, opcao, nome):
    _, ativa = ambiente
    codigo, tela = _rodar(opcao + "\n")
    assert codigo == 0
    esperado = CAMPANHAS[nome]
    assert json.loads(ativa.read_text(encoding="utf-8")) == esperado
    assert esperado["id"] in tela and "Campanha ativa agora" in tela
    assert not list(ativa.parent.glob(".campanha_ativa_*"))  # sem temporário sobrando


@pytest.mark.parametrize("entrada", ["\n", "", "x\n", "9\n", "0\n", "-1\n", "1.5\n"])
def test_opcao_invalida_nao_altera(ambiente, entrada):
    _, ativa = ambiente
    codigo, tela = _rodar(entrada)
    assert codigo == 1
    assert ativa.read_bytes() == ATIVA_INICIAL
    assert "Nada foi alterado" in tela


def test_campanha_corrompida_nao_altera(ambiente):
    pasta, ativa = ambiente
    (pasta / "abogados.json").write_text("{ isto nao e json", encoding="utf-8")
    codigo, tela = _rodar("1\n")
    assert codigo == 1
    assert ativa.read_bytes() == ATIVA_INICIAL
    assert "Nada foi alterado" in tela and "problema" in tela


def test_campanha_sem_campo_obrigatorio_nao_altera(ambiente):
    pasta, ativa = ambiente
    (pasta / "abogados.json").write_text(json.dumps({"id": "so-id"}), encoding="utf-8")
    codigo, _ = _rodar("1\n")
    assert codigo == 1 and ativa.read_bytes() == ATIVA_INICIAL


def test_corrompida_nao_impede_outra_valida(ambiente):
    pasta, ativa = ambiente
    (pasta / "abogados.json").write_text("lixo", encoding="utf-8")
    codigo, _ = _rodar("3\n")
    assert codigo == 0
    assert json.loads(ativa.read_text(encoding="utf-8"))["id"] == "psicologos-x"


def test_pasta_sem_campanhas_nao_altera(tmp_path, monkeypatch):
    ativa = tmp_path / "ativa.json"
    ativa.write_bytes(ATIVA_INICIAL)
    monkeypatch.setenv(trocar_campanha.ENV_DIR_CAMPANHAS, str(tmp_path / "inexistente"))
    monkeypatch.setenv(campanha.ENV_CAMINHO, str(ativa))
    codigo, tela = _rodar("1\n")
    assert codigo == 1 and ativa.read_bytes() == ATIVA_INICIAL and "nenhuma campanha" in tela


def test_menu_marca_a_ativa(ambiente):
    _, ativa = ambiente
    ativa.write_text(json.dumps(CAMPANHAS["arquitectos.json"]), encoding="utf-8")
    _, tela = _rodar("\n")
    linha = [ln for ln in tela.splitlines() if "arquitectos-x" in ln][0]
    assert "ativa agora" in linha
    assert sum("ativa agora" in ln for ln in tela.splitlines()) == 1


def test_menu_mostra_o_nicho_e_a_cidade_padrao(ambiente):
    """Multicidade (06/10/2026): o menu escolhe o nicho; a cidade padrão aparece como tal."""
    _, tela = _rodar("\n")
    linha = [ln for ln in tela.splitlines() if "arquitectos-x" in ln][0]
    assert "Arquitectos (cidade padrão Elche)" in linha


def test_campanha_no_formato_antigo_com_cidade_e_recusada(ambiente):
    """Arquivo com `cidade` e sem `cidade_padrao` (formato anterior à multicidade) não vale."""
    pasta, ativa = ambiente
    antigo = {k: v for k, v in CAMPANHAS["abogados.json"].items() if k != "cidade_padrao"}
    (pasta / "abogados.json").write_text(json.dumps({**antigo, "cidade": "Alicante"}), encoding="utf-8")
    codigo, tela = _rodar("1\n")
    assert codigo == 1 and ativa.read_bytes() == ATIVA_INICIAL and "Nada foi alterado" in tela


def test_falha_de_gravacao_restaura(ambiente, monkeypatch):
    _, ativa = ambiente
    chamadas = {"n": 0}
    real = trocar_campanha._gravar_atomico

    def gravar_corrompendo(destino, conteudo):
        chamadas["n"] += 1
        real(destino, b"{ corrompido" if chamadas["n"] == 1 else conteudo)

    monkeypatch.setattr(trocar_campanha, "_gravar_atomico", gravar_corrompendo)
    codigo, tela = _rodar("1\n")
    assert codigo == 1 and ativa.read_bytes() == ATIVA_INICIAL and "Nada foi alterado" in tela
