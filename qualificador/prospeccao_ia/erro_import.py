"""Erro do import em linguagem clara (Tarefa 3, diretor 06/10/2026).

Quando o import PARA por um caso previsto -- termo da busca sem campanha ou com mais de uma;
cidade do termo não reconhecida pela lista do INE, vazia ou ambígua; lista do INE ou campanhas
com problema; campanha ativa ausente ou inválida; CSV ou `.meta.json` fora do contrato do
EXTRATOR; CSV que não se deixa ler -- a tela mostra só uma mensagem curta em português (o que
aconteceu, o termo, as campanhas envolvidas e o que fazer) e o processo sai com
`CODIGO_SAIDA`. O traceback completo vai para um arquivo de log (`gravar_log`), cujo caminho
aparece na mensagem. Erro fora desses casos NÃO é tratado aqui: `main.run` grava o log e
deixa a exceção subir como sempre.

O comportamento do import não muda: os casos previstos já levantam antes de gravar
qualquer coisa (`main.importar_csv`). Só a apresentação muda. $0, sem LLM.

Próximo passo sugerido: só o que foi verificado. O termo de exemplo
("<nicho> <cidade padrão>") só aparece se, passado pela MESMA regra da escolha
(`campanha.interpretar_termo`), ele cair exatamente naquela campanha e num município.
"""
import os
import traceback
from datetime import datetime

import campanha
import csv_contrato


class CsvIlegivelError(Exception):
    """O CSV não existe ou não se deixa ler (decodificação, arquivo malformado, acesso).
    Levantado por `main.importar_csv` antes de gravar qualquer coisa."""


PREVISTOS = (csv_contrato.ContratoCsvInvalido, campanha.CampanhaInvalidaError, CsvIlegivelError)
CODIGO_SAIDA = 1

_ATALHO = "Trocar-campanha.bat (na raiz do LeadFarm)"
_REEXTRAIR = "extraia a lista de novo com a extensão e importe o CSV novo, sem editar os arquivos."


def gravar_log(exc: BaseException, pasta: str) -> str:
    """Grava o traceback completo de `exc` num arquivo novo em `pasta` e devolve o caminho."""
    os.makedirs(pasta, exist_ok=True)
    caminho = os.path.join(pasta, f"import_erro_{datetime.now().strftime('%Y%m%d-%H%M%S-%f')}.log")
    with open(caminho, "w", encoding="utf-8") as f:
        f.write("".join(traceback.format_exception(type(exc), exc, exc.__traceback__)))
    return caminho


def termo_sugerido(c: dict, disponiveis: list):
    """'<nicho> <cidade padrão>' em minúsculas, se esse termo escolher exatamente `c` e um
    município; senão None."""
    termo = f"{c['nicho']} {c['cidade_padrao']}".lower()
    try:
        escolhida, _municipio = campanha.interpretar_termo(termo, disponiveis)
    except campanha.CampanhaInvalidaError:
        return None
    return termo if escolhida["id"] == c["id"] else None


def _campanha(c: dict) -> str:
    return f"{c['nicho']} ({c['id']})"


def _com_exemplos(campanhas: list, disponiveis: list) -> list:
    linhas = []
    for c in campanhas:
        exemplo = termo_sugerido(c, disponiveis)
        linhas.append(f"  - {_campanha(c)}" + (f'  ->  exemplo de busca: "{exemplo}"' if exemplo else ""))
    return linhas


def _por_termo(exc: campanha.CampanhaPorTermoError) -> tuple:
    """(o que aconteceu, linhas de detalhe, o que fazer)."""
    termo = f'Termo da busca: "{exc.termo}"'
    if exc.motivo == "cidade":
        sobra = f'Cidade lida no termo: "{exc.sobra}"' if exc.sobra else "Cidade lida no termo: (nenhuma)"
        if exc.candidatos:
            return ("cidade não reconhecida -- esse nome é de mais de um município.",
                    [termo, sobra, "Municípios com esse nome:",
                     *(f"  - {m['nombre']} (INE {m['codigo_ine']})" for m in exc.candidatos)],
                    "a busca não consegue escolher entre eles; avise quem cuida da configuração.")
        if not exc.sobra:
            return ("cidade não reconhecida -- o termo da busca não traz cidade, só o nicho.",
                    [termo, sobra, "Campanha do nicho:", *_com_exemplos(exc.envolvidas, exc.disponiveis)],
                    'busque de novo no Google Maps como "<nicho> <município>", com o nome do município '
                    "(exemplo acima), extraia e importe a lista nova.")
        return ("cidade não reconhecida -- não é um município da lista oficial do INE.",
                [termo, sobra, "Campanha do nicho:", *_com_exemplos(exc.envolvidas, exc.disponiveis)],
                'busque de novo no Google Maps como "<nicho> <município>", com o nome do município '
                "(exemplo acima), extraia e importe a lista nova.")
    if exc.motivo == "mais_de_uma":
        return ("a busca casa com mais de uma campanha.",
                [termo, "Campanhas que casaram:", *_com_exemplos(exc.envolvidas, exc.disponiveis)],
                "busque um nicho por vez no Google Maps (exemplos acima), extraia e importe a lista nova.")
    if exc.motivo == "nenhuma":
        return ("nenhuma campanha pronta tem o nicho dessa busca.",
                [termo, "Campanhas disponíveis:", *_com_exemplos(exc.disponiveis, exc.disponiveis)],
                "busque no Google Maps o nicho de uma das campanhas acima e a cidade, extraia e "
                "importe a lista nova.")
    if exc.motivo == "municipios":
        return ("a lista oficial de municípios do INE (qualificador/prospeccao_ia/config/"
                "municipios_ine.json) está ausente ou com problema, então a cidade da busca não "
                "pode ser conferida.", [termo], "avise quem cuida da configuração; o detalhe está no log.")
    return ("as campanhas prontas (EQC/config/campanhas/) estão ausentes ou com problema, "
            "então a busca não pode ser ligada a uma campanha com segurança.",
            [], "avise quem cuida da configuração; o detalhe está no log.")


def mensagem(exc: BaseException, caminho_log: str) -> str:
    """Mensagem curta de tela para um erro PREVISTO (`isinstance(exc, PREVISTOS)`)."""
    if isinstance(exc, campanha.CampanhaPorTermoError):
        aconteceu, detalhes, fazer = _por_termo(exc)
    elif isinstance(exc, campanha.CampanhaInvalidaError):
        aconteceu, detalhes, fazer = (
            "a lista não tem termo de busca e a campanha ativa do menu está ausente ou com problema.",
            [], f"dê duplo clique em {_ATALHO}, escolha o nicho da lista e importe de novo.")
    elif isinstance(exc, csv_contrato.ContratoCsvInvalido):
        aconteceu, detalhes, fazer = (
            "o CSV ou o .meta.json ao lado dele não está no formato do extrator.",
            [f"Motivo: {str(exc).splitlines()[0]}"], _REEXTRAIR)
    elif isinstance(exc, CsvIlegivelError):
        aconteceu, detalhes, fazer = (
            "o CSV não pôde ser lido (não existe, está corrompido ou não é um CSV do extrator).",
            [f"Motivo: {str(exc).splitlines()[0]}"], _REEXTRAIR)
    else:
        raise TypeError(f"erro não previsto não tem mensagem de tela: {type(exc).__name__}")
    return "\n".join([
        "==================================================",
        "O IMPORT PAROU -- nada foi gravado.",
        f"O que aconteceu: {aconteceu}",
        *detalhes,
        f"O que fazer: {fazer}",
        f"Detalhe técnico: {caminho_log}",
        "==================================================",
    ])
