# Output Schema — Intent JSON

This document defines the flat intent JSON object emitted by the
`voc-task-understanding` skill when an analysis request is fully resolved
and confirmed by the user.

---

## Schema

```json
{
  "subject": "MoMo",
  "market": "Vietnam",
  "goal": "product",
  "focus": "Login",
  "filters": {
    "time_range": "last_90_days",
    "platform": "all",
    "sentiment": "all",
    "keywords": ["timeout", "otp", "error"]
  },
  "clarifications_done": ["market", "goal"],
  "plan_steps": [
    "Fetch MoMo product reviews from Vietnam market (last 90 days, all platforms)",
    "Cluster complaints by feature area using topic modelling",
    "Rank feature clusters by complaint volume and negative sentiment score",
    "Identify top-3 pain points with representative user quotes",
    "Flag anomalies and sudden complaint spikes by date"
  ]
}
```

---

## Field Reference

| Field | Type | Required | Description |
|---|---|---|---|
| `subject` | string | ✅ | Product, app, or brand being analyzed (e.g. `"MoMo"`, `"ZaloPay"`) |
| `market` | string | ✅ | Geographic or demographic scope (e.g. `"Vietnam"`, `"Southeast Asia"`) |
| `goal` | enum | ✅ | `"product"` \| `"marketing"` \| `"competitive"` |
| `focus` | string \| null | ❌ | Sub-scope for deep dives (e.g. `"Login"`, `"Payment"`, `"Checkout"`). `null` for top-level analysis. |
| `filters.time_range` | string | ❌ | Default `"last_90_days"`. Other values: `"last_30_days"`, `"last_6_months"`, `"last_year"`, `"custom:<ISO8601_start>/<ISO8601_end>"` |
| `filters.platform` | string | ❌ | Default `"all"`. Other values: `"ios"`, `"android"`, `"web"` |
| `filters.sentiment` | string | ❌ | Default `"all"`. Other values: `"negative"`, `"positive"`, `"neutral"` |
| `filters.keywords` | string[] | ❌ | Keywords extracted from deep-dive question (e.g. `["timeout", "otp"]`). Empty array for no keyword filter. |
| `clarifications_done` | string[] | ❌ | Ordered list of fields that were resolved through Q&A (audit trail). |
| `plan_steps` | string[] | ✅ | Ordered list of analysis steps the data-source skill will execute. |

> **Note**: The `_plan_summary` field (used internally for agent messaging) is stripped before
> the intent JSON is passed to downstream skills.

---

## Downstream Consumers

| Skill | Consumes | Notes |
|---|---|---|
| `/voc-datasource` | Full intent JSON | Uses `subject`, `market`, `goal`, `focus`, `filters` to select and query data sources |
| `/voc-report` | Full intent JSON + analysis results | Uses `plan_steps` to structure the report sections |

---

## Versioning

- Current schema version: **v1.0**
- Breaking changes will bump the minor version.
- Add a `"schema_version": "1.0"` field if versioning becomes necessary for routing.
