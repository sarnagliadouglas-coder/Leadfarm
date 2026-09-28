"""planilha_envio.py — planilha de envio em .xlsx (Etapa E2b), três abas.
Motivo: o CSV com vírgula do QUALIFICADOR abre numa coluna só no Excel do
diretor — .xlsx real, formatado, resolve isso de vez.

MVP de mensagem por MODELO FIXO (mudança de rumo, decisão do diretor,
24/09/2026): a primeira mensagem de cada lead sai de `angulo_mensagem.py`
(ângulo escolhido por regra + 5 textos fixos), nunca mais de uma chamada de
LLM. A Etapa E2 (`pipeline_estrategia_mensagem.py`, `entrada_estrategia.py`,
`prompts/estrategia_mensagem_sistema.md`) e os templates antigos da pista
Direta (`templates_direta.py`, 5 classes) continuam existindo no código e
nos testes — só saem do fluxo desta planilha.

Aba "Geral": todas as linhas do CSV humano mais recente do QUALIFICADOR
(pistas Direta/Espera) -- ângulo `sem_site`/`doctoralia`.

Aba "Nata": `nata` + `candidatos_triagem` do lote mais recente (coluna
"pista" distingue as duas) -- ângulo `contato`/`reputacao`/`lentidao`.

Aba "Como usar": texto fixo com as regras do operador (não gerado por
lead).

Lead sem ângulo (nenhuma regra bateu): sem mensagem, coluna `Status` =
"sem mensagem gerada" (Nata) ou célula vazia (Geral, como antes). Mensagem
que falha no validador: célula vazia + `Aviso` com o motivo -- nunca uma
mensagem inválida na planilha.

Nunca sobrescreve uma planilha anterior. Exclui, na geração, quem já está no
registro de abordados (`registro_abordagens.py`) — e informa quantos.
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from openpyxl import Workbook
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
from openpyxl.styles import Alignment, Font
from openpyxl.utils import get_column_letter

try:
    import eqc
except ModuleNotFoundError:  # pragma: no cover - bootstrap de sys.path
    import sys as _sys

    _sys.path.insert(0, str(Path(__file__).resolve().parent))
    import eqc

import angulo_mensagem
import contrato_loader
import email_utils
import entrada_estrategia
import registro_abordagens
import whatsapp_utils
from validador_mensagem import carregar_config as carregar_config_validacao

_DADOS_DIR = Path(__file__).resolve().parent.parent / "_planilhas"
DIRETORIO_SAIDA_PADRAO = _DADOS_DIR
ENV_SAIDA_DIR = "COMERCIAL_PLANILHAS_DIR"

_RE_TIMESTAMP = re.compile(r"(\d{8}-\d{6})")
_RE_PROFISSIONAL = re.compile(r"^\s*(?:dr\.?|dra\.?|doctor|doctora)\b", re.IGNORECASE)

COLUNAS_CSV_HUMANO = (
    "pista", "motivo", "nome", "cidade", "telefone", "email", "instagram", "site",
    "classe_site", "avaliacoes", "nota", "google_maps_url", "place_id",
)

# "Respondeu" (livre) virou o funil estruturado (Etapa/Resultado/Mensagem/
# Motivo da edição/Decidi não enviar/Motivo de não enviar) -- decisão do
# diretor, 24/09/2026, quarta rodada: registro_abordagens.xlsx passa a ser a
# planilha de acompanhamento, mesmas colunas nas duas abas e no registro
# (registro_abordagens.COLUNAS_FUNIL é a única fonte -- nunca duplicada
# aqui). "Data 1º contato" e "Próximo contato" são novas (quinta rodada,
# mesmo dia). "Enviado em" saiu (sexta rodada, mesmo dia) -- "Data 1º
# contato" passou a ser o único sinal de envio, lido por
# registro_abordagens.py. "Follow-up em"/"Observação" continuam.
COLUNAS_DIRETOR = (
    ("Data 1º contato", "Próximo contato")
    + registro_abordagens.COLUNAS_FUNIL
    + ("Follow-up em", "Observação")
)

# "place_id" é o identificador padrão de todo lead, em TODA aba de leads
# (decisão do diretor, 25/09/2026, defeito grave: a Nata não tinha essa
# coluna -- registro_abordagens._linhas_enviadas pulava a aba em silêncio,
# e nenhum envio dela seria registrado). Sempre por último, sempre
# preenchida -- gerar_planilha recusa gravar qualquer linha sem ela
# (PlaceIdAusenteError). Oculta na planilha (_escrever_aba) -- é para o
# programa, não para o diretor editar.
#
# "WhatsApp" é o ÚNICO link de WhatsApp por linha (decisão do diretor,
# 25/09/2026, especificação final do MVP): com a mensagem sugerida, quando
# houver; senão, link de conversa vazia (quando há celular válido). A coluna
# "Abrir conversa" saiu -- duplicava o mesmo link.
COLUNAS_GERAL = (
    "pista", "motivo", "nome", "cidade", "telefone", "WhatsApp", "email", "Abrir e-mail", "Canal",
    "instagram", "site", "classe_site", "avaliacoes", "nota", "google_maps_url",
    "Ângulo", "Variante", "Mensagem sugerida", "Profissional detectado", "Captura",
) + COLUNAS_DIRETOR + ("Aviso", "Contexto para IA", "place_id")

COLUNAS_NATA = (
    "pista", "nome", "telefone", "WhatsApp", "email", "Abrir e-mail", "Canal",
    "problema vendável", "Ângulo", "Variante", "mensagem", "Status",
    "conferir_antes_de_enviar", "Profissional detectado", "Captura",
    "site", "google_maps_url", "texto_site",
) + COLUNAS_DIRETOR + ("Aviso", "Contexto para IA", "place_id")

STATUS_SEM_MENSAGEM = "sem mensagem gerada"

# Limite real do Excel por célula (.xlsx) -- acima disso o arquivo corrompe a
# célula. "Contexto para IA" é a única coluna que pode chegar perto (o texto
# do site sozinho já vai a até 4000 chars, config/texto_site.json do
# QUALIFICADOR) -- por isso é a única parte truncada quando preciso.
LIMITE_CELULA_XLSX = 32767
_AVISO_TRUNCAMENTO = " [texto do site truncado -- limite de 32.767 caracteres por célula do Excel]"

_COMO_USAR_TEXTO = (
    ("Lentidão", "Antes de enviar, abra o site no seu celular; se carregar rápido, não envie."),
    (
        "Profissional detectado",
        'Quando a coluna "Profissional detectado" = "sim" e você tiver certeza do sobrenome, '
        'troque "Hola, buenas" por "Hola, Dr./Dra. [Apellido]".',
    ),
    (
        "Teste A/B da abertura",
        'Coluna "Variante": A = abertura atual (serviço primeiro); B = abertura nova (motivo do contato '
        "primeiro). O corpo da mensagem é o MESMO nas duas -- só a abertura muda. Envie a variante que "
        "está na linha, sem trocar; A e B já vêm alternadas dentro de cada ângulo e canal. Não mude o "
        "texto dos modelos durante o teste. Mensagem editada à mão (\"Enviada como\" = editada por mim) "
        "fica fora da comparação.",
    ),
    (
        "Comparar A e B",
        "Compare A com B dentro do mesmo ângulo e canal, nunca misturando. Métrica principal: respostas / "
        "mensagens enviadas. Depois: respostas positivas / enviadas; positivas / respostas; pedidos de "
        "preço / enviadas. Com 40 a 50 envios o resultado é um SINAL, não prova: diga \"neste lote, B "
        "teve mais respostas\", \"não houve diferença neste lote\" ou \"amostra insuficiente\" -- "
        "nunca \"B é comprovadamente melhor\".",
    ),
    (
        "Classificar a resposta",
        "resposta positiva: \"Sí, envíamelo\", \"¿Cuánto cobras?\", \"Sí, cuéntame\", \"Me interesa\", "
        "\"¿Qué cambiarías?\". resposta neutra: \"¿Quién eres?\" (útil, mas não positiva). resposta "
        "negativa: \"No me interesa\", \"No necesito nada\". \"No contactar\" = pediu para não "
        "contatar. Nenhuma resposta = sem resposta. Decida a classificação ANTES de olhar a variante.",
    ),
)


class PlanilhaJaExisteError(Exception):
    """Já existe uma planilha com este nome — nunca sobrescrever uma rodada anterior."""


class PlaceIdAusenteError(Exception):
    """Uma ou mais linhas de uma aba de leads sem `place_id` (decisão do
    diretor, 25/09/2026, defeito grave). `place_id` é o identificador padrão
    usado por `registro_abordagens.py` para registrar envios e excluir leads
    já abordados -- uma linha sem ele nunca é gravada; a planilha inteira
    falha, com o nome da aba e as linhas afetadas, em vez de gerar uma
    planilha incompleta em silêncio."""


def _validar_place_ids(nome_aba: str, linhas: list) -> None:
    faltando = [i for i, linha in enumerate(linhas, start=2) if not linha.get("place_id")]
    if faltando:
        raise PlaceIdAusenteError(
            f'Aba "{nome_aba}": {len(faltando)} linha(s) sem place_id (linhas {faltando}) -- '
            f"nenhuma planilha foi gerada."
        )


def diretorio_saida_padrao() -> Path:
    """`COMERCIAL_PLANILHAS_DIR` (env) vence; senão `comercial/_planilhas/`."""
    import os

    valor = (os.environ.get(ENV_SAIDA_DIR) or "").strip()
    return Path(valor) if valor else DIRETORIO_SAIDA_PADRAO


# --- Localização das fontes -----------------------------------------------


def _timestamp_do_nome(caminho: Path) -> Optional[str]:
    achado = _RE_TIMESTAMP.search(caminho.name)
    return achado.group(1) if achado else None


def localizar_csv_humano_mais_recente(diretorio: Optional[Path] = None) -> Path:
    diretorio = Path(diretorio) if diretorio else eqc.diretorio_saida_humana()
    candidatos = sorted(
        (p for p in diretorio.glob("qualificador_*.csv") if _timestamp_do_nome(p)),
        key=_timestamp_do_nome,
    )
    if not candidatos:
        raise FileNotFoundError(f"Nenhum CSV humano ('qualificador_*.csv') encontrado em {diretorio}")
    return candidatos[-1]


def ler_csv_humano(caminho: Path) -> list:
    with open(caminho, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f, delimiter=";"))


# --- Registro de abordados (exclusão na geração) ---------------------------


def place_ids_ja_abordados(caminho_registro: Optional[Path] = None) -> set:
    """`place_id`s já registrados em `registro_abordagens.xlsx` (delega a
    `registro_abordagens.place_ids_registrados` — uma única leitura do
    formato do registro). `caminho_registro` omitido usa o caminho padrão
    (`comercial/_abordagens/registro_abordagens.xlsx`)."""
    caminho = Path(caminho_registro) if caminho_registro else registro_abordagens.caminho_registro()
    return registro_abordagens.place_ids_registrados(caminho)


# --- Canal (decisão do diretor, 24/09/2026, quinta rodada) ------------------


def determinar_canal(telefone: Optional[str], email: Optional[str]) -> str:
    """`"whatsapp"` (celular espanhol válido, 6/7) tem prioridade; senão
    `"email"` quando há e-mail; senão `"para depois"` (nenhum canal de
    contato direto). Celular presente: só WhatsApp é usado, mesmo com
    e-mail também disponível -- "Sem celular e com e-mail => só 'Abrir
    e-mail'" implica a mesma exclusividade no sentido contrário."""
    if whatsapp_utils.normalizar_movel_espanhol(telefone):
        return "whatsapp"
    if email:
        return "email"
    return "para depois"


