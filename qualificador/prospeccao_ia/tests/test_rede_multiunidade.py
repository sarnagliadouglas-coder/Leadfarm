"""Filtro de redes / multiunidade (rede_multiunidade.py + main.importar_csv): marca no nome,
grupos por telefone normalizado e por domínio do site próprio sobre o POOL inteiro.
Dados fictícios. A campanha de teste do conftest aceita "Fisioterapeuta"."""
import json
import os

import pytest

import csv_contrato
import main as main_mod
import rede_multiunidade as rm

HEADER = list(csv_contrato.COLUNAS_OBRIGATORIAS_V1)
CONFIG = {"limiar_rede": 3, "marcas": ["vitaldent", "asisa"]}


def _linha(nome, pid, **over):
    d = {c: "" for c in HEADER}
    d.update({"Name": nome, "Categories": "Fisioterapeuta", "Place Id": pid,
              "Email": f"{pid}@ficticio.es", "Fulladdress": "Calle Ficticia 1, 03001 Alicante"})
    d.update(over)
    return [d[c] for c in HEADER]


def _csv(tmp_path, linhas, nome="extrator_rede_v1.csv"):
    def fmt(vals):
        return ",".join('"' + v.replace('"', '""') + '"' for v in vals)
    caminho = tmp_path / nome
    caminho.write_text("\n".join([fmt(HEADER)] + [fmt(l) for l in linhas]) + "\n", encoding="utf-8-sig")
    (tmp_path / (nome[:-4] + ".meta.json")).write_text(json.dumps({"schema_version": 1}), encoding="utf-8")
    return caminho


def _por_pid(caminho):
    return {r["dados_empresa"]["place_id"]: r for r in main_mod.carregar_json(caminho)}


def _ativos():
    return {**_por_pid(main_mod.PATH_COLETADOS), **_por_pid(main_mod.PATH_COM_SITE)}


# --- config --------------------------------------------------------------------------------

def test_config_do_repo_carrega_com_a_lista_inicial():
    config = rm.carregar_config()
    assert config["limiar_rede"] == 3
    assert {"vitaldent", "vithas", "asisa", "sanitas", "adeslas", "dentix", "vivanta", "dentalios"} <= set(config["marcas"])


def test_config_ausente_ou_invalida_levanta(tmp_path):
    with pytest.raises(rm.ConfigRedeInvalidaError):
        rm.carregar_config(str(tmp_path / "nao_existe.json"))
    ruim = tmp_path / "ruim.json"
    ruim.write_text(json.dumps({"limiar_rede": 1, "marcas": ["x"]}), encoding="utf-8")
    with pytest.raises(rm.ConfigRedeInvalidaError):
        rm.carregar_config(str(ruim))


def test_import_sem_config_de_rede_falha_e_nao_grava_nada(tmp_path, monkeypatch):
    monkeypatch.setattr(rm, "CAMINHO_CONFIG", str(tmp_path / "nao_existe.json"))
    with pytest.raises(rm.ConfigRedeInvalidaError):
        main_mod.importar_csv(str(_csv(tmp_path, [_linha("A", "pa")])))
    for caminho in (main_mod.PATH_COLETADOS, main_mod.PATH_COM_SITE, main_mod.PATH_REPROVADOS, main_mod.PATH_IMPORT_META):
        assert not os.path.exists(caminho)


# --- regras puras --------------------------------------------------------------------------

@pytest.mark.parametrize("nome,esperado", [
    ("Clínica Vitaldent Alicante", "vitaldent"),
    ("ASISA Fisioterapia", "asisa"),
    ("Kasisa Fisio", None),              # palavra inteira: "asisa" dentro de outra palavra não conta
    ("Fisio Ficticia", None),
])
def test_marca_no_nome_por_palavra_inteira_sem_acento_e_maiuscula(nome, esperado):
    assert rm.marca_no_nome({"nome": nome}, CONFIG["marcas"]) == esperado


def test_dominio_de_plataforma_nao_forma_grupo_e_proprio_forma():
    assert rm.chave_dominio({"website": "https://www.doctoralia.es/x"}) is None
    assert rm.chave_dominio({"website": "https://fisio.wixsite.com/x"}) is None
    assert rm.chave_dominio({"website": "https://www.fisio-ficticia.es/contacto"}) == "fisio-ficticia.es"


def test_grupo_de_3_por_telefone_normalizado_descarta_todos():
    fichas = [{"place_id": "a", "telefone": "+34 612 34 56 78"},
              {"place_id": "b", "telefone": "612345678"},
              {"place_id": "c", "telefone": "0034612345678"},
              {"place_id": "d", "telefone": "699000000"}]
    descartes, avisos = rm.agrupar(fichas, 3)
    assert set(descartes) == {0, 1, 2}
    assert descartes[0] == {"por": "telefone", "chave": "612345678", "tamanho_grupo": 3}
    assert avisos == {}


def test_grupo_de_2_avisa_as_duas_com_o_place_id_da_outra():
    fichas = [{"place_id": "a", "telefone": "612345678"}, {"place_id": "b", "telefone": "612 345 678"}]
    descartes, avisos = rm.agrupar(fichas, 3)
    assert descartes == {}
    assert avisos[0] == [{"place_id": "b", "por": "telefone", "chave": "612345678"}]
    assert avisos[1] == [{"place_id": "a", "por": "telefone", "chave": "612345678"}]


