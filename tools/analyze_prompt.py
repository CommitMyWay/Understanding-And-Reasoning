"""
analyze_prompt.py
-----------------
Parses a raw user message and merges the result with the current session context
to produce an updated intent state.

Fields:
  - subject      : company/product/app/service/feature/topic/competitor being analyzed (required)
  - market       : geographic scope (required)
  - target_user  : who is analyzing — product | marketing | quality (required)
  - goal         : free-text research objective, e.g. "pain points in payment feature" (required)
  - focus        : sub-topic for deep-dive follow-ups (optional)
  - data_source  : list of sources to pull from (default = all 6)

Fixes:
  - #6: _extract_focus skips FOCUS_STOP_WORDS
  - #7: mode=deep_dive only when ALL required fields are resolved
  - #10: _extract_market with broader country list + word-boundary guard
"""

import argparse
import json
import re
import sys

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

REQUIRED_FIELDS = ["subject", "market", "target_user", "goal"]

# target_user detection (who is doing the analysis)
TARGET_USER_KEYWORDS = {
    "product": [
        "product owner", "po ", " po,", "product manager", " pm ", "pm,",
        "ux", "user experience", "usability", "flow", "ui", "roadmap",
        "sản phẩm", "tính năng", "trải nghiệm",
        "user journey", "conversion", "onboarding", "payment flow", "checkout",
        "adoption", "wireframe", "customer journey", "pain point",
        "người dùng", "hành trình", "chuyển đổi", "giữ chân", "luồng thanh toán",
        "giao diện", "thiết kế", "điểm chạm",
    ],
    "marketing": [
        "marketing", "marketer", "brand", "perception", "awareness", "campaign",
        "acquisition", "retention", "thương hiệu", "quảng cáo", "nhận thức",
        "mkt", "i am a market",
        "churn", "social", "sentiment", "nps", "csat", "engagement", "promoter",
        "customer success", "voucher", "promo", "positioning", "voice",
        "khuyến mãi", "chăm sóc khách hàng", "truyền thông", "cảm xúc",
        "đánh giá", "tương tác", "định vị", "khách hàng trung thành",
    ],
    # quality role removed — scope is now Marketer (MKT) and Product Owner (PO) only
}

# Supported data sources
ALL_DATA_SOURCES = ["App Store", "CH Play", "Youtube", "Voz", "Tinhte", "Reddit"]

DATA_SOURCE_TOKENS = {
    "app store": "App Store",
    "appstore": "App Store",
    "ios": "App Store",
    "ch play": "CH Play",
    "chplay": "CH Play",
    "google play": "CH Play",
    "play store": "CH Play",
    "android": "CH Play",
    "youtube": "Youtube",
    "voz": "Voz",
    "tinhte": "Tinhte",
    "tinh tế": "Tinhte",
    "reddit": "Reddit",
}

DEEP_DIVE_PATTERNS = [
    # ---- Original English ----
    r"\bwhy\b",
    r"\bwhat cause",
    r"\broot cause",
    r"\bdeep.?dive\b",
    r"\banalyze\s+(?:the\s+)?(\w+)\s+(?:group|cluster|issue|complaint|problem)",
    r"\btell me more about\b",
    r"\bbreak down\b",
    
    # ---- Added English ----
    r"\binvestigate\b",
    r"\bdrill.?down\b",               # Bắt cả 'drilldown' và 'drill down'
    r"\blook into\b",
    r"\breason(?:s)? behind\b",       # Bắt 'reason behind' và 'reasons behind'
    r"\bwhat(?:'s| is| are) (?:the )?caus(?:ing|e|es)\b", # Bắt 'what's causing', 'what is the cause', v.v.
    r"\bgive me (?:more )?details\b",
    r"\bexplain\b",
    r"\bclarify\b",

    # ---- Original Vietnamese ----
    r"\bphân tích sâu\b",
    r"\btại sao\b",
    r"\bvì sao\b",
    r"\bchi tiết\b",

    # ---- Added Vietnamese ----
    r"\bnguyên nhân\b",               # Rất hay dùng: "nguyên nhân là gì", "tìm nguyên nhân"
    r"\blý do\b",
    r"\bgiải thích\b",                # vd: "giải thích cho tôi..."
    r"\blàm rõ\b",
    r"\bđào sâu\b",
    r"\bđi sâu\b",
    r"\btìm hiểu thêm\b",
    r"\bcụ thể(?: hơn)?\b",           # Bắt 'cụ thể' hoặc 'cụ thể hơn'
    r"\bdo đâu\b",                    # vd: "lỗi này do đâu"
]

