"""Prova nas duas pontas de `_guardiao_producao.py` (Etapa D, fechamento — passo D8):
um arquivo criado numa pasta "de produção" (aqui, uma pasta fake sob tmp_path -- nunca a
pasta real, por segurança) tem de ser acusado, nomeado; nada mudando, o guardião tem de
ficar quieto. Os testes exercitam `fotografar`/`diferencas`/`mensagem_de_falha`
diretamente -- são as MESMAS funções que `conftest.py` liga ao ciclo de vida real da
sessão do pytest; não há lógica adicional escondida na fixture."""
import _guardiao_producao as guardiao


def _pasta_fake(tmp_path, nome="producao_fake"):
    pasta = tmp_path / nome
    pasta.mkdir()
    return pasta


# --- Controle negativo: nada muda, guardião fica quieto -----------------------------------


def test_suite_limpa_nao_acusa(tmp_path):
    pasta = _pasta_fake(tmp_path)
    (pasta / "existente.json").write_text('{"a": 1}', encoding="utf-8")

    antes = guardiao.fotografar([("fake", pasta)])
    depois = guardiao.fotografar([("fake", pasta)])  # nada mudou entre as duas fotos

    assert guardiao.diferencas(antes, depois) == []


def test_pasta_de_producao_ausente_conta_como_vazia_nao_levanta(tmp_path):
    pasta_inexistente = tmp_path / "nunca_existiu"
    foto = guardiao.fotografar([("fake", pasta_inexistente)])
    assert foto == {}


# --- Prova positiva: arquivo criado de propósito é acusado, nomeado -----------------------


def test_arquivo_criado_e_acusado_e_nomeado(tmp_path):
    pasta = _pasta_fake(tmp_path)
    antes = guardiao.fotografar([("fake", pasta)])

    (pasta / "ensaio_esquecido.csv").write_text("pista;motivo\n", encoding="utf-8")

    depois = guardiao.fotografar([("fake", pasta)])
    linhas = guardiao.diferencas(antes, depois)

    assert len(linhas) == 1
    assert "CRIADO" in linhas[0]
    assert "ensaio_esquecido.csv" in linhas[0]
    assert "[fake]" in linhas[0]


def test_arquivo_criado_em_subpasta_tambem_e_acusado(tmp_path):
    """Cobre 'EQC/pipeline/ inteira, incluindo subpastas' -- saidas-humanas/,
    qualificador-output/ etc. são subpastas de EQC/pipeline/."""
    pasta = _pasta_fake(tmp_path)
    (pasta / "subpasta").mkdir()
    antes = guardiao.fotografar([("fake", pasta)])

    (pasta / "subpasta" / "novo.csv").write_text("x", encoding="utf-8")

    depois = guardiao.fotografar([("fake", pasta)])
    linhas = guardiao.diferencas(antes, depois)

    assert len(linhas) == 1
    assert "subpasta/novo.csv" in linhas[0] or "subpasta\\novo.csv" in linhas[0]


def test_arquivo_apagado_e_acusado():
    antes = {("fake", "sumiu.json"): 10}
    depois = {}
    linhas = guardiao.diferencas(antes, depois)
    assert len(linhas) == 1
    assert "APAGADO" in linhas[0] and "sumiu.json" in linhas[0]


def test_arquivo_alterado_de_tamanho_e_acusado(tmp_path):
    pasta = _pasta_fake(tmp_path)
    alvo = pasta / "mutavel.json"
    alvo.write_text("{}", encoding="utf-8")
    antes = guardiao.fotografar([("fake", pasta)])

    alvo.write_text('{"campo": "valor bem mais comprido do que antes"}', encoding="utf-8")

    depois = guardiao.fotografar([("fake", pasta)])
    linhas = guardiao.diferencas(antes, depois)

    assert len(linhas) == 1
    assert "ALTERADO" in linhas[0] and "mutavel.json" in linhas[0]


def test_arquivo_diminuido_de_tamanho_tambem_e_acusado(tmp_path):
    """Não só crescimento -- um arquivo que ENCOLHE também é uma alteração real."""
    pasta = _pasta_fake(tmp_path)
    alvo = pasta / "encolheu.json"
    alvo.write_text('{"campo": "valor bem comprido que vai sumir"}', encoding="utf-8")
    antes = guardiao.fotografar([("fake", pasta)])

    alvo.write_text("{}", encoding="utf-8")

    depois = guardiao.fotografar([("fake", pasta)])
    linhas = guardiao.diferencas(antes, depois)

    assert len(linhas) == 1
    assert "ALTERADO" in linhas[0] and "encolheu.json" in linhas[0]


def test_arquivo_reescrito_com_mesmo_tamanho_escapa_por_design():
    """Limitação DECLARADA, não bug: o guardião compara só nome+tamanho (requisito
    explícito -- 'fotografar nome e tamanho basta, não é preciso ler conteúdo'). Um
    arquivo reescrito com o MESMO número de bytes não aparece como diferença. Registrado
    aqui pra não virar surpresa depois."""
    antes = {("fake", "estavel.json"): 42}
    depois = {("fake", "estavel.json"): 42}
    assert guardiao.diferencas(antes, depois) == []


def test_multiplas_pastas_distinguidas_pelo_rotulo(tmp_path):
    pasta_a = _pasta_fake(tmp_path, "pasta_a")
    pasta_b = _pasta_fake(tmp_path, "pasta_b")
    antes = guardiao.fotografar([("A", pasta_a), ("B", pasta_b)])

    (pasta_b / "vazou.csv").write_text("x", encoding="utf-8")

    depois = guardiao.fotografar([("A", pasta_a), ("B", pasta_b)])
    linhas = guardiao.diferencas(antes, depois)

    assert len(linhas) == 1
    assert "[B]" in linhas[0] and "[A]" not in linhas[0]


def test_mensagem_de_falha_inclui_todas_as_linhas():
    linhas = ["CRIADO   [fake] a.csv (10 bytes)", "APAGADO  [fake] b.csv (era 5 bytes)"]
    msg = guardiao.mensagem_de_falha(linhas)
    assert "a.csv" in msg and "b.csv" in msg
    assert "PRODUÇÃO" in msg
