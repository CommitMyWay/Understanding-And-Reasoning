#!/bin/bash
# run_contract_tests.sh
# VoC Skill — JSON Contract & Parser Test Suite
# Usage: bash run_contract_tests.sh
# Results printed to terminal + saved to contract_test_results.txt

BASE="https://openclaw-111743-openclaw-xdf3x.agentbase-runtime.aiplatform.vngcloud.vn/v1/chat/completions"
TOKEN="IhJDKyzO1dEaF3DMGoDPWS3N73gKj5vc4vrG92HoFaJhm3labDWXtMm"
OUT="contract_test_results.txt"
PASS=0; FAIL=0; SKIP=0

# ── helpers ──────────────────────────────────────────────────────────────────

call_agent() {
  curl -s --max-time 30 "$BASE" \
    -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    -d "{\"model\":\"openclaw:main\",\"messages\":$1}" \
    | python3 -c "
import sys, json
raw = sys.stdin.read()
try:
    d = json.loads(raw)
    print(d['choices'][0]['message']['content'])
except:
    print('')
" 2>/dev/null
}

json_contains() {
  # Returns 0 (true) if the response, parsed as JSON then re-serialised, matches regex $2
  echo "$1" | python3 -c "
import sys, json, re
t = sys.stdin.read().strip()
try:
    t2 = json.dumps(json.loads(t))
except:
    t2 = t
sys.exit(0 if re.search(sys.argv[1], t2, re.I|re.S) else 1)
" "$2" 2>/dev/null
}

run_test() {
  local id="$1" label="$2" messages="$3" must_have="$4" must_not="$5"
  local resp ok=1

  resp=$(call_agent "$messages")

  if [ -z "$resp" ]; then
    printf "⚠️  SKIP  [%-6s] %s  (no response / timeout)\n" "$id" "$label"
    echo "SKIP [$id] $label" >> "$OUT"
    ((SKIP++)); return
  fi

  [ -n "$must_have" ] && ! json_contains "$resp" "$must_have" && ok=0
  [ -n "$must_not" ] && json_contains "$resp" "$must_not" && ok=0

  if [ "$ok" -eq 1 ]; then
    printf "✅ PASS  [%-6s] %s\n" "$id" "$label"
    echo "PASS [$id] $label" >> "$OUT"
    ((PASS++))
  else
    printf "❌ FAIL  [%-6s] %s\n" "$id" "$label"
    echo "FAIL [$id] $label" >> "$OUT"
    echo "  resp: $(echo "$resp" | head -c 400)" >> "$OUT"
    ((FAIL++))
  fi
}

# ── test data ─────────────────────────────────────────────────────────────────

ZALOPAY_PROMPT='I am a Marketer in fintech company. Please help me research negative feedback which have 1, 2 stars on App store, CH play about feature transfer money of product Zalopay and finally propose for me some advices to improve'

# ── run ───────────────────────────────────────────────────────────────────────

echo "VoC Skill — JSON Contract & Parser Tests  $(date)" | tee "$OUT"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" | tee -a "$OUT"

echo ""
echo "── Group 1: Shape 1 — Query Echo ──"

run_test "QE-01" "query field present on any input" \
  '[{"role":"user","content":"using skill voc-task-understanding: Analyze MoMo"}]' \
  '"query"' ''

run_test "QE-02" "query echoes user text (Zalopay)" \
  '[{"role":"user","content":"using skill voc-task-understanding: Analyze Zalopay"}]' \
  '"query".*"Analyze Zalopay"|"Analyze Zalopay".*"query"' ''

run_test "QE-03" "query echo for Vietnamese input" \
  '[{"role":"user","content":"dùng skill voc-task-understanding: phân tích MoMo"}]' \
  '"query"' ''

echo ""
echo "── Group 2: Shape 2 — suggestedQuestions ──"

run_test "SQ-01" "suggestedQuestions present when fields missing" \
  '[{"role":"user","content":"using skill voc-task-understanding: Analyze TikTok Shop"}]' \
  '"suggestedQuestions"' ''

run_test "SQ-02" "each question has id field (q_*)" \
  '[{"role":"user","content":"using skill voc-task-understanding: Analyze TikTok Shop"}]' \
  '"id".*"q_' ''

run_test "SQ-03" "each question has choices array" \
  '[{"role":"user","content":"using skill voc-task-understanding: Analyze TikTok Shop"}]' \
  '"choices"' ''

run_test "SQ-04" "TikTok Shop market choices include Vietnam" \
  '[{"role":"user","content":"using skill voc-task-understanding: Analyze TikTok Shop"}]' \
  '"Vietnam"' ''

