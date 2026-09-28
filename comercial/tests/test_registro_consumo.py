"""Testes de registro_consumo.py — sempre em tmp_path, nunca na pasta real
comercial/_consumo_llm (guardiao_producao não vigia essa pasta porque o
código não tem caminho padrão para ela; os testes isolam por conta própria)."""

import json
from datetime import datetime, timezone

import pytest

from custo_llm import Uso
from registro_consumo import registrar_chamada, resumo_rodada


def test_registrar_chamada_grava_uma_linha_json_com_os_campos_esperados(tmp_path):
    caminho = tmp_path / "rodada.jsonl"
    uso = Uso(input_tokens=100, output_tokens=200, cache_read_input_tokens=50)
    quando = datetime(2026, 9, 23, 12, 0, 0, tzinfo=timezone.utc)

    registro = registrar_chamada(
        caminho,
        lead_id="lead-abc",
        modelo="modelo-de-teste",
        uso=uso,
        custo_usd=0.0123,
        quando=quando,
    )

    linhas = caminho.read_text(encoding="utf-8").splitlines()
    assert len(linhas) == 1
    gravado = json.loads(linhas[0])
    assert gravado == registro
    assert gravado["lead_id"] == "lead-abc"
    assert gravado["modelo"] == "modelo-de-teste"
    assert gravado["tokens"]["input_tokens"] == 100
    assert gravado["tokens"]["cache_read_input_tokens"] == 50
    assert gravado["custo_estimado_usd"] == 0.0123
    assert gravado["quando"] == "2026-09-23T12:00:00Z"


def test_registrar_chamada_acrescenta_sem_apagar_linha_anterior(tmp_path):
    caminho = tmp_path / "rodada.jsonl"
    uso = Uso(input_tokens=1, output_tokens=1)
    registrar_chamada(caminho, lead_id="lead-1", modelo="m", uso=uso, custo_usd=0.01)
    registrar_chamada(caminho, lead_id="lead-2", modelo="m", uso=uso, custo_usd=0.02)

    linhas = caminho.read_text(encoding="utf-8").splitlines()
    assert len(linhas) == 2
    assert json.loads(linhas[0])["lead_id"] == "lead-1"
    assert json.loads(linhas[1])["lead_id"] == "lead-2"


def test_resumo_rodada_arquivo_ausente_devolve_tudo_zerado(tmp_path):
    resumo = resumo_rodada(tmp_path / "nao-existe.jsonl")
    assert resumo["numero_chamadas"] == 0
    assert resumo["custo_total_usd"] == 0.0
    assert all(v == 0 for v in resumo["tokens_totais"].values())


def test_resumo_rodada_soma_varias_chamadas_corretamente(tmp_path):
    """Prova de não-vacuidade: chamadas com custos e tokens DIFERENTES entre
    si — uma mutação que trocasse soma por 'pega só a última' ou por
    contagem errada de chamadas faria este teste falhar."""
    caminho = tmp_path / "rodada.jsonl"
    registrar_chamada(
        caminho,
        lead_id="lead-1",
        modelo="m",
        uso=Uso(input_tokens=100, output_tokens=50, cache_creation_input_tokens=10),
        custo_usd=0.10,
    )
    registrar_chamada(
        caminho,
        lead_id="lead-2",
        modelo="m",
        uso=Uso(input_tokens=200, output_tokens=75, cache_read_input_tokens=30),
        custo_usd=0.25,
    )
    registrar_chamada(
        caminho,
        lead_id="lead-3",
        modelo="m",
        uso=Uso(input_tokens=300, output_tokens=125),
        custo_usd=0.40,
    )

    resumo = resumo_rodada(caminho)

    assert resumo["numero_chamadas"] == 3
    assert resumo["tokens_totais"]["input_tokens"] == 600
    assert resumo["tokens_totais"]["output_tokens"] == 250
    assert resumo["tokens_totais"]["cache_creation_input_tokens"] == 10
    assert resumo["tokens_totais"]["cache_read_input_tokens"] == 30
    assert resumo["custo_total_usd"] == pytest.approx(0.75)


def test_resumo_rodada_ignora_linhas_vazias(tmp_path):
    caminho = tmp_path / "rodada.jsonl"
    registrar_chamada(
        caminho, lead_id="lead-1", modelo="m", uso=Uso(input_tokens=1, output_tokens=1), custo_usd=0.01
    )
    with caminho.open("a", encoding="utf-8") as f:
        f.write("\n")

    resumo = resumo_rodada(caminho)
    assert resumo["numero_chamadas"] == 1
