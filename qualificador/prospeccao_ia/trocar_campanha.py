"""Troca da campanha ativa por menu (atalho de duplo clique: `Trocar-campanha.bat` na raiz).

Mostra as campanhas (uma por nicho) de `<eqc_root>/config/campanhas/*.json`, o diretor escolhe
um número e o script grava `<eqc_root>/config/campanha_ativa.json` com o conteúdo da escolhida.
Nada além disso. A campanha ativa só decide o nicho -- e a cidade, pela `cidade_padrao` -- de
lista SEM termo de busca; lista com termo escolhe sozinha (`campanha.escolher_campanha`).

Regras: a escolhida é validada com `campanha.carregar_campanha` ANTES de gravar; qualquer erro
(opção inválida, campanha inválida) deixa o arquivo ativo intacto (byte a byte). A gravação é
atômica (arquivo temporário na mesma pasta + `os.replace`) e o resultado é revalidado; se a
revalidação falhar, o conteúdo anterior é restaurado.

Caminhos: sem caminho absoluto de máquina. Raiz via `contrato.eqc_root()` (`LEADFARM_ROOT` etc.).
Overrides SÓ PARA TESTE: `QUALIFICADOR_CAMPANHAS_DIR` (pasta das campanhas) e
`QUALIFICADOR_CAMPANHA` (arquivo ativo, o mesmo que `campanha.py` já respeita).
Código de saída: 0 = campanha trocada; 1 = nada foi alterado. $0, sem LLM.
"""
import os
import sys
import tempfile
from pathlib import Path

import campanha

ENV_DIR_CAMPANHAS = campanha.ENV_DIR_CAMPANHAS


def dir_campanhas() -> Path:
    """Pasta das campanhas disponíveis (a mesma da escolha pelo termo, `campanha.dir_campanhas`).
    A env (só teste) vence."""
    return Path(campanha.dir_campanhas())


def listar_campanhas(pasta: Path):
    """Lista de dicts {arquivo, id, nicho, cidade_padrao, valida} em ordem de nome de arquivo.
    Arquivo ilegível ou inválido entra na lista como `valida=False` (a escolha será recusada)."""
    itens = []
    for arq in sorted(pasta.glob("*.json"), key=lambda p: p.name.lower()):
        item = {"arquivo": arq, "id": None, "nicho": None, "cidade_padrao": None, "valida": True}
        try:
            dados = campanha.carregar_campanha(str(arq))
            item.update(id=dados["id"], nicho=dados["nicho"], cidade_padrao=dados["cidade_padrao"])
        except campanha.CampanhaInvalidaError:
            item["valida"] = False
        itens.append(item)
    return itens


def _id_ativo(caminho_ativo: str):
    try:
        return campanha.carregar_campanha(caminho_ativo)["id"]
    except campanha.CampanhaInvalidaError:
        return None


def _gravar_atomico(destino: Path, conteudo: bytes):
    destino.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".campanha_ativa_", suffix=".tmp", dir=str(destino.parent))
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(conteudo)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, destino)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def _recusar(saida, motivo):
    print(f"\nNada foi alterado. {motivo}", file=saida)
    return 1


def executar(entrada=None, saida=None) -> int:
    entrada = entrada or sys.stdin
    saida = saida or sys.stdout
    pasta = dir_campanhas()
    ativo = Path(campanha.caminho_campanha())

    print("TROCAR A CAMPANHA ATIVA", file=saida)
    print("=======================\n", file=saida)

    itens = listar_campanhas(pasta) if pasta.is_dir() else []
    if not itens:
        return _recusar(saida, f"Não encontrei nenhuma campanha na pasta '{pasta}'.")

    id_ativo = _id_ativo(str(ativo))
    print("Campanhas disponíveis:\n", file=saida)
    for n, it in enumerate(itens, 1):
        if it["valida"]:
            marca = "   <- ativa agora" if it["id"] == id_ativo else ""
            print(f"  {n}) {it['nicho']} (cidade padrão {it['cidade_padrao']})  ({it['id']}){marca}", file=saida)
        else:
            print(f"  {n}) {it['arquivo'].name}  (arquivo com problema, não dá para usar)", file=saida)

    print("\nDigite o número da campanha e aperte Enter: ", end="", file=saida, flush=True)
    escolha = (entrada.readline() or "").strip()
    print(escolha, file=saida)

    if not escolha:
        return _recusar(saida, "Você não digitou nada.")
    if not escolha.isdigit():
        return _recusar(saida, f"'{escolha}' não é um número. Digite só o número da lista.")
    n = int(escolha)
    if not 1 <= n <= len(itens):
        return _recusar(saida, f"O número {n} não está na lista (vai de 1 a {len(itens)}).")

    escolhida = itens[n - 1]["arquivo"]
    try:
        campanha.carregar_campanha(str(escolhida))
    except campanha.CampanhaInvalidaError as e:
        return _recusar(saida, f"A campanha escolhida tem problema e não foi usada: {e}")

    antes = ativo.read_bytes() if ativo.is_file() else None
    try:
        _gravar_atomico(ativo, escolhida.read_bytes())
        dados = campanha.carregar_campanha(str(ativo))
    except (OSError, campanha.CampanhaInvalidaError) as e:
        if antes is not None:
            try:
                _gravar_atomico(ativo, antes)
            except OSError:
                pass
        return _recusar(saida, f"Não consegui gravar a troca ({e}). O arquivo anterior foi mantido.")

    print("\nPronto. Campanha ativa agora:", file=saida)
    print(f"  {dados['nicho']} (cidade padrão {dados['cidade_padrao']})  ({dados['id']})", file=saida)
    print("\nAgora pode importar a lista desse nicho. A cidade padrão só vale para lista sem termo "
          "de busca; lista com termo usa o nicho e a cidade da busca.", file=saida)
    return 0


if __name__ == "__main__":
    for fluxo in (sys.stdout, sys.stderr):
        try:
            fluxo.reconfigure(encoding="utf-8")
        except Exception:
            pass
    sys.exit(executar())
