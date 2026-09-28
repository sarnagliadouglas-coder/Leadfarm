"""Prova, não promessa: a fixture autouse _isolar_persistencia_de_dados (conftest.py) tem que
redirecionar main.py pra fora de data/ real ANTES de qualquer teste rodar -- mesmo um teste
que não faça isolamento manual nenhum. Se esta fixture for removida ou quebrada, estes testes
falham primeiro, antes de qualquer dano a data/ real."""
import os

import main as main_mod

_DATA_REAL = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")


def test_todos_os_paths_de_persistencia_apontam_pra_fora_de_data_real():
    for nome in ("PATH_COLETADOS", "PATH_QUALIFICADOS", "PATH_REPROVADOS", "PATH_COM_SITE", "PATH_IMPORT_META"):
        caminho = getattr(main_mod, nome)
        assert not caminho.startswith(_DATA_REAL), (
            f"{nome} aponta pra dentro de data/ real ({caminho}) -- "
            f"a fixture autouse de isolamento não está ativa"
        )


def test_output_dir_do_contrato_aponta_pra_fora_do_projeto():
    import contrato
    assert not contrato.output_dir().startswith(_DATA_REAL)


def test_data_dir_nao_e_a_pasta_real():
    assert main_mod.DATA_DIR != _DATA_REAL


def test_fase_saida_sem_nenhum_isolamento_manual_nao_toca_data_real():
    """Sem ISTO ser verdade, um teste que esquecer de isolar (como o que causou o efeito
    colateral relatado) volta a escrever em cima de dados reais."""
    antes = sorted(os.listdir(_DATA_REAL)) if os.path.isdir(_DATA_REAL) else []

    main_mod.fase_saida()  # nenhum monkeypatch manual aqui de propósito -- só a fixture autouse

    depois = sorted(os.listdir(_DATA_REAL)) if os.path.isdir(_DATA_REAL) else []
    assert antes == depois, "fase_saida tocou em data/ real (deveria escrever só no QUALIFICADOR_OUTPUT_DIR isolado)"
