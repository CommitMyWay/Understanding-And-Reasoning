"""
clarification_engine.py
-----------------------
Generates exactly ONE clarifying question based on the highest-priority
missing required field in the current intent.

Field priority: subject → market → target_user → goal

Changes:
  - target_user replaces goal as the multiple-choice field (product/marketing/quality)
  - goal is now a free-text research objective (asked after target_user is known)
  - market options are dynamically suggested based on the subject (TikTok Shop → UK/SEA...)
  - All questions return an options array for clickable quick-reply

Language detection: Vietnamese diacritics → vi, otherwise en.
"""

import argparse
import json
import re
import sys

# ---------------------------------------------------------------------------
# Priority order
# ---------------------------------------------------------------------------

FIELD_PRIORITY = ["subject", "market", "target_user", "goal"]
MAX_RETRIES_PER_FIELD = 2

# ---------------------------------------------------------------------------
# Smart market hints per subject
# ---------------------------------------------------------------------------

# Maps product name keywords → likely markets (ordered by relevance)
SUBJECT_MARKET_HINTS: dict[str, list[str]] = {
    "tiktok shop":  ["Vietnam", "Indonesia", "UK", "USA", "Thailand", "Philippines", "Malaysia"],
    "tiktok":       ["Vietnam", "Indonesia", "USA", "UK", "Thailand", "Philippines"],
    "shopee":       ["Vietnam", "Indonesia", "Thailand", "Philippines", "Malaysia", "Singapore"],
    "lazada":       ["Vietnam", "Indonesia", "Thailand", "Philippines", "Malaysia", "Singapore"],
    "grab":         ["Vietnam", "Indonesia", "Thailand", "Philippines", "Malaysia", "Singapore"],
    "gojek":        ["Indonesia", "Vietnam", "Thailand", "Philippines"],
    "momo":         ["Vietnam"],
    "zalopay":      ["Vietnam"],
    "zalo":         ["Vietnam"],
    "vnpay":        ["Vietnam"],
    "tiki":         ["Vietnam"],
    "sendo":        ["Vietnam"],
    "airbnb":       ["Vietnam", "Indonesia", "USA", "UK", "Thailand", "Global"],
    "agoda":        ["Vietnam", "Indonesia", "Thailand", "Philippines", "Malaysia", "Singapore"],
    "booking":      ["Vietnam", "Indonesia", "USA", "UK", "Global"],
    "facebook":     ["Vietnam", "Indonesia", "USA", "UK", "Global"],
    "instagram":    ["Vietnam", "Indonesia", "USA", "UK", "Global"],
    "youtube":      ["Vietnam", "Indonesia", "USA", "UK", "Global"],
    "netflix":      ["Vietnam", "Indonesia", "USA", "UK", "Global"],
    "spotify":      ["Vietnam", "Indonesia", "USA", "UK", "Global"],
    "amazon":       ["USA", "UK", "Germany", "Japan", "India", "Global"],
    "uber":         ["USA", "UK", "Indonesia", "Vietnam", "Thailand", "Global"],
    "paypal":       ["USA", "UK", "Germany", "Australia", "Global"],
}

DEFAULT_MARKET_OPTIONS = {
    "en": ["Vietnam", "Indonesia", "Thailand", "Philippines", "Malaysia", "Singapore", "Global"],
    "vi": ["Việt Nam", "Indonesia", "Thái Lan", "Philippines", "Malaysia", "Singapore", "Toàn cầu"],
}


def _get_market_options(subject: str | None, lang: str) -> list[str]:
    """Return market options tailored to the subject, falling back to defaults."""
    if subject:
        subject_lower = subject.lower()
        for key, markets in SUBJECT_MARKET_HINTS.items():
            if key in subject_lower or subject_lower in key:
                return markets
    return DEFAULT_MARKET_OPTIONS.get(lang, DEFAULT_MARKET_OPTIONS["en"])


# ---------------------------------------------------------------------------
# Question templates
# ---------------------------------------------------------------------------

QUESTIONS = {
    "subject": {
        "en": "Which product or app would you like to analyze?",
        "vi": "Bạn muốn phân tích sản phẩm hoặc ứng dụng nào?",
    },
    "market": {
        "en": "Which market should I focus on?",
        "vi": "Bạn muốn phân tích thị trường nào?",
    },
    "target_user": {
        "en": "What is the goal of this analysis?",
        "vi": "Mục tiêu phân tích này là gì?",
    },
    "goal": {
        "en": "What specifically would you like to find out?",
        "vi": "Bạn muốn tìm hiểu điều gì cụ thể?",
    },
}

