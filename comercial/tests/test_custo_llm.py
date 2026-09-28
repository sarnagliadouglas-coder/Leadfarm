"""Testes de custo_llm.py — nenhuma chamada de rede. Uso é dado direto
(fato simulado); custo é a única coisa calculada aqui (derivado)."""

import pytest

from custo_llm import ModeloSemPrecoError, Uso, calcular_custo_usd, uso_de_resposta


class _UsageFalso:
    def __init__(self, input_tokens, output_tokens, cache_creation=None, cache_read=None):
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        if cache_creation is not None:
            self.cache_creation_input_tokens = cache_creation
        if cache_read is not None:
            self.cache_read_input_tokens = cache_read


class _RespostaFalsa:
    def __init__(self, usage):
        self.usage = usage


_TABELA = {
    "modelo_default": "modelo-a",
    "precos_por_modelo": {
        "modelo-a": {
            "entrada": 2.0,
            "saida": 10.0,
            "cache_escrita": 2.5,
            "cache_leitura": 0.2,
        },
        "modelo-b": {
            "entrada": 5.0,
            "saida": 25.0,
            "cache_escrita": 6.25,
            "cache_leitura": 0.5,
        },
    },
}


def test_uso_de_resposta_extrai_os_quatro_campos():
    resposta = _RespostaFalsa(_UsageFalso(1000, 2000, cache_creation=300, cache_read=400))
    uso = uso_de_resposta(resposta)
    assert uso == Uso(
        input_tokens=1000,
        output_tokens=2000,
        cache_creation_input_tokens=300,
        cache_read_input_tokens=400,
    )


def test_uso_de_resposta_sem_campos_de_cache_conta_como_zero():
    """Resposta sem cache (a maioria) não traz essas chaves no objeto real da
    API — precisa não quebrar e não inventar valor."""
    resposta = _RespostaFalsa(_UsageFalso(500, 100))
    uso = uso_de_resposta(resposta)
    assert uso.cache_creation_input_tokens == 0
    assert uso.cache_read_input_tokens == 0


def test_calcular_custo_usd_soma_as_quatro_categorias():
    uso = Uso(
        input_tokens=1_000_000,
        output_tokens=1_000_000,
        cache_creation_input_tokens=1_000_000,
        cache_read_input_tokens=1_000_000,
    )
    custo = calcular_custo_usd(uso, "modelo-a", _TABELA)
    # 1 MTok de cada categoria, ao preço cheio de cada uma
    assert custo == pytest.approx(2.0 + 10.0 + 2.5 + 0.2)


def test_calcular_custo_usd_cada_categoria_pesa_seu_proprio_preco():
    """Prova de não-vacuidade: isolar cada campo de token e conferir que só o
    preço daquela categoria entra no resultado — pega uma mutação que trocasse
    o preço usado (ex.: usar 'saida' para 'cache_leitura')."""
    so_entrada = Uso(input_tokens=1_000_000, output_tokens=0)
    so_saida = Uso(input_tokens=0, output_tokens=1_000_000)
    so_cache_escrita = Uso(
        input_tokens=0, output_tokens=0, cache_creation_input_tokens=1_000_000
    )
    so_cache_leitura = Uso(
        input_tokens=0, output_tokens=0, cache_read_input_tokens=1_000_000
    )
    assert calcular_custo_usd(so_entrada, "modelo-a", _TABELA) == pytest.approx(2.0)
    assert calcular_custo_usd(so_saida, "modelo-a", _TABELA) == pytest.approx(10.0)
    assert calcular_custo_usd(so_cache_escrita, "modelo-a", _TABELA) == pytest.approx(2.5)
    assert calcular_custo_usd(so_cache_leitura, "modelo-a", _TABELA) == pytest.approx(0.2)


def test_calcular_custo_usd_troca_de_modelo_troca_a_tabela_usada():
    uso = Uso(input_tokens=1_000_000, output_tokens=0)
    assert calcular_custo_usd(uso, "modelo-a", _TABELA) == pytest.approx(2.0)
    assert calcular_custo_usd(uso, "modelo-b", _TABELA) == pytest.approx(5.0)


def test_calcular_custo_usd_modelo_sem_preco_levanta_erro_claro():
    """Controle negativo: sem preço cadastrado, nunca deriva custo zero em
    silêncio — a ausência de preço é um erro, não um valor."""
    uso = Uso(input_tokens=1000, output_tokens=1000)
    with pytest.raises(ModeloSemPrecoError, match="modelo-inexistente"):
        calcular_custo_usd(uso, "modelo-inexistente", _TABELA)
