"""Campanha e cidade escolhidas pelo termo da busca (Tarefa 3, multicidade, diretor 06/10/2026):
`campanha.escolher_campanha` e o import (`main.importar_csv`) lendo `termo_busca` do sidecar.

Campanhas de teste em tmp_path (uma por nicho, com `cidade_padrao`), nunca o EQC real. A
cidade é conferida na lista OFICIAL do INE versionada em `config/municipios_ine.json` -- os
termos pedidos pelo diretor usam municípios reais. Dados de lead fictícios."""
import json
import os

import pytest

import campanha
import csv_contrato
import main as main_mod
import municipios

HEADER = list(csv_contrato.COLUNAS_OBRIGATORIAS_V1)

PSI = {"id": "psi-t", "nicho": "Psicólogos", "cidade_padrao": "Alicante",
       "categorias_aceitas": ["psicolog"], "categorias_excluidas": [], "termos_de_busca": ["psicolog"]}
ABO = {"id": "abo-t", "nicho": "Abogados", "cidade_padrao": "Alicante",
       "categorias_aceitas": ["abogad"], "categorias_excluidas": [], "termos_de_busca": ["abogad"]}
ARQ = {"id": "arq-t", "nicho": "Arquitectos", "cidade_padrao": "Alicante",
       "categorias_aceitas": ["arquitect"], "categorias_excluidas": [], "termos_de_busca": ["arquitect"]}


@pytest.fixture
def campanhas(tmp_path, monkeypatch):
    """Pasta com as três campanhas de teste; a ativa do menu é PSI (trocável por `ativar`)."""
    pasta = tmp_path / "campanhas"
    pasta.mkdir()
    for c in (PSI, ABO, ARQ):
        (pasta / f"{c['id']}.json").write_text(json.dumps(c), encoding="utf-8")
    monkeypatch.setenv(campanha.ENV_DIR_CAMPANHAS, str(pasta))
    monkeypatch.delenv(municipios.ENV_CAMINHO, raising=False)  # lista oficial versionada

    def ativar(c):
        ativa = tmp_path / "campanha_ativa.json"
        ativa.write_text(json.dumps(c), encoding="utf-8")
        monkeypatch.setenv(campanha.ENV_CAMINHO, str(ativa))
        return ativa

    ativar(PSI)
    return {"pasta": pasta, "ativar": ativar}


# --- termos pedidos pelo diretor -------------------------------------------------------

@pytest.mark.parametrize("termo,id_esperado,cidade_esperada,codigo_ine", [
    ("psicólogo murcia", "psi-t", "Murcia", "30030"),
    ("abogado alicante", "abo-t", "Alicante", "03014"),
    ("arquitecto elche", "arq-t", "Elche", "03065"),
    ("abogado alacant", "abo-t", "Alacant", "03014"),           # forma valenciana, grafia da forma digitada
    ("psicólogo san vicente del raspeig", "psi-t", "San Vicente del Raspeig", "03122"),
    ("PSICOLOGOS  MURCIA", "psi-t", "Murcia", "30030"),          # sem acento, maiúscula, espaço duplo
    ("psicólogo valencia", "psi-t", "València", "46250"),        # grafia oficial com acento
    ("murcia psicóloga", "psi-t", "Murcia", "30030"),            # nicho depois da cidade
])
def test_termo_escolhe_campanha_e_cidade_oficial(campanhas, termo, id_esperado, cidade_esperada, codigo_ine):
    r = campanha.escolher_campanha(termo)
    assert (r["campanha"]["id"], r["cidade"], r["codigo_ine"], r["origem"]) == (
        id_esperado, cidade_esperada, codigo_ine, campanha.ORIGEM_TERMO)


@pytest.mark.parametrize("termo,trecho", [
    ("psicólogo murcai", "'murcai' não é um município"),
    ("psicólogo", "o termo não traz cidade"),
    ("psicólogo infantil murcia", "'infantil murcia' não é um município"),
])
def test_cidade_nao_reconhecida_para(campanhas, termo, trecho):
    with pytest.raises(campanha.CampanhaPorTermoError) as exc:
        campanha.escolher_campanha(termo)
    assert exc.value.motivo == "cidade" and trecho in str(exc.value) and "cidade não reconhecida" in str(exc.value)
    assert exc.value.termo == termo


def test_cidade_com_mais_de_um_municipio_para(campanhas):
    """'Torrent' é município em Girona (17197) e em Valencia (46244): nunca adivinhar."""
    with pytest.raises(campanha.CampanhaPorTermoError) as exc:
        campanha.escolher_campanha("psicólogo torrent")
    assert exc.value.motivo == "cidade"
    assert sorted(m["codigo_ine"] for m in exc.value.candidatos) == ["17197", "46244"]


