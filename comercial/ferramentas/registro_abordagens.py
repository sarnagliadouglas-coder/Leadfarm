"""registro_abordagens.py — comando "registrar-envios" (Etapa F mínima).

Lê as linhas com "Data 1º contato" preenchida (sinal de envio -- "Enviado
em" saiu na sexta rodada de decisões do diretor, 24/09/2026: "Data 1º
contato" já cobria a mesma informação) OU "Decidi não enviar" = "sim" em
QUALQUER aba de uma planilha de envio já preenchida pelo diretor, e
acrescenta em
`comercial/_abordagens/registro_abordagens.xlsx` (fora do Git), sem duplicar
`place_id`. NUNCA escreve na planilha do diretor — só leitura
(`load_workbook(..., read_only=True)`). Faz backup do registro antes de
gravar. Se o registro estiver aberto em outro programa (Excel), levanta erro
claro sem perder nada — o backup já foi feito antes da tentativa de gravar,
e a planilha do diretor nunca foi tocada.

A geração da planilha (`planilha_envio.gerar_planilha`) lê este registro
(`place_ids_ja_abordados`) e exclui quem já está aqui.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from openpyxl import Workbook, load_workbook
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

_DADOS_DIR = Path(__file__).resolve().parent.parent / "_abordagens"
DIRETORIO_PADRAO = _DADOS_DIR
NOME_REGISTRO = "registro_abordagens.xlsx"

_CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"
CAMINHO_FUNIL_PADRAO = _CONFIG_DIR / "funil_planilha.json"
_CHAVES_FUNIL_OBRIGATORIAS = ("etapa", "resultado", "mensagem", "decidi_nao_enviar")

# Colunas com lista de escolha (validação de dados do Excel) -- decisão do
# diretor, 24/09/2026, quarta rodada: "registro_abordagens.xlsx passa a ser
# a planilha de acompanhamento". Mesmas colunas nas duas abas da planilha de
# envio (planilha_envio.py) e aqui -- "Motivo da edição" e "Motivo de não
# enviar" são texto livre, sem lista. "Mensagem" (como está/editada) virou
# "Enviada como" na sexta rodada (mesmo dia) -- a aba Nata também tem a
# coluna "mensagem" (minúscula, o texto em si); os dois nomes quase iguais
# confundiam o operador. A chave de config continua "mensagem" (minúscula,
# config/funil_planilha.json) -- só o título da coluna mudou.
COLUNAS_FUNIL = ("Etapa", "Resultado", "Enviada como", "Motivo da edição", "Decidi não enviar", "Motivo de não enviar")

# "angulo" e "variante" (decisão do diretor, 27/09/2026, teste A/B da
# abertura) ficam no FIM: um registro já existente, com o cabeçalho antigo,
# ganha as duas colunas no fim do cabeçalho e a escrita é feita por NOME de
# coluna (`_escrever_por_cabecalho`) -- nenhuma coluna antiga muda de posição.
COLUNAS_REGISTRO = (
    "place_id", "nome", "telefone", "aba_origem", "enviado_em",
    "canal", "modelo", "custo_usd", "registrado_em",
) + COLUNAS_FUNIL + ("angulo", "variante")


class ConfigFunilInvalidaError(Exception):
    """`config/funil_planilha.json` ausente, ilegível ou incompleto."""


def carregar_opcoes_funil(caminho: Path = CAMINHO_FUNIL_PADRAO) -> dict:
    caminho = Path(caminho)
    try:
        texto = caminho.read_text(encoding="utf-8")
    except (FileNotFoundError, IsADirectoryError, PermissionError, OSError) as e:
        raise ConfigFunilInvalidaError(f"Config do funil não encontrada em {caminho}: {e}") from e
    try:
        config = json.loads(texto)
    except json.JSONDecodeError as e:
        raise ConfigFunilInvalidaError(f"Config do funil em {caminho} não é JSON válido: {e}") from e

    faltando = [c for c in _CHAVES_FUNIL_OBRIGATORIAS if c not in config]
    if faltando:
        raise ConfigFunilInvalidaError(f"Config do funil em {caminho} sem as chaves: {faltando}")
    return config


def aplicar_validacao_lista(ws, colunas: tuple, nome_coluna: str, opcoes: list, ultima_linha: int) -> None:
    """Restringe `nome_coluna` (nome exato em `colunas`) a uma lista de
    escolha (Dados > Validação de Dados do Excel), da linha 2 até
    `ultima_linha`. Sem opções, sem linha de dados, ou coluna ausente desta
    aba: não aplica nada -- nunca quebra a escrita da planilha."""
    if not opcoes or ultima_linha < 2 or nome_coluna not in colunas:
        return
    idx = colunas.index(nome_coluna) + 1
    letra = get_column_letter(idx)
    dv = DataValidation(type="list", formula1='"' + ",".join(opcoes) + '"', allow_blank=True)
    dv.add(f"{letra}2:{letra}{ultima_linha}")
    ws.add_data_validation(dv)


def aplicar_validacoes_funil(ws, colunas: tuple, opcoes_funil: dict, ultima_linha: int) -> None:
    """As quatro colunas do funil com lista de escolha -- "Motivo da edição"
    e "Motivo de não enviar" são texto livre, sem validação."""
    aplicar_validacao_lista(ws, colunas, "Etapa", opcoes_funil.get("etapa", []), ultima_linha)
    aplicar_validacao_lista(ws, colunas, "Resultado", opcoes_funil.get("resultado", []), ultima_linha)
    aplicar_validacao_lista(ws, colunas, "Enviada como", opcoes_funil.get("mensagem", []), ultima_linha)
    aplicar_validacao_lista(
        ws, colunas, "Decidi não enviar", opcoes_funil.get("decidi_nao_enviar", []), ultima_linha
    )


class PlanilhaAbertaError(Exception):
    """O arquivo de registro está aberto em outro programa (ex.: Excel).
    Nada foi perdido: o backup já foi feito, a planilha do diretor não foi
    tocada — feche o arquivo e rode de novo."""


class RegistroSemPlaceIdError(Exception):
    """Defeito grave, 25/09/2026: uma aba com envio pendente de registro
    ("Data 1º contato" ou "Decidi não enviar" preenchidos) não tem a coluna
    `place_id`, ou alguma dessas linhas tem `place_id` vazio. `place_id` é o
    identificador padrão de todo lead -- nunca cai para nome ou telefone
    como alternativa, e nunca pula a aba em silêncio (a Nata não tinha essa
    coluna e nenhum envio dela seria registrado -- os leads voltariam nas
    próximas planilhas, sem aviso nenhum). Levantado ANTES de qualquer
    escrita -- nada é registrado, nem parcialmente."""


def caminho_registro(diretorio: Optional[Path] = None) -> Path:
    diretorio = Path(diretorio) if diretorio else DIRETORIO_PADRAO
    return Path(diretorio) / NOME_REGISTRO


def _linhas_enviadas(caminho_planilha: Path) -> list:
    """Uma entrada por linha com "Data 1º contato" preenchida OU "Decidi não
    enviar" = "sim" (decisão do diretor, 24/09/2026, quarta rodada -- um
    lead que o diretor decidiu não abordar também precisa sair do registro
    para não voltar nas próximas planilhas; "Data 1º contato" substituiu
    "Enviado em" como sinal de envio na sexta rodada, mesmo dia), em
    QUALQUER aba que tenha "Data 1º contato" ou "Decidi não enviar" (abas
    sem nenhuma das duas, como "Como usar", são ignoradas -- não são abas de
    leads). "canal"/"modelo"/"custo_usd" e os campos do funil vêm de colunas
    que só a aba Nata tem hoje -- ausentes na Geral, ficam "" (não é erro, é
    pista Direta sem LLM).

    `place_id` é o identificador padrão, sempre obrigatório (decisão do
    diretor, 25/09/2026, defeito grave): uma aba com envio pendente sem a
    coluna `place_id`, ou com alguma dessas linhas de `place_id` vazio,
    levanta `RegistroSemPlaceIdError` ANTES de qualquer coisa ser
    registrada -- nunca pula a aba em silêncio, nunca cai para nome ou
    telefone como identificador alternativo."""
    wb = load_workbook(caminho_planilha, read_only=True, data_only=True)
    try:
        encontradas = []
        erros = []
        for nome_aba in wb.sheetnames:
            linhas_da_aba = list(wb[nome_aba].iter_rows(values_only=True))
            if not linhas_da_aba:
                continue
            cabecalho, linhas_dados = linhas_da_aba[0], linhas_da_aba[1:]
            tem_data_contato = "Data 1º contato" in cabecalho
            tem_decidi_nao_enviar = "Decidi não enviar" in cabecalho
            if not tem_data_contato and not tem_decidi_nao_enviar:
                continue  # aba sem colunas de acompanhamento -- não é aba de leads

            idx = {nome: i for i, nome in enumerate(cabecalho)}

            def _valor(linha, coluna, idx=idx):
                i = idx.get(coluna)
                return linha[i] if i is not None and i < len(linha) else None

            pendentes = []
            for numero_linha, linha in enumerate(linhas_dados, start=2):
                enviado_em = _valor(linha, "Data 1º contato") if tem_data_contato else None
                decidiu_nao_enviar = (
                    str(_valor(linha, "Decidi não enviar") or "").strip().lower() == "sim"
                    if tem_decidi_nao_enviar else False
                )
                if enviado_em or decidiu_nao_enviar:
                    pendentes.append((numero_linha, linha, enviado_em, decidiu_nao_enviar))

            if not pendentes:
                continue

            if "place_id" not in cabecalho:
                erros.append(
                    f'aba "{nome_aba}": {len(pendentes)} linha(s) com envio pendente, '
                    f"mas a aba não tem a coluna place_id"
                )
                continue

            linhas_sem_place_id = [numero for numero, linha, *_ in pendentes if not _valor(linha, "place_id")]
            if linhas_sem_place_id:
                erros.append(
                    f'aba "{nome_aba}": linha(s) {linhas_sem_place_id} com envio pendente e place_id vazio'
                )
                continue

            for numero_linha, linha, enviado_em, decidiu_nao_enviar in pendentes:
                encontradas.append({
                    "place_id": _valor(linha, "place_id"),
                    "nome": _valor(linha, "nome") or "",
                    "telefone": _valor(linha, "telefone") or "",
                    "aba_origem": nome_aba,
                    "enviado_em": enviado_em or "",
                    # "Canal" é a coluna da planilha atual (MVP, 24/09); "canal_sugerido"
                    # era a da planilha da Etapa E2 -- defeito achado em 27/09/2026: só a
                    # antiga era lida, e o canal chegava vazio ao registro.
                    "canal": _valor(linha, "Canal") or _valor(linha, "canal_sugerido") or "",
                    "modelo": _valor(linha, "modelo") or "",
                    "custo_usd": _valor(linha, "custo_total_usd") or "",
                    "etapa": _valor(linha, "Etapa") or "",
                    "resultado": _valor(linha, "Resultado") or "",
                    "mensagem_status": _valor(linha, "Enviada como") or "",
                    "motivo_edicao": _valor(linha, "Motivo da edição") or "",
                    "decidiu_nao_enviar": "sim" if decidiu_nao_enviar else "",
                    "motivo_nao_enviar": _valor(linha, "Motivo de não enviar") or "",
                    "angulo": _valor(linha, "Ângulo") or "",
                    "variante": _valor(linha, "Variante") or "",
                })

        if erros:
            raise RegistroSemPlaceIdError(
                "Não é possível registrar -- nada foi gravado: " + "; ".join(erros)
            )
        return encontradas
    finally:
        wb.close()


def place_ids_registrados(caminho: Path) -> set:
    """`place_id`s já presentes no registro. Arquivo ausente devolve
    conjunto vazio — usada tanto aqui (evitar duplicar) quanto por
    `planilha_envio.gerar_planilha` (excluir quem já foi abordado)."""
    return _place_ids_existentes(caminho)


def _place_ids_existentes(caminho: Path) -> set:
    if not Path(caminho).is_file():
        return set()
    wb = load_workbook(caminho, read_only=True)
    try:
        ws = wb.active
        linhas = ws.iter_rows(values_only=True)
        cabecalho = next(linhas, None)
        if not cabecalho or "place_id" not in cabecalho:
            return set()
        idx = cabecalho.index("place_id")
        return {linha[idx] for linha in linhas if linha and linha[idx]}
    finally:
        wb.close()


def _garantir_cabecalho(ws) -> list:
    """Cabeçalho da aba do registro, com as colunas de `COLUNAS_REGISTRO`
    que faltarem ACRESCENTADAS NO FIM (registro criado antes de 27/09/2026
    não tem "angulo"/"variante"). Nunca reordena nem remove coluna
    existente -- a escrita das linhas novas é por nome de coluna."""
    cabecalho = [c.value for c in ws[1]]
    for coluna in COLUNAS_REGISTRO:
        if coluna not in cabecalho:
            ws.cell(row=1, column=len(cabecalho) + 1, value=coluna)
            cabecalho.append(coluna)
    return cabecalho


def _fazer_backup(caminho: Path) -> Optional[Path]:
    if not Path(caminho).is_file():
        return None
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    destino = caminho.with_name(f"{caminho.stem}.bak-{ts}{caminho.suffix}")
    shutil.copy2(caminho, destino)
    return destino


def registrar_envios(
    caminho_planilha: Path, *, diretorio_registro: Optional[Path] = None, agora=None,
    opcoes_funil: Optional[dict] = None,
) -> dict:
    """Devolve `{"acrescentados", "ja_existentes", "backup"}`. Nunca duplica
    `place_id` (linhas cujo `place_id` já está no registro são só contadas
    em `ja_existentes`, não gravadas de novo) e NUNCA altera uma linha já
    existente -- só acrescenta (decisão do diretor, 24/09/2026, quarta
    rodada: o registro passa a ser a planilha de acompanhamento, o diretor
    edita diretamente nele). `opcoes_funil` omitido carrega
    `config/funil_planilha.json`."""
    agora = agora or datetime.now(timezone.utc)
    caminho_reg = caminho_registro(diretorio_registro)
    opcoes_funil = opcoes_funil if opcoes_funil is not None else carregar_opcoes_funil()

    enviadas = _linhas_enviadas(Path(caminho_planilha))
    existentes = _place_ids_existentes(caminho_reg)

    novas = [e for e in enviadas if e["place_id"] and e["place_id"] not in existentes]
    ja_existentes = len(enviadas) - len(novas)

    if not novas:
        return {"acrescentados": 0, "ja_existentes": ja_existentes, "backup": None}

    backup = _fazer_backup(caminho_reg)

    try:
        if caminho_reg.is_file():
            wb = load_workbook(caminho_reg)
            ws = wb.active
        else:
            wb = Workbook()
            ws = wb.active
            ws.title = "Registro"
            ws.append(list(COLUNAS_REGISTRO))

        cabecalho = _garantir_cabecalho(ws)
        registrado_em = agora.strftime("%Y-%m-%dT%H:%M:%SZ")
        for e in novas:
            valores = {
                "place_id": e["place_id"], "nome": e["nome"], "telefone": e["telefone"],
                "aba_origem": e["aba_origem"], "enviado_em": e["enviado_em"], "canal": e["canal"],
                "modelo": e["modelo"], "custo_usd": e["custo_usd"], "registrado_em": registrado_em,
                "Etapa": e["etapa"], "Resultado": e["resultado"], "Enviada como": e["mensagem_status"],
                "Motivo da edição": e["motivo_edicao"], "Decidi não enviar": e["decidiu_nao_enviar"],
                "Motivo de não enviar": e["motivo_nao_enviar"], "angulo": e["angulo"], "variante": e["variante"],
            }
            ws.append([valores.get(c, "") for c in cabecalho])

        aplicar_validacoes_funil(ws, cabecalho, opcoes_funil, ws.max_row)

        caminho_reg.parent.mkdir(parents=True, exist_ok=True)
        wb.save(caminho_reg)
    except PermissionError as exc:
        raise PlanilhaAbertaError(
            f"{caminho_reg} está aberto em outro programa (provavelmente o Excel). "
            f"Nada foi perdido -- o backup em {backup} preserva o estado anterior do "
            f"registro, e a planilha de envio não foi tocada. Feche o arquivo e rode de novo."
        ) from exc

    return {"acrescentados": len(novas), "ja_existentes": ja_existentes, "backup": backup}


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Registra os envios (\"Data 1º contato\" preenchida) de uma planilha de envio já preenchida pelo diretor."
    )
    ap.add_argument("planilha", type=Path, help="Caminho da planilha de envio preenchida pelo diretor.")
    args = ap.parse_args(argv)

    resultado = registrar_envios(args.planilha)

    print(
        f"OK: {resultado['acrescentados']} envio(s) registrado(s), "
        f"{resultado['ja_existentes']} já existente(s) no registro."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