# Words that look like focus topics but are question/sentence starters
FOCUS_STOP_WORDS = {
    # ---- Original ----
    "Why", "What", "How", "When", "Where", "Who", "Which",
    "Tell", "Show", "Give", "Let", "Break", "Find", "Get", "Can",
    "Please", "Help", "Make", "Does", "Is", "Are", "Was", "Were",
    "Phân", "Tại", "Vì", "Hãy", "Cho", "Bạn", "Tôi",
    
    # ---- English Additions ----
    "Could", "Would", "Should", "Do", "Did", "Has", "Have", "Had",
    "Need", "Want", "I", "You", "He", "She", "It", "We", "They",
    "A", "An", "The", "This", "That", "These", "Those", 
    "About", "On", "In", "At", "To", "From", "By", "With", "Explain",
    
    # ---- Vietnamese Additions ----
    "Làm", "Thế", "Nào", "Ai", "Ở", "Đâu", "Cái", "Gì", "Này", "Kia", "Đó",
    "Những", "Các", "Về", "Muốn", "Cần", "Nói", "Xem", "Dùng", "Sử", "Dụng",
    "Chúng", "Anh", "Chị", "Em", "Hắn", "Họ", "Và", "Hoặc", "Là", 
    "Có", "Không", "Đã", "Đang", "Sẽ", "Được", "Bị", "Thử", "Kiểm",
}

PII_PATTERNS = [
    r"\b[\w.+-]+@[\w-]+\.\w{2,}\b",                # Email
    r"\b(?:\+84|0)\d{9,10}\b",                      # VN phone number
    r"\b\d{9,12}\b",                                # Numeric ID (CCCD/CMND VN thường 9 hoặc 12 số)
    
    # ---- Additions for Fintech & Tech ----
    r"\b(?:\d[ -]*?){13,16}\b",                     # Credit/Debit Card (16 digits, optional spaces/dashes)
    r"\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b",           # IPv4 Address
    # NOTE: removed \b[A-Z0-9]{8,15}\b — too broad, redacts product names like ZALOPAY, MOMO
    # Real transaction codes are typically mixed with lowercase context or follow specific prefixes.
    r"\b(?:TXN|TRX|REF|VCB|TCB|MBB|ACB|VPB)[A-Z0-9]{6,12}\b",  # Prefixed transaction codes only
    r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b",           # Date of Birth (dd/mm/yyyy)
]

# Expanded market token list
MARKET_TOKENS = [
    # ---- Original ----
    "vietnam", "việt nam",
    "southeast asia", "sea",
    "indonesia", "thailand", "philippines", "singapore", "malaysia",
    "japan", "korea", "south korea", "china", "india",
    "usa", "united states", "us", "uk", "united kingdom",
    "australia", "europe", "global", "worldwide",
    "hồ chí minh", "hà nội", "hanoi", "ho chi minh",
    
    # ---- Vietnamese Local Markets ----
    "hcm", "hn", "đà nẵng", "da nang", "cần thơ", "can tho", 
    "hải phòng", "hai phong", "miền bắc", "miền nam", "miền trung", 
    "northern vietnam", "southern vietnam",
    
    # ---- Regional & Global Additions ----
    "apac", "asia", "asia pacific", "taiwan", "hong kong",
    "north america", "latam", "emea", "canada", "germany", "france",
]

