"""Campanha ativa (campanha.py): carga com falha alta, carimbo no import e corte de
categoria antes da separação em ondas (main.importar_csv / AgentColetor). Dados fictícios."""
import json
import os

import pytest

import campanha
import contrato
import csv_contrato
import main as main_mod

HEADER = list(csv_contrato.COLUNAS_OBRIGATORIAS_V1)

CAMPANHA_PSI = {
    "id": "psi-teste",
    "nicho": "Psicólogos",
    "cidade": "Cidade Ficticia",
    "categorias_aceitas": ["psicólogo", "psicología", "salud mental", "psicoterapeuta"],
    "categorias_excluidas": [],
}


def _gravar_campanha(tmp_path, monkeypatch, conteudo, nome="campanha.json"):
    caminho = tmp_path / nome
    caminho.write_text(conteudo if isinstance(conteudo, str) else json.dumps(conteudo), encoding="utf-8")
    monkeypatch.setenv(campanha.ENV_CAMINHO, str(caminho))
    return caminho


def _linha(**over):
    d = {c: "" for c in HEADER}
    d.update({"Name": "Consulta Ficticia", "Categories": "Psicólogo", "Place Id": "pid-x",
              "Email": "contacto@ficticio.es", "Fulladdress": "Calle Ficticia 1, 03001 Alicante"})
    d.update(over)
    return [d[c] for c in HEADER]


def _csv(tmp_path, linhas, nome="extrator_teste_v1.csv"):
    def fmt(vals):
        return ",".join('"' + v.replace('"', '""') + '"' for v in vals)
    caminho = tmp_path / nome
    caminho.write_text("\n".join([fmt(HEADER)] + [fmt(l) for l in linhas]) + "\n", encoding="utf-8-sig")
    (tmp_path / (nome[:-4] + ".meta.json")).write_text(json.dumps({"schema_version": 1}), encoding="utf-8")
    return caminho


def _arquivos_de_dados():
    return [main_mod.PATH_COLETADOS, main_mod.PATH_COM_SITE, main_mod.PATH_REPROVADOS,
            main_mod.PATH_QUALIFICADOS, main_mod.PATH_IMPORT_META]


# --- carga / validação ------------------------------------------------------------------

def test_campanha_valida_carrega_e_aceita_campos_extras(tmp_path, monkeypatch):
    _gravar_campanha(tmp_path, monkeypatch, {**CAMPANHA_PSI, "vocabulario_copy": {"cliente": "paciente"}})
    c = campanha.carregar_campanha()
    assert c["id"] == "psi-teste" and c["vocabulario_copy"] == {"cliente": "paciente"}


def test_categorias_excluidas_vazia_e_valida(tmp_path, monkeypatch):
    _gravar_campanha(tmp_path, monkeypatch, {**CAMPANHA_PSI, "categorias_excluidas": []})
    assert campanha.carregar_campanha()["categorias_excluidas"] == []


def test_campanha_ausente_levanta_com_mensagem_clara(tmp_path, monkeypatch):
    monkeypatch.setenv(campanha.ENV_CAMINHO, str(tmp_path / "nao_existe.json"))
    with pytest.raises(campanha.CampanhaInvalidaError) as exc:
        campanha.carregar_campanha()
    assert "não encontrada" in str(exc.value) and "nao_existe.json" in str(exc.value)


def test_campanha_json_invalido_levanta(tmp_path, monkeypatch):
    _gravar_campanha(tmp_path, monkeypatch, "{ isto não é json")
    with pytest.raises(campanha.CampanhaInvalidaError) as exc:
        campanha.carregar_campanha()
    assert "não é JSON válido" in str(exc.value)


@pytest.mark.parametrize("campo", ["id", "nicho", "cidade", "categorias_aceitas", "categorias_excluidas"])
def test_campo_minimo_faltando_levanta_nomeando_o_campo(tmp_path, monkeypatch, campo):
    dados = {k: v for k, v in CAMPANHA_PSI.items() if k != campo}
    _gravar_campanha(tmp_path, monkeypatch, dados)
    with pytest.raises(campanha.CampanhaInvalidaError) as exc:
        campanha.carregar_campanha()
    assert f"'{campo}'" in str(exc.value)


def test_categorias_aceitas_vazia_levanta(tmp_path, monkeypatch):
    _gravar_campanha(tmp_path, monkeypatch, {**CAMPANHA_PSI, "categorias_aceitas": []})
    with pytest.raises(campanha.CampanhaInvalidaError):
        campanha.carregar_campanha()


