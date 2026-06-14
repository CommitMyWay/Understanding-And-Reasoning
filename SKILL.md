---
name: voc-task-understanding
description: "Voice of Customer (VoC) — Task Understanding & Interactive Reasoning. Parses user intent for product/marketing/quality analysis requests, demands missing parameters via ask_for_parameters tool before proceeding, builds a structured role-based analysis plan (PO, MKT, QE), and maintains conversation context for deep-dive follow-ups. Trigger: any request to analyze an app, product, brand, or customer feedback (e.g., 'analyze MoMo', 'why is Login complained about', 'deep dive checkout issues', 'what are users saying about feature X'). Outputs a flat intent JSON for downstream skills (data source, report). DO NOT use for data fetching (/voc-datasource) or report rendering (/voc-report)."
---

# VoC Task Understanding & Interactive Reasoning

This skill powers the **reasoning front-end** of the Voice of Customer agent. It transforms an ambiguous user request into a fully resolved, structured intent object that downstream skills can execute — without requiring the user to know the data model or query syntax up front.

When the intent is fully resolved and confirmed, the skill emits a **flat intent JSON** (see `references/output-schema.md`) consumed by `/voc-datasource` and `/voc-report`.

> **Scope boundary**: This skill does NOT fetch data, generate analysis results, or render reports.
> Its sole outputs are JSON objects formatted via `tools/response_formatter.py`.

---

## (**CRITICAL**) JSON-Only Output Rule

**This skill NEVER outputs plain text.** Every agent turn must end with exactly one call to `tools/response_formatter.py` and output its JSON result verbatim. No prose, no markdown, no explanation alongside the JSON.

### FE API Contract — 4 output shapes

| Stage | When | Shape |
|---|---|---|
| **1. Query echo** | Immediately on any user input | `{"query": "..."}` |
| **2. Clarifying questions** | One or more required fields missing | `{"query": "...", "suggestedQuestions": [...]}` |
| **3. Plan confirmation** | All fields resolved, awaiting user confirm | `{"query": "...", "focusArea": "..."}` |
| **4. Execution plan** | After user confirms | `{"query": "...", "subject": ..., "plan_steps": [...], ...}` |

#### Shape 2 — suggestedQuestions
```json
{
  "query": "Analyze TikTok Shop",
  "suggestedQuestions": [
    {
      "id": "q_market",
      "question": "Which market should I analyze TikTok Shop in?",
      "choices": ["Vietnam", "Indonesia", "UK", "USA", "...", "Suggest another market...", "Other (type your own)..."]
    },
    {
      "id": "q_target_user",
      "question": "What is the goal of this TikTok Shop analysis?",
      "choices": ["Product", "Marketing", "Quality", "Suggest another goal type...", "Other (type your own)..."]
    }
  ]
}
```
`choices` **always** ends with `"Suggest another {field}..."` + `"Other (type your own)..."`.

#### Shape 3 — focusArea
```json
{
  "query": "looks good",
  "focusArea": "Target Product: TikTok Shop. Research goal: crash in payment. Lens: Quality Engineering (QE). Market: UK. Customized parameters: Date Range: last 90 days, Sources: App Store, CH Play."
}
```

#### Shape 4 — Execution plan (flat intent JSON + query)
```json
{
  "query": "go",
  "subject": "TikTok Shop",
  "market": "UK",
  "target_user": "quality",
  "goal": "crash in payment",
  "focus": null,
  "data_source": ["App Store", "CH Play"],
  "filters": {"time_range": "last_90_days", ...},
  "clarifications_done": [...],
  "plan_steps": [...]
}
```

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
- [ ] `target_user` — exactly one of `product` | `marketing` | `quality`
- [ ] `goal` — non-null free-text research objective
- [ ] User responded with an explicit confirmation keyword (see Confirmation Keywords)
- [ ] PII stripped from all fields via `context_manager.strip_pii`

Skipping any item is not permitted regardless of how confident the agent is about the values.

---

## Mandatory Process — Must follow in order

> **SILENT EXECUTION RULE**: All steps below are internal reasoning steps. Do NOT narrate them, label them, or show their status to the user. Do NOT output "Mode 1", "Bước 1", field checklists, or internal state. The only things the agent surfaces to the user are: a clarifying question, a plan summary, or the final intent JSON.

### Mode 1

