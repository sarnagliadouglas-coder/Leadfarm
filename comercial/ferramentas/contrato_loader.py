"""
contrato_loader.py — porta de entrada única do COMERCIAL para o contrato
produzido pelo QUALIFICADOR.

Nenhuma ferramenta do COMERCIAL deve abrir um arquivo de leads diretamente
do disco. Todos passam por aqui. O motivo é que este módulo é o único
ponto onde quatro garantias podem ser impostas de uma vez:

1. O arquivo foi validado contra `leads_qualificados.schema.json` antes de
   qualquer agente vê-lo. Arquivo inválido não vira objeto Python — vira
   exceção. Não existe modo "carregar mesmo assim".
2. `contract_version` é conferido contra a versão que este módulo foi
   escrito para entender (ver `VERSAO_CONTRATO_SUPORTADA`). Passar na
   validação de schema não basta — um schema mais novo apontado por engano
   via COMERCIAL_CONTRACT_SCHEMA pode validar estruturalmente um payload
   com campos que este código nunca leu. Ver "Trava de versão" abaixo.
3. O bloco `priorizacao` é NÃO AUTORITATIVO (`autoritativo: false` no
   contrato, CONTRACT.md §2) e fica atrás de um nome que carrega o aviso.
   Ver "Proteção do bloco priorizacao" abaixo.
4. Os campos `{valor, estado}` do vocabulário de evidência
   (CONFIRMADO_PRESENTE / CONFIRMADO_AUSENTE / NAO_VERIFICADO,
   CONTRACT.md §"Vocabulário de estado") não podem ser lidos como um valor
   cru sem que o código escolha o que fazer com o estado. Ver "Proteção
   dos campos de evidência" abaixo.

Uso:
    from contrato_loader import carregar_lote

    lote = carregar_lote()                        # mais recente do diretório padrão
    lote = carregar_lote(caminho=Path("x.json"))  # arquivo explícito (testes)

    for lead in lote.leads:            # nata + candidatos_triagem, nessa ordem
        lead["identidade"]["nome"]                     # campo plano: acesso normal
        lead["contato"]["telefone"].presente()          # bool
        lead["contato"]["telefone"].valor_confirmado    # só se presente() -> True
        lead.priorizacao_nao_autoritativa               # bloco não autoritativo
        lead.priorizacao                                # -> BlocoNaoAutoritativoError
        psi_estado(lead)                                # PSI_SEM_SITE | "NAO_VERIFICADO" | "CONFIRMADO_PRESENTE"

    lote.nata                                            # só a nata
    lote.candidatos_triagem                               # só os candidatos à triagem visual
    lote.descartados                                       # lista crua, fora da proteção de LeadQualificado

Configuração por ambiente (localização do EQC — resolvida por `eqc.py`, sem
caminho absoluto de máquina fixo no código):
    COMERCIAL_CONTRACT_SCHEMA  caminho final do leads_qualificados.schema.json
    COMERCIAL_INPUT_DIR        diretório final dos leads_qualificados_*.json
    COMERCIAL_EQC_ROOT         pasta ".../EQC" (deriva os dois caminhos acima)
    LEADFARM_ROOT              raiz do LeadFarm; o EQC é <LEADFARM_ROOT>/EQC
Sem nenhuma delas, `eqc.py` descobre o EQC subindo a árvore do projeto e, em
último caso, usa `<pasta-que-contém-o-projeto>/EQC`. Ver o docstring de `eqc.py`.

Requisitos:
    pip install -r requirements.txt   (usa jsonschema)


Trava de versão
----------------
`leads_qualificados.schema.json` já declara `contract_version` como
`"const": "2.0.0"` — um documento com outra versão já reprova na validação
de schema. Este módulo verifica a versão de novo, separadamente, depois da
validação. A razão para a redundância: a garantia de schema depende de
qual arquivo de schema foi carregado. Se `COMERCIAL_CONTRACT_SCHEMA` algum
dia apontar para um schema 3.0.0 sem que este código tenha sido revisado
para os campos novos daquela versão, a validação estrutural passaria limpa
e o código correria sobre um contrato que não entende. A checagem de
`VERSAO_CONTRATO_SUPORTADA` é a garantia que não depende do arquivo de
schema estar certo — depende só deste módulo saber o que sabe.


Proteção do bloco `priorizacao`
--------------------------------
O contrato marca `priorizacao` como `autoritativo: false` (CONTRACT.md
§2). O risco real não é técnico, é humano: um agente futuro lê
`lead.priorizacao.commercial_fit_score` e passa a julgar o lead por um
número que o contrato diz explicitamente que não serve para isso —
julgamento é função do COMERCIAL sobre evidência verificada, não herança
de score do QUALIFICADOR.

Renomear o atributo para `priorizacao_nao_autoritativa` é metade da
proteção — resolve o acesso por atributo, mas deixa aberto o caminho
`lead["priorizacao"]`, que é o que alguém escreve por reflexo ao tratar o
lead como dicionário. Por isso este módulo faz as duas coisas:

- `lead.priorizacao_nao_autoritativa` — o caminho suportado. O nome viaja
  junto com o dado; um `lead.priorizacao_nao_autoritativa["commercial_fit_score"]`
  no meio de uma lógica de decisão fica visivelmente errado em code review.
- `lead.priorizacao` e `lead["priorizacao"]` — ambos levantam erro
  explicando o motivo e apontando o nome correto, em vez de devolver o
  bloco silenciosamente.
- O bloco devolvido é somente-leitura e seu `repr` carrega o aviso —
  aparece em log, em traceback e em depuração.

Nada disso é barreira de segurança: quem quiser burlar chama `lead.bruto()`,
que existe justamente para tornar essa intenção explícita e localizável num
grep. O objetivo é dificultar o erro distraído, não impedir o deliberado.


Proteção dos campos de evidência (`{valor, estado}`)
------------------------------------------------------
CONTRACT.md é explícito: *"NAO_VERIFICADO não é o mesmo que
CONFIRMADO_AUSENTE. O primeiro é 'não sabemos', o segundo é 'sabemos que
não tem'. Tratar os dois como equivalentes descarta informação que pode
valer a pena investigar ao vivo."*

O jeito mais fácil de cometer esse erro em Python é ler o `valor` cru e
testar verdade: `if not lead["contato"]["email"]["valor"]:` é `True` tanto
para "confirmamos que não tem email" quanto para "não checamos se tem
email" — e só o primeiro caso deveria fechar a pergunta. Segue a mesma
filosofia da proteção do `priorizacao`: não impedir o acesso, mas tirar o
caminho de menor esforço de baixo do erro mais fácil de cometer.

Por isso cada campo `{valor, estado}` do contrato — `contato.telefone`,
`contato.email`, `reputacao.nota_google`, `gbp_campos_crus.tem_horario`,
etc. — chega ao agente como um objeto `CampoEvidencia`, nunca como o dict
cru:

- `.estado` — sempre acessível: `"CONFIRMADO_PRESENTE"` |
  `"CONFIRMADO_AUSENTE"` | `"NAO_VERIFICADO"`.
- `.presente()`, `.confirmado_ausente()`, `.nao_verificado()` — predicados
  explícitos. Forçam o agente a nomear o estado que está tratando, em vez
  de inferir de um valor nulo.
- `.valor_confirmado` — devolve `valor` **somente quando `.presente()` é
  verdadeiro**. Nos outros dois estados, levanta `EvidenciaNaoConfirmadaError`
  explicando a diferença entre eles e apontando os predicados. Não existe
  um `.valor` puro e incondicional — esse é o nome que convidaria a pular
  a checagem de estado.
- `.bruto()` — o dict cru `{"valor": ..., "estado": ...}`, para quem
  precisa dele de propósito (serialização, log). Mesma escotilha explícita
  usada em `priorizacao`.

O reconhecimento de quais campos do JSON são `{valor, estado}` é
estrutural, não uma lista de nomes mantida à mão: qualquer dict cujas
chaves sejam exatamente `valor` e `estado`, com `estado` num dos três
valores do vocabulário, vira `CampoEvidencia` — em qualquer profundidade do
lead. Isso cobre os campos hoje existentes (`contato.*`, `reputacao.*`,
`presenca_digital.*`, `gbp_campos_crus.*`, `gbp_diagnostico.sinais.*`, que
tem só `estado` sem `valor`) sem enumerá-los, e continua cobrindo campos
`{valor, estado}` que o contrato acrescentar no futuro sem exigir alteração
deste módulo.


`psi` — o campo que NÃO é `CampoEvidencia` (D12: não estender)
------------------------------------------------------------------
`lead["psi"]` é deliberadamente excluído do envolvimento estrutural acima:
suas três formas (`None` | `{estado: NAO_VERIFICADO, ...}` |
`{estado: CONFIRMADO_PRESENTE, performance_score, lcp_ms, ...}`, ver
`EQC/contracts/CONTRACT.md`, campo `psi`) não batem com a forma `{valor, estado}` — no caso medido não
existe sequer uma chave `valor`. Isso é intencional e não vira
`CampoEvidencia` (decisão D12 — psi tem forma própria demais para
caber nessa abstração sem distorcê-la).

Isso deixa `lead["psi"]` cru: um `dict` ou `None`. Foi comprovado no piloto
da esteira A1–A4 (aposentada em 28/09/2026) que isso convida ao erro óbvio — `lead["psi"]["estado"]` levanta
`TypeError: 'NoneType' object is not subscriptable` sempre que o lead não
tem site, e é fácil esquecer de checar `is None` primeiro. `psi_estado()`
existe só para isso: distinguir os três casos sem exigir que quem chama
lembre da forma exata. É conveniência com trava, não uma nova abstração —
continua devolvendo o dict cru de dentro (quem quiser os campos medidos
segue lendo `lead["psi"]["performance_score"]` etc. normalmente, já sabendo
qual caso está em mãos).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator, Optional

try:
    import jsonschema
except ModuleNotFoundError as exc:  # pragma: no cover - erro de instalação
    raise ModuleNotFoundError(
        "contrato_loader requer a biblioteca 'jsonschema' (mesma escolha do "
        "QUALIFICADOR, para manter os dois lados do contrato consistentes). "
        "Instale com: pip install -r requirements.txt"
    ) from exc

try:
    import eqc
except ModuleNotFoundError:  # pragma: no cover - bootstrap de sys.path
    import sys as _sys

    _sys.path.insert(0, str(Path(__file__).resolve().parent))
    import eqc


# --- Localização do contrato e da entrada -------------------------------
#
# Nenhum caminho absoluto de máquina fica fixo aqui. A árvore EQC é resolvida
# em runtime por `ferramentas/eqc.py` (env COMERCIAL_CONTRACT_SCHEMA /
# COMERCIAL_INPUT_DIR / COMERCIAL_EQC_ROOT / LEADFARM_ROOT → descoberta pela
# árvore do projeto → fallback <pasta-que-contém-o-projeto>/EQC). Ver eqc.py.

ENV_DIRETORIO_ENTRADA = eqc.ENV_INPUT_DIR       # "COMERCIAL_INPUT_DIR"
ENV_SCHEMA = eqc.ENV_CONTRACT_SCHEMA            # "COMERCIAL_CONTRACT_SCHEMA"

# Versão do CONTRACT.md que este módulo foi escrito para entender. Ver
# "Trava de versão" no docstring do módulo. Atualizar isto é uma decisão
# consciente — implica revisar o resto do código contra o que mudou no
# contrato (CONTRACT.md, seção "Histórico de versões").
# 2.1.0 (24/09/2026): acrescenta o campo opcional texto_site (MINOR,
# aditivo) -- lotes 2.0.0 não são mais aceitos (serão refeitos).
VERSAO_CONTRATO_SUPORTADA = "2.1.0"

# leads_qualificados_20260906-201042_v2.0.0.json
# O `.meta.json` que acompanha cada lote NÃO é um arquivo de leads e é
# excluído explicitamente — o glob ingênuo o capturaria.
PADRAO_ARQUIVO = "leads_qualificados_*.json"
SUFIXO_META = ".meta.json"

# Timestamp no nome: AAAAMMDD-HHMMSS (formato usado pelo EXTRATOR e pelo
# QUALIFICADOR). A ordenação é pelo timestamp, nunca por mtime — mtime muda
# ao copiar um arquivo e escolheria o lote errado.
_RE_TIMESTAMP = re.compile(r"(\d{8}-\d{6})")
_FORMATO_TIMESTAMP = "%Y%m%d-%H%M%S"

CHAVE_PRIORIZACAO = "priorizacao"

# Contrato 2.0.0: os leads que atravessam a fronteira vêm em duas listas
# separadas -- nunca mais uma chave 'leads' única (schema.json,
# required de topo). 'descartados' continua à parte, fora da proteção de
# LeadQualificado (ver Lote.descartados).
CHAVE_NATA = "nata"
CHAVE_CANDIDATOS_TRIAGEM = "candidatos_triagem"

# Vocabulário de estado — CONTRACT.md, seção "Vocabulário de estado".
ESTADO_CONFIRMADO_PRESENTE = "CONFIRMADO_PRESENTE"
ESTADO_CONFIRMADO_AUSENTE = "CONFIRMADO_AUSENTE"
ESTADO_NAO_VERIFICADO = "NAO_VERIFICADO"
_ESTADOS_VALIDOS = frozenset(
    {ESTADO_CONFIRMADO_PRESENTE, ESTADO_CONFIRMADO_AUSENTE, ESTADO_NAO_VERIFICADO}
)

# Estados de `psi` — ver "psi — o campo que NÃO é CampoEvidencia" acima.
# PSI_SEM_SITE não é vocabulário do contrato (o contrato nunca escreve essa
# string); é um marcador só deste módulo para o caso `lead["psi"] is None`,
# para que quem chama psi_estado() não precise comparar contra `None`
# diretamente nem redescobrir esse terceiro caso a cada uso.
PSI_SEM_SITE = "SEM_SITE"


# --- Erros ---------------------------------------------------------------


class ContratoError(Exception):
    """Base de todos os erros deste módulo."""


class SchemaIndisponivelError(ContratoError):
    """O arquivo de schema do contrato não foi encontrado ou não é JSON válido."""


class ArquivoDeEntradaError(ContratoError):
    """Diretório inexistente, vazio, ou arquivo de entrada ilegível."""


class ContratoInvalidoError(ContratoError):
    """O arquivo não passou na validação contra o schema do contrato.

    Levantado sem fallback e sem modo permissivo: nenhum agente roda sobre
    um arquivo que não passou.
    """


class VersaoContratoNaoSuportadaError(ContratoInvalidoError):
    """`contract_version` do arquivo difere de VERSAO_CONTRATO_SUPORTADA.

    Distinto de uma violação comum de schema porque a causa mais provável
    não é um arquivo corrompido — é este módulo estar desatualizado em
    relação a uma versão nova e legítima do contrato. Ver "Trava de versão"
    no docstring do módulo.
    """


class BlocoNaoAutoritativoError(ContratoError):
    """Tentativa de acessar o bloco `priorizacao` pelo nome desprotegido."""


class EvidenciaNaoConfirmadaError(ContratoError):
    """Tentativa de ler `.valor_confirmado` num campo que não está CONFIRMADO_PRESENTE."""


_MSG_PRIORIZACAO = (
    "O bloco 'priorizacao' é NÃO AUTORITATIVO (autoritativo: false no contrato) "
    "e não pode ser acessado por este nome. Ele não é evidência sobre o lead e "
    "não deve entrar em nenhum julgamento de qualificação, diagnóstico ou copy. "
    "Se o uso for realmente legítimo (ex.: ordenar uma fila de processamento), "
    "acesse por 'lead.priorizacao_nao_autoritativa' — o nome precisa acompanhar "
    "o dado no ponto de uso."
)


# --- Campo de evidência ({valor, estado}) --------------------------------


class CampoEvidencia:
    """Um campo `{valor, estado}` do vocabulário de evidência do contrato.

    Ver "Proteção dos campos de evidência" no docstring do módulo. Não tem
    `.valor` incondicional de propósito.
    """

    __slots__ = ("_valor", "_estado")

    def __init__(self, bruto: Mapping):
        object.__setattr__(self, "_valor", bruto.get("valor"))
        object.__setattr__(self, "_estado", bruto.get("estado"))

    @property
    def estado(self) -> str:
        return self._estado

    def presente(self) -> bool:
        return self._estado == ESTADO_CONFIRMADO_PRESENTE

    def confirmado_ausente(self) -> bool:
        return self._estado == ESTADO_CONFIRMADO_AUSENTE

    def nao_verificado(self) -> bool:
        return self._estado == ESTADO_NAO_VERIFICADO

    @property
    def valor_confirmado(self) -> Any:
        """`valor`, mas só quando `.presente()` é verdadeiro.

        Levanta nos outros dois estados em vez de devolver `None` — um
        `None` de retorno seria indistinguível do `None` legítimo que o
        contrato permite mesmo em CONFIRMADO_PRESENTE (ex.: um campo
        confirmado presente mas cujo valor é vazio). A exceção obriga o
        chamador a decidir o que fazer com "não sabemos" versus "sabemos
        que não tem" em vez de deixar os dois caírem no mesmo `if`.
        """
        if not self.presente():
            raise EvidenciaNaoConfirmadaError(
                f"Campo com estado '{self._estado}', não "
                f"'{ESTADO_CONFIRMADO_PRESENTE}'. '{ESTADO_NAO_VERIFICADO}' "
                f"significa 'não checamos' — diferente de "
                f"'{ESTADO_CONFIRMADO_AUSENTE}' ('checamos, não tem'). Trate os "
                f"dois separadamente: use .presente() / .confirmado_ausente() / "
                f".nao_verificado() para decidir o que fazer, e '.bruto()' se "
                f"precisar do valor cru mesmo assim."
            )
        return self._valor

    def bruto(self) -> dict:
        """`{"valor": ..., "estado": ...}` cru. Escotilha explícita."""
        return {"valor": self._valor, "estado": self._estado}

    def __repr__(self) -> str:
        return f"<CampoEvidencia estado={self._estado!r} valor={self._valor!r}>"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, CampoEvidencia):
            return NotImplemented
        return self._valor == other._valor and self._estado == other._estado


def _parece_campo_evidencia(valor: Any) -> bool:
    return (
        isinstance(valor, Mapping)
        and set(valor.keys()) <= {"valor", "estado"}
        and valor.get("estado") in _ESTADOS_VALIDOS
    )


def _envolver_evidencias(valor: Any) -> Any:
    """Percorre recursivamente e troca todo `{valor, estado}` por `CampoEvidencia`.

    Estrutural, não uma lista de nomes de campo — ver a nota no fim do
    docstring do módulo sobre por que isso é deliberado.
    """
    if _parece_campo_evidencia(valor):
        return CampoEvidencia(valor)
    if isinstance(valor, Mapping):
        return {chave: _envolver_evidencias(v) for chave, v in valor.items()}
    if isinstance(valor, list):
        return [_envolver_evidencias(v) for v in valor]
    return valor


def psi_estado(lead: "LeadQualificado") -> str:
    """Um dos três estados de `lead["psi"]`, sem exigir checagem manual de `None`.

    Devolve:
        PSI_SEM_SITE            — `psi` é `None` (lead não tem site a medir).
        ESTADO_NAO_VERIFICADO   — `psi["estado"] == "NAO_VERIFICADO"` (site
                                   existe, ainda não foi medido).
        ESTADO_CONFIRMADO_PRESENTE — `psi["estado"] == "CONFIRMADO_PRESENTE"`
                                   (medição concluída; os campos de medição —
                                   `performance_score`, `lcp_ms`, etc. — estão
                                   em `lead["psi"]`).

    Não devolve o dict de `psi` em si — só o estado. Quem precisar dos
    campos medidos lê `lead["psi"]` normalmente depois de saber, por este
    retorno, que está no caso `CONFIRMADO_PRESENTE`.

    Existe porque `psi` não é `CampoEvidencia` (ver docstring do módulo,
    "psi — o campo que NÃO é CampoEvidencia") — `lead["psi"]["estado"]`
    direto levanta `TypeError` sempre que o lead não tem site, e esse erro
    já ocorreu de verdade no piloto do Agente 1.
    """
    psi = lead["psi"]
    if psi is None:
        return PSI_SEM_SITE
    if not isinstance(psi, Mapping) or psi.get("estado") not in (
        ESTADO_NAO_VERIFICADO,
        ESTADO_CONFIRMADO_PRESENTE,
    ):
        raise ContratoError(
            f"lead['psi'] tem forma inesperada: {psi!r}. Esperado None, "
            f"{{'estado': '{ESTADO_NAO_VERIFICADO}', ...}} ou "
            f"{{'estado': '{ESTADO_CONFIRMADO_PRESENTE}', ...}} — ver "
            f"referencias/insumos_sistema_qualificacao.md, seção 'psi'."
        )
    return psi["estado"]


# --- Bloco não autoritativo ---------------------------------------------


class BlocoNaoAutoritativo(Mapping):
    """Mapeamento somente-leitura cujo `repr` carrega o aviso.

    Somente-leitura porque um bloco não autoritativo não deve ser mutado e
    depois reapresentado como se fosse dado do contrato.
    """

    __slots__ = ("_dados", "_nome")

    def __init__(self, dados: Mapping, nome: str = CHAVE_PRIORIZACAO):
        self._dados = dict(dados) if isinstance(dados, Mapping) else dados
        self._nome = nome

    def __getitem__(self, chave: str) -> Any:
        return self._dados[chave]

    def __iter__(self) -> Iterator[str]:
        return iter(self._dados)

    def __len__(self) -> int:
        return len(self._dados)

    def __repr__(self) -> str:
        return f"<{self._nome} NAO_AUTORITATIVO {self._dados!r}>"

    def bruto(self) -> Any:
        """Conteúdo cru do bloco. Chamada explícita, localizável num grep."""
        return self._dados


# --- Lead ----------------------------------------------------------------


class LeadQualificado(Mapping):
    """Um lead do contrato.

    Comporta-se como um mapeamento somente-leitura sobre os campos do
    contrato, com duas exceções deliberadas:

    - a chave `priorizacao` não é acessível nem por atributo nem por
      índice (ver "Proteção do bloco priorizacao" no docstring do módulo);
    - todo campo `{valor, estado}`, em qualquer profundidade, é devolvido
      como `CampoEvidencia`, nunca como o dict cru (ver "Proteção dos
      campos de evidência").

    Este módulo NÃO conhece os nomes dos demais campos do contrato de
    propósito — quem define o conjunto de campos é o schema, e duplicar essa
    lista aqui criaria um segundo contrato para sair de sincronia.
    """

    __slots__ = ("_dados",)

    def __init__(self, dados: Mapping):
        object.__setattr__(self, "_dados", dados)

    # -- acesso por índice --------------------------------------------

    def __getitem__(self, chave: str) -> Any:
        if chave == CHAVE_PRIORIZACAO:
            raise BlocoNaoAutoritativoError(_MSG_PRIORIZACAO)
        return _envolver_evidencias(self._dados[chave])

    def __iter__(self) -> Iterator[str]:
        # `priorizacao` fica fora da iteração: um `dict(lead)` ou um
        # `for campo in lead` não deve reintroduzir o bloco por acidente.
        return (c for c in self._dados if c != CHAVE_PRIORIZACAO)

    def __len__(self) -> int:
        return sum(1 for _ in self)

    # -- acesso por atributo ------------------------------------------

    def __getattr__(self, nome: str) -> Any:
        if nome == CHAVE_PRIORIZACAO:
            raise BlocoNaoAutoritativoError(_MSG_PRIORIZACAO)
        raise AttributeError(
            f"LeadQualificado não tem o atributo '{nome}'. Campos do contrato "
            f"são acessados por índice: lead['{nome}']."
        )

    # -- bloco não autoritativo ---------------------------------------

    @property
    def priorizacao_nao_autoritativa(self) -> BlocoNaoAutoritativo:
        """Bloco `priorizacao` do contrato. NÃO é evidência sobre o lead.

        O contrato 2.0.0 declara `priorizacao` como objeto sempre
        obrigatório (nunca `null`, nunca ausente) — a validação de schema
        já reprova um lead sem ele. Este acessor não lança para bloco
        ausente porque, sob o contrato suportado, essa situação não deveria
        chegar aqui; se chegar, é sinal de um schema carregado incompatível
        com `VERSAO_CONTRATO_SUPORTADA`, e a validação de versão é quem
        deve pegar isso antes.
        """
        return BlocoNaoAutoritativo(self._dados[CHAVE_PRIORIZACAO])

    # -- escotilha explícita ------------------------------------------

    def bruto(self) -> Mapping:
        """Dicionário cru, sem nenhum envolvimento — `priorizacao` incluída
        e todo campo de evidência como dict `{valor, estado}` puro.

        Existe para serialização e depuração. Usar isto para ler
        `priorizacao` ou o valor cru de um campo de evidência contorna as
        proteções deste módulo de forma deliberada — é justamente por isso
        que a chamada tem nome próprio e aparece num grep por `.bruto()`.
        """
        return self._dados

    def __repr__(self) -> str:
        return f"<LeadQualificado campos={sorted(self)!r}>"


# --- Lote ----------------------------------------------------------------


class Lote:
    """Conjunto de leads validado, com a proveniência do arquivo de origem.

    O contrato 2.0.0 separa os leads que atravessam a fronteira em duas
    listas (`nata`, `candidatos_triagem`) -- `descartados` nunca entra
    nelas (ver `Lote.descartados`). `leads` é uma conveniência de leitura
    deste módulo (nata + candidatos_triagem, nessa ordem), não um campo do
    contrato -- quem precisa distinguir as duas populações usa `.nata` /
    `.candidatos_triagem` diretamente.
    """

    __slots__ = ("nata", "candidatos_triagem", "origem", "schema_usado", "_documento")

    def __init__(
        self,
        nata: list[LeadQualificado],
        candidatos_triagem: list[LeadQualificado],
        origem: Path,
        schema_usado: Path,
        documento: Any,
    ):
        self.nata = nata
        self.candidatos_triagem = candidatos_triagem
        self.origem = origem
        self.schema_usado = schema_usado
        self._documento = documento

    @property
    def leads(self) -> list[LeadQualificado]:
        """`nata + candidatos_triagem`, nessa ordem. Ver docstring da classe."""
        return self.nata + self.candidatos_triagem

    def __len__(self) -> int:
        return len(self.leads)

    def __iter__(self) -> Iterator[LeadQualificado]:
        return iter(self.leads)

    @property
    def contract_version(self) -> str:
        return self._documento["contract_version"]

    @property
    def stats(self) -> Mapping:
        """Bloco `stats` cru do documento (contagens do lote, avisos de campo)."""
        return self._documento["stats"]

    @property
    def descartados(self) -> list:
        """Lista crua de `descartados`. Não passa pela proteção de LeadQualificado
        — descartados não são leads processados pelo pipeline do COMERCIAL."""
        return self._documento["descartados"]

    def documento_bruto(self) -> Any:
        """Documento JSON completo, incluindo metadados de topo do lote."""
        return self._documento

    def __repr__(self) -> str:
        return f"<Lote {len(self.leads)} lead(s) origem={self.origem.name!r}>"


# --- Seleção do arquivo --------------------------------------------------


def _timestamp_do_nome(caminho: Path) -> Optional[datetime]:
    achado = _RE_TIMESTAMP.search(caminho.name)
    if not achado:
        return None
    try:
        return datetime.strptime(achado.group(1), _FORMATO_TIMESTAMP)
    except ValueError:
        return None


def listar_arquivos(diretorio: Path) -> list[Path]:
    """Arquivos de lote do diretório, do mais antigo ao mais recente.

    Exclui `*.meta.json` e arquivos sem timestamp reconhecível no nome —
    ordenar por um timestamp que não existe seria adivinhação.
    """
    if not diretorio.is_dir():
        raise ArquivoDeEntradaError(
            f"Diretório de entrada não existe: {diretorio}\n"
            f"Defina {ENV_DIRETORIO_ENTRADA}, aponte o EQC ({eqc.ENV_EQC_ROOT} / "
            f"{eqc.ENV_LEADFARM_ROOT}), ou crie o diretório.\n"
            f"{eqc.descrever_resolucao()}"
        )

    candidatos = [
        caminho
        for caminho in diretorio.glob(PADRAO_ARQUIVO)
        if not caminho.name.endswith(SUFIXO_META)
    ]
    datados = [(ts, c) for c in candidatos if (ts := _timestamp_do_nome(c)) is not None]
    datados.sort(key=lambda par: (par[0], par[1].name))
    return [caminho for _, caminho in datados]


def localizar_mais_recente(diretorio: Optional[Path] = None) -> Path:
    """Arquivo de lote mais recente, pelo timestamp no nome."""
    diretorio = Path(diretorio) if diretorio else diretorio_entrada()
    arquivos = listar_arquivos(diretorio)
    if not arquivos:
        raise ArquivoDeEntradaError(
            f"Nenhum arquivo '{PADRAO_ARQUIVO}' com timestamp AAAAMMDD-HHMMSS "
            f"no nome foi encontrado em: {diretorio}"
        )
    return arquivos[-1]


def diretorio_entrada() -> Path:
    """Diretório dos lotes do QUALIFICADOR. `COMERCIAL_INPUT_DIR` (caminho final)
    vence; senão `<eqc_root>/pipeline/qualificador-output` — ver `eqc.py`."""
    return eqc.diretorio_lotes_entrada()


def caminho_schema() -> Path:
    """Caminho do schema formal do contrato. `COMERCIAL_CONTRACT_SCHEMA` (caminho
    final) vence; senão `<eqc_root>/contracts/leads_qualificados.schema.json` —
    ver `eqc.py`."""
    return eqc.caminho_schema_contrato()


# --- Validação -----------------------------------------------------------


def carregar_schema(caminho: Optional[Path] = None) -> dict:
    caminho = Path(caminho) if caminho else caminho_schema()
    if not caminho.is_file():
        raise SchemaIndisponivelError(
            f"Schema do contrato não encontrado: {caminho}\n"
            f"Sem o schema não há validação, e sem validação nenhum agente roda.\n"
            f"{eqc.descrever_resolucao()}"
        )
    try:
        return json.loads(caminho.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SchemaIndisponivelError(
            f"Schema do contrato não é JSON válido ({caminho}): {exc}"
        ) from exc


def validar(documento: Any, schema: dict, origem: Optional[Path] = None) -> None:
    """Valida contra o schema e levanta na primeira violação. Sem modo permissivo.

    A mensagem preserva o texto do jsonschema e acrescenta o caminho do
    campo, que é o que torna o erro acionável num arquivo de dezenas de
    leads.
    """
    classe = jsonschema.validators.validator_for(schema)
    try:
        classe.check_schema(schema)
    except jsonschema.exceptions.SchemaError as exc:
        raise SchemaIndisponivelError(
            f"O próprio schema do contrato é inválido: {exc.message}"
        ) from exc

    validador = classe(schema)
    erros = sorted(validador.iter_errors(documento), key=lambda e: list(e.absolute_path))
    if not erros:
        return

    primeiro = erros[0]
    caminho_campo = "/".join(str(p) for p in primeiro.absolute_path) or "(raiz)"
    nome_origem = str(origem) if origem else "(documento em memória)"
    raise ContratoInvalidoError(
        f"Arquivo reprovado na validação do contrato: {nome_origem}\n"
        f"{len(erros)} violação(ões). Primeira em '{caminho_campo}':\n"
        f"{primeiro.message}"
    )


def _verificar_versao(documento: Any, origem: Path) -> None:
    """Confere `contract_version` contra VERSAO_CONTRATO_SUPORTADA.

    Roda depois de `validar()`. Ver "Trava de versão" no docstring do
    módulo — é uma checagem redundante com o `const` do schema por design,
    não por descuido.
    """
    versao = documento.get("contract_version") if isinstance(documento, Mapping) else None
    if versao != VERSAO_CONTRATO_SUPORTADA:
        raise VersaoContratoNaoSuportadaError(
            f"Arquivo {origem} declara contract_version={versao!r}, mas este "
            f"módulo só entende {VERSAO_CONTRATO_SUPORTADA!r}. Um schema mais "
            f"novo poderia validar este arquivo estruturalmente sem que este "
            f"código tenha sido revisado para o que mudou — ver CONTRACT.md, "
            f"seção 'Histórico de versões', antes de atualizar "
            f"VERSAO_CONTRATO_SUPORTADA."
        )


# --- Extração dos leads --------------------------------------------------


def _extrair_lista(documento: Any, chave: str, origem: Path) -> list[Mapping]:
    """Localiza uma das listas de leads (`nata` ou `candidatos_triagem`) no
    documento já validado.

    O contrato 2.0.0 fixa o formato: essas duas chaves, sempre num objeto
    de topo (nunca uma lista solta, nunca a antiga chave única `leads` do
    contrato 1.x). Esta função não tolera formato alternativo — o formato é
    conhecido, não uma suposição. Se isso não bater, é sinal de um schema
    carregado incompatível com o que este módulo espera, e a falha é alta.
    """
    if not isinstance(documento, Mapping) or not isinstance(documento.get(chave), list):
        raise ContratoInvalidoError(
            f"Documento de {origem} não tem uma lista em '{chave}'. O "
            f"contrato {VERSAO_CONTRATO_SUPORTADA} exige um objeto de topo com "
            f"essa chave. Isso não deveria acontecer num arquivo que passou na "
            f"validação de schema — verificar se o schema carregado "
            f"(COMERCIAL_CONTRACT_SCHEMA) é mesmo o do contrato {VERSAO_CONTRATO_SUPORTADA}."
        )

    itens = documento[chave]
    for i, item in enumerate(itens):
        if not isinstance(item, Mapping):
            raise ContratoInvalidoError(
                f"Item na posição {i} de '{chave}' em {origem} não é um objeto "
                f"JSON (tipo: {type(item).__name__})."
            )
    return itens


# --- API pública ---------------------------------------------------------


def carregar_lote(
    caminho: Optional[Path] = None,
    *,
    diretorio: Optional[Path] = None,
    schema: Optional[Path] = None,
) -> Lote:
    """Carrega, valida e devolve um lote de leads qualificados.

    Args:
        caminho: arquivo explícito. Quando omitido, usa o mais recente de
            `diretorio` (útil para testes e para reprocessar um lote antigo).
        diretorio: diretório de entrada. Default: COMERCIAL_INPUT_DIR ou
            DIRETORIO_ENTRADA_PADRAO. Ignorado se `caminho` for dado.
        schema: caminho do schema. Default: COMERCIAL_CONTRACT_SCHEMA ou
            SCHEMA_PADRAO.

    Raises:
        SchemaIndisponivelError: schema ausente ou inválido.
        ArquivoDeEntradaError: diretório/arquivo inexistente ou ilegível.
        ContratoInvalidoError: arquivo reprovado na validação de schema, ou
            documento não tem o formato esperado.
        VersaoContratoNaoSuportadaError: `contract_version` diferente de
            VERSAO_CONTRATO_SUPORTADA (subclasse de ContratoInvalidoError).
    """
    caminho_schema_usado = Path(schema) if schema else caminho_schema()
    esquema = carregar_schema(caminho_schema_usado)

    origem = Path(caminho) if caminho else localizar_mais_recente(diretorio)
    if not origem.is_file():
        raise ArquivoDeEntradaError(f"Arquivo de entrada não existe: {origem}")

    try:
        documento = json.loads(origem.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise ContratoInvalidoError(
            f"Arquivo de entrada não é JSON válido ({origem}): {exc}"
        ) from exc
    except OSError as exc:
        raise ArquivoDeEntradaError(f"Não foi possível ler {origem}: {exc}") from exc

    validar(documento, esquema, origem=origem)
    _verificar_versao(documento, origem)

    nata = [LeadQualificado(bruto) for bruto in _extrair_lista(documento, CHAVE_NATA, origem)]
    candidatos_triagem = [
        LeadQualificado(bruto)
        for bruto in _extrair_lista(documento, CHAVE_CANDIDATOS_TRIAGEM, origem)
    ]
    return Lote(
        nata=nata,
        candidatos_triagem=candidatos_triagem,
        origem=origem,
        schema_usado=caminho_schema_usado,
        documento=documento,
    )


_AJUDA_CLI = """\
CLI fina sobre `carregar_lote` — carrega e valida um lote, não um artefato
único. Forma diferente dos outros dois wrappers deste módulo por desenho:
este arquivo é a porta de entrada do lote inteiro, não um validador de
artefato de saída.

Cobre 4 das 6 exceções da hierarquia ContratoError — exatamente as que
`carregar_lote` pode levantar (ver seu docstring: SchemaIndisponivelError,
ArquivoDeEntradaError, ContratoInvalidoError, VersaoContratoNaoSuportadaError).
NÃO exercita BlocoNaoAutoritativoError nem EvidenciaNaoConfirmadaError — as
duas só disparam no acesso a um bloco de um lead já carregado (`.priorizacao`,
`.valor_confirmado`), não na carga do lote. Por desenho: esta CLI só carrega,
nunca acessa bloco de lead individual.

Modo humano (sem --json): a mensagem de erro vai para stderr na codificação
local do console — correta numa tela interativa, mas NÃO segura se um
processo capturar essa saída assumindo UTF-8. Consumo automatizado (hook,
pipeline) deve sempre usar --json, que é ASCII puro e decodifica em
qualquer codificação.
"""


def _serializar_evidencias(valor: Any) -> Any:
    """Converte recursivamente `CampoEvidencia` -> `{valor, estado}` (via
    `.bruto()`, a escotilha explícita de CADA campo) para virar JSON.

    Nunca chama `lead.bruto()` (o do LEAD inteiro) — só a escotilha por
    campo, já sancionada pelo próprio módulo para serialização. Opera sobre
    valores que já passaram por `LeadQualificado.__getitem__`, ou seja, já
    filtrados pela proteção de `priorizacao`.
    """
    if isinstance(valor, CampoEvidencia):
        return valor.bruto()
    if isinstance(valor, Mapping):
        return {chave: _serializar_evidencias(v) for chave, v in valor.items()}
    if isinstance(valor, list):
        return [_serializar_evidencias(v) for v in valor]
    return valor


def _lead_para_json(lead: "LeadQualificado") -> dict:
    """Serializa um lead inteiro para JSON, passando pelas duas proteções
    do módulo: `priorizacao` nunca pelo nome desprotegido — só como
    `priorizacao_nao_autoritativa`, exposta por `.bruto()` do próprio bloco
    não autoritativo — e todo campo de evidência como dict explícito, nunca
    a instância `CampoEvidencia` crua (que `json.dumps` não serializa).
    """
    saida = {chave: _serializar_evidencias(lead[chave]) for chave in lead}
    saida["priorizacao_nao_autoritativa"] = _serializar_evidencias(
        lead.priorizacao_nao_autoritativa.bruto()
    )
    return saida


def _localizar_por_place_id(lote: "Lote", place_id: str) -> Optional["LeadQualificado"]:
    for lead in lote.leads:
        if lead["place_id"] == place_id:
            return lead
    return None


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=_AJUDA_CLI, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("caminho", type=Path, nargs="?", default=None, help="Arquivo do lote (JSON). Omitido = mais recente do diretório")
    ap.add_argument("--diretorio", type=Path, default=None, help="Diretório de entrada, se --caminho for omitido")
    ap.add_argument("--schema", type=Path, default=None, help="Schema alternativo do contrato")
    ap.add_argument(
        "--place-id", type=str, default=None,
        help="Localiza UM lead do lote pelo place_id e devolve só ele, pela "
             "visão protegida (priorizacao nunca pelo nome desprotegido — "
             "só como priorizacao_nao_autoritativa). Omitido: comportamento "
             "atual, só reporta a contagem de leads do lote.",
    )
    ap.add_argument(
        "--json", action="store_true",
        help="Saída em JSON. Exit codes: 0 válido (lote, ou lead encontrado "
             "quando --place-id é dado) · 1 lote reprovado no contrato "
             "(schema ou versão) · 2 não foi possível (arquivo/schema "
             "ausente ou ilegível, ou place_id não encontrado no lote).",
    )
    args = ap.parse_args(argv)

    try:
        lote = carregar_lote(caminho=args.caminho, diretorio=args.diretorio, schema=args.schema)
    except (SchemaIndisponivelError, ArquivoDeEntradaError) as exc:
        # Falha operacional: nunca chegou a existir um documento para
        # julgar. carregar_lote já converte JSONDecodeError em
        # ContratoInvalidoError internamente — não reinterpretamos isso.
        if args.json:
            print(json.dumps({"valido": None, "erro_operacional": str(exc)}))
        else:
            print(str(exc), file=sys.stderr)
        return 2
    except ContratoError as exc:
        # ContratoInvalidoError e VersaoContratoNaoSuportadaError — o
        # documento existe e foi lido, mas reprova o contrato.
        if args.json:
            print(json.dumps({"valido": False, "erro": str(exc)}))
        else:
            print(str(exc), file=sys.stderr)
        return 1

    if args.place_id is not None:
        lead = _localizar_por_place_id(lote, args.place_id)
        if lead is None:
            erro = f"place_id '{args.place_id}' não encontrado no lote {lote.origem}"
            if args.json:
                print(json.dumps({"valido": None, "erro_operacional": erro}))
            else:
                print(erro, file=sys.stderr)
            return 2

        if args.json:
            print(json.dumps({"valido": True, "lead": _lead_para_json(lead)}))
        else:
            print(f"OK: lead {args.place_id} encontrado em {lote.origem}.")
        return 0

    if args.json:
        print(json.dumps({
            "valido": True,
            "origem": str(lote.origem),
            "leads": len(lote.leads),
        }))
    else:
        print(f"OK: {lote.origem} — lote carregado, {len(lote.leads)} lead(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
