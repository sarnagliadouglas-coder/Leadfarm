import glob
import json
import os

import pytest

import contrato
import main as main_mod
import output_json
import saida_humana


def _isolar(tmp_path, monkeypatch):
    caminhos = {}
    for nome, arquivo in [
        ("PATH_QUALIFICADOS", "qualificados.json"),
        ("PATH_COM_SITE", "com_site.json"),
        ("PATH_REPROVADOS", "reprovados.json"),
        ("PATH_IMPORT_META", "_import_meta.json"),
    ]:
        caminho = tmp_path / arquivo
        caminhos[nome] = caminho
        monkeypatch.setattr(main_mod, nome, str(caminho))
    monkeypatch.setattr(main_mod, "DATA_DIR", str(tmp_path))
    monkeypatch.setenv("QUALIFICADOR_OUTPUT_DIR", str(tmp_path / "_saida"))
    caminhos["_OUT_DIR"] = tmp_path / "_saida"
    # Isola a saída humana também -- nunca escrever em EQC/pipeline/saidas-humanas/ real a
    # partir de um teste. QUALIFICADOR_SAIDA_HUMANA_OUTPUT_DIR (D6b, item 2) é o jeito
    # oficial de fazer isso agora -- uma variável, sem monkeypatchar a função nem tocar
    # QUALIFICADOR_EQC_ROOT (que também mudaria o schema resolvido por contrato.validar()).
    saida_humana_dir = tmp_path / "_saida_humana"
    monkeypatch.setenv(saida_humana.ENV_OUTPUT_DIR, str(saida_humana_dir))
    caminhos["_SAIDA_HUMANA_DIR"] = saida_humana_dir
    monkeypatch.delenv(saida_humana.ENV_COPIA_DIR, raising=False)
    return caminhos


def _saida_e_meta(out_dir):
    jsons = sorted(p for p in glob.glob(str(out_dir / "leads_qualificados_*_v*.json")) if not p.endswith(".meta.json"))
    metas = sorted(glob.glob(str(out_dir / "leads_qualificados_*_v*.meta.json")))
    assert len(jsons) == 1 and len(metas) == 1, (jsons, metas)
    return (json.loads(open(jsons[0], encoding="utf-8").read()),
            json.loads(open(metas[0], encoding="utf-8").read()))


def _csv_humano(pasta):
    import csv as _csv
    csvs = sorted(glob.glob(str(pasta / "qualificador_*.csv")))
    assert len(csvs) == 1, csvs
    with open(csvs[0], encoding="utf-8-sig", newline="") as f:
        linhas = list(_csv.DictReader(f, delimiter=";"))
    return csvs[0], linhas


def test_fase_saida_reune_tudo_num_arquivo(tmp_path, monkeypatch):
    caminhos = _isolar(tmp_path, monkeypatch)
    gbp = {"score_completude": None, "detail_scraped": False, "sinais": {}, "lacunas": []}
    caminhos["PATH_QUALIFICADOS"].write_text(json.dumps([
        {"dados_empresa": {"place_id": "q1", "nome": "A", "website_status": "not_listed_google_maps"},
         "qualificacao": {"score": 50, "priority": "media", "contactability": "media",
                          "evidence": [], "risks": [], "reasons": []},
         "gbp_diagnostico": gbp, "status": "qualified"}
    ]), encoding="utf-8")
    caminhos["PATH_COM_SITE"].write_text(json.dumps([
        {"dados_empresa": {"place_id": "s1", "nome": "B", "website": "https://b.es", "website_status": "listed"},
         "website_analysis": {"status": "ok", "error_type": None, "signals": {}}, "commercial_fit": {"score": 30, "reasons": []},
         "website_opportunity": {"score": 40, "reasons": []},
         "gbp_diagnostico": gbp,
         "priority_score": 35, "priority_label": "baixa", "wave2_evaluated_at": "2026-09-04T10:00:00Z", "status": "analyzed"},
        {"dados_empresa": {"place_id": "s2", "nome": "C"}, "status": "queued_future"},
    ]), encoding="utf-8")
    caminhos["PATH_REPROVADOS"].write_text(json.dumps([
        {"dados_empresa": {"place_id": "r1", "nome": "D", "nicho": "Hospital"},
         "status": "rejected", "rejection_reason": "large_organization"}
    ]), encoding="utf-8")
    caminhos["PATH_IMPORT_META"].write_text(json.dumps({"origem_csv": "maps-leads-teste.csv"}), encoding="utf-8")

    stats = main_mod.fase_saida()

    saida, meta = _saida_e_meta(caminhos["_OUT_DIR"])
    assert saida["schema_version"] == "2.0"
    assert saida["contract_version"] == contrato.CONTRACT_VERSION  # 2.1.0 (adiciona texto_site, MINOR)
    assert saida["origem_csv"] == "maps-leads-teste.csv"
    assert stats["nata"] == 0 and stats["candidatos_triagem"] == 0
    assert stats["descartados"] == 1 and stats["onda2_ainda_pendente"] == 1
    # amostra pequena e sem Detail Scraped -> health-check pulado, aviso de amostra insuficiente
    assert stats["gbp_field_warnings"] and "amostra insuficiente" in stats["gbp_field_warnings"][0]["aviso"]
    assert saida["descartados"][0]["place_id"] == "r1"

    assert meta["contract_version"] == contrato.CONTRACT_VERSION  # 2.1.0 (adiciona texto_site, MINOR)
    assert meta["origem_csv"] == "maps-leads-teste.csv"
    assert meta["leads_total"] == 0 and meta["sem_site"] == 0 and meta["com_site"] == 0 and meta["descartados"] == 1
    assert meta["qualificador_versao"] == "1.1.0"
    assert meta["gerado_em"] == saida["generated_at"]

    # --- Saída humana (Etapa D, passo D6) ---------------------------------------------
    # "A" (qualificado, sem site) -> Direta; "B" (com_site, analisado, sem problema, sem
    # avaliações suficientes pra triagem) -> Espera; "C" (queued_future) fica de fora;
    # "D" (descartado) fica de fora (nunca chega nem no CSV nem no JSON como lead).
    _csv_path, linhas_csv = _csv_humano(caminhos["_SAIDA_HUMANA_DIR"])
    assert [l["place_id"] for l in linhas_csv] == ["q1", "s1"]
    assert [l["pista"] for l in linhas_csv] == ["direta", "espera"]
    assert linhas_csv[0]["motivo"] == "sem site"
    assert linhas_csv[1]["motivo"] == "sem problema encontrado"
    leiame = caminhos["_SAIDA_HUMANA_DIR"] / saida_humana.LEIAME_NOME
    assert leiame.is_file()


