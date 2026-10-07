"""Linha deslocada com os marcadores novos (config/linha_deslocada.json), observados no CSV de
abogados de Alicante em 04/10/2026: glifo de ícone (caractere de uso privado, U+E934) ou texto
de horário ("Apertura: 9:00 (lun)") no lugar da categoria, categoria real em
Fulladdress/Street, Municipality vazio. Só a FORMA do deslocamento é real; nome, telefone,
site, endereço e place_id são fictícios."""
import json

import pytest

import agent_coletor
import csv_contrato
import main as main_mod
from agent_coletor import AgentColetor

HEADER = list(csv_contrato.COLUNAS_OBRIGATORIAS_V1)
GLIFO = ""


def _linha_integra(**over):
    d = {c: "" for c in HEADER}
    d.update({"Name": "Despacho Ficticio", "Phone": "600000001", "Phones": "600000001",
              "Website": "https://despacho-ficticio.es/", "Domain": "despacho-ficticio.es",
              "Fulladdress": "C. Ficticia, 10, 03001 Alicante (Alacant), Alicante",
              "Street": "C. Ficticia, 10", "Municipality": "03001 Alicante (Alacant), Alicante",
              "Categories": "Abogado", "Review Count": "40", "Average Rating": "4.7",
              "Place Id": "pid-integra"})
    d.update(over)
    return d


def _linha_deslocada(marcador=GLIFO, categoria_real="Abogado especialista en derecho de extranjería", **over):
    """Forma real: categoria em Fulladdress/Street, Municipality vazio, marcador em
    Categories; telefone, site, avaliações e nota NO LUGAR CERTO."""
    d = _linha_integra(Name="Abogados Ficticios", Fulladdress=categoria_real, Street=categoria_real[:30],
                       Municipality="", Categories=marcador, **{"Review Count": "65", "Average Rating": "4.9",
                                                                 "Place Id": "pid-deslocada"})
    d.update(over)
    return d


# --- detecção -----------------------------------------------------------------------------

@pytest.mark.parametrize("categoria,esperado", [
    (GLIFO, "caractere_uso_privado"),
    ("Apertura: 9:00 (lun)", "marcador_config"),
    ("Cierra: 20:30", "marcador_config"),
    ("No hay reseñas", "sem_avaliacao"),
    ("Abogado", None),                 # controle: categoria normal
    ("Cerrajero", None),               # controle: palavra parecida, sem horário
    ("Abierto al público", None),      # controle: sem hh:mm
])
def test_padrao_de_linha_deslocada(categoria, esperado):
    assert agent_coletor.padrao_de_linha_deslocada(categoria) == esperado


# --- recuperação (mesmo mecanismo de "No hay reseñas") --------------------------------------

@pytest.mark.parametrize("marcador", [GLIFO, "Apertura: 9:00 (lun)"])
def test_categoria_recuperada_e_campos_preservados(marcador):
    lead = AgentColetor._montar_lead(_linha_deslocada(marcador))
    assert lead["nicho"] == "Abogado especialista en derecho de extranjería"
    assert lead["endereco"] is None                       # o que estava ali era a categoria
    assert lead["telefone"] == "600000001"
    assert lead["website"] == "https://despacho-ficticio.es/"
    assert lead["review_count"] == 65 and lead["nota_google"] == 4.9
    assert lead["linha_deslocada"] == {"padrao": agent_coletor.padrao_de_linha_deslocada(marcador),
                                       "categoria_recuperada": True, "campos_suspeitos": []}


def test_linha_integra_nao_e_mexida():
    """Controle negativo: linha normal não ganha marca nem perde endereço."""
    lead = AgentColetor._montar_lead(_linha_integra())
    assert lead["nicho"] == "Abogado"
    assert lead["endereco"].startswith("C. Ficticia, 10")
    assert "linha_deslocada" not in lead


def test_sem_avaliacao_com_review_count_deslocado_nao_e_suspeito():
    """Na forma antiga, Review Count também vem com o texto "sem avaliação" -- é o
    deslocamento conhecido, não um campo trocado."""
    lead = AgentColetor._montar_lead(_linha_deslocada("No hay reseñas", **{"Review Count": "Nohayreseñas",
                                                                             "Average Rating": ""}))
    assert lead["linha_deslocada"]["campos_suspeitos"] == []
    assert lead["review_count"] is None


