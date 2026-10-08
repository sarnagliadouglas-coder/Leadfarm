"""Leads reprovados (diretor, 07/10/2026): carimbo de cada reprovação, histórico permanente
só de acréscimo, consulta só de leitura, reavaliação por categoria (prévia por padrão,
aplicação só com --confirmar), arquivar-pool com backup conferido e prova de que nada disso
atravessa para o COMERCIAL.

Dados fictícios. O conftest isola data/, o histórico e a pasta de backups num tmp_path."""
import hashlib
import json
import os
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

import campanha
import contrato
import csv_contrato
import lead_qualification
import main as main_mod
import municipios
import output_json as oj
import reprovados as rep
import saida_humana as sh
from test_contrato_2_2_0 import _nata
from test_output_json import _com_site, _emp, _qualificado

HEADER = list(csv_contrato.COLUNAS_OBRIGATORIAS_V1)

FIS = {"id": "fis-t", "nicho": "Fisioterapeutas (teste)", "cidade_padrao": "Alicante",
       "categorias_aceitas": ["fisioterap"], "categorias_excluidas": [], "termos_de_busca": ["fisioterap"]}


# --- ajudantes ---------------------------------------------------------------------------

@pytest.fixture
def campanhas(tmp_path, monkeypatch):
    """Pasta de campanhas de teste com FIS, que também é a ativa do menu."""
    pasta = tmp_path / "campanhas"
    pasta.mkdir()
    arquivo = pasta / "fis-t.json"
    arquivo.write_text(json.dumps(FIS), encoding="utf-8")
    monkeypatch.setenv(campanha.ENV_DIR_CAMPANHAS, str(pasta))
    monkeypatch.setenv(campanha.ENV_CAMINHO, str(arquivo))
    monkeypatch.delenv(municipios.ENV_CAMINHO, raising=False)

    def trocar(**over):
        arquivo.write_text(json.dumps({**FIS, **over}), encoding="utf-8")
    return {"pasta": pasta, "arquivo": arquivo, "trocar": trocar}


def _linha(nome, pid, **over):
    d = {c: "" for c in HEADER}
    # telefone celular fictício diferente por place_id (telefone igual formaria grupo de rede)
    telefone = "+34 6" + str(sum(ord(c) * 31 ** i for i, c in enumerate(pid)) % 10 ** 8).zfill(8)
    d.update({"Name": nome, "Categories": "Fisioterapeuta", "Place Id": pid, "Phone": telefone,
              "Email": f"{pid}@ficticio.es", "Fulladdress": "Calle Ficticia 1, 03001 Alicante",
              "Average Rating": "4.5", "Review Count": "20"})
    d.update(over)
    return [d[c] for c in HEADER]


def _csv(tmp_path, linhas, nome="extrator_ficticio_v1.csv", termo=None):
    def fmt(vals):
        return ",".join('"' + v.replace('"', '""') + '"' for v in vals)
    caminho = tmp_path / nome
    caminho.write_text("\n".join([fmt(HEADER)] + [fmt(l) for l in linhas]) + "\n", encoding="utf-8-sig")
    meta = ({"schema_version": 2, "termo_busca": termo, "termo_busca_origem": "url"} if termo
            else {"schema_version": 1})
    (tmp_path / (nome[:-4] + ".meta.json")).write_text(json.dumps(meta), encoding="utf-8")
    return str(caminho)


def _por_pid(caminho):
    return {r["dados_empresa"]["place_id"]: r for r in main_mod.carregar_json(caminho)}


def _historico():
    return rep.ler_historico(main_mod.PATH_HISTORICO_REPROVADOS)[0]


def _hash(caminho):
    if not os.path.exists(caminho):
        return None
    return hashlib.sha256(Path(caminho).read_bytes()).hexdigest()


def _hashes_do_pool():
    return {os.path.basename(p): _hash(p)
            for p in main_mod._arquivos_do_pool() + [main_mod.PATH_HISTORICO_REPROVADOS]}


def _iso_valido(texto):
    return datetime.fromisoformat(texto).tzinfo is not None


# --- 1. carimbo ----------------------------------------------------------------------------

def test_import_carimba_reprovacao_com_data_origem_termo_e_etapa(tmp_path, campanhas):
    csv_path = _csv(tmp_path, [_linha("Fisio Uno", "f1"), _linha("Osteo Uno", "o1", Categories="Osteópata")],
                    nome="lista_carimbo_v1.csv", termo="fisioterapeuta murcia")
    main_mod.importar_csv(csv_path)

    r = _por_pid(main_mod.PATH_REPROVADOS)["o1"]
    assert r["rejection_reason"] == campanha.MOTIVO_FORA_DO_PERFIL
    assert _iso_valido(r["reprovado_em"])
    assert (r["origem_csv"], r["termo_busca"], r["etapa"]) == ("lista_carimbo_v1.csv", "fisioterapeuta murcia", "import")
    assert r["rejection_detail"]["categoria"] == "Osteópata"  # o detalhe do import continua igual
    assert "detalhe_interno" not in r
    # o lead aprovado leva a origem em dados_empresa, para a Onda 1 achar depois
    ativo = _por_pid(main_mod.PATH_COLETADOS)["f1"]["dados_empresa"]
    assert (ativo["origem_csv"], ativo["termo_busca"]) == ("lista_carimbo_v1.csv", "fisioterapeuta murcia")


def test_import_de_lista_sem_termo_grava_termo_vazio(tmp_path, campanhas):
    main_mod.importar_csv(_csv(tmp_path, [_linha("Osteo Dos", "o2", Categories="Osteópata")]))
    r = _por_pid(main_mod.PATH_REPROVADOS)["o2"]
    assert r["termo_busca"] is None and r["origem_csv"] == "extrator_ficticio_v1.csv"


