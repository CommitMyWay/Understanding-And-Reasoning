# Output Schema — Intent JSON

This document defines the flat intent JSON object emitted by the
`voc-task-understanding` skill when an analysis request is fully resolved
and confirmed by the user.

---

## Schema

```json
{
  "query": "go",
  "subject": "MoMo",
  "market": "Vietnam",
  "target_user": "marketing",
  "goal": "brand sentiment and voice of customer",
  "focus": null,
  "data_source": ["App Store", "CH Play", "Youtube", "Voz", "Tinhte", "Reddit"],
  "filters": {
    "time_range": "last_90_days",
    "platform": "all",
    "sentiment": "all",
    "keywords": []
  },
  "clarifications_done": ["market", "target_user", "goal"],
  "plan_steps": [
    "Fetch MoMo reviews and mentions from all sources in Vietnam (last 90 days)",
    "Run sentiment trend analysis — positive / neutral / negative ratio over time",
    "Extract Voice of Customer (VoC) keywords and top brand perception themes",
    "Identify promoter language (what happy users say) vs detractor language",
    "Flag acquisition & retention friction points mentioned in onboarding and first-use reviews",
    "Compile Customer Dictionary and messaging insights aligned to research goal"
  ],
  "suggestedDeepDives": [
    "List potential ASO keywords",
    "Build User Persona",
    "Create Sentiment Analysis table by feature",
    "Write Feature Request Brief"
  ]
}
```

---

## Field Reference

| Field | Type | Required | Description |
|---|---|---|---|
| `query` | string | ✅ | Echo of the user's last message. Always present per FE API contract. |
| `subject` | string | ✅ | Product, app, or brand being analyzed (e.g. `"MoMo"`, `"ZaloPay"`) |
| `market` | string | ✅ | Geographic or demographic scope (e.g. `"Vietnam"`, `"Southeast Asia"`) |
| `target_user` | enum | ✅ | Who is running the analysis: `"product"` (PO) \| `"marketing"` (MKT) |
| `goal` | string | ✅ | Free-text research objective (e.g. `"pain points in checkout flow"`, `"brand sentiment trends"`) |
| `focus` | string \| null | ❌ | Sub-scope for deep dives (e.g. `"Login"`, `"Payment"`). `null` for top-level analysis. |
| `data_source` | string[] | ❌ | Sources to pull from. Default: all 6 (`"App Store"`, `"CH Play"`, `"Youtube"`, `"Voz"`, `"Tinhte"`, `"Reddit"`). |
| `filters.time_range` | string | ❌ | Default `"last_90_days"`. Other: `"last_30_days"`, `"last_6_months"`, `"last_year"` |
| `filters.platform` | string | ❌ | Default `"all"`. Other: `"ios"`, `"android"`, `"web"` |
| `filters.sentiment` | string | ❌ | Default `"all"`. Other: `"negative"`, `"positive"`, `"neutral"` |
| `filters.keywords` | string[] | ❌ | Keywords extracted from deep-dive question. Empty array for no filter. |
| `clarifications_done` | string[] | ❌ | Ordered list of fields resolved through Q&A (audit trail). |
| `plan_steps` | string[] | ✅ | Ordered analysis steps the `/voc-datasource` skill will execute. |
| `suggestedDeepDives` | string[] | ❌ | Role-based next-step options shown after analysis completes. Pre-filtered to exclude suggestions already covered by `goal`/`focus`. Empty array if all were already requested. |

> **Note**: The `_plan_summary` field (used internally for agent messaging) is stripped before
> the intent JSON is passed to downstream skills.

---

## Downstream Consumers

| Skill | Consumes | Notes |
|---|---|---|
| `/voc-datasource` | Full intent JSON | Uses `subject`, `market`, `target_user`, `goal`, `focus`, `data_source`, `filters` to select and query data sources |
| `/voc-report` | Full intent JSON + analysis results | Uses `target_user`, `plan_steps` to structure the report sections |

---

## Versioning

- Current schema version: **v1.0**
- Breaking changes will bump the minor version.
- Add a `"schema_version": "1.0"` field if versioning becomes necessary for routing.