def test_caminho_padrao_vive_no_eqc_e_env_vence(tmp_path, monkeypatch):
    monkeypatch.delenv(campanha.ENV_CAMINHO, raising=False)
    assert campanha.caminho_campanha() == str(contrato.eqc_root() / "config" / "campanha_ativa.json")
    monkeypatch.setenv(campanha.ENV_CAMINHO, str(tmp_path / "x.json"))
    assert campanha.caminho_campanha() == str(tmp_path / "x.json")


def test_campanha_real_do_repo_e_valida():
    """O arquivo versionado em EQC/config/ tem de passar na mesma validação do import."""
    caminho = contrato.eqc_root() / "config" / "campanha_ativa.json"
    c = campanha.carregar_campanha(str(caminho))
    assert c["categorias_aceitas"]


# --- regra de categoria -----------------------------------------------------------------

@pytest.mark.parametrize("nicho", ["Psicólogo", "psicologo infantil", "PSICOLOGÍA CLÍNICA",
                                   "Servicio de salud mental", "Psicoterapeuta"])
def test_categoria_aceita_sem_acento_e_sem_maiuscula(nicho):
    assert campanha.motivo_categoria(nicho, CAMPANHA_PSI) is None


@pytest.mark.parametrize("nicho", ["Dentista", "Clínica de psicopedagogía", "categoría sin especificar", ""])
def test_categoria_fora_do_perfil_corta(nicho):
    assert campanha.motivo_categoria(nicho, CAMPANHA_PSI) == (campanha.MOTIVO_FORA_DO_PERFIL, None)


def test_categoria_excluida_vence_aceita():
    c = {**CAMPANHA_PSI, "categorias_excluidas": ["infantil"]}
    assert campanha.motivo_categoria("Psicólogo infantil", c) == (campanha.MOTIVO_EXCLUIDA, "infantil")
    assert campanha.motivo_categoria("Psicólogo", c) is None


# --- import: falha alta antes de gravar ---------------------------------------------------

@pytest.mark.parametrize("conteudo", [None, "{ quebrado", {k: v for k, v in CAMPANHA_PSI.items() if k != "id"}],
                         ids=["ausente", "json_invalido", "campo_minimo_faltando"])
def test_import_sem_campanha_valida_falha_e_nao_grava_nada(tmp_path, monkeypatch, conteudo):
    if conteudo is None:
        monkeypatch.setenv(campanha.ENV_CAMINHO, str(tmp_path / "nao_existe.json"))
    else:
        _gravar_campanha(tmp_path, monkeypatch, conteudo)
    csv_path = _csv(tmp_path, [_linha()])
    with pytest.raises(campanha.CampanhaInvalidaError):
        main_mod.importar_csv(str(csv_path))
    for caminho in _arquivos_de_dados():
        assert not os.path.exists(caminho), caminho


def test_import_com_campanha_valida_grava(tmp_path, monkeypatch):
    """Controle negativo do teste acima: mesmo CSV, campanha válida -> grava."""
    _gravar_campanha(tmp_path, monkeypatch, CAMPANHA_PSI)
    main_mod.importar_csv(str(_csv(tmp_path, [_linha()])))
    assert os.path.exists(main_mod.PATH_COLETADOS) and os.path.exists(main_mod.PATH_IMPORT_META)


# --- import: carimbo --------------------------------------------------------------------

def test_import_carimba_campanha_e_nunca_recarimba(tmp_path, monkeypatch):
    _gravar_campanha(tmp_path, monkeypatch, CAMPANHA_PSI)
    main_mod.importar_csv(str(_csv(tmp_path, [_linha(Name="A", **{"Place Id": "pa"})], nome="extrator_a_v1.csv")))

    _gravar_campanha(tmp_path, monkeypatch, {**CAMPANHA_PSI, "id": "outra", "nicho": "Outro"}, nome="c2.json")
    main_mod.importar_csv(str(_csv(tmp_path, [_linha(Name="A", **{"Place Id": "pa"}),
                                              _linha(Name="B", **{"Place Id": "pb"}, Email="b@ficticio.es")],
                                   nome="extrator_b_v1.csv")))

    coletados = {r["dados_empresa"]["place_id"]: r["dados_empresa"] for r in main_mod.carregar_json(main_mod.PATH_COLETADOS)}
    assert (coletados["pa"]["campanha_id"], coletados["pa"]["campanha_nicho"]) == ("psi-teste", "Psicólogos")
    assert (coletados["pb"]["campanha_id"], coletados["pb"]["campanha_nicho"]) == ("outra", "Outro")


