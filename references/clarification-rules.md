# Clarification Rules

How the agent decides whether a VoC request is ready, and how it asks for what's missing.

## Gating fields

A request is **ready to plan** only when all four are present and valid:

| field       | what it captures | example |
|-------------|------------------|---------|
| `role`      | who the user is — **only** `Marketing` or `Product Owner` | "I am a Marketer" → `Marketing` |
| `subject`   | the company/product to research | "product Zalopay" → `Zalopay` |
| `focus`     | the feature/topic to analyze | "feature transfer money" → `transfer money` |
| `objective` | the research goal | "research negative feedback ... propose advices to improve" |

`data_sources` is **not** a gating field. If the user named specific sources, use exactly those.
If the user named **none**, default to all five (`app_store, google_play, youtube, tinhte, voz`) —
do not ask. Because the max-3-choices rule would be violated by a 5-option source picker, the
agent never asks `data_sources` as a clarification; it is always inferred or defaulted.

## Role normalization

Map synonyms before validating: `marketer/mkt/growth/brand → Marketing`;
`po/pm/product manager/product owner → Product Owner`. Anything else (e.g. "DEV", "designer",
"CEO") is **invalid** → treat as missing and re-ask (see edge case below).

## Asking questions

- **Batch everything.** Put one question per missing gating field into a single
  `CLARIFICATION_REQUIRED` response. Never ask them one turn at a time.
- **1–3 choices** per select question. Never more than three.
- **Always `allow_other: true`.** The FE shows a free-text box; the user is never forced into a
  preset. Do not add the literal `"Other"` to `choices`.
- **Uniform shape.** Every question object carries all six keys (`key`, `type`, `question`,
  `choices`, `recommended`, `allow_other`); `recommended` is `null` when there is no good default.

## Questions are authored from context, not canned

The tool ships **no hard-coded answer choices**. For each field it knows only a neutral question
template + a default `type` (`FIELD_META` in `tools/voc_reasoning.py`). The **agent authors** the
actual question objects into `state.questions`, deriving `choices`/`recommended` from the user's
real prompt so they are specific to the subject.

| field      | default type    | choices |
|------------|-----------------|---------|
| `role`     | `single_select` | **fixed**: Marketing · Product Owner (the only spec-allowed values) |
| `subject`  | `text`          | agent-authored from context (often none → free text) |
| `focus`    | `single_select` | agent-authored from context (e.g. for VNG: "ZaloPay payments & transfers") |
| `objective`| `single_select` | agent-authored from context (e.g. "Benchmark vs MoMo/VNPay") |

Example — for *"research VNG"*, author focus choices about VNG's products, not generic
placeholders. The tool then enforces the structure: ≤3 choices, no literal "Other", `allow_other`
always `true`, all six keys present, and `role` choices forced to the two valid roles. If the agent
authors nothing, the tool falls back to asking the missing fields as free text (empty `choices`).

## Edge case — off-topic or vague answer

If a user's free-text answer doesn't actually resolve the field:

- **Wrong category** (asked for role, answered "DEV"): re-ask only `role`.
- **Too broad** (objective = "measure something"): re-ask only `objective`.

Set in STATE:
- `clarify_fields`: a list with just the unresolved field(s).
- `reclarify_reason`: a one-line human explanation.

Then run `clarify` again. The result is the **second-round** shape — same questions plus a top-level
`reason` in `payload`:

```json
{
  "response_type": "CLARIFICATION_REQUIRED",
  "payload": {
    "reason": "'DEV' isn't a supported role here — please pick Marketing or Product Owner.",
    "suggestedQuestions": [ { "key": "role", "type": "single_select", "question": "...", "choices": ["Marketing", "Product Owner"], "recommended": null, "allow_other": true } ]
  }
}
```

## Decision flow

```
user input
   │
   ├─ merge into STATE (raw_query = latest input)
   ├─ normalize role + data sources
   ├─ run `validate`
   │
   ├─ complete? ── yes ──► run `plan`    -> PLAN_CONFIRMATION
   │                no
   ├─ a prior answer was invalid/vague? ── yes ──► set clarify_fields + reclarify_reason
   │                                                run `clarify` -> 2nd-round CLARIFICATION_REQUIRED
   └─ otherwise ──────────────────────────────────► run `clarify` -> 1st-round CLARIFICATION_REQUIRED

garbled/unusable input ──► run `error` -> ERROR
```
