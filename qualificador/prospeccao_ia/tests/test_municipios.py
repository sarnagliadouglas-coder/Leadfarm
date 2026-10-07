"""municipios.py: reconhecer a cidade do termo da busca na lista do INE (multicidade,
06/10/2026). Lista pequena fictícia em tmp_path; um teste confere a lista oficial versionada."""
import json

import pytest

import municipios


def _lista(tmp_path, municipios_, fonte=None):
    caminho = tmp_path / "municipios.json"
    caminho.write_text(json.dumps({"fonte": fonte if fonte is not None else {"orgao": "teste"},
                                   "total_municipios": len(municipios_), "municipios": municipios_},
                                  ensure_ascii=False), encoding="utf-8")
    return str(caminho)


FICTICIA = [
    {"codigo_ine": "90001", "cpro": "90", "cmun": "001", "nombre": "Villa Ficticia/Vila Fictícia",
     "formas": ["Villa Ficticia", "Vila Fictícia"]},
    {"codigo_ine": "90002", "cpro": "90", "cmun": "002", "nombre": "Rozas Ficticias, Las",
     "formas": ["Rozas Ficticias, Las", "Las Rozas Ficticias"]},
    {"codigo_ine": "91003", "cpro": "91", "cmun": "003", "nombre": "Repetida", "formas": ["Repetida"]},
    {"codigo_ine": "92004", "cpro": "92", "cmun": "004", "nombre": "Repetida", "formas": ["Repetida"]},
]


@pytest.mark.parametrize("texto,forma", [
    ("villa ficticia", "Villa Ficticia"), ("VILA FICTICIA", "Vila Fictícia"),
    ("  las   rozas  ficticias ", "Las Rozas Ficticias"), ("rozas ficticias, las", "Rozas Ficticias, Las"),
])
def test_forma_oficial_da_grafia_digitada(tmp_path, texto, forma):
    [m] = municipios.procurar(texto, _lista(tmp_path, FICTICIA))
    assert m["forma"] == forma and m["codigo_ine"] in ("90001", "90002")


@pytest.mark.parametrize("texto", ["villa", "ficticia", "villa ficticia centro", "", "   "])
def test_so_o_nome_inteiro_casa(tmp_path, texto):
    """Controle negativo: pedaço de nome, nome com palavra a mais ou vazio não casam."""
    assert municipios.procurar(texto, _lista(tmp_path, FICTICIA)) == []


def test_nome_em_mais_de_um_municipio_devolve_todos(tmp_path):
    achados = municipios.procurar("repetida", _lista(tmp_path, FICTICIA))
    assert sorted(m["codigo_ine"] for m in achados) == ["91003", "92004"]


@pytest.mark.parametrize("conteudo", [
    "{ quebrado", json.dumps({"municipios": []}), json.dumps({"fonte": {}, "municipios": []}),
    json.dumps({"fonte": {}, "municipios": [{"codigo_ine": "1", "nombre": "X", "formas": []}]}),
    json.dumps({"fonte": {}, "municipios": [{"codigo_ine": 1, "nombre": "X", "formas": ["X"]}]}),
])
def test_lista_invalida_levanta(tmp_path, conteudo):
    caminho = tmp_path / "ruim.json"
    caminho.write_text(conteudo, encoding="utf-8")
    with pytest.raises(municipios.ListaMunicipiosInvalidaError):
        municipios.procurar("x", str(caminho))


def test_lista_ausente_levanta(tmp_path):
    with pytest.raises(municipios.ListaMunicipiosInvalidaError):
        municipios.procurar("x", str(tmp_path / "nao_existe.json"))


def test_env_aponta_a_lista(tmp_path, monkeypatch):
    monkeypatch.setenv(municipios.ENV_CAMINHO, _lista(tmp_path, FICTICIA))
    assert municipios.procurar("villa ficticia")[0]["codigo_ine"] == "90001"


def test_lista_oficial_versionada_tem_fonte_e_os_municipios_da_operacao(monkeypatch):
    """A lista em config/ é a oficial do INE (fonte registrada) e reconhece os municípios
    usados nos testes de campo."""
    monkeypatch.delenv(municipios.ENV_CAMINHO, raising=False)
    dados = municipios.carregar()
    assert dados["fonte"]["orgao"].startswith("Instituto Nacional de Estadística")
    assert dados["fonte"]["url"].startswith("https://www.ine.es/")
    for texto, codigo in (("murcia", "30030"), ("alicante", "03014"), ("alacant", "03014"), ("elx", "03065")):
        assert [m["codigo_ine"] for m in municipios.procurar(texto)] == [codigo]