def test_fase_saida_com_tudo_vazio_nao_quebra(tmp_path, monkeypatch):
    caminhos = _isolar(tmp_path, monkeypatch)
    stats = main_mod.fase_saida()
    assert stats["nata"] == 0
    saida, _meta = _saida_e_meta(caminhos["_OUT_DIR"])
    assert saida["nata"] == [] and saida["candidatos_triagem"] == []
    _csv_path, linhas_csv = _csv_humano(caminhos["_SAIDA_HUMANA_DIR"])
    assert linhas_csv == []


def test_fase_saida_copia_de_conveniencia_com_destino_invalido_nao_derruba_a_rodada(tmp_path, monkeypatch):
    """Item de prova do D6: destino inválido para a cópia de conveniência não pode fazer
    fase_saida() levantar nem deixar de gravar as duas saídas oficiais."""
    caminhos = _isolar(tmp_path, monkeypatch)
    destino_invalido = tmp_path / "isto_e_um_arquivo"
    destino_invalido.write_text("nao sou uma pasta", encoding="utf-8")
    monkeypatch.setenv(saida_humana.ENV_COPIA_DIR, str(destino_invalido))

    stats = main_mod.fase_saida()  # não deve levantar

    assert stats is not None
    _saida_e_meta(caminhos["_OUT_DIR"])  # JSON/meta foram gravados normalmente
    _csv_humano(caminhos["_SAIDA_HUMANA_DIR"])  # CSV oficial foi gravado normalmente
    # nenhum arquivo foi criado "dentro" do destino inválido (que nem é uma pasta)
    assert destino_invalido.read_text(encoding="utf-8") == "nao sou uma pasta"


def test_fase_saida_copia_de_conveniencia_com_destino_valido_copia_o_csv(tmp_path, monkeypatch):
    caminhos = _isolar(tmp_path, monkeypatch)
    destino = tmp_path / "conveniencia"
    monkeypatch.setenv(saida_humana.ENV_COPIA_DIR, str(destino))

    main_mod.fase_saida()

    caminho_oficial, _ = _csv_humano(caminhos["_SAIDA_HUMANA_DIR"])
    copia = destino / os.path.basename(caminho_oficial)
    assert copia.is_file()
    assert copia.read_bytes() == open(caminho_oficial, "rb").read()


# --- Achado 3, RODADA REAL 23/09/2026: mensagem clara quando falta rodar uma fase ---------


def _com_site_sem_gbp(place_id="s1"):
    return {
        "dados_empresa": {"place_id": place_id, "nome": "B", "website": "https://b.es",
                           "website_status": "listed", "review_count": 20},
        "website_analysis": {"status": "ok", "error_type": None, "signals": {}},
        "commercial_fit": {"score": 30, "reasons": []},
        "wave2_evaluated_at": "2026-09-23T10:00:00Z", "status": "analyzed",
        # sem "gbp_diagnostico" -- fase_gbp nunca rodou pra este lead
    }


def test_fase_saida_sem_gbp_levanta_mensagem_clara_e_nao_grava_nada(tmp_path, monkeypatch):
    caminhos = _isolar(tmp_path, monkeypatch)
    caminhos["PATH_COM_SITE"].write_text(json.dumps([_com_site_sem_gbp()]), encoding="utf-8")

    with pytest.raises(output_json.FaseAnteriorAusenteError) as exc:
        main_mod.fase_saida()

    msg = str(exc.value)
    assert "gbp_diagnostico" in msg
    assert "python main.py gbp" in msg
    assert "1 lead" in msg
    # nada foi gravado -- nem o contrato, nem a saída humana
    assert glob.glob(str(caminhos["_OUT_DIR"] / "*.json")) == []
    assert not caminhos["_SAIDA_HUMANA_DIR"].exists() or glob.glob(
        str(caminhos["_SAIDA_HUMANA_DIR"] / "*.csv")) == []


def test_fase_saida_com_gbp_grava_normalmente_apos_o_erro_anterior(tmp_path, monkeypatch):
    """Controle negativo do achado 3: o MESMO lead, agora com gbp_diagnostico presente
    (fase_gbp rodou), grava normalmente -- a checagem nova não reprova estado completo."""
    caminhos = _isolar(tmp_path, monkeypatch)
    registro = _com_site_sem_gbp()
    registro["gbp_diagnostico"] = {"score_completude": 50, "detail_scraped": True,
                                    "sinais": {}, "lacunas": []}
    caminhos["PATH_COM_SITE"].write_text(json.dumps([registro]), encoding="utf-8")

    stats = main_mod.fase_saida()  # não levanta

    assert stats is not None
    _saida_e_meta(caminhos["_OUT_DIR"])
    _csv_humano(caminhos["_SAIDA_HUMANA_DIR"])
