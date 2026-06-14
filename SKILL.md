---
name: voc-task-understanding
description: "Voice of Customer (VoC) — Task Understanding & Interactive Reasoning. Parses user intent for product/market/competitive analysis requests, demands missing parameters via ask_for_parameters tool before proceeding, builds a structured analysis plan, and maintains conversation context for deep-dive follow-ups. Trigger: any request to analyze an app, product, brand, or customer feedback (e.g., 'analyze MoMo', 'why is Login complained about', 'deep dive checkout issues', 'what are users saying about feature X', 'compare ZaloPay vs MoMo'). Outputs a flat intent JSON for downstream skills (data source, report). DO NOT use for data fetching (/voc-datasource) or report rendering (/voc-report)."
---

# VoC Task Understanding & Interactive Reasoning

This skill powers the **reasoning front-end** of the Voice of Customer agent. It transforms an ambiguous user request into a fully resolved, structured intent object that downstream skills can execute — without requiring the user to know the data model or query syntax up front.

When the intent is fully resolved and confirmed, the skill emits a **flat intent JSON** (see `references/output-schema.md`) consumed by `/voc-datasource` and `/voc-report`.

> **Scope boundary**: This skill does NOT fetch data, generate analysis results, or render reports.
> Its sole outputs are: clarifying questions (via `ask_for_parameters`), a plan summary, and an intent JSON.

---

## Mode 1: Prompt Analysis
**Triggered by**: any new analysis request (product, app, brand, feature, competitive).
**Ending with**: all 3 required fields resolved → plan confirmed by user → intent JSON emitted.

## Mode 2: Dive Deep
**Triggered by**: a follow-up question referencing a specific insight or feature AFTER Mode 1 is complete (e.g., "Why is Login complained about?", "Break down the Payment timeout issue").
**Ending with**: `focus` field updated → deep-dive intent JSON emitted.

> Classify the mode FIRST before taking any action. Do not skip classification.

---

## (**IMPORTANT**) Pre-Output Gate

**DO NOT emit intent JSON until every item below is satisfied:**

- [ ] `subject` — non-null, resolved via parse or `ask_for_parameters`
- [ ] `market` — non-null, geographic or demographic scope
- [ ] `goal` — exactly one of `product` | `marketing` | `competitive`
- [ ] User responded with an explicit confirmation keyword (see Confirmation Keywords)
- [ ] PII stripped from all fields via `context_manager.strip_pii`

Skipping any item is not permitted regardless of how confident the agent is about the values.

---

## Mandatory Process — Must follow in order

### Mode 1

1. **Classify mode** — confirm this is a new analysis request (not a follow-up). If unclear, treat as Mode 1.
2. **Parse intent** — run `tools/analyze_prompt.py` with the user message and current context.
3. **Check missing required fields** (`subject`, `market`, `goal`). For each null field:
   - Call `tools/ask_for_parameters.py request` with `--field`, `--reason`, `--question`.
   - **STOP. Do not proceed to the next step.** Wait for user reply.
   - On user reply, call `tools/ask_for_parameters.py respond` to record the value.
   - Repeat until all required fields are resolved.
4. **Verify Pre-Output Gate checklist** — all 5 items must be checked before continuing.
5. **Build plan** — run `tools/conversation_planner.py --mode initial`.
6. **Present plan summary** to user and ask for confirmation. Wait for explicit confirmation keyword.
7. **Strip PII** — run `context_manager.strip_pii`.
8. **Emit intent JSON** — output the JSON object and pass to `/voc-datasource`.

### Mode 2

1. **Classify mode** — confirm this is a follow-up referencing a specific feature/insight on an already-confirmed analysis.
2. **Extract focus** — run `tools/analyze_prompt.py` to detect focus topic and keywords.
3. **Do NOT re-ask** `subject`, `market`, or `goal` — they are already resolved.
4. Only call `ask_for_parameters` if the focus topic is genuinely ambiguous (no clear referent).
5. **Build deep-dive plan** — run `tools/conversation_planner.py --mode deep_dive`.
6. **Emit updated intent JSON** with `focus` set.

---

## ask_for_parameters — Tool Reference

Use this tool whenever a required field is missing or ambiguous. Do NOT ask via prose text.

```
tools/ask_for_parameters.py request
  --session  <session-id>
  --field    subject | market | goal | focus
  --reason   "why agent is blocked — be specific"
  --question "exact single question for user"
  --options  '["option1","option2"]'   (optional)
```

```
tools/ask_for_parameters.py respond
  --session  <session-id>
  --field    <same field>
  --value    "<user's answer>"
```

**Rules:**
- One call per missing field. Never bundle two fields in one call.
- If `status = max_retries_reached`, use a sensible default and proceed without asking again.
- If `status = invalid_value`, call `request` again for that field.
- `goal` valid values: `product`, `marketing`, `competitive`.

---

## Core Concepts

