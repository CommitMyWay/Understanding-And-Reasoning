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

# ---------------------------------------------------------------------------
# Role labels shown in plan summary
# ---------------------------------------------------------------------------

ROLE_LABELS = {
    "product": "Product Owner (PO)",
    "marketing": "Marketing (MKT)",
    "quality": "Quality Engineering (QE)",
}

# ---------------------------------------------------------------------------
# initial mode: 6-step role-based plan templates
# ---------------------------------------------------------------------------

INITIAL_PLAN_TEMPLATES = {
    # PO lens: understand what to build / fix next on the roadmap
    "product": [
        "Fetch {subject} reviews from {data_source_str} in {market} ({time_range})",
        "Tag each review with a feature label (Login, Payment, Onboarding, Performance, Other)",
        "Rank feature clusters by complaint volume and negative sentiment score",
        "Score top pain points by severity (1-star vs 2-star review ratio)",
        "Extract representative user quotes for the top 3 pain points",
        "Map findings to roadmap impact (High / Med / Low) and draft prioritised action items",
    ],
    # MKT lens: brand perception, sentiment, acquisition signals
    "marketing": [
        "Fetch {subject} reviews and mentions from {data_source_str} in {market} ({time_range})",
        "Run sentiment trend analysis — positive / neutral / negative ratio over time",
        "Extract top brand perception keywords and recurring themes",
        "Identify promoter language (what happy users say) vs detractor language",
        "Flag acquisition friction points mentioned in onboarding and first-use reviews",
        "Recommend 3–5 messaging angles and campaign talking points backed by user language",
    ],
    # QE lens: bugs, crashes, regressions for dev/QA handoff
    "quality": [
        "Fetch 1-star and 2-star {subject} reviews from {data_source_str} in {market} ({time_range})",
        "Classify defects by category: crash / UI bug / performance / data integrity / other",
        "Score each defect class by frequency and user-impact severity",
        "Break down by platform (iOS App Store vs Android CH Play) and recency (last 30 days vs prior)",
        "Flag potential regressions — spike in complaint volume compared to previous period",
        "Output structured bug-report summary with severity labels, ready for Jira / dev handoff",
    ],
}

# deep_dive mode: 6 sub-steps drilling into a specific focus topic
DEEP_DIVE_PREFIX = [
    "Filter {subject} review corpus to all mentions of {focus} from {data_source_str}",
    "Re-cluster {focus} complaints into granular sub-themes (e.g. error type, user action, platform)",
    "Rank sub-themes by frequency and severity score",
    "Extract the 3 most representative user quotes per sub-theme",
    "Trace {focus} complaint volume trend over {time_range} — identify regression spike dates",
    "Summarise root-cause hypotheses per sub-theme with supporting evidence",
]

# ---------------------------------------------------------------------------
# Summary templates (natural-language confirmation message shown to user)
# ---------------------------------------------------------------------------

SUMMARY_TEMPLATES = {
    "product": (
        "I'll fetch {subject} reviews from {data_source_str} in {market} (last {time_range}), "
        "tag complaints by feature, rank pain points by severity, and map them to roadmap priorities. "
        "Want to adjust the data sources or proceed?"
    ),
    "marketing": (
        "I'll pull {subject} mentions and reviews from {data_source_str} in {market} (last {time_range}), "
        "analyse sentiment trends, surface brand themes, and recommend messaging angles. "
        "Want to adjust the data sources or proceed?"
    ),
    "quality": (
        "I'll scan 1–2 star {subject} reviews from {data_source_str} in {market} (last {time_range}), "
        "classify defects, flag regressions, and produce a bug-report summary for the dev team. "
        "Want to adjust the data sources or proceed?"
    ),
    "deep_dive": (
        "I'll drill into the {focus} complaint cluster for {subject} in {market} "
        "across {data_source_str}, break it into sub-themes, and identify when issues started spiking. "
        "Shall I proceed?"
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
    data_source = intent.get("data_source") or ["App Store", "CH Play", "Youtube", "Voz", "Tinhte", "Reddit"]

    filter_desc = _describe_filters(filters)

    # Human-readable source list: ≤3 shown, then "+ N more"
    if len(data_source) <= 3:
        data_source_str = ", ".join(data_source)
    elif len(data_source) == len(["App Store", "CH Play", "Youtube", "Voz", "Tinhte", "Reddit"]):
        data_source_str = "all sources (App Store, CH Play, Youtube, Voz, Tinhte, Reddit)"
    else:
        data_source_str = ", ".join(data_source[:3]) + f" + {len(data_source) - 3} more"

    vars_ = {
        "subject": subject,
        "market": market,
        "goal": goal,
        "focus": focus or "the selected topic",
        "time_range": filter_desc["time_range"],
        "platform": filter_desc["platform"],
        "sentiment": filter_desc["sentiment"],
        "data_source_str": data_source_str,
        "role_label": ROLE_LABELS.get(goal, ""),
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
