"""Contrato EXTRATOR -> QUALIFICADOR: validação de header do CSV e do sidecar .meta.json
(csv_contrato) + reconciliação de contagem no import (main.importar_csv).
"""
import json

import pytest

import csv_contrato
import main as main_mod
from agent_coletor import AgentColetor

HEADER_COMPLETO = list(csv_contrato.COLUNAS_OBRIGATORIAS_V1)


def _linha_csv(valores):
    return ",".join('"' + v.replace('"', '""') + '"' for v in valores)


def _escrever_csv(tmp_path, colunas, linhas_de_valores, sidecar=None, nome="extrator_x_v1.csv"):
    csv_path = tmp_path / nome
    conteudo = _linha_csv(colunas) + "\n"
    for vals in linhas_de_valores:
        conteudo += _linha_csv(vals) + "\n"
    csv_path.write_text(conteudo, encoding="utf-8-sig")
    if sidecar is not None:
        (tmp_path / (nome[:-4] + ".meta.json")).write_text(json.dumps(sidecar), encoding="utf-8")
    return csv_path


def _uma_linha(**over):
    d = {c: "" for c in HEADER_COMPLETO}
    d.update({"Name": "Clínica Ejemplo", "Phone": "612345678", "Categories": "Fisioterapeuta",
              "Place Id": "pid-x"})
    d.update(over)
    return [d[c] for c in HEADER_COMPLETO]


# --- validar_header ----------------------------------------------------------------------

def test_header_completo_passa_sem_aviso():
    assert csv_contrato.validar_header(HEADER_COMPLETO) == []


def test_header_com_obrigatoria_faltando_levanta_listando_todas():
    parcial = [c for c in HEADER_COMPLETO if c not in ("LinkedIn", "Owner")]
    with pytest.raises(csv_contrato.ContratoCsvInvalido) as exc:
        csv_contrato.validar_header(parcial)
    assert "LinkedIn" in str(exc.value) and "Owner" in str(exc.value)


def test_header_com_coluna_extra_passa_com_aviso():
    avisos = csv_contrato.validar_header(HEADER_COMPLETO + ["ColunaNova"])
    assert avisos and "ColunaNova" in avisos[0]


# --- validar_sidecar --------------------------------------------------------------------

def test_sidecar_ausente_nao_falha_so_avisa(tmp_path):
    csv_path = _escrever_csv(tmp_path, HEADER_COMPLETO, [_uma_linha()], sidecar=None)
    sc, avisos = csv_contrato.validar_sidecar(str(csv_path))
    assert sc is None
    assert avisos and "ausente" in avisos[0]


# Meta v2 (Tarefa 3, 06/10/2026) substituiu "schema_version 2 levanta": a regra agora é
# "versão fora de (1, 2) levanta" -- o controle negativo continua, com 3, 0, "2" e True.
@pytest.mark.parametrize("versao", [3, 0, None, "2", True])
def test_sidecar_schema_version_fora_do_contrato_levanta(tmp_path, versao):
    csv_path = _escrever_csv(tmp_path, HEADER_COMPLETO, [_uma_linha()],
                             sidecar={"schema_version": versao, "plataforma": "google",
                                      "termo_busca": None, "termo_busca_origem": "ausente"})
    with pytest.raises(csv_contrato.ContratoCsvInvalido) as exc:
        csv_contrato.validar_sidecar(str(csv_path))
    assert f"schema_version={versao!r}" in str(exc.value) and "suporta 1 ou 2" in str(exc.value)


@pytest.mark.parametrize("termo,origem", [
    ("psicólogo alicante", "url"), ("psicologo alicante", "caixa_de_busca"), (None, "ausente"),
])
def test_sidecar_v2_com_termo_coerente_passa(tmp_path, termo, origem):
    csv_path = _escrever_csv(tmp_path, HEADER_COMPLETO, [_uma_linha()],
                             sidecar={"schema_version": 2, "termo_busca": termo, "termo_busca_origem": origem})
    sc, avisos = csv_contrato.validar_sidecar(str(csv_path))
    assert sc["termo_busca"] == termo and avisos == []


@pytest.mark.parametrize("extra,trecho", [
    ({}, "faltam"),
    ({"termo_busca": "psicólogo alicante"}, "faltam"),
    ({"termo_busca": "x", "termo_busca_origem": "teclado"}, "fora de"),
    ({"termo_busca": "   ", "termo_busca_origem": "url"}, "texto não vazio"),
    ({"termo_busca": 7, "termo_busca_origem": "url"}, "texto não vazio"),
    ({"termo_busca": None, "termo_busca_origem": "url"}, "incoerente"),
    ({"termo_busca": "psicólogo alicante", "termo_busca_origem": "ausente"}, "incoerente"),
])
def test_sidecar_v2_sem_termo_valido_levanta(tmp_path, extra, trecho):
    csv_path = _escrever_csv(tmp_path, HEADER_COMPLETO, [_uma_linha()],
                             sidecar={"schema_version": 2, **extra})
    with pytest.raises(csv_contrato.ContratoCsvInvalido) as exc:
        csv_contrato.validar_sidecar(str(csv_path))
    assert trecho in str(exc.value)