# Patterns to extract a free-text research goal from a detailed message
GOAL_EXTRACT_PATTERNS_EN = [
    # ---- Original ----
    r"\b(?:research|find|study|look\s+for)\s+(.{10,120}?)\s+(?:of|for|from)\s+(?:product\s+)?[A-Z][a-z]",
    r"\bhelp\s+(?:me\s+)?(?:research|analyze|find|study|understand)\s+(.{10,120}?)(?:\s+and\s+(?:finally|propose|then|also)\b|\s*$)",
    r"\b(?:research|study|understand|investigate|explore)\s+(?:the\s+)?(.{8,80}?)(?:\s+(?:of|for)\s+(?:product\s+)?[A-Z]|\s*$)",
    r"\babout\s+(.{6,60}?)\s+(?:issues?|feedback|complaints?|problems?|bugs?|crashes?)",
    r"(?:negative\s+)?(?:feedback|complaints?|issues?|bugs?)\s+(?:about|on|with)\s+(.{5,60}?)(?:\s+in\s+|\s*$)",
    
    # ---- Added Patterns ----
    # "summarize/pull/gather the feedback/data for/about X"
    r"\b(?:summarize|pull|gather|get|collect)\s+(?:the\s+)?(?:data|feedback|reviews|complaints|comments|stats)\s+(?:for|about|on)\s+(.{5,80}?)(?:\s+(?:in|from|during)\s+|\s*$)",
    
    # "what are users saying about X" / "why are customers complaining about X"
    r"\b(?:why|what)\s+(?:are\s+)?(?:users|customers|people|they)\s+(?:complaining|saying|angry|frustrated|talking)\s+(?:about|with)\s+(.{5,80}?)(?:\s+(?:in|on|at)\s+|\s*$)",
    
    # "reasons behind user drop off in X" / "why users abandon X"
    r"\b(?:reasons?\s+)?(?:why|behind)\s+(?:users?\s+)?(?:drop\s+off|churn|leave|abandon|quit)\s+(.{5,60}?)(?:\s+(?:in|on|at)\s+|\s*$)",
    
    # "give me a summary of X"
    r"\b(?:give\s+(?:me\s+)?(?:a\s+)?summary\s+of|summarize)\s+(.{8,100}?)(?:\s+(?:and|for|in|from)\s+|\s*$)",
]

GOAL_EXTRACT_PATTERNS_VI = [
    # ---- Original ----
    r"(?:phản hồi|khiếu nại|lỗi|vấn đề|nghiên cứu)\s+(?:về\s+)?(.{5,60}?)(?:\s+(?:ở|tại|của|cho)\s+|\s*$)",
    r"(?:tìm hiểu|nghiên cứu|phân tích)\s+(?:về\s+)?(.{5,60}?)(?:\s+(?:ở|tại)\s+|\s*$)",
    
    # ---- Added Patterns ----
    # "tổng hợp/lấy data/dữ liệu/feedback về X"
    r"(?:tổng hợp|lấy|thu thập|xem)\s+(?:data|dữ liệu|feedback|đánh giá|nhận xét|review)\s+(?:về|của|cho)\s+(.{5,80}?)(?:\s+(?:ở|tại|trong)\s+|\s*$)",
    
    # "tại sao khách hàng/user chê/phàn nàn/bỏ X"
    r"(?:tại sao|vì sao|lý do)\s+(?:khách hàng|người dùng|user|họ)\s+(?:chê|phàn nàn|kêu|bỏ|không dùng|huỷ)\s+(.{5,80}?)(?:\s+(?:ở|tại|trong)\s+|\s*$)",
    
    # "đánh giá/nhận xét của người dùng về X"
    r"(?:đánh giá|nhận xét|ý kiến)\s+(?:của\s+)?(?:người dùng|khách hàng|user)\s+(?:về\s+)?(.{5,80}?)(?:\s+(?:trên|ở|tại|trong)\s+|\s*$)",
    
    # "kiểm tra/check xem lỗi ở/của X"
    r"(?:kiểm tra|check)\s+(?:xem\s+)?(?:lỗi|tình trạng|vấn đề)\s+(?:của|ở|phần|luồng)\s+(.{5,80}?)(?:\s+(?:như thế nào|ra sao)|\s*$)",
]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _strip_pii(text: str) -> str:
    for pattern in PII_PATTERNS:
        text = re.sub(pattern, "[REDACTED]", text, flags=re.IGNORECASE)
    return text


