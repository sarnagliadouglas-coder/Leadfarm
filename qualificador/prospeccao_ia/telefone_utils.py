"""Regra única de telefone / celular espanhol.

Antes esta mesma regra vivia duplicada em dois lugares, com normalizações
ligeiramente diferentes:
  - lead_qualification._numero_nacional_espanhol / _e_movel_espanhol (filtro de
    contatabilidade da Onda 1);
  - output_json._contato (campo whatsapp_apto do contrato de saída).

Agora as duas importam daqui. 100% Python, $0, sem LLM. Não decide corte nem
prioridade — só descreve o fato "este número é um celular espanhol (prefixo 6/7)".

6 e 7 são os dois prefixos de celular espanhol (a faixa 7XX foi liberada para
celular em 2021; antes só existia como fixo em alguns indicativos). 8/9 são fixo.
"""
import re

PREFIXOS_MOVEL_ESPANHOL = ("6", "7")


def numero_nacional_espanhol(telefone) -> str:
    """Normaliza para o número nacional (9 dígitos, sem código de país) antes de
    checar o prefixo -- os dados chegam em formatos variados: "+34 6xx xxx xxx",
    "0034 6xx...", "6xx xxx xxx", com ou sem espaço/hífen. Devolve "" quando não
    dá para normalizar (vazio, ou nenhum dígito)."""
    bruto = (telefone or "").strip()
    digitos = re.sub(r"\D", "", bruto)
    if not digitos:
        return ""
    if bruto.startswith("00"):
        digitos = digitos[2:]
    if digitos.startswith("34") and len(digitos) > 9:
        digitos = digitos[2:]
    return digitos


def e_movel_espanhol(telefone) -> bool:
    """True se o número, normalizado, começa com prefixo de celular espanhol (6/7)."""
    numero = numero_nacional_espanhol(telefone)
    return bool(numero) and numero[0] in PREFIXOS_MOVEL_ESPANHOL


def classificar_celular_espanhol(telefone) -> dict:
    """Forma estruturada da mesma decisão: {numero_nacional, e_movel}."""
    numero = numero_nacional_espanhol(telefone)
    return {
        "numero_nacional": numero,
        "e_movel": bool(numero) and numero[0] in PREFIXOS_MOVEL_ESPANHOL,
    }