# --- Profissional detectado (decisão do diretor, 24/09/2026, quinta rodada) -


def profissional_detectado(nome: Optional[str]) -> str:
    """`"sim"` quando `nome` começa com Dr./Dra./Doctor/Doctora (qualquer
    caixa, com ou sem ponto), `"não"` caso contrário. NUNCA extrai o nome do
    profissional -- só a flag booleana."""
    return "sim" if nome and _RE_PROFISSIONAL.match(nome) else "não"


# --- Captura de tela (decisão do diretor, 24/09/2026, quinta rodada) --------


def link_captura(place_id: Optional[str], classe_site: Optional[str], diretorio: Path) -> tuple:
    """`(valor_da_celula, aviso)` -- link `file://` para
    `<place_id>_mobile.png` das capturas do QUALIFICADOR (`eqc.diretorio_
    capturas()`, resolvido pela raiz do LeadFarm, nunca caminho absoluto no
    código). Captura só é esperada para lead com site PRÓPRIO
    (`classe_site == "proprio"`) -- só esses passam pela fase de
    renderização do QUALIFICADOR (`main.py:fase_render`, que só mede
    `classe_site == "proprio"`). Fora disso (defeito real, 24/09/2026: o
    aviso "captura não encontrada" aparecia até em leads da Direta, que
    nunca têm captura), célula vazia e SEM aviso -- não é uma falta, é
    esperado. Para `classe_site == "proprio"`: aviso quando falta
    `place_id`, ou o arquivo não existe."""
    if classe_site != "proprio":
        return "", ""
    if not place_id:
        return "", "sem captura (place_id ausente)"
    caminho = Path(diretorio) / f"{place_id}_mobile.png"
    if caminho.is_file():
        return caminho.as_uri(), ""
    return "", f"captura não encontrada: {caminho.name}"


