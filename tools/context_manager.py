"""
context_manager.py
------------------
In-memory session context store for the VoC Task Understanding skill.

All state lives in a module-level dict keyed by session_id.
State is NOT persisted to disk — it resets when the process exits.

Usage (CLI):
    # Initialize a new session
    python tools/context_manager.py init --session my-session-id

    # Save context
    python tools/context_manager.py save \
        --session my-session-id \
        --context '{"subject":"MoMo","market":"Vietnam",...}'

    # Get context
    python tools/context_manager.py get --session my-session-id

    # Append a turn to conversation history
    python tools/context_manager.py append_turn \
        --session my-session-id \
        --role user \
        --message "Analyze MoMo"

    # Strip PII from all string fields in context
    python tools/context_manager.py strip_pii \
        --session my-session-id

    # Get the final intent JSON (strips internal meta-fields)
    python tools/context_manager.py get_intent_json \
        --session my-session-id

    # Reset session
    python tools/context_manager.py reset --session my-session-id
"""

import argparse
import json
import re
import sys
from copy import deepcopy
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# In-memory store (module-level singleton)
# ---------------------------------------------------------------------------

_SESSIONS: dict[str, dict] = {}

# ---------------------------------------------------------------------------
# PII patterns (shared with analyze_prompt.py)
# ---------------------------------------------------------------------------

_PII_PATTERNS = [
    r"\b[\w.+-]+@[\w-]+\.\w{2,}\b",   # email
    r"\b(?:\+84|0)\d{9,10}\b",         # VN phone
    r"\b\d{9,12}\b",                   # numeric ID
]


def _strip_pii_str(text: str) -> str:
    for p in _PII_PATTERNS:
        text = re.sub(p, "[REDACTED]", text, flags=re.IGNORECASE)
    return text


def _strip_pii_recursive(obj):
    if isinstance(obj, str):
        return _strip_pii_str(obj)
    if isinstance(obj, dict):
        return {k: _strip_pii_recursive(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_strip_pii_recursive(i) for i in obj]
    return obj


# ---------------------------------------------------------------------------
# Intent skeleton
# ---------------------------------------------------------------------------

def _empty_intent() -> dict:
    return {
        "subject": None,
        "market": None,
        "goal": None,
        "focus": None,
        "filters": {
            "time_range": "last_90_days",
            "platform": "all",
            "sentiment": "all",
            "keywords": [],
        },
        "clarifications_done": [],
        "plan_steps": [],
    }


def _empty_session(session_id: str) -> dict:
    return {
        "session_id": session_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "intent": _empty_intent(),
        "history": [],          # list of {role, message, timestamp}
        "state": "collecting",  # collecting | planning | confirmed | deep_dive
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def init_session(session_id: str) -> dict:
    """Create a fresh session and return it."""
    session = _empty_session(session_id)
    _SESSIONS[session_id] = session
    return deepcopy(session)


def get_session(session_id: str) -> dict:
    """Return the current session, creating one if it doesn't exist."""
    if session_id not in _SESSIONS:
        return init_session(session_id)
    return deepcopy(_SESSIONS[session_id])


def save_context(session_id: str, intent_update: dict) -> dict:
    """
    Merge `intent_update` into the session's intent fields.
    Internal meta-fields (missing_required, mode) are NOT stored.
    """
    session = get_session(session_id)
    internal_keys = {"missing_required", "mode"}

    for key, value in intent_update.items():
        if key in internal_keys:
            continue
        if key in session["intent"]:
            session["intent"][key] = value
        # Also update top-level state hints
        if key == "mode":
            if value == "planning":
                session["state"] = "planning"
            elif value == "deep_dive":
                session["state"] = "deep_dive"

    session["updated_at"] = datetime.now(timezone.utc).isoformat()
    _SESSIONS[session_id] = session
    return deepcopy(session)


def append_turn(session_id: str, role: str, message: str) -> dict:
    """Add a conversation turn (user or agent) to the history."""
    if role not in ("user", "agent"):
        raise ValueError(f"Invalid role: {role}. Must be 'user' or 'agent'.")
    session = get_session(session_id)
    session["history"].append({
        "role": role,
        "message": _strip_pii_str(message),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })
    session["updated_at"] = datetime.now(timezone.utc).isoformat()
    _SESSIONS[session_id] = session
    return deepcopy(session)


def mark_confirmed(session_id: str) -> dict:
    """Mark the session as confirmed — ready to emit intent JSON."""
    session = get_session(session_id)
    session["state"] = "confirmed"
    session["updated_at"] = datetime.now(timezone.utc).isoformat()
    _SESSIONS[session_id] = session
    return deepcopy(session)


def strip_pii(session_id: str) -> dict:
    """Run PII stripping over all string fields in intent and history."""
    session = get_session(session_id)
    session["intent"] = _strip_pii_recursive(session["intent"])
    session["history"] = _strip_pii_recursive(session["history"])
    session["updated_at"] = datetime.now(timezone.utc).isoformat()
    _SESSIONS[session_id] = session
    return deepcopy(session)


def get_intent_json(session_id: str) -> dict:
    """
    Return the clean intent object — safe to pass to downstream skills.
    Strips PII first. Does not include history or internal session metadata.
    """
    strip_pii(session_id)
    session = _SESSIONS[session_id]
    return deepcopy(session["intent"])


def reset_session(session_id: str) -> dict:
    """Wipe and reinitialise the session."""
    return init_session(session_id)


# ---------------------------------------------------------------------------
# CLI entrypoint
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="VoC in-memory context manager.")
    parser.add_argument(
        "command",
        choices=["init", "get", "save", "append_turn", "strip_pii", "get_intent_json", "reset"],
    )
    parser.add_argument("--session", required=True, help="Session ID")
    parser.add_argument("--context", default=None, help="Intent JSON string (for 'save')")
    parser.add_argument("--role", default=None, help="'user' or 'agent' (for 'append_turn')")
    parser.add_argument("--message", default=None, help="Message text (for 'append_turn')")
    args = parser.parse_args()

    try:
        if args.command == "init":
            result = init_session(args.session)
        elif args.command == "get":
            result = get_session(args.session)
        elif args.command == "save":
            if not args.context:
                print(json.dumps({"error": "--context required for save"}), file=sys.stderr)
                sys.exit(1)
            intent_update = json.loads(args.context)
            result = save_context(args.session, intent_update)
        elif args.command == "append_turn":
            if not args.role or not args.message:
                print(json.dumps({"error": "--role and --message required"}), file=sys.stderr)
                sys.exit(1)
            result = append_turn(args.session, args.role, args.message)
        elif args.command == "strip_pii":
            result = strip_pii(args.session)
        elif args.command == "get_intent_json":
            result = get_intent_json(args.session)
        elif args.command == "reset":
            result = reset_session(args.session)
        else:
            print(json.dumps({"error": f"Unknown command: {args.command}"}), file=sys.stderr)
            sys.exit(1)

        print(json.dumps(result, ensure_ascii=False, indent=2))

    except json.JSONDecodeError as e:
        print(json.dumps({"error": f"Invalid JSON: {e}"}), file=sys.stderr)
        sys.exit(1)
    except ValueError as e:
        print(json.dumps({"error": str(e)}), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