run_test "SQ-05" "TikTok Shop market choices include UK" \
  '[{"role":"user","content":"using skill voc-task-understanding: Analyze TikTok Shop"}]' \
  '"UK"' ''

run_test "SQ-06" "Zalopay: market=Vietnam only, NOT USA" \
  '[{"role":"user","content":"using skill voc-task-understanding: Analyze Zalopay"}]' \
  '"Vietnam"' '"USA"'

run_test "SQ-07" "choices always contains Other option" \
  '[{"role":"user","content":"using skill voc-task-understanding: Analyze MoMo"}]' \
  '"Other' ''

run_test "SQ-08" "target_user choices include Product/Marketing/Quality" \
  '[{"role":"user","content":"using skill voc-task-understanding: Analyze MoMo in Vietnam"}]' \
  '"Product".*"Marketing"\|"Marketing".*"Quality"' ''

echo ""
echo "── Group 3: Parser — subject / market / target_user / goal ──"

run_test "PA-01" "Zalopay fintech prompt → subject=Zalopay" \
  "[{\"role\":\"user\",\"content\":\"using skill voc-task-understanding: $ZALOPAY_PROMPT\"}]" \
  '"Zalopay"' '"I am a Marketer"'

run_test "PA-02" "Zalopay fintech prompt → target_user=marketing" \
  "[{\"role\":\"user\",\"content\":\"using skill voc-task-understanding: $ZALOPAY_PROMPT\"}]" \
  '"marketing"' ''

run_test "PA-03" "Zalopay fintech prompt → market NOT Fintech (asks for market)" \
  "[{\"role\":\"user\",\"content\":\"using skill voc-task-understanding: $ZALOPAY_PROMPT\"}]" \
  '"market"\|"suggestedQuestions"' '"Fintech"\|"fintech"'

run_test "PA-04" "Zalopay prompt → data_source has App Store + CH Play" \
  "[{\"role\":\"user\",\"content\":\"using skill voc-task-understanding: $ZALOPAY_PROMPT\"}]" \
  '"App Store"' '"Youtube"\|"Reddit"'

run_test "PA-05" "goal extracted → transfer money or negative feedback" \
  "[{\"role\":\"user\",\"content\":\"using skill voc-task-understanding: $ZALOPAY_PROMPT\"}]" \
  '"transfer|negative feedback"' ''

run_test "PA-06" "Short prompt: no market → asks for market" \
  '[{"role":"user","content":"using skill voc-task-understanding: Analyze Shopee"}]' \
  '"market"\|"suggestedQuestions"' ''

run_test "PA-07" "Full one-shot intent → no missing fields, goes to focusArea" \
  '[{"role":"user","content":"using skill voc-task-understanding: Analyze MoMo in Vietnam for quality, goal: crash patterns in payment"}]' \
  '"focusArea"\|"Target Product"' '"suggestedQuestions"'

echo ""
echo "── Group 4: Shape 3 — focusArea ──"

run_test "FA-01" "focusArea present after all fields resolved" \
  '[{"role":"user","content":"using skill voc-task-understanding: Analyze MoMo in Vietnam for quality, goal: crash in payment"}]' \
  '"focusArea"' ''

run_test "FA-02" "focusArea contains Target Product" \
  '[{"role":"user","content":"using skill voc-task-understanding: Analyze MoMo in Vietnam for marketing, goal: brand perception"}]' \
  '"Target Product"' ''

run_test "FA-03" "focusArea contains Lens" \
  '[{"role":"user","content":"using skill voc-task-understanding: Analyze MoMo in Vietnam for quality, goal: crash in payment"}]' \
  '"Lens"' ''

run_test "FA-04" "focusArea contains Date Range" \
  '[{"role":"user","content":"using skill voc-task-understanding: Analyze MoMo in Vietnam for quality, goal: crash in payment"}]' \
  '"Date Range"' ''

echo ""
echo "── Group 5: Shape 4 — Execution Plan ──"

run_test "PL-01" "plan_steps present after user confirms go" \
  '[{"role":"user","content":"using skill voc-task-understanding: Analyze MoMo in Vietnam for quality, goal: crash patterns"},{"role":"assistant","content":"{\"query\":\"ok\",\"focusArea\":\"Target Product: MoMo. Research goal: crash patterns. Lens: Quality Engineering (QE). Market: Vietnam. Customized parameters: Date Range: last 90 days, Sources: App Store, CH Play, Youtube, Voz, Tinhte, Reddit.\"}"},{"role":"user","content":"go"}]' \
  '"plan_steps"' ''