def _detect_target_user(text: str) -> str | None:
    for tu, keywords in TARGET_USER_KEYWORDS.items():
        for kw in keywords:
            # Strip khoảng trắng thừa trong config (vd: " po," -> "po")
            clean_kw = kw.strip(" ,") 
            # Dùng \b để bắt từ độc lập, tránh lỗi "ui" dính vào "building"
            if re.search(r"\b" + re.escape(clean_kw) + r"\b", text, re.IGNORECASE):
                return tu
    return None


def _extract_goal_from_message(text: str) -> str | None:
    if len(text.split()) < 7:
        return None

    for pattern in GOAL_EXTRACT_PATTERNS_EN:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            candidate = m.group(1).strip().rstrip(".,")
            if len(candidate) >= 8:
                return candidate

    for pattern in GOAL_EXTRACT_PATTERNS_VI:
        # THÊM re.IGNORECASE VÀO ĐÂY
        m = re.search(pattern, text, re.IGNORECASE) 
        if m:
            candidate = m.group(1).strip().rstrip(".,")
            if len(candidate) >= 5:
                return candidate

    return None


def _detect_deep_dive(text: str) -> bool:
    # Bỏ text_lower, nhường việc xử lý hoa/thường cho thư viện re
    return any(re.search(p, text, re.IGNORECASE) for p in DEEP_DIVE_PATTERNS)


# Mẹo: Nên khai báo biến này ở file config hoặc ngoài hàm để tối ưu hiệu năng
FOCUS_STOP_WORDS_LOWER = {w.lower() for w in FOCUS_STOP_WORDS}

def _extract_focus(text: str, subject: str | None) -> str | None:
    for match in re.finditer(
        r"\b([A-Z][a-zA-Z0-9]+(?:\s[A-Z][a-zA-Z0-9]+)?)\b"
        r"(?:\s+(?:is|are|flow|feature|group|cluster|issue|complaint|problem|error|bug))?",
        text,
    ):
        candidate = match.group(1)
        # Fix: So sánh phiên bản in thường với tập lowercase
        if candidate.lower() in FOCUS_STOP_WORDS_LOWER:
            continue
        if subject and candidate.lower() == subject.lower():
            continue
        if candidate.lower() in MARKET_TOKENS:
            continue
        return candidate

    match_vi = re.search(
        r"(?:nhóm|vấn đề|tính năng|màn hình|chức năng)\s+([A-Za-zÀ-ɏ0-9]+)",
        text,
        re.IGNORECASE  # Thêm ignore case cho tiếng Việt
    )
    if match_vi:
        return match_vi.group(1)

    return None


def _extract_subject(text: str) -> str | None:
    patterns = [
        # Highest priority: "of product Zalopay", "product Zalopay" — keyword `product` specifically
        # Capture single product name only (stop at common conjunctions/prepositions)
        r"\bproduct\s+([A-Za-z0-9À-ɏ]{2,30})(?:\s+(?:and|or|,|in|for|to|the)\b|$)",
        # "analyze/review X in/for" — action verb before product name
        r"(?:analyze|analyse|phân tích|review|đánh giá|compare)\s+([A-Za-z0-9À-ɏ][A-Za-z0-9À-ɏ\s]{0,20}?)(?:\s+(?:in|for|ở|tại|về)|$)",
        # "Zalopay app" at sentence start
        r"^([A-Za-z0-9À-ɏ]{2,30})\s+(?:app|platform|service|ứng dụng)",
        # Single-word proper noun at start before "in/for" (no spaces allowed in capture)
        r"^([A-Z][a-zA-Z0-9]{2,25})\s+(?:in|for|ở|tại|cho)\s",
    ]
    for p in patterns:
        m = re.search(p, text, flags=re.IGNORECASE)
        if m:
            return m.group(1).strip()
    return None


def _extract_data_sources(text: str) -> list[str] | None:
    text_lower = text.lower()
    found = []
    for token, source in DATA_SOURCE_TOKENS.items():
        if token in text_lower and source not in found:
            found.append(source)
    return found if found else None


