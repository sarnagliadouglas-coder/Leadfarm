"""
Testes que os exemplos completos de schemas/NN_*.md continuam válidos contra
o .schema.json correspondente — Etapa 5.2 do GUIA-IMPLEMENTACAO.md.

Por quê: o `.schema.json` valida o artefato real; o exemplo em Markdown é
prosa solta, sem checagem própria. Exemplo errado é pior que exemplo ausente
— quem copia não sabe se o erro é dele ou do modelo.

Escopo, e por quê é este e não "cada schemas/NN_*.md": só 01 e 02 têm
`.schema.json` formal contra o qual validar. `03_output_copy.md` é stub (só
TODOs, sem schema — nada foi especificado ainda, `comercial/CLAUDE.md` §5
regra 1 entra sozinha quando o A3 for especificado). `04_output_revisao.md`
é parcial (sem `.schema.json`, sem bloco de exemplo). `output_final.md` é
stub. Nenhum dos três tem contra o que este teste possa validar.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

FERRAMENTAS_DIR = Path(__file__).resolve().parent.parent / "ferramentas"
SCHEMAS_DIR = Path(__file__).resolve().parent.parent / "schemas"
sys.path.insert(0, str(FERRAMENTAS_DIR))

import jsonschema  # noqa: E402


def _extrair_blocos_json_da_secao(md_texto: str, cabecalho: str) -> list[dict]:
    """Extrai todo bloco ```json ...``` dentro da seção `## <cabecalho>` até
    o próximo `## ` (ou fim do arquivo). Levanta se a seção não existir ou
    não tiver nenhum bloco — silêncio aqui esconderia um exemplo removido.
    """
    padrao_secao = re.compile(
        rf"^## {re.escape(cabecalho)}\s*$(.*?)(?=^## |\Z)",
        re.MULTILINE | re.DOTALL,
    )
    m = padrao_secao.search(md_texto)
    if not m:
        raise AssertionError(f"Seção '## {cabecalho}' não encontrada")

    corpo = m.group(1)
    blocos = re.findall(r"```json\s*\n(.*?)\n```", corpo, re.DOTALL)
    if not blocos:
        raise AssertionError(f"Nenhum bloco ```json``` na seção '## {cabecalho}'")
    return [json.loads(b) for b in blocos]


@pytest.mark.parametrize(
    "md_nome, schema_nome",
    [
        ("01_output_investigacao.md", "01_output_investigacao.schema.json"),
        ("02_output_diagnostico.md", "02_output_diagnostico.schema.json"),
    ],
)
def test_exemplo_do_schema_valida_contra_json_schema(md_nome, schema_nome):
    md_texto = (SCHEMAS_DIR / md_nome).read_text(encoding="utf-8")
    schema = json.loads((SCHEMAS_DIR / schema_nome).read_text(encoding="utf-8"))

    exemplos = _extrair_blocos_json_da_secao(md_texto, "Exemplo")
    assert exemplos, f"Nenhum exemplo extraído de {md_nome}"

    for i, exemplo in enumerate(exemplos):
        try:
            jsonschema.validate(instance=exemplo, schema=schema)
        except jsonschema.ValidationError as exc:
            pytest.fail(
                f"{md_nome}: exemplo #{i + 1} da seção '## Exemplo' não valida "
                f"contra {schema_nome} — {exc.message} (caminho: {list(exc.path)})"
            )
