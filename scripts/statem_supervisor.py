#!/usr/bin/env python3
"""
StateM Subagent Supervisor (statem_supervisor.py)
Orchestrates sequential subagent execution across Runbook states with:
- Intelligent error taxonomy classification (Recoverable vs Fatal)
- Automatic subagent respawn with failure context injection
- Circuit-breaker limits (max retries) and human escalation
- Zero external dependencies
"""

import sys
import os
import re
import argparse
import subprocess
import time
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SKILL_ROOT = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, SCRIPT_DIR)
import statem_driver
import working_set


# ==============================================================================
# Error Taxonomy & Classification Engine
# ==============================================================================

FATAL_PATTERNS = [
    (r"Operation not permitted", "macOS SIP or filesystem permission barrier (requires human authorization)"),
    (r"Password:", "Interactive sudo password prompt encountered"),
    (r"No space left on device", "Disk space exhausted"),
    (r"Connection refused.*(1933|8000)", "Core infrastructure daemon (OpenViking or Model Server) is offline"),
    (r"No such file or directory:.*(\.dmg|\.app)", "Target input material missing from workspace")
]

RECOVERABLE_PATTERNS = [
    (r"SIGILL|EXC_BAD_INSTRUCTION", "Illegal instruction in binary patch (e.g. BRK#0 vs NOP)"),
    (r"SIGSEGV|EXC_BAD_ACCESS", "Segmentation fault / invalid memory address accessed"),
    (r"Unlicensed|Trial Expired|未许可", "UI verification failed: License/Pro checks still active"),
    (r"Text file busy", "Binary locked by running process (requires pkill cleanup)"),
    (r"Permission denied", "File permissions restricted (retry after chmod/codesign, do not treat as SIP)"),
    (r"code signature invalid|CSSMERR_TP_NOT_TRUSTED", "Ad-hoc codesigning failed or needs resigning"),
    (r"Prompt too long|Context Length Exceeded", "Subagent context overflowed (requires fresh clean restart)")
]


def classify_error(output_log: str) -> tuple:
    """
    Classifies error into:
    - ('FATAL', reason, description) -> Escalate to human
    - ('RECOVERABLE', reason, description) -> Auto-rebuild subagent with feedback
    - ('UNKNOWN', 'Unknown failure', snippet) -> Default recoverable up to max_retries
    """
    for pattern, desc in FATAL_PATTERNS:
        if re.search(pattern, output_log, re.IGNORECASE):
            return ("FATAL", pattern, desc)

    for pattern, desc in RECOVERABLE_PATTERNS:
        if re.search(pattern, output_log, re.IGNORECASE):
            return ("RECOVERABLE", pattern, desc)

    return ("UNKNOWN", "Execution failed", output_log[-300:] if output_log else "No output")


# ==============================================================================
# Subagent Prompt Synthesizer
# ==============================================================================

