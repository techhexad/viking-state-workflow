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


# ==============================================================================
# Error Taxonomy & Classification Engine
# ==============================================================================

FATAL_PATTERNS = [
    (r"Operation not permitted", "macOS SIP or filesystem permission barrier (requires human authorization)"),
    (r"Permission denied", "File permissions restricted (requires sudo/chmod)"),
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

def generate_subagent_prompt(project: str, state_name: str, state_meta: dict, failure_context: str = None) -> str:
    desc = state_meta.get("description", "")
    gate = state_meta.get("gate", state_meta.get("gates", ""))
    
    prompt = f"""You are the specialized Subagent for Phase [{state_name}] in project [{project}].

## Your Mission:
{desc}

## Gate Requirements (Success Criteria):
{gate}

## Operational Rules:
1. All heavy commands (> 40 lines) MUST use: python3 {SCRIPT_DIR}/viking_bridge.py run --dest "viking://knowledge/{project}/..." --cmd "..."
2. For UI verification, run: python3 {SCRIPT_DIR}/viking_bridge.py capture-ocr --app "work/<app_name>.app"
3. When the gate criteria are met, write key findings to HANDOVER.md and exit with code 0.
"""

    if failure_context:
        prompt += f"""
---
> [!WARNING]
> ### ⚠️ PREVIOUS ATTEMPT FAILED - LEARN AND ADJUST:
> {failure_context}
> Avoid repeating this exact failure. Modify the approach accordingly.
"""
    return prompt


# ==============================================================================
# Supervisor Execution Engine
# ==============================================================================

def supervise_phase(runbook_path: str, max_retries: int = 3, auto_execute_cmd: str = None):
    data = statem_driver.load_runbook(runbook_path)
    project = data.get("task_name", data.get("name", "project"))
    curr_state = statem_driver.get_current_state(data)
    states = data.get("states", {})
    state_meta = states.get(curr_state, {})

    print("\n" + "=" * 65)
    print(f"🎯  [StateM Supervisor] Managing Phase: \033[1;34m{curr_state}\033[0m")
    print(f"📋  Objective: {state_meta.get('description', '')}")
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
            failure_context="\n".join(failure_history) if failure_history else None
        )

        print(f"\n🚀 [Attempt {retry_count + 1}/{max_retries}] Launching Subagent for [{curr_state}]...")
        
        # If an external command runner is provided, execute it; otherwise print instructions
        if auto_execute_cmd:
            proc = subprocess.run(auto_execute_cmd, shell=True, capture_output=True, text=True)
            output = proc.stdout + "\n" + proc.stderr
            returncode = proc.returncode
        else:
            print("📝 Synthesized Subagent Directives:")
            print("-" * 50)
            print(subagent_prompt)
            print("-" * 50)
            return 0  # In agent environment, prompt is consumed by agent engine

        # Evaluate output
        if returncode == 0:
            print(f"\n✅ [StateM Supervisor] Phase [{curr_state}] passed gate verification!")
            statem_driver.advance_state(runbook_path)
            return 0

        # Classify Error
        category, err_type, err_desc = classify_error(output)
        print(f"\n🔍 Error Classification: [{category}] - {err_desc}")

        if category == "FATAL":
            print("\n" + "🛑" * 30)
            print(f"🚨 [FATAL ERROR - HUMAN INTERVENTION REQUIRED]")
            print(f"Reason: {err_desc}")
            print(f"The supervisor has paused execution. Please resolve the barrier and resume.")
            print("🛑" * 30 + "\n")
            return 2

        # Recoverable error
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

    sys.exit(supervise_phase(args.runbook, args.max_retries, args.exec))


if __name__ == "__main__":
    main()
