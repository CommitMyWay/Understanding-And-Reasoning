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
python3 tools/voc_reasoning.py validate '<state-json>'   # internal: complete? what's missing?
python3 tools/voc_reasoning.py clarify  '<state-json>'   # -> CLARIFICATION_REQUIRED
python3 tools/voc_reasoning.py plan     '<state-json>'   # -> PLAN_CONFIRMATION
python3 tools/voc_reasoning.py error    '<message>' [--query '<raw input>']  # -> ERROR
```

`validate` prints an internal helper object **for you** (not for the frontend). `clarify`, `plan`,
and `error` print the frontend payload. See `references/output-schema.md` for every field.

## The STATE object

You maintain one accumulating STATE object across the whole chat thread. Each turn, merge the
user's new input into it, then pass it to the tool. Shape:

```json
{
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
  "questions": []          // YOU author these — contextual question objects (see below)
}
```

### You author the clarifying questions (no canned choices)

The tool ships **no hard-coded answer choices**. When clarification is needed, YOU build each
question object and put them in `state.questions`, deriving the `choices`/`recommended` from the
user's actual prompt so they are specific (e.g. for "research VNG" the focus choices should be
about VNG's products like ZaloPay payments — not generic placeholders). Each object:

```json
{ "key": "focus", "type": "single_select", "question": "...", "choices": ["...", "..."], "recommended": "...", "allow_other": true }
```

Rules the tool enforces for you: `<= 3` choices, never the literal "Other" in `choices`,
`allow_other` always `true`, and `role` choices are always exactly `Marketing` / `Product Owner`.
If you author no questions, the tool falls back to asking the missing fields as free text.

## The loop

1. **Extract & normalize.** Pull `role`, `subject`, `focus`, `objective`, and any named data
   sources from the prompt. Map role synonyms ("marketer" → Marketing, "PO"/"product manager"
   → Product Owner). Roles outside {Marketing, Product Owner} are **not valid** — treat as missing.
2. **Validate.** Run `validate`. It returns `complete`, `missing[]`, and `ready_for`.
3. **If incomplete → clarify.** Author one contextual question per missing field into
   `state.questions` (choices derived from the user's prompt), then run `clarify`. Batch every
   missing field in a single response — never drip them one at a time.
4. **Prefer a deep-research intake, not the bare minimum.** The four gating fields decide whether
   planning is technically allowed, but your behavior should feel like a serious research setup
   flow rather than a minimal validator.

   - For short or broad prompts like `"analyze Shopee"` or `"research negative feedback"`, do
     **not** stop at only the missing gating fields if the request is still underspecified in a way
     that would weaken the plan.
   - In those cases, ask a richer bundled brief that usually includes some mix of:
     `competitors`, `market`, `time_range`, `data_sources`, `sentiment`, and `keywords`, in
     addition to any missing gating fields.
   - **Include a source-selection question when the prompt is broad.** Even though the backend
     defaults to all sources, the setup should still give the user a chance to narrow the crawl.
     Present `data_sources` as an optional tuning question, with the semantic default being
     **all sources** if the user does not express a preference.
   - Aim for **5–8 total questions/decisions** for broad prompts unless the user already provided
     strong detail. Keep them concise, high-signal, and directly useful.
   - Avoid redundant questions. If the user already specified a field clearly, do not ask it again.
   - Ask optional questions only when they would materially improve the downstream analysis plan.
5. **If complete → resolve apps, then plan.** Before `plan`, resolve the subject and each
   competitor against real store pages when possible. Use web search/fetch to confirm Google Play
   package names and App Store IDs, then store them in `state.resolved_apps`:

   ```json
   [
     {
       "name": "ZaloPay",
       "playId": "com.vinagame.zalopay",
       "appStoreId": "1107454800",
       "evidence": "https://play.google.com/store/apps/details?id=com.vinagame.zalopay"
     }
   ]
   ```

   Only include IDs you could verify from a real store page. If you cannot verify an ID, set that
   field to `null`. Then run `plan`. It applies defaults (data_sources → all five if none named,
   market → Vietnam, time_range → last_90_days, sentiment → negative when the goal targets
   negative feedback, else all) and returns the PLAN_CONFIRMATION envelope.
6. **On bad/garbled input → error.** Run `error` with a clear message.

**Output ONLY the JSON the tool prints — nothing else.** No greeting, no explanation, no
"let me know" sentence. Your entire response is the tool's JSON output verbatim.

## Clarification rules (summary)

- Only **four fields gate** the pipeline: role, subject, focus, objective. `data_sources` and
  `competitors` never block — if the user named no sources, they default to all five; if
  competitors are unspecified, ask only when that comparison would materially clarify the request,
  otherwise they default to `[subject]`.
- The gating fields define the minimum contract, **not** the ideal user experience. When the brief
  is broad, ask enough extra questions to make the setup feel like a thoughtful research intake.
- For prompts that are only a company/product name or a vague analysis request, it is usually too
  shallow to ask only 1–2 questions. Prefer a richer bundle covering goal, focus, comparison set,
  geography, and time horizon.
- Source scope should usually be one of those extra questions for broad prompts. The default may
  still be all five sources, but the user should be offered the chance to narrow the crawl.
- Batch **every** missing question into one `CLARIFICATION_REQUIRED` response.
- Each select question offers **1–3 choices**, never more, and **always** sets `allow_other: true`
  so the user can type a free answer. Never put the string "Other" inside `choices`.
- **Choices are contextual, never canned.** Derive them from the user's prompt. Only `role` has
  fixed choices (`Marketing` / `Product Owner`).
- **Edge case — off-topic / vague answer.** If the user answers a clarifying question with
  something invalid (e.g. role = "DEV", or objective = "measure something"), set
  `clarify_fields` to just that field and `reclarify_reason` to a short explanation, then run
  `clarify` again. This produces the second-round shape with a `reason` field.

Full rules and the question bank: `references/clarification-rules.md`.
Full JSON schemas with examples: `references/output-schema.md`.

## Output contract reminder

Your response is **JSON only** (no prose) — a single response envelope object:

```
{"response_type": "CLARIFICATION_REQUIRED", "payload": { ... }}
```

`response_type` is always exactly one of: `CLARIFICATION_REQUIRED`, `PLAN_CONFIRMATION`, `ERROR`.
There is **no `query` field** — the frontend owns that value and forwards it elsewhere; it is out
of this skill's scope. Always run the tool to generate the JSON — do not write it by hand.
