"""Conversor da relação oficial de municípios do INE para `config/municipios_ine.json`.

Lê o .xlsx "Relación de municipios y códigos por comunidades autónomas y
provincias" (diccionario de códigos municipais do Instituto Nacional de
Estadística, arquivo "Fichero completo") e grava um JSON determinístico com um
registro por município: código INE (CPRO + CMUN), nome exatamente como no INE e
as grafias oficiais aceitáveis ("formas").

Determinístico, custo $0, sem LLM e sem rede: o mesmo .xlsx e os mesmos
metadados geram sempre o mesmo JSON. Nenhuma grafia é inventada — toda forma
deriva mecanicamente do texto oficial:

- nome bilíngue ("Elche/Elx") é dividido nas partes separadas por "/";
- parte com artigo posposto no padrão do INE ("Rozas de Madrid, Las") ganha
  também a forma com o artigo na frente ("Las Rozas de Madrid"); a forma
  original é mantida. Artigo terminado em apóstrofo ("Ametlla de Mar, L'")
  cola na palavra seguinte ("L'Ametlla de Mar").

O conjunto de artigos pospostos reconhecidos (`ARTIGOS_POSPOSTOS`) é fechado e
foi levantado do próprio arquivo de 01/01/2026. Uma vírgula cujo trecho final
não seja um desses artigos (por exemplo "Castell d'Aro, Platja d'Aro i
s'Agaró") não é tratada como artigo posposto e o nome fica como está.

Uso (o caminho do .xlsx e os metadados da fonte vêm por argumento; nenhum
caminho de máquina fica no código):

    python gerar_municipios_ine.py ARQUIVO.xlsx --saida config/municipios_ine.json \\
        --titulo "..." --url "..." --pagina "..." \\
        --data-referencia 2026-01-01 --obtido-em 2026-10-06
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import openpyxl

# Artigos que o INE posposta ao nome ("Nome, Artigo"), comparados em minúsculas.
ARTIGOS_POSPOSTOS = frozenset(
    {"la", "el", "los", "las", "les", "els", "a", "o", "as", "os", "es", "sa", "ses", "l'"}
)

ORGAO = "Instituto Nacional de Estadística (INE)"
COLUNAS = ("CPRO", "CMUN", "NOMBRE")


def _forma_com_artigo_na_frente(parte: str) -> str | None:
    """Devolve a forma com artigo na frente, ou None se a parte não tem artigo posposto."""
    base, sep, artigo = parte.rpartition(", ")
    if not sep or not base.strip() or artigo.strip().lower() not in ARTIGOS_POSPOSTOS:
        return None
    artigo = artigo.strip()
    junta = "" if artigo.endswith("'") else " "
    return f"{artigo}{junta}{base.strip()}"


def formas_do_nome(nome: str) -> list[str]:
    """Grafias oficiais aceitáveis de um nome do INE, sem duplicatas, em ordem estável."""
    formas: list[str] = []
    for parte in nome.split("/"):
        parte = parte.strip()
        if not parte:
            continue
        candidatas = [parte]
        movida = _forma_com_artigo_na_frente(parte)
        if movida:
            candidatas.append(movida)
        for forma in candidatas:
            if forma not in formas:
                formas.append(forma)
    return formas


def _texto(valor, largura: int | None = None) -> str:
    """Célula como texto; número vira texto com zeros à esquerda quando há largura."""
    if valor is None:
        return ""
    if isinstance(valor, float) and valor.is_integer():
        valor = int(valor)
    texto = str(valor).strip()
    if largura and texto.isdigit():
        texto = texto.zfill(largura)
    return texto


def ler_municipios(caminho_xlsx: Path) -> list[dict]:
    """Lê a primeira planilha e devolve os municípios ordenados por `codigo_ine`."""
    planilha = openpyxl.load_workbook(caminho_xlsx, read_only=True, data_only=True).worksheets[0]
    indices: dict[str, int] | None = None
    municipios: dict[str, dict] = {}
    for linha in planilha.iter_rows(values_only=True):
        if indices is None:
            cabecalho = [_texto(c).upper() for c in linha]
            if all(c in cabecalho for c in COLUNAS):
                indices = {c: cabecalho.index(c) for c in COLUNAS}
            continue
        cpro = _texto(linha[indices["CPRO"]], 2)
        cmun = _texto(linha[indices["CMUN"]], 3)
        nombre = _texto(linha[indices["NOMBRE"]])
        if not (cpro or cmun or nombre):
            continue
        if not (cpro and cmun and nombre):
            raise ValueError(f"linha incompleta (CPRO={cpro!r}, CMUN={cmun!r}, NOMBRE={nombre!r})")
        codigo = cpro + cmun
        if codigo in municipios:
            raise ValueError(f"codigo_ine duplicado: {codigo}")
        municipios[codigo] = {
            "codigo_ine": codigo,
            "cpro": cpro,
            "cmun": cmun,
            "nombre": nombre,
            "formas": formas_do_nome(nombre),
        }
    if indices is None:
        raise ValueError(f"cabeçalho com as colunas {COLUNAS} não encontrado em {caminho_xlsx.name}")
    return [municipios[c] for c in sorted(municipios)]


def montar_saida(caminho_xlsx: Path, *, titulo: str, url: str, pagina: str,
                 data_referencia: str, obtido_em: str) -> dict:
    """Monta o documento completo (fonte + municípios)."""
    conteudo = caminho_xlsx.read_bytes()
    municipios = ler_municipios(caminho_xlsx)
    return {
        "fonte": {
            "orgao": ORGAO,
            "titulo": titulo,
            "url": url,
            "pagina": pagina,
            "data_referencia": data_referencia,
            "obtido_em": obtido_em,
            "arquivo_original": caminho_xlsx.name,
            "sha256_arquivo_original": hashlib.sha256(conteudo).hexdigest(),
            "bytes_arquivo_original": len(conteudo),
        },
        "total_municipios": len(municipios),
        "municipios": municipios,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("xlsx", type=Path, help="arquivo .xlsx original do INE")
    ap.add_argument("--saida", type=Path, required=True, help="JSON de saída")
    ap.add_argument("--titulo", required=True)
    ap.add_argument("--url", required=True)
    ap.add_argument("--pagina", required=True)
    ap.add_argument("--data-referencia", required=True)
    ap.add_argument("--obtido-em", required=True)
    args = ap.parse_args(argv)

    doc = montar_saida(
        args.xlsx, titulo=args.titulo, url=args.url, pagina=args.pagina,
        data_referencia=args.data_referencia, obtido_em=args.obtido_em,
    )
    args.saida.parent.mkdir(parents=True, exist_ok=True)
    args.saida.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"{doc['total_municipios']} municípios gravados em {args.saida}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