def test_onda1_carimba_e_grava_detalhe_interno_nunca_rejection_detail(tmp_path, campanhas, monkeypatch):
    linhas = [
        _linha("Sem Canal", "c1", Email="", Phone="+34 912 000 001"),                       # fixo, sem e-mail/rede
        _linha("Sem Sinal", "d1", **{"Average Rating": "", "Review Count": ""}),           # tem e-mail, sem sinal
        _linha("Nota Baixa", "n1", **{"Average Rating": "3.0"}),
        _linha("Poucas", "p1", **{"Review Count": "2"}, Instagram="@poucas"),
    ]
    main_mod.importar_csv(_csv(tmp_path, linhas, nome="lista_onda1_v1.csv", termo="fisioterapeuta murcia"))
    icp = {**lead_qualification.carregar_icp(), "rating_minimo": 4.0, "reviews_minimo": 0}
    monkeypatch.setattr(lead_qualification, "carregar_icp", lambda *a, **k: icp)
    main_mod.fase_qualify()

    rep_ = _por_pid(main_mod.PATH_REPROVADOS)
    assert rep_["c1"]["rejection_reason"] == "sem_canal_de_contato"
    assert rep_["c1"]["detalhe_interno"] == {"tem_email": False, "tem_instagram": False, "tem_facebook": False,
                                             "telefone_celular_espanhol": False}
    assert rep_["n1"]["rejection_reason"] == "icp_rating_abaixo_minimo"
    assert rep_["n1"]["detalhe_interno"] == {"nota_google": 3.0, "minimo": 4.0}
    assert rep_["d1"]["rejection_reason"] == "qualification_declined"
    assert set(rep_["d1"]["detalhe_interno"]) == {"score", "reasons"}
    for pid in ("c1", "n1", "d1"):
        r = rep_[pid]
        assert "rejection_detail" not in r and "detalhe_interno" not in r["dados_empresa"]
        assert (r["etapa"], r["origem_csv"], r["termo_busca"]) == ("onda1", "lista_onda1_v1.csv", "fisioterapeuta murcia")
        assert _iso_valido(r["reprovado_em"])
    assert "p1" not in rep_  # controle negativo: lead com sinal e canal passa


def test_onda1_anota_cada_reprovacao_no_historico(tmp_path, campanhas, monkeypatch):
    """M12 do verificador: as reprovações da Onda 1 chegam ao histórico com etapa onda1, com
    motivo e detalhe_interno; o lead que passa não ganha linha (controle negativo)."""
    linhas = [_linha("Sem Canal", "c1", Email="", Phone="+34 912 000 001"),
              _linha("Sem Sinal", "d1", **{"Average Rating": "", "Review Count": ""}),
              _linha("Passa", "p1", Instagram="@passa")]
    main_mod.importar_csv(_csv(tmp_path, linhas, nome="lista_hist_onda1_v1.csv"))
    assert _historico() == []  # o import não reprovou ninguém
    main_mod.fase_qualify()

    onda1 = {l["place_id"]: l for l in _historico() if l["etapa"] == "onda1"}
    assert set(onda1) == {"c1", "d1"}
    assert onda1["c1"]["motivo"] == "sem_canal_de_contato" and onda1["d1"]["motivo"] == "qualification_declined"
    assert onda1["c1"]["detalhe_interno"]["tem_email"] is False
    assert all(l["evento"] == "reprovado" and l["origem_csv"] == "lista_hist_onda1_v1.csv" for l in onda1.values())
    assert "p1" not in {l["place_id"] for l in _historico()}
    assert "p1" in _por_pid(main_mod.PATH_QUALIFICADOS)


def test_detalhe_onda1_das_avaliacoes():
    assert rep.detalhe_onda1({"review_count": 2}, "icp_reviews_abaixo_minimo", {"reviews_minimo": 5}) == \
        {"review_count": 2, "minimo": 5}
    assert rep.detalhe_onda1({}, "large_organization") is None


def test_filtro_de_rede_sobre_o_pool_carimba_as_fichas_movidas(tmp_path, campanhas):
    tel = {"Phone": "+34 600 111 222"}
    main_mod.importar_csv(_csv(tmp_path, [_linha("Rede A", "r1", **tel), _linha("Rede B", "r2", **tel)],
                               nome="lista_rede1_v1.csv"))
    main_mod.importar_csv(_csv(tmp_path, [_linha("Rede C", "r3", **tel)], nome="lista_rede2_v1.csv"))
    rep_ = _por_pid(main_mod.PATH_REPROVADOS)
    assert rep_["r1"]["etapa"] == "rede_pool" and rep_["r1"]["origem_csv"] == "lista_rede1_v1.csv"
    assert rep_["r3"]["etapa"] == "import" and rep_["r3"]["origem_csv"] == "lista_rede2_v1.csv"
    etapas = sorted((l["place_id"], l["etapa"]) for l in _historico())
    assert etapas == [("r1", "rede_pool"), ("r2", "rede_pool"), ("r3", "import")]


# --- 2. histórico ----------------------------------------------------------------------------

def test_historico_uma_linha_por_reprovacao_e_so_acrescenta(tmp_path, campanhas):
    main_mod.importar_csv(_csv(tmp_path, [_linha("Osteo A", "oa", Categories="Osteópata"),
                                          _linha("Osteo B", "ob", Categories="Osteópata")], nome="h1_v1.csv"))
    antes = Path(main_mod.PATH_HISTORICO_REPROVADOS).read_bytes()
    assert len(_historico()) == 2
    main_mod.importar_csv(_csv(tmp_path, [_linha("Osteo C", "oc", Categories="Osteópata")], nome="h2_v1.csv"))
    depois = Path(main_mod.PATH_HISTORICO_REPROVADOS).read_bytes()
    assert depois.startswith(antes)  # o que já estava continua idêntico, byte a byte
    linhas = _historico()
    assert [l["place_id"] for l in linhas] == ["oa", "ob", "oc"]
    assert linhas[0]["evento"] == "reprovado" and linhas[0]["dados_empresa"]["nome"] == "Osteo A"
    assert linhas[2]["origem_csv"] == "h2_v1.csv"


