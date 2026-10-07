"""Campanha -- lida no import, carimbada em cada lead, fonte das categorias aceitas.

Uma campanha por NICHO (multicidade, diretor 06/10/2026): as campanhas prontas vivem em
`<eqc_root>/config/campanhas/` e a ativa do menu em `<eqc_root>/config/campanha_ativa.json`
(camada compartilhada; formato e local em `EQC/INDEX.md`). Sem caminho absoluto de máquina:
a raiz vem de `contrato.eqc_root()`; as env `QUALIFICADOR_CAMPANHA` (arquivo ativo) e
`QUALIFICADOR_CAMPANHAS_DIR` (pasta) existem só para teste.

Campos mínimos: `id`, `nicho` (rótulo humano), `cidade_padrao` (cidade usada SÓ em lista
sem termo de busca), `categorias_aceitas` (lista com pelo menos um termo),
`categorias_excluidas` (lista, pode ser vazia). Opcional: `termos_de_busca` (raízes do nicho
no termo da busca do Maps; se presente, lista com pelo menos um termo) -- campanha sem ele
só é escolhida pelo menu. Campos extras são aceitos e ignorados aqui.

Arquivo ausente, JSON inválido ou campo mínimo faltando/errado => `CampanhaInvalidaError`,
levantado ANTES de o import gravar qualquer coisa (main.importar_csv). $0, sem LLM.

Escolha no import -- `escolher_campanha`:
- o sidecar do EXTRATOR traz `termo_busca` ("<nicho> <cidade>") => a campanha é a ÚNICA de
  `campanhas/` cujas raízes aparecem no termo (contidas, sem acento e sem maiúscula); a
  cidade é o que SOBRA do termo depois de tirar as palavras do nicho (as que contêm uma
  raiz) e um "en" solto no início (decisão do diretor, 06/10/2026), e só vale se for um
  município da lista oficial do INE (`municipios.py`), gravado na grafia oficial da forma
  digitada. Nenhuma campanha, mais de uma, cidade não reconhecida, sobra vazia ou mais de
  um município possível => `CampanhaPorTermoError`, e o import para antes de gravar.
  Campanha do termo diferente da ativa do menu => vale a do termo, com aviso;
- sem termo (lista antiga, meta v1 ou sem meta) => a campanha ativa do menu, com a
  `cidade_padrao` dela, mostradas em destaque.
"""
import json
import os
import unicodedata

import contrato
import municipios

ENV_CAMINHO = "QUALIFICADOR_CAMPANHA"
_CAMPANHA_REL = ("config", "campanha_ativa.json")
# Pasta das campanhas prontas (menu do atalho e escolha pelo termo). Env SÓ PARA TESTE.
ENV_DIR_CAMPANHAS = "QUALIFICADOR_CAMPANHAS_DIR"
_CAMPANHAS_REL = ("config", "campanhas")

MOTIVO_FORA_DO_PERFIL = "icp_categoria_fora_do_perfil"
MOTIVO_EXCLUIDA = "icp_categoria_excluida"

ORIGEM_TERMO = "termo_busca"
ORIGEM_MENU = "menu"

# Palavra solta tirada do início da sobra antes de procurar o município ("psicólogo en murcia").
_CONECTOR_INICIAL = "en"


class CampanhaInvalidaError(Exception):
    """Campanha ativa ausente ou inválida. Falha alta: o import não grava nada."""


class CampanhaPorTermoError(CampanhaInvalidaError):
    """O termo da busca não aponta para exatamente uma campanha e um município. Falha alta:
    o import não grava nada -- nunca adivinhar.

    Atributos para a mensagem de tela (`erro_import`): `termo`; `motivo` ("nenhuma",
    "mais_de_uma", "cidade" -- cidade não reconhecida, sobra vazia ou ambígua --, "municipios"
    -- lista do INE ausente/inválida -- ou "pasta" -- pasta de campanhas ausente/inválida);
    `envolvidas` (campanhas que casaram pela raiz), `disponiveis` (todas as válidas), `sobra`
    (o texto procurado como cidade) e `candidatos` (municípios possíveis, se mais de um)."""

    def __init__(self, texto, *, termo=None, motivo="pasta", envolvidas=(), disponiveis=(), sobra=None,
                 candidatos=()):
        super().__init__(texto)
        self.termo = termo
        self.motivo = motivo
        self.envolvidas = list(envolvidas)
        self.disponiveis = list(disponiveis)
        self.sobra = sobra
        self.candidatos = list(candidatos)


