"""
dossie_io.py — escrita em disco do dossiê do Agente 1.

Um dossiê por lead (o A1 roda por lead, não em lote — diferente de
`fetch_tecnico.py`/`psi` do QUALIFICADOR, que processam lote inteiro).
Nunca sobrescreve: o timestamp no nome do arquivo preserva rastreabilidade
entre tentativas — se o mesmo lead for investigado de novo (reprocesso,
escalonamento, correção), o dossiê anterior continua no disco.

Uso:
    from dossie_io import salvar_dossie

    caminho = salvar_dossie(dossie)                         # diretório padrão
    caminho = salvar_dossie(dossie, output_dir=Path("..."))  # explícito (testes)

Diretório padrão: sem `COMERCIAL_A1_OUTPUT_DIR`, deriva do EQC resolvido em
runtime por `eqc.py` — `<eqc_root>/pipeline/comercial/01-investigacao`. Nenhum
caminho absoluto de máquina fica fixo aqui.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping, Optional

try:
    import eqc
except ModuleNotFoundError:  # pragma: no cover - bootstrap de sys.path
    import sys as _sys

    _sys.path.insert(0, str(Path(__file__).resolve().parent))
    import eqc

try:
    from validador_dossie import DossieInvalidoError, validar_dossie
except ModuleNotFoundError:  # pragma: no cover - bootstrap de sys.path
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from validador_dossie import DossieInvalidoError, validar_dossie

ENV_DIRETORIO_SAIDA = eqc.ENV_A1_OUTPUT_DIR  # "COMERCIAL_A1_OUTPUT_DIR"


class DossieIOError(Exception):
    """Erro ao gravar o dossiê em disco."""


def diretorio_saida() -> Path:
    """Diretório de saída do dossiê. `COMERCIAL_A1_OUTPUT_DIR` (caminho final)
    vence; senão `<eqc_root>/pipeline/comercial/01-investigacao` — ver `eqc.py`."""
    return eqc.diretorio_saida_a1()


def _preencher_investigado_em(dossie: Mapping, agora: datetime) -> dict:
    """Devolve uma CÓPIA do dossiê com `investigado_em` preenchido por
    `agora` (o mesmo instante usado no nome do arquivo), em ISO 8601 UTC
    com "Z" — sempre substitui qualquer valor recebido, nunca rejeita.

    Decisão D14 (`docs/decisoes.md`), 18/09/2026: o A1 não tem relógio e
    inventava este valor (`prompt.md` pedia "agora"); em 3 de 5 dossiês
    reais o valor declarado era POSTERIOR ao carimbo do nome do arquivo. O
    campo passa a ser preenchido pela ferramenta, nunca pelo agente.
    """
    novo = dict(dossie)
    novo["investigado_em"] = agora.strftime("%Y-%m-%dT%H:%M:%SZ")
    return novo


def salvar_dossie(
    dossie: Mapping,
    *,
    output_dir: Optional[Path] = None,
    agora: Optional[datetime] = None,
) -> Path:
    """Grava o dossiê em `<output_dir>/dossie_<place_id>_<AAAAMMDD-HHMMSS>.json`.

    Preenche (substituindo qualquer valor recebido) `investigado_em` com o
    MESMO `agora` usado no carimbo do nome do arquivo — ver
    `_preencher_investigado_em`. Vale para toda chamada, direta ou via CLI.

    Args:
        dossie: o documento do dossiê (já validado por `validador_dossie`
            antes de chegar aqui — este módulo não valida, só grava).
        output_dir: diretório de saída. Default: COMERCIAL_A1_OUTPUT_DIR ou
            DIRETORIO_SAIDA_PADRAO.
        agora: timestamp a usar no nome do arquivo e em `investigado_em`.
            Default: agora, UTC. Parametrizável para tornar os testes
            determinísticos.

    Raises:
        DossieIOError: `place_id` ausente/vazio no dossiê, ou falha ao
            escrever o arquivo.
    """
    place_id = dossie.get("place_id") if isinstance(dossie, Mapping) else None
    if not place_id:
        raise DossieIOError(
            "Dossiê sem 'place_id' — não é possível nomear o arquivo de saída. "
            "Valide o dossiê (validador_dossie.validar_dossie) antes de salvar."
        )

    destino_dir = Path(output_dir) if output_dir else diretorio_saida()
    try:
        destino_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise DossieIOError(f"Não foi possível criar o diretório de saída {destino_dir}: {exc}") from exc

    agora_resolvido = agora or datetime.now(timezone.utc)
    dossie = _preencher_investigado_em(dossie, agora_resolvido)

    timestamp = agora_resolvido.strftime("%Y%m%d-%H%M%S")
    nome = f"dossie_{place_id}_{timestamp}.json"
    caminho = destino_dir / nome

    if caminho.exists():
        # Colisão de timestamp (mesma execução, mesmo segundo) -- nunca
        # sobrescrever; ver docstring do módulo.
        raise DossieIOError(
            f"{caminho} já existe -- nunca sobrescrevemos um dossiê. "
            f"Se isto for um reprocesso deliberado no mesmo segundo, aguarde "
            f"e tente de novo."
        )

    try:
        caminho.write_text(json.dumps(dossie, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError as exc:
        raise DossieIOError(f"Não foi possível escrever {caminho}: {exc}") from exc

    return caminho


def main(argv: Optional[list[str]] = None) -> int:
    """CLI fina sobre `validar_dossie` + `salvar_dossie` — não decide nada,
    só compõe as duas. Duas fontes de entrada:

    - stdin (padrão, sem --arquivo): heredoc. Funciona na sessão pai e nos
      testes; `MEDIDO` 16/09/2026 que NÃO funciona quando a ferramenta Bash
      é chamada de dentro de um subagente (heredoc de 272 linhas chega como
      uma linha só ao bash do subagente — erro "unexpected EOF").
    - `--arquivo <caminho>`: lê o dossiê já gravado em disco. Existe por
      causa da medição acima.

    Quando --arquivo é dado, stdin NUNCA é lido nem inspecionado — nem por
    `peek()`. `MEDIDO` 16/09/2026: uma versão anterior tentava detectar uso
    conjunto de --arquivo com stdin via `sys.stdin.buffer.peek()`; isso
    travava indefinidamente sempre que o chamador não redirecionava stdin
    explicitamente (o caso real do Bash do subagente) — `peek()` bloqueia
    esperando dado ou EOF que nunca vêm num stdin herdado e aberto. Exit 0
    nos testes automatizados (que sempre fecham ou redirecionam stdin) e
    travamento no uso real é o mesmo padrão de falha da Etapa 5.1: o teste
    exercitava o caminho onde o defeito não podia aparecer. Por isso: com
    --arquivo, stdin é ignorado, ponto — sem tentativa de detectar conflito.

    Sem opção --output: o destino é sempre `diretorio_saida()`
    (`COMERCIAL_A1_OUTPUT_DIR` em testes) — nunca sobrescreve, comportamento
    de `salvar_dossie` inalterado.

    Exit codes: 0 gravado · 1 dossiê reprovado na validação (nada gravado) ·
    2 não foi possível (entrada vazia, JSON malformado, arquivo ausente ou
    ilegível, ou falha ao gravar — `DossieIOError`).

    Modo humano (sem --json): mesma ressalva de codificação dos wrappers da
    Etapa 5.1 — consumo automatizado deve sempre usar --json.

    NÃO VERIFICADO nesta rodada: `lead_origem` não é passado a
    `validar_dossie` — as checagens de `place_id` e eco de
    rating/avaliações contra o lead de origem são puladas.
    """
    ap = argparse.ArgumentParser(description=main.__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument(
        "--arquivo", type=Path, default=None,
        help="Lê o dossiê deste caminho, em vez de stdin. Quando dado, "
             "stdin é ignorado — nunca lido, nunca inspecionado.",
    )
    ap.add_argument(
        "--json", action="store_true",
        help="Saída em JSON. Exit codes: 0 gravado · 1 dossiê reprovado na "
             "validação (nada gravado) · 2 não foi possível (entrada vazia, "
             "JSON malformado, arquivo ausente/ilegível, ou falha ao "
             "gravar).",
    )
    args = ap.parse_args(argv)

    if args.arquivo is not None:
        try:
            bruto = args.arquivo.read_bytes()
        except OSError as exc:
            if args.json:
                print(json.dumps({"gravado": None, "erro_operacional": str(exc)}))
            else:
                print(str(exc), file=sys.stderr)
            return 2
    else:
        bruto = sys.stdin.buffer.read()
        if not bruto.strip():
            erro = "stdin vazio — nenhum dossiê recebido"
            if args.json:
                print(json.dumps({"gravado": None, "erro_operacional": erro}))
            else:
                print(erro, file=sys.stderr)
            return 2

    try:
        dossie = json.loads(bruto.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        if args.json:
            print(json.dumps({"gravado": None, "erro_operacional": str(exc)}))
        else:
            print(str(exc), file=sys.stderr)
        return 2

    # investigado_em é preenchido ANTES da validação — o agente não tem
    # relógio e não deve ser responsabilizado (nem bloqueado) por esse
    # campo; a validação já vê o valor que a ferramenta vai gravar. O mesmo
    # `agora` é reusado em salvar_dossie() para o carimbo do nome do
    # arquivo, garantindo que os dois batem exatamente (D14).
    agora = datetime.now(timezone.utc)
    dossie = _preencher_investigado_em(dossie, agora)

    try:
        validar_dossie(dossie)
    except DossieInvalidoError as exc:
        if args.json:
            print(json.dumps({"gravado": False, "erro": str(exc)}))
        else:
            print(str(exc), file=sys.stderr)
        return 1

    try:
        caminho = salvar_dossie(dossie, agora=agora)
    except DossieIOError as exc:
        if args.json:
            print(json.dumps({"gravado": None, "erro_operacional": str(exc)}))
        else:
            print(str(exc), file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps({"gravado": True, "caminho": str(caminho), "investigado_em": dossie["investigado_em"]}))
    else:
        print(str(caminho))
    return 0


if __name__ == "__main__":
    sys.exit(main())
