#!/bin/bash
# run_tests.sh — Automated test runner for voc-task-understanding skill
# Usage: bash run_tests.sh
# Results saved to: test_results.md

BASE="https://openclaw-111743-openclaw-xdf3x.agentbase-runtime.aiplatform.vngcloud.vn/v1/chat/completions"
TOKEN="IhJDKyzO1dEaF3DMGoDPWS3N73gKj5vc4vrG92HoFaJhm3labDWXtMm"
OUT="test_results.md"
PASS=0
FAIL=0
WARN=0

echo "# Test Results — voc-task-understanding" > "$OUT"
echo "_Run: $(date)_" >> "$OUT"
echo "" >> "$OUT"

call_agent() {
  local messages="$1"
  curl -s --max-time 30 --location "$BASE" \
    --header "Authorization: Bearer $TOKEN" \
    --header "Content-Type: application/json" \
    --data "{\"model\":\"openclaw:main\",\"messages\":$messages}" \
    | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['choices'][0]['message']['content'])" 2>/dev/null
}

run_test() {
  local id="$1"
  local label="$2"
  local messages="$3"
  local check_for="$4"      # string that MUST appear in response
  local must_not="$5"       # string that must NOT appear in response

  echo -n "[$id] $label ... "
  local resp
  resp=$(call_agent "$messages")

  if [ -z "$resp" ]; then
    echo "ERROR (no response)"
    echo "## ❌ $id — $label" >> "$OUT"
    echo '```' >> "$OUT"
    echo "(no response / timeout)" >> "$OUT"
    echo '```' >> "$OUT"
    ((FAIL++))
    return
  fi

  local status="✅ PASS"
  local note=""

  if [ -n "$check_for" ] && ! echo "$resp" | grep -qi "$check_for"; then
    status="❌ FAIL"
    note=" | Expected to find: \"$check_for\""
    ((FAIL++))
  elif [ -n "$must_not" ] && echo "$resp" | grep -qi "$must_not"; then
    status="⚠️  WARN"
    note=" | Should NOT contain: \"$must_not\""
    ((WARN++))
  else
    ((PASS++))
  fi

  echo "$status$note"
  echo "## $status $id — $label$note" >> "$OUT"
  echo '```' >> "$OUT"
  echo "$resp" >> "$OUT"
  echo '```' >> "$OUT"
  echo "" >> "$OUT"
}

echo "## Summary" >> "$OUT"
echo "" >> "$OUT"

# ---------------------------------------------------------------------------
# SKILL TRIGGER TESTS
# ---------------------------------------------------------------------------
echo "--- Skill Trigger ---"

run_test "T1" "Trigger: subject only (EN)" \
  '[{"role":"user","content":"using skill understanding-reasoning: Analyze MoMo"}]' \
  "market\|thị trường\|which market\|nào" ""

run_test "T2" "Trigger: Vietnamese input" \
  '[{"role":"user","content":"dùng skill understanding-reasoning: Tôi muốn phân tích ZaloPay"}]' \
  "thị trường\|market" ""

run_test "T3" "Trigger: deep-dive pattern" \
  '[{"role":"user","content":"using skill understanding-reasoning: Why is the Login feature complained about so much?"}]' \
  "product\|market\|subject\|phân tích\|analyze\|Login" ""

run_test "T6" "Trigger: Vietnamese deep-dive" \
  '[{"role":"user","content":"dùng skill understanding-reasoning: tại sao Login bị complain nhiều vậy?"}]' \
  "sản phẩm\|thị trường\|market\|Login" ""

# ---------------------------------------------------------------------------
# CLARIFICATION FLOW
# ---------------------------------------------------------------------------
echo "--- Clarification Flow ---"

run_test "C1a" "Clarification: asks market (not multiple questions)" \
  '[{"role":"user","content":"using skill understanding-reasoning: Analyze MoMo"}]' \
  "market\|thị trường" "goal\|product\|marketing"

run_test "C2" "Full intent one-shot: skip clarification" \
  '[{"role":"user","content":"using skill understanding-reasoning: Analyze MoMo in Vietnam for product insights"}]' \
  "plan\|confirm\|proceed\|xác nhận\|tiến hành" ""

run_test "C3" "Multi-turn: subject→market→goal→confirm" \
  '[{"role":"user","content":"using skill understanding-reasoning: Analyze MoMo"},{"role":"assistant","content":"Which market should I analyze MoMo in?"},{"role":"user","content":"Vietnam"},{"role":"assistant","content":"Is this analysis of MoMo for Product insights or Marketing insights?"},{"role":"user","content":"Product"}]' \
  "plan\|confirm\|xác nhận\|step\|fetch" ""

