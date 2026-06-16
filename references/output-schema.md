# Output Schema — Frontend JSON Contract

The agent's response is **JSON only** — no natural-language prose — and is a **single response
envelope** object: one of `CLARIFICATION_REQUIRED`, `PLAN_CONFIRMATION`, `ERROR`.

```
{"response_type": "CLARIFICATION_REQUIRED", "payload": { ... }}
```

`response_type` is **always exactly** one of the three strings above (case-sensitive).

> **No `query` field.** The frontend owns the `query` value (it forwards the user's request
> elsewhere); echoing it is out of scope for this skill and never appears in the output.

---

## 1. `CLARIFICATION_REQUIRED`

Sent when the request is missing one or more **gating fields**, or when a previous answer was
ambiguous/invalid. The agent may also include a non-gating `competitors` question when benchmark
targets are still unclear and asking would materially improve the final plan.

### First round (no `reason`)

Choices are **authored by the agent from the user's prompt**, never canned. The example below is
for *"I am a Marketer ... research VNG"* — note the choices are specific to VNG's products:

```json
{
  "response_type": "CLARIFICATION_REQUIRED",
  "payload": {
    "suggestedQuestions": [
      {
        "key": "focus",
        "type": "single_select",
        "question": "Which VNG product or area should we focus on?",
        "choices": ["ZaloPay payments & transfers", "ZaloPay wallet top-up", "Zalo app experience"],
        "recommended": "ZaloPay payments & transfers",
        "allow_other": true
      },
      {
        "key": "objective",
        "type": "single_select",
        "question": "What is your primary objective for researching VNG?",
        "choices": ["Find negative feedback & propose improvements", "Benchmark vs MoMo/VNPay", "Spot top user complaints"],
        "recommended": "Find negative feedback & propose improvements",
        "allow_other": true
      }
    ]
  }
}
```

### Second round (re-clarify — includes `reason`)

```json
{
  "response_type": "CLARIFICATION_REQUIRED",
  "payload": {
    "reason": "Your objective 'measure something' is too broad to scope the analysis.",
    "suggestedQuestions": [
      {
        "key": "objective",
        "type": "single_select",
        "question": "What is your primary objective for this research?",
        "choices": ["Find negative feedback & propose improvements", "Benchmark against competitors", "QA bug sweep"],
        "recommended": "Find negative feedback & propose improvements",
        "allow_other": true
      }
    ]
  }
}
```

### Question object — fields (always all six present)

| field         | type            | notes |
|---------------|-----------------|-------|
| `key`         | string          | maps to a STATE field (`role`, `subject`, `focus`, `objective`, ...) |
| `type`        | string          | `single_select` \| `multi_select` \| `text` \| `boolean` |
| `question`    | string          | the prompt shown to the user |
| `choices`     | array of string | **1–3** items for select types; `[]` for `text`/`boolean` |
| `recommended` | string \| null  | suggested default, or `null` when there is none |
| `allow_other` | boolean         | **always `true`** — FE renders a free-text box; never put "Other" in `choices` |

#### How the frontend renders each `type`

| type            | FE render                         | user returns        |
|-----------------|-----------------------------------|---------------------|
| `single_select` | radio group / single-choice chips | one string from `choices` |
| `multi_select`  | checkboxes / multi chips          | array of strings    |
| `text`          | single-line input                 | free string         |
| `boolean`       | toggle / Yes-No                   | `true` or `false`   |

> `allow_other: true` is used **instead of** adding the literal `"Other"` to `choices`, so the
> agent never mistakes "Other" for a semantic option.

---

## 2. `PLAN_CONFIRMATION`

Sent when all four gating fields are present. Defaults are applied by the tool.

```json
{
  "response_type": "PLAN_CONFIRMATION",
  "payload": {
    "intent": {
      "subject": "Zalopay",
      "market": "Vietnam",
      "competitors": ["Zalopay"],
      "audience": "Marketing",
      "objective": "research negative feedback which have 1, 2 stars and propose advices to improve",
      "focus": "transfer money",
      "data_sources": ["app_store", "google_play"],
      "filters": {
        "time_range": "last_90_days",
        "sentiment": "negative",
        "keywords": []
      }
    },
    "plan": {
      "summary": "Through a Marketing lens, research Zalopay's 'transfer money' to ... Pull user reviews from App Store, Google Play over the last 90 days (sentiment: negative)."
    },
    "resolved_apps": [
      {
        "name": "Zalopay",
        "playId": "com.vng.zalopay",
        "appStoreId": "1112345678",
        "evidence": "https://play.google.com/store/apps/details?id=com.vng.zalopay"
      }
    ]
  }
}
```

### `intent` fields

| field          | meaning | default |
|----------------|---------|---------|
| `subject`      | company/product to research | — (gating) |
| `market`       | target market | `"Vietnam"` |
| `competitors`  | the research targets to compare | `[subject]` |
| `audience`     | the user's role | — (gating; `Marketing` \| `Product Owner`) |
| `objective`    | the research goal | — (gating) |
| `focus`        | feature/topic | — (gating) |
| `data_sources` | canonical source keys | all five if user named none |
| `filters.time_range` | review window | `"last_90_days"` |
| `filters.sentiment`  | `all` \| `negative` | `negative` if goal targets negatives, else `all` |
| `filters.keywords`   | extra search keywords | `[]` |

### `resolved_apps` fields

| field        | meaning |
|--------------|---------|
| `name`       | display name of the app |
| `playId`     | Google Play package name, or `null` if unverified |
| `appStoreId` | App Store numeric ID, or `null` if unverified |
| `evidence`   | store URL used to verify at least one ID |

### Canonical `data_sources` keys

`app_store`, `google_play`, `youtube`, `tinhte`, `voz` (default set), plus `reddit` if requested.
Aliases accepted on input: "App Store"/"iOS" → `app_store`; "CH Play"/"Google Play"/"Play Store"/
"Android" → `google_play`; "YouTube" → `youtube`; etc.

---

## 3. `ERROR`

Sent on garbled or unusable input.

```json
{
  "response_type": "ERROR",
  "error": { "message": "Please input correctly" }
}
```

---

## Internal `validate` output (NOT sent to the frontend)

```json
{
  "complete": false,
  "missing": ["role", "objective"],
  "ready_for": "clarify",
  "normalized": { "role": null, "data_sources": ["app_store", "google_play", "youtube", "tinhte", "voz"] }
}
```

The agent uses this to decide whether to call `clarify` or `plan` next.