def test_sidecar_v1_nao_exige_termo(tmp_path):
    """Controle: os campos do termo são exigência só do v2."""
    csv_path = _escrever_csv(tmp_path, HEADER_COMPLETO, [_uma_linha()], sidecar={"schema_version": 1})
    sc, _ = csv_contrato.validar_sidecar(str(csv_path))
    assert "termo_busca" not in sc


def test_sidecar_schema_version_1_passa(tmp_path):
    csv_path = _escrever_csv(tmp_path, HEADER_COMPLETO, [_uma_linha()],
                             sidecar={"schema_version": 1, "linhas_totais": 1})
    sc, avisos = csv_contrato.validar_sidecar(str(csv_path))
    assert sc["schema_version"] == 1 and avisos == []


# --- integração: coletar_leads_de_csv / importar_csv -----------------------------------

def test_coletar_falha_e_nao_importa_com_header_incompleto(tmp_path, monkeypatch):
    colunas = [c for c in HEADER_COMPLETO if c != "Featured Image"]
    linhas = [[v for c, v in zip(HEADER_COMPLETO, _uma_linha()) if c != "Featured Image"]]
    csv_path = _escrever_csv(tmp_path, colunas, linhas, sidecar={"schema_version": 1})

    monkeypatch.setattr(main_mod, "PATH_COLETADOS", str(tmp_path / "col.json"))
    monkeypatch.setattr(main_mod, "PATH_COM_SITE", str(tmp_path / "site.json"))
    monkeypatch.setattr(main_mod, "PATH_REPROVADOS", str(tmp_path / "rep.json"))
    monkeypatch.setattr(main_mod, "PATH_QUALIFICADOS", str(tmp_path / "qual.json"))

    with pytest.raises(csv_contrato.ContratoCsvInvalido):
        main_mod.importar_csv(str(csv_path))

    assert not (tmp_path / "col.json").exists()
    assert not (tmp_path / "site.json").exists()
    assert not (tmp_path / "rep.json").exists()


def test_coletar_passa_com_header_completo_e_sidecar_v1(tmp_path):
    csv_path = _escrever_csv(
        tmp_path, HEADER_COMPLETO,
        [_uma_linha(Name="A", **{"Place Id": "p1"}),
         _uma_linha(Name="B", **{"Place Id": "p2"}, Website="https://b-site.es")],
        sidecar={"schema_version": 1, "linhas_totais": 2},
    )
    wave1, reprovados, wave2, custo, recon = AgentColetor().coletar_leads_de_csv(str(csv_path))
    assert recon["linhas_csv"] == 2
    assert len(wave1) == 1 and len(wave2) == 1 and reprovados == []


def test_linkedin_do_csv_chega_ao_lead_montado():
    linha = {c: "" for c in HEADER_COMPLETO}
    linha.update({"Name": "Fisio Ficticia", "Categories": "Fisioterapeuta", "Place Id": "p1",
                  "LinkedIn": "http://www.linkedin.com/in/profesional-ficticia"})
    lead = AgentColetor._montar_lead(linha)
    assert lead["linkedin"] == "http://www.linkedin.com/in/profesional-ficticia"
    # sem a coluna preenchida -> None
    linha["LinkedIn"] = ""
    assert AgentColetor._montar_lead(linha)["linkedin"] is None


def test_reconciliacao_fecha_a_conta(tmp_path, monkeypatch, capsys):
    # 5 linhas: 1 sem Name, 2 iguais (dedup interno), 2 leads distintos
    linhas = [
        _uma_linha(Name="", **{"Place Id": ""}),                       # sem Name
        _uma_linha(Name="Dup", **{"Place Id": "dup"}),                 # fica
        _uma_linha(Name="Dup 2", **{"Place Id": "dup"}),               # dedup interno (mesmo place_id)
        _uma_linha(Name="Unica A", **{"Place Id": "a"}),               # fica
        _uma_linha(Name="Unica B", **{"Place Id": "b"}, Website="https://b.es"),  # fica (Onda 2)
    ]
    csv_path = _escrever_csv(tmp_path, HEADER_COMPLETO, linhas, sidecar={"schema_version": 1})

    for nome, arq in [("PATH_COLETADOS", "col.json"), ("PATH_COM_SITE", "site.json"),
                      ("PATH_REPROVADOS", "rep.json"), ("PATH_QUALIFICADOS", "qual.json"),
                      ("PATH_IMPORT_META", "_m.json")]:
        monkeypatch.setattr(main_mod, nome, str(tmp_path / arq))
    monkeypatch.setattr(main_mod, "DATA_DIR", str(tmp_path))

    main_mod.importar_csv(str(csv_path))
    out = capsys.readouterr().out
    assert "RECONCILIAÇÃO DO IMPORT" in out
    assert "Linhas no CSV:                              5" in out
    assert "descartadas sem 'Name':                   1" in out
    assert "dedup interno (repetidas no mesmo CSV):   1" in out
    assert "OK" in out.split("Confere")[1].splitlines()[0]
