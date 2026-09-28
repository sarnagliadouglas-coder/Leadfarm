import glob
import json

import contrato
import main as main_mod


def _isolar_todos_os_caminhos(tmp_path, monkeypatch):
    for nome, arquivo in [
        ("PATH_COLETADOS", "coletados.json"), ("PATH_QUALIFICADOS", "qualificados.json"),
        ("PATH_REPROVADOS", "reprovados.json"), ("PATH_COM_SITE", "com_site.json"),
    ]:
        (tmp_path / arquivo).write_text(json.dumps([]), encoding="utf-8")
        monkeypatch.setattr(main_mod, nome, str(tmp_path / arquivo))
    monkeypatch.setattr(main_mod, "PATH_IMPORT_META", str(tmp_path / "_import_meta.json"))
    monkeypatch.setattr(main_mod, "DATA_DIR", str(tmp_path))
    monkeypatch.setenv("QUALIFICADOR_OUTPUT_DIR", str(tmp_path / "_saida"))


def _saida_gerada(tmp_path):
    arquivos = glob.glob(str(tmp_path / "_saida" / "leads_qualificados_*_v*.json"))
    arquivos = [a for a in arquivos if not a.endswith(".meta.json")]
    assert len(arquivos) == 1, arquivos
    return json.loads(open(arquivos[0], encoding="utf-8").read())


def test_fase_all_sem_csv_roda_todas_as_fases_com_entrada_vazia(tmp_path, monkeypatch):
    _isolar_todos_os_caminhos(tmp_path, monkeypatch)
    monkeypatch.setattr(main_mod, "importar_csv", lambda caminho: (_ for _ in ()).throw(AssertionError("não deveria importar")))

    resultado = main_mod.fase_all(caminho_csv=None)

    assert resultado["custo_total_usd"] == 0.0
    assert resultado["onda1"] is None
    assert resultado["onda2"] is None
    # fase_saida rodou de verdade e gerou um arquivo válido, mesmo sem lead nenhum
    saida = _saida_gerada(tmp_path)
    assert saida["stats"]["nata"] == 0
    assert saida["contract_version"] == contrato.CONTRACT_VERSION  # 2.1.0 (adiciona texto_site, MINOR)


def test_fase_all_encadeia_as_fases_na_ordem_certa(tmp_path, monkeypatch):
    _isolar_todos_os_caminhos(tmp_path, monkeypatch)

    chamadas = []
    monkeypatch.setattr(main_mod, "importar_csv", lambda c: chamadas.append(("import", c)))
    monkeypatch.setattr(main_mod, "fase_gbp", lambda: chamadas.append("gbp"))
    monkeypatch.setattr(main_mod, "fase_qualify", lambda: chamadas.append("qualify") or {"custo_total_usd": 0.0, "qualificados": 3})
    monkeypatch.setattr(main_mod, "fase_wave2", lambda: chamadas.append("wave2") or {"avaliados": 5})
    monkeypatch.setattr(main_mod, "fase_psi", lambda: chamadas.append("psi"))
    monkeypatch.setattr(main_mod, "fase_saida", lambda: chamadas.append("saida"))

    resultado = main_mod.fase_all(caminho_csv="dummy.csv")

    assert chamadas == [("import", "dummy.csv"), "gbp", "qualify", "wave2", "psi", "saida"]
    assert resultado["onda1"]["qualificados"] == 3
    assert resultado["onda2"]["avaliados"] == 5


def test_fase_qualify_reordena_pool_existente_mesmo_sem_lead_elegivel_novo(tmp_path, monkeypatch):
    """Leads que já pagaram a Qualification e estão em leads_qualificados.json não podem ser
    esquecidos só porque não chegou nenhum lead 'eligible' novo -- a fase re-ranqueia o pool
    e devolve métricas, nunca None."""
    coletados = tmp_path / "coletados.json"
    qualificados = tmp_path / "qualificados.json"
    reprovados = tmp_path / "reprovados.json"
    coletados.write_text(json.dumps([]), encoding="utf-8")
    qualificados.write_text(json.dumps([
        {"dados_empresa": {"nome": "Lead B", "place_id": "pB", "nicho": "Fisioterapeuta"},
         "qualificacao": {"score": 40, "priority": "media"}, "status": "qualified"},
        {"dados_empresa": {"nome": "Lead A", "place_id": "pA", "nicho": "Fisioterapeuta"},
         "qualificacao": {"score": 80, "priority": "alta"}, "status": "qualified"},
    ]), encoding="utf-8")
    reprovados.write_text(json.dumps([]), encoding="utf-8")

    monkeypatch.setattr(main_mod, "PATH_COLETADOS", str(coletados))
    monkeypatch.setattr(main_mod, "PATH_QUALIFICADOS", str(qualificados))
    monkeypatch.setattr(main_mod, "PATH_REPROVADOS", str(reprovados))

    metricas = main_mod.fase_qualify()

    assert metricas is not None
    assert metricas["chamadas_qualification"] == 0
    salvo = json.loads(qualificados.read_text(encoding="utf-8"))
    assert [r["dados_empresa"]["place_id"] for r in salvo] == ["pA", "pB"]  # re-ranqueado por score desc