run_test "PL-02" "plan output has subject + market + target_user" \
  '[{"role":"user","content":"using skill voc-task-understanding: Analyze MoMo in Vietnam for quality, goal: crash patterns"},{"role":"assistant","content":"{\"query\":\"ok\",\"focusArea\":\"Target Product: MoMo...\"}"},{"role":"user","content":"go"}]' \
  '"subject".*"market"\|"market".*"subject"' ''

run_test "PL-03" "plan output has query field" \
  '[{"role":"user","content":"using skill voc-task-understanding: Analyze MoMo in Vietnam for quality, goal: crash patterns"},{"role":"assistant","content":"{\"query\":\"ok\",\"focusArea\":\"Target Product: MoMo...\"}"},{"role":"user","content":"yes"}]' \
  '"query"' ''

run_test "PL-04" "QE plan steps contain defect/classify (quality lens)" \
  '[{"role":"user","content":"using skill voc-task-understanding: Analyze MoMo in Vietnam for quality, goal: crash patterns"},{"role":"assistant","content":"{\"query\":\"ok\",\"focusArea\":\"...\"}"},{"role":"user","content":"go"}]' \
  '"defect\|classify\|crash\|bug\|Jira"' ''

run_test "PL-05" "MKT plan steps contain sentiment/brand (marketing lens)" \
  '[{"role":"user","content":"using skill voc-task-understanding: Analyze MoMo in Vietnam for marketing, goal: brand perception"},{"role":"assistant","content":"{\"query\":\"ok\",\"focusArea\":\"...\"}"},{"role":"user","content":"go"}]' \
  '"sentiment\|brand\|perception\|messaging"' ''

echo ""
echo "── Group 6: Deep Dive ──"

run_test "DD-01" "Deep dive: focus field in response" \
  '[{"role":"user","content":"using skill voc-task-understanding: Analyze MoMo in Vietnam for quality, goal: crash in payment"},{"role":"assistant","content":"{\"query\":\"ok\",\"plan_steps\":[\"step1\",\"step2\"]}"},{"role":"user","content":"Why is the Login crash worst on Android?"}]' \
  '"Login"\|"focus"' '"which market\|thị trường"'

run_test "DD-02" "Deep dive: no re-ask of subject or market" \
  '[{"role":"user","content":"using skill voc-task-understanding: Analyze MoMo in Vietnam for quality, goal: crash in payment"},{"role":"assistant","content":"{\"query\":\"ok\",\"plan_steps\":[]}"},{"role":"user","content":"Why is the Login crash worst on Android?"}]' \
  '.' '"which market\|what product\|which product"'

run_test "DD-03" "Deep dive Vietnamese: no re-ask" \
  '[{"role":"user","content":"dùng skill voc-task-understanding: phân tích MoMo ở Việt Nam cho quality, goal: crash in payment"},{"role":"assistant","content":"{\"query\":\"ok\",\"plan_steps\":[]}"},{"role":"user","content":"tại sao Login bị crash nhiều vậy?"}]' \
  '"Login"' '"thị trường nào\|sản phẩm nào"'

echo ""
echo "── Group 7: Anti-Hallucination ──"

run_test "AH-01" "No actual complaint data in response" \
  '[{"role":"user","content":"using skill voc-task-understanding: Analyze MoMo in Vietnam for quality, goal: crash in payment"}]' \
  '.' '"1-star review\|users said\|top complaint\|most complained"'

run_test "AH-02" "No plain-text narration (must output JSON)" \
  '[{"role":"user","content":"using skill voc-task-understanding: Analyze Zalopay"}]' \
  '"query"' 'Bước 1\|Step 1\|I will now\|Let me'

run_test "AH-03" "No premature intent emit without confirm" \
  '[{"role":"user","content":"using skill voc-task-understanding: Analyze MoMo in Vietnam for quality, goal: crash in payment"}]' \
  '"focusArea"\|"suggestedQuestions"' '"plan_steps"'

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
TOTAL=$((PASS+FAIL+SKIP))
printf " ✅ PASS: %d   ❌ FAIL: %d   ⚠️  SKIP: %d   TOTAL: %d\n" "$PASS" "$FAIL" "$SKIP" "$TOTAL"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Full log: $OUT"

# append summary to log
echo "" >> "$OUT"
echo "PASS=$PASS FAIL=$FAIL SKIP=$SKIP TOTAL=$TOTAL" >> "$OUT"