def caminho_campanha() -> str:
    """`QUALIFICADOR_CAMPANHA` (caminho final) tem precedência; senão
    `<eqc_root>/config/campanha_ativa.json`. Lê o ambiente a cada chamada."""
    return (os.environ.get(ENV_CAMINHO) or "").strip() or str(contrato.eqc_root().joinpath(*_CAMPANHA_REL))


def normalizar(texto) -> str:
    """Sem acento e sem maiúscula -- base de toda comparação de categoria e de marca."""
    decomposto = unicodedata.normalize("NFKD", texto or "")
    return "".join(c for c in decomposto if not unicodedata.combining(c)).lower().strip()


def _texto_obrigatorio(dados, campo, erros):
    valor = dados.get(campo)
    if not isinstance(valor, str) or not valor.strip():
        erros.append(f"'{campo}' ausente ou vazio (texto obrigatório)")


def _lista_de_termos(dados, campo, erros, pode_ser_vazia):
    if campo not in dados:
        erros.append(f"'{campo}' ausente (lista obrigatória)")
        return
    valor = dados[campo]
    if not isinstance(valor, list) or not all(isinstance(t, str) and t.strip() for t in valor):
        erros.append(f"'{campo}' deve ser uma lista de textos não vazios")
    elif not valor and not pode_ser_vazia:
        erros.append(f"'{campo}' precisa de pelo menos um termo")


def validar_campanha(dados, origem="campanha") -> dict:
    """Devolve a própria campanha se válida; senão levanta listando TODOS os problemas."""
    if not isinstance(dados, dict):
        raise CampanhaInvalidaError(f"{origem}: o conteúdo deve ser um objeto JSON.")
    erros = []
    for campo in ("id", "nicho", "cidade_padrao"):
        _texto_obrigatorio(dados, campo, erros)
    _lista_de_termos(dados, "categorias_aceitas", erros, pode_ser_vazia=False)
    _lista_de_termos(dados, "categorias_excluidas", erros, pode_ser_vazia=True)
    if "termos_de_busca" in dados:
        _lista_de_termos(dados, "termos_de_busca", erros, pode_ser_vazia=False)
    if erros:
        raise CampanhaInvalidaError(f"{origem}: campanha ativa inválida -- " + "; ".join(erros) + ".")
    return dados


def carregar_campanha(caminho=None) -> dict:
    """Lê e valida a campanha ativa. Nunca cai em default: sem campanha válida, o import para."""
    caminho = caminho or caminho_campanha()
    if not os.path.isfile(caminho):
        raise CampanhaInvalidaError(
            f"Campanha ativa não encontrada em '{caminho}'. Crie o arquivo (formato em EQC/INDEX.md) "
            f"ou aponte {ENV_CAMINHO} para ele. Nada foi importado.")
    try:
        with open(caminho, "r", encoding="utf-8") as f:
            dados = json.load(f)
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise CampanhaInvalidaError(f"Campanha ativa em '{caminho}' não é JSON válido ({e}). Nada foi importado.")
    return validar_campanha(dados, origem=caminho)


def carimbo(campanha, cidade) -> dict:
    """Campos gravados em `dados_empresa` de cada lead importado sob esta campanha e cidade
    (`cidade` = a do termo da busca, validada pelo INE, ou a `cidade_padrao` em lista sem termo)."""
    return {"campanha_id": campanha["id"], "campanha_nicho": campanha["nicho"], "campanha_cidade": cidade}


