# COMERCIAL — primeira mensagem de prospecção

O COMERCIAL recebe os leads já qualificados pelo QUALIFICADOR e produz uma
**planilha de envio**: para cada lead, o argumento (ângulo) mais adequado, a
primeira mensagem pronta e o canal para enviá-la. O envio é feito à mão, pelo
vendedor. Depois, um comando registra quem foi contatado, para que as próximas
planilhas deixem essas pessoas de fora.

A primeira mensagem **não usa IA**: o ângulo é escolhido por regra e o texto vem
de modelos fixos, editáveis sem mexer no código.

## Fluxo

```
contrato JSON + CSV do QUALIFICADOR
  → contrato_loader    (valida contra o schema e trava a versão do contrato)
  → angulo_mensagem    (escolhe o ângulo por regra e monta a mensagem do modelo)
  → validador_mensagem (recusa o que afirma algo não medido)
  → planilha_envio     (.xlsx: abas Geral, Nata e Como usar)
  → registro_abordagens (depois dos envios: quem foi contatado ou pulado)
```

## Como o ângulo é escolhido

- **Leads com site próprio:** o primeiro ângulo em que o lead se encaixa —
  contato difícil no celular, poucas avaliações em comparação com um concorrente
  da mesma busca, ou site lento no celular. Sem ângulo, sem mensagem.
- **Leads sem site próprio** (nenhum site, portal, rede social, construtor
  gratuito): um modelo para cada situação.

Cada mensagem segue a estrutura *fato medido → consequência plausível → pergunta
ou oferta pequena*. Um validador determinístico bloqueia, entre outras coisas,
número que não veio da medição, preço, link, nome do negócio e frase que afirma
um resultado não medido. A frase de abertura é testada em duas variantes (A/B),
com o mesmo corpo de mensagem.

## Como rodar

```bash
# gerar a planilha de envio a partir do lote mais recente do QUALIFICADOR
python ferramentas/planilha_envio.py --saida-dir "<pasta de saída>"

# depois dos envios: registrar quem foi contatado
python ferramentas/registro_abordagens.py "<planilha preenchida>"

# conferir se algum envio ainda não foi registrado (só lê)
python ferramentas/pendencias_registro.py "<planilha preenchida>"
```

A localização do contrato é resolvida automaticamente; variáveis opcionais em
[`.env.example`](.env.example).

## Estrutura

```
comercial/
├── config/        textos das mensagens, regras de ângulo e listas do validador (JSON)
├── ferramentas/   código (Python)
├── prompts/       prompt de uma versão com IA, fora do fluxo atual
└── tests/         suíte pytest
```

`ferramentas/llm_cliente.py`, `pipeline_estrategia_mensagem.py` e peças
relacionadas são uma versão da mensagem escrita por IA, **fora do fluxo atual**:
o teste mostrou que o que decide é o argumento, não quem escreve.

## Testes

```bash
python -m pytest -q
```

Todos os dados de leads em testes e exemplos são **fictícios** (por exemplo,
"Fisioficticia Salud", telefone `+34 600 000 000`). Dados reais — lotes,
planilhas, registro de abordagens — ficam fora do repositório.
