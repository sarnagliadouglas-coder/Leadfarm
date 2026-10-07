"""Erro do import em linguagem clara (Tarefa 3, diretor 06/10/2026): `main.run` com `--csv`.
Caso previsto => mensagem curta, log com o traceback, código de saída != 0 e nada gravado.
Erro inesperado => sobe como erro, também com log. Campanhas em tmp_path; cidade conferida na
lista oficial do INE versionada (`config/municipios_ine.json`). Dados de lead fictícios."""
import json
import os
import sys

import pytest

import agent_coletor
import campanha
import csv_contrato
import erro_import
import main as main_mod
import municipios

HEADER = list(csv_contrato.COLUNAS_OBRIGATORIAS_V1)

PSI = {"id": "psi-t", "nicho": "Psicólogos", "cidade_padrao": "Alicante",
       "categorias_aceitas": ["psicolog"], "categorias_excluidas": [], "termos_de_busca": ["psicolog"]}
ABO = {"id": "abo-t", "nicho": "Abogados", "cidade_padrao": "Alicante",
       "categorias_aceitas": ["abogad"], "categorias_excluidas": [], "termos_de_busca": ["abogad"]}


@pytest.fixture
def ambiente(tmp_path, monkeypatch):
    pasta = tmp_path / "campanhas"
    pasta.mkdir()
    for c in (PSI, ABO):
        (pasta / f"{c['id']}.json").write_text(json.dumps(c), encoding="utf-8")
    ativa = tmp_path / "campanha_ativa.json"
    ativa.write_text(json.dumps(PSI), encoding="utf-8")
    monkeypatch.setenv(campanha.ENV_DIR_CAMPANHAS, str(pasta))
    monkeypatch.setenv(campanha.ENV_CAMINHO, str(ativa))
    monkeypatch.delenv(municipios.ENV_CAMINHO, raising=False)
    monkeypatch.setattr(main_mod, "LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.setattr(main_mod.env_loader, "carregar_env", lambda: [])
    return {"tmp": tmp_path, "pasta": pasta, "ativa": ativa, "logs": tmp_path / "logs"}


def _csv(tmp_path, meta, colunas=HEADER, nome="extrator_teste_v1.csv", bruto=None):
    def fmt(vals):
        return ",".join('"' + v.replace('"', '""') + '"' for v in vals)
    linha = {c: "" for c in colunas}
    linha.update({"Name": "Consulta Ficticia", "Categories": "Psicólogo", "Place Id": "pid-x",
                  "Email": "contacto@ficticio.es"})
    caminho = tmp_path / nome
    if bruto is not None:
        caminho.write_bytes(bruto)
    else:
        caminho.write_text(fmt(colunas) + "\n" + fmt([linha[c] for c in colunas]) + "\n", encoding="utf-8-sig")
    if meta is not None:
        (tmp_path / (nome[:-4] + ".meta.json")).write_text(json.dumps(meta), encoding="utf-8")
    return caminho


def _meta(termo):
    return {"schema_version": 2, "termo_busca": termo, "termo_busca_origem": "url" if termo else "ausente"}


def _rodar(monkeypatch, csv_path):
    """Roda o CLI como o operador: devolve o código de saída (None = terminou normal)."""
    monkeypatch.setattr(sys, "argv", ["main.py", "--csv", str(csv_path)])
    try:
        main_mod.run()
    except SystemExit as e:
        return e.code
    return None


def _nada_gravado():
    return not any(os.path.exists(p) for p in (main_mod.PATH_COLETADOS, main_mod.PATH_COM_SITE,
                                                main_mod.PATH_REPROVADOS, main_mod.PATH_IMPORT_META))


CASOS = [
    ("nenhuma", _meta("dentista murcia"), {},
     ["nenhuma campanha pronta tem o nicho dessa busca", 'Termo da busca: "dentista murcia"',
      'Psicólogos (psi-t)  ->  exemplo de busca: "psicólogos alicante"',
      'Abogados (abo-t)  ->  exemplo de busca: "abogados alicante"']),
    ("cidade_nao_reconhecida", _meta("psicólogo murcai"), {},
     ["cidade não reconhecida -- não é um município da lista oficial do INE",
      'Termo da busca: "psicólogo murcai"', 'Cidade lida no termo: "murcai"',
      'Psicólogos (psi-t)  ->  exemplo de busca: "psicólogos alicante"']),
    ("sem_cidade", _meta("psicólogo"), {},
     ["cidade não reconhecida -- o termo da busca não traz cidade, só o nicho.",
      "Cidade lida no termo: (nenhuma)",
      'Psicólogos (psi-t)  ->  exemplo de busca: "psicólogos alicante"']),
    ("municipio_ambiguo", _meta("psicólogo torrent"), {},
     ["esse nome é de mais de um município", "Torrent (INE 17197)", "Torrent (INE 46244)",
      "avise quem cuida da configuração"]),
    ("mais_de_uma", _meta("psicólogo abogado murcia"), {},
     ["a busca casa com mais de uma campanha", "psi-t", "abo-t"]),
    ("meta_incoerente", {"schema_version": 2, "termo_busca": None, "termo_busca_origem": "url"}, {},
     ["não está no formato do extrator", "incoerente"]),
    ("contrato_csv", {"schema_version": 1}, {"colunas": [c for c in HEADER if c != "Owner"]},
     ["não está no formato do extrator", "Owner"]),
    ("csv_ilegivel", {"schema_version": 1}, {"bruto": b"\x81\x8d\x8f\x90\x9d\xff\xfe"},
     ["o CSV não pôde ser lido", "não pôde ser lido:", "extraia a lista de novo"]),
]


@pytest.mark.parametrize("nome,meta,extra,trechos", CASOS, ids=[c[0] for c in CASOS])
def test_caso_previsto_mostra_mensagem_curta_sai_com_erro_e_grava_log(ambiente, monkeypatch, capsys,
                                                                       nome, meta, extra, trechos):
    codigo = _rodar(monkeypatch, _csv(ambiente["tmp"], meta, **extra))
    err = capsys.readouterr().err
    assert codigo == erro_import.CODIGO_SAIDA and codigo != 0
    assert "O IMPORT PAROU -- nada foi gravado." in err and "O que fazer:" in err
    for t in trechos:
        assert t in err, t
    assert "Traceback" not in err  # o técnico vai para o log, não para a tela
    [log] = list(ambiente["logs"].iterdir())
    assert f"Detalhe técnico: {log}" in err
    assert "Traceback" in log.read_text(encoding="utf-8")
    assert _nada_gravado()


def test_termo_sem_cidade_nao_diz_que_a_cidade_nao_e_municipio(ambiente, monkeypatch, capsys):
    """Termo só com o nicho: a mensagem diz que não há cidade, não que "não é município do
    INE"; controle: com uma cidade errada, é o contrário."""
    _rodar(monkeypatch, _csv(ambiente["tmp"], _meta("psicólogo")))
    sem = capsys.readouterr().err
    assert "não traz cidade" in sem and "não é um município" not in sem
    _rodar(monkeypatch, _csv(ambiente["tmp"], _meta("psicólogo murcai"), nome="extrator_outro_v1.csv"))
    errada = capsys.readouterr().err
    assert "não é um município da lista oficial do INE" in errada and "não traz cidade" not in errada


def test_arquivo_inexistente_para_com_mensagem_e_codigo(ambiente, monkeypatch, capsys):
    """Sugestão 2 aprovada (06/10/2026): antes saía com código 0 e só imprimia '[Erro]'."""
    codigo = _rodar(monkeypatch, ambiente["tmp"] / "nao_existe.csv")
    err = capsys.readouterr().err
    assert codigo == erro_import.CODIGO_SAIDA
    assert "o CSV não pôde ser lido" in err and "Arquivo não encontrado" in err
    assert _nada_gravado()


def test_erro_de_programa_na_leitura_nao_vira_csv_ilegivel(ambiente, monkeypatch, capsys):
    """Controle negativo da sugestão 2: só erro de LEITURA (decodificação, CSV malformado,
    acesso) vira "CSV ilegível". Defeito do código continua erro inesperado, com log."""
    def defeito(self, caminho, campanha=None, cidade=None):
        raise KeyError("defeito fictício de teste")
    monkeypatch.setattr(agent_coletor.AgentColetor, "coletar_leads_de_csv", defeito)
    monkeypatch.setattr(sys, "argv", ["main.py", "--csv", str(_csv(ambiente["tmp"], {"schema_version": 1}))])
    with pytest.raises(KeyError):
        main_mod.run()
    err = capsys.readouterr().err
    assert "Erro inesperado" in err and "O IMPORT PAROU" not in err
    assert _nada_gravado()


def test_campanha_ativa_invalida_sem_termo_aponta_o_atalho(ambiente, monkeypatch, capsys):
    ambiente["ativa"].unlink()
    codigo = _rodar(monkeypatch, _csv(ambiente["tmp"], _meta(None)))
    err = capsys.readouterr().err
    assert codigo == erro_import.CODIGO_SAIDA
    assert "campanha ativa do menu está ausente ou com problema" in err and "Trocar-campanha.bat" in err
    assert _nada_gravado()


def test_lista_do_ine_ausente_aponta_a_configuracao(ambiente, monkeypatch, capsys):
    monkeypatch.setenv(municipios.ENV_CAMINHO, str(ambiente["tmp"] / "sem_lista.json"))
    codigo = _rodar(monkeypatch, _csv(ambiente["tmp"], _meta("psicólogo murcia")))
    err = capsys.readouterr().err
    assert codigo == erro_import.CODIGO_SAIDA and "lista oficial de municípios do INE" in err
    assert _nada_gravado()


def test_import_que_funciona_nao_sai_com_erro_nem_grava_log(ambiente, monkeypatch, capsys):
    """Controle negativo dos casos acima: termo bom => importa, sem mensagem de parada nem log."""
    codigo = _rodar(monkeypatch, _csv(ambiente["tmp"], _meta("psicólogo murcia")))
    assert codigo is None
    assert "O IMPORT PAROU" not in capsys.readouterr().err
    assert not ambiente["logs"].exists()
    assert not _nada_gravado()


def test_erro_inesperado_nao_e_mascarado_e_tambem_vai_para_o_log(ambiente, monkeypatch, capsys):
    def explode(_caminho):
        raise RuntimeError("falha fictícia de teste")
    monkeypatch.setattr(main_mod, "importar_csv", explode)
    monkeypatch.setattr(sys, "argv", ["main.py", "--csv", "qualquer.csv"])
    with pytest.raises(RuntimeError, match="falha fictícia de teste"):
        main_mod.run()
    err = capsys.readouterr().err
    assert "Erro inesperado" in err and "O IMPORT PAROU" not in err
    [log] = list(ambiente["logs"].iterdir())
    assert "RuntimeError" in log.read_text(encoding="utf-8")


def test_comando_sem_import_nao_passa_pelo_tratamento(ambiente, monkeypatch):
    """Sem --csv, o erro sobe sem log (o tratamento é só do import)."""
    monkeypatch.setattr(main_mod, "fase_gbp", lambda: (_ for _ in ()).throw(RuntimeError("x")))
    monkeypatch.setattr(sys, "argv", ["main.py", "gbp"])
    with pytest.raises(RuntimeError):
        main_mod.run()
    assert not ambiente["logs"].exists()


def test_termo_sugerido_so_quando_escolhe_a_propria_campanha_e_um_municipio(ambiente):
    sem_raiz_no_nome = {**PSI, "id": "ter-t", "nicho": "Terapeutas"}
    cidade_invalida = {**PSI, "cidade_padrao": "Cidade Ficticia"}
    assert erro_import.termo_sugerido(PSI, [PSI, ABO]) == "psicólogos alicante"
    assert erro_import.termo_sugerido(sem_raiz_no_nome, [sem_raiz_no_nome, ABO]) is None
    assert erro_import.termo_sugerido(cidade_invalida, [cidade_invalida, ABO]) is None
    # duas campanhas com a mesma raiz: o exemplo escolheria as duas -> não sugere
    assert erro_import.termo_sugerido(PSI, [PSI, {**PSI, "id": "psi-2"}]) is None
    # o nome do nicho casa com as raízes de OUTRA campanha: o exemplo levaria à outra -> não sugere
    raiz_diferente = {**PSI, "id": "ter-t", "termos_de_busca": ["terapeut"]}
    assert erro_import.termo_sugerido(raiz_diferente, [raiz_diferente, PSI]) is None


def test_mensagem_recusa_erro_nao_previsto():
    with pytest.raises(TypeError):
        erro_import.mensagem(RuntimeError("x"), "log")