# --- Contexto para IA -------------------------------------------------------
#
# Texto único, montado por PROGRAMA a partir dos dados já coletados/gerados
# -- nenhuma chamada de LLM aqui. Serve para o diretor colar numa conversa
# com uma IA quando o cliente responde. Respeita LIMITE_CELULA_XLSX: só a
# seção "TEXTO DO SITE" é truncada quando o total passaria do limite (é a
# única parte de tamanho variável grande — até 4000 chars).


def _juntar_secoes(linhas_fixas_antes, texto_site_secao, linhas_fixas_depois) -> str:
    return "\n".join([*linhas_fixas_antes, f"TEXTO DO SITE: {texto_site_secao}", *linhas_fixas_depois])


def _montar_com_limite(linhas_antes, texto_site_txt, linhas_depois, limite=LIMITE_CELULA_XLSX) -> str:
    completo = _juntar_secoes(linhas_antes, texto_site_txt, linhas_depois)
    if len(completo) <= limite:
        return completo
    overhead = len(_juntar_secoes(linhas_antes, "", linhas_depois)) + len(_AVISO_TRUNCAMENTO)
    espaco = max(limite - overhead, 0)
    texto_cortado = texto_site_txt[:espaco] + _AVISO_TRUNCAMENTO
    return _juntar_secoes(linhas_antes, texto_cortado, linhas_depois)