def test_historico_nunca_deduplica(tmp_path):
    caminho = str(tmp_path / "hist.jsonl")
    registro = {"dados_empresa": {"place_id": "x"}, "rejection_reason": "unknown", "reprovado_em": "2026-10-07T10:00:00+00:00"}
    rep.acrescentar_historico(caminho, rep.linhas_reprovacao([registro]))
    rep.acrescentar_historico(caminho, rep.linhas_reprovacao([registro]))
    assert len(rep.ler_historico(caminho)[0]) == 2


def test_import_sem_reprovado_nao_cria_linha(tmp_path, campanhas):
    """Controle negativo: sem reprovação, o histórico não ganha linha nenhuma."""
    main_mod.importar_csv(_csv(tmp_path, [_linha("Fisio So", "fs")]))
    assert not os.path.exists(main_mod.PATH_HISTORICO_REPROVADOS)


# --- 3. consulta -----------------------------------------------------------------------------

def _linha_hist(pid, motivo, em, campanha_id="fis-t", cidade="Murcia", categoria="Osteópata"):
    return {"evento": "reprovado", "em": em, "place_id": pid, "nome": f"Nome {pid}", "categoria": categoria,
            "campanha_id": campanha_id, "campanha_cidade": cidade, "motivo": motivo, "origem_csv": "x_v1.csv"}


@pytest.fixture
def historico_ficticio():
    rep.acrescentar_historico(main_mod.PATH_HISTORICO_REPROVADOS, [
        _linha_hist("a", "icp_categoria_fora_do_perfil", "2026-09-30T12:00:00+00:00"),
        _linha_hist("b", "icp_categoria_fora_do_perfil", "2026-10-02T12:00:00+00:00"),
        _linha_hist("c", "icp_categoria_fora_do_perfil", "2026-10-03T12:00:00+00:00", campanha_id="abo-t",
                    cidade="Alicante", categoria="Notaría"),
        _linha_hist("d", "sem_canal_de_contato", "2026-10-03T12:00:00+00:00", categoria="Fisioterapeuta"),
        _linha_hist("e", "motivo_novo_xyz", "2026-10-04T12:00:00+00:00"),
    ])


def test_consulta_filtra_por_data_e_motivo_e_agrupa(historico_ficticio, capsys):
    sel = main_mod.fase_reprovados(desde=date(2026, 10, 1), motivo="icp_categoria_fora_do_perfil")
    assert sorted(l["place_id"] for l in sel) == ["b", "c"]
    out = capsys.readouterr().out
    assert "categoria fora do perfil da campanha (icp_categoria_fora_do_perfil)" in out
    assert "Total encontrado: 2" in out
    for titulo in ("Por motivo:", "Por campanha:", "Por cidade (a da busca):", "Por categoria do Google:"):
        assert titulo in out
    assert "O histórico começa em 30/09/2026" in out


@pytest.mark.parametrize("filtros,esperados", [
    ({"ate": date(2026, 10, 2)}, ["a", "b"]),
    ({"campanha": "ABO"}, ["c"]),
    ({"cidade": "alicante"}, ["c"]),
    ({"categoria": "notaria"}, ["c"]),  # sem acento
    ({"motivo": "nao_existe"}, []),
])
def test_consulta_cada_filtro(historico_ficticio, filtros, esperados):
    assert sorted(l["place_id"] for l in main_mod.fase_reprovados(**filtros)) == esperados


def test_motivo_sem_traducao_aparece_com_o_codigo_e_lista_por_lead(historico_ficticio, capsys):
    main_mod.fase_reprovados(motivo="motivo_novo_xyz", lista=True)
    out = capsys.readouterr().out
    assert "motivo_novo_xyz" in out and "Nome e" in out


MADRI = ZoneInfo("Europe/Madrid")


def test_virada_de_dia_no_fuso_de_madri_verao_e_inverno():
    """M3 do verificador: a data vem do fuso de Madri fixado no teste, nunca do relógio nem do
    fuso da máquina. Verão (UTC+2): 21:30Z ainda é 1/7, 22:30Z já é 2/7. Inverno (UTC+1): 21:30Z
    e 22:30Z ainda são 15/1."""
    rep.acrescentar_historico(main_mod.PATH_HISTORICO_REPROVADOS, [
        _linha_hist("v1", "unknown", "2026-07-01T21:30:00+00:00"),
        _linha_hist("v2", "unknown", "2026-07-01T22:30:00+00:00"),
        _linha_hist("i1", "unknown", "2026-01-15T21:30:00+00:00"),
        _linha_hist("i2", "unknown", "2026-01-15T22:30:00+00:00"),
    ])

    def dia(d, fuso=MADRI):
        return sorted(l["place_id"] for l in main_mod.fase_reprovados(desde=d, ate=d, fuso=fuso))
    assert dia(date(2026, 7, 1)) == ["v1"]
    assert dia(date(2026, 7, 2)) == ["v2"]
    assert dia(date(2026, 1, 15)) == ["i1", "i2"]
    assert dia(date(2026, 1, 16)) == []
    # controle: pelo dia em UTC o 22:30Z de verão continuaria em 1/7 -- o fuso faz diferença
    assert dia(date(2026, 7, 1), fuso=timezone.utc) == ["v1", "v2"]


