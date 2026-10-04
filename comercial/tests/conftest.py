"""conftest.py do COMERCIAL -- só o guardião de isolamento de produção (Etapa D, fechamento
— passo D8). O resto da suíte isola cada saída manualmente, teste a teste (via
monkeypatch/tmp_path nos próprios arquivos de teste) -- este
fixture não substitui isso, é uma segunda rede, que não depende de ninguém lembrar de somar
a próxima saída nova à lista de isolamento manual.
"""
import sys
from pathlib import Path

import pytest

_TESTS_DIR = Path(__file__).resolve().parent
_FERRAMENTAS_DIR = _TESTS_DIR.parent / "ferramentas"
sys.path.insert(0, str(_TESTS_DIR))
sys.path.insert(0, str(_FERRAMENTAS_DIR))

import env_loader  # noqa: E402
import eqc  # noqa: E402
import _guardiao_producao as guardiao  # noqa: E402


def _pastas_producao():
    """Resolvidas UMA vez por sessão, contra o ambiente REAL (antes de qualquer
    monkeypatch de teste). Cobre a árvore EQC (via eqc.eqc_root()) e as pastas de
    dado operacional do COMERCIAL.

    Inclui COMERCIAL_PLANILHAS_DIR (planilha consolidada, fora do repo) desde
    01/10/2026: defeito real nesta máquina -- `gerar_planilha()` ganhou uma
    saída nova (a consolidada) que lê essa env direto de `comercial/.env`, e
    testes que chamam `gerar_planilha()` sem isolar `consolidada_dir`
    escreveram fixture de teste na planilha de verdade do diretor, em
    silêncio, até alguém notar o conteúdo contaminado. Pasta ausente ou env
    não configurada conta como vazia (`fotografar` já trata isso)."""
    eqc_root = eqc.eqc_root()
    raiz_modulo = _TESTS_DIR.parent  # tests -> comercial
    env_loader.carregar_env()
    import os

    pastas = [
        ("EQC/pipeline", eqc_root / "pipeline"),
        ("EQC/contracts", eqc_root / "contracts"),
        ("comercial/_consumo_llm", raiz_modulo / "_consumo_llm"),
        ("comercial/_mensagens", raiz_modulo / "_mensagens"),
        ("comercial/_planilhas", raiz_modulo / "_planilhas"),
        ("comercial/_abordagens", raiz_modulo / "_abordagens"),
    ]
    consolidada_dir = (os.environ.get("COMERCIAL_PLANILHAS_DIR") or "").strip()
    if consolidada_dir:
        pastas.append(("COMERCIAL_PLANILHAS_DIR (consolidada)", Path(consolidada_dir)))
    return pastas


@pytest.fixture(scope="session", autouse=True)
def _guardiao_pastas_producao():
    """Fotografa nome+tamanho das pastas de produção antes da suíte inteira e de novo
    depois; falha nomeando qualquer arquivo criado, apagado ou alterado. Roda mesmo se
    algum teste tiver falhado antes (teardown de fixture de sessão sempre roda ao final).
    Ver o mesmo mecanismo, testado, em qualificador/prospeccao_ia/tests/conftest.py."""
    pastas = _pastas_producao()
    antes = guardiao.fotografar(pastas)
    yield
    depois = guardiao.fotografar(pastas)
    linhas = guardiao.diferencas(antes, depois)
    if linhas:
        pytest.fail(guardiao.mensagem_de_falha(linhas), pytrace=False)