def _linha_lead_generica(nome, nicho, cidade, telefone, site, google_maps_url) -> str:
    partes = [nome]
    if nicho:
        partes.append(nicho)
    if cidade:
        partes.append(cidade)
    partes += [telefone or "(sem telefone)", site or "(sem site)", google_maps_url or "(sem link)"]
    return "LEAD: " + " · ".join(partes)


def montar_contexto_ia_geral(linha: dict) -> str:
    """"Contexto para IA" da aba Geral: dados do lead, classe do site,
    ângulo escolhido e a mensagem sugerida."""
    linha_lead = _linha_lead_generica(
        linha.get("nome", ""), None, linha.get("cidade"), linha.get("telefone"),
        linha.get("site"), linha.get("google_maps_url"),
    )
    classe = linha.get("classe_site") or ""
    angulo = linha.get("Ângulo") or ""
    return "\n".join([
        linha_lead,
        f"CLASSE DO SITE: {classe or '(não classificado)'}",
        f"ÂNGULO: {angulo or '(nenhum)'}",
        f"MENSAGEM SUGERIDA: {linha.get('Mensagem sugerida') or '(nenhuma)'}",
    ])[:LIMITE_CELULA_XLSX]


# --- Linhas da aba Geral (pista Direta) -------------------------------------


def _linha_geral(
    lead: dict, *, aberturas, distribuidor, config_validacao, assuntos_email, mensagens_angulo, diretorio_capturas,
) -> dict:
    telefone = lead.get("telefone")
    email = lead.get("email")
    numero = whatsapp_utils.normalizar_movel_espanhol(telefone)
    canal = determinar_canal(telefone, email)

    linha = dict(lead)
    linha["Canal"] = canal
    linha["Aviso"] = ""
    linha["Mensagem sugerida"] = ""
    linha["Abrir e-mail"] = ""
    linha["Profissional detectado"] = profissional_detectado(lead.get("nome"))

    angulo = angulo_mensagem.escolher_angulo_direta(lead)
    linha["Ângulo"] = angulo
    linha["Variante"] = ""
    if angulo != angulo_mensagem.SEM_ANGULO:
        variante = distribuidor.proxima(angulo, canal)
        mensagem, entrada_derivada = angulo_mensagem.montar_mensagem_direta(
            angulo, lead, apresentacao=aberturas[variante]["texto"], mensagens=mensagens_angulo,
        )
        resultado_validacao = angulo_mensagem.validar_mensagem_angulo(
            mensagem, angulo, entrada_derivada, nome_negocio=lead.get("nome"), config_validacao=config_validacao,
            palavras_genericas_nome=angulo_mensagem.palavras_genericas_nome(angulo_mensagem.carregar_cidade_busca()),
        )
        if not resultado_validacao.valido:
            linha["Aviso"] = "; ".join(resultado_validacao.motivos)
        else:
            linha["Mensagem sugerida"] = mensagem
            linha["Variante"] = variante
            distribuidor.confirmar(angulo, canal)
            if canal == "email":
                linha["Abrir e-mail"] = email_utils.link_mailto(email, assuntos_email["direta"], mensagem)

    linha["WhatsApp"] = (
        whatsapp_utils.link_whatsapp_com_mensagem(numero, linha["Mensagem sugerida"])
        if numero and linha["Mensagem sugerida"]
        else whatsapp_utils.link_whatsapp(numero) if numero else ""
    )

    captura, aviso_captura = link_captura(lead.get("place_id"), lead.get("classe_site"), diretorio_capturas)
    linha["Captura"] = captura
    if aviso_captura:
        linha["Aviso"] = "; ".join(filter(None, [linha["Aviso"], aviso_captura]))

    linha["Contexto para IA"] = montar_contexto_ia_geral(linha)
    return linha


