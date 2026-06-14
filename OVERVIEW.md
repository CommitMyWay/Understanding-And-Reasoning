# Skill Overview — voc-task-understanding

## What It Does

Converts an ambiguous user request ("Analyze MoMo") into a structured **intent JSON** that downstream skills (data source, report) can execute. It handles the full reasoning loop: parse → clarify → plan → confirm → output.

---

## File Structure

```
Understanding-And-Reasoning/
├── SKILL.md                          # Skill definition loaded by the agent
├── tools/
│   ├── analyze_prompt.py             # Parse intent from user message
│   ├── clarification_engine.py       # Generate one clarifying question
│   ├── context_manager.py            # In-memory session state
│   └── conversation_planner.py       # Build analysis plan → emit intent JSON
└── references/
    ├── output-schema.md              # Intent JSON field reference
    └── clarification-rules.md        # When/how/order to ask questions
```

---

## How It Works

### Turn-by-turn flow

```
User message
    │
    ▼
analyze_prompt.py         ← parse subject / market / goal / deep-dive signal
    │
    ├─ missing fields? ──► clarification_engine.py  ── ask 1 question ──► User
    │
    └─ all resolved?  ──► conversation_planner.py   ── present plan   ──► User confirm?
                                                                              │
                                                                        emit intent JSON
                                                                    (→ voc-datasource)
```

### Deep-dive follow-up

```
User: "Why is Login complained about?"
    │
    ▼
analyze_prompt.py detects deep-dive pattern
    → sets focus = "Login"
    → no re-ask of subject/market/goal
    │
    ▼
conversation_planner.py (mode=deep_dive)
    → emits updated intent JSON with Login sub-plan
```

---

## Components

### `analyze_prompt.py`
- Extracts `subject`, `market`, `goal` from free-text using regex heuristics
- Detects deep-dive intent ("why", "tại sao", "break down", etc.)
- Strips PII (email, phone, numeric IDs) before processing
- Merges new fields into existing session context (never overwrites already-resolved fields)

### `clarification_engine.py`
- Always returns **exactly 1 question** — highest-priority missing field
- Priority order: `subject` → `market` → `goal`
- Detects Vietnamese diacritics → responds in the user's language (EN/VI)
- Contains confirmation keyword list for both EN and VI

### `context_manager.py`
- In-memory store (module-level dict), resets on process restart / new session
- Tracks: intent fields, conversation history, session state, clarifications done
- `strip_pii()` runs before any context is saved or emitted
- `get_intent_json()` returns clean output — no internal meta-fields

### `conversation_planner.py`
- Two modes: `initial` (full 5-step plan) and `deep_dive` (5-step drill-down)
- Plan templates per goal: `product` / `marketing` / `competitive`
- Outputs `_plan_summary` string for agent's confirmation message (stripped before downstream handoff)

---

## Intent JSON Output

```json
{
  "subject": "MoMo",
  "market": "Vietnam",
  "goal": "product",
  "focus": null,
  "filters": {
    "time_range": "last_90_days",
    "platform": "all",
    "sentiment": "all",
    "keywords": []
  },
  "clarifications_done": ["market", "goal"],
  "plan_steps": [
    "Fetch MoMo product reviews from Vietnam (last 90 days, all platforms)",
    "Cluster user complaints by feature area using topic modelling",
    "Rank feature clusters by complaint volume and negative sentiment score",
    "Identify top-3 pain points with representative user quotes",
    "Flag anomalies and sudden complaint spikes by date"
  ]
}
```

---

## Constraints & Known Gaps

| Item | Detail |
|---|---|
| Max clarification turns | **3** (one per required field) + **1** confirmation = 4 turns max in happy path |
| Re-ask loop risk | No hard cap if user keeps giving ambiguous answers — `max_retries_per_field` not implemented |
| Context persistence | In-memory only — resets on process restart, no cross-session memory |
| Language support | EN and VI only — other languages fall back to EN |
| Scope boundary | Does not fetch data or render reports — output is intent JSON only |

---

## Downstream Integration

| Next Skill | Receives | Does |
|---|---|---|
| `/voc-datasource` | Intent JSON | Selects data sources, fetches reviews |
| `/voc-report` | Intent JSON + analysis results | Renders report / distributes |
