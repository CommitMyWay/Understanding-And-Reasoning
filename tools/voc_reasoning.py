#!/usr/bin/env python3
"""
voc_reasoning.py — Reasoning & Understanding tool for the Voice-of-Customer (VoC) agent.

This is the DETERMINISTIC validator/formatter for the front-door reasoning stage.
The LLM (driven by SKILL.md) does the natural-language understanding: it reads the
user's prompt, extracts the fields into a STATE object, normalizes fuzzy values, and
judges whether a free-text answer is valid. This tool then GUARANTEES the FE JSON
contract so the agent never hand-writes (and never hallucinates) the schema.

Subcommands:
  validate  -> internal helper for the LLM: is the state complete? which fields miss?
  clarify   -> CLARIFICATION_REQUIRED envelope (batched questions for missing fields)
  plan      -> PLAN_CONFIRMATION envelope (intent + plan, with defaults applied)
  error     -> ERROR envelope

Output: a SINGLE response envelope object, printed as compact single-line JSON:
  {"response_type": "...", ...}
(`validate` prints a single internal object for the agent, NOT sent to the FE.)
There is no `query` field — the frontend owns that value (it forwards the request
elsewhere); it is out of this skill's scope.

Standard library only — no third-party dependencies.

Usage:
  python3 voc_reasoning.py validate '<state-json>'
  python3 voc_reasoning.py clarify  '<state-json>'
  python3 voc_reasoning.py plan     '<state-json>'
  python3 voc_reasoning.py error    '<message>'
"""

import json
import re
import sys

# --------------------------------------------------------------------------- #
# Canonical contract constants (single source of truth for the whole skill)   #
# --------------------------------------------------------------------------- #

# The four fields that GATE the pipeline. data_sources is auto-defaulted and
# never blocks, so it is intentionally NOT in this list.
GATING_FIELDS = ["role", "subject", "focus", "objective"]

# Roles are restricted to exactly these two.
ROLE_CHOICES = ["Marketing", "Product Owner"]
ROLE_SYNONYMS = {
    "marketing": "Marketing",
    "marketer": "Marketing",
    "mkt": "Marketing",
    "growth": "Marketing",
    "brand": "Marketing",
    "product owner": "Product Owner",
    "po": "Product Owner",
    "product manager": "Product Owner",
    "pm": "Product Owner",
    "product": "Product Owner",
}

# Default data sources when the user names none.
DEFAULT_DATA_SOURCES = ["app_store", "google_play", "youtube", "tinhte", "voz"]

DATA_SOURCE_LABELS = {
    "app_store": "App Store",
    "google_play": "Google Play",
    "youtube": "YouTube",
    "tinhte": "Tinhte",
    "voz": "Voz",
    "reddit": "Reddit",
}

SOURCE_ALIASES = {
    "app store": "app_store", "appstore": "app_store", "ios": "app_store",
    "app_store": "app_store",
    "google play": "google_play", "ch play": "google_play", "chplay": "google_play",
    "play store": "google_play", "android": "google_play", "google_play": "google_play",
    "youtube": "youtube", "yt": "youtube",
    "tinhte": "tinhte", "tinh te": "tinhte",
    "voz": "voz",
    "reddit": "reddit",
}

DEFAULT_MARKET = "Vietnam"
DEFAULT_TIME_RANGE = "last_90_days"
DEFAULT_SENTIMENT = "all"

# When the objective clearly targets negative feedback, derive sentiment=negative.
NEGATIVE_HINT = re.compile(
    r"negativ|complain|dissatisf|churn|crash|\bbug\b|\bissue\b|\bproblem\b|"
    r"bad review|low rating|1[\s,\-/]*(?:&|and)?[\s,]*2?\s*star|one[\s-]?star|two[\s-]?star",
    re.IGNORECASE,
)

# Neutral question TEMPLATES per gating field. The tool intentionally ships NO
# canned answer choices: the LLM authors contextual choices from the user's actual
# prompt and passes them in state["questions"]. `role` is the ONLY field whose
# choices are fixed, because the spec restricts roles to exactly two values.
FIELD_META = {
    "role": {"type": "single_select", "question": "Which role best describes you?"},
    "subject": {"type": "text", "question": "Which company or product do you want to research?"},
    "focus": {"type": "single_select", "question": "Which feature or topic should we focus on?"},
    "objective": {"type": "single_select", "question": "What is your primary objective for this research?"},
}

MAX_CHOICES = 3

# --------------------------------------------------------------------------- #
# Normalization helpers                                                       #
# --------------------------------------------------------------------------- #


def normalize_role(value):
    """Map a fuzzy role string to one of ROLE_CHOICES, or None if unresolvable."""
    if not value:
        return None
    key = str(value).strip().lower()
    return ROLE_SYNONYMS.get(key)