def test_devolvido_conta_so_quando_vem_depois_da_reprovacao_e_mostra_eventos_e_leads(capsys):
    """Lead A: reprovado, devolvido, reprovado de novo -- só a 1ª reprovação foi seguida de
    devolução. Lead B: devolução sem reprovação depois dela não conta para a reprovação dele."""
    rep.acrescentar_historico(main_mod.PATH_HISTORICO_REPROVADOS, [
        _linha_hist("A", "icp_categoria_fora_do_perfil", "2026-10-01T10:00:00+00:00"),
        {**_linha_hist("A", "icp_categoria_fora_do_perfil", "2026-10-02T10:00:00+00:00"), "evento": "devolvido"},
        _linha_hist("A", "qualification_declined", "2026-10-03T10:00:00+00:00"),
        {**_linha_hist("B", "icp_categoria_fora_do_perfil", "2026-09-01T10:00:00+00:00"), "evento": "devolvido"},
        _linha_hist("B", "sem_canal_de_contato", "2026-09-05T10:00:00+00:00"),
    ])
    todas = _historico()
    selecionadas = main_mod.fase_reprovados()
    assert [(l["place_id"], l["em"][:10]) for l in rep.seguidas_de_devolucao(selecionadas, todas)] == \
        [("A", "2026-10-01")]
    out = capsys.readouterr().out
    assert "Total encontrado: 3 reprovação(ões), de 2 lead(s) diferente(s)." in out
    assert "Destas, 1 reprovação(ões) foram seguidas de devolução à fila" in out


def test_consulta_sem_resultado_lista_os_motivos_validos(historico_ficticio, capsys):
    assert main_mod.fase_reprovados(motivo="motivo_que_nao_existe") == []
    out = capsys.readouterr().out
    assert "Nenhuma reprovação encontrada com esse filtro." in out and "Motivos válidos" in out
    assert "icp_categoria_fora_do_perfil = categoria fora do perfil da campanha  [há reprovações no histórico]" in out
    assert "large_organization = organização grande: hospital, grupo ou rede" in out
    assert "motivo_novo_xyz = motivo sem frase  [há reprovações no histórico]" in out


def test_lista_mostra_a_frase_do_motivo(historico_ficticio, capsys):
    main_mod.fase_reprovados(motivo="sem_canal_de_contato", lista=True)
    linha = [l for l in capsys.readouterr().out.splitlines() if "Nome d" in l]
    assert linha and "sem canal para abordar: sem e-mail, sem rede social e sem celular (sem_canal_de_contato)" in linha[0]


def test_consulta_com_historico_vazio_explica(capsys):
    assert main_mod.fase_reprovados() == []
    assert "Ainda não há nenhuma reprovação anotada no histórico." in capsys.readouterr().out


def test_consulta_nao_altera_nenhum_arquivo(tmp_path, campanhas, historico_ficticio):
    main_mod.importar_csv(_csv(tmp_path, [_linha("Osteo Z", "oz", Categories="Osteópata"), _linha("F", "f9")]))
    antes = _hashes_do_pool()
    main_mod.fase_reprovados(desde=date(2026, 10, 1), lista=True)
    assert _hashes_do_pool() == antes


def test_linha_de_comando_recusa_data_errada_e_confirmar_fora_de_lugar(monkeypatch, capsys):
    for argv in (["main.py", "reprovados", "--desde", "2026-13-01"],
                 ["main.py", "reprovados", "--confirmar"],
                 ["main.py", "qualify", "--motivo", "x"]):
        monkeypatch.setattr("sys.argv", argv)
        with pytest.raises(SystemExit) as exc:
            main_mod.run()
        assert exc.value.code == 2
    err = capsys.readouterr().err
    assert "ano-mês-dia" in err and "--confirmar só vale" in err


# --- 4. reavaliação --------------------------------------------------------------------------

def _pool_para_reavaliar(tmp_path, campanhas, extra=()):
    linhas = [_linha("Osteo Sem Site", "o1", Categories="Osteópata"),
              _linha("Osteo Com Site", "o2", Categories="Osteópata", Website="https://osteo-ficticio.es"),
              _linha("Podo Fora", "p1", Categories="Podólogo"),
              _linha("Fisio Ativo", "f1")] + list(extra)
    main_mod.importar_csv(_csv(tmp_path, linhas, nome="lista_reav_v1.csv"))
    campanhas["trocar"](categorias_aceitas=["fisioterap", "osteop"])  # a regra mudou


def test_reavaliar_sem_confirmar_so_mostra_e_nao_altera_nada(tmp_path, campanhas, capsys):
    _pool_para_reavaliar(tmp_path, campanhas)
    antes = _hashes_do_pool()
    r = main_mod.fase_reavaliar()
    assert _hashes_do_pool() == antes
    assert not (tmp_path / "_backups").exists()
    assert not r["confirmado"]
    assert [e["place_id"] for e in r["plano"]["wave1"]] == ["o1"]
    assert [e["place_id"] for e in r["plano"]["wave2"]] == ["o2"]
    out = capsys.readouterr().out
    assert "Voltariam para a fila: 2" in out and "Nada foi alterado" in out
    assert "Podo Fora" in out and "python main.py reavaliar --confirmar" in out


def test_reavaliar_confirmar_devolve_registra_e_faz_backup(tmp_path, campanhas, capsys):
    _pool_para_reavaliar(tmp_path, campanhas)
    antes = {os.path.basename(p): _hash(p) for p in main_mod._arquivos_do_pool() + [main_mod.PATH_HISTORICO_REPROVADOS]}
    r = main_mod.fase_reavaliar(confirmar=True)

    assert r["devolvidos"] == 2
    assert _por_pid(main_mod.PATH_COLETADOS)["o1"]["status"] == "eligible"
    assert _por_pid(main_mod.PATH_COM_SITE)["o2"]["status"] == "queued_future"
    assert set(_por_pid(main_mod.PATH_REPROVADOS)) == {"p1"}
    dev = [l for l in _historico() if l["evento"] == "devolvido"]
    assert sorted((l["place_id"], l["destino"]) for l in dev) == [("o1", "onda1"), ("o2", "onda2")]
    assert all(l["motivo"] == campanha.MOTIVO_FORA_DO_PERFIL and l["reprovado_em_anterior"] for l in dev)
    # backup de antes da mudança, conferido: cada cópia igual ao arquivo como era antes
    backup = Path(r["backup"])
    assert backup.parent == tmp_path / "_backups" and backup.name.startswith("pool-antes-de-reavaliar-")
    for nome, h in antes.items():
        if h is not None:
            assert _hash(backup / nome) == h
    assert str(backup) in capsys.readouterr().out


