import csv
import os

import pytest

import saida_humana as sh
import site_classificacao as sc
from test_output_json import _com_site, _emp, _qualificado, _render


# --- Montagem das linhas: DIRETA / ESPERA, e nunca NATA -----------------------------------


# --- Cidade: coluna de exibição, reserva a partir do endereço --------------------------


def test_cidade_presente_e_usada_direto():
    assert sh._cidade_para_exibicao({"cidade": "Alicante", "endereco": "qualquer coisa"}) == "Alicante"


def test_cidade_vazia_usa_reserva_do_endereco_apos_cep():
    emp = {"cidade": None, "endereco": "Calle Falsa 123, 03001 Alicante"}
    assert sh._cidade_para_exibicao(emp) == "Alicante"


def test_cidade_vazia_sem_cep_no_endereco_fica_em_branco():
    emp = {"cidade": None, "endereco": "Calle Falsa 123, sem código postal"}
    assert sh._cidade_para_exibicao(emp) == ""


def test_cidade_vazia_sem_endereco_nenhum_fica_em_branco():
    assert sh._cidade_para_exibicao({"cidade": None, "endereco": None}) == ""


def test_linha_usa_cidade_de_exibicao_no_csv():
    q = _qualificado()
    q["dados_empresa"]["cidade"] = None
    q["dados_empresa"]["endereco"] = "Gran Vía 1, 28013 Madrid"
    linhas = sh.montar_linhas([q], [])
    assert linhas[0]["cidade"] == "Madrid"


def test_qualificado_onda1_vira_direta_sem_site():
    linhas = sh.montar_linhas([_qualificado()], [])
    assert len(linhas) == 1
    assert linhas[0]["pista"] == "direta"
    assert linhas[0]["motivo"] == "sem site"
    assert linhas[0]["classe_site"] == "sem_site"


def test_onda1_nao_qualificado_nao_entra():
    q = _qualificado()
    q["status"] = "rejected"
    assert sh.montar_linhas([q], []) == []


@pytest.mark.parametrize("dominio,classe,motivo_esperado", [
    ("https://booksy.com/es/x/clinica", sc.PORTAL, "site é portal"),
    ("https://instagram.com/clinica", sc.REDE_SOCIAL, "site é rede social"),
    ("https://g.page/clinica", sc.SUPERFICIE_GOOGLE, "site é página do Google"),
    ("https://clinica.wixsite.com/inicio", sc.CONSTRUTOR, "site em construtor gratuito"),
])
def test_com_site_nao_proprio_vira_direta(dominio, classe, motivo_esperado):
    registro = _com_site(dados_empresa=_emp(website=dominio, website_status="listed"))
    linhas = sh.montar_linhas([], [registro])
    assert len(linhas) == 1
    assert linhas[0]["pista"] == "direta"
    assert linhas[0]["classe_site"] == classe
    assert linhas[0]["motivo"] == motivo_esperado


def test_site_proprio_sem_problema_e_sem_triagem_vira_espera():
    """review_count=9 (< 10) não vira candidato_triagem_visual (output_json exige >=10) e
    sem problema não vira nata -- então _lead_site() devolve None -- Espera."""
    registro = _com_site(dados_empresa=_emp(review_count=9))
    linhas = sh.montar_linhas([], [registro])
    assert len(linhas) == 1
    assert linhas[0]["pista"] == "espera"
    assert linhas[0]["motivo"] == "sem problema encontrado"
    assert linhas[0]["classe_site"] == "proprio"


def test_lead_de_nata_nunca_aparece_no_csv():
    nata = _com_site(site_renderizado=_render(mobile={"contato_visivel": False},
                                               desktop={"contato_visivel": False}))
    linhas = sh.montar_linhas([], [nata])
    assert linhas == []


def test_lead_candidato_a_triagem_nunca_aparece_no_csv():
    """review_count=120 (>=10), sem problema -- candidato à triagem, não Espera."""
    candidato = _com_site()
    linhas = sh.montar_linhas([], [candidato])
    assert linhas == []


def test_onda2_ainda_nao_analisado_nao_entra():
    pendente = _com_site(status="queued_future")
    assert sh.montar_linhas([], [pendente]) == []


# --- Ordenação --------------------------------------------------------------------------


