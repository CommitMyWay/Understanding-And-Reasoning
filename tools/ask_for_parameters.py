"""
ask_for_parameters.py
---------------------
Formal tool that halts agent execution and demands a single missing
parameter from the user before the agent can proceed.

Inspired by XAgent's `ask_human_for_help` pattern:
- Registered as a tool call, not a conversational message
- One call = one missing field (never bundle multiple)
- Schema enforces specificity: agent must state WHICH field and WHY
- Execution is considered blocked until this tool returns a user answer

Usage (CLI):
    # Agent calls this when a required field is missing
    python tools/ask_for_parameters.py request \
        --session my-session \
        --field market \
        --reason "Cannot scope data fetch without geographic target" \
        --question "Which market should I analyze MoMo in?" \
        --options '["Vietnam", "Southeast Asia", "Global"]'

    # After user responds, agent submits the answer back
    python tools/ask_for_parameters.py respond \
        --session my-session \
        --field market \
        --value "Vietnam"

Output (request):
    {
        "status": "awaiting_user",
        "missing_field": "market",
        "question": "Which market should I analyze MoMo in?",
        "options": ["Vietnam", "Southeast Asia", "Global"],
        "instruction": "DO NOT proceed until respond is called with user answer."
    }

Output (respond):
    {
        "status": "resolved",
        "missing_field": "market",
        "value": "Vietnam",
        "retries_used": 1
    }
"""

import argparse
import json
import os
import sys
import tempfile
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VALID_FIELDS = ["subject", "market", "goal", "focus"]
FIELD_OPTIONS = {
    "goal": ["product", "marketing", "competitive"],
}
MAX_RETRIES = 2  # After this many failed attempts, agent should use default

# ---------------------------------------------------------------------------
# Session file helpers (file-based so CLI calls share state)
# ---------------------------------------------------------------------------

def _session_path(session_id: str) -> str:
    tmp = tempfile.gettempdir()
    return os.path.join(tmp, f"voc_ask_{session_id}.json")


def _load_state(session_id: str) -> dict:
    path = _session_path(session_id)
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return {"pending": None, "resolved": {}, "retries": {}}


def _save_state(session_id: str, state: dict):
    path = _session_path(session_id)
    with open(path, "w") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# Core operations
# ---------------------------------------------------------------------------

def request_parameter(
    session_id: str,
    field: str,
    reason: str,
    question: str,
    options: list[str] | None = None,
) -> dict:
    """
    Agent calls this to declare it is blocked on a missing field.
    Returns the question to surface to the user.
    Execution must not continue until `respond_parameter` is called.
    """
    if field not in VALID_FIELDS:
        return {"error": f"Invalid field '{field}'. Must be one of {VALID_FIELDS}"}

    state = _load_state(session_id)

    # Track retries
    retries = state["retries"].get(field, 0)
    if retries >= MAX_RETRIES:
        return {
            "status": "max_retries_reached",
            "missing_field": field,
            "instruction": (
                f"Field '{field}' has been asked {retries} times without a valid answer. "
                f"Use a sensible default and proceed. Do NOT ask again."
            ),
            "retries_used": retries,
        }

    # Use known options if not provided
    if options is None:
        options = FIELD_OPTIONS.get(field)

    state["pending"] = {
        "field": field,
        "reason": reason,
        "question": question,
        "options": options,
        "requested_at": datetime.now(timezone.utc).isoformat(),
        "retries": retries + 1,
    }
    state["retries"][field] = retries + 1
    _save_state(session_id, state)

    result = {
        "status": "awaiting_user",
        "missing_field": field,
        "reason_blocked": reason,
        "question": question,
        "instruction": "DO NOT proceed to planning or JSON emission until respond is called with the user's answer.",
    }
    if options:
        result["options"] = options
    return result


def respond_parameter(
    session_id: str,
    field: str,
    value: str,
) -> dict:
    """
    Called after the user provides an answer.
    Marks the field as resolved and unblocks the agent.
    """
    if field not in VALID_FIELDS:
        return {"error": f"Invalid field '{field}'."}

    state = _load_state(session_id)
    retries = state["retries"].get(field, 1)

    # Validate goal values
    if field == "goal" and value.lower() not in FIELD_OPTIONS["goal"]:
        return {
            "status": "invalid_value",
            "missing_field": field,
            "value_received": value,
            "valid_options": FIELD_OPTIONS["goal"],
            "instruction": "Value is not valid. Call request_parameter again for this field.",
        }

    state["resolved"][field] = value
    state["pending"] = None
    _save_state(session_id, state)

    return {
        "status": "resolved",
        "missing_field": field,
        "value": value,
        "retries_used": retries,
    }


def get_resolved(session_id: str) -> dict:
    """Return all fields resolved via ask_for_parameters in this session."""
    state = _load_state(session_id)
    return state.get("resolved", {})


def reset(session_id: str) -> dict:
    """Clear all ask_for_parameters state for the session."""
    path = _session_path(session_id)
    if os.path.exists(path):
        os.remove(path)
    return {"status": "reset", "session_id": session_id}


# ---------------------------------------------------------------------------
# Tool schema (for agent registration)
# ---------------------------------------------------------------------------

TOOL_SCHEMA = {
    "name": "ask_for_parameters",
    "description": (
        "Call this tool when a required parameter (subject, market, goal) is missing or ambiguous. "
        "Execution is blocked until the user provides the value. "
        "Call ONCE per missing field — do NOT bundle multiple fields in one call. "
        "Do NOT proceed to plan building or intent JSON emission while status is 'awaiting_user'."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "missing_field": {
                "type": "string",
                "enum": VALID_FIELDS,
                "description": "The specific parameter that is missing or ambiguous.",
            },
            "reason_blocked": {
                "type": "string",
                "description": "Why the agent cannot proceed without this parameter. Be specific.",
            },
            "question": {
                "type": "string",
                "description": "The exact question to present to the user. Single question only.",
            },
            "options": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Known valid values for this field, if applicable.",
            },
        },
        "required": ["missing_field", "reason_blocked", "question"],
    },
}


# ---------------------------------------------------------------------------
# CLI entrypoint
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="ask_for_parameters tool")
    sub = parser.add_subparsers(dest="command")

    # request
    req = sub.add_parser("request", help="Agent requests a missing parameter from user")
    req.add_argument("--session", required=True)
    req.add_argument("--field", required=True, choices=VALID_FIELDS)
    req.add_argument("--reason", required=True)
    req.add_argument("--question", required=True)
    req.add_argument("--options", default=None, help="JSON array of valid options")

    # respond
    res = sub.add_parser("respond", help="Submit user's answer for a pending field")
    res.add_argument("--session", required=True)
    res.add_argument("--field", required=True, choices=VALID_FIELDS)
    res.add_argument("--value", required=True)

    # get_resolved
    gr = sub.add_parser("get_resolved", help="Get all resolved fields")
    gr.add_argument("--session", required=True)

    # schema
    sub.add_parser("schema", help="Print the tool schema JSON")

    # reset
    rst = sub.add_parser("reset", help="Reset session state")
    rst.add_argument("--session", required=True)

    args = parser.parse_args()

    if args.command == "request":
        options = json.loads(args.options) if args.options else None
        result = request_parameter(args.session, args.field, args.reason, args.question, options)
    elif args.command == "respond":
        result = respond_parameter(args.session, args.field, args.value)
    elif args.command == "get_resolved":
        result = get_resolved(args.session)
    elif args.command == "schema":
        result = TOOL_SCHEMA
    elif args.command == "reset":
        result = reset(args.session)
    else:
        parser.print_help()
        sys.exit(1)

    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