# ---------------------------------------------------------------------------
# DEEP DIVE
# ---------------------------------------------------------------------------
echo "--- Deep Dive ---"

run_test "D1" "Deep dive: Login after full context" \
  '[{"role":"user","content":"using skill understanding-reasoning: Analyze MoMo in Vietnam for product"},{"role":"assistant","content":"Plan confirmed. Fetching MoMo reviews..."},{"role":"user","content":"Why is Login complained about so much?"}]' \
  "Login\|deep.dive\|focus\|sub-theme\|drill" "which market\|thị trường\|what is your goal"

run_test "D3" "Deep dive: Vietnamese follow-up" \
  '[{"role":"user","content":"using skill understanding-reasoning: phân tích MoMo ở Việt Nam cho product"},{"role":"assistant","content":"Kế hoạch đã xác nhận."},{"role":"user","content":"Phân tích sâu nhóm Login"}]' \
  "Login" "thị trường\|market\|goal"

# ---------------------------------------------------------------------------
# EDGE CASES
# ---------------------------------------------------------------------------
echo "--- Edge Cases ---"

run_test "E1" "No subject: asks what to analyze" \
  '[{"role":"user","content":"using skill understanding-reasoning: Analyze"}]' \
  "product\|app\|sản phẩm\|ứng dụng\|what\|which\|nào" ""

run_test "E2" "Ambiguous goal: asks product or marketing" \
  '[{"role":"user","content":"using skill understanding-reasoning: Analyze MoMo in Vietnam for the team"}]' \
  "product\|marketing\|goal\|mục tiêu" ""

run_test "E7" "Guide only: how would you analyze" \
  '[{"role":"user","content":"using skill understanding-reasoning: How would you analyze MoMo?"}]' \
  "" "intent\|\"subject\"\|\"market\"\|\"goal\"\|plan_steps"

run_test "E8" "Non-confirmation does not auto-proceed" \
  '[{"role":"user","content":"using skill understanding-reasoning: Analyze MoMo in Vietnam for product"},{"role":"assistant","content":"Here is my plan: ... Shall I proceed?"},{"role":"user","content":"maybe later"}]' \
  "confirm\|proceed\|let me know\|whenever\|xác nhận" ""

# ---------------------------------------------------------------------------
# NEGATIVE CASES
# ---------------------------------------------------------------------------
echo "--- Negative Cases ---"

run_test "N1" "General question: no skill trigger" \
  '[{"role":"user","content":"using skill understanding-reasoning: What is MoMo?"}]' \
  "" "which market\|thị trường\|goal\|product insight"

run_test "N3" "No datasource skill: no hallucinated data" \
  '[{"role":"user","content":"using skill understanding-reasoning: Show me the top complaints for MoMo in Vietnam"}]' \
  "" "1\\.\|top complaint\|users said\|review shows"

# ---------------------------------------------------------------------------
# STANDALONE EDGE CASES
# ---------------------------------------------------------------------------
echo "--- Standalone ---"

run_test "S1" "After JSON emitted: asks for results" \
  '[{"role":"user","content":"using skill understanding-reasoning: Analyze MoMo in Vietnam for product"},{"role":"assistant","content":"{\"subject\":\"MoMo\",\"market\":\"Vietnam\",\"goal\":\"product\",\"plan_steps\":[]}"},{"role":"user","content":"So what are the results?"}]' \
  "datasource\|not yet\|chưa\|skill\|data" ""

run_test "S3" "No hallucinate complaint data" \
  '[{"role":"user","content":"using skill understanding-reasoning: Show me the top complaints for MoMo"}]' \
  "market\|thị trường\|which" "1\\. Login\|top 3\|most complained"

# ---------------------------------------------------------------------------
# SUMMARY
# ---------------------------------------------------------------------------
TOTAL=$((PASS + FAIL + WARN))
echo ""
echo "============================="
echo " PASS: $PASS / $TOTAL"
echo " FAIL: $FAIL / $TOTAL"
echo " WARN: $WARN / $TOTAL"
echo "============================="
echo "Full results: $OUT"

# Prepend summary table to results file
SUMMARY="| Result | Count |\n|---|---|\n| ✅ PASS | $PASS |\n| ❌ FAIL | $FAIL |\n| ⚠️  WARN | $WARN |\n| **Total** | **$TOTAL** |\n\n---\n\n"
TMP=$(mktemp)
{ echo -e "$SUMMARY"; cat "$OUT"; } > "$TMP" && mv "$TMP" "$OUT"