def generate_subagent_prompt(project: str, state_name: str, state_meta: dict,
                             failure_context: str = None, sprint_goal: str = None) -> str:
    desc = state_meta.get("description", "")
    gate = state_meta.get("gate", state_meta.get("gates", ""))
    working_set.reset_sprint_budget()
    checkpoint_slice = working_set.checkpoint_prompt_slice()
    ck = working_set.load_checkpoint()
    question = sprint_goal or ck.get("next_action") or (
        f"Do ONLY the next smallest slice of: {desc}"
    )

    prompt = f"""You are a micro-sprint Subagent for Phase [{state_name}] in project [{project}].
You answer ONE question, persist the working set, then stop. You do not finish the whole phase.

## This sprint's single question:
{question}

## Working set (do not re-derive; do not reload chat history):
{checkpoint_slice}

## Phase gate (NOT your sprint goal — parent judges this later):
{gate}

## Rules:
1. One question only. No unrelated exploration.
2. Exploration budget: at most 8 `viking_bridge.py` explore calls (`run`/`grep`/`ocr`). `note`/`checkpoint`/`doctor`/`ask-ui`/`sprint-done` do not count. Calls 6–7 are refused (drain). Call 8 auto-writes checkpoint.json and exits 20.
   UI verify is `ask-ui` once (human y/n). Do not call capture-ocr in a retry loop.
3. Persist every confirmed address/dead-end immediately:
   `python3 {SCRIPT_DIR}/viking_bridge.py note --confirmed "<fact>" --rejected "<dead-end>" --next "<next question>"`
4. Heavy output only via `python3 {SCRIPT_DIR}/viking_bridge.py run --dest "viking://knowledge/{project}/..." --cmd "..."`.
   Search only via `viking_bridge.py grep`. Never grep/cat/head `work/disasm`, `~/.openviking/local_vfs`, or `.viking_vfs`.
5. Last command MUST be:
   `python3 {SCRIPT_DIR}/viking_bridge.py sprint-done --status DONE|YIELD|FAIL --confirmed "<fact>" --next "<next>"`
   Then stop. Closing message = the 4 lines sprint-done printed. The host splices your last message into the parent — a long closing poisons the supervisor.
6. Native-first: on Universal binaries, this sprint stays on `uname -m` only.
7. Continuous tool execution: You MUST execute a tool (`bash`/`viking_bridge.py`) on EVERY turn. DO NOT output a pure text plan without calling a tool in the same turn, as that will prematurely terminate your session!

### 💡 Quick Tool Invocation:
python3 {SCRIPT_DIR}/viking_bridge.py grep --uri "viking://knowledge/{project}/disasm/main_disasm.asm" --pattern "<target_symbol_or_address>"
"""

    if failure_context:
        prompt += f"""
---
> [!WARNING]
> ### Previous sprint failed — adjust:
> {failure_context}
"""
    return prompt


# ==============================================================================
# Supervisor Execution Engine
# ==============================================================================

def _sprint_status_from_output(output: str, returncode: int) -> str:
    if returncode == 20 or re.search(r"SPRINT_STATUS:\s*YIELD", output, re.IGNORECASE):
        return "YIELD"
    if returncode == 18:
        return "DRAIN"
    if re.search(r"SPRINT_STATUS:\s*FAIL|GATE FAIL", output, re.IGNORECASE):
        return "FAIL"
    if re.search(r"SPRINT_STATUS:\s*DONE", output, re.IGNORECASE):
        return "DONE"
    return "UNKNOWN"