def motivo_categoria(nicho, campanha):
    """(motivo, termo) do corte de categoria, ou None se o lead está no perfil da campanha.

    Termo contido na categoria do Google (`nicho`, já corrigido nas linhas deslocadas),
    sem acento e sem maiúscula. Excluída vence aceita. `termo` é o termo excluído que bateu
    (None no corte por fora do perfil)."""
    categoria = normalizar(nicho)
    for termo in campanha.get("categorias_excluidas") or []:
        if normalizar(termo) in categoria:
            return MOTIVO_EXCLUIDA, termo
    if not any(normalizar(t) in categoria for t in campanha.get("categorias_aceitas") or []):
        return MOTIVO_FORA_DO_PERFIL, None
    return None


# --- escolha da campanha e da cidade pelo termo da busca -------------------------------


def dir_campanhas() -> str:
    """Pasta das campanhas prontas. `QUALIFICADOR_CAMPANHAS_DIR` (só teste) vence;
    senão `<eqc_root>/config/campanhas`. Lê o ambiente a cada chamada."""
    return (os.environ.get(ENV_DIR_CAMPANHAS) or "").strip() or str(contrato.eqc_root().joinpath(*_CAMPANHAS_REL))


def carregar_campanhas_disponiveis(pasta=None) -> list:
    """Todas as campanhas de `pasta` (padrão: `dir_campanhas()`), em ordem de nome de arquivo.
    Uma inválida, pasta vazia/ausente ou `id` repetido => `CampanhaPorTermoError`: sem o
    conjunto inteiro confiável, a escolha pelo termo não tem como provar que é única."""
    pasta = pasta or dir_campanhas()
    if not os.path.isdir(pasta):
        raise CampanhaPorTermoError(f"Pasta de campanhas não encontrada: '{pasta}'. Nada foi importado.")
    arquivos = sorted((a for a in os.listdir(pasta) if a.lower().endswith(".json")), key=str.lower)
    if not arquivos:
        raise CampanhaPorTermoError(f"Nenhuma campanha em '{pasta}'. Nada foi importado.")
    campanhas, vistos = [], {}
    for nome in arquivos:
        try:
            c = carregar_campanha(os.path.join(pasta, nome))
        except CampanhaInvalidaError as e:
            raise CampanhaPorTermoError(f"Campanha com problema, a escolha pelo termo não é segura: {e}") from e
        if c["id"] in vistos:
            raise CampanhaPorTermoError(
                f"id '{c['id']}' repetido em {vistos[c['id']]} e {nome}. Nada foi importado.")
        vistos[c["id"]] = nome
        campanhas.append(c)
    return campanhas


def _raizes(campanha) -> list:
    return [normalizar(r) for r in campanha.get("termos_de_busca") or []]


def _descrever(campanhas) -> str:
    linhas = []
    for c in campanhas:
        termos = ", ".join(c.get("termos_de_busca") or []) or "sem termos_de_busca: só pelo menu"
        linhas.append(f"  - {c['id']}: {c['nicho']} (raízes: {termos})")
    return "\n".join(linhas)


def campanhas_do_termo(termo, disponiveis) -> list:
    """Campanhas cujas raízes aparecem (contidas) no termo, sem acento e sem maiúscula."""
    termo_n = normalizar(termo)
    return [c for c in disponiveis if any(r in termo_n for r in _raizes(c))]


def sobra_do_termo(termo, campanha) -> str:
    """O que sobra do termo, já normalizado, depois de tirar as palavras do nicho (as que
    contêm uma raiz da campanha) e um "en" solto no início."""
    raizes = _raizes(campanha)
    resto = [p for p in normalizar(termo).split() if not any(r in p for r in raizes)]
    if len(resto) > 1 and resto[0] == _CONECTOR_INICIAL:
        resto = resto[1:]
    return " ".join(resto)


