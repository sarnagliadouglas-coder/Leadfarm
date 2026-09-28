"""Playwright e dependencia OPCIONAL do QUALIFICADOR (Etapa C, passo C3, decisao do diretor de
20/09/2026): sem ele o modulo continua funcionando como sempre. Sem rede, sem navegador.

Prova nas duas pontas:
  - ponta 1: com Playwright BLOQUEADO de verdade no processo (nao apenas ausente), importar todo
    modulo do pacote funciona;
  - ponta 2: e a unica coisa que falha, com mensagem explicita, e o uso do Playwright em si.
Controle: o bloqueio realmente bloqueia (`import playwright` levanta ImportError).
"""
import re
import subprocess
import sys
from pathlib import Path

import pytest

PACOTE = Path(__file__).resolve().parent.parent
_BLOQUEIO = "import sys; sys.modules['playwright'] = None; sys.modules['playwright.sync_api'] = None\n"


def _python(codigo, timeout=90):
    return subprocess.run([sys.executable, "-c", codigo], cwd=str(PACOTE), capture_output=True,
                          text=True, timeout=timeout)


def _modulos_do_pacote():
    return sorted(p.stem for p in PACOTE.glob("*.py"))


def test_o_bloqueio_do_teste_realmente_bloqueia_o_playwright():
    """Controle: sem isto, os testes abaixo passariam mesmo com Playwright instalado."""
    r = _python(_BLOQUEIO + "try:\n    import playwright\nexcept ImportError:\n    print('bloqueado')\n")
    assert r.returncode == 0, r.stderr
    assert "bloqueado" in r.stdout


def test_todo_modulo_do_pacote_importa_sem_playwright():
    modulos = _modulos_do_pacote()
    assert {"main", "site_renderizado", "output_json", "wave2_scoring", "agent_coletor"} <= set(modulos)
    codigo = _BLOQUEIO + (
        "import importlib\n"
        f"falhas = []\n"
        f"for nome in {modulos!r}:\n"
        "    try:\n"
        "        importlib.import_module(nome)\n"
        "    except Exception as e:\n"
        "        falhas.append(f'{nome}: {type(e).__name__}: {e}')\n"
        "print('FALHAS=' + repr(falhas))\n"
        f"print('IMPORTADOS=' + str(len({modulos!r}) - len(falhas)))\n"
    )
    r = _python(codigo)
    assert r.returncode == 0, r.stderr
    assert "FALHAS=[]" in r.stdout, r.stdout
    assert f"IMPORTADOS={len(modulos)}" in r.stdout


def test_sem_playwright_so_o_uso_do_playwright_falha_e_com_mensagem_explicita():
    codigo = _BLOQUEIO + (
        "import site_renderizado as sr\n"
        "try:\n"
        "    sr.abrir_playwright()\n"
        "except sr.PlaywrightIndisponivelError as e:\n"
        "    print('MSG=' + str(e))\n"
    )
    r = _python(codigo)
    assert r.returncode == 0, r.stderr
    assert "MSG=" in r.stdout and "pip install" in r.stdout and "playwright install chromium" in r.stdout


def test_nenhum_modulo_do_pacote_importa_playwright_no_topo():
    for arquivo in PACOTE.glob("*.py"):
        topo = [l for l in arquivo.read_text(encoding="utf-8").splitlines()
                if re.match(r"^(import|from)\s+playwright", l)]
        assert not topo, f"{arquivo.name}: import de playwright no topo -> {topo}"
    # controle: o import existe, mas tardio (indentado, dentro de funcao), so no modulo de renderizacao
    com_import_tardio = [a.name for a in PACOTE.glob("*.py")
                         if re.search(r"^\s+from playwright", a.read_text(encoding="utf-8"), re.M)]
    assert com_import_tardio == ["site_renderizado.py"]


def test_requirements_declara_playwright_como_opcional_e_documenta_a_instalacao():
    texto = (PACOTE / "requirements.txt").read_text(encoding="utf-8")
    linhas = [l.strip() for l in texto.splitlines()]
    assert any(re.fullmatch(r"playwright>=\d+(\.\d+)*", l) for l in linhas)
    comentarios = "\n".join(l for l in linhas if l.startswith("#"))
    assert "OPCIONAL" in comentarios
    assert "playwright install chromium" in comentarios           # o pacote nao traz o navegador
    assert "SEM esta linha" in comentarios or "sem esta linha" in comentarios.lower()
    # controle: as dependencias que ja existiam continuam la
    assert "pytest" in linhas and any(l.startswith("jsonschema>=") for l in linhas)


def test_a_instalacao_esta_documentada_onde_o_modulo_documenta_dependencias():
    import site_renderizado
    doc = site_renderizado.__doc__
    assert "OPCIONAL" in doc and "playwright install chromium" in doc
    indice = PACOTE / "docs" / "INDEX.md"
    # docs/ é documentação interna, fora do repositório público (28/09/2026):
    # só confere o índice onde ele existe.
    if indice.is_file():
        assert "playwright" in indice.read_text(encoding="utf-8").lower()
