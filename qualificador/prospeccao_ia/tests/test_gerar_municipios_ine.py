"""Conversor da relação de municípios do INE (`gerar_municipios_ine`).
Tudo em tmp_path, com um .xlsx fictício no mesmo layout do arquivo oficial (título,
cabeçalho CODAUTO/CPRO/CMUN/DC/NOMBRE, uma linha por município). Nomes inventados."""
import hashlib
import json

import openpyxl
import pytest

import gerar_municipios_ine as g

LINHAS = [
    ("01", "07", "012", "3", "Vilaverde/Villaverde"),       # bilíngue, zeros à esquerda
    ("01", "07", "003", "1", "Rozas de Prova, Las"),        # artigo posposto
    ("02", "43", "101", "2", "Ametlla de Teste, L'"),       # apóstrofo
    ("02", "43", "009", "5", "Vall Falsa, la/Vall Falsa de Prova"),  # bilíngue + artigo na 1ª parte
    ("03", "50", "001", "7", "Cidade Qualquer"),
    ("03", "50", "002", "9", "Castell Falso, Praia Falsa i s'Agaro"),  # vírgula que não é artigo
    (7, 5, 4, "1", "Numerica"),                             # células numéricas
]


def _xlsx(tmp_path, linhas=LINHAS):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Relación fictícia de municípios", None, None, None, None])
    ws.append(["CODAUTO", "CPRO", "CMUN", "DC", "NOMBRE"])
    for lin in linhas:
        ws.append(list(lin))
    caminho = tmp_path / "fake.xlsx"
    wb.save(caminho)
    return caminho


def _gerar(tmp_path):
    xlsx = _xlsx(tmp_path)
    saida = tmp_path / "out" / "m.json"
    rc = g.main([str(xlsx), "--saida", str(saida), "--titulo", "Titulo Ficticio",
                 "--url", "https://exemplo.invalid/f.xlsx", "--pagina", "https://exemplo.invalid/p",
                 "--data-referencia", "2026-01-01", "--obtido-em", "2026-10-06"])
    assert rc == 0
    return xlsx, json.loads(saida.read_text(encoding="utf-8"))


def _por_codigo(doc):
    return {m["codigo_ine"]: m for m in doc["municipios"]}


def test_formas_bilingues(tmp_path):
    _, doc = _gerar(tmp_path)
    assert _por_codigo(doc)["07012"]["formas"] == ["Vilaverde", "Villaverde"]
    assert _por_codigo(doc)["07012"]["nombre"] == "Vilaverde/Villaverde"


def test_artigo_posposto_movido_e_original_mantido(tmp_path):
    _, doc = _gerar(tmp_path)
    assert _por_codigo(doc)["07003"]["formas"] == ["Rozas de Prova, Las", "Las Rozas de Prova"]


def test_apostrofo_sem_espaco(tmp_path):
    _, doc = _gerar(tmp_path)
    assert _por_codigo(doc)["43101"]["formas"] == ["Ametlla de Teste, L'", "L'Ametlla de Teste"]


def test_bilingue_com_artigo_na_primeira_parte(tmp_path):
    _, doc = _gerar(tmp_path)
    assert _por_codigo(doc)["43009"]["formas"] == [
        "Vall Falsa, la", "la Vall Falsa", "Vall Falsa de Prova"]


def test_virgula_que_nao_e_artigo_nao_e_movida(tmp_path):
    _, doc = _gerar(tmp_path)
    assert _por_codigo(doc)["50002"]["formas"] == ["Castell Falso, Praia Falsa i s'Agaro"]


def test_codigo_com_zeros_a_esquerda_e_celulas_numericas(tmp_path):
    _, doc = _gerar(tmp_path)
    m = _por_codigo(doc)["05004"]
    assert (m["cpro"], m["cmun"], m["codigo_ine"]) == ("05", "004", "05004")
    assert _por_codigo(doc)["07012"]["cpro"] == "07"


def test_ordem_por_codigo_e_total(tmp_path):
    _, doc = _gerar(tmp_path)
    codigos = [m["codigo_ine"] for m in doc["municipios"]]
    assert codigos == sorted(codigos)
    assert doc["total_municipios"] == len(codigos) == len(LINHAS)


def test_sem_formas_duplicadas():
    assert g.formas_do_nome("Igual/Igual") == ["Igual"]


def test_metadados_gravados(tmp_path):
    xlsx, doc = _gerar(tmp_path)
    f = doc["fonte"]
    assert f["orgao"] == "Instituto Nacional de Estadística (INE)"
    assert f["titulo"] == "Titulo Ficticio"
    assert f["url"] == "https://exemplo.invalid/f.xlsx"
    assert f["pagina"] == "https://exemplo.invalid/p"
    assert f["data_referencia"] == "2026-01-01"
    assert f["obtido_em"] == "2026-10-06"
    assert f["arquivo_original"] == "fake.xlsx"
    assert f["sha256_arquivo_original"] == hashlib.sha256(xlsx.read_bytes()).hexdigest()
    assert f["bytes_arquivo_original"] == xlsx.stat().st_size


def test_codigo_duplicado_falha(tmp_path):
    xlsx = _xlsx(tmp_path, [("01", "07", "001", "1", "A"), ("01", "07", "001", "2", "B")])
    with pytest.raises(ValueError, match="duplicado"):
        g.ler_municipios(xlsx)
