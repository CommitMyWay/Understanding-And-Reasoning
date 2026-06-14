---
name: voc-task-understanding
description: "Voice of Customer (VoC) — Task Understanding & Interactive Reasoning. Parses user intent for product/market analysis requests, asks ONE clarifying question at a time when information is missing, builds a structured analysis plan, and maintains conversation context for deep-dive follow-ups. Trigger: any request to analyze an app, product, brand, or customer feedback (e.g., 'analyze MoMo', 'why is Login complained about', 'deep dive checkout issues', 'what are users saying about feature X'). Outputs a flat intent JSON for downstream skills (data source, report). DO NOT use for data fetching (/voc-datasource) or report rendering (/voc-report)."
---

# VoC Task Understanding & Interactive Reasoning

This skill powers the **reasoning front-end** of the Voice of Customer agent. It transforms an ambiguous user request into a fully resolved, structured intent object that downstream skills can execute against — without requiring the user to know the data model or query syntax up front.

The skill operates in two phases:

- **1.1 Prompt Analysis** — parse the user's request, identify the subject/market/goal, detect missing fields, maintain conversation context, and ask one focused clarifying question per turn until the intent is unambiguous.
- **1.2 Dive-Deep Conversation** — once a base analysis is complete, handle follow-up questions, drill into specific insights (e.g., "why is Login complained about?"), and autonomously generate sub-questions to surface root causes.

When the intent is fully resolved, the skill emits a **flat intent JSON** (see `references/output-schema.md`) that the data source skill and report skill consume.

> **Scope boundary**: This skill does NOT fetch data or render reports. Its sole output is a structured intent object plus the next agent message (clarification question, plan summary, or deep-dive response).

---

## Interaction Guidelines

- **One question per turn** — never ask more than one clarifying question in a single response. Pick the highest-priority missing field (see `references/clarification-rules.md`) and ask only that.
- **Never assume intent** — if the subject is ambiguous (e.g., "analyze MoMo" could mean market analysis, competitor analysis, or internal product analysis), ask before proceeding.
- **Confirm the plan before handing off** — once all required fields are resolved, summarize the analysis plan in natural language and ask the user to confirm before emitting the intent JSON.
- **Detect and respond in the user's language** — if the user writes in Vietnamese, respond in Vietnamese. Skill internals (field names, JSON keys, code) remain in English.
- **Maintain context across turns** — every clarification answer is accumulated into the session context. Never re-ask a question the user already answered in this conversation.
- **Deep-dive trigger** — if the user asks a follow-up that references a specific insight (e.g., "why is Login complained about?"), treat it as a drill-down into the current analysis scope. Update the intent's `focus` field and emit a new plan step without restarting the full clarification flow.
- **Data privacy** — never log, echo back, or include in the intent JSON any personally identifiable information (PII) the user may mention (names, emails, user IDs). Strip PII before passing context downstream.
- **Guide first, execute only on confirmation** — if the user asks "how would you analyze X?", respond with an explanation only. Do not emit an intent JSON until the user explicitly asks you to proceed.

---

## Core Concepts

| Concept | Description |
|---|---|
| **Subject** | The product, app, brand, or feature being analyzed (e.g., "MoMo", "Login flow", "Checkout"). Required. |
| **Market** | The geographic or demographic scope (e.g., "Vietnam", "Southeast Asia", "18–25 age group"). Required. |
| **Goal** | The analysis objective: `product` (feature/UX insights), `marketing` (brand/perception insights), or `competitive` (vs. competitor). Required. |
| **Focus** | Optional sub-scope for deep dives (e.g., "Login", "Payment timeout"). Set on follow-up turns. |
| **Filters** | Optional constraints: time range, platform (iOS/Android/web), sentiment, rating band, keyword. |
| **Clarifications Done** | Ordered list of fields that were resolved through clarification questions this session. |
| **Plan Steps** | Ordered list of analysis actions the agent will execute (e.g., fetch reviews, cluster complaints, rank themes). |
| **Intent JSON** | The flat output object emitted when intent is fully resolved. Consumed by `/voc-datasource` and `/voc-report`. |
| **Session Context** | In-memory store of conversation history, resolved fields, and current intent state. Reset on new session. |

---

## Required vs. Optional Fields

