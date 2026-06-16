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
If the user named **none**, default to all five (`app_store, google_play, youtube, tinhte, voz`).
For broad prompts, the agent should usually still ask a **source preference** question as part of
the research intake so the user can narrow the crawl, but if the user leaves it unspecified the
semantic default remains all five.

`competitors` is also **not** a gating field, but the agent may ask for it as an extra
clarification when the user clearly wants benchmarking and no comparison set is obvious.

The key distinction is:

- **Gating** decides whether the request can technically move to planning.
- **Clarification quality** decides whether the setup feels like a serious research intake.

For broad prompts, do not confuse those two. A request may be technically plannable after the four
gating fields are known, but still be too shallow from a UX and research-quality perspective.

## Role normalization

Map synonyms before validating: `marketer/mkt/growth/brand → Marketing`;
`po/pm/product manager/product owner → Product Owner`. Anything else (e.g. "DEV", "designer",
"CEO") is **invalid** → treat as missing and re-ask (see edge case below).

## Asking questions

- **Batch everything.** Put one question per missing gating field into a single
  `CLARIFICATION_REQUIRED` response. Never ask them one turn at a time.
- **Prefer a research brief for broad prompts.** For requests like `"analyze Shopee"` or
  `"research customer feedback"`, ask a fuller intake bundle rather than only the strict minimum.
  In practice, that usually means 5–8 total questions/decisions across:
  `role`, `subject`, `focus`, `objective`, `competitors`, `market`, `time_range`,
  `data_sources`, `sentiment`, or `keywords`, depending on what the user already specified.
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

Common high-value **optional** questions for broad requests:

| field         | when to ask | good examples |
|---------------|-------------|---------------|
| `competitors` | user wants comparison, benchmarking, or the subject sits in a crowded category | "MoMo", "Lazada", "TikTok Shop" |
| `market`      | geography affects review mix, UX, or competitors | "Vietnam", "Indonesia", "Southeast Asia" |
| `time_range`  | freshness matters or the user did not specify a review window | "last_30_days", "last_90_days", "last_180_days" |
| `data_sources`| source mix meaningfully changes findings; broad prompts should usually expose this choice | "App stores", "Forums", "Video/social" |
| `sentiment`   | the user did not say whether to focus on negative-only vs all feedback | "negative", "mixed", "all" |
| `keywords`    | the request hints at a narrow scenario | "refund", "checkout", "delivery" |

### Example standard for a vague request

For a prompt like `"analyze Shopee"`, asking only 1–2 questions is usually too shallow. A better
batch would typically cover:

1. the user's role,
2. the product area to focus on,
3. the research objective,
4. which competitors to benchmark,
5. which market to focus on,
6. what time window to analyze,
7. which source groups to crawl.

If the prompt is even broader, add source preferences or a sentiment lens as well.

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
   ├─ merge into STATE
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
