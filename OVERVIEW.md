# reasoning-and-understanding

The **first stage** of a Voice-of-Customer (VoC) research agent. It receives the user's raw
research prompt and either asks for the missing pieces or confirms a machine-readable analysis
plan that the downstream scraping/analysis stages consume.

## Where it sits in the pipeline

```
[user prompt] ──► reasoning-and-understanding ──► scraping ──► LLM analysis ──► report + options
                  (this skill)                    (downstream — not in this folder)
```

This folder implements **only** the reasoning/understanding step. It does not scrape, classify,
or generate reports.

## What it does

- Parses the prompt and checks four **gating fields**: role (`Marketing`/`Product Owner`),
  subject (product/company), focus (feature/topic), objective (goal).
- If anything is missing, returns batched clarifying questions (≤3 choices each, always with a
  free-text option) as `CLARIFICATION_REQUIRED`.
- When complete, returns a scoped `PLAN_CONFIRMATION` with intent + plan summary + estimated scope.
- Returns `ERROR` on unusable input. Output is JSON only — a single response envelope (the
  frontend owns the `query` value, so it is not part of this skill's output).

## Files

| path | purpose |
|------|---------|
| `SKILL.md` | the agent's operating procedure (read by the OpenClaw/GreenNode agent) |
| `tools/voc_reasoning.py` | deterministic validator/formatter — guarantees the FE JSON contract |
| `references/output-schema.md` | full JSON schemas + examples for all envelope types |
| `references/clarification-rules.md` | gating logic, question bank, edge cases |

## Quick test

```bash
# Fully specified prompt -> PLAN_CONFIRMATION
python3 tools/voc_reasoning.py plan '{"role":"Marketing","subject":"Zalopay","focus":"transfer money","objective":"research negative 1,2 star feedback and propose improvements","data_sources":["App Store","CH Play"]}'

# Missing fields -> CLARIFICATION_REQUIRED (agent authors contextual choices)
python3 tools/voc_reasoning.py clarify '{"role":"Marketing","subject":"VNG","questions":[{"key":"focus","type":"single_select","question":"Which VNG product should we focus on?","choices":["ZaloPay payments","ZaloPay wallet top-up","Zalo app"],"recommended":"ZaloPay payments","allow_other":true},{"key":"objective","type":"single_select","question":"What is your objective?","choices":["Find negative feedback & improve","Benchmark vs MoMo/VNPay"],"allow_other":true}]}'

# Re-clarify a bad role answer -> CLARIFICATION_REQUIRED with reason
python3 tools/voc_reasoning.py clarify '{"clarify_fields":["role"],"reclarify_reason":"DEV is not a supported role; pick Marketing or Product Owner."}'
```