def test_reavaliar_duas_vezes_nao_duplica(tmp_path, campanhas):
    _pool_para_reavaliar(tmp_path, campanhas)
    main_mod.fase_reavaliar(confirmar=True)
    segunda = main_mod.fase_reavaliar(confirmar=True)
    assert segunda["devolvidos"] == 0
    ids = [r["dados_empresa"]["place_id"] for r in main_mod.carregar_json(main_mod.PATH_COLETADOS)]
    assert ids.count("o1") == 1


def test_reavaliar_lead_ja_no_pool_nao_duplica(tmp_path, campanhas, capsys):
    _pool_para_reavaliar(tmp_path, campanhas)
    reprovados = main_mod.carregar_json(main_mod.PATH_REPROVADOS)
    copia_f1 = dict(_por_pid(main_mod.PATH_COLETADOS)["f1"]["dados_empresa"])
    reprovados.append({"dados_empresa": copia_f1, "status": "rejected",
                       "rejection_reason": campanha.MOTIVO_FORA_DO_PERFIL})
    main_mod.salvar_json(main_mod.PATH_REPROVADOS, reprovados)
    main_mod.fase_reavaliar(confirmar=True)
    ids = [r["dados_empresa"]["place_id"] for r in main_mod.carregar_json(main_mod.PATH_COLETADOS)]
    assert ids.count("f1") == 1
    assert "Já estão no pool ativo" in capsys.readouterr().out


def test_reavaliar_campanha_inexistente_nao_volta(tmp_path, campanhas, capsys):
    _pool_para_reavaliar(tmp_path, campanhas)
    reprovados = main_mod.carregar_json(main_mod.PATH_REPROVADOS)
    for r in reprovados:
        if r["dados_empresa"]["place_id"] == "o1":
            r["dados_empresa"]["campanha_id"] = "campanha-que-sumiu"
    main_mod.salvar_json(main_mod.PATH_REPROVADOS, reprovados)
    r = main_mod.fase_reavaliar(confirmar=True)
    assert "o1" in _por_pid(main_mod.PATH_REPROVADOS)
    assert [x["dados_empresa"]["place_id"] for x in r["plano"]["sem_campanha"]] == ["o1"]
    assert "Campanha não encontrada (o lead não volta): 1" in capsys.readouterr().out


def test_reavaliar_lead_que_cai_em_outro_filtro_continua_fora(tmp_path, campanhas):
    sem_nada = _linha("Osteo Sem Nada", "o3", Categories="Osteópata", Phone="", Email="",
                      **{"Average Rating": "", "Review Count": ""})
    _pool_para_reavaliar(tmp_path, campanhas, extra=[sem_nada])
    main_mod.fase_reavaliar(confirmar=True)
    r = _por_pid(main_mod.PATH_REPROVADOS)["o3"]
    assert (r["rejection_reason"], r["etapa"]) == ("no_contact_no_signal", "reavaliacao")
    assert "o3" not in _por_pid(main_mod.PATH_COLETADOS)
    assert [l["etapa"] for l in _historico() if l["place_id"] == "o3"] == ["import", "reavaliacao"]


def test_reavaliar_lead_cujo_grupo_ja_e_rede_continua_fora_por_rede(tmp_path, campanhas):
    """Caso real: o reprovado por categoria já contou no grupo no import (regra existente),
    então as duas ativas saíram ali como rede; devolvido, o lead cai na mesma regra."""
    tel = {"Phone": "+34 600 999 888"}
    main_mod.importar_csv(_csv(tmp_path, [_linha("Ativa Um", "a1", **tel), _linha("Ativa Dois", "a2", **tel)],
                               nome="rede_ativas_v1.csv"))
    _pool_para_reavaliar(tmp_path, campanhas, extra=[_linha("Osteo Rede", "o4", Categories="Osteópata", **tel)])
    assert _por_pid(main_mod.PATH_REPROVADOS)["o4"]["rejection_reason"] == campanha.MOTIVO_FORA_DO_PERFIL
    main_mod.fase_reavaliar(confirmar=True)
    r = _por_pid(main_mod.PATH_REPROVADOS)["o4"]
    assert (r["rejection_reason"], r["etapa"]) == ("rede_ou_multiunidade", "reavaliacao")
    assert "o4" not in _por_pid(main_mod.PATH_COLETADOS)


def test_reavaliar_lead_que_completa_rede_mostra_na_previa_e_aplica_a_regra_do_import(tmp_path, campanhas, capsys):
    """Pool montado antes da regra de redes (simulado escrevendo o reprovado direto no arquivo):
    a devolução forma um grupo de 3 com duas fichas ATIVAS, que saem do pool como no import."""
    tel = {"Phone": "+34 600 999 888"}
    main_mod.importar_csv(_csv(tmp_path, [_linha("Ativa Um", "a1", **tel), _linha("Ativa Dois", "a2", **tel)],
                               nome="rede_ativas_v1.csv"))
    _pool_para_reavaliar(tmp_path, campanhas)
    reprovados = main_mod.carregar_json(main_mod.PATH_REPROVADOS)
    o4 = json.loads(json.dumps(_por_pid(main_mod.PATH_REPROVADOS)["o1"]))
    o4["dados_empresa"].update(place_id="o4", nome="Osteo Rede", telefone="+34 600 999 888")
    main_mod.salvar_json(main_mod.PATH_REPROVADOS, reprovados + [o4])
    assert {"a1", "a2"} <= set(_por_pid(main_mod.PATH_COLETADOS))

    antes = _hashes_do_pool()
    main_mod.fase_reavaliar()
    out = capsys.readouterr().out
    assert _hashes_do_pool() == antes
    assert "ATENÇÃO: fichas que hoje estão ATIVAS e sairiam do pool" in out and "Ativa Um" in out

    main_mod.fase_reavaliar(confirmar=True)
    rep_ = _por_pid(main_mod.PATH_REPROVADOS)
    assert rep_["a1"]["rejection_reason"] == rep_["o4"]["rejection_reason"] == "rede_ou_multiunidade"
    assert rep_["a1"]["etapa"] == "rede_pool" and rep_["o4"]["etapa"] == "reavaliacao"
    assert not ({"a1", "a2", "o4"} & set(_por_pid(main_mod.PATH_COLETADOS)))