def interpretar_termo(termo, disponiveis) -> tuple:
    """`(campanha, municipio)` do termo, ou `CampanhaPorTermoError`. `municipio` =
    `{"codigo_ine", "nombre", "forma"}` (`municipios.procurar`). Fonte única da regra: a
    escolha no import e o termo de exemplo da mensagem de erro passam por aqui."""
    por_raiz = campanhas_do_termo(termo, disponiveis)
    if len(por_raiz) != 1:
        if not por_raiz:
            motivo, texto = "nenhuma", "nenhuma campanha tem raiz no termo"
        else:
            motivo, texto = "mais_de_uma", ("mais de uma campanha casa com o termo: "
                                            + ", ".join(c["id"] for c in por_raiz))
        raise CampanhaPorTermoError(
            f"Termo da busca: '{termo}' -- {texto}. Nada foi importado.\n"
            f"Campanhas disponíveis:\n{_descrever(disponiveis)}",
            termo=termo, motivo=motivo, envolvidas=por_raiz, disponiveis=disponiveis)

    escolhida = por_raiz[0]
    sobra = sobra_do_termo(termo, escolhida)
    try:
        achados = municipios.procurar(sobra)
    except municipios.ListaMunicipiosInvalidaError as e:
        raise CampanhaPorTermoError(f"{e} Nada foi importado.", termo=termo, motivo="municipios",
                                    envolvidas=[escolhida], disponiveis=disponiveis) from e
    if len(achados) != 1:
        if not sobra:
            texto = "o termo não traz cidade depois do nicho"
        elif not achados:
            texto = f"'{sobra}' não é um município da lista oficial do INE"
        else:
            texto = (f"'{sobra}' é o nome de mais de um município: "
                     + ", ".join(f"{m['nombre']} (INE {m['codigo_ine']})" for m in achados))
        raise CampanhaPorTermoError(
            f"Termo da busca: '{termo}' -- cidade não reconhecida: {texto}. Nada foi importado.",
            termo=termo, motivo="cidade", envolvidas=[escolhida], disponiveis=disponiveis, sobra=sobra,
            candidatos=achados)
    return escolhida, achados[0]


def escolher_campanha(termo_busca, pasta=None) -> dict:
    """Campanha e cidade do import: `{"campanha", "cidade", "codigo_ine", "origem", "avisos"}`
    (`origem` = "termo_busca" ou "menu"; `codigo_ine` None no menu; `avisos` = linhas para
    a tela). Regras no docstring do módulo."""
    termo = termo_busca.strip() if isinstance(termo_busca, str) else ""
    if not termo:
        ativa = carregar_campanha()
        return {"campanha": ativa, "cidade": ativa["cidade_padrao"], "codigo_ine": None, "origem": ORIGEM_MENU,
                "avisos": [
                    "LISTA SEM TERMO DE BUSCA -- usando a campanha do MENU e a cidade padrão dela:",
                    f"    {ativa['nicho']}, cidade {ativa['cidade_padrao']}  ({ativa['id']})",
                    "Confira se são o nicho e a cidade desta lista: os leads desta importação levam "
                    "esta campanha e esta cidade.",
                ]}

    escolhida, municipio = interpretar_termo(termo, carregar_campanhas_disponiveis(pasta))
    avisos = [f"Campanha escolhida pelo termo da busca '{termo}': {escolhida['nicho']} ({escolhida['id']}); "
              f"cidade {municipio['forma']} (INE {municipio['codigo_ine']})."]
    try:
        id_menu = carregar_campanha()["id"]
    except CampanhaInvalidaError:
        id_menu = None
    if id_menu != escolhida["id"]:
        avisos.append(f"ATENÇÃO: a campanha ativa do menu é outra ({id_menu or 'nenhuma válida'}); "
                      f"vale a do termo, {escolhida['id']}. O menu não foi alterado.")
    return {"campanha": escolhida, "cidade": municipio["forma"], "codigo_ine": municipio["codigo_ine"],
            "origem": ORIGEM_TERMO, "avisos": avisos}
