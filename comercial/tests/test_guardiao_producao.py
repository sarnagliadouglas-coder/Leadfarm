"""Prova nas duas pontas de `_guardiao_producao.py` (Etapa D, fechamento — passo D8).
Ver a mesma prova, mais extensa, em
qualificador/prospeccao_ia/tests/test_guardiao_producao.py -- este arquivo cobre o mínimo
que garante que a CÓPIA usada pelo COMERCIAL (conftest.py deste módulo) se comporta igual."""
import _guardiao_producao as guardiao


def _pasta_fake(tmp_path, nome="producao_fake"):
    pasta = tmp_path / nome
    pasta.mkdir()
    return pasta


def test_suite_limpa_nao_acusa(tmp_path):
    pasta = _pasta_fake(tmp_path)
    (pasta / "existente.json").write_text('{"a": 1}', encoding="utf-8")

    antes = guardiao.fotografar([("fake", pasta)])
    depois = guardiao.fotografar([("fake", pasta)])

    assert guardiao.diferencas(antes, depois) == []


def test_arquivo_criado_e_acusado_e_nomeado(tmp_path):
    pasta = _pasta_fake(tmp_path)
    antes = guardiao.fotografar([("fake", pasta)])

    (pasta / "dossie_ensaio.json").write_text("{}", encoding="utf-8")

    depois = guardiao.fotografar([("fake", pasta)])
    linhas = guardiao.diferencas(antes, depois)

    assert len(linhas) == 1
    assert "CRIADO" in linhas[0]
    assert "dossie_ensaio.json" in linhas[0]
    assert "[fake]" in linhas[0]


def test_pasta_de_producao_ausente_conta_como_vazia_nao_levanta(tmp_path):
    assert guardiao.fotografar([("fake", tmp_path / "nunca_existiu")]) == {}


def test_mensagem_de_falha_inclui_todas_as_linhas():
    linhas = ["CRIADO   [fake] a.json (10 bytes)"]
    msg = guardiao.mensagem_de_falha(linhas)
    assert "a.json" in msg and "PRODUÇÃO" in msg


def test_guardiao_fotografa_eqc_config_onde_vive_a_campanha_ativa():
    """Etapa 2 (diretor, 06/10/2026): EQC/config (campanha ativa e campanhas prontas)
    entra na lista de pastas de produção vigiadas -- ao lado de pipeline e contracts."""
    import eqc
    from conftest import _pastas_producao

    pastas = dict(_pastas_producao())
    assert pastas["EQC/config"] == eqc.eqc_root() / "config"
    assert {"EQC/pipeline", "EQC/contracts"} <= set(pastas)


def test_alteracao_na_campanha_e_acusada(tmp_path):
    """Controle: mudar o conteúdo (tamanho) de um campanha_ativa.json é acusado."""
    pasta = _pasta_fake(tmp_path, "config")
    arquivo = pasta / "campanha_ativa.json"
    arquivo.write_text('{"cidade": "Alicante"}', encoding="utf-8")
    antes = guardiao.fotografar([("EQC/config", pasta)])
    arquivo.write_text('{"cidade": "Elche, España"}', encoding="utf-8")
    linhas = guardiao.diferencas(antes, guardiao.fotografar([("EQC/config", pasta)]))
    assert len(linhas) == 1 and "campanha_ativa.json" in linhas[0]