# --- import: corte de categoria antes das ondas -----------------------------------------

def test_lead_fora_da_categoria_nao_chega_a_nenhuma_onda(tmp_path, monkeypatch, capsys):
    _gravar_campanha(tmp_path, monkeypatch, CAMPANHA_PSI)
    linhas = [
        _linha(Name="Psi Sem Site", **{"Place Id": "p1"}),
        _linha(Name="Psi Com Site", **{"Place Id": "p2"}, Website="https://psi-ficticio.es", Email="p2@f.es"),
        _linha(Name="Dentista Sem Site", Categories="Dentista", **{"Place Id": "d1"}, Email="d1@f.es"),
        _linha(Name="Dentista Com Site", Categories="Dentista", **{"Place Id": "d2"},
               Website="https://dentista-ficticio.es", Email="d2@f.es"),
    ]
    main_mod.importar_csv(str(_csv(tmp_path, linhas)))

    onda1 = {r["dados_empresa"]["place_id"] for r in main_mod.carregar_json(main_mod.PATH_COLETADOS)}
    onda2 = {r["dados_empresa"]["place_id"] for r in main_mod.carregar_json(main_mod.PATH_COM_SITE)}
    reprovados = {r["dados_empresa"]["place_id"]: r for r in main_mod.carregar_json(main_mod.PATH_REPROVADOS)}
    assert onda1 == {"p1"} and onda2 == {"p2"}
    assert set(reprovados) == {"d1", "d2"}
    for r in reprovados.values():
        assert r["rejection_reason"] == "icp_categoria_fora_do_perfil"
        assert r["rejection_detail"]["categoria"] == "Dentista"

    out = capsys.readouterr().out
    assert "reprovados por icp_categoria_fora_do_perfil: 2" in out
    assert "OK" in out.split("Confere")[1].splitlines()[0]


# --- termos por raiz (tarefa 1b, item C) ------------------------------------------------
# Raízes autorizadas pelo diretor (04/10/2026). Testadas com campanhas de teste: o arquivo
# real em EQC/config/ não foi alterado nesta rodada (edição negada pelo ambiente).
RAIZES = {
    "psicologos": ["psicólog", "psicoterapeut", "salud mental"],
    "abogados": ["abogad", "servicios legales", "bufete", "gestor"],
    "arquitectos": ["arquitect"],
}


def _camp(nicho):
    return {**CAMPANHA_PSI, "id": nicho, "categorias_aceitas": RAIZES[nicho]}


@pytest.mark.parametrize("nicho,categoria", [
    ("psicologos", "Psicóloga"), ("psicologos", "Psicólogo infantil"), ("psicologos", "Psicoterapeuta"),
    ("abogados", "Abogada"), ("abogados", "Abogado"), ("abogados", "Gestoría"),
    ("arquitectos", "Arquitecta"), ("arquitectos", "Arquitecto técnico"), ("arquitectos", "Estudio de arquitectura"),
])
def test_raiz_casa_feminino_e_variantes(nicho, categoria):
    assert campanha.motivo_categoria(categoria, _camp(nicho)) is None


@pytest.mark.parametrize("nicho,categoria", [
    ("psicologos", "Dentista"), ("psicologos", "Abogada"),
    ("abogados", "Arquitecta"), ("abogados", "Psicóloga"),
    ("arquitectos", "Abogado"), ("arquitectos", "Diseñador de interiores"),
])
def test_raiz_fora_da_campanha_continua_cortada(nicho, categoria):
    """Controle negativo: termo de outra campanha (ou fora de todas) continua cortado."""
    assert campanha.motivo_categoria(categoria, _camp(nicho)) == (campanha.MOTIVO_FORA_DO_PERFIL, None)


def test_termo_antigo_nao_casava_psicologa():
    """Evidência do motivo da troca: o termo inteiro "psicólogo" não casa com "Psicóloga"."""
    assert campanha.motivo_categoria("Psicóloga", CAMPANHA_PSI) == (campanha.MOTIVO_FORA_DO_PERFIL, None)