QUESTIONS_WITH_SUBJECT = {
    "market": {
        "en": "Which market should I analyze {subject} in?",
        "vi": "Tôi nên phân tích {subject} ở thị trường nào?",
    },
    "target_user": {
        "en": "What is the goal of this {subject} analysis?",
        "vi": "Mục tiêu phân tích {subject} này là gì?",
    },
    "goal": {
        "en": "What specifically would you like to find out about {subject}?",
        "vi": "Bạn muốn tìm hiểu điều gì cụ thể về {subject}?",
    },
}

# Retry prompts when first answer was ambiguous
RETRY_QUESTIONS = {
    "target_user": {
        "en": "Please choose one: Product (feature/UX), Marketing (brand & perception), or Quality (bugs & ratings).",
        "vi": "Vui lòng chọn một: Product (tính năng/UX), Marketing (thương hiệu), hoặc Quality (lỗi & chất lượng).",
    },
    "market": {
        "en": "Please name a specific market or region (e.g., Vietnam, UK, Southeast Asia).",
        "vi": "Vui lòng chỉ định thị trường hoặc khu vực (ví dụ: Việt Nam, Anh, Đông Nam Á).",
    },
    "subject": {
        "en": "Please provide the product or app name you want to analyze.",
        "vi": "Vui lòng cung cấp tên sản phẩm hoặc ứng dụng bạn muốn phân tích.",
    },
    "goal": {
        "en": "Please describe your research objective in one sentence (e.g., 'understand what causes checkout abandonment').",
        "vi": "Vui lòng mô tả mục tiêu nghiên cứu trong một câu (ví dụ: 'hiểu lý do user bỏ giỏ hàng').",
    },
}

# Static options for multiple-choice fields
STATIC_OPTIONS = {
    "target_user": {
        "en": ["Product", "Marketing", "Quality"],
        "vi": ["Product", "Marketing", "Quality"],
    },
    "data_source": {
        "en": ["App Store", "CH Play", "Youtube", "Voz", "Tinhte", "Reddit", "All sources"],
        "vi": ["App Store", "CH Play", "Youtube", "Voz", "Tinhte", "Reddit", "Tất cả"],
    },
}

# Goal hint examples based on target_user (shown in the question)
GOAL_EXAMPLES = {
    "product": {
        "en": "e.g. 'pain points in checkout flow', 'features users want most', 'UX issues in onboarding'",
        "vi": "ví dụ: 'vấn đề trong luồng thanh toán', 'tính năng user mong muốn', 'lỗi UX khi đăng ký'",
    },
    "marketing": {
        "en": "e.g. 'brand sentiment trends', 'what drives users to competitors', 'perception of the app'",
        "vi": "ví dụ: 'xu hướng cảm nhận thương hiệu', 'lý do user chuyển sang đối thủ'",
    },
    "quality": {
        "en": "e.g. 'most reported crashes', 'performance issues on Android', 'regression since last update'",
        "vi": "ví dụ: 'lỗi crash phổ biến nhất', 'vấn đề hiệu năng trên Android', 'regression sau bản cập nhật'",
    },
}

# ---------------------------------------------------------------------------
# Confirmation keywords (language-aware)
# ---------------------------------------------------------------------------

CONFIRMATION_KEYWORDS_EN = {
    "yes", "confirm", "ok", "okay", "approve", "proceed",
    "go ahead", "do it", "ship it", "lgtm", "sure", "correct",
    "sounds good", "looks good", "go", "start", "let's go",
}
CONFIRMATION_KEYWORDS_VI = {
    "có", "đúng", "ổn", "được", "tiến hành", "làm đi",
    "ok", "đồng ý", "chính xác", "chuẩn", "tiếp tục", "bắt đầu", "go",
}

# ---------------------------------------------------------------------------
# Language detection
# ---------------------------------------------------------------------------

_VI_PATTERN = re.compile(
    r"[àáâãèéêìíòóôõùúýăđơưạảấầẩẫậắằẳẵặẹẻẽếềểễệỉịọỏốồổỗộớờởỡợụủứừửữựỳỷỹỵ]",
    re.IGNORECASE,
)


def detect_language(history: list[dict]) -> str:
    for turn in reversed(history):
        if turn.get("role") == "user":
            if _VI_PATTERN.search(turn.get("message", "")):
                return "vi"
    return "en"


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------

