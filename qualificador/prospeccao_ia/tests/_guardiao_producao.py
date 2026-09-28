"""Guardião de isolamento das pastas de PRODUÇÃO durante a suíte de testes.

Existe porque `_isolar_persistencia_de_dados` (conftest.py) protege por ENUMERAÇÃO -- uma
lista de cada `PATH_*`/env que precisa ser redirecionado pra `tmp_path`. Essa proteção
depende de alguém lembrar de somar a próxima saída nova à lista; quando o passo D6 criou a
saída humana, ninguém somou, e a suíte passou igual -- só que escrevendo CSVs de ensaio na
pasta real (`EQC/pipeline/saidas-humanas/`). Achado da supervisão, 23/09/2026, confirmado
rodando só a suíte com a pasta vazia antes e dois CSVs depois.

Este módulo é a rede que pega a PRÓXIMA vez que isso acontecer, sem depender de ninguém
lembrar de nada: tira uma fotografia (nome + tamanho, nunca conteúdo -- rápido, cobre até
pasta grande sem incomodar) das pastas de produção antes da suíte e outra depois; qualquer
arquivo criado, apagado ou de tamanho diferente vira falha nomeada -- nunca um "algo mudou"
genérico. Não é um teste em si -- é infraestrutura pura, sem I/O de rede nem estado global,
por isso o nome não começa com `test_` (não é coletado pelo pytest). Testado diretamente em
`test_guardiao_producao.py`.
"""
from pathlib import Path


def fotografar(pastas):
    """pastas: iterável de `(rotulo, caminho)`. Devolve
    `{(rotulo, caminho_relativo_str): tamanho_em_bytes}` para cada arquivo sob cada pasta,
    recursivo. Uma pasta ausente conta como vazia (nunca levanta) -- uma pasta de produção
    que ainda não existe nesta máquina não é erro aqui, só ausência de conteúdo pra vigiar."""
    foto = {}
    for rotulo, pasta in pastas:
        pasta = Path(pasta)
        if not pasta.is_dir():
            continue
        for caminho in pasta.rglob("*"):
            if caminho.is_file():
                rel = caminho.relative_to(pasta).as_posix()
                foto[(rotulo, rel)] = caminho.stat().st_size
    return foto


def diferencas(antes, depois):
    """Compara duas fotografias de `fotografar()`. Devolve uma lista de linhas de texto,
    uma por arquivo criado/apagado/alterado, nomeando pasta (rótulo) e caminho relativo.
    Lista vazia = nenhuma diferença -- suíte limpa."""
    linhas = []
    for chave in sorted(depois.keys() - antes.keys()):
        rotulo, rel = chave
        linhas.append(f"CRIADO   [{rotulo}] {rel} ({depois[chave]} bytes)")
    for chave in sorted(antes.keys() - depois.keys()):
        rotulo, rel = chave
        linhas.append(f"APAGADO  [{rotulo}] {rel} (era {antes[chave]} bytes)")
    for chave in sorted(antes.keys() & depois.keys()):
        if antes[chave] != depois[chave]:
            rotulo, rel = chave
            linhas.append(f"ALTERADO [{rotulo}] {rel} ({antes[chave]} -> {depois[chave]} bytes)")
    return linhas


def mensagem_de_falha(linhas):
    return (
        "A suíte escreveu, apagou ou alterou arquivo(s) em pasta(s) de PRODUÇÃO, fora do "
        "isolamento por tmp_path -- provavelmente uma saída nova que ainda não entrou na "
        "lista de isolamento (ver conftest.py: _isolar_persistencia_de_dados):\n"
        + "\n".join(linhas)
    )
