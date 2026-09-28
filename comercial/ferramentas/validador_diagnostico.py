"""
validador_diagnostico.py — validação determinística do diagnóstico do Agente 2.

Mesmo princípio já aplicado no resto do projeto: o que é verificável por
regra não consome julgamento de LLM. Este módulo NÃO decide se um ângulo é
*bom*, nem se um fato *de fato* invalida a presunção de oportunidade da
trilha COMPLETO_SEM_SITE — isso é julgamento comercial, não estrutura.
Decide se o diagnóstico é *estruturalmente e referencialmente consistente*
com o que schemas/02_output_diagnostico.md promete ao Agente 3 e ao
Agente 4.

Duas camadas de checagem, mesma divisão de trabalho usada em
validador_dossie.py:

1. **Schema formal** (`02_output_diagnostico.schema.json`, via `jsonschema`)
   — tipos, enums, obrigatoriedade, formato dos ids, e a forma
   `prosseguir`/`sem_angulo` (achados vazio/não-vazio, angulo_principal
   nulo/preenchido, sem_angulo.fatos_ref obrigatório na trilha
   COMPLETO_SEM_SITE).
2. **Regras de referência cruzada contra o dossiê de origem** — o que JSON
   Schema não expressa bem: todo `fatos_ref`/`inferencias_ref`/
   `incertezas_ref` de todo achado aponta para um id que existe no bloco
   certo do DOSSIÊ DO AGENTE 1 (não só sintaticamente no diagnóstico);
   exatamente um achado tem `papel: principal` e `angulo_principal.achado_ref`
   aponta para ele; todo achado `evidencia` tem `reforca_achado_ref`
   apontando para um achado real deste mesmo diagnóstico; `place_id` e
   `estagio_analise` do diagnóstico batem com o dossiê de origem (eco, não
   reclassificação).

Diferente de `contrato_loader.validar()` (reporta a primeira violação — é
gate de pipeline), e igual a `validador_dossie.validar_dossie()`: este
módulo **acumula todas as violações antes de levantar**. Um diagnóstico é
produzido por LLM e revisado por humano no piloto; uma lista completa vale
mais que descobrir um problema de cada vez. Ainda assim fail-hard: não
existe "válido com ressalvas".

Uso:
    from validador_diagnostico import validar_diagnostico, carregar_schema_diagnostico

    validar_diagnostico(diagnostico, dossie_origem=dossie)  # levanta DiagnosticoInvalidoError se houver problema

Requisitos:
    pip install -r requirements.txt   (usa jsonschema)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Mapping, Optional

try:
    import jsonschema
except ModuleNotFoundError as exc:  # pragma: no cover - erro de instalação
    raise ModuleNotFoundError(
        "validador_diagnostico requer a biblioteca 'jsonschema'. "
        "Instale com: pip install -r requirements.txt"
    ) from exc


SCHEMA_DIAGNOSTICO_PADRAO = Path(__file__).resolve().parent.parent / "schemas" / "02_output_diagnostico.schema.json"


class DiagnosticoInvalidoError(Exception):
    """O diagnóstico não passou na validação — schema ou referência cruzada.

    A mensagem lista TODOS os problemas encontrados, não só o primeiro —
    ver o docstring do módulo.
    """


def carregar_schema_diagnostico(caminho: Optional[Path] = None) -> dict:
    caminho = Path(caminho) if caminho else SCHEMA_DIAGNOSTICO_PADRAO
    if not caminho.is_file():
        raise DiagnosticoInvalidoError(f"Schema do diagnóstico não encontrado: {caminho}")
    try:
        return json.loads(caminho.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise DiagnosticoInvalidoError(f"Schema do diagnóstico não é JSON válido ({caminho}): {exc}") from exc


def _erros_de_schema(diagnostico: Any, schema: dict) -> list[str]:
    classe = jsonschema.validators.validator_for(schema)
    classe.check_schema(schema)
    validador = classe(schema)
    erros = sorted(validador.iter_errors(diagnostico), key=lambda e: list(e.absolute_path))
    saida = []
    for e in erros:
        caminho = "/".join(str(p) for p in e.absolute_path) or "(raiz)"
        saida.append(f"[schema] {caminho}: {e.message}")
    return saida


def _ids(itens: list, chave: str = "id") -> set:
    return {item[chave] for item in itens if isinstance(item, Mapping) and chave in item}


def _erros_de_papel(diagnostico: Mapping) -> list[str]:
    """Regra de validação 1 e 3 do schema .md: exatamente um `principal`,
    `angulo_principal.achado_ref` aponta para ele, e todo `evidencia` tem
    `reforca_achado_ref` apontando para um achado real deste diagnóstico.

    Roda independente de `decisao` (achados é `[]` em `sem_angulo`, então
    as checagens não encontram nada para reprovar nesse caso — não é uma
    exceção especial, é o caso vazio caindo naturalmente nas mesmas regras).
    """
    erros: list[str] = []
    achados = diagnostico.get("achados", [])
    achado_ids = _ids(achados)

    principais = [a for a in achados if a.get("papel") == "principal"]
    if diagnostico.get("decisao") == "prosseguir":
        if len(principais) != 1:
            erros.append(
                f"[papel] exatamente um achado deveria ter papel='principal' quando "
                f"decisao='prosseguir'; encontrados {len(principais)}"
            )
        else:
            esperado = principais[0].get("id")
            referenciado = (diagnostico.get("angulo_principal") or {}).get("achado_ref")
            if referenciado != esperado:
                erros.append(
                    f"[papel] angulo_principal.achado_ref ({referenciado!r}) não aponta para "
                    f"o achado com papel='principal' ({esperado!r})"
                )

    for achado in achados:
        if achado.get("papel") == "evidencia":
            ref = achado.get("reforca_achado_ref")
            if ref is None:
                erros.append(
                    f"[papel] achados[{achado.get('id')}] tem papel='evidencia' mas "
                    f"reforca_achado_ref está vazio"
                )
            elif ref not in achado_ids:
                erros.append(
                    f"[papel] achados[{achado.get('id')}].reforca_achado_ref aponta para "
                    f"'{ref}', que não existe entre os achados deste diagnóstico"
                )

    return erros


def _erros_de_referencia_contra_dossie(diagnostico: Mapping, dossie_origem: Mapping) -> list[str]:
    """Todo fatos_ref/inferencias_ref/incertezas_ref de todo achado, e todo
    sem_angulo.fatos_ref/evidencias_consideradas, apontam para um id que
    existe no bloco certo do DOSSIÊ DO AGENTE 1 — não só sintaticamente
    válido no diagnóstico (isso o schema formal já garante via o padrão do
    id), mas referencialmente real.
    """
    erros: list[str] = []
    fato_ids = _ids(dossie_origem.get("fatos_observados", []))
    inf_ids = _ids(dossie_origem.get("inferencias", []))
    inc_ids = _ids(dossie_origem.get("incertezas", []))

    for achado in diagnostico.get("achados", []):
        aid = achado.get("id")
        for ref in achado.get("fatos_ref", []):
            if ref not in fato_ids:
                erros.append(
                    f"[referencia] achados[{aid}].fatos_ref aponta para '{ref}', que não "
                    f"existe em fatos_observados do dossiê de origem"
                )
        for ref in achado.get("inferencias_ref", []) or []:
            if ref not in inf_ids:
                erros.append(
                    f"[referencia] achados[{aid}].inferencias_ref aponta para '{ref}', que não "
                    f"existe em inferencias do dossiê de origem"
                )
        for ref in achado.get("incertezas_ref", []) or []:
            if ref not in inc_ids:
                erros.append(
                    f"[referencia] achados[{aid}].incertezas_ref aponta para '{ref}', que não "
                    f"existe em incertezas do dossiê de origem"
                )

    sem_angulo = diagnostico.get("sem_angulo")
    if sem_angulo:
        for ref in sem_angulo.get("fatos_ref", []):
            if ref not in fato_ids:
                erros.append(
                    f"[referencia] sem_angulo.fatos_ref aponta para '{ref}', que não existe "
                    f"em fatos_observados do dossiê de origem"
                )
        for ref in sem_angulo.get("evidencias_consideradas", []):
            todos = fato_ids | inf_ids | inc_ids
            if ref not in todos:
                erros.append(
                    f"[referencia] sem_angulo.evidencias_consideradas aponta para '{ref}', que "
                    f"não existe em nenhum bloco de evidência do dossiê de origem"
                )

    return erros


def _erros_contra_dossie_origem(diagnostico: Mapping, dossie_origem: Mapping) -> list[str]:
    """place_id e estagio_analise são eco do dossiê de origem, não reclassificação."""
    erros = []

    if diagnostico.get("place_id") != dossie_origem.get("place_id"):
        erros.append(
            f"[origem] place_id do diagnóstico ({diagnostico.get('place_id')!r}) difere do "
            f"dossiê de origem ({dossie_origem.get('place_id')!r})"
        )

    estagio_dossie = (
        dossie_origem.get("qualificador", {})
        .get("sinais_recebidos", {})
        .get("estagio_analise")
    )
    if diagnostico.get("estagio_analise") != estagio_dossie:
        erros.append(
            f"[origem] estagio_analise do diagnóstico ({diagnostico.get('estagio_analise')!r}) "
            f"difere de qualificador.sinais_recebidos.estagio_analise do dossiê de origem "
            f"({estagio_dossie!r}) — deveria ser eco, não reclassificação"
        )

    return erros


def validar_diagnostico(
    diagnostico: Mapping,
    *,
    dossie_origem: Optional[Mapping] = None,
    schema: Optional[dict] = None,
    schema_path: Optional[Path] = None,
) -> None:
    """Valida um diagnóstico do Agente 2. Levanta `DiagnosticoInvalidoError`
    com a lista completa de problemas encontrados; não levanta nada se o
    diagnóstico passar em todas as checagens.

    Args:
        diagnostico: o documento JSON do diagnóstico (dict já carregado).
        dossie_origem: o dossiê do Agente 1 (dict) usado como base deste
            diagnóstico — necessário para as checagens de referência
            cruzada (fatos_ref/inferencias_ref/incertezas_ref reais) e de
            eco (place_id, estagio_analise). Se omitido, essas checagens
            são puladas (útil para validar só a forma do diagnóstico).
        schema: schema já carregado (dict). Se omitido, carrega de
            `schema_path` ou do caminho padrão.
        schema_path: caminho alternativo do schema, ignorado se `schema` for dado.
    """
    esquema = schema if schema is not None else carregar_schema_diagnostico(schema_path)

    problemas: list[str] = []
    problemas.extend(_erros_de_schema(diagnostico, esquema))

    # As checagens de referência pressupõem a forma básica do documento —
    # só rodam se o schema já não reprovou a raiz.
    if not any(p.startswith("[schema] (raiz)") for p in problemas):
        problemas.extend(_erros_de_papel(diagnostico))
        if dossie_origem is not None:
            problemas.extend(_erros_de_referencia_contra_dossie(diagnostico, dossie_origem))
            problemas.extend(_erros_contra_dossie_origem(diagnostico, dossie_origem))

    if problemas:
        lista = "\n".join(f"  - {p}" for p in problemas)
        raise DiagnosticoInvalidoError(
            f"Diagnóstico reprovado na validação — {len(problemas)} problema(s):\n{lista}"
        )


def main(argv: Optional[list[str]] = None) -> int:
    """CLI fina sobre `validar_diagnostico` — não decide nada, só chama.

    Dois argumentos obrigatórios, não um: as checagens de referência cruzada
    (fatos_ref/inferencias_ref/incertezas_ref e o eco de place_id/
    estagio_analise) só rodam contra o dossiê de origem real. Uma CLI de um
    argumento só validaria a forma do diagnóstico, não a referência — e
    esconderia a classe de erro mais provável em produção.

    Modo humano (sem --json): a mensagem de erro vai para stderr na
    codificação local do console — correta numa tela interativa, mas NÃO
    segura se um processo capturar essa saída assumindo UTF-8. Consumo
    automatizado (hook, pipeline) deve sempre usar --json, que é ASCII
    puro e decodifica em qualquer codificação.
    """
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("diagnostico", type=Path, help="Caminho do diagnóstico (JSON) a validar")
    ap.add_argument("dossie_origem", type=Path, help="Caminho do dossiê do Agente 1 que originou este diagnóstico (JSON)")
    ap.add_argument(
        "--json", action="store_true",
        help="Saída em JSON. Exit codes: 0 válido · 1 diagnóstico reprovado "
             "na validação · 2 não foi possível validar (arquivo ausente, "
             "ilegível, ou JSON malformado).",
    )
    args = ap.parse_args(argv)

    try:
        diagnostico = json.loads(args.diagnostico.read_text(encoding="utf-8"))
        dossie_origem = json.loads(args.dossie_origem.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        if args.json:
            print(json.dumps({"valido": None, "erro_operacional": str(exc)}))
        else:
            print(str(exc), file=sys.stderr)
        return 2

    try:
        validar_diagnostico(diagnostico, dossie_origem=dossie_origem)
    except DiagnosticoInvalidoError as exc:
        if args.json:
            print(json.dumps({"valido": False, "erro": str(exc)}))
        else:
            print(str(exc), file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps({"valido": True}))
    else:
        print(f"OK: {args.diagnostico} é um diagnóstico válido.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