def _build_one_question(
    field: str,
    lang: str,
    subject: str | None,
    target_user: str | None,
    field_attempts: int,
) -> dict:
    """Build a single question object for one missing field."""
    # Choose question wording
    if field_attempts > 0 and field in RETRY_QUESTIONS:
        question = RETRY_QUESTIONS[field][lang]
    elif subject and field in QUESTIONS_WITH_SUBJECT:
        question = QUESTIONS_WITH_SUBJECT[field][lang].format(subject=subject)
    else:
        question = QUESTIONS[field][lang]

    # Append goal hint examples
    if field == "goal":
        examples_key = target_user or "product"
        hint = GOAL_EXAMPLES.get(examples_key, GOAL_EXAMPLES["product"])[lang]
        question = f"{question} ({hint})"

    # Determine options
    if field == "market":
        options = _get_market_options(subject, lang)
    elif field in STATIC_OPTIONS:
        options = STATIC_OPTIONS[field][lang]
    else:
        options = None  # free-text (subject, goal)

    result = {
        "field":          field,
        "question":       question,
        "language":       lang,
        "attempt_number": field_attempts + 1,
    }
    if options:
        result["options"] = options
    return result


def get_clarification_question(
    missing: list[str],
    history: list[dict],
    subject: str | None = None,
    target_user: str | None = None,
    attempts: dict | None = None,
) -> dict | None:
    """
    Returns ONE question dict (highest-priority missing field), or None.
    Used for single-question-per-turn flow.
    """
    if not missing:
        return None

    attempts = attempts or {}
    lang = detect_language(history)

    for field in FIELD_PRIORITY:
        if field not in missing:
            continue
        field_attempts = attempts.get(field, 0)
        if field_attempts >= MAX_RETRIES_PER_FIELD:
            continue
        return _build_one_question(field, lang, subject, target_user, field_attempts)

    return None


def get_all_clarification_questions(
    missing: list[str],
    history: list[dict],
    subject: str | None = None,
    target_user: str | None = None,
    attempts: dict | None = None,
) -> list[dict]:
    """
    Batch mode: returns ALL missing fields as a list of question objects.
    Used by response_formatter to build suggestedQuestions for the FE.
    Skips fields that have already hit max retries.
    """
    if not missing:
        return []

    attempts = attempts or {}
    lang = detect_language(history)
    results = []

    # Resolve target_user from already-answered fields if available
    # (so goal question gets the right examples)
    resolved_target_user = target_user

    for field in FIELD_PRIORITY:
        if field not in missing:
            continue
        field_attempts = attempts.get(field, 0)
        if field_attempts >= MAX_RETRIES_PER_FIELD:
            continue
        q = _build_one_question(field, lang, subject, resolved_target_user, field_attempts)
        results.append(q)

    return results


def is_confirmation(message: str, language: str = "en") -> bool:
    msg = message.strip().lower()
    return msg in (CONFIRMATION_KEYWORDS_EN | CONFIRMATION_KEYWORDS_VI)


# ---------------------------------------------------------------------------
# CLI entrypoint
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Generate clarifying question(s) for missing fields."
    )
    parser.add_argument("--missing",     required=True, help='JSON array e.g. \'["market","goal"]\'')
    parser.add_argument("--history",     default="[]",  help="Conversation history JSON array")
    parser.add_argument("--subject",     default=None)
    parser.add_argument("--target_user", default=None)
    parser.add_argument("--attempts",    default="{}", help='JSON object of attempt counts per field')
    parser.add_argument("--batch",       action="store_true",
                        help="Return ALL missing fields as a JSON array (for FE multi-card display)")
    args = parser.parse_args()

    try:
        missing  = json.loads(args.missing)
        history  = json.loads(args.history)
        attempts = json.loads(args.attempts)
    except json.JSONDecodeError as e:
        print(json.dumps({"error": f"Invalid JSON: {e}"}), file=sys.stderr)
        sys.exit(1)

    if args.batch:
        results = get_all_clarification_questions(
            missing, history,
            subject=args.subject,
            target_user=args.target_user,
            attempts=attempts,
        )
        print(json.dumps(results, ensure_ascii=False, indent=2))
    else:
        result = get_clarification_question(
            missing, history,
            subject=args.subject,
            target_user=args.target_user,
            attempts=attempts,
        )
        if result is None:
            print(json.dumps({"field": None, "question": None, "language": "en"}))
        else:
            print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
