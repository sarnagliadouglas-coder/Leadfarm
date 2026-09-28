"""Portabilidade da integração com o EQC (LeadFarm).

Garante que `contrato.py` não fixa nenhum caminho absoluto de máquina e que a raiz
do EQC é resolvida por env var ou por descoberta na árvore de diretórios -- de modo
a continuar funcionando depois que o QUALIFICADOR virar
`.../Projetos/LeadFarm/QUALIFICADOR` com o EQC em `.../Projetos/LeadFarm/EQC`.
"""
from pathlib import Path

import contrato

_ENV_EQC = (
    "QUALIFICADOR_CONTRACT_SCHEMA",
    "QUALIFICADOR_OUTPUT_DIR",
    "QUALIFICADOR_EQC_ROOT",
    "LEADFARM_ROOT",
)


def _limpar_env(monkeypatch):
    for k in _ENV_EQC:
        monkeypatch.delenv(k, raising=False)


def _fake_eqc(base: Path) -> Path:
    """Cria `<base>/EQC/contracts/leads_qualificados.schema.json`. Devolve `<base>/EQC`."""
    contracts = base / "EQC" / "contracts"
    contracts.mkdir(parents=True)
    (contracts / "leads_qualificados.schema.json").write_text("{}", encoding="utf-8")
    return base / "EQC"


def test_modulo_nao_tem_caminho_absoluto_de_maquina():
    fonte = Path(contrato.__file__).read_text(encoding="utf-8")
    assert "C:\\Users\\Douglas Sarnaglia" not in fonte
    assert "\\Desktop\\EQC" not in fonte
    assert "/Desktop/EQC" not in fonte
    # os nomes retrocompat continuam existindo (CLAUDE.md os cita)
    assert isinstance(contrato.CONTRACT_SCHEMA_DEFAULT, str)
    assert isinstance(contrato.OUTPUT_DIR_DEFAULT, str)


def test_env_de_caminho_final_tem_precedencia(monkeypatch, tmp_path):
    _limpar_env(monkeypatch)
    monkeypatch.setenv("LEADFARM_ROOT", str(tmp_path / "ignorado"))
    alvo_schema = tmp_path / "x" / "schema.json"
    alvo_out = tmp_path / "y"
    monkeypatch.setenv("QUALIFICADOR_CONTRACT_SCHEMA", str(alvo_schema))
    monkeypatch.setenv("QUALIFICADOR_OUTPUT_DIR", str(alvo_out))
    assert contrato.contract_schema_path() == str(alvo_schema)
    assert contrato.output_dir() == str(alvo_out)


def test_leadfarm_root_resolve_o_eqc(monkeypatch, tmp_path):
    _limpar_env(monkeypatch)
    monkeypatch.setenv("LEADFARM_ROOT", str(tmp_path))
    assert contrato.eqc_root() == tmp_path / "EQC"
    assert contrato.contract_schema_path() == str(
        tmp_path / "EQC" / "contracts" / "leads_qualificados.schema.json")
    assert contrato.output_dir() == str(
        tmp_path / "EQC" / "pipeline" / "qualificador-output")


def test_qualificador_eqc_root_vence_leadfarm_root(monkeypatch, tmp_path):
    _limpar_env(monkeypatch)
    monkeypatch.setenv("LEADFARM_ROOT", str(tmp_path / "ecossistema"))
    monkeypatch.setenv("QUALIFICADOR_EQC_ROOT", str(tmp_path / "eqc-explicito"))
    assert contrato.eqc_root() == tmp_path / "eqc-explicito"


def test_descoberta_layout_futuro_leadfarm(monkeypatch, tmp_path):
    _limpar_env(monkeypatch)
    leadfarm = tmp_path / "Projetos" / "LeadFarm"
    eqc = _fake_eqc(leadfarm)
    repo = leadfarm / "QUALIFICADOR" / "algum" / "subdir"
    repo.mkdir(parents=True)
    monkeypatch.setattr(contrato, "_REPO_DIR", repo)
    assert contrato.eqc_root() == eqc


def test_descoberta_layout_atual(monkeypatch, tmp_path):
    _limpar_env(monkeypatch)
    desktop = tmp_path / "Desktop"
    eqc = _fake_eqc(desktop)
    repo = desktop / "Projeto comercial" / "prospeccao_ia"
    repo.mkdir(parents=True)
    monkeypatch.setattr(contrato, "_REPO_DIR", repo)
    assert contrato.eqc_root() == eqc


def test_fallback_modulos_irmaos_quando_nada_encontrado(monkeypatch, tmp_path):
    _limpar_env(monkeypatch)
    repo = tmp_path / "solto" / "QUALIFICADOR"
    repo.mkdir(parents=True)
    monkeypatch.setattr(contrato, "_REPO_DIR", repo)
    assert contrato.eqc_root() == repo.parent / "EQC"


def test_schema_e_saida_sob_a_mesma_raiz_de_eqc(monkeypatch, tmp_path):
    _limpar_env(monkeypatch)
    monkeypatch.setenv("LEADFARM_ROOT", str(tmp_path))
    p_schema = Path(contrato.contract_schema_path())
    p_out = Path(contrato.output_dir())
    assert p_schema.parents[1] == tmp_path / "EQC"
    assert p_out.parents[1] == tmp_path / "EQC"


def test_maquina_atual_ainda_resolve_o_schema_real(monkeypatch):
    """Sem nenhuma env var, a descoberta tem que achar o EQC real desta máquina --
    senão a suíte inteira aborta (tests/conftest.py)."""
    _limpar_env(monkeypatch)
    assert Path(contrato.contract_schema_path()).is_file()
