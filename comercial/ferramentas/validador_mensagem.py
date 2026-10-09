"""validador_mensagem.py — validação determinística da saída de estratégia +
mensagem (Etapa E2, `RUMO-COMERCIAL-2026-09.md` §5, "DESENHO APROVADO PELO
DIRETOR EM 23/09"). Nenhuma chamada de LLM aqui — só regras de programa.
Nunca aceita em silêncio: toda falha vem com o(s) motivo(s), nunca só um bool.

Treze checagens (1-12 do desenho aprovado em 23/09; 13 da mudança 2, 27/09/2026):
1. JSON bem formado com os 4 campos (`estrategia`, `canal_sugerido`,
   `mensagem_1`, `fato_usado`), todos string não vazia.
2. `mensagem_1` com no máximo `max_palavras_mensagem_1` palavras.
3. `mensagem_1` termina com `"?"`.
4. `mensagem_1` sem URL.
5. `mensagem_1` sem símbolo de moeda nem palavra de preço.
6. `mensagem_1` sem marca de tratamento informal (usted é obrigatório).
7. Todo número presente em `mensagem_1` existe em algum lugar da entrada
   daquele lead — nunca um número inventado pelo modelo. Conta como número
   tanto dígito (`\\d+`) quanto número por extenso em espanhol
   (`numeros_por_extenso_es`, ex. "diez" -> 10, inclusive compostos como
   "veintidós" e "treinta y dos") e expressão numérica
   (`expressoes_numericas_es`, ex. "medio minuto" -> 30) — achado em
   produção 24/09/2026: "casi diez segundos" citando 8 segundos reais
   escapava da checagem porque só dígito contava como número.
8. `mensagem_1` começa exatamente com `saudacao_fixa` (decisão do diretor,
   24/09/2026: "Hola, buenas"). Checagem opcional — config sem essa chave
   não aplica a regra (unidade que testa outra regra não precisa satisfazer
   esta também).
9. `mensagem_1` sem nenhum termo de `termos_proibidos` (decisão do diretor,
   24/09/2026: nunca afirmar que o site "está caído" — a frase correta é
   na linha de "no me cargó cuando intenté entrar"; "celular" também entra
   aqui — espanhol da Espanha diz "móvil", nunca "celular"). Checagem
   opcional pelo mesmo motivo da 8.
10. `trecho_site` (campo novo, v3 do prompt, 24/09/2026; regra endurecida na
    v4, mesma data): quando não `null`, precisa existir LITERALMENTE
    (comparação normalizada de espaços e maiúsculas —
    `_normalizar_para_comparacao`) dentro de `entrada["texto_site"]`.
    Citação que o modelo não pode provar que veio do texto real do site é
    tratada como fato inventado — a mensagem inteira é rejeitada, não só o
    campo. Duas bordas adicionais (v4, decisão do diretor: o prompt v3 deixava
    a citação do site opcional e o modelo nunca usava — rodada real de
    24/09/2026, 37 de 37 leads com `trecho_site` nulo): com `texto_site`
    presente na entrada, `trecho_site` nulo é rejeitado ("mensagem sem
    detalhe do site" — o prompt v4 torna a citação obrigatória nesse caso);
    sem `texto_site` na entrada, `trecho_site` não-nulo é rejeitado (nada a
    citar).
11. `mensagem_1` nunca cita o nome do negócio (decisão do diretor,
    24/09/2026, quarta rodada — "nome do negócio fora das mensagens"):
    rejeitada se contiver o nome ORIGINAL do lead (`nome_negocio`, passado
    à parte — `entrada` não carrega mais `nome` nenhum) ou o corte de
    `nome_comercial.nome_comercial_limpo`, comparando sem diferenciar
    maiúsculas e acentos (`_normalizar_forte`). Checagem opcional:
    `nome_negocio` omitido não roda esta regra.
12. `trecho_site`, quando passa a checagem 10, ainda não pode carregar
    detalhe pessoal (formação, diploma, universidade, biografia, prêmio,
    anos de experiência — `termos_proibidos_trecho_site` da config; caso
    real 24/09/2026: "está diplomada en Fisioterapia en la Escuela
    Universitaria Ficticia"). Radicais de palavra, comparados sem
    diferenciar maiúsculas e acentos. Checagem opcional pela ausência da
    chave, mesmo princípio das checagens 8 e 9.
13. `mensagem_1` sem frase de RESULTADO_NAO_SUSTENTADO (decisão do
    diretor, 27/09/2026, mudança 2, com o ajuste à decisão 5): cada frase é
    classificada por `afirmacao.classificar_frase` -- marcador de
    resultado/causalidade ("pierde", "provoca", "abandonen", ...) SEM modal
    ("puede", "podría", ...) na mesma frase rejeita a mensagem; com modal é
    implicação plausível e passa. A palavra sozinha não basta para rejeitar.
    Checagem opcional pela ausência da chave `afirmacao`, mesmo princípio
    das checagens 8 e 9.

14. `mensagem_1` sem nenhum domínio ou endereço (`padrao_dominio` da
    config: "palavra.palavra" com sufixo, subdomínios, e-mails, linktr.ee...),
    mesmo sem "http"/"www" -- o WhatsApp o transforma em link e um subdomínio
    pode trazer o nome do negócio (decisão do diretor, 09/10/2026). Única
    exceção: o e-mail de modelo citado pelo `defeito_visivel`, que chega em
    `entrada["texto_encontrado"]`. Checagem opcional pela ausência da chave,
    mesmo princípio das checagens 8 e 9.

Exceções por modelo (decisão do diretor, 01/10/2026, "Novos templates e
ângulos"): `validar_mensagem(..., excecoes=...)` dispensa, SÓ para o modelo
que as declara em `config/mensagens_angulo.json` (`excecoes_validacao`), a
checagem 11 (`nome_negocio`), a 3 (`sem_pergunta_final`) e a contagem de
certas palavras como número por extenso na 7 (`numeros_por_extenso`, ex.
`["dos"]`). Sem `excecoes` -- ou para qualquer outro modelo -- nada muda.

As listas de preço/informalidade/números por extenso/termos proibidos e o
limite de palavras vêm de `config/validacao_mensagem.json` — nunca fixas em
código (mesmo princípio da tabela de preços da Etapa E1).
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

try:
    from nome_comercial import nome_comercial_limpo
except ModuleNotFoundError:  # pragma: no cover - bootstrap de sys.path
    import sys as _sys

    _sys.path.insert(0, str(Path(__file__).resolve().parent))
    from nome_comercial import nome_comercial_limpo

import afirmacao

_CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"
CAMINHO_CONFIG_PADRAO = _CONFIG_DIR / "validacao_mensagem.json"

CAMPOS_OBRIGATORIOS = ("estrategia", "canal_sugerido", "mensagem_1", "fato_usado")

_CHAVES_CONFIG_OBRIGATORIAS = (
    "max_palavras_mensagem_1",
    "simbolos_moeda",
    "palavras_preco",
    "marcas_informais_es",
    "saudacao_fixa",
    "termos_proibidos",
)


class ConfigValidacaoInvalidaError(Exception):
    """`config/validacao_mensagem.json` ausente, ilegível ou incompleto."""


@dataclass(frozen=True)
class ResultadoValidacao:
    """`valido=False` sempre vem com `motivos` não vazio — nunca falha muda."""

    valido: bool
    motivos: list
    dados: Optional[dict]


def carregar_config(caminho: Path = CAMINHO_CONFIG_PADRAO) -> dict:
    caminho = Path(caminho)
    try:
        texto = caminho.read_text(encoding="utf-8")
    except (FileNotFoundError, IsADirectoryError, PermissionError, OSError) as e:
        raise ConfigValidacaoInvalidaError(
            f"Config de validação não encontrada em {caminho}: {e}"
        ) from e
    try:
        config = json.loads(texto)
    except json.JSONDecodeError as e:
        raise ConfigValidacaoInvalidaError(
            f"Config de validação em {caminho} não é JSON válido: {e}"
        ) from e

    faltando = [c for c in _CHAVES_CONFIG_OBRIGATORIAS if c not in config]
    if faltando:
        raise ConfigValidacaoInvalidaError(
            f"Config de validação em {caminho} sem as chaves: {faltando}"
        )
    return config


def _extrair_json(texto: str) -> tuple:
    """`(dados, None)` se `texto` tiver um objeto JSON válido (tolera cercas
    de código ```` ```json ... ``` ````), ou `(None, motivo)` se não."""
    bruto = texto.strip()
    if bruto.startswith("```"):
        bruto = re.sub(r"^```(?:json)?\s*", "", bruto)
        bruto = re.sub(r"\s*```$", "", bruto)
    try:
        dados = json.loads(bruto)
    except json.JSONDecodeError as e:
        return None, f"resposta não é JSON válido: {e}"
    if not isinstance(dados, dict):
        return None, f"JSON devolvido não é um objeto (veio {type(dados).__name__})"
    return dados, None


def _numeros(texto: str) -> set:
    return set(re.findall(r"\d+", texto))


def _remover_acentos(texto: str) -> str:
    """Decompõe acentos (NFKD) e descarta os caracteres combinantes -- "é"
    vira "e", "ñ" vira "n". Usado onde a comparação precisa ignorar acento
    além de maiúscula/minúscula (checagens 11 e 12, decisão do diretor,
    24/09/2026: 'sem diferenciar maiúsculas e acentos')."""
    return "".join(c for c in unicodedata.normalize("NFKD", texto) if not unicodedata.combining(c))


def _normalizar_forte(texto: str) -> str:
    """`_normalizar_para_comparacao` (espaço + maiúscula) mais remoção de
    acento -- para comparar nome do negócio e termos proibidos de
    `trecho_site`, nunca para `trecho_site`-existe-no-`texto_site` (checagem
    10, que continua só espaço/maiúscula -- acento faz parte da citação
    literal ali)."""
    return _remover_acentos(_normalizar_para_comparacao(texto))


# Conectoras fixas da checagem 11 (decisão do diretor, 25/09/2026, oitava
# rodada) -- sempre genéricas, somadas às palavras de `palavras_genericas_
# nome` (nicho do lead, cidade da busca) que quem chama `validar_mensagem`
# fornecer.
_CONECTORES_NOME_GENERICO = {"en", "de", "del", "la", "el", "y"}


def _genericas_normalizadas(frases_genericas: Optional[list]) -> set:
    palavras = set(_CONECTORES_NOME_GENERICO)
    for frase in frases_genericas or ():
        for palavra in str(frase or "").split():
            normalizada = _remover_acentos(palavra).strip().lower()
            if normalizada:
                palavras.add(normalizada)
    return palavras


def _normalizar_para_comparacao(texto: str) -> str:
    """Espaços colapsados + minúsculas — para comparar `trecho_site` contra
    `entrada["texto_site"]` sem reprovar por uma quebra de linha ou
    maiúscula/minúscula diferente entre o que o modelo copiou e o texto
    original (regra 24/09/2026: comparação normalizada de espaços e
    maiúsculas, não igualdade byte a byte)."""
    return re.sub(r"\s+", " ", texto or "").strip().lower()


_DEZENAS_COMPOSTAS = ("treinta", "cuarenta", "cincuenta", "sesenta", "setenta", "ochenta", "noventa")
_UNIDADES_COMPOSTAS = ("uno", "dos", "tres", "cuatro", "cinco", "seis", "siete", "ocho", "nueve")


def _padrao_composto_y(numeros_config: dict):
    """Regex `dezena + 'y' + unidade` (ex.: "treinta y dos"), construído só
    com as palavras que a própria config tiver — nunca lista nova, reusa
    `numeros_por_extenso_es`."""
    dezenas = [p for p in _DEZENAS_COMPOSTAS if p in numeros_config]
    unidades = [p for p in _UNIDADES_COMPOSTAS if p in numeros_config]
    if not dezenas or not unidades:
        return None
    return re.compile(
        r"\b(" + "|".join(re.escape(d) for d in dezenas) + r")\s+y\s+("
        + "|".join(re.escape(u) for u in unidades) + r")\b",
        re.IGNORECASE,
    )


def _numeros_por_extenso(texto: str, config: dict) -> set:
    """Números escritos por extenso em espanhol (`numeros_por_extenso_es`,
    inclusive compostos de uma palavra só como "veintidós") e expressões
    numéricas de mais de uma palavra (`expressoes_numericas_es`), convertidos
    para o mesmo vocabulário de `_numeros` (string de dígitos), para entrar
    no mesmo cruzamento contra a entrada. Ambas as chaves são opcionais na
    config — ausência não é erro, só não detecta por extenso.

    Trata também o composto "dezena y unidade" ("treinta y dos" -> 32) —
    achado como borda faltante em 24/09/2026: sem isto, "treinta" e "dos"
    seriam contados como dois números soltos (30 e 2), nenhum dos quais bate
    com o "32" da entrada, e a mensagem seria rejeitada por engano mesmo
    citando o número certo. Por isso o trecho casado por esse composto é
    mascarado ANTES da varredura de palavras soltas — "treinta y dos" vira
    só "32", nunca "32" mais "30" mais "2"."""
    numeros_config = config.get("numeros_por_extenso_es", {})
    encontrados: set = set()

    texto_sem_compostos = texto
    padrao_composto = _padrao_composto_y(numeros_config)
    if padrao_composto is not None:
        for casado in padrao_composto.finditer(texto):
            dezena_valor = numeros_config.get(casado.group(1).lower())
            unidade_valor = numeros_config.get(casado.group(2).lower())
            if dezena_valor is None or unidade_valor is None:
                continue
            encontrados.add(str(int(dezena_valor) + int(unidade_valor)))
            texto_sem_compostos = texto_sem_compostos.replace(casado.group(0), " ", 1)

    for palavra, valor in numeros_config.items():
        if re.search(rf"\b{re.escape(palavra)}\b", texto_sem_compostos, re.IGNORECASE):
            encontrados.add(str(valor))

    for frase, valor in config.get("expressoes_numericas_es", {}).items():
        if re.search(rf"\b{re.escape(frase)}\b", texto, re.IGNORECASE):
            encontrados.add(str(valor))

    return encontrados


def validar_mensagem(
    texto_resposta: str,
    entrada: dict,
    *,
    config: Optional[dict] = None,
    nome_negocio: Optional[str] = None,
    palavras_genericas_nome: Optional[list] = None,
    excecoes: Optional[dict] = None,
) -> ResultadoValidacao:
    """Valida a resposta bruta do modelo (`texto_resposta`) contra as treze
    regras, cruzando números com `entrada` (a mesma entrada enviada para
    aquele lead). `config` omitido carrega `config/validacao_mensagem.json`.
    `nome_negocio` (decisão do diretor, 24/09/2026, quarta rodada) é o nome
    ORIGINAL do lead -- não vem de `entrada` (que não carrega mais `nome`
    nenhum) -- passado à parte por quem chama (`pipeline_estrategia_mensagem`,
    `templates_direta`, `angulo_mensagem`); omitido, a checagem 11 não roda
    (unidade que testa outra regra não precisa fornecer isso também).
    `palavras_genericas_nome` (decisão do diretor, 25/09/2026, oitava rodada
    -- falso positivo real: lead "Psicólogo en Alicante - Pedro Ficticio", nome
    limpo "Psicólogo en Alicante", só palavras genéricas, rejeitado porque o
    modelo de `poucas_avaliacoes` legitimamente diz "quien busca psicólogo en
    Alicante") é uma lista de frases (nicho do lead, cidade da busca) cujas
    palavras, somadas às conectoras fixas ("en", "de", "del", "la", "el",
    "y"), tornam um trecho do nome "genérico" -- um candidato de nome cujas
    palavras são TODAS genéricas não conta como o nome do negócio vazando.
    Nome com qualquer palavra própria (ex.: "Ficticio") continua rejeitado.
    `excecoes` (ver docstring do módulo): dict com `nome_negocio` (bool),
    `sem_pergunta_final` (bool) e `numeros_por_extenso` (lista de palavras
    que não contam como número) -- cada chave dispensa só a sua checagem."""
    excecoes = excecoes or {}
    if config is None:
        config = carregar_config()
    motivos: list = []

    dados, motivo_json = _extrair_json(texto_resposta)
    if dados is None:
        return ResultadoValidacao(valido=False, motivos=[motivo_json], dados=None)

    faltando = [
        campo
        for campo in CAMPOS_OBRIGATORIOS
        if not isinstance(dados.get(campo), str) or not dados[campo].strip()
    ]
    if faltando:
        motivos.append(f"campos ausentes, não-string ou vazios: {faltando}")
        # sem mensagem_1 utilizável não dá para seguir as checagens de texto
        return ResultadoValidacao(valido=False, motivos=motivos, dados=dados)

    mensagem = dados["mensagem_1"]

    palavras = mensagem.split()
    if len(palavras) > config["max_palavras_mensagem_1"]:
        motivos.append(
            f"mensagem_1 tem {len(palavras)} palavras "
            f"(máximo {config['max_palavras_mensagem_1']})"
        )

    if not excecoes.get("sem_pergunta_final") and not mensagem.strip().endswith("?"):
        motivos.append("mensagem_1 não termina com '?'")

    if re.search(r"https?://|www\.", mensagem, re.IGNORECASE):
        motivos.append("mensagem_1 contém URL")

    padrao_dominio = config.get("padrao_dominio")
    if padrao_dominio:
        # checagem 14: nenhum domínio nem endereço, nem sem "http"/"www" -- a
        # única exceção é o e-mail de modelo que o `defeito_visivel` cita
        # (`entrada["texto_encontrado"]`), que é a própria evidência
        sem_permitidos = mensagem
        permitido = entrada.get("texto_encontrado")
        if isinstance(permitido, str) and permitido:
            sem_permitidos = sem_permitidos.replace(permitido, " ")
        dominios = re.findall(padrao_dominio, sem_permitidos, re.IGNORECASE)
        if dominios:
            motivos.append(f"mensagem_1 contém domínio ou endereço: {dominios}")

    achados_moeda = [s for s in config["simbolos_moeda"] if s in mensagem]
    if achados_moeda:
        motivos.append(f"mensagem_1 contém símbolo de moeda: {achados_moeda}")

    achadas_preco = [
        p for p in config["palavras_preco"] if re.search(rf"\b{re.escape(p)}\b", mensagem, re.IGNORECASE)
    ]
    if achadas_preco:
        motivos.append(f"mensagem_1 contém palavra de preço: {achadas_preco}")

    achadas_informais = [
        m for m in config["marcas_informais_es"] if re.search(rf"\b{re.escape(m)}\b", mensagem, re.IGNORECASE)
    ]
    if achadas_informais:
        motivos.append(f"mensagem_1 contém tratamento informal: {achadas_informais}")

    saudacao_fixa = config.get("saudacao_fixa")
    if saudacao_fixa and not mensagem.startswith(saudacao_fixa):
        motivos.append(f"mensagem_1 não começa com a saudação fixa {saudacao_fixa!r}")

    achados_proibidos = [
        t for t in config.get("termos_proibidos", []) if re.search(rf"\b{re.escape(t)}\b", mensagem, re.IGNORECASE)
    ]
    if achados_proibidos:
        motivos.append(f"mensagem_1 contém termo proibido: {achados_proibidos}")

    config_afirmacao = config.get("afirmacao")
    if config_afirmacao:
        resultados = afirmacao.afirmacoes_de_resultado(mensagem, config_afirmacao)
        if resultados:
            motivos.append(f"mensagem_1 afirma resultado/causa não observado (sem 'puede'/'podría'): {resultados}")

    trecho_site = dados.get("trecho_site")
    texto_site_entrada = entrada.get("texto_site") or ""
    if trecho_site is not None:
        if not isinstance(trecho_site, str) or not trecho_site.strip():
            motivos.append("trecho_site deve ser string não vazia ou null")
        elif not texto_site_entrada:
            motivos.append("trecho_site citado sem texto_site na entrada -- nada a citar")
        elif _normalizar_para_comparacao(trecho_site) not in _normalizar_para_comparacao(texto_site_entrada):
            motivos.append(f"trecho_site não existe literalmente no texto do site: {trecho_site!r}")
        else:
            termos_pessoais = [
                t for t in config.get("termos_proibidos_trecho_site", [])
                if _normalizar_forte(t) in _normalizar_forte(trecho_site)
            ]
            if termos_pessoais:
                motivos.append(f"trecho_site contém detalhe pessoal proibido: {termos_pessoais}")
    elif texto_site_entrada:
        motivos.append("mensagem sem detalhe do site -- trecho_site é obrigatório quando texto_site está na entrada")

    if nome_negocio and not excecoes.get("nome_negocio"):
        candidatos_nome = {nome_negocio}
        nome_limpo = nome_comercial_limpo(nome_negocio)
        if nome_limpo:
            candidatos_nome.add(nome_limpo)
        mensagem_normalizada = _normalizar_forte(mensagem)
        genericas = _genericas_normalizadas(palavras_genericas_nome)
        achados_nome = []
        for c in candidatos_nome:
            c_normalizado = _normalizar_forte(c)
            if not c_normalizado or c_normalizado not in mensagem_normalizada:
                continue
            palavras_candidato = c_normalizado.split()
            if palavras_candidato and all(p in genericas for p in palavras_candidato):
                continue  # só palavras genéricas (nicho/cidade/conectoras) -- não é o nome vazando
            achados_nome.append(c)
        if achados_nome:
            motivos.append(f"mensagem_1 cita o nome do negócio: {achados_nome}")

    mensagem_para_extenso = mensagem
    for palavra in excecoes.get("numeros_por_extenso") or ():
        mensagem_para_extenso = re.sub(rf"\b{re.escape(palavra)}\b", " ", mensagem_para_extenso, flags=re.IGNORECASE)
    numeros_mensagem = _numeros(mensagem) | _numeros_por_extenso(mensagem_para_extenso, config)
    numeros_entrada = _numeros(json.dumps(entrada, ensure_ascii=False))
    numeros_fora = numeros_mensagem - numeros_entrada
    if numeros_fora:
        motivos.append(f"mensagem_1 cita número fora da entrada: {sorted(numeros_fora)}")

    return ResultadoValidacao(valido=not motivos, motivos=motivos, dados=dados)