| Concept | Description |
|---|---|
| **Subject** | Product, app, brand, or feature being analyzed (e.g., "MoMo", "Login flow"). Required. |
| **Market** | Geographic or demographic scope (e.g., "Vietnam", "Southeast Asia"). Required. |
| **Goal** | `product` (feature/UX insights) \| `marketing` (brand/perception) \| `competitive` (vs. competitors). Required. |
| **Focus** | Sub-scope for deep dives (e.g., "Login", "Payment timeout"). Optional, set in Mode 2. |
| **Filters** | Optional: time range, platform, sentiment, keywords. Defaults applied if not specified. |
| **Clarifications Done** | Ordered list of fields resolved via `ask_for_parameters` this session. |
| **Plan Steps** | Ordered analysis actions emitted in intent JSON. |
| **Intent JSON** | Flat output object. See `references/output-schema.md`. |

---

## Required vs Optional Fields

| Field | Required | Default if missing |
|---|---|---|
| `subject` | ✅ | — must ask |
| `market` | ✅ | — must ask |
| `goal` | ✅ | — must ask |
| `focus` | ❌ | `null` |
| `filters.time_range` | ❌ | `last_90_days` |
| `filters.platform` | ❌ | `all` |
| `filters.sentiment` | ❌ | `all` |
| `filters.keywords` | ❌ | `[]` |

---

## Confirmation Keywords

Wait for one of these before emitting intent JSON (case-insensitive):

**English:** yes, confirm, ok, okay, approve, proceed, go ahead, do it, ship it, lgtm, sure, correct, sounds good, looks good, go

**Vietnamese:** có, đúng, ổn, được, tiến hành, làm đi, ok, đồng ý, chính xác, chuẩn, tiếp tục

Any other response (questions, corrections, new instructions) = not a confirmation. Update the plan and re-present.

---

## Anti-Speculation Rules

- **DO NOT** include any complaint data, user quotes, ratings, or analysis results in any response.
- **DO NOT** suggest what the data might show before it is fetched.
- **DO NOT** emit intent JSON before the Pre-Output Gate is satisfied.
- **DO NOT** proceed past step 3 in Mode 1 while any required field is null.
- **DO NOT** re-ask a field that was already resolved in this session.
- Present only: clarifying questions, plan structure, and the intent JSON. Nothing else.

---

## Language

Detect language from the user's message. Respond in the same language. Skill internals (field names, JSON keys, tool commands) remain in English. If the user switches language mid-conversation, follow their current language.

---

## Data Privacy

- Run `context_manager.strip_pii` before saving context or emitting intent JSON.
- PII stripped: email addresses, Vietnamese phone numbers, numeric user/account IDs.
- Replaced with: `[REDACTED]`.
- If a user's answer consists entirely of PII, call `ask_for_parameters request` again and ask for the product name instead.

---

## Example Flow

```
[Mode 1]
User:   Analyze MoMo
Agent:  → ask_for_parameters(field=market, question="Which market should I analyze MoMo in?")
User:   Vietnam
Agent:  → ask_for_parameters.respond(field=market, value="Vietnam")
        → ask_for_parameters(field=goal, question="Is this for Product, Marketing, or Competitive analysis?",
                             options=["product","marketing","competitive"])
User:   Product
Agent:  → ask_for_parameters.respond(field=goal, value="product")
        → verify Pre-Output Gate ✅
        → conversation_planner(mode=initial)
        → "Here's my plan: [5 steps]. Shall I proceed?"
User:   Yes
Agent:  → strip_pii → emit intent JSON → /voc-datasource

[Mode 2 — same session]
User:   Why is Login complained about so much?
Agent:  → classify: Mode 2 (deep-dive, all required fields already resolved)
        → analyze_prompt detects focus=Login
        → conversation_planner(mode=deep_dive)
        → emit updated intent JSON with focus=Login → /voc-datasource
```

---

## Troubleshooting

| Symptom | Likely Cause | Fix |
|---|---|---|
| Agent emits JSON with null fields | Pre-Output Gate not enforced | Verify all 5 checklist items before step 8 |
| Agent re-asks a resolved field | Context not saved after `ask_for_parameters respond` | Call `context_manager.save_context` after each respond |
| Deep dive resets to Mode 1 | `mode` detection not checking context | Pass full context to `analyze_prompt.py` |
| focus = "Why" or "Tell" | Stop words not filtered in `_extract_focus` | Check `FOCUS_STOP_WORDS` list in `analyze_prompt.py` |
| Agent asks two questions at once | Called `ask_for_parameters` twice before waiting | One request call per turn; wait for respond before next |
| `max_retries_reached` returned | Field asked too many times without valid answer | Use default value, log in `clarifications_done`, proceed |
| PII in emitted JSON | `strip_pii` not called | Always call `context_manager.strip_pii` before emit |
| `goal` invalid value | User gave unexpected answer | `ask_for_parameters respond` returns `invalid_value`; call request again |