def supervise_phase(runbook_path: str, max_retries: int = 3, auto_execute_cmd: str = None,
                    sprint_goal: str = None):
    data = statem_driver.load_runbook(runbook_path)
    project = data.get("task_name", data.get("name", "project"))
    curr_state = statem_driver.get_current_state(data)
    states = data.get("states", {})
    state_meta = states.get(curr_state, {})

    print("\n" + "=" * 65)
    print(f"🎯  [StateM Supervisor] Managing Phase: \033[1;34m{curr_state}\033[0m")
    print(f"📋  Objective: {state_meta.get('description', '')}")
    print(f"🧩  Sprint goal: {sprint_goal or working_set.load_checkpoint().get('next_action') or '(next smallest slice)'}")
    print("=" * 65)

    if curr_state == "completed":
        print("🎉 Task is already marked as completed!")
        return 0

    retry_count = 0
    failure_history = []

    while retry_count < max_retries:
        subagent_prompt = generate_subagent_prompt(
            project=project,
            state_name=curr_state,
            state_meta=state_meta,
            failure_context="\n".join(failure_history) if failure_history else None,
            sprint_goal=sprint_goal,
        )

        print(f"\n🚀 [Sprint attempt {retry_count + 1}/{max_retries}] Launching micro-sprint for [{curr_state}]...")
        
        if auto_execute_cmd:
            proc = subprocess.run(auto_execute_cmd, shell=True, capture_output=True, text=True)
            output = proc.stdout + "\n" + proc.stderr
            returncode = proc.returncode
        else:
            prompt_path = working_set.sprint_prompt_file()
            working_set.ensure_state_dir()
            with open(prompt_path, "w", encoding="utf-8") as f:
                f.write(subagent_prompt)
            question = sprint_goal or working_set.load_checkpoint().get("next_action") or curr_state
            dispatch = (
                f"Read {prompt_path} and execute tools continuously until sprint-done. "
                f"Finish with: python3 {SCRIPT_DIR}/viking_bridge.py sprint-done "
                f"--status DONE|YIELD|FAIL --confirmed \"<fact>\" --next \"<next>\". "
                f"Do not output a plan without calling a tool in the same turn."
            )
            print("📝 Sprint card (do not cat PROMPT_FILE in this parent turn):")
            print("-" * 50)
            print(f"PROMPT_FILE: {prompt_path}")
            print(f"SPRINT_GOAL: {question}")
            print(f"PHASE: {curr_state}")
            print(f"DISPATCH_PROMPT: {dispatch}")
            print("-" * 50)
            print("ℹ️  Sprint DONE ≠ phase complete. Advance the phase only via:")
            print(f"    python3 {SCRIPT_DIR}/statem_driver.py --advance --gate-check")
            print()
            print("=" * 65)
            print("PARENT HALT — this turn is over after you dispatch `subagent`.")
            print("Do NOT: bash / sleep / list_agents / grep disasm / spawn a watcher child.")
            print("Wait for the host to deliver the child result as the next user message.")
            print("A 'goal round' while the child is running is not a reason to poll.")
            print("=" * 65)
            return 0

        sprint_status = _sprint_status_from_output(output, returncode)
        print(f"\n🔍 Sprint result: [{sprint_status}] rc={returncode}")

        if sprint_status in ("DONE", "YIELD", "DRAIN"):
            if not os.path.exists(working_set.checkpoint_file()):
                working_set.auto_synthesize_checkpoint(reason=f"sprint {sprint_status}")
            print("✅ Working set is on disk (.viking_state/checkpoint.json).")
            print("⛔ Not advancing the runbook phase. Parent must gate-check, then dispatch the next sprint.")
            return 0 if sprint_status == "DONE" else 20

        category, err_type, err_desc = classify_error(output)
        print(f"🔍 Error Classification: [{category}] - {err_desc}")

        if category == "FATAL":
            print("\n" + "🛑" * 30)
            print(f"🚨 [FATAL ERROR - HUMAN INTERVENTION REQUIRED]")
            print(f"Reason: {err_desc}")
            print(f"The supervisor has paused execution. Please resolve the barrier and resume.")
            print("🛑" * 30 + "\n")
            return 2

        retry_count += 1
        failure_msg = f"- Attempt #{retry_count} failed on error '{err_type}': {err_desc}"
        failure_history.append(failure_msg)
        print(f"⚠️ Recoverable failure detected. Queueing auto-rebuild for attempt {retry_count + 1}...")
        time.sleep(1)

    print("\n" + "🛑" * 30)
    print(f"🚨 [CIRCUIT BREAKER TRIGGERED - Max Retries ({max_retries}) Exceeded]")
    print(f"Phase [{curr_state}] failed repeatedly. Escalating to human developer for review.")
    print("🛑" * 30 + "\n")
    return 1


def main():
    parser = argparse.ArgumentParser(description="StateM Sequential Subagent Supervisor")
    parser.add_argument("--runbook", default="runbook.yaml", help="Path to runbook.yaml")
    parser.add_argument("--max-retries", type=int, default=3, help="Max retries before human escalation")
    parser.add_argument("--classify", help="Test error classification on a log file")
    parser.add_argument("--exec", help="Optional command to run subagent execution")
    parser.add_argument("--sprint-goal", help="Single-question goal for this micro-sprint")

    args = parser.parse_args()

    if args.classify:
        if os.path.exists(args.classify):
            with open(args.classify, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
            cat, err, desc = classify_error(content)
            print(f"Classification: Category={cat}, Type={err}, Description={desc}")
        else:
            print(f"File not found: {args.classify}")
        sys.exit(0)

    sys.exit(supervise_phase(args.runbook, args.max_retries, args.exec, args.sprint_goal))


if __name__ == "__main__":
    main()