def test_dominio_de_plataforma_repetido_nao_agrupa():
    fichas = [{"place_id": p, "website": f"https://www.doctoralia.es/{p}"} for p in "abc"]
    assert rm.agrupar(fichas, 3) == ({}, {})


def test_dominio_proprio_repetido_agrupa():
    fichas = [{"place_id": p, "website": f"https://www.rede-ficticia.es/{p}"} for p in "abc"]
    descartes, _ = rm.agrupar(fichas, 3)
    assert set(descartes) == {0, 1, 2} and descartes[0]["por"] == "dominio"


# --- integração com o import -----------------------------------------------------------------

def test_import_grupo_de_3_sai_inteiro_como_rede(tmp_path, capsys):
    linhas = [_linha(f"Fisio {p}", p, Phone="612345678") for p in ("r1", "r2", "r3")]
    linhas.append(_linha("Fisio Sozinha", "s1", Phone="699111222"))
    main_mod.importar_csv(str(_csv(tmp_path, linhas)))

    reprovados = _por_pid(main_mod.PATH_REPROVADOS)
    assert set(reprovados) == {"r1", "r2", "r3"}
    for r in reprovados.values():
        assert r["rejection_reason"] == "rede_ou_multiunidade"
        assert r["rejection_detail"] == {"por": "telefone", "chave": "612345678", "tamanho_grupo": 3}
    assert set(_ativos()) == {"s1"}
    out = capsys.readouterr().out
    assert "reprovados por rede_ou_multiunidade: 3" in out
    assert "OK" in out.split("Confere")[1].splitlines()[0]


def test_import_grupo_de_2_chega_as_ondas_com_aviso_nas_duas(tmp_path):
    linhas = [_linha("Fisio Um", "q1", Phone="612000001"),
              _linha("Fisio Dois", "q2", Phone="612000001", Website="https://fisio-dois.es"),
              _linha("Fisio Tres", "q3", Phone="612000003")]
    main_mod.importar_csv(str(_csv(tmp_path, linhas)))

    ativos = _ativos()
    assert set(ativos) == {"q1", "q2", "q3"}
    assert [a["place_id"] for a in ativos["q1"]["dados_empresa"]["possivel_mesmo_negocio"]] == ["q2"]
    assert [a["place_id"] for a in ativos["q2"]["dados_empresa"]["possivel_mesmo_negocio"]] == ["q1"]
    assert ativos["q3"]["dados_empresa"]["possivel_mesmo_negocio"] == []
    assert not os.path.exists(main_mod.PATH_REPROVADOS) or _por_pid(main_mod.PATH_REPROVADOS) == {}


def test_import_dominio_de_plataforma_repetido_nao_descarta(tmp_path):
    linhas = [_linha(f"Fisio {p}", p, Phone=f"61200010{i}", Website=f"https://www.doctoralia.es/{p}")
              for i, p in enumerate(("x1", "x2", "x3"))]
    main_mod.importar_csv(str(_csv(tmp_path, linhas)))
    assert set(_ativos()) == {"x1", "x2", "x3"}


def test_import_marca_no_nome_descarta(tmp_path, monkeypatch):
    monkeypatch.setattr(rm, "CAMINHO_CONFIG", str(tmp_path / "rede.json"))
    (tmp_path / "rede.json").write_text(json.dumps(CONFIG), encoding="utf-8")
    main_mod.importar_csv(str(_csv(tmp_path, [_linha("Vitaldent Fisio Centro", "m1", Phone="612000009"),
                                              _linha("Fisio Independiente", "m2", Phone="612000010")])))
    reprovados = _por_pid(main_mod.PATH_REPROVADOS)
    assert set(reprovados) == {"m1"}
    assert reprovados["m1"]["rejection_detail"] == {"por": "marca", "chave": "vitaldent", "tamanho_grupo": None}
    assert set(_ativos()) == {"m2"}


def test_pool_terceira_ficha_em_outro_import_descarta_tambem_as_ja_gravadas(tmp_path, capsys):
    """Olha o POOL, não só o CSV: par no import 1 (aviso), 3ª ficha no import 2 -> as três
    viram rede, inclusive as duas que já estavam nas ondas (saem do arquivo delas)."""
    main_mod.importar_csv(str(_csv(tmp_path, [_linha("Fisio A", "pa", Phone="612777777"),
                                              _linha("Fisio B", "pb", Phone="612777777",
                                                     Website="https://fisio-b.es")],
                                   nome="extrator_1_v1.csv")))
    assert set(_ativos()) == {"pa", "pb"}
    capsys.readouterr()

    main_mod.importar_csv(str(_csv(tmp_path, [_linha("Fisio C", "pc", Phone="+34 612 77 77 77")],
                                   nome="extrator_2_v1.csv")))
    reprovados = _por_pid(main_mod.PATH_REPROVADOS)
    assert set(reprovados) == {"pa", "pb", "pc"}
    assert all(r["rejection_reason"] == "rede_ou_multiunidade" for r in reprovados.values())
    assert reprovados["pa"]["status_anterior"] == "eligible"
    assert reprovados["pb"]["status_anterior"] == "queued_future"
    assert reprovados["pc"]["rejection_detail"]["tamanho_grupo"] == 3
    assert _ativos() == {}
    out = capsys.readouterr().out
    assert "movidas para reprovados (rede_ou_multiunidade), fora da conta acima: 2" in out
    assert "OK" in out.split("Confere")[1].splitlines()[0]