@pytest.mark.parametrize("campo,valor,esperado", [
    ("Review Count", "C. Ficticia", "avaliacoes"),
    ("Average Rating", "Abogado", "nota"),
    ("Average Rating", "65", "nota"),
    ("Website", "Abogado", "website"),
    ("Phone", "Calle Ficticia", "telefone"),
])
def test_campo_com_forma_errada_e_marcado(campo, valor, esperado):
    lead = AgentColetor._montar_lead(_linha_deslocada(**{campo: valor}))
    assert esperado in lead["linha_deslocada"]["campos_suspeitos"]


# --- corte -----------------------------------------------------------------------------------

def test_irrecuperavel_vai_para_reprovados_com_motivo_proprio():
    leads = [AgentColetor._montar_lead(_linha_deslocada(Fulladdress="C/ Mayor, 12", Street="C/ Mayor")),
             AgentColetor._montar_lead(_linha_deslocada(**{"Review Count": "C. Ficticia", "Place Id": "p2"})),
             AgentColetor._montar_lead(_linha_deslocada(**{"Place Id": "p3"})),
             AgentColetor._montar_lead(_linha_integra())]
    aprovados, reprovados = AgentColetor._aplicar_filtro_linha_deslocada(leads)
    assert [l["place_id"] for l in aprovados] == ["p3", "pid-integra"]
    assert [l["rejection_reason"] for l in reprovados] == [agent_coletor.MOTIVO_LINHA_DESLOCADA] * 2
    assert reprovados[0]["rejection_detail"]["categoria_recuperada"] is False
    assert reprovados[1]["rejection_detail"]["campos_suspeitos"] == ["avaliacoes"]


def _csv(tmp_path, linhas):
    def fmt(d):
        return ",".join('"' + d[c].replace('"', '""') + '"' for c in HEADER)
    caminho = tmp_path / "extrator_desloc_v1.csv"
    caminho.write_text("\n".join([",".join(f'"{c}"' for c in HEADER)] + [fmt(l) for l in linhas]) + "\n",
                       encoding="utf-8-sig")
    (tmp_path / "extrator_desloc_v1.meta.json").write_text(json.dumps({"schema_version": 1}), encoding="utf-8")
    return caminho


def test_import_recupera_advogado_deslocado_e_reprova_o_irrecuperavel(tmp_path, monkeypatch, capsys):
    campanha = tmp_path / "abogados.json"
    campanha.write_text(json.dumps({"id": "abog-teste", "nicho": "Abogados", "cidade_padrao": "Cidade Ficticia",
                                    "categorias_aceitas": ["abogad", "servicios legales", "bufete", "gestor"],
                                    "categorias_excluidas": []}), encoding="utf-8")
    monkeypatch.setenv("QUALIFICADOR_CAMPANHA", str(campanha))
    linhas = [
        _linha_deslocada(GLIFO, **{"Place Id": "a1", "Phone": "600000011"}),
        _linha_deslocada("Apertura: 9:00 (lun)", "Abogado especializado en quiebras y concursos",
                         **{"Place Id": "a2", "Phone": "600000012", "Website": "https://a2-ficticio.es/"}),
        _linha_deslocada(GLIFO, Fulladdress="C/ Mayor, 12", Street="C/ Mayor",
                         **{"Place Id": "a3", "Phone": "600000013", "Website": "https://a3-ficticio.es/"}),
        _linha_integra(**{"Place Id": "a4", "Phone": "600000014", "Website": "https://a4-ficticio.es/"}),
    ]
    main_mod.importar_csv(str(_csv(tmp_path, linhas)))

    ativos = {r["dados_empresa"]["place_id"]: r["dados_empresa"]
              for r in main_mod.carregar_json(main_mod.PATH_COM_SITE) + main_mod.carregar_json(main_mod.PATH_COLETADOS)}
    reprovados = {r["dados_empresa"]["place_id"]: r for r in main_mod.carregar_json(main_mod.PATH_REPROVADOS)}
    assert set(ativos) == {"a1", "a2", "a4"}
    assert ativos["a1"]["nicho"].startswith("Abogado especialista")
    assert set(reprovados) == {"a3"}
    assert reprovados["a3"]["rejection_reason"] == "linha_deslocada_irrecuperavel"
    out = capsys.readouterr().out
    assert "reprovados por linha_deslocada_irrecuperavel: 1" in out
    assert "OK" in out.split("Confere")[1].splitlines()[0]