def _direta(nome, avaliacoes, place_id=None):
    q = _qualificado()
    q["dados_empresa"]["nome"] = nome
    q["dados_empresa"]["review_count"] = avaliacoes
    q["dados_empresa"]["place_id"] = place_id or nome
    return q


def test_ordem_prioritaria_depois_resto_direta_depois_espera():
    prioritaria = _direta("A-prioritaria", avaliacoes=50, place_id="a")
    resto_mais_avaliado = _direta("B-resto-mais", avaliacoes=5, place_id="b")
    resto_menos_avaliado = _direta("C-resto-menos", avaliacoes=2, place_id="c")
    espera = _com_site(dados_empresa=_emp(review_count=9, nome="D-espera", place_id="d"))

    linhas = sh.montar_linhas(
        [resto_menos_avaliado, prioritaria, resto_mais_avaliado], [espera]
    )

    assert [l["nome"] for l in linhas] == [
        "A-prioritaria", "B-resto-mais", "C-resto-menos", "D-espera",
    ]
    assert [l["pista"] for l in linhas] == ["direta", "direta", "direta", "espera"]


def test_nota_abaixo_do_corte_nao_e_prioritaria_mesmo_com_muitas_avaliacoes():
    baixa_nota = _qualificado()
    baixa_nota["dados_empresa"]["review_count"] = 999
    baixa_nota["dados_empresa"]["nota_google"] = 3.0
    baixa_nota["dados_empresa"]["place_id"] = "baixa"
    alta = _qualificado()
    alta["dados_empresa"]["review_count"] = 10
    alta["dados_empresa"]["nota_google"] = 3.5
    alta["dados_empresa"]["place_id"] = "alta"

    linhas = sh.montar_linhas([baixa_nota, alta], [])

    # "alta" tem menos avaliações, mas é PRIORITÁRIA (nota >= 3.5); "baixa_nota" tem nota
    # abaixo do corte -- mesmo com 999 avaliações, cai no grupo 1 (resto), depois de "alta".
    assert [l["place_id"] for l in linhas] == ["alta", "baixa"]


def test_desempate_por_canais_de_contato():
    # place_id de propósito "ao contrário" do alfabeto -- se o desempate por canais for
    # removido, a ordem cai pro próximo critério (place_id) e "z_menos" viria DEPOIS de
    # "a_mais" só por coincidência alfabética; aqui é o oposto, então só passa se o
    # desempate por canais realmente decidir.
    mais_canais = _qualificado()
    mais_canais["dados_empresa"]["review_count"] = 3
    mais_canais["dados_empresa"]["place_id"] = "z_mais"
    mais_canais["dados_empresa"]["email"] = "a@a.com"  # telefone + instagram + email

    menos_canais = _qualificado()
    menos_canais["dados_empresa"]["review_count"] = 3
    menos_canais["dados_empresa"]["place_id"] = "a_menos"
    menos_canais["dados_empresa"]["instagram"] = None  # só telefone

    linhas = sh.montar_linhas([menos_canais, mais_canais], [])
    assert [l["place_id"] for l in linhas] == ["z_mais", "a_menos"]


def test_ordem_e_deterministica_entrada_igual_saida_igual():
    a = _qualificado()
    a["dados_empresa"]["place_id"] = "a"
    b = _qualificado()
    b["dados_empresa"]["place_id"] = "b"
    linhas1 = sh.montar_linhas([a, b], [])
    linhas2 = sh.montar_linhas([b, a], [])
    assert [l["place_id"] for l in linhas1] == [l["place_id"] for l in linhas2]


# --- Gravação e releitura do CSV ----------------------------------------------------------


def test_csv_relido_bate_com_o_gravado(tmp_path):
    linhas = sh.montar_linhas([_qualificado()], [])
    caminho = tmp_path / "saida" / "qualificador_teste.csv"
    sh.escrever_csv(linhas, str(caminho))

    assert caminho.is_file()
    with open(caminho, "r", encoding="utf-8-sig", newline="") as f:
        conteudo = f.read()
        assert "\ufeff" not in conteudo  # utf-8-sig: o BOM já foi consumido na decodificação
        f.seek(0)
        leitor = csv.DictReader(f, delimiter=";")
        assert leitor.fieldnames == list(sh.COLUNAS)
        relidas = list(leitor)

    assert len(relidas) == 1
    assert relidas[0]["nome"] == "Clínica X"  # acento sobrevive à volta
    assert relidas[0]["pista"] == "direta"
    assert relidas[0]["motivo"] == "sem site"
    # nenhuma coluna interna de ordenação vazou pro arquivo
    assert set(leitor.fieldnames) == set(sh.COLUNAS)


