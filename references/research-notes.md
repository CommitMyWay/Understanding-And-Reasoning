# Research Notes — Prompt Engineering Patterns for VoC Skill

Learnings from MetaGPT (PM role) and XAgent (`ask_human_for_help` tool).
Applied to: `voc-task-understanding` skill.

---

## 1. MetaGPT — Constraining LLM via Prompt Structure

Source: `metagpt/prompts/product_manager.py`, `metagpt/prompts/di/role_zero.py`

### Core patterns observed

**Mode dispatch with explicit terminal state**
Each mode declares:
- `Triggered by:` — entry condition (LLM must classify mode before acting)
- `ending with:` — terminal state (LLM knows exactly when it's allowed to stop)

```python
## Mode 1: PRD Creation
Triggered by software/product requests or feature enhancements,
ending with the output of a complete PRD.

## Mode 2: Market Research
Triggered by market analysis requests,
ending with the output of a complete report document.
```

Without "ending with", LLM has no pinned completion state and may stop early or overshoot.

---

**Required Fields as hard gate (not a suggestion)**

MetaGPT labels critical field sections with `(**IMPORTANT**)` and `(Required)` at the field level:

```
### Required Fields
2. Product Definition (**IMPORTANT**)
   - Competitive Quadrant Chart (Required): Using Mermaid
```

The agent treats these as blockers — it cannot produce output until they are all filled. Contrast with prose guidelines ("you should include X"), which LLMs treat as soft suggestions.

---

**Mandatory sequential process with numbered steps**

```
### **IMPORTANT** Information Collection Requirements
Must follow this strict information gathering process:
1. Keyword Generation Rules: Infer directly (instead of using tools)
2. Search Process: Use SearchEnhancedQA for each keyword
3. Information Analysis: Must read EACH unique source individually
4. Quality Control: Verify data consistency across sources
```

Key detail: `"Infer directly instead of using tools"` forces the LLM to reason internally before calling external tools. This prevents premature tool use.

Numbered lists are harder for LLMs to skip than prose bullets.

---

**Anti-speculation via explicit exclusion list**

```
Report must be entirely focused on insights and analysis:
- No mention of research methodology
- No source tracking or process documentation
- Present only validated findings and conclusions
```

Stronger than "don't hallucinate". Tells the LLM what CANNOT appear in output, not just what should appear.

---

**Think-before-act structure (THOUGHT_GUIDANCE)**

```
First, describe the actions you have taken recently.
Second, describe the messages received, especially from users.
Third, describe the plan status and current task.
Fourth, describe necessary human interaction.
Fifth, describe if you should terminate.
```

Forces structured internal monologue before any command output. LLM cannot jump straight to action.

---

### Takeaway for our skill
Current `SKILL.md` uses prose guidelines that LLMs treat as soft. Need to add:
- Mode classification with "Triggered by / ending with"
- `(**IMPORTANT**)` pre-output checklist as a blocking gate
- Numbered mandatory process steps
- Explicit "what must NOT appear in output" anti-speculation rules

---

## 2. XAgent — `ask_human_for_help` as a Formal Tool

Source: `XAgent/ai_functions/pure_functions/task_handle_functions.yml`,
`XAgent/function_handler.py`, `XAgent/inner_loop_search_algorithms/ReACT.py`

### The core insight

XAgent does NOT ask clarifying questions as prose text.
It registers `ask_human_for_help` as a **formal tool call** in the agent's tool list.

When the agent needs parameters, it CALLS the tool — the same way it would call `FileSystem.read` or `Browser.goto`. The tool call halts execution until the human responds.

---

### Tool schema

```yaml
- name: ask_human_for_help
  description: >
    This is the only tool that allows you to interact with human.
    Use this tool ONLY if you cannot continue the task without human help,
    such as needing more information like unclear requirement, user account,
    api key, location, etc. Human will receive your query and give you a
    suggestion or the needed information.
  parameters:
    requirement:
      type: string
      description: >
        What you want human to help you with. Must be very specific
        to avoid ambiguity for the human.
    requirement_type:
      type: string
      enum: [give_information, other_type]
      description: Helps human understand the type of help needed.
  required: [requirement, requirement_type]
```

---

### How it works in the loop

```python
# function_handler.py — tool is conditionally added to agent's toolset
def intrinsic_tools(self, enable_ask_human_for_help):
    tools = [self.subtask_submit_function]
    if enable_ask_human_for_help:
        tools.append(self.ask_human_for_help_function)   # ← registered as tool
    return tools

# ReACT.py — prompt tells agent when to use it
if config.enable_ask_human_for_help:
    human_prompt = "- Use 'ask_human_for_help' when you need help, \
      remember to be specific to your requirement."
else:
    human_prompt = "- Human is NOT available. Solve by yourself. \
      If information is not enough, try your best to use default value."
```

When agent calls `ask_human_for_help`, `handle_human_help()` blocks execution and waits for human input before returning to the loop.

---

### Why this is superior to conversational asking

| Approach | Conversational ask | Tool call |
|---|---|---|
| LLM can skip it | ✅ yes — prose, easy to ignore | ❌ no — must call tool to get value |
| Forces specificity | ❌ LLM chooses how vague to be | ✅ schema requires `requirement` field |
| Auditable | ❌ buried in chat text | ✅ logged as structured tool call |
| Blocks execution | ❌ LLM may proceed anyway | ✅ loop halts until human responds |
| Can ask multiple at once | ✅ easy to bundle questions | ❌ one tool call = one request |
| Classifies WHY | ❌ not enforced | ✅ `requirement_type` enum |

---

### Conditional availability is critical

XAgent has `enable_ask_human_for_help` flag. When `False`, the agent is explicitly told:
> "Human is NOT available. You are not allowed to ask human for help in any form or channel."

This is the inverse gate — when the tool is off, the LLM cannot ask conversationally either. The flag governs ALL forms of human interaction.

---

## 3. How to Apply Both Patterns to `voc-task-understanding`

### Proposed: `ask_for_parameters` tool

Register a formal tool in the skill that the agent MUST call to obtain missing required fields.
The agent cannot emit intent JSON without calling this tool for each missing field.

```json
{
  "name": "ask_for_parameters",
  "description": "Call this tool when a required parameter (subject, market, goal) is missing or ambiguous. Execution is blocked until the user provides the value. Call once per missing field — do NOT bundle multiple fields in one call.",
  "parameters": {
    "missing_field": {
      "type": "string",
      "enum": ["subject", "market", "goal", "focus"],
      "description": "The specific parameter that is missing."
    },
    "reason_blocked": {
      "type": "string",
      "description": "Why the agent cannot proceed without this parameter. Be specific."
    },
    "question": {
      "type": "string",
      "description": "The exact question to present to the user. Single question only."
    },
    "options": {
      "type": "array",
      "items": {"type": "string"},
      "description": "Known valid values for this field, if applicable. E.g. ['product', 'marketing', 'competitive'] for goal."
    }
  },
  "required": ["missing_field", "reason_blocked", "question"]
}
```

**Implementation in `tools/ask_for_parameters.py`** — validates the call, logs it, returns the question to surface to the user, updates context with `clarifications_done`.

---

### Updated SKILL.md structure (MetaGPT-style)

```markdown
## Mode 1: Prompt Analysis
Triggered by: any new product/app/feature analysis request.
Ending with: all required fields resolved → plan confirmed → intent JSON emitted.

## Mode 2: Dive Deep
Triggered by: follow-up referencing a specific insight after Mode 1 completes.
Ending with: focus field updated → deep-dive intent JSON emitted.

## (**IMPORTANT**) Pre-Output Gate
DO NOT emit intent JSON until this checklist is fully satisfied:
- [ ] subject — non-null, resolved via parse or ask_for_parameters
- [ ] market — non-null, resolved via parse or ask_for_parameters
- [ ] goal — one of `product` | `marketing` | `competitive`
- [ ] User confirmed plan with explicit affirmative keyword
- [ ] PII stripped from all fields

## Mandatory Process — Must follow in order
1. Classify mode (Mode 1 or Mode 2).
2. Parse intent from user message via analyze_prompt.py.
3. For each missing required field: call ask_for_parameters tool. STOP. Wait.
4. Verify Pre-Output Gate checklist.
5. Build plan via conversation_planner.py. Present to user.
6. Wait for explicit confirmation keyword.
7. Strip PII. Emit intent JSON.

## Anti-Speculation Rules
- DO NOT include complaint data, user quotes, or analysis results in any response.
- DO NOT suggest what data might show before it is fetched.
- DO NOT proceed past step 3 while any required field is null.
```

---

## 4. Summary: Key Principles

| Principle | Source | Applied As |
|---|---|---|
| Mode dispatch + terminal state | MetaGPT | "Triggered by / Ending with" in SKILL.md |
| Required fields as hard gate | MetaGPT | `(**IMPORTANT**)` Pre-Output Checklist |
| Numbered mandatory steps | MetaGPT | "Mandatory Process" numbered list |
| Anti-speculation exclusion list | MetaGPT | "DO NOT include..." Anti-Speculation Rules |
| Ask as tool call, not prose | XAgent | `ask_for_parameters` tool |
| One question per tool call | XAgent | `missing_field` is single enum, not array |
| Execution blocks until answered | XAgent | Tool call halts loop |
| Classify WHY asking | XAgent | `reason_blocked` required field |
| Conditional availability | XAgent | Tool only in toolset when clarification needed |
