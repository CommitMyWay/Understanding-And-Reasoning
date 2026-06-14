"""
response_formatter.py
---------------------
Formats all agent outputs into the FE API contract JSON shapes.

Every agent response MUST be produced through this formatter.
The `query` field (echo of the user's latest input) is always present.

Commands
--------

1. query        — Echo user input only (first immediate response)
   Usage: python tools/response_formatter.py query --message "Analyze MoMo"
   Output: {"query": "Analyze MoMo"}

2. questions    — Agent asks one or more clarifying questions
   Usage: python tools/response_formatter.py questions \
              --message "Analyze TikTok Shop" \
              --questions '[{"field":"market","question":"Which market?","options":["Vietnam","UK"],"language":"en"}, ...]'
   Output:
   {
     "query": "Analyze TikTok Shop",
     "suggestedQuestions": [
       {
         "id": "q_market",
         "question": "Which market should I analyze TikTok Shop in?",
         "choices": ["Vietnam", "UK", "Suggest another market...", "Other (type your own)..."]
       }
     ]
   }

3. focus_area   — Agent presents plan summary and asks for confirmation
   Usage: python tools/response_formatter.py focus_area \
              --message "go" \
              --intent '{"subject":"MoMo","market":"Vietnam","target_user":"quality","goal":"crash in payment",...}'
   Output:
   {
     "query": "go",
     "focusArea": "Target Product: MoMo. Research goal: crash in payment. Lens: Quality Engineering (QE). Market: Vietnam. Customized parameters: Date Range: last 90 days, Sources: App Store, CH Play."
   }

4. plan         — Final execution plan after user confirms
   Usage: python tools/response_formatter.py plan \
              --message "yes" \
              --intent '{"subject":"MoMo",...,"plan_steps":[...]}'
   Output: {"query": "yes", "subject": "MoMo", "market": "Vietnam", ...all intent fields...}

Notes
-----
- choices always ends with "Suggest another {field}..." + "Other (type your own)..."
- _plan_summary is stripped from the plan output (internal only)
- All fields from intent are included in the plan output
"""

import argparse
import json
import sys

# ---------------------------------------------------------------------------
# Role labels (mirrors conversation_planner)
# ---------------------------------------------------------------------------

ROLE_LABELS = {
    "product":   "Product (PO)",
    "marketing": "Marketing (MKT)",
    "quality":   "Quality Engineering (QE)",
}

# Human-readable field labels for "Suggest another X..." suffix
FIELD_LABELS = {
    "subject":     "product",
    "market":      "market",
    "target_user": "goal type",
    "goal":        "research objective",
    "data_source": "source",
    "focus":       "topic",
}

FREE_TEXT_SUFFIX = {
    "en": "Other (type your own)...",
    "vi": "Nhập tùy chọn khác...",
}

SUGGEST_ANOTHER_SUFFIX = {
    "en": "Suggest another {field}...",
    "vi": "Gợi ý {field} khác...",
}

# ---------------------------------------------------------------------------
# Formatters
# ---------------------------------------------------------------------------

def fmt_query(message: str) -> dict:
    """Stage 1: Echo user input."""
    return {"query": message}


def fmt_questions(message: str, questions: list[dict]) -> dict:
    """
    Stage 2: Format clarifying questions.
    Each question object: {field, question, options (list|None), language}
    """
    suggested = []
    for q in questions:
        field    = q.get("field", "q")
        question = q.get("question", "")
        options  = q.get("options") or []
        lang     = q.get("language", "en")

        choices = list(options)

        # Append "Suggest another X..." if there are already options (makes sense for enumerated fields)
        if options:
            field_label = FIELD_LABELS.get(field, field)
            suggest_label = SUGGEST_ANOTHER_SUFFIX[lang].format(field=field_label)
            choices.append(suggest_label)

        # Always append "Other (type your own)..."
        choices.append(FREE_TEXT_SUFFIX.get(lang, FREE_TEXT_SUFFIX["en"]))

        suggested.append({
            "id":       f"q_{field}",
            "question": question,
            "choices":  choices,
        })

    return {
        "query":             message,
        "suggestedQuestions": suggested,
    }


def fmt_focus_area(message: str, intent: dict) -> dict:
    """
    Stage 3: Plan confirmation. Builds the focusArea summary string.
    Format mirrors the FE contract:
    "Target Product: X. Research goal: Y. Lens: Z. Market: M.
     Customized parameters: Date Range: T, Sources: S."
    """
    subject     = intent.get("subject", "")
    market      = intent.get("market", "")
    target_user = intent.get("target_user", "")
    goal        = intent.get("goal", "")
    time_range  = (
        intent.get("filters", {})
              .get("time_range", "last_90_days")
              .replace("_", " ")
    )
    sources     = ", ".join(intent.get("data_source") or [])
    focus       = intent.get("focus")

    role_label = ROLE_LABELS.get(target_user, target_user.title() if target_user else "")

    parts = []
    if subject:
        parts.append(f"Target Product: {subject}")
    if goal:
        parts.append(f"Research goal: {goal}")
    if focus:
        parts.append(f"Focus area: {focus}")
    if role_label:
        parts.append(f"Lens: {role_label}")
    if market:
        parts.append(f"Market: {market}")

    custom_parts = []
    if time_range:
        custom_parts.append(f"Date Range: {time_range}")
    if sources:
        custom_parts.append(f"Sources: {sources}")
    if custom_parts:
        parts.append("Customized parameters: " + ", ".join(custom_parts))

    focus_area_str = ". ".join(parts) + ("." if parts else "")

    return {
        "query":     message,
        "focusArea": focus_area_str,
    }


def fmt_plan(message: str, intent: dict) -> dict:
    """
    Stage 4: Final execution plan.
    Merges query into the full intent JSON. Strips internal-only fields.
    """
    result = dict(intent)
    result.pop("_plan_summary", None)   # internal — not for FE
    result.pop("missing_required", None)
    result.pop("mode", None)
    result["query"] = message
    return result


# ---------------------------------------------------------------------------
# CLI entrypoint
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="FE API contract response formatter")
    sub = parser.add_subparsers(dest="command")

    # query
    q = sub.add_parser("query", help="Echo user input")
    q.add_argument("--message", required=True)

    # questions
    qs = sub.add_parser("questions", help="Format clarifying questions for FE")
    qs.add_argument("--message", required=True, help="User's latest input")
    qs.add_argument("--questions", required=True,
                    help="JSON array of {field, question, options, language}")

    # focus_area
    fa = sub.add_parser("focus_area", help="Format plan confirmation for FE")
    fa.add_argument("--message", required=True)
    fa.add_argument("--intent",  required=True, help="Resolved intent JSON")

    # plan
    pl = sub.add_parser("plan", help="Format final execution plan for FE")
    pl.add_argument("--message", required=True)
    pl.add_argument("--intent",  required=True, help="Full intent JSON with plan_steps")

    args = parser.parse_args()

    try:
        if args.command == "query":
            result = fmt_query(args.message)

        elif args.command == "questions":
            questions = json.loads(args.questions)
            result    = fmt_questions(args.message, questions)

        elif args.command == "focus_area":
            intent = json.loads(args.intent)
            result = fmt_focus_area(args.message, intent)

        elif args.command == "plan":
            intent = json.loads(args.intent)
            result = fmt_plan(args.message, intent)

        else:
            parser.print_help()
            sys.exit(1)

    except (json.JSONDecodeError, KeyError) as e:
        print(json.dumps({"error": str(e)}), file=sys.stderr)
        sys.exit(1)

    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
