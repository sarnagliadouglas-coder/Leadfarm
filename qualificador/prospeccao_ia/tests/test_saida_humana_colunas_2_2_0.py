"""CSV humano, colunas acrescentadas no fim em 2.2.0: campanha_id, campanha_nicho,
possivel_mesmo_negocio, prioridade_rotulo, prioridade_score. Dados fictícios."""
import csv

import saida_humana as sh
from test_output_json import _com_site, _emp, _qualificado

ANTIGAS = ("pista", "motivo", "nome", "nicho", "cidade", "telefone", "email", "instagram", "site",
           "classe_site", "avaliacoes", "nota", "google_maps_url", "place_id")
NOVAS = ("campanha_id", "campanha_nicho", "possivel_mesmo_negocio", "prioridade_rotulo", "prioridade_score")
# 2.3.0 (06/10/2026): mais uma no fim, depois das da 2.2.0 -- ver test_contrato_2_3_0.py.
NOVAS_2_3_0 = ("campanha_cidade",)
CARIMBO = {"campanha_id": "camp-teste", "campanha_nicho": "Psicólogos (teste)"}


def test_colunas_novas_no_fim_e_antigas_na_mesma_ordem():
    assert sh.COLUNAS == ANTIGAS + NOVAS + NOVAS_2_3_0


def test_onda1_traz_carimbo_aviso_e_prioridade():
    q = _qualificado(**CARIMBO, possivel_mesmo_negocio=[
        {"place_id": "p-outro", "por": "telefone", "chave": "600000001"},
        {"place_id": "p-outro", "por": "dominio", "chave": "x.es"}])
    [linha] = sh.montar_linhas([q], [])
    assert (linha["campanha_id"], linha["campanha_nicho"]) == ("camp-teste", "Psicólogos (teste)")
    assert linha["possivel_mesmo_negocio"] == "p-outro"          # sem repetir o mesmo place_id
    assert (linha["prioridade_rotulo"], linha["prioridade_score"]) == ("media", 48)


def test_onda2_direta_fica_sem_prioridade_da_onda1():
    registro = _com_site(dados_empresa=_emp(website="https://booksy.com/es/x", website_status="listed",
                                             **CARIMBO, possivel_mesmo_negocio=[]))
    [linha] = sh.montar_linhas([], [registro])
    assert linha["pista"] == "direta"
    assert (linha["prioridade_rotulo"], linha["prioridade_score"]) == ("", "")
    assert linha["possivel_mesmo_negocio"] == ""                 # checado, sem par
    assert linha["campanha_id"] == "camp-teste"


def test_lead_antigo_sem_carimbo_vem_nao_verificado():
    [linha] = sh.montar_linhas([_qualificado()], [])
    assert linha["campanha_id"] == linha["campanha_nicho"] == linha["possivel_mesmo_negocio"] == "NAO_VERIFICADO"


def test_score_zero_nao_vira_celula_vazia():
    """Controle: 0 é um score real; só ausência vira vazio."""
    q = _qualificado(**CARIMBO)
    q["qualificacao"]["score"] = 0
    assert sh.montar_linhas([q], [])[0]["prioridade_score"] == 0


def test_csv_gravado_tem_as_colunas_na_ordem_e_relido_bate(tmp_path):
    caminho = tmp_path / "qualificador_x.csv"
    sh.escrever_csv(sh.montar_linhas([_qualificado(**CARIMBO, possivel_mesmo_negocio=[])], []), str(caminho))
    with open(caminho, encoding="utf-8-sig", newline="") as f:
        leitor = csv.DictReader(f, delimiter=";")
        linhas = list(leitor)
    assert leitor.fieldnames == list(ANTIGAS + NOVAS + NOVAS_2_3_0)
    assert linhas[0]["campanha_id"] == "camp-teste" and linhas[0]["prioridade_rotulo"] == "media"