def montar_linhas_geral(leads_csv: list, distribuidor=None, **kwargs) -> list:
    """Um `DistribuidorVariante` por aba: A/B alternam dentro de cada
    (ângulo, canal) da aba Geral, na ordem das linhas."""
    distribuidor = distribuidor or angulo_mensagem.DistribuidorVariante()
    return [_linha_geral(lead, distribuidor=distribuidor, **kwargs) for lead in leads_csv]


# --- Linhas da aba Nata (nata + candidatos_triagem) -------------------------


def _campo_evidencia_ou_vazio(lead, chave1, chave2=None):
    bloco = lead[chave1]
    campo = bloco[chave2] if chave2 else bloco
    return campo.valor_confirmado if campo.presente() else ""


def _resumo_problema_vendavel(lead) -> str:
    itens = lead["problema_vendavel"]
    return "; ".join(item["tipo"] for item in itens)


def _tem_problema_fora_do_ar(lead) -> bool:
    return any(item["tipo"] == "fora_do_ar" for item in lead["problema_vendavel"])


def _problemas_medidos_texto(lead) -> list:
    """Cada problema vendável com a medição -- a evidência CRUA do contrato
    (não a versão saneada que `entrada_estrategia` manda ao modelo): aqui é
    material de auditoria pro diretor/IA, não entrada de LLM com as mesmas
    restrições."""
    medidos = [
        f"{item['tipo']} ({item['medicao']}): {item['evidencia']}"
        for item in lead["problema_vendavel"]
    ]
    nota = lead["reputacao"]["nota_google"]
    avaliacoes = lead["reputacao"]["review_count"]
    if nota.presente() or avaliacoes.presente():
        nota_txt = nota.valor_confirmado if nota.presente() else "não confirmada"
        aval_txt = avaliacoes.valor_confirmado if avaliacoes.presente() else "não confirmadas"
        medidos.append(f"nota {nota_txt}, avaliações {aval_txt}")
    return medidos


def montar_contexto_ia_nata(lead, angulo: str, mensagem: Optional[str]) -> str:
    """"Contexto para IA" da aba Nata -- ordem fixa: LEAD, O QUE MEDIMOS,
    TEXTO DO SITE, ÂNGULO, MENSAGEM. Sem chamada de LLM: `angulo`/`mensagem`
    vêm de `angulo_mensagem.py` (MVP, 24/09/2026)."""
    identidade = lead["identidade"]
    telefone = _campo_evidencia_ou_vazio(lead, "contato", "telefone")
    site = _campo_evidencia_ou_vazio(lead, "presenca_digital", "website_url")

    linha_lead = _linha_lead_generica(
        identidade["nome"], identidade["nicho"], identidade["cidade"], telefone, site,
        identidade["google_maps_url"],
    )
    medidos = _problemas_medidos_texto(lead)
    linha_medimos = "O QUE MEDIMOS: " + ("; ".join(medidos) if medidos else "nada medido")

    texto_site_txt = entrada_estrategia.texto_do_site(lead) or "não medido"

    linha_angulo = f"ÂNGULO: {angulo}"
    linha_mensagem = f"MENSAGEM: {mensagem or '(nenhuma -- sem ângulo)'}"

    return _montar_com_limite([linha_lead, linha_medimos], texto_site_txt, [linha_angulo, linha_mensagem])