| Field | Required | Source |
|---|---|---|
| `subject` | ✅ | Parsed from prompt or clarification |
| `market` | ✅ | Parsed from prompt or clarification |
| `goal` | ✅ | Parsed from prompt or clarification |
| `focus` | ❌ | Set on deep-dive follow-up |
| `filters.time_range` | ❌ | User-supplied or defaulted to last 90 days |
| `filters.platform` | ❌ | User-supplied or `all` |
| `filters.sentiment` | ❌ | User-supplied or `all` |
| `filters.keywords` | ❌ | Extracted from deep-dive question |

---

## Operations Summary

| Operation | Trigger | Tool |
|---|---|---|
| Parse initial prompt | User sends any analysis request | `tools/analyze_prompt.py` |
| Generate clarification question | Required field missing after parse | `tools/clarification_engine.py` |
| Store / retrieve context | Every turn | `tools/context_manager.py` |
| Build analysis plan | All required fields resolved | `tools/conversation_planner.py` |
| Deep dive drill-down | User asks follow-up on a specific insight | `tools/analyze_prompt.py` + `tools/conversation_planner.py` |

---

## Top-Level Instructions

1. **On every user message**, load the current session context via `tools/context_manager.py get_context`.

2. **Parse the message** with `tools/analyze_prompt.py`. Pass both the raw message and the current context so the parser can merge new information with already-resolved fields.

3. **Check for missing required fields** (`subject`, `market`, `goal`). If any are missing:
   - Call `tools/clarification_engine.py` to get the single highest-priority question.
   - Respond with that question only. Do not proceed to planning.
   - Save the updated context with `tools/context_manager.py save_context`.

4. **When all required fields are resolved**:
   - Call `tools/conversation_planner.py` to generate `plan_steps`.
   - Present a natural-language summary of the plan to the user.
   - Ask: *"Does this look right? Should I proceed?"* (or equivalent in the user's language).
   - Wait for explicit confirmation (`yes`, `proceed`, `go`, `confirm`, or equivalent affirmative). Do NOT auto-proceed.

5. **On confirmation**, emit the intent JSON (see `references/output-schema.md`) and pass it to the downstream skill (`/voc-datasource`).

6. **On deep-dive follow-up** (e.g., "why is Login complained about?"):
   - Update `focus` and `filters.keywords` in the context.
   - Call `tools/conversation_planner.py` with `mode=deep_dive`.
   - Do NOT restart the clarification flow unless a new required field is explicitly absent.
   - Respond: *"Let me analyze the [focus] group in depth."* and emit the updated intent JSON.

7. **On ambiguous follow-ups** (reference is unclear): ask one focused question to resolve the ambiguity before updating the plan.

8. **Never fabricate insights** — this skill produces structure and plans only. Do not invent analysis results. Actual data comes from `/voc-datasource`.

9. **PII guard** — before saving context or emitting intent JSON, strip any detected PII (names, emails, phone numbers, user IDs) from all string fields.

---

## Example Flow

```
User:    Analyze MoMo
Agent:   Which market would you like to analyze?
User:    Vietnam
Agent:   Is this for Product insights or Marketing insights?
User:    Product
Agent:   Here's my plan:
         1. Fetch MoMo product reviews from Vietnam (last 90 days, all platforms)
         2. Cluster complaints by feature area
         3. Rank themes by volume and sentiment score
         Shall I proceed?
User:    Yes
Agent:   [emits intent JSON → /voc-datasource]

--- later in the same session ---

User:    Why is Login complained about so much?
Agent:   Let me deep-dive the Login complaint cluster.
         [emits updated intent JSON with focus=Login → /voc-datasource]
```

---

## Troubleshooting

| Symptom | Likely Cause | Fix |
|---|---|---|
| Agent keeps re-asking resolved fields | Context not saved after clarification | Ensure `context_manager.save_context` is called after each turn |
| Intent JSON missing `plan_steps` | `conversation_planner.py` not called before emit | Call planner whenever all required fields are present |
| Deep-dive resets entire flow | `analyze_prompt.py` not receiving current context | Always pass context to parser; check `mode` detection logic |
| PII appears in emitted JSON | PII stripper not running | Call `context_manager.strip_pii` before `get_intent_json` |
| Agent asks two questions at once | Clarification engine returning multiple | Set `max_questions=1` in `clarification_engine.py` call |
| User confirms but agent asks again | Confirmation keyword not matched | Check language-aware confirmation list in `clarification_engine.py` |
| `goal` parsed as wrong type | Ambiguous phrasing (e.g., "for the team") | Clarification engine should catch `goal=unknown` and ask |