def test_reavaliar_backup_que_falha_nao_altera_nada(tmp_path, campanhas, monkeypatch, capsys):
    _pool_para_reavaliar(tmp_path, campanhas)
    antes = _hashes_do_pool()

    def falha(*a, **k):
        raise rep.BackupFalhouError("disco cheio (simulado). Nada foi alterado.")
    monkeypatch.setattr(rep, "backup_conferido", falha)
    assert main_mod.fase_reavaliar(confirmar=True) is None
    assert _hashes_do_pool() == antes
    assert "O backup falhou" in capsys.readouterr().out


def test_reavaliar_lead_duplicado_a_mao_vai_para_olho_humano_e_nao_volta(tmp_path, campanhas, capsys):
    """M9 do verificador: o mesmo lead duas vezes em leads_reprovados.json aparece UMA vez na
    prévia, com "(aparece 2 vezes)", conta como um lead e não volta para a fila."""
    _pool_para_reavaliar(tmp_path, campanhas)
    reprovados = main_mod.carregar_json(main_mod.PATH_REPROVADOS)
    duplicado = json.loads(json.dumps(_por_pid(main_mod.PATH_REPROVADOS)["o1"]))
    main_mod.salvar_json(main_mod.PATH_REPROVADOS, reprovados + [duplicado])

    main_mod.fase_reavaliar()
    out = capsys.readouterr().out
    assert out.count("Osteo Sem Site") == 1
    assert "Osteo Sem Site · Osteópata · Alicante (campanha fis-t) (aparece 2 vezes)" in out
    assert "precisam de olho humano): 1 lead(s)" in out
    assert "Reprovados por categoria no pool atual: 3 lead(s) (4 registros)" in out
    assert "Voltariam para a fila: 1 lead(s)" in out  # só o o2

    main_mod.fase_reavaliar(confirmar=True)
    assert "o1" not in _por_pid(main_mod.PATH_COLETADOS)
    restantes = [r["dados_empresa"]["place_id"] for r in main_mod.carregar_json(main_mod.PATH_REPROVADOS)]
    assert restantes.count("o1") == 2  # os dois registros continuam, para o olho humano
    assert not [l for l in _historico() if l["evento"] == "devolvido" and l["place_id"] == "o1"]


@pytest.fixture
def duas_campanhas(tmp_path, monkeypatch):
    """M1b do verificador: a campanha do MENU (psi-t, com o arquivo ativo próprio) e a campanha
    do LEAD (fis-t, escolhida pelo termo da busca) são diferentes."""
    pasta = tmp_path / "campanhas2"
    pasta.mkdir()
    psi = {"id": "psi-t", "nicho": "Psicólogos (teste)", "cidade_padrao": "Alicante",
           "categorias_aceitas": ["psicolog"], "categorias_excluidas": [], "termos_de_busca": ["psicolog"]}
    (pasta / "psi-t.json").write_text(json.dumps(psi), encoding="utf-8")
    (pasta / "fis-t.json").write_text(json.dumps(FIS), encoding="utf-8")
    ativa = tmp_path / "campanha_ativa.json"
    ativa.write_text(json.dumps(psi), encoding="utf-8")
    monkeypatch.setenv(campanha.ENV_DIR_CAMPANHAS, str(pasta))
    monkeypatch.setenv(campanha.ENV_CAMINHO, str(ativa))
    monkeypatch.delenv(municipios.ENV_CAMINHO, raising=False)

    def trocar(arquivo, base, **over):
        arquivo.write_text(json.dumps({**base, **over}), encoding="utf-8")
    return {"pasta": pasta, "ativa": ativa, "psi": psi, "trocar": trocar}


def test_reavaliar_usa_a_campanha_do_lead_e_nao_a_do_menu(tmp_path, duas_campanhas):
    c = duas_campanhas
    main_mod.importar_csv(_csv(tmp_path, [_linha("Osteo Termo", "ot", Categories="Osteópata")],
                               nome="lista_duas_v1.csv", termo="fisioterapeuta murcia"))
    assert _por_pid(main_mod.PATH_REPROVADOS)["ot"]["dados_empresa"]["campanha_id"] == "fis-t"

    # mudar só o menu (arquivo ativo e a campanha do menu na pasta) não devolve nada
    c["trocar"](c["ativa"], c["psi"], categorias_aceitas=["psicolog", "osteop"])
    c["trocar"](c["pasta"] / "psi-t.json", c["psi"], categorias_aceitas=["psicolog", "osteop"])
    r = main_mod.fase_reavaliar(confirmar=True)
    assert r["devolvidos"] == 0 and "ot" in _por_pid(main_mod.PATH_REPROVADOS)

    # mudar a campanha do lead devolve
    c["trocar"](c["pasta"] / "fis-t.json", FIS, categorias_aceitas=["fisioterap", "osteop"])
    r = main_mod.fase_reavaliar(confirmar=True)
    assert r["devolvidos"] == 1 and "ot" in _por_pid(main_mod.PATH_COLETADOS)


