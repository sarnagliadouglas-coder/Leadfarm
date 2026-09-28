"""Testes de llm_config.py — nenhuma chamada de rede. Isola de comercial/.env
real apontando env_loader para um arquivo que não existe, para o teste não
depender (nem ser afetado) pelo .env de verdade da máquina."""

import json

import pytest

import env_loader
import llm_config


@pytest.fixture(autouse=True)
def _sem_env_real(tmp_path, monkeypatch):
    """Impede que comercial/.env real (se existir na máquina de quem roda o
    teste) vaze para dentro da suíte, e limpa as variáveis entre testes."""
    monkeypatch.setattr(env_loader, "_ENV_PATH", tmp_path / "nao-existe.env")
    monkeypatch.delenv(llm_config.ENV_API_KEY, raising=False)
    monkeypatch.delenv(llm_config.ENV_MODEL, raising=False)


def test_resolver_api_key_ausente_levanta_erro_com_instrucao(monkeypatch):
    with pytest.raises(llm_config.ChaveApiAusenteError) as exc:
        llm_config.resolver_api_key()
    mensagem = str(exc.value)
    assert llm_config.ENV_API_KEY in mensagem
    assert ".env" in mensagem
    assert "Nenhuma chamada foi feita" in mensagem


def test_resolver_api_key_presente_devolve_o_valor(monkeypatch):
    monkeypatch.setenv(llm_config.ENV_API_KEY, "chave-de-teste-fake")
    assert llm_config.resolver_api_key() == "chave-de-teste-fake"


def test_carregar_tabela_precos_le_o_arquivo_de_verdade():
    """Controle: o arquivo real de configuração (não um fixture) tem o
    formato que o código exige — se alguém editar precos_llm.json e quebrar
    o formato, este teste acusa."""
    tabela = llm_config.carregar_tabela_precos()
    assert "modelo_default" in tabela
    assert tabela["modelo_default"] in tabela["precos_por_modelo"]


def test_carregar_tabela_precos_arquivo_ausente_levanta_erro_claro(tmp_path):
    with pytest.raises(llm_config.TabelaPrecosInvalidaError, match="não encontrada"):
        llm_config.carregar_tabela_precos(tmp_path / "nao-existe.json")


def test_carregar_tabela_precos_json_invalido_levanta_erro_claro(tmp_path):
    caminho = tmp_path / "precos.json"
    caminho.write_text("{ isso nao e json", encoding="utf-8")
    with pytest.raises(llm_config.TabelaPrecosInvalidaError, match="JSON válido"):
        llm_config.carregar_tabela_precos(caminho)


def test_carregar_tabela_precos_sem_chaves_exigidas_levanta_erro_claro(tmp_path):
    caminho = tmp_path / "precos.json"
    caminho.write_text(json.dumps({"algo": "sem nada a ver"}), encoding="utf-8")
    with pytest.raises(llm_config.TabelaPrecosInvalidaError):
        llm_config.carregar_tabela_precos(caminho)


def test_resolver_modelo_usa_default_da_tabela_quando_env_ausente():
    tabela = {"modelo_default": "modelo-x", "precos_por_modelo": {"modelo-x": {}}}
    assert llm_config.resolver_modelo(tabela) == "modelo-x"


def test_resolver_modelo_env_vence_o_default_da_tabela(monkeypatch):
    monkeypatch.setenv(llm_config.ENV_MODEL, "modelo-escolhido-por-env")
    tabela = {"modelo_default": "modelo-x", "precos_por_modelo": {"modelo-x": {}}}
    assert llm_config.resolver_modelo(tabela) == "modelo-escolhido-por-env"