def _linha_nata(
    lead, pista: str, leads_do_lote: list, *,
    aberturas, distribuidor, config_validacao, assuntos_email, regras_angulo, mensagens_angulo, diretorio_capturas,
) -> dict:
    telefone = _campo_evidencia_ou_vazio(lead, "contato", "telefone")
    email = _campo_evidencia_ou_vazio(lead, "contato", "email")
    numero = whatsapp_utils.normalizar_movel_espanhol(telefone)
    canal = determinar_canal(telefone, email)

    linha = {
        "pista": pista,
        "place_id": lead["place_id"],
        "nome": lead["identidade"]["nome"],
        "telefone": telefone,
        "WhatsApp": "",
        "email": email,
        "Abrir e-mail": "",
        "Canal": canal,
        "problema vendável": _resumo_problema_vendavel(lead),
        "Ângulo": "",
        "Variante": "",
        "mensagem": "",
        "Status": "",
        "conferir_antes_de_enviar": "sim" if _tem_problema_fora_do_ar(lead) else "não",
        "Profissional detectado": profissional_detectado(lead["identidade"]["nome"]),
        "Captura": "",
        "site": _campo_evidencia_ou_vazio(lead, "presenca_digital", "website_url"),
        "google_maps_url": lead["identidade"]["google_maps_url"] or "",
        "texto_site": entrada_estrategia.texto_do_site(lead) or "",
        "Aviso": "",
    }
    for c in COLUNAS_DIRETOR:
        linha[c] = ""

    angulo = angulo_mensagem.escolher_angulo_nata(lead, leads_do_lote, regras_angulo)
    linha["Ângulo"] = angulo
    mensagem_final = None
    if angulo == angulo_mensagem.SEM_ANGULO:
        linha["Status"] = STATUS_SEM_MENSAGEM
    else:
        variante = distribuidor.proxima(angulo, canal)
        mensagem, entrada_derivada = angulo_mensagem.montar_mensagem_nata(
            angulo, lead, leads_do_lote, apresentacao=aberturas[variante]["texto"], regras=regras_angulo,
            mensagens=mensagens_angulo,
        )
        resultado_validacao = angulo_mensagem.validar_mensagem_angulo(
            mensagem, angulo, entrada_derivada, nome_negocio=lead["identidade"]["nome"],
            config_validacao=config_validacao,
            palavras_genericas_nome=angulo_mensagem.palavras_genericas_nome(
                lead["identidade"]["nicho"], angulo_mensagem.carregar_cidade_busca(),
            ),
        )
        if not resultado_validacao.valido:
            linha["Aviso"] = "; ".join(resultado_validacao.motivos)
            linha["Status"] = STATUS_SEM_MENSAGEM
        else:
            linha["mensagem"] = mensagem
            linha["Variante"] = variante
            distribuidor.confirmar(angulo, canal)
            mensagem_final = mensagem
            if canal == "email":
                linha["Abrir e-mail"] = email_utils.link_mailto(email, assuntos_email["nata"], mensagem)

    linha["WhatsApp"] = (
        whatsapp_utils.link_whatsapp_com_mensagem(numero, linha["mensagem"])
        if numero and linha["mensagem"]
        else whatsapp_utils.link_whatsapp(numero) if numero else ""
    )

    captura, aviso_captura = link_captura(lead["place_id"], lead["classe_site"], diretorio_capturas)
    linha["Captura"] = captura
    if aviso_captura:
        linha["Aviso"] = "; ".join(filter(None, [linha["Aviso"], aviso_captura]))

    linha["Contexto para IA"] = montar_contexto_ia_nata(lead, angulo, mensagem_final)
    return linha


def montar_linhas_nata(nata: list, candidatos_triagem: list, descartados: list, distribuidor=None, **kwargs) -> list:
    """`nata` e `candidatos_triagem` viram linhas (coluna `pista` distingue
    as duas); `descartados` entra só como pool de concorrentes do ângulo
    `reputacao` (`angulo_mensagem.escolher_angulo_nata`), nunca vira linha
    própria."""
    leads_do_lote = list(nata) + list(candidatos_triagem) + list(descartados)
    distribuidor = distribuidor or angulo_mensagem.DistribuidorVariante()
    linhas = [_linha_nata(lead, "nata", leads_do_lote, distribuidor=distribuidor, **kwargs) for lead in nata]
    linhas += [
        _linha_nata(lead, "candidatos_triagem", leads_do_lote, distribuidor=distribuidor, **kwargs)
        for lead in candidatos_triagem
    ]
    return linhas


# --- Aba "Como usar" ----------------------------------------------------------


