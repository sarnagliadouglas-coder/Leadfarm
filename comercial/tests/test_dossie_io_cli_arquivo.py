"""
Testes de contorno de `--arquivo` na CLI de dossie_io.py — nível de
processo, subprocess real, mesmo motivo de test_dossie_io_cli.py.

Por que este modo existe além do stdin: o heredoc por stdin não funciona
quando a ferramenta Bash é chamada de DENTRO de um subagente — medido em
16/09/2026 (falha "unexpected EOF while looking for matching `''`" em
13.389, 13.391 e 16.570 bytes, e também com JSON compacto numa linha só;
o mesmo comando roda normalmente na sessão pai). `--arquivo` lê de um
caminho já gravado em disco, contornando o heredoc — sem substituir o
stdin, que continua coberto pelos testes de test_dossie_io_cli.py.

Defeito achado e corrigido em 16/09/2026, nesta mesma rodada: a primeira
versão de --arquivo tentava detectar uso conjunto com stdin via
`sys.stdin.buffer.peek()`. Isso travava indefinidamente sempre que o
chamador não redirecionava stdin explicitamente — exatamente o caso real
do Bash do subagente (`--arquivo <path> --json`, sem heredoc, sem `<
/dev/null`). Os 6 testes originais nunca pegaram isso porque todos fecham
ou redirecionam stdin (`DEVNULL` ou `input=`) — o mesmo padrão de falha da
Etapa 5.1, um teste que exercita o caminho onde o defeito não pode
aparecer. Correção: com --arquivo, stdin nunca é tocado — nem por
`peek()`. `test_arquivo_junto_com_stdin_exit_2` (a checagem de conflito)
não faz mais sentido e foi SUBSTITUÍDO por
`test_arquivo_sem_redirecionar_stdin_nao_trava` (reproduz o cenário real,
com timeout) e `test_arquivo_com_stdin_com_conteudo_e_ignorado` (confirma
que o conteúdo do arquivo prevalece e stdin nunca é lido).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

FERRAMENTAS_DIR = Path(__file__).resolve().parent.parent / "ferramentas"
# Qualquer dossiê real que esteja na pasta do pipeline (fora do Git) serve de
# referência -- nenhum place_id de lead real fica escrito no código versionado.
# Sem nenhum dossiê na pasta, os testes que dependem dele são pulados.
_DIR_DOSSIES_REAIS = (
    Path(__file__).resolve().parent.parent.parent / "EQC" / "pipeline" / "comercial" / "01-investigacao"
)
EQC_DOSSIE_REAL = next(iter(sorted(_DIR_DOSSIES_REAIS.glob("dossie_*.json"))), _DIR_DOSSIES_REAIS / "dossie_ausente.json")


TIMEOUT_S = 10  # todo subprocess desta suíte tem timeout explícito —
                 # um teste que pendura trava a suíte inteira, não falha.


def _rodar(output_dir: Path, *args: str) -> subprocess.CompletedProcess:
    """stdin explicitamente DEVNULL — determinístico, nunca herda o stdin
    do processo de teste (que pode ser qualquer coisa)."""
    env = dict(os.environ)
    env["COMERCIAL_A1_OUTPUT_DIR"] = str(output_dir)
    return subprocess.run(
        [sys.executable, str(FERRAMENTAS_DIR / "dossie_io.py"), *args],
        capture_output=True,
        stdin=subprocess.DEVNULL,
        env=env,
        timeout=TIMEOUT_S,
    )


@pytest.fixture
def dossie_valido_bytes() -> bytes:
    if not EQC_DOSSIE_REAL.is_file():
        pytest.skip(f"dossiê real de referência não encontrado: {EQC_DOSSIE_REAL}")
    return EQC_DOSSIE_REAL.read_bytes()


def test_arquivo_valido_grava_e_devolve_caminho(tmp_path, dossie_valido_bytes):
    entrada = tmp_path / "entrada" / "dossie.json"
    entrada.parent.mkdir()
    entrada.write_bytes(dossie_valido_bytes)
    saida_dir = tmp_path / "saida"
    saida_dir.mkdir()

    r = _rodar(saida_dir, "--arquivo", str(entrada), "--json")

    assert r.returncode == 0, f"stdout={r.stdout!r} stderr={r.stderr!r}"
    corpo = json.loads(r.stdout.decode("utf-8"))
    assert corpo["gravado"] is True

    arquivos = list(saida_dir.iterdir())
    assert len(arquivos) == 1, f"esperava 1 arquivo gravado, achei {arquivos}"
    assert corpo["caminho"] == str(arquivos[0])


def test_arquivo_dossie_invalido_exit_1_nada_gravado(tmp_path):
    entrada = tmp_path / "entrada" / "dossie.json"
    entrada.parent.mkdir()
    entrada.write_text(json.dumps({"place_id": "X"}), encoding="utf-8")
    saida_dir = tmp_path / "saida"
    saida_dir.mkdir()

    r = _rodar(saida_dir, "--arquivo", str(entrada), "--json")

    assert r.returncode == 1, f"stdout={r.stdout!r} stderr={r.stderr!r}"
    corpo = json.loads(r.stdout.decode("utf-8"))
    assert corpo["gravado"] is False
    assert list(saida_dir.iterdir()) == []


def test_arquivo_inexistente_exit_2(tmp_path):
    saida_dir = tmp_path / "saida"
    saida_dir.mkdir()
    ausente = tmp_path / "nao_existe.json"

    r = _rodar(saida_dir, "--arquivo", str(ausente), "--json")

    assert r.returncode == 2, f"stdout={r.stdout!r} stderr={r.stderr!r}"
    corpo = json.loads(r.stdout.decode("utf-8"))
    assert corpo["gravado"] is None
    assert "erro_operacional" in corpo
    assert list(saida_dir.iterdir()) == []


def test_arquivo_json_malformado_exit_2(tmp_path):
    entrada = tmp_path / "entrada" / "malformado.json"
    entrada.parent.mkdir()
    entrada.write_text("{isto nao e json", encoding="utf-8")
    saida_dir = tmp_path / "saida"
    saida_dir.mkdir()

    r = _rodar(saida_dir, "--arquivo", str(entrada), "--json")

    assert r.returncode == 2, f"stdout={r.stdout!r} stderr={r.stderr!r}"
    corpo = json.loads(r.stdout.decode("utf-8"))
    assert corpo["gravado"] is None
    assert list(saida_dir.iterdir()) == []


def test_arquivo_sem_redirecionar_stdin_nao_trava(tmp_path, dossie_valido_bytes):
    """Reproduz o cenário real do Bash do subagente: --arquivo chamado sem
    nenhum redirecionamento de stdin (nem heredoc, nem < /dev/null). stdin
    fica aberto, herdado, sem dado e sem fechar — exatamente a condição que
    travava a versão com peek() (MEDIDO 16/09/2026, timeout 20s, exit 124
    no uso real; um teste chegou a ficar pendurado uma hora).

    Não usa subprocess.run(input=...) nem stdin=DEVNULL — os dois FECHAM
    stdin e não reproduzem o defeito. Usa Popen com stdin=PIPE e NUNCA
    escreve nem fecha esse pipe antes do processo terminar sozinho —
    stdin fica genuinamente aberto e vazio, como no Bash do subagente.
    """
    entrada = tmp_path / "entrada" / "dossie.json"
    entrada.parent.mkdir()
    entrada.write_bytes(dossie_valido_bytes)
    saida_dir = tmp_path / "saida"
    saida_dir.mkdir()
    env = dict(os.environ)
    env["COMERCIAL_A1_OUTPUT_DIR"] = str(saida_dir)

    proc = subprocess.Popen(
        [sys.executable, str(FERRAMENTAS_DIR / "dossie_io.py"), "--arquivo", str(entrada), "--json"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
    )
    try:
        proc.wait(timeout=TIMEOUT_S)  # não toca stdin/stdout — só espera o exit
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
        pytest.fail(
            f"CLI travou com --arquivo e stdin aberto sem redirecionar — "
            f"não terminou em {TIMEOUT_S}s. Este é o defeito de 16/09/2026."
        )

    stdout = proc.stdout.read()
    stderr = proc.stderr.read()
    proc.stdin.close()
    assert proc.returncode == 0, f"stdout={stdout!r} stderr={stderr!r}"
    corpo = json.loads(stdout.decode("utf-8"))
    assert corpo["gravado"] is True


def test_arquivo_com_stdin_com_conteudo_e_ignorado(tmp_path, dossie_valido_bytes):
    """Com --arquivo, stdin nunca é lido — mesmo que tenha dado, mesmo que
    o dado fosse inválido. O conteúdo do arquivo é o que sempre vale."""
    entrada = tmp_path / "entrada" / "dossie.json"
    entrada.parent.mkdir()
    entrada.write_bytes(dossie_valido_bytes)
    saida_dir = tmp_path / "saida"
    saida_dir.mkdir()

    env = dict(os.environ)
    env["COMERCIAL_A1_OUTPUT_DIR"] = str(saida_dir)
    r = subprocess.run(
        [sys.executable, str(FERRAMENTAS_DIR / "dossie_io.py"), "--arquivo", str(entrada), "--json"],
        input=b"isto nao e json valido -- se isto fosse lido, o processo falharia",
        capture_output=True,
        env=env,
        timeout=TIMEOUT_S,
    )

    assert r.returncode == 0, (
        f"stdin com lixo não deveria influenciar o resultado — "
        f"stdout={r.stdout!r} stderr={r.stderr!r}"
    )
    corpo = json.loads(r.stdout.decode("utf-8"))
    assert corpo["gravado"] is True
    arquivos = list(saida_dir.iterdir())
    assert len(arquivos) == 1
    place_id_referencia = json.loads(EQC_DOSSIE_REAL.read_text(encoding="utf-8"))["place_id"]
    assert place_id_referencia in arquivos[0].name, (
        "o arquivo gravado deveria vir do --arquivo (place_id real), não de stdin"
    )


# --- D14 (docs/decisoes.md, 18/09/2026): investigado_em preenchido pela
# ferramenta, na CLI, ANTES da validação — mesmo comportamento de
# salvar_dossie() direto (test_dossie_io.py), aqui via subprocess real.

def test_arquivo_sem_investigado_em_grava_com_carimbo_do_nome(tmp_path, dossie_valido_bytes):
    dossie = json.loads(dossie_valido_bytes)
    dossie.pop("investigado_em", None)
    entrada = tmp_path / "entrada" / "dossie.json"
    entrada.parent.mkdir()
    entrada.write_text(json.dumps(dossie, ensure_ascii=False), encoding="utf-8")
    saida_dir = tmp_path / "saida"
    saida_dir.mkdir()

    r = _rodar(saida_dir, "--arquivo", str(entrada), "--json")

    assert r.returncode == 0, f"stdout={r.stdout!r} stderr={r.stderr!r}"
    corpo = json.loads(r.stdout.decode("utf-8"))
    assert "investigado_em" in corpo

    arquivos = list(saida_dir.iterdir())
    assert len(arquivos) == 1
    gravado = json.loads(arquivos[0].read_text(encoding="utf-8"))
    assert gravado["investigado_em"] == corpo["investigado_em"]
    # AAAAMMDD-HHMMSS do nome do arquivo vira AAAA-MM-DDTHH:MM:SSZ
    carimbo_nome = arquivos[0].name.rsplit("_", 1)[1].removesuffix(".json")
    esperado_iso = (
        f"{carimbo_nome[0:4]}-{carimbo_nome[4:6]}-{carimbo_nome[6:8]}"
        f"T{carimbo_nome[9:11]}:{carimbo_nome[11:13]}:{carimbo_nome[13:15]}Z"
    )
    assert gravado["investigado_em"] == esperado_iso


def test_arquivo_com_investigado_em_inventado_e_substituido(tmp_path, dossie_valido_bytes):
    dossie = json.loads(dossie_valido_bytes)
    dossie["investigado_em"] = "2099-01-01T00:00:00Z"  # valor inventado
    entrada = tmp_path / "entrada" / "dossie.json"
    entrada.parent.mkdir()
    entrada.write_text(json.dumps(dossie, ensure_ascii=False), encoding="utf-8")
    saida_dir = tmp_path / "saida"
    saida_dir.mkdir()

    r = _rodar(saida_dir, "--arquivo", str(entrada), "--json")

    assert r.returncode == 0, f"stdout={r.stdout!r} stderr={r.stderr!r}"
    corpo = json.loads(r.stdout.decode("utf-8"))
    assert corpo["investigado_em"] != "2099-01-01T00:00:00Z"

    arquivos = list(saida_dir.iterdir())
    gravado = json.loads(arquivos[0].read_text(encoding="utf-8"))
    assert gravado["investigado_em"] != "2099-01-01T00:00:00Z"
    assert gravado["investigado_em"] == corpo["investigado_em"]


def test_stdout_ascii_puro_com_arquivo(tmp_path):
    entrada = tmp_path / "entrada" / "dossie.json"
    entrada.parent.mkdir()
    entrada.write_text(json.dumps({"place_id": "X"}), encoding="utf-8")
    saida_dir = tmp_path / "saida"
    saida_dir.mkdir()

    r = _rodar(saida_dir, "--arquivo", str(entrada), "--json")

    assert r.returncode == 1
    assert all(b < 128 for b in r.stdout), f"stdout não é ASCII puro: {r.stdout[:200]!r}"
    r.stdout.decode("utf-8")  # não deve levantar
