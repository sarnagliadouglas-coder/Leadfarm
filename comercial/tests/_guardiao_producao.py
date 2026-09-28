"""Guardião de isolamento das pastas de PRODUÇÃO durante a suíte de testes.

Cópia deliberada do mesmo módulo em `qualificador/prospeccao_ia/tests/_guardiao_producao.py`
(Etapa D, fechamento — passo D8): cada módulo do LeadFarm mantém sua própria suíte
autocontida, sem import cruzado entre QUALIFICADOR e COMERCIAL (mesma convenção que já vale
pra `tests/fixtures/leads_qualificados.schema.json`, cópia vendorizada, não importada do
QUALIFICADOR). O conteúdo é intencionalmente idêntico -- é infraestrutura de teste genérica
(fotografa nome+tamanho de arquivo sob uma lista de pastas, compara duas fotografias), não
lógica de negócio de um módulo específico.

Motivo de existir: `_isolar_persistencia_de_dados`-like isolamento por ENUMERAÇÃO (cada
teste que grava dossiê/diagnóstico redireciona `COMERCIAL_A1_OUTPUT_DIR`/
`COMERCIAL_A2_OUTPUT_DIR` pra `tmp_path` manualmente) depende de todo teste novo lembrar de
fazer isso. A checagem de 23/09/2026 (Etapa D, fechamento — passo D8) não achou nenhum
vazamento hoje na suíte do COMERCIAL, mas o mesmo tipo de lacuna que vazou no QUALIFICADOR
(saída humana nova, D6) pode se repetir aqui com uma saída futura. Este módulo é a rede que
pega isso sem depender de ninguém lembrar.
"""
from pathlib import Path


def fotografar(pastas):
    """pastas: iterável de `(rotulo, caminho)`. Devolve
    `{(rotulo, caminho_relativo_str): tamanho_em_bytes}` para cada arquivo sob cada pasta,
    recursivo. Uma pasta ausente conta como vazia (nunca levanta)."""
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
        "isolamento por tmp_path -- provavelmente uma saída nova (dossiê/diagnóstico/outro) "
        "que algum teste esqueceu de redirecionar via COMERCIAL_A1_OUTPUT_DIR/"
        "COMERCIAL_A2_OUTPUT_DIR/etc.:\n" + "\n".join(linhas)
    )