1. **Classify mode** — confirm new analysis (not follow-up). *[internal]*
2. **Echo query** — call `tools/response_formatter.py query --message "<user input>"`. Output the result verbatim.
3. **Parse intent** — run `tools/analyze_prompt.py`. *[internal]*
4. **Check missing required fields** (`subject`, `market`, `target_user`, `goal`). If any null:
   - Call `tools/clarification_engine.py --batch` to get all missing questions at once.
   - Call `tools/response_formatter.py questions --message "..." --questions '[...]'`.
   - **STOP. Output the `suggestedQuestions` JSON verbatim. Nothing else.**
   - For each user answer, call `tools/ask_for_parameters.py respond` to record the value.
   - Re-run `analyze_prompt.py` and repeat until all fields resolved.
5. **Verify Pre-Output Gate** — all items checked. *[internal]*
6. **Build plan** — run `tools/conversation_planner.py --mode initial`. *[internal]*
7. **Present confirmation** — call `tools/response_formatter.py focus_area --message "..." --intent '...'`. Output verbatim.
8. **Wait for user confirm** — accepted keywords: yes / go / confirm / ok / đồng ý / tiến hành / ...
9. **Strip PII** — run `context_manager.strip_pii`. *[internal]*
10. **Emit execution plan** — call `tools/response_formatter.py plan --message "<confirm word>" --intent '...'`. Output verbatim → pass to `/voc-datasource`.

### Mode 2

1. **Classify mode** — follow-up on an already-confirmed analysis. *[internal]*
2. **Echo query** — `response_formatter.py query`. Output verbatim.
3. **Extract focus** — run `tools/analyze_prompt.py`. *[internal]*
4. **Do NOT re-ask** `subject`, `market`, `target_user`, or `goal`.
5. If focus is ambiguous, call `clarification_engine.py --batch` → `response_formatter.py questions`.
6. **Build deep-dive plan** — run `tools/conversation_planner.py --mode deep_dive`. *[internal]*
7. **Emit updated plan** — `response_formatter.py plan --message "..." --intent '...'`. Output verbatim.

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
- `target_user` valid values: `product`, `marketing`, `quality`.
- `goal` valid values: any non-empty free-text string (no validation).
- `data_source` valid values: `App Store`, `CH Play`, `Youtube`, `Voz`, `Tinhte`, `Reddit`, `All`.

---

## Core Concepts

| Concept | Description |
|---|---|
| **Subject** | Product, app, brand, or feature being analyzed (e.g., "MoMo", "Login flow"). Required. |
| **Market** | Geographic or demographic scope (e.g., "Vietnam", "Southeast Asia"). Required. |
| **Target User** | Who is running the analysis: `product` (PO lens) \| `marketing` (MKT lens) \| `quality` (QE lens). Required. |
| **Goal** | Free-text research objective, e.g. "pain points in payment flow", "features users want most". Required. |
| **Data Source** | Which platforms to pull reviews from. Default = all: `App Store`, `CH Play`, `Youtube`, `Voz`, `Tinhte`, `Reddit`. Updatable during plan confirmation. |
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
| `target_user` | ✅ | — must ask |
| `goal` | ✅ | — must ask (free-text) |
| `data_source` | ❌ | all 6 sources |
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

## Response Format

**All responses are JSON only.** Never output plain text. Always call `response_formatter.py` and output its result verbatim.

| ❌ INCORRECT | ✅ CORRECT |
|---|---|
| `Bước 1: ... Câu hỏi 1: ...` (plain text) | `{"query":"phân tích ZaloPay","suggestedQuestions":[...]}` |
| `I will now ask about the market. Which market?` | `{"query":"Analyze ZaloPay","suggestedQuestions":[{"id":"q_market","question":"...","choices":[...]}]}` |
| Bulleted plan summary in prose | `{"query":"ok","focusArea":"Target Product: ZaloPay. Research goal: ..."}` |
| Raw intent JSON without query field | `{"query":"go","subject":"ZaloPay","market":"Vietnam",...}` |

---

## Example Flow

```
[Mode 1]
User:   Analyze MoMo
Agent:  → ask_for_parameters(field=market, question="Which market should I analyze MoMo in?")
User:   Vietnam
Agent:  → ask_for_parameters.respond(field=market, value="Vietnam")
        → ask_for_parameters(field=target_user, question="What is the goal of this MoMo analysis?",
                             options=["Product","Marketing","Quality"])
User:   Quality
Agent:  → ask_for_parameters.respond(field=target_user, value="quality")
        → ask_for_parameters(field=goal, question="What specifically would you like to find out about MoMo?
                             (e.g. 'most reported crashes', 'performance issues on Android')")
User:   crash patterns in payment flow
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