def test_csv_nao_junta_tudo_numa_coluna_e_separador_e_ponto_e_virgula(tmp_path):
    caminho = tmp_path / "s.csv"
    sh.escrever_csv(sh.montar_linhas([_qualificado()], []), str(caminho))
    primeira_linha = caminho.read_text(encoding="utf-8-sig").splitlines()[0]
    assert primeira_linha.count(";") == len(sh.COLUNAS) - 1
    assert "," not in primeira_linha.split(";")[0]  # cabeçalho não tem vírgula solta


# --- Nome de arquivo / não sobrescrever ---------------------------------------------------


def test_nome_arquivo_padrao():
    assert sh.nome_arquivo("20260923-101500") == "qualificador_20260923-101500.csv"


def test_nome_arquivo_nao_leva_numero_de_versao():
    """Decisão da supervisão (D6b, item 2): este CSV não é o contrato, então não leva
    v<versão> no nome -- evita dois números de versão diferentes na mesma pasta."""
    assert "v" not in sh.nome_arquivo("20260923-101500").split(".")[0].split("_")[-1]


def test_caminho_sem_sobrescrever_acrescenta_sufixo(tmp_path):
    (tmp_path / "qualificador_x.csv").write_text("ja existe", encoding="utf-8")
    caminho = sh.caminho_sem_sobrescrever(str(tmp_path), "qualificador_x.csv")
    assert os.path.basename(caminho) == "qualificador_x_2.csv"
    assert not os.path.exists(caminho)
    # o arquivo original continua intacto
    assert (tmp_path / "qualificador_x.csv").read_text(encoding="utf-8") == "ja existe"


def test_caminho_sem_sobrescrever_incrementa_ate_achar_livre(tmp_path):
    (tmp_path / "a.csv").write_text("1", encoding="utf-8")
    (tmp_path / "a_2.csv").write_text("2", encoding="utf-8")
    caminho = sh.caminho_sem_sobrescrever(str(tmp_path), "a.csv")
    assert os.path.basename(caminho) == "a_3.csv"


# --- LEIA-ME --------------------------------------------------------------------------


def test_escrever_leiame_cria_uma_vez_e_nao_sobrescreve(tmp_path):
    sh.escrever_leiame(str(tmp_path))
    caminho = tmp_path / sh.LEIAME_NOME
    assert caminho.is_file()
    conteudo_original = caminho.read_text(encoding="utf-8")
    assert "cópia" in conteudo_original.lower() or "copia" in conteudo_original.lower()

    caminho.write_text("editado à mão pelo operador", encoding="utf-8")
    sh.escrever_leiame(str(tmp_path))
    assert caminho.read_text(encoding="utf-8") == "editado à mão pelo operador"


# --- Cópia de conveniência: best-effort, nunca derruba a rodada ---------------------------


def test_copia_conveniencia_sem_env_nao_falha():
    ok, msg = sh.copiar_conveniencia("/qualquer/origem.csv", None)
    assert ok is False
    assert sh.ENV_COPIA_DIR in msg


def test_copia_conveniencia_com_sucesso(tmp_path):
    origem = tmp_path / "origem.csv"
    origem.write_text("conteudo", encoding="utf-8")
    destino_dir = tmp_path / "conveniencia"

    ok, destino = sh.copiar_conveniencia(str(origem), str(destino_dir))

    assert ok is True
    assert os.path.isfile(destino)
    assert open(destino, encoding="utf-8").read() == "conteudo"


def test_copia_conveniencia_com_destino_invalido_nao_derruba_a_rodada(tmp_path):
    """Destino inválido: um ARQUIVO já existe no lugar onde a pasta de destino deveria
    estar -- os.makedirs(exist_ok=True) levanta porque não dá pra criar diretório onde já
    há um arquivo. copiar_conveniencia precisa devolver (False, motivo), nunca levantar."""
    origem = tmp_path / "origem.csv"
    origem.write_text("conteudo", encoding="utf-8")
    destino_invalido = tmp_path / "isto_e_um_arquivo"
    destino_invalido.write_text("nao sou uma pasta", encoding="utf-8")

    ok, msg = sh.copiar_conveniencia(str(origem), str(destino_invalido))

    assert ok is False
    assert isinstance(msg, str) and msg  # motivo legível, não uma exceção propagada


