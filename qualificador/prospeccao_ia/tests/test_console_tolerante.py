"""Testes de main._tornar_console_tolerante() -- item 1 (BLOQUEADOR) da Etapa D, passo D6b:
`python main.py <fase>` precisa rodar num console Windows padrão (cp1252), sem nenhuma
variável de ambiente, com os acentos legíveis. Simula esse console com um
io.TextIOWrapper(io.BytesIO(), encoding="cp1252", errors="strict") -- o MESMO par
encoding/errors que o console real usa quando `sys.stdout.reconfigure()` nunca foi chamado."""
import io

import pytest

import main as main_mod

BANNER = " 🤖 SISTEMA AUTÔNOMO DE PROSPECÇÃO (ESPANHA) 🤖"


def _console_cp1252():
    """Um stream que se comporta como o console cp1252 padrão do Windows -- ANTES de
    qualquer reconfigure(). errors="strict" é o handler padrão de qualquer TextIOWrapper
    sem correção -- é o que faz o processo real morrer na primeira linha do banner."""
    buffer = io.BytesIO()
    return buffer, io.TextIOWrapper(buffer, encoding="cp1252", errors="strict")


# --- Controle negativo: prova que o problema é real, hoje, sem a correção ------------------


def test_console_cp1252_sem_correcao_derruba_no_banner():
    _buffer, fluxo = _console_cp1252()
    with pytest.raises(UnicodeEncodeError):
        fluxo.write(BANNER)
        fluxo.flush()


# --- _tornar_console_tolerante corrige, sem perder acento ----------------------------------


def test_tornar_console_tolerante_preserva_acentos_e_troca_emoji():
    buffer, fluxo = _console_cp1252()

    main_mod._tornar_console_tolerante([fluxo])
    fluxo.write(BANNER)  # não deve levantar
    fluxo.flush()

    bruto = buffer.getvalue()
    # Bytes cp1252 reais dos acentos usados no banner -- prova ao nível de byte, não de
    # exibição de terminal (um terminal UTF-8 mostraria esses mesmos bytes cp1252 como
    # lixo, o que seria um falso alarme do TESTE, não do código).
    assert b"AUT\xd4NOMO" in bruto        # Ô = 0xD4 em cp1252
    assert b"PROSPEC\xc7\xc3O" in bruto   # Ç = 0xC7, Ã = 0xC3 em cp1252
    assert b"ESPANHA" in bruto
    # O emoji (fora do cp1252) virou "?", não travou nem sumiu em silêncio sem sinal.
    assert bruto.count(b"?") == 2  # os dois "🤖" do banner


def test_tornar_console_tolerante_nao_muda_a_codificacao_so_o_error_handler():
    _buffer, fluxo = _console_cp1252()
    assert fluxo.errors == "strict"
    main_mod._tornar_console_tolerante([fluxo])
    assert fluxo.encoding == "cp1252"  # continua cp1252 -- não virou utf-8
    assert fluxo.errors == "replace"


def test_tornar_console_tolerante_texto_sem_caractere_especial_sai_identico():
    buffer, fluxo = _console_cp1252()
    main_mod._tornar_console_tolerante([fluxo])
    fluxo.write("linha comum, sem emoji nem seta")
    fluxo.flush()
    assert buffer.getvalue().decode("cp1252") == "linha comum, sem emoji nem seta"


# --- Não trava em stream sem reconfigure() (ex.: capturado por um runner de teste) ---------


class _StreamSemReconfigure:
    def __init__(self):
        self.escrito = []

    def write(self, texto):
        self.escrito.append(texto)


def test_tornar_console_tolerante_ignora_stream_sem_reconfigure():
    fluxo = _StreamSemReconfigure()
    main_mod._tornar_console_tolerante([fluxo])  # não deve levantar
    fluxo.write("ok")
    assert fluxo.escrito == ["ok"]


def test_tornar_console_tolerante_ignora_stream_com_reconfigure_que_levanta_valueerror():
    class _StreamFechado:
        def reconfigure(self, **kw):
            raise ValueError("I/O operation on closed file")

    main_mod._tornar_console_tolerante([_StreamFechado()])  # não deve levantar


def test_tornar_console_tolerante_padrao_afeta_stdout_e_stderr(monkeypatch):
    chamadas = []

    class _Fluxo:
        def reconfigure(self, **kw):
            chamadas.append(kw)

    monkeypatch.setattr(main_mod.sys, "stdout", _Fluxo())
    monkeypatch.setattr(main_mod.sys, "stderr", _Fluxo())

    main_mod._tornar_console_tolerante()  # sem argumento -- usa sys.stdout/sys.stderr

    assert chamadas == [{"errors": "replace"}, {"errors": "replace"}]
