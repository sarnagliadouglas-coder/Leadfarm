"""Testes de llm_cliente.py — NENHUM faz chamada real à API. Todo teste
injeta um cliente simulado (`cliente=`); a chave usada é sempre um valor
fixo de teste, nunca uma chave real."""

import pytest

import env_loader
import llm_config
from custo_llm import Uso
from llm_cliente import chamar_llm


class _ContentBlock:
    def __init__(self, type_, text=None):
        self.type = type_
        self.text = text


class _UsageFalso:
    def __init__(self, input_tokens=10, output_tokens=20):
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens


class _RespostaFalsa:
    def __init__(self, content, usage=None):
        self.content = content
        self.usage = usage or _UsageFalso()


class _ClienteFalso:
    """Simula `anthropic.Anthropic().messages.create(...)`. Registra a
    chamada para os testes conferirem que (ou que não) foi acionado."""

    def __init__(self, resposta):
        self._resposta = resposta
        self.chamadas = []

        class _Messages:
            def __init__(self, outer):
                self._outer = outer

            def create(self, **kwargs):
                self._outer.chamadas.append(kwargs)
                return self._outer._resposta

        self.messages = _Messages(self)


@pytest.fixture(autouse=True)
def _sem_env_real(tmp_path, monkeypatch):
    monkeypatch.setattr(env_loader, "_ENV_PATH", tmp_path / "nao-existe.env")
    monkeypatch.delenv(llm_config.ENV_API_KEY, raising=False)
    monkeypatch.delenv(llm_config.ENV_MODEL, raising=False)


def test_chamar_llm_extrai_texto_e_uso_de_uma_resposta_simulada(monkeypatch):
    monkeypatch.setenv(llm_config.ENV_API_KEY, "chave-de-teste-fake")
    resposta = _RespostaFalsa(
        content=[_ContentBlock("text", "resposta do modelo")],
        usage=_UsageFalso(input_tokens=123, output_tokens=456),
    )
    cliente = _ClienteFalso(resposta)

    resultado = chamar_llm(
        [{"role": "user", "content": "oi"}],
        modelo="modelo-de-teste",
        cliente=cliente,
    )

    assert resultado.texto == "resposta do modelo"
    assert resultado.uso == Uso(input_tokens=123, output_tokens=456)
    assert resultado.modelo == "modelo-de-teste"
    assert len(cliente.chamadas) == 1
    assert cliente.chamadas[0]["model"] == "modelo-de-teste"


def test_chamar_llm_ignora_blocos_que_nao_sao_texto(monkeypatch):
    """Blocos `thinking` (ou outro tipo) não entram no texto extraído — só
    `type == 'text'`."""
    monkeypatch.setenv(llm_config.ENV_API_KEY, "chave-de-teste-fake")
    resposta = _RespostaFalsa(
        content=[
            _ContentBlock("thinking", "raciocínio interno"),
            _ContentBlock("text", "parte 1. "),
            _ContentBlock("text", "parte 2."),
        ]
    )
    cliente = _ClienteFalso(resposta)

    resultado = chamar_llm([{"role": "user", "content": "oi"}], cliente=cliente)

    assert resultado.texto == "parte 1. parte 2."
    assert "raciocínio" not in resultado.texto


def test_chamar_llm_sem_chave_nao_chama_o_cliente_nem_a_rede(monkeypatch):
    """Controle negativo: mesmo com um cliente simulado injetado, sem chave
    a função falha ANTES de tocar nele — prova que a checagem de chave não é
    contornável passando `cliente=`."""
    resposta = _RespostaFalsa(content=[_ContentBlock("text", "nunca deveria chegar aqui")])
    cliente = _ClienteFalso(resposta)

    with pytest.raises(llm_config.ChaveApiAusenteError):
        chamar_llm([{"role": "user", "content": "oi"}], cliente=cliente)

    assert cliente.chamadas == []


def test_chamar_llm_modelo_omitido_resolve_pela_configuracao(monkeypatch, tmp_path):
    """Sem `modelo=` explícito, usa llm_config.resolver_modelo() — aqui
    fixado por env para não depender do default real do arquivo."""
    monkeypatch.setenv(llm_config.ENV_API_KEY, "chave-de-teste-fake")
    monkeypatch.setenv(llm_config.ENV_MODEL, "modelo-vindo-da-config")
    resposta = _RespostaFalsa(content=[_ContentBlock("text", "ok")])
    cliente = _ClienteFalso(resposta)

    resultado = chamar_llm([{"role": "user", "content": "oi"}], cliente=cliente)

    assert resultado.modelo == "modelo-vindo-da-config"
    assert cliente.chamadas[0]["model"] == "modelo-vindo-da-config"