def normalize_sources(sources):
    """Map source names to canonical keys (deduped, ordered).

    Hardened against malformed input the LLM might emit:
    - a bare string is treated as a single source (not iterated char-by-char);
    - any non-list/non-string value falls back to the five defaults;
    - non-string elements are skipped, not stringified into bogus sources;
    - unknown sources (typos like "youtub", off-contract like "facebook") are
      dropped — only canonical sources in SOURCE_ALIASES survive.
    If nothing valid remains, default to all five sources.
    """
    if isinstance(sources, str):
        sources = [sources]
    if not isinstance(sources, (list, tuple)) or not sources:
        return list(DEFAULT_DATA_SOURCES)
    out = []
    for s in sources:
        if not isinstance(s, str):
            continue
        canon = SOURCE_ALIASES.get(s.strip().lower())
        if canon and canon not in out:
            out.append(canon)
    return out or list(DEFAULT_DATA_SOURCES)


def compute_missing(state):
    """Return the gating fields that are still missing or invalid."""
    missing = []
    for field in GATING_FIELDS:
        value = state.get(field)
        if field == "role":
            if normalize_role(value) is None:
                missing.append(field)
        else:
            if value is None or not str(value).strip():
                missing.append(field)
    return missing


def derive_sentiment(objective, explicit):
    if explicit:
        return explicit
    if objective and NEGATIVE_HINT.search(str(objective)):
        return "negative"
    return DEFAULT_SENTIMENT


def humanize_time_range(time_range):
    return str(time_range).replace("last_", "last ").replace("_", " ")


# --------------------------------------------------------------------------- #
# Envelope builders                                                           #
# --------------------------------------------------------------------------- #


def build_validate(state):
    """Internal helper (NOT for the FE): tells the LLM what to call next."""
    missing = compute_missing(state)
    return {
        "complete": len(missing) == 0,
        "missing": missing,
        "ready_for": "plan" if not missing else "clarify",
        "normalized": {
            "role": normalize_role(state.get("role")),
            "data_sources": normalize_sources(state.get("data_sources")),
        },
    }


def _normalize_question(q):
    """Validate & format a single (LLM-authored or skeletal) question object.

    The CONTENT (question text, choices, recommended) comes from the LLM so it is
    contextual to the user's prompt — the tool never invents canned choices. The
    tool only GUARANTEES the structure: all six keys present, <=3 choices, the
    literal "Other" stripped, and allow_other always true.
    """
    key = str(q.get("key") or "").strip()
    meta = FIELD_META.get(key, {})

    qtype = q.get("type") or meta.get("type") or "text"
    question_text = q.get("question") or meta.get("question") or ("Please clarify '%s'." % key)

    choices = q.get("choices")
    if not isinstance(choices, list):
        choices = []
    if key == "role":
        # The one spec-fixed field: choices are always the two valid roles.
        choices = list(ROLE_CHOICES)
    else:
        choices = [c for c in choices if isinstance(c, str) and c.strip()]
        # The literal "Other" is never a semantic choice — allow_other handles it.
        choices = [c for c in choices if c.strip().lower() != "other"]
        choices = choices[:MAX_CHOICES]
        # A select with no choices is meaningless -> present it as free text.
        if qtype in ("single_select", "multi_select") and not choices:
            qtype = "text"

    recommended = q.get("recommended")
    if not isinstance(recommended, str) or not recommended.strip():
        recommended = None
    elif choices and recommended not in choices:
        recommended = None

    return {
        "key": key,
        "type": qtype,
        "question": question_text,
        "choices": choices,
        "recommended": recommended,
        "allow_other": True,  # always — the user can always type a free answer
    }


def build_clarification(state):
    """CLARIFICATION_REQUIRED envelope. Batches every still-missing question.

    The LLM may pass `clarify_fields` to ask only specific fields (edge case:
    re-asking just the ambiguous one) and `reclarify_reason` for a 2nd-round reason.
    """
    authored = state.get("questions")
    if isinstance(authored, list) and authored:
        # Primary path: the LLM authored contextual questions (choices derived
        # from the user's prompt). Trust their field selection; just format.
        raw = [q for q in authored if isinstance(q, dict) and str(q.get("key") or "").strip()]
    else:
        # Defensive fallback: no authored questions -> ask the missing fields with
        # neutral templates and NO canned choices (free text via allow_other).
        explicit = state.get("clarify_fields")
        if isinstance(explicit, list) and any(isinstance(f, str) for f in explicit):
            fields = [f for f in explicit if isinstance(f, str)]
        else:
            fields = compute_missing(state)
        raw = [{"key": f} for f in fields]

    if not raw:
        # Nothing left to clarify -> the state is complete; planning is the
        # correct output. Never emit a CLARIFICATION_REQUIRED with zero questions.
        return build_plan(state)

    questions = [_normalize_question(q) for q in raw]

    payload = {}
    reason = state.get("reclarify_reason")
    if isinstance(reason, str) and reason.strip():
        payload["reason"] = reason
    payload["suggestedQuestions"] = questions
    return {"response_type": "CLARIFICATION_REQUIRED", "payload": payload}