# Industry/category terms that look like markets but are not geographic markets
MARKET_BLACKLIST = {
    "product", "marketing", "quality", "the", "me", "us",
    "fintech", "tech", "technology", "company", "enterprise", "startup",
    "business", "industry", "sector", "app", "application", "platform",
    "service", "store", "market", "channel", "you", "we",
}


def _extract_market(text: str) -> str | None:
    # Primary: explicit preposition pattern
    m = re.search(
        r"(?:\bin\b|\bat\b|tại|ở|cho thị trường)\s+([A-Za-zÀ-ɏ][\w\s]{1,30}?)(?:\s+(?:for|with|to|and|,|$))",
        text,
        re.IGNORECASE,
    )
    if m:
        candidate = m.group(1).strip().rstrip(",.")
        if candidate.lower() not in MARKET_BLACKLIST:
            return candidate.title()

    # Simpler fallback with word boundary (fix #10: prevents "Login bad" → market="Bad")
    m2 = re.search(r"\b(?:in|at|tại|ở)\b\s+([A-Za-zÀ-ɏ]{3,})", text, re.IGNORECASE)
    if m2:
        candidate = m2.group(1).strip().title()
        if candidate.lower() not in MARKET_BLACKLIST:
            return candidate

    # Token list fallback (authoritative geographic list — word-boundary safe)
    text_lower = text.lower()
    for token in MARKET_TOKENS:
        if re.search(r"\b" + re.escape(token) + r"\b", text_lower):
            return token.title()

    return None


# ---------------------------------------------------------------------------
# Core parser
# ---------------------------------------------------------------------------

def parse(message: str, context: dict) -> dict:
    """
    Merges parsed fields from `message` into `context`.
    Returns updated intent dict with `missing_required` and `mode` added.
    """
    message = _strip_pii(message)

    is_deep_dive = _detect_deep_dive(message)

    # Extract new information from message
    extracted_subject = _extract_subject(message)
    extracted_market = _extract_market(message)
    extracted_target_user = _detect_target_user(message)
    extracted_goal = _extract_goal_from_message(message)
    extracted_focus = (
        _extract_focus(message, context.get("subject") or extracted_subject)
        if is_deep_dive else None
    )
    extracted_sources = _extract_data_sources(message)

    # Merge: only fill fields still null/missing in context
    intent = dict(context)
    if not intent.get("subject") and extracted_subject:
        intent["subject"] = extracted_subject
    if not intent.get("market") and extracted_market:
        intent["market"] = extracted_market
    if not intent.get("target_user") and extracted_target_user:
        intent["target_user"] = extracted_target_user
    if not intent.get("goal") and extracted_goal:
        intent["goal"] = extracted_goal
    if extracted_focus:
        intent["focus"] = extracted_focus
    if extracted_sources:
        intent["data_source"] = extracted_sources

    # Fix #7: deep_dive mode only when ALL required fields already resolved
    all_resolved = all(intent.get(f) for f in REQUIRED_FIELDS)
    if is_deep_dive and all_resolved:
        mode = "deep_dive"
    elif all_resolved:
        mode = "planning"
    else:
        mode = "clarification" if context.get("clarifications_done") else "initial"

    missing = [f for f in REQUIRED_FIELDS if not intent.get(f)]

    intent["missing_required"] = missing
    intent["mode"] = mode

    # Ensure keys exist
    intent.setdefault("focus", None)
    intent.setdefault("target_user", None)
    intent.setdefault("goal", None)
    intent.setdefault("data_source", list(ALL_DATA_SOURCES))
    intent.setdefault("filters", {})
    intent.setdefault("clarifications_done", [])
    intent.setdefault("plan_steps", [])

    return intent


# ---------------------------------------------------------------------------
# CLI entrypoint
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Parse a VoC user prompt into intent fields.")
    parser.add_argument("--message", required=True, help="Raw user message")
    parser.add_argument("--context", default="{}", help="Current session context as JSON string")
    args = parser.parse_args()

    try:
        context = json.loads(args.context)
    except json.JSONDecodeError as e:
        print(json.dumps({"error": f"Invalid context JSON: {e}"}), file=sys.stderr)
        sys.exit(1)

    result = parse(args.message, context)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