def test_termo_sem_nicho_para(campanhas):
    with pytest.raises(campanha.CampanhaPorTermoError) as exc:
        campanha.escolher_campanha("dentista murcia")
    assert exc.value.motivo == "nenhuma" and "nenhuma campanha" in str(exc.value)


def test_termo_com_dois_nichos_para(campanhas):
    with pytest.raises(campanha.CampanhaPorTermoError) as exc:
        campanha.escolher_campanha("psicólogo abogado murcia")
    assert exc.value.motivo == "mais_de_uma"
    assert {c["id"] for c in exc.value.envolvidas} == {"psi-t", "abo-t"}


# --- "en" solto no início da sobra (decisão do diretor, 06/10/2026) --------------------

def test_en_solto_e_ignorado(campanhas):
    assert campanha.escolher_campanha("psicólogo en murcia")["cidade"] == "Murcia"


@pytest.mark.parametrize("termo", ["psicólogo de murcia", "psicólogo en", "psicólogo en en murcia"])
def test_so_um_en_solto_no_inicio_e_tirado(campanhas, termo):
    """Controle negativo da regra do 'en': outra palavra, 'en' sozinho ou dois 'en' continuam parando."""
    with pytest.raises(campanha.CampanhaPorTermoError) as exc:
        campanha.escolher_campanha(termo)
    assert exc.value.motivo == "cidade"


def test_sobra_do_termo_tira_so_as_palavras_do_nicho():
    assert campanha.sobra_do_termo("Psicólogos infantiles Murcia", PSI) == "infantiles murcia"
    assert campanha.sobra_do_termo("psicólogo en san vicente del raspeig", PSI) == "san vicente del raspeig"


# --- termo ausente e divergência com o menu -------------------------------------------

@pytest.mark.parametrize("termo", [None, "", "   "])
def test_termo_ausente_usa_o_menu_e_a_cidade_padrao(campanhas, termo):
    campanhas["ativar"]({**ARQ, "cidade_padrao": "Elche"})
    r = campanha.escolher_campanha(termo)
    assert (r["campanha"]["id"], r["cidade"], r["origem"]) == ("arq-t", "Elche", campanha.ORIGEM_MENU)
    assert "MENU" in r["avisos"][0] and "cidade Elche" in r["avisos"][1]


def test_termo_e_menu_divergentes_vale_o_termo_com_aviso(campanhas):
    ativa = campanhas["ativar"](ABO)
    antes = ativa.read_bytes()
    r = campanha.escolher_campanha("psicólogo murcia")
    assert r["campanha"]["id"] == "psi-t" and r["origem"] == campanha.ORIGEM_TERMO
    assert any("ATENÇÃO" in a and "abo-t" in a for a in r["avisos"])
    assert ativa.read_bytes() == antes  # o menu não é alterado


def test_termo_e_menu_iguais_sem_aviso_de_divergencia(campanhas):
    """Controle negativo do caso acima."""
    r = campanha.escolher_campanha("psicólogo murcia")
    assert not any("ATENÇÃO" in a for a in r["avisos"])


# --- campanhas e lista do INE com problema ---------------------------------------------

def test_campanha_sem_termos_de_busca_nunca_casa_pelo_termo(campanhas):
    sem = {k: v for k, v in PSI.items() if k != "termos_de_busca"}
    (campanhas["pasta"] / "psi-t.json").write_text(json.dumps(sem), encoding="utf-8")
    with pytest.raises(campanha.CampanhaPorTermoError) as exc:
        campanha.escolher_campanha("psicólogo murcia")
    assert exc.value.motivo == "nenhuma" and "só pelo menu" in str(exc.value)


def test_campanha_invalida_na_pasta_para(campanhas):
    (campanhas["pasta"] / "zz.json").write_text("{ quebrado", encoding="utf-8")
    with pytest.raises(campanha.CampanhaPorTermoError):
        campanha.escolher_campanha("psicólogo murcia")


def test_id_repetido_na_pasta_para(campanhas):
    (campanhas["pasta"] / "copia.json").write_text(json.dumps(PSI), encoding="utf-8")
    with pytest.raises(campanha.CampanhaPorTermoError) as exc:
        campanha.escolher_campanha("psicólogo murcia")
    assert "repetido" in str(exc.value)


def test_lista_do_ine_ausente_para(campanhas, tmp_path, monkeypatch):
    monkeypatch.setenv(municipios.ENV_CAMINHO, str(tmp_path / "nao_existe.json"))
    with pytest.raises(campanha.CampanhaPorTermoError) as exc:
        campanha.escolher_campanha("psicólogo murcia")
    assert exc.value.motivo == "municipios"


@pytest.mark.parametrize("termos", [[], [""], "psicolog", [3]])
def test_termos_de_busca_presente_e_invalido_recusa(termos):
    with pytest.raises(campanha.CampanhaInvalidaError):
        campanha.validar_campanha({**PSI, "termos_de_busca": termos})