def build_summary(intent):
    sources = ", ".join(
        DATA_SOURCE_LABELS.get(s, s) for s in intent["data_sources"]
    )
    return (
        "Through a {audience} lens, research {subject}'s '{focus}' to {objective}. "
        "Pull user reviews from {sources} over the {time_human} "
        "(sentiment: {sentiment})."
    ).format(
        audience=intent["audience"],
        subject=intent["subject"],
        focus=intent["focus"],
        objective=intent["objective"],
        sources=sources,
        time_human=humanize_time_range(intent["filters"]["time_range"]),
        sentiment=intent["filters"]["sentiment"],
    )


def build_plan(state):
    """PLAN_CONFIRMATION envelope. Applies all defaults deterministically.

    Gating safety net: this is the deterministic guarantee of the FE contract,
    so it re-checks the gating fields. If any are missing/invalid (e.g. an
    out-of-vocabulary role like "DEV", or an empty subject), it routes back to
    clarification rather than emitting a spec-violating plan.
    """
    missing = compute_missing(state)
    if missing:
        return build_clarification(state)

    subject = state.get("subject")
    role = normalize_role(state.get("role"))  # guaranteed resolvable past the gate
    focus = state.get("focus")
    objective = state.get("objective")

    data_sources = normalize_sources(state.get("data_sources"))

    competitors = state.get("competitors")
    if isinstance(competitors, str) and competitors.strip():
        competitors = [competitors]
    if not isinstance(competitors, list):
        competitors = []
    competitors = [c for c in competitors if isinstance(c, str) and c.strip()] or [subject]

    market = state.get("market")
    if not isinstance(market, str) or not market.strip():
        market = DEFAULT_MARKET

    filters_in = state.get("filters")
    if not isinstance(filters_in, dict):
        filters_in = {}
    time_range = filters_in.get("time_range") or DEFAULT_TIME_RANGE
    sentiment = derive_sentiment(objective, filters_in.get("sentiment"))
    keywords = filters_in.get("keywords")
    if not isinstance(keywords, list):
        keywords = []

    intent = {
        "subject": subject,
        "market": market,
        "competitors": competitors,
        "audience": role,
        "objective": objective,
        "focus": focus,
        "data_sources": data_sources,
        "filters": {
            "time_range": time_range,
            "sentiment": sentiment,
            "keywords": keywords,
        },
    }
    resolved_apps = state.get("resolved_apps")
    if not isinstance(resolved_apps, list):
        resolved_apps = []

    payload = {
        "intent": intent,
        "plan": {
            "summary": build_summary(intent),
        },
    }
    if resolved_apps:
        payload["resolved_apps"] = resolved_apps

    return {"response_type": "PLAN_CONFIRMATION", "payload": payload}


def build_error(message):
    return {
        "response_type": "ERROR",
        "error": {"message": message or "Please input correctly"},
    }


# --------------------------------------------------------------------------- #
# Output                                                                      #
# --------------------------------------------------------------------------- #


def emit(envelope):
    """Print the response envelope as a single compact JSON object."""
    sys.stdout.write(json.dumps(envelope, ensure_ascii=False) + "\n")


def _parse_state(raw):
    state = json.loads(raw)
    if not isinstance(state, dict):
        raise ValueError("state must be a JSON object")
    return state


def main(argv):
    if len(argv) < 2:
        emit(build_error("Missing subcommand. Use: validate | clarify | plan | error"))
        return 1

    cmd = argv[1]

    if cmd == "error":
        message = argv[2] if len(argv) > 2 else None
        emit(build_error(message))
        return 0

    if len(argv) < 3:
        emit(build_error("Missing state JSON argument."))
        return 1

    try:
        state = _parse_state(argv[2])
    except Exception as exc:  # malformed input -> ERROR envelope, never a crash
        emit(build_error("Invalid state JSON: %s" % exc))
        return 1

    # Defense in depth: any unforeseen builder fault becomes an ERROR envelope,
    # never a traceback ("malformed input -> ERROR envelope, never a crash").
    try:
        if cmd == "validate":
            # Internal helper only — single object, for the agent (not the FE).
            sys.stdout.write(json.dumps(build_validate(state), ensure_ascii=False) + "\n")
            return 0
        if cmd == "clarify":
            emit(build_clarification(state))
            return 0
        if cmd == "plan":
            emit(build_plan(state))
            return 0
    except Exception as exc:
        emit(build_error("Internal error: %s" % exc))
        return 1

    emit(build_error("Unknown subcommand: %s" % cmd))
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
