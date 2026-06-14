"""
conversation_planner.py
-----------------------
Builds a structured analysis plan from a fully resolved intent object.

Changes:
  - Plans are keyed by target_user (product/marketing/quality) not goal
  - goal (free-text research objective) is woven into plan steps and summary
  - Plan confirmation message is conversational: shows goal, target_user, sources,
    and invites the user to adjust or confirm naturally

Two modes:
  - initial   : full 6-step plan for a new analysis
  - deep_dive : focused sub-plan for drilling into a specific insight

Usage (CLI):
    python tools/conversation_planner.py \
        --intent '{"subject":"MoMo","market":"Vietnam","target_user":"quality",
                   "goal":"understand crash patterns in payment flow",
                   "data_source":["App Store","CH Play"],...}' \
        --mode initial
"""

import argparse
import json
import sys

# ---------------------------------------------------------------------------
# Role labels
# ---------------------------------------------------------------------------

ROLE_LABELS = {
    "product":   "Product (PO)",
    "marketing": "Marketing (MKT)",
    "quality":   "Quality Engineering (QE)",
}

# ---------------------------------------------------------------------------
# 6-step plan templates keyed by target_user
# ---------------------------------------------------------------------------

INITIAL_PLAN_TEMPLATES = {
    # PO lens: what to build / fix next on the roadmap
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

# Deep-dive: 6 sub-steps drilling into a specific focus topic
DEEP_DIVE_STEPS = [
    "Filter {subject} review corpus to all mentions of {focus} from {data_source_str}",
    "Re-cluster {focus} complaints into granular sub-themes (e.g. error type, user action, platform)",
    "Rank sub-themes by frequency and severity score",
    "Extract the 3 most representative user quotes per sub-theme",
    "Trace {focus} complaint volume trend over {time_range} — identify regression spike dates",
    "Summarise root-cause hypotheses per sub-theme with supporting evidence",
]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _format_steps(steps: list[str], vars_: dict) -> list[str]:
    return [s.format(**vars_) for s in steps]


def _describe_filters(filters: dict) -> dict:
    time_range = filters.get("time_range", "last_90_days").replace("_", " ")
    platform   = filters.get("platform", "all")
    sentiment  = filters.get("sentiment", "all")
    keywords   = filters.get("keywords", [])
    return {
        "time_range": time_range,
        "platform":   platform if platform != "all" else "all platforms",
        "sentiment":  sentiment if sentiment != "all" else "all sentiments",
        "keywords":   keywords,
    }


def _format_source_str(data_source: list[str]) -> str:
    all_six = {"App Store", "CH Play", "Youtube", "Voz", "Tinhte", "Reddit"}
    if set(data_source) >= all_six:
        return "all sources (App Store, CH Play, Youtube, Voz, Tinhte, Reddit)"
    if len(data_source) <= 3:
        return ", ".join(data_source)
    return ", ".join(data_source[:3]) + f" + {len(data_source) - 3} more"


def _build_confirm_message(
    subject: str,
    market: str,
    target_user: str,
    goal: str | None,
    data_source_str: str,
    time_range: str,
    lang: str = "en",
) -> str:
    """
    Natural-language plan confirmation shown to user.
    Includes research goal, team lens, sources, and a friendly prompt to adjust or proceed.
    """
    role = ROLE_LABELS.get(target_user, target_user.title())
    goal_line = goal or ("the research objective" if lang == "en" else "mục tiêu nghiên cứu")

    if lang == "vi":
        return (
            f"Đây là kế hoạch của tôi:\n\n"
            f"🎯 Mục tiêu: {goal_line}\n"
            f"👤 Góc nhìn: {role}\n"
            f"📡 Nguồn dữ liệu: {data_source_str}\n"
            f"📅 Thời gian: {time_range}\n\n"
            f"Tôi sẽ lấy review {subject} tại {market}, phân tích theo lens {role.split('(')[0].strip()}, "
            f"và tổng hợp insights phù hợp với mục tiêu trên.\n\n"
            f"Bạn muốn điều chỉnh gì không — nguồn dữ liệu, khoảng thời gian, hay phạm vi? "
            f"Hoặc nói \"go\" để tôi bắt đầu."
        )
    else:
        return (
            f"Here's my plan:\n\n"
            f"🎯 Research goal: {goal_line}\n"
            f"👤 Lens: {role}\n"
            f"📡 Sources: {data_source_str}\n"
            f"📅 Time range: {time_range}\n\n"
            f"I'll pull {subject} reviews in {market}, analyse them through the {role.split('(')[0].strip()} lens, "
            f"and surface insights aligned to your goal.\n\n"
            f"Anything you'd like to adjust — sources, time range, or scope? "
            f"Otherwise just say \"go\" and I'll start."
        )


# ---------------------------------------------------------------------------
# Core planner
# ---------------------------------------------------------------------------

def build_plan(intent: dict, mode: str = "initial") -> dict:
    subject     = intent.get("subject", "the product")
    market      = intent.get("market", "the market")
    target_user = intent.get("target_user") or "product"
    goal        = intent.get("goal")
    focus       = intent.get("focus")
    filters     = intent.get("filters", {})
    data_source = intent.get("data_source") or ["App Store", "CH Play", "Youtube", "Voz", "Tinhte", "Reddit"]

    filter_desc     = _describe_filters(filters)
    data_source_str = _format_source_str(data_source)

    vars_ = {
        "subject":         subject,
        "market":          market,
        "target_user":     target_user,
        "goal":            goal or "user feedback trends",
        "focus":           focus or "the selected topic",
        "time_range":      filter_desc["time_range"],
        "platform":        filter_desc["platform"],
        "sentiment":       filter_desc["sentiment"],
        "data_source_str": data_source_str,
        "role_label":      ROLE_LABELS.get(target_user, ""),
    }

    if mode == "deep_dive" and focus:
        steps = _format_steps(DEEP_DIVE_STEPS, vars_)
    else:
        template = INITIAL_PLAN_TEMPLATES.get(target_user, INITIAL_PLAN_TEMPLATES["product"])
        steps = _format_steps(template, vars_)

    # Detect language from goal/subject (simple heuristic: Vietnamese diacritics)
    import re
    _vi = re.compile(r"[àáâãèéêìíòóôõùúýăđơưạảấầẩẫậắằẳẵặẹẻẽếềểễệỉịọỏốồổỗộớờởỡợụủứừửữựỳỷỹỵ]", re.I)
    lang = "vi" if _vi.search((goal or "") + " " + market) else "en"

    summary = _build_confirm_message(
        subject, market, target_user, goal,
        data_source_str, filter_desc["time_range"], lang,
    )

    result = dict(intent)
    result["plan_steps"]    = steps
    result["_plan_summary"] = summary

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
    parser.add_argument("--intent", required=True, help="Resolved intent JSON string")
    parser.add_argument("--mode", default="initial", choices=["initial", "deep_dive"])
    args = parser.parse_args()

    try:
        intent = json.loads(args.intent)
    except json.JSONDecodeError as e:
        print(json.dumps({"error": f"Invalid intent JSON: {e}"}), file=sys.stderr)
        sys.exit(1)

    missing = [f for f in ["subject", "market", "target_user"] if not intent.get(f)]
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
