---
name: reasoning-and-understanding
description: "Front-door reasoning stage for a Voice-of-Customer (VoC) research agent. Parses the user's research prompt, decides whether it carries enough information to scope the work, and either asks batched clarifying questions or hands off a confirmed analysis plan. Required fields it checks: user role (Marketing or Product Owner), the company/product to research, the feature/topic to focus on, and the research goal (data sources default to all when unspecified). Outputs a strict JSON contract for the frontend: CLARIFICATION_REQUIRED, PLAN_CONFIRMATION, or ERROR. Trigger this skill at the very start of any VoC request — when a user pastes a research prompt, asks to analyze feedback/reviews/ratings about a product, or says things like 'research negative feedback', 'analyze reviews', 'I am a marketer/product owner and want to research X'. DO NOT use this skill for the later pipeline stages (web scraping, review classification, report generation, export, scheduling) — it only understands the request and confirms the plan."
---

# Reasoning & Understanding

This skill is the **first stage** of the VoC agent pipeline. It turns a raw user prompt into
either a set of clarifying questions or a confirmed, machine-readable analysis plan. It does
**not** scrape data, classify reviews, or write reports — those are downstream stages.

Your job each turn:

1. Understand the user's request (natural-language reasoning — your job, not the tool's).
2. Decide whether the request has enough information to scope the analysis.
3. Emit the correct JSON contract for the frontend by **calling the tool** — never hand-write JSON.

## The deterministic tool

All JSON the frontend receives is produced by `tools/voc_reasoning.py` so the schema is always
valid. You do the reasoning; the tool does the formatting.

```bash
python tools/voc_reasoning.py validate '<state-json>'   # internal: complete? what's missing?
python tools/voc_reasoning.py clarify  '<state-json>'   # -> CLARIFICATION_REQUIRED
python tools/voc_reasoning.py plan     '<state-json>'   # -> PLAN_CONFIRMATION
python tools/voc_reasoning.py error    '<message>' [--query '<raw input>']  # -> ERROR
```

`validate` prints an internal helper object **for you** (not for the frontend). `clarify`, `plan`,
and `error` print the frontend payload. See `references/output-schema.md` for every field.

## The STATE object

You maintain one accumulating STATE object across the whole chat thread. Each turn, merge the
user's new input into it, then pass it to the tool. Shape:

```json
{
  "raw_query": "<the user's most recent raw input>",
  "role": null,            // -> "Marketing" | "Product Owner" (normalize synonyms yourself)
  "subject": null,         // company/product, e.g. "Zalopay"
  "focus": null,           // feature/topic, e.g. "transfer money"
  "objective": null,       // the research goal
  "data_sources": [],      // names the user gave; leave [] to default to ALL five
  "competitors": [],       // research targets; defaults to [subject]
  "market": null,          // defaults to "Vietnam"
  "filters": { "time_range": null, "sentiment": null, "keywords": [] },
  "clarify_fields": null,  // optional: ask ONLY these fields (edge-case re-clarify)
  "reclarify_reason": null,// optional: human reason shown on a 2nd clarification round
  "overrides": {}          // optional: per-field {choices/recommended/question} overrides
}
```

## The loop

1. **Always echo the query.** Whenever there is user input, the tool emits a separate
   `{"query": "..."}` object (line 1) ahead of the response envelope (line 2). Put the raw input
   in `state.raw_query` so it is echoed.
2. **Extract & normalize.** Pull `role`, `subject`, `focus`, `objective`, and any named data
   sources from the prompt. Map role synonyms ("marketer" → Marketing, "PO"/"product manager"
   → Product Owner). Roles outside {Marketing, Product Owner} are **not valid** — treat as missing.
3. **Validate.** Run `validate`. It returns `complete`, `missing[]`, and `ready_for`.
4. **If incomplete → clarify.** Run `clarify`. It batches one question per missing field
   (all in a single response — never drip them one at a time). Then write a short, friendly
   human message alongside the JSON.
5. **If complete → plan.** Run `plan`. It applies defaults (data_sources → all five if none
   named, market → Vietnam, time_range → last_90_days, sentiment → negative when the goal targets
   negative feedback, else all) and returns the PLAN_CONFIRMATION envelope. Summarize the plan in
   plain language for the user too.
6. **On bad/garbled input → error.** Run `error` with a clear message.

## Clarification rules (summary)

- Only **four fields gate** the pipeline: role, subject, focus, objective. `data_sources` never
  blocks — if the user named none, it defaults to all five.
- Batch **every** missing question into one `CLARIFICATION_REQUIRED` response.
- Each select question offers **1–3 choices**, never more, and **always** sets `allow_other: true`
  so the user can type a free answer. Never put the string "Other" inside `choices`.
- **Edge case — off-topic / vague answer.** If the user answers a clarifying question with
  something invalid (e.g. role = "DEV", or objective = "measure something"), set
  `clarify_fields` to just that field and `reclarify_reason` to a short explanation, then run
  `clarify` again. This produces the second-round shape with a `reason` field.

Full rules and the question bank: `references/clarification-rules.md`.
Full JSON schemas with examples: `references/output-schema.md`.

## Output contract reminder

The frontend reads **two separate JSON objects** per turn (JSONL — one per line):

```
{"query": "I am a Marketer in fintech company..."}
{"response_type": "CLARIFICATION_REQUIRED", "payload": { ... }}
```

`response_type` is always exactly one of: `CLARIFICATION_REQUIRED`, `PLAN_CONFIRMATION`, `ERROR`.
Always run the tool to generate these — do not write the JSON by hand.