def _escrever_aba_como_usar(wb) -> None:
    ws = wb.create_sheet("Como usar")
    ws.append(["Regra", "O que fazer"])
    for cel in ws[1]:
        cel.font = Font(bold=True)
    for titulo, texto in _COMO_USAR_TEXTO:
        ws.append([titulo, texto])
    for r in range(2, ws.max_row + 1):
        ws.cell(row=r, column=2).alignment = Alignment(wrap_text=True, vertical="top")
    ws.column_dimensions["A"].width = 22
    ws.column_dimensions["B"].width = 100


# --- Escrita da planilha -----------------------------------------------------


def _sem_caracteres_ilegais(valor):
    """Remove caracteres de controle que o Excel recusa
    (`openpyxl.cell.cell.ILLEGAL_CHARACTERS_RE` -- ex.: `\\x0b`, `\\x1f`) de
    um valor de célula. Defeito real, 25/09/2026: o `texto_site` de um lead
    real trazia um caractere de controle e `IllegalCharacterError` impedia a
    planilha inteira de ser gerada -- nenhuma linha chegava a ser gravada.
    Ponto único de limpeza: toda célula de texto passa por aqui antes de
    `ws.append`, nunca em cada lugar que monta uma linha."""
    if isinstance(valor, str):
        return ILLEGAL_CHARACTERS_RE.sub("", valor)
    return valor


def _escrever_aba(ws, colunas, linhas, *, colunas_link=(), colunas_wrap=(), opcoes_funil=None):
    ws.append([_sem_caracteres_ilegais(c) for c in colunas])
    for cel in ws[1]:
        cel.font = Font(bold=True)
    ws.freeze_panes = "A2"

    for linha in linhas:
        ws.append([_sem_caracteres_ilegais(linha.get(c, "")) for c in colunas])

    ultima_linha = ws.max_row
    if ultima_linha >= 1:
        ws.auto_filter.ref = f"A1:{get_column_letter(len(colunas))}{max(ultima_linha, 1)}"

    if opcoes_funil:
        registro_abordagens.aplicar_validacoes_funil(ws, colunas, opcoes_funil, ultima_linha)

    for nome_col in colunas_link:
        idx = colunas.index(nome_col) + 1
        for r in range(2, ultima_linha + 1):
            cel = ws.cell(row=r, column=idx)
            if cel.value:
                cel.hyperlink = cel.value
                cel.font = Font(color="0563C1", underline="single")

    for nome_col in colunas_wrap:
        idx = colunas.index(nome_col) + 1
        for r in range(2, ultima_linha + 1):
            ws.cell(row=r, column=idx).alignment = Alignment(wrap_text=True, vertical="top")

    for i, nome_col in enumerate(colunas, start=1):
        maior = len(nome_col)
        for linha in linhas:
            maior = max(maior, len(str(linha.get(nome_col, ""))))
        ws.column_dimensions[get_column_letter(i)].width = min(max(maior + 2, 10), 60)

    if "place_id" in colunas:
        ws.column_dimensions[get_column_letter(colunas.index("place_id") + 1)].hidden = True


def _caminho_planilha(saida_dir: Path, agora: datetime) -> Path:
    return Path(saida_dir) / f"planilha_envio_{agora.strftime('%Y%m%d-%H%M%S')}.xlsx"