def test_reavaliar_backup_pela_metade_vira_incompleto_e_nada_muda(tmp_path, campanhas, monkeypatch, capsys):
    _pool_para_reavaliar(tmp_path, campanhas)
    antes = _hashes_do_pool()
    chamadas = []
    original = rep.shutil.copy2

    def copia_que_falha_na_segunda(origem, destino):
        chamadas.append(origem)
        if len(chamadas) == 2:
            raise OSError("falha simulada")
        return original(origem, destino)
    monkeypatch.setattr(rep.shutil, "copy2", copia_que_falha_na_segunda)
    assert main_mod.fase_reavaliar(confirmar=True) is None
    assert _hashes_do_pool() == antes
    [pasta] = list((tmp_path / "_backups").iterdir())
    assert pasta.name.startswith("pool-antes-de-reavaliar-") and pasta.name.endswith("-INCOMPLETO")
    assert len([p for p in pasta.iterdir() if p.is_file()]) == 1  # o que já tinha sido copiado fica
    out = capsys.readouterr().out
    assert "INCOMPLETO" in out and "nada foi apagado" in out


# --- A. arquivar-pool ------------------------------------------------------------------------

def _pool_com_historico(tmp_path, campanhas):
    main_mod.importar_csv(_csv(tmp_path, [_linha("Osteo Arq", "oq", Categories="Osteópata"), _linha("F", "fq"),
                                          _linha("Com Site", "sq", Website="https://site-ficticio.es")]))
    assert os.path.exists(main_mod.PATH_HISTORICO_REPROVADOS)


def test_arquivar_sem_confirmar_nao_altera_nada(tmp_path, campanhas, capsys):
    _pool_com_historico(tmp_path, campanhas)
    antes = _hashes_do_pool()
    assert main_mod.fase_arquivar_pool() == {"confirmado": False}
    assert _hashes_do_pool() == antes
    assert not (tmp_path / "_backups").exists()
    assert "Nada foi alterado" in capsys.readouterr().out


def test_arquivar_confirmar_copia_confere_zera_e_preserva_historico(tmp_path, campanhas):
    _pool_com_historico(tmp_path, campanhas)
    antes = _hashes_do_pool()
    hist_bytes = Path(main_mod.PATH_HISTORICO_REPROVADOS).read_bytes()
    r = main_mod.fase_arquivar_pool(confirmar=True)

    backup = Path(r["backup"])
    assert backup.parent == tmp_path / "_backups" and backup.name.startswith("pool-arquivado-")
    for nome, h in antes.items():
        if h is not None:
            assert _hash(backup / nome) == h, nome
    assert Path(main_mod.PATH_HISTORICO_REPROVADOS).read_bytes() == hist_bytes
    assert r["historico_intacto"]
    for p in (main_mod.PATH_COLETADOS, main_mod.PATH_COM_SITE, main_mod.PATH_QUALIFICADOS, main_mod.PATH_REPROVADOS):
        assert main_mod.carregar_json(p) == []
    assert main_mod.carregar_json(main_mod.PATH_IMPORT_META) == {}


@pytest.mark.parametrize("defeito", ["copia_falha", "copia_diferente"])
def test_arquivar_com_copia_ruim_nao_zera_nada(tmp_path, campanhas, monkeypatch, capsys, defeito):
    _pool_com_historico(tmp_path, campanhas)
    antes = _hashes_do_pool()
    chamadas = []

    def copia_ruim(origem, destino):
        chamadas.append(origem)
        if len(chamadas) < 3:
            Path(destino).write_bytes(Path(origem).read_bytes())
        elif defeito == "copia_falha":
            raise OSError("falha simulada")
        else:
            Path(destino).write_bytes(b"conteudo diferente")
    monkeypatch.setattr(rep.shutil, "copy2", copia_ruim)
    assert main_mod.fase_arquivar_pool(confirmar=True) is None
    assert _hashes_do_pool() == antes
    out = capsys.readouterr().out
    assert "O pool NÃO foi zerado." in out
    # backup pela metade: renomeado para ...-INCOMPLETO, com o que já tinha sido copiado
    [pasta] = list((tmp_path / "_backups").iterdir())
    assert pasta.name.startswith("pool-arquivado-") and pasta.name.endswith("-INCOMPLETO")
    assert len([p for p in pasta.iterdir() if p.is_file()]) >= 2
    assert str(pasta) in out and "nada foi apagado" in out


def _criar_capturas_e_logs(tmp_path):
    capturas = Path(main_mod._pasta_capturas())
    (capturas / "fq").mkdir(parents=True)
    (capturas / "fq" / "mobile.png").write_bytes(b"\x89PNG captura ficticia mobile")
    (capturas / "desktop.png").write_bytes(b"\x89PNG captura ficticia desktop")
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "import_erro_ficticio.log").write_text("log ficticio", encoding="utf-8")
    return capturas, logs


def test_arquivar_leva_as_capturas_para_o_backup_e_deixa_os_logs(tmp_path, campanhas, capsys):
    _pool_com_historico(tmp_path, campanhas)
    capturas, logs = _criar_capturas_e_logs(tmp_path)
    hashes = {p.relative_to(capturas).as_posix(): _hash(p) for p in capturas.rglob("*") if p.is_file()}

    main_mod.fase_arquivar_pool()
    assert "capturas_site/: 2 arquivo(s)" in capsys.readouterr().out and capturas.is_dir()  # prévia não mexe

    r = main_mod.fase_arquivar_pool(confirmar=True)
    backup = Path(r["backup"])
    for rel, h in hashes.items():
        assert _hash(backup / "capturas_site" / rel) == h, rel
    assert not capturas.exists()
    assert (logs / "import_erro_ficticio.log").read_text(encoding="utf-8") == "log ficticio"
    assert not (backup / "logs").exists()


