"""
validador_dossie.py — validação determinística do dossiê do Agente 1.

Mesmo princípio já aplicado no resto do projeto (contrato_loader.py): o que é
verificável por regra não consome julgamento de LLM. Este módulo NÃO decide
se o conteúdo do dossiê é *bom* — decide se ele é *estruturalmente e
referencialmente consistente* com o que schemas/01_output_investigacao.md
promete ao Agente 2 e ao Agente 4.

Duas camadas de checagem, na mesma divisão de trabalho usada no contrato do
QUALIFICADOR:

1. **Schema formal** (`01_output_investigacao.schema.json`, via `jsonschema`)
   — tipos, enums, obrigatoriedade, formato dos ids.
2. **Regras de referência cruzada** — o que JSON Schema não expressa bem:
   todo `*_ref` aponta para um id que existe no bloco certo (nunca para uma
   `inferencia` onde o schema espera um `fato_observado` — Regra de
   validação 9), o eco de `rating_coletado`/`total_avaliacoes_coletado`
   bate com o que o contrato do QUALIFICADOR realmente enviou (é eco, não
   recálculo — divergência aqui é bug do A1, não sinal comercial),
   `divergencias_com_qualificador` só referencia campos reais, e o
   `place_id` do dossiê é o mesmo do lead de origem.

Diferença deliberada de estilo em relação a `contrato_loader.validar()`:
aquele reporta a *primeira* violação de schema (é gate de pipeline, uma
falha já basta para recusar o arquivo). Este módulo **acumula todas as
violações encontradas antes de levantar** — um dossiê é produzido por LLM
e revisado por humano no piloto; uma lista completa de problemas vale mais
que descobrir um de cada vez. Ainda assim, é fail-hard: não existe modo
permissivo, e `validar_dossie` nunca devolve "válido com ressalvas" — ou
levanta com a lista completa, ou não levanta.

Uso:
    from validador_dossie import validar_dossie, carregar_schema_dossie

    validar_dossie(dossie, lead_origem=lead_bruto)   # levanta DossieInvalidoError se houver problema

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
        "validador_dossie requer a biblioteca 'jsonschema'. "
        "Instale com: pip install -r requirements.txt"
    ) from exc


SCHEMA_DOSSIE_PADRAO = Path(__file__).resolve().parent.parent / "schemas" / "01_output_investigacao.schema.json"

# Campos aceitos em negocio.divergencias_com_qualificador[].campo — os que têm
# par coletado/verificado explícito, mais os campos de identidade simples que
# o Agente 1 pode comparar contra identidade.* do contrato (ex.: nicho).
CAMPOS_DIVERGENCIA_VALIDOS = frozenset({
    "rating", "total_avaliacoes", "nicho", "nome", "localizacao", "website", "google_maps_url",
})


class DossieInvalidoError(Exception):
    """O dossiê não passou na validação — schema ou referência cruzada.

    A mensagem lista TODOS os problemas encontrados, não só o primeiro —
    ver o docstring do módulo.
    """


def carregar_schema_dossie(caminho: Optional[Path] = None) -> dict:
    caminho = Path(caminho) if caminho else SCHEMA_DOSSIE_PADRAO
    if not caminho.is_file():
        raise DossieInvalidoError(f"Schema do dossiê não encontrado: {caminho}")
    try:
        return json.loads(caminho.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise DossieInvalidoError(f"Schema do dossiê não é JSON válido ({caminho}): {exc}") from exc


def _erros_de_schema(dossie: Any, schema: dict) -> list[str]:
    classe = jsonschema.validators.validator_for(schema)
    classe.check_schema(schema)
    validador = classe(schema)
    erros = sorted(validador.iter_errors(dossie), key=lambda e: list(e.absolute_path))
    saida = []
    for e in erros:
        caminho = "/".join(str(p) for p in e.absolute_path) or "(raiz)"
        saida.append(f"[schema] {caminho}: {e.message}")
    return saida


def _ids(itens: list, chave: str = "id") -> set:
    return {item[chave] for item in itens if isinstance(item, Mapping) and chave in item}


def _erros_de_referencia(dossie: Mapping) -> list[str]:
    """Regras de validação 1, 6, 9, 10 do schema .md — não expressáveis em JSON Schema puro."""
    erros: list[str] = []

    fato_ids = _ids(dossie.get("fatos_observados", []))
    fonte_ids = _ids(dossie.get("fontes_dos_fatos", []))

    # Regra 1: todo fato_observado referencia >=1 fonte que existe
    for fato in dossie.get("fatos_observados", []):
        for ref in fato.get("fontes_ref", []):
            if ref not in fonte_ids:
                disponiveis = ", ".join(sorted(fonte_ids)) or "(nenhuma fonte declarada)"
                erros.append(
                    f"[referencia] fatos_observados[{fato.get('id')}].fontes_ref aponta para "
                    f"'{ref}', que não existe em fontes_dos_fatos; ids disponíveis: {disponiveis}. "
                    f"Se o fato veio de uma leitura cruzada e não de observação direta, ele "
                    f"pertence a 'inferencias', não a 'fatos_observados'."
                )

    # Regra 10: toda inferencia é baseada em >=1 fato que existe
    for inf in dossie.get("inferencias", []):
        for ref in inf.get("baseada_em", []):
            if ref not in fato_ids:
                erros.append(
                    f"[referencia] inferencias[{inf.get('id')}].baseada_em aponta para "
                    f"'{ref}', que não existe em fatos_observados"
                )

    # incertezas.sinais_conflitantes -- mesma lógica, campo opcional
    for inc in dossie.get("incertezas", []):
        for ref in inc.get("sinais_conflitantes", []) or []:
            if ref not in fato_ids:
                erros.append(
                    f"[referencia] incertezas[{inc.get('id')}].sinais_conflitantes aponta para "
                    f"'{ref}', que não existe em fatos_observados"
                )

    # Regra 9: por_dispositivo.*.fatos_ref só aponta para fatos_observados reais
    # (o padrão "^fato_" do schema já barra um id de inferencia por engano de
    # prefixo; esta checagem barra também um "fato_099" que não existe)
    por_dispositivo = dossie.get("por_dispositivo", {})
    for dispositivo in ("mobile", "desktop"):
        bloco = por_dispositivo.get(dispositivo, {})
        for ref in bloco.get("fatos_ref", []):
            if ref not in fato_ids:
                erros.append(
                    f"[referencia] por_dispositivo.{dispositivo}.fatos_ref aponta para "
                    f"'{ref}', que não existe em fatos_observados"
                )

    # jornada_principal.etapas[].fato_ref e caminhos_alternativos[].fato_ref
    jornada = dossie.get("jornada_principal", {})
    for i, etapa in enumerate(jornada.get("etapas", [])):
        ref = etapa.get("fato_ref")
        if ref is not None and ref not in fato_ids:
            erros.append(
                f"[referencia] jornada_principal.etapas[{i}].fato_ref aponta para "
                f"'{ref}', que não existe em fatos_observados"
            )
    for i, caminho in enumerate(jornada.get("caminhos_alternativos", [])):
        ref = caminho.get("fato_ref")
        if ref is not None and ref not in fato_ids:
            erros.append(
                f"[referencia] jornada_principal.caminhos_alternativos[{i}].fato_ref aponta "
                f"para '{ref}', que não existe em fatos_observados"
            )

    # qualificador.procedencia[].fatos_ref
    for i, entrada in enumerate(dossie.get("qualificador", {}).get("procedencia", [])):
        for ref in entrada.get("fatos_ref", []):
            if ref not in fato_ids:
                erros.append(
                    f"[referencia] qualificador.procedencia[{i}].fatos_ref aponta para "
                    f"'{ref}', que não existe em fatos_observados"
                )

    return erros


def _erros_de_divergencia(dossie: Mapping) -> list[str]:
    """Cada divergencias_com_qualificador[].campo referencia um campo real."""
    erros = []
    for i, div in enumerate(dossie.get("negocio", {}).get("divergencias_com_qualificador", [])):
        campo = div.get("campo")
        if campo not in CAMPOS_DIVERGENCIA_VALIDOS:
            erros.append(
                f"[divergencia] negocio.divergencias_com_qualificador[{i}].campo = {campo!r} "
                f"não é um campo reconhecido (esperado um de {sorted(CAMPOS_DIVERGENCIA_VALIDOS)})"
            )
    return erros


def _erros_contra_lead_origem(dossie: Mapping, lead_origem: Mapping) -> list[str]:
    """Confere o dossiê contra o lead de origem do contrato: place_id e o eco
    fiel de rating/total_avaliacoes coletados.

    `rating_coletado`/`total_avaliacoes_coletado` são ECO, não recálculo —
    ver schemas/01_output_investigacao.md, bloco `negocio`. Uma divergência
    aqui é bug de transcrição do A1, não sinal comercial (isso é o que
    `divergencias_com_qualificador` existe para carregar).
    """
    erros = []

    if dossie.get("place_id") != lead_origem.get("place_id"):
        erros.append(
            f"[origem] place_id do dossiê ({dossie.get('place_id')!r}) difere do "
            f"lead de origem ({lead_origem.get('place_id')!r})"
        )

    negocio = dossie.get("negocio", {})
    reputacao = lead_origem.get("reputacao", {})

    rating_dossie = negocio.get("rating_coletado")
    rating_lead = reputacao.get("nota_google")
    if rating_dossie != rating_lead:
        erros.append(
            f"[origem] negocio.rating_coletado ({rating_dossie!r}) não bate com "
            f"reputacao.nota_google do lead de origem ({rating_lead!r}) — deveria ser eco fiel"
        )

    avaliacoes_dossie = negocio.get("total_avaliacoes_coletado")
    avaliacoes_lead = reputacao.get("review_count")
    if avaliacoes_dossie != avaliacoes_lead:
        erros.append(
            f"[origem] negocio.total_avaliacoes_coletado ({avaliacoes_dossie!r}) não bate com "
            f"reputacao.review_count do lead de origem ({avaliacoes_lead!r}) — deveria ser eco fiel"
        )

    return erros


def validar_dossie(
    dossie: Mapping,
    *,
    lead_origem: Optional[Mapping] = None,
    schema: Optional[dict] = None,
    schema_path: Optional[Path] = None,
) -> None:
    """Valida um dossiê do Agente 1. Levanta `DossieInvalidoError` com a
    lista completa de problemas encontrados; não levanta nada se o dossiê
    passar em todas as checagens.

    Args:
        dossie: o documento JSON do dossiê (dict já carregado).
        lead_origem: o lead bruto do contrato (dict) que originou este
            dossiê — necessário para as checagens de `place_id` e do eco
            de rating/avaliações. Se omitido, essas duas checagens são
            puladas (útil para validar só a forma do dossiê, sem o lead).
        schema: schema já carregado (dict). Se omitido, carrega de
            `schema_path` ou do caminho padrão.
        schema_path: caminho alternativo do schema, ignorado se `schema` for dado.
    """
    esquema = schema if schema is not None else carregar_schema_dossie(schema_path)

    problemas: list[str] = []
    problemas.extend(_erros_de_schema(dossie, esquema))

    # As checagens de referência pressupõem a forma básica do documento
    # (arrays presentes) — só rodam se o schema já não reprovou a raiz.
    if not any(p.startswith("[schema] (raiz)") for p in problemas):
        problemas.extend(_erros_de_referencia(dossie))
        problemas.extend(_erros_de_divergencia(dossie))
        if lead_origem is not None:
            problemas.extend(_erros_contra_lead_origem(dossie, lead_origem))

    if problemas:
        lista = "\n".join(f"  - {p}" for p in problemas)
        raise DossieInvalidoError(
            f"Dossiê reprovado na validação — {len(problemas)} problema(s):\n{lista}"
        )


def main(argv: Optional[list[str]] = None) -> int:
    """CLI fina sobre `validar_dossie` — não decide nada, só chama.

    Modo humano (sem --json): a mensagem de erro vai para stderr na
    codificação local do console — correta numa tela interativa, mas NÃO
    segura se um processo capturar essa saída assumindo UTF-8. Consumo
    automatizado (hook, pipeline) deve sempre usar --json, que é ASCII
    puro e decodifica em qualquer codificação.
    """
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("dossie", type=Path, help="Caminho do dossiê (JSON) a validar")
    ap.add_argument(
        "--lead-origem", type=Path, default=None,
        help="Caminho do lead de origem (JSON). Sem ele, as checagens de "
             "place_id e eco de rating/avaliações são puladas.",
    )
    ap.add_argument(
        "--json", action="store_true",
        help="Saída em JSON. Exit codes: 0 válido · 1 dossiê reprovado na "
             "validação · 2 não foi possível validar (arquivo ausente, "
             "ilegível, ou JSON malformado).",
    )
    args = ap.parse_args(argv)

    try:
        dossie = json.loads(args.dossie.read_text(encoding="utf-8"))
        lead_origem = (
            json.loads(args.lead_origem.read_text(encoding="utf-8"))
            if args.lead_origem else None
        )
    except (OSError, json.JSONDecodeError) as exc:
        if args.json:
            print(json.dumps({"valido": None, "erro_operacional": str(exc)}))
        else:
            print(str(exc), file=sys.stderr)
        return 2

    try:
        validar_dossie(dossie, lead_origem=lead_origem)
    except DossieInvalidoError as exc:
        if args.json:
            print(json.dumps({"valido": False, "erro": str(exc)}))
        else:
            print(str(exc), file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps({"valido": True}))
    else:
        print(f"OK: {args.dossie} é um dossiê válido.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
