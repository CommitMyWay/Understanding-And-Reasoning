"""
conversation_planner.py
-----------------------
Builds a structured analysis plan from a fully resolved intent object
and outputs the final flat intent JSON ready for downstream skills.

Two modes:
  - initial   : full plan for a new analysis request
  - deep_dive : focused sub-plan for drilling into a specific insight

Usage (CLI):
    python tools/conversation_planner.py \
        --intent '{"subject":"MoMo","market":"Vietnam","goal":"product","focus":null,"filters":{"time_range":"last_90_days","platform":"all","sentiment":"all","keywords":[]},"clarifications_done":["market","goal"],"plan_steps":[]}' \
        --mode initial

    python tools/conversation_planner.py \
        --intent '{"subject":"MoMo","market":"Vietnam","goal":"product","focus":"Login",...}' \
        --mode deep_dive

Output (stdout, JSON):
    {
        "subject": "MoMo",
        "market": "Vietnam",
        "goal": "product",
        "focus": null,
        "filters": { "time_range": "last_90_days", "platform": "all", "sentiment": "all", "keywords": [] },
        "clarifications_done": ["market", "goal"],
        "plan_steps": [
            "Fetch MoMo product reviews from Vietnam market (last 90 days, all platforms)",
            "Cluster complaints by feature area using topic modelling",
            "Rank feature clusters by complaint volume and negative sentiment score",
            "Identify top-3 pain points with representative user quotes",
            "Flag anomalies and sudden complaint spikes by date"
        ],
        "_plan_summary": "I'll fetch MoMo reviews from Vietnam, cluster complaints by feature, and surface the top pain points."
    }
"""

import argparse
import json
import sys

# ---------------------------------------------------------------------------
# Plan templates
# ---------------------------------------------------------------------------

# initial mode: steps keyed by goal
INITIAL_PLAN_TEMPLATES = {
    "product": [
        "Fetch {subject} product reviews from {market} ({time_range}, {platform})",
        "Cluster user complaints by feature area using topic modelling",
        "Rank feature clusters by complaint volume and negative sentiment score",
        "Identify top-3 pain points with representative user quotes",
        "Flag anomalies and sudden complaint spikes by date",
    ],
    "marketing": [
        "Fetch {subject} brand mentions and ratings from {market} ({time_range}, {platform})",
        "Analyse overall sentiment trend over the selected time range",
        "Identify top brand perception themes (positive and negative)",
        "Benchmark net promoter signals against category baseline",
        "Surface top-quoted user phrases for messaging opportunities",
    ],
    "competitive": [
        "Fetch {subject} reviews alongside key competitor reviews from {market} ({time_range})",
        "Compare complaint volume and sentiment scores across competitors",
        "Identify feature gaps where {subject} lags behind competitors",
        "Highlight areas where {subject} outperforms on user satisfaction",
        "Summarise competitive positioning with supporting data points",
    ],
}

# deep_dive mode: sub-steps injected before a focus-specific drill
DEEP_DIVE_PREFIX = [
    "Filter review corpus to complaints mentioning {focus}",
    "Re-cluster {focus} complaints into sub-themes",
    "Rank sub-themes by frequency and severity score",
    "Extract representative user quotes for each sub-theme",
    "Trace complaint volume trend for {focus} over time to detect regression points",
]

# Summary templates for the agent's natural-language plan confirmation message
SUMMARY_TEMPLATES = {
    "product": (
        "I'll fetch {subject} reviews from {market}, cluster complaints by feature area, "
        "and surface the top pain points with supporting quotes."
    ),
    "marketing": (
        "I'll analyse {subject} brand perception in {market}, track sentiment trends, "
        "and identify the strongest positive and negative themes."
    ),
    "competitive": (
        "I'll compare {subject} against its competitors in {market}, "
        "identify feature gaps, and summarise competitive positioning."
    ),
    "deep_dive": (
        "I'll deep-dive into the {focus} complaint cluster for {subject} in {market}, "
        "break it into sub-themes, and trace when issues started spiking."
    ),
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _format_steps(steps: list[str], vars_: dict) -> list[str]:
    """Apply variable substitution to each step string."""
    return [s.format(**vars_) for s in steps]


def _describe_filters(filters: dict) -> dict:
    """Produce human-readable filter descriptions."""
    time_range = filters.get("time_range", "last_90_days").replace("_", " ")
    platform = filters.get("platform", "all")
    sentiment = filters.get("sentiment", "all")
    keywords = filters.get("keywords", [])
    return {
        "time_range": time_range,
        "platform": platform if platform != "all" else "all platforms",
        "sentiment": sentiment if sentiment != "all" else "all sentiments",
        "keywords": keywords,
    }


# ---------------------------------------------------------------------------
# Core planner
# ---------------------------------------------------------------------------

def build_plan(intent: dict, mode: str = "initial") -> dict:
    """
    Returns the intent dict with `plan_steps` and `_plan_summary` populated.
    """
    subject = intent.get("subject", "the product")
    market = intent.get("market", "the market")
    goal = intent.get("goal", "product")
    focus = intent.get("focus")
    filters = intent.get("filters", {})

    filter_desc = _describe_filters(filters)
    vars_ = {
        "subject": subject,
        "market": market,
        "goal": goal,
        "focus": focus or "the selected topic",
        "time_range": filter_desc["time_range"],
        "platform": filter_desc["platform"],
        "sentiment": filter_desc["sentiment"],
    }

    if mode == "deep_dive" and focus:
        steps = _format_steps(DEEP_DIVE_PREFIX, vars_)
        summary = SUMMARY_TEMPLATES["deep_dive"].format(**vars_)
    else:
        template = INITIAL_PLAN_TEMPLATES.get(goal, INITIAL_PLAN_TEMPLATES["product"])
        steps = _format_steps(template, vars_)
        summary = SUMMARY_TEMPLATES.get(goal, SUMMARY_TEMPLATES["product"]).format(**vars_)

    result = dict(intent)
    result["plan_steps"] = steps
    result["_plan_summary"] = summary

    # Remove internal meta-fields not meant for downstream skills
    result.pop("missing_required", None)
    result.pop("mode", None)

    return result


# ---------------------------------------------------------------------------
# CLI entrypoint
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Build an analysis plan from a resolved intent object."
    )
    parser.add_argument(
        "--intent",
        required=True,
        help="Resolved intent JSON string",
    )
    parser.add_argument(
        "--mode",
        default="initial",
        choices=["initial", "deep_dive"],
        help="Planning mode: 'initial' for full analysis, 'deep_dive' for focused drill-down",
    )
    args = parser.parse_args()

    try:
        intent = json.loads(args.intent)
    except json.JSONDecodeError as e:
        print(json.dumps({"error": f"Invalid intent JSON: {e}"}), file=sys.stderr)
        sys.exit(1)

    # Validate required fields
    missing = [f for f in ["subject", "market", "goal"] if not intent.get(f)]
    if missing:
        print(
            json.dumps({"error": f"Cannot build plan — missing required fields: {missing}"}),
            file=sys.stderr,
        )
        sys.exit(1)

    result = build_plan(intent, mode=args.mode)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