def test_arquivar_com_copia_de_captura_ruim_nao_remove_nada(tmp_path, campanhas, monkeypatch):
    _pool_com_historico(tmp_path, campanhas)
    capturas, _logs = _criar_capturas_e_logs(tmp_path)
    antes = _hashes_do_pool()
    original = rep.shutil.copy2

    def falha_nas_capturas(origem, destino):
        if "capturas_site" in str(origem):
            raise OSError("falha simulada na captura")
        return original(origem, destino)
    monkeypatch.setattr(rep.shutil, "copy2", falha_nas_capturas)
    assert main_mod.fase_arquivar_pool(confirmar=True) is None
    assert _hashes_do_pool() == antes
    assert sorted(p.name for p in capturas.rglob("*") if p.is_file()) == ["desktop.png", "mobile.png"]


def test_mensagens_dos_comandos_novos_nao_usam_seta_unicode(tmp_path, campanhas, capsys):
    """No console padrão do Windows a seta "→" sai como "?": os comandos novos usam "->"."""
    _pool_para_reavaliar(tmp_path, campanhas)
    _criar_capturas_e_logs(tmp_path)
    capsys.readouterr()
    main_mod.fase_reprovados(lista=True)
    main_mod.fase_reprovados(motivo="nao_existe")
    main_mod.fase_reavaliar()
    main_mod.fase_reavaliar(confirmar=True)
    main_mod.fase_arquivar_pool()
    main_mod.fase_arquivar_pool(confirmar=True)
    out = capsys.readouterr().out
    assert "->" in out and "→" not in out


def test_guardiao_vigia_a_pasta_real_de_backups_mesmo_com_o_env_no_shell(monkeypatch, tmp_path):
    import conftest
    real = rep.dir_backups_padrao()
    monkeypatch.setenv(rep.ENV_BACKUP_DIR, str(tmp_path / "outra"))
    pastas = dict((rotulo, Path(p)) for rotulo, p in conftest._pastas_producao())
    assert pastas["_backups/leadfarm"] == real
    assert pastas["QUALIFICADOR_BACKUP_DIR do shell"] == tmp_path / "outra"  # a do env também
    for rotulo in ("EQC/pipeline", "qualificador/prospeccao_ia/data", "EQC/contracts"):
        assert rotulo in pastas  # nenhuma proteção anterior saiu


def test_pasta_de_backup_padrao_fica_fora_do_repositorio(monkeypatch):
    monkeypatch.delenv(rep.ENV_BACKUP_DIR, raising=False)
    pasta = rep.dir_backups()
    raiz_repo = Path(contrato.eqc_root()).resolve().parent
    assert pasta.parts[-2:] == ("_backups", "leadfarm")
    assert raiz_repo not in pasta.parents


# --- C. nada atravessa para o COMERCIAL ------------------------------------------------------

CAMPOS_NOVOS = {"origem_csv", "termo_busca", "detalhe_interno", "reprovado_em", "etapa"}
VALORES_NOVOS = ("lista-ficticia-xyz_v1.csv", "termo ficticio xyz", "valor-interno-xyz")
CARIMBO = {"campanha_id": "camp-teste", "campanha_nicho": "Teste", "campanha_cidade": "Murcia",
           "possivel_mesmo_negocio": []}


def _registros(com_campos_novos):
    novos_emp = {"origem_csv": VALORES_NOVOS[0], "termo_busca": VALORES_NOVOS[1]} if com_campos_novos else {}
    novos_reg = ({"reprovado_em": "2026-10-07T10:00:00+00:00", "origem_csv": VALORES_NOVOS[0],
                  "termo_busca": VALORES_NOVOS[1], "etapa": "onda1",
                  "detalhe_interno": {"marca": VALORES_NOVOS[2]}} if com_campos_novos else {})
    com_site = [_nata(place_id="n1", **CARIMBO, **novos_emp),
                _com_site(dados_empresa=_emp(place_id="t1", review_count=50, **CARIMBO, **novos_emp))]
    qualificados = [_qualificado(place_id="q1", **CARIMBO, **novos_emp)]
    reprovados = [{"dados_empresa": _emp(place_id="r1", **CARIMBO, **novos_emp), "status": "rejected",
                   "rejection_reason": "sem_canal_de_contato", **novos_reg}]
    return qualificados, com_site, reprovados


def _chaves(obj):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield k
            yield from _chaves(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _chaves(v)


def test_campos_novos_nao_mudam_nada_do_handoff_nem_do_csv_humano():
    sem = oj.montar(*_registros(False))
    com = oj.montar(*_registros(True))
    contrato.validar(com)
    assert com["nata"] and com["candidatos_triagem"] and com["descartados"]
    for doc in (sem, com):
        doc.pop("generated_at")
    assert com == sem  # leads aprovados (nata, triagem), descartados e stats idênticos

    for lista in ("nata", "candidatos_triagem", "descartados"):
        assert not (CAMPOS_NOVOS & set(_chaves(com[lista]))), lista
    texto = json.dumps(com, ensure_ascii=False)
    assert not any(v in texto for v in VALORES_NOVOS)

    q_sem, s_sem, _ = _registros(False)
    q_com, s_com, _ = _registros(True)
    linhas_com = sh.montar_linhas(q_com, s_com)
    assert linhas_com and linhas_com == sh.montar_linhas(q_sem, s_sem)
    assert not any(v in json.dumps(linhas_com, ensure_ascii=False) for v in VALORES_NOVOS)


def test_controle_positivo_o_detector_acha_campo_que_vazasse():
    """Prova que a varredura acima pegaria um vazamento (sem isto ela poderia passar sempre)."""
    _q, com_site, reprovados = _registros(True)
    doc = oj.montar([], com_site, reprovados)
    doc["descartados"][0]["campos_do_corte"]["detalhe_interno"] = {"marca": VALORES_NOVOS[2]}
    assert CAMPOS_NOVOS & set(_chaves(doc["descartados"]))
    assert VALORES_NOVOS[2] in json.dumps(doc)