def test_copia_conveniencia_dir_le_env(monkeypatch):
    monkeypatch.delenv(sh.ENV_COPIA_DIR, raising=False)
    assert sh.copia_conveniencia_dir() is None
    monkeypatch.setenv(sh.ENV_COPIA_DIR, "  C:\\Resultado LEADFARM  ")
    assert sh.copia_conveniencia_dir() == "C:\\Resultado LEADFARM"


def test_saida_humana_dir_fica_sob_eqc_pipeline(monkeypatch):
    """conftest.py isola TODO teste por padrão (ENV_OUTPUT_DIR sempre setada -- ver
    _isolar_persistencia_de_dados) -- então o default sem override só aparece removendo a
    env explicitamente aqui, o que também prova a precedência ao contrário do teste
    seguinte."""
    monkeypatch.delenv(sh.ENV_OUTPUT_DIR, raising=False)
    caminho = sh.saida_humana_dir().replace("\\", "/")
    assert caminho.endswith("EQC/pipeline/saidas-humanas")


def test_env_output_dir_tem_precedencia_sobre_o_default(monkeypatch, tmp_path):
    """D6b, item 2 -- prova nas duas pontas: sem a variável, cai no default sob
    eqc_root(); com ela, vence, ponto final (não é sufixo nem é ignorada)."""
    monkeypatch.delenv(sh.ENV_OUTPUT_DIR, raising=False)
    assert sh.saida_humana_dir().replace("\\", "/").endswith("EQC/pipeline/saidas-humanas")

    destino = tmp_path / "ensaio_isolado"
    monkeypatch.setenv(sh.ENV_OUTPUT_DIR, str(destino))
    assert sh.saida_humana_dir() == str(destino)


def test_env_output_dir_isola_fase_saida_da_pasta_oficial(monkeypatch, tmp_path):
    """Prova de ponta a ponta (a fim visada pelo item 2): com a variável apontando pra uma
    pasta temporária, fase_saida() não escreve NADA na pasta oficial real
    (EQC/pipeline/saidas-humanas/) -- só na pasta isolada."""
    import main as main_mod

    # conftest.py isola TODO teste por padrão (ENV_OUTPUT_DIR sempre setada) -- pra pegar o
    # caminho REAL da pasta oficial (não a isolada que o próprio conftest já armou),
    # precisa remover a env antes de perguntar. Comparado sempre contra ESTE caminho fixo
    # dali em diante, nunca chamando saida_humana_dir() de novo (que resolveria diferente
    # depois do monkeypatch.setenv abaixo).
    monkeypatch.delenv(sh.ENV_OUTPUT_DIR, raising=False)
    pasta_oficial_real = sh.saida_humana_dir()
    real_antes = set(os.listdir(pasta_oficial_real)) if os.path.isdir(pasta_oficial_real) else set()

    for nome, arquivo in [
        ("PATH_QUALIFICADOS", "qualificados.json"),
        ("PATH_COM_SITE", "com_site.json"),
        ("PATH_REPROVADOS", "reprovados.json"),
        ("PATH_IMPORT_META", "_import_meta.json"),
    ]:
        caminho = tmp_path / arquivo
        monkeypatch.setattr(main_mod, nome, str(caminho))
    monkeypatch.setattr(main_mod, "DATA_DIR", str(tmp_path))
    monkeypatch.setenv("QUALIFICADOR_OUTPUT_DIR", str(tmp_path / "_saida_contrato"))
    destino_isolado = tmp_path / "_saida_humana_isolada"
    monkeypatch.setenv(sh.ENV_OUTPUT_DIR, str(destino_isolado))
    monkeypatch.delenv(sh.ENV_COPIA_DIR, raising=False)

    main_mod.fase_saida()

    assert os.path.isdir(destino_isolado)
    assert any(n.startswith("qualificador_") for n in os.listdir(destino_isolado))
    real_depois = set(os.listdir(pasta_oficial_real)) if os.path.isdir(pasta_oficial_real) else set()
    assert real_depois == real_antes, "fase_saida() escreveu na pasta OFICIAL mesmo com a env definida"
