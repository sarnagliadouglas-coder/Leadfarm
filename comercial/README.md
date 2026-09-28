# COMERCIAL — first outreach message

The COMERCIAL module takes the leads already qualified by the QUALIFICADOR and turns
them into an **outreach sheet**: for each lead, the most relevant angle, a ready-to-send
first message and the channel to send it through. Messages are sent by hand, a few per
day — never in bulk. Afterwards, one command logs who was contacted, so future sheets
leave them out.

The first message **does not use an LLM**: the angle is chosen by explicit rules and the
text comes from fixed templates that can be edited without touching the code.

## Flow

```
JSON hand-off + human CSV from the QUALIFICADOR
  → contrato_loader     (validates against the JSON Schema, pins the contract version)
  → angulo_mensagem     (picks the angle by rule, fills the template)
  → validador_mensagem  (rejects anything that asserts what was not measured)
  → planilha_envio      (.xlsx with three tabs: Geral, Nata, Como usar)
  → registro_abordagens (after sending: who was contacted or skipped)
```

## How the angle is chosen

- **Leads with their own website:** the first angle the lead fits — contact is hard on a
  phone, few reviews compared with a competitor from the same search, or a slow site on
  mobile. No angle, no message.
- **Leads without their own website** (none, a directory portal, a social network, a
  free site builder): one template per situation.

Every message follows *measured fact → plausible consequence → small question or
ready-made offer*. A deterministic validator blocks, among other things, any number that
did not come from a measurement, prices, links, the business name, and sentences that
state an unmeasured outcome ("you are losing patients") rather than a hedged one ("this
can add friction"). The opening line is A/B-tested in two variants with an identical
message body, balanced by angle and channel.

## Running it

```bash
# build the outreach sheet from the latest QUALIFICADOR batch
python ferramentas/planilha_envio.py --saida-dir "<output folder>"

# after sending: log who was contacted
python ferramentas/registro_abordagens.py "<filled-in sheet>"

# check whether any sent message is still missing from the log (read-only)
python ferramentas/pendencias_registro.py "<filled-in sheet>"
```

The contract location is resolved automatically; optional variables are listed in
[`.env.example`](.env.example).

## Layout

```
comercial/
├── config/        message templates, angle rules and validator word lists (JSON)
├── ferramentas/   code (Python)
├── prompts/       prompt for an LLM-written variant, not used in the current flow
└── tests/         pytest suite
```

`ferramentas/llm_cliente.py`, `pipeline_estrategia_mensagem.py` and related pieces are an
LLM-written version of the message, **outside the current flow**: testing showed that the
angle matters, not who writes the sentence.

## Tests

```bash
python -m pytest -q
```

Every lead in tests and examples is **fictitious** (e.g. "Fisioficticia Salud", phone
`+34 600 000 000`). Real data — batches, sheets, the contact log — stays off this
repository.
