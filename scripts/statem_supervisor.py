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

## Operational Rules & Strict Step Budget:
1. 🛑 **Hard Step Budget (最大 20 步硬熔断)**: 你在当前阶段的执行预算严格限制在 **20 步** 以内！严禁在单会话内死磕超过 20 步。如果在第 15 步仍未达成目标，必须立即停止探索，将已定位地址和阻碍写入 HANDOVER.md，输出 `GATE FAIL: <原因>` 并正常退出。监督器会自动销毁你的会话，拉起全新的下一任子智能体接力，彻底防止长跑退化！
2. 🛡️ **严禁内存 Dump 毒化上下文 (Anti-Hex-Dump Shield)**: 严禁在终端大段打印 `memory read` / `xxd` / `hexdump` 原始十六进制（大量零字节会导致大模型注意力崩溃输出 0,0,0 退化）。所有内存 Dump 必须使用 Python 解析出关键结构或管道写入 `viking://`！
3. 🧹 **彻底强杀旧进程 (Mandatory Force-Kill)**: 在构建、补丁、重签或启动测试前，必须强制执行 `pkill -9 -f "<app_name>" 2>/dev/null || killall -9 "<app_name>" 2>/dev/null || true`，确保内存完全干净！
4. 📦 **重型命令必须进 Viking**: 所有反汇编、长日志必须使用 `python3 {SCRIPT_DIR}/viking_bridge.py run --dest "viking://knowledge/{project}/..." --cmd "..."`。
5. ⚡ **单向极简交接与立即终结 (One-Shot Compact Exit)**: 达成 Gate 或熔断退出时，仅需更新 HANDOVER.md，输出 ≤5 行极简结构化结论（如 `GATE_STATUS: PASS | PATCHES: [0x5445C7, 0x51E050] | VERIFY: OK`），并**立即彻底结束会话退出**。严禁输出长篇废话或与调度器进行多轮 Ping-Pong 中继闲聊，确保本地 GPU 显存与算力瞬间 100% 释放给主控！
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
