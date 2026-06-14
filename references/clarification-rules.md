# Clarification Rules

This document defines when, how, and in what order the `voc-task-understanding`
skill asks clarifying questions.

---

## Core Rule: One Question Per Turn

**Never ask more than one question in a single agent response.**

Pick the highest-priority missing field, ask only that, and wait for the user's answer
before proceeding. This keeps the conversation feeling natural and avoids overwhelming
the user with a form-like list of questions.

---

## Priority Order

When multiple required fields are missing, ask in this order:

| Priority | Field | Rationale |
|---|---|---|
| 1 | `subject` | Nothing can be scoped without knowing what to analyze |
| 2 | `market` | Determines data source geography; needed before any fetch |
| 3 | `goal` | Determines the analysis lens; affects plan structure |

---

## When to Ask vs. When to Infer

| Situation | Action |
|---|---|
| `subject` is clearly named in the prompt (e.g. "Analyze MoMo") | Infer — do NOT ask |
| `market` appears in the prompt (e.g. "in Vietnam") | Infer — do NOT ask |
| `goal` can be inferred from keywords (e.g. "feature complaints" → `product`) | Infer — do NOT ask |
| Prompt is ambiguous (e.g. "analyze MoMo for the team") | Ask — goal is unclear |
| User gives a one-word answer that maps to a known value | Accept — do NOT ask again |
| User answers with an unexpected value | Accept as-is and continue; only re-ask if the value is truly unresolvable |

---

## Re-asking Rules

- **Never re-ask** a field that was already answered in this session.
- If a user corrects a previous answer (e.g. "actually, marketing not product"), update the field silently and continue from current state — do NOT restart the whole flow.
- If the same field appears missing again after a correction, it means the new answer was also ambiguous — ask once more with the specific options spelled out.

---

## Confirmation Gate

Before building and emitting the intent JSON, the agent MUST present a natural-language
plan summary and ask for explicit confirmation.

**Accepted confirmation signals** (case-insensitive, language-aware):

English: `yes`, `confirm`, `ok`, `okay`, `approve`, `proceed`, `go ahead`,
`do it`, `ship it`, `lgtm`, `sure`, `correct`, `sounds good`, `looks good`, `go`

Vietnamese: `có`, `đúng`, `ổn`, `được`, `tiến hành`, `làm đi`, `ok`,
`đồng ý`, `chính xác`, `chuẩn`, `tiếp tục`

**Non-confirmation responses** (questions, corrections, additions) must be treated as
adjustment input — update the plan and re-present for confirmation. Never interpret
silence or a new instruction as approval.

---

## Deep-Dive Follow-Up Rules

When the user asks a follow-up that references a specific feature or insight
(e.g. "Why is Login complained about so much?"):

1. Detect the deep-dive pattern (see `tools/analyze_prompt.py` → `_detect_deep_dive`).
2. Extract the focus topic from the message.
3. Update `intent.focus` and add relevant keywords to `intent.filters.keywords`.
4. Do **NOT** re-ask `subject`, `market`, or `goal` — they are already resolved.
5. Only ask a clarifying question if the focus topic is genuinely ambiguous
   (e.g. "that thing" with no clear referent).

---

## Data Privacy Rules

Before storing any user answer in the context or emitting it in the intent JSON:

1. Run PII stripping (`context_manager.strip_pii`).
2. Patterns stripped: email addresses, Vietnamese phone numbers, numeric user IDs.
3. Replaced with: `[REDACTED]`.
4. **Never echo PII back** to the user in a clarification question.
5. If the user's answer consists entirely of PII (e.g. a user ID as the subject),
   ask the user to provide the product name instead.