def test_termos_de_busca_e_opcional():
    """Controle: campanha sem o campo continua válida (só não é escolhida pelo termo)."""
    sem = {k: v for k, v in PSI.items() if k != "termos_de_busca"}
    assert campanha.validar_campanha(sem) is sem


def test_formato_antigo_com_cidade_e_sem_cidade_padrao_e_recusado():
    antigo = {k: v for k, v in PSI.items() if k != "cidade_padrao"}
    with pytest.raises(campanha.CampanhaInvalidaError) as exc:
        campanha.validar_campanha({**antigo, "cidade": "Alicante"})
    assert "'cidade_padrao'" in str(exc.value)


# --- import de ponta a ponta -------------------------------------------------------------

def _linha(**over):
    d = {c: "" for c in HEADER}
    d.update({"Name": "Consulta Ficticia", "Categories": "Psicólogo", "Place Id": "pid-x",
              "Email": "contacto@ficticio.es", "Fulladdress": "Calle Ficticia 1, 30001 Murcia"})
    d.update(over)
    return [d[c] for c in HEADER]


def _csv(tmp_path, linhas, meta, nome="extrator_teste_v1.csv"):
    def fmt(vals):
        return ",".join('"' + v.replace('"', '""') + '"' for v in vals)
    caminho = tmp_path / nome
    caminho.write_text("\n".join([fmt(HEADER)] + [fmt(l) for l in linhas]) + "\n", encoding="utf-8-sig")
    if meta is not None:
        (tmp_path / (nome[:-4] + ".meta.json")).write_text(json.dumps(meta), encoding="utf-8")
    return caminho


def _meta_v2(termo):
    return {"schema_version": 2, "termo_busca": termo, "termo_busca_origem": "url" if termo else "ausente"}


def _arquivos_de_dados():
    return [main_mod.PATH_COLETADOS, main_mod.PATH_COM_SITE, main_mod.PATH_REPROVADOS,
            main_mod.PATH_QUALIFICADOS, main_mod.PATH_IMPORT_META]


def test_import_com_termo_carimba_campanha_e_cidade_e_registra_origem(tmp_path, campanhas, capsys):
    campanhas["ativar"](ABO)  # menu diverge do termo
    main_mod.importar_csv(str(_csv(tmp_path, [_linha()], _meta_v2("psicólogo murcia"))))
    meta = main_mod.carregar_json(main_mod.PATH_IMPORT_META)
    assert (meta["campanha_id"], meta["campanha_cidade"], meta["origem_campanha"]) == ("psi-t", "Murcia", "termo_busca")
    [lead] = main_mod.carregar_json(main_mod.PATH_COLETADOS)
    emp = lead["dados_empresa"]
    assert (emp["campanha_id"], emp["campanha_nicho"], emp["campanha_cidade"]) == ("psi-t", "Psicólogos", "Murcia")
    out = capsys.readouterr().out
    assert "ATENÇÃO" in out and "origem: termo_busca" in out and "cidade: Murcia" in out


@pytest.mark.parametrize("meta", [None, {"schema_version": 1}, _meta_v2(None)],
                         ids=["sem_meta", "meta_v1", "meta_v2_sem_termo"])
def test_import_sem_termo_usa_o_menu_e_a_cidade_padrao(tmp_path, campanhas, capsys, meta):
    main_mod.importar_csv(str(_csv(tmp_path, [_linha()], meta)))
    m = main_mod.carregar_json(main_mod.PATH_IMPORT_META)
    assert (m["campanha_id"], m["campanha_cidade"], m["origem_campanha"]) == ("psi-t", "Alicante", "menu")
    [lead] = main_mod.carregar_json(main_mod.PATH_COLETADOS)
    assert lead["dados_empresa"]["campanha_cidade"] == "Alicante"
    assert "LISTA SEM TERMO DE BUSCA" in capsys.readouterr().out


@pytest.mark.parametrize("termo", ["dentista murcia", "psicólogo abogado murcia", "psicólogo murcai",
                                   "psicólogo", "psicólogo torrent"])
def test_import_com_termo_que_nao_fecha_para_sem_gravar_nada(tmp_path, campanhas, termo):
    with pytest.raises(campanha.CampanhaPorTermoError):
        main_mod.importar_csv(str(_csv(tmp_path, [_linha()], _meta_v2(termo))))
    for caminho in _arquivos_de_dados():
        assert not os.path.exists(caminho), caminho


def test_import_meta_v2_invalido_para_sem_gravar_nada(tmp_path, campanhas):
    with pytest.raises(csv_contrato.ContratoCsvInvalido):
        main_mod.importar_csv(str(_csv(tmp_path, [_linha()], {"schema_version": 2})))
    for caminho in _arquivos_de_dados():
        assert not os.path.exists(caminho), caminho