def gerar_planilha(
    *,
    caminho_csv_humano: Optional[Path] = None,
    caminho_lote: Optional[Path] = None,
    caminho_registro: Optional[Path] = None,
    saida_dir: Optional[Path] = None,
    agora: Optional[datetime] = None,
    aberturas: Optional[dict] = None,
    config_validacao: Optional[dict] = None,
    assuntos_email: Optional[dict] = None,
    opcoes_funil: Optional[dict] = None,
    regras_angulo: Optional[dict] = None,
    mensagens_angulo: Optional[dict] = None,
    diretorio_capturas: Optional[Path] = None,
) -> dict:
    """Gera `planilha_envio_<timestamp>.xlsx` com as abas Geral, Nata e
    "Como usar". Nunca sobrescreve (`PlanilhaJaExisteError`). Exclui, das
    abas Geral e Nata, quem já está no registro de abordados. Devolve
    `{"caminho", "excluidos_geral", "excluidos_nata"}`."""
    saida_dir = Path(saida_dir) if saida_dir else diretorio_saida_padrao()
    agora = agora or datetime.now(timezone.utc)
    caminho = _caminho_planilha(saida_dir, agora)
    if caminho.exists():
        raise PlanilhaJaExisteError(f"{caminho} já existe — nunca sobrescrever uma planilha anterior.")

    aberturas = aberturas if aberturas is not None else angulo_mensagem.carregar_aberturas()
    config_validacao = config_validacao or carregar_config_validacao()
    assuntos_email = assuntos_email if assuntos_email is not None else email_utils.carregar_assuntos_email()
    opcoes_funil = opcoes_funil if opcoes_funil is not None else registro_abordagens.carregar_opcoes_funil()
    regras_angulo = regras_angulo if regras_angulo is not None else angulo_mensagem.carregar_regras_angulo()
    mensagens_angulo = mensagens_angulo if mensagens_angulo is not None else angulo_mensagem.carregar_mensagens_angulo()
    diretorio_capturas = Path(diretorio_capturas) if diretorio_capturas else eqc.diretorio_capturas()

    caminho_csv = Path(caminho_csv_humano) if caminho_csv_humano else localizar_csv_humano_mais_recente()
    leads_csv = ler_csv_humano(caminho_csv)

    lote = contrato_loader.carregar_lote(caminho=caminho_lote)

    ja_abordados = place_ids_ja_abordados(caminho_registro)
    excluidos_geral = [l for l in leads_csv if l.get("place_id") in ja_abordados]
    leads_csv = [l for l in leads_csv if l.get("place_id") not in ja_abordados]
    nata_excluida = [l for l in lote.nata if l["place_id"] in ja_abordados]
    nata_incluida = [l for l in lote.nata if l["place_id"] not in ja_abordados]
    candidatos_excluidos = [l for l in lote.candidatos_triagem if l["place_id"] in ja_abordados]
    candidatos_incluidos = [l for l in lote.candidatos_triagem if l["place_id"] not in ja_abordados]

    kwargs_comuns = dict(
        aberturas=aberturas, config_validacao=config_validacao, assuntos_email=assuntos_email,
        mensagens_angulo=mensagens_angulo, diretorio_capturas=diretorio_capturas,
    )

    # Um distribuidor para as duas abas: o equilíbrio A/B é do pacote inteiro
    # (decisão do diretor, 28/09/2026); os estratos (ângulo, canal) das abas não se misturam.
    distribuidor = angulo_mensagem.DistribuidorVariante()
    linhas_geral = montar_linhas_geral(leads_csv, distribuidor=distribuidor, **kwargs_comuns)
    linhas_nata = montar_linhas_nata(
        nata_incluida, candidatos_incluidos, lote.descartados, regras_angulo=regras_angulo, distribuidor=distribuidor,
        **kwargs_comuns,
    )

    _validar_place_ids("Geral", linhas_geral)
    _validar_place_ids("Nata", linhas_nata)

    wb = Workbook()
    ws_geral = wb.active
    ws_geral.title = "Geral"
    _escrever_aba(
        ws_geral, COLUNAS_GERAL, linhas_geral,
        colunas_link=("WhatsApp", "Abrir e-mail", "Captura"),
        colunas_wrap=("Mensagem sugerida", "Contexto para IA"),
        opcoes_funil=opcoes_funil,
    )
    ws_nata = wb.create_sheet("Nata")
    _escrever_aba(
        ws_nata, COLUNAS_NATA, linhas_nata,
        colunas_link=("WhatsApp", "Abrir e-mail", "Captura"),
        colunas_wrap=("mensagem", "texto_site", "Contexto para IA"),
        opcoes_funil=opcoes_funil,
    )
    _escrever_aba_como_usar(wb)

    saida_dir.mkdir(parents=True, exist_ok=True)
    wb.save(caminho)

    return {
        "caminho": caminho,
        "excluidos_geral": len(excluidos_geral),
        "excluidos_nata": len(nata_excluida) + len(candidatos_excluidos),
    }


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Etapa E2b — planilha de envio em .xlsx (abas Geral, Nata e Como usar)."
    )
    ap.add_argument(
        "--saida-dir", type=Path, default=None,
        help="Diretório de saída (default: COMERCIAL_PLANILHAS_DIR ou comercial/_planilhas/).",
    )
    args = ap.parse_args(argv)

    resultado = gerar_planilha(saida_dir=args.saida_dir)

    print(
        f"OK: planilha gerada em {resultado['caminho']} "
        f"({resultado['excluidos_geral']} excluído(s) na Geral, "
        f"{resultado['excluidos_nata']} excluído(s) na Nata -- já abordados)."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
