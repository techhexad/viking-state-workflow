#!/usr/bin/env python3
"""
Workspace Initializer (workspace_init.py)
Automatically synthesizes tailored `AGENTS.md` and `runbook.yaml` for ANY long-horizon task type:
- Reverse Engineering / Binary Analysis
- Large-Scale Code Refactoring / Migration
- Deep Bug Hunting / Multi-Service Debugging
- Data & AI Pipeline Execution
- General Long-Horizon Task

Zero external dependencies (pure standard library).
"""

import sys
import os
import argparse

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SKILL_ROOT = os.path.dirname(SCRIPT_DIR)
SKILL_MD_PATH = os.path.join(SKILL_ROOT, "SKILL.md")


TEMPLATES = {
    "reverse_engineering": {
        "title": "Reverse Engineering & Binary Analysis",
        "description": "Binary slicing, symbol analysis, binary patching, and UI OCR verification.",
        "vfs_paths": [
            ("disasm", "Full disassembly & decompile dumps"),
            ("strings", "Extracted string tables"),
            ("ocr", "UI verification transcripts"),
            ("logs", "Dynamic tracing & LLDB logs")
        ],
        "states": [
            ("unpack_and_extract", "Unpack package/DMG and slice thin binary", "Thin binary and frameworks extracted in work/"),
            ("symbol_and_disasm", "Extract symbols, strings, and full disassembly to Viking", "Symbol tables and disassembly stored in viking://"),
            ("analyze_gating", "Locate authorization/license checks via String XREF in main binary", "Target check functions and patch addresses locked"),
            ("craft_patch", "Write byte patch, reconstruct fat binary and re-sign", "Patched binary passes codesign validation"),
            ("verify_and_deliver", "Human confirms Pro/Activated UI via ask-ui", "Human confirmed Pro/Activated on the license page")
        ],
        "custom_commands": """### 1. 逆向黄金法则与字符串交叉引用秒杀 SOP (String XREF-First Protocol)
> [!IMPORTANT]
> 1. **主二进制第一原则**：严禁在第三方 SDK（如 Paddle/Sparkle）上单独打转；授权总闸门 100% 存在于主二进制（Main Binary）内部的 Swift 状态机与 Feature Flag！
> 2. **秒杀 SOP（字符串 XREF 倒推）**：
>    - 步骤 1：定位 UI 状态字符串（如 `"Pro License"`, `"Activated"`, `"Unlicensed"`）在 `__cstring` 中的内存地址；
>    - 步骤 2：在主汇编中通过 `viking_bridge.py grep` 搜索对该地址的 `adrp / ldr` 交叉引用 (XREF)；
>    - 步骤 3：倒推上方 5~10 行汇编，锁定分流的关键条件跳转（`cbz`, `cbnz`, `tbz`, `b.eq`）；
>    - 步骤 4：改写该跳转指令，直接强制流向 Pro 分支！

### 2. 重型反汇编与符号查询
```bash
# 提取汇编并转存 Viking
python3 {skill_dir}/viking_bridge.py run \\
  --dest "viking://knowledge/{project}/disasm/main.asm" \\
  --cmd "objdump -d work/<binary_name>"

# 精准切片检索字符串与汇编交叉引用
python3 {skill_dir}/viking_bridge.py grep \\
  --uri "viking://knowledge/{project}/disasm/main.asm" \\
  --pattern "<target_address_or_symbol>" \\
  --context 15

# 重签并注入 Debug Entitlements (防止 macOS AMFI 拦截 LLDB error 9)
cat > /tmp/debug_entitlements.plist << 'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>com.apple.security.get-task-allow</key>
    <true/>
    <key>com.apple.security.cs.debugger</key>
    <true/>
    <key>com.apple.security.cs.disable-library-validation</key>
    <true/>
</dict>
</plist>
EOF
codesign --force --deep --sign - --entitlements /tmp/debug_entitlements.plist "work/<app_name>.app"

# 还原 Swift Mangled 符号
echo "<mangled_symbol>" | swift demangle
```

### 3. UI 验收必须人工 (阶段 5: verify_and_deliver)
禁止自动 open + Cmd+, + 截屏 OCR 重试（打不开授权页）。只问一次人：
```bash
python3 {skill_dir}/viking_bridge.py ask-ui \\
  --app "work/<app_name>.app" \\
  --open \\
  --question "License/Pro 页是否显示 Activated 或 Pro？(y/n)" \\
  --timeout 600
```
exit 4 (`ASK_UI: NEED_HUMAN`) 交给主控在主对话询问，禁止循环重试。"""
    },
    "code_refactor": {
        "title": "Large-Scale Code Refactoring & Migration",
        "description": "Multi-module architectural migration, AST transformations, and regression verification.",
        "vfs_paths": [
            ("ast", "AST dumps and symbol callgraphs"),
            ("build_logs", "Full compiler and build output logs"),
            ("diffs", "Large multi-file patch diffs"),
            ("test_reports", "Full unit & integration test outputs")
        ],
        "states": [
            ("dependency_audit", "Scan codebase dependencies and generate callgraph into Viking", "Callgraph and module boundaries mapped in viking://"),
            ("core_refactor", "Refactor core API interfaces and type definitions", "Core modules compile cleanly with zero type errors"),
            ("caller_migration", "Batch migrate all call sites across modules", "All downstream callers updated and building"),
            ("regression_testing", "Run full test matrix and offload failure logs to Viking", "100% unit and integration tests passing"),
            ("cleanup_and_docs", "Remove deprecated shims and update documentation", "Clean codebase ready for PR review")
        ],
        "custom_commands": """### 1. 全局构建与重型测试日志转存
```bash
# 运行完整构建并将超长大日志存入 Viking
python3 {skill_dir}/viking_bridge.py run \\
  --dest "viking://knowledge/{project}/build_logs/full_build.log" \\
  --cmd "make build-all"

# 检索测试失败用例与堆栈
python3 {skill_dir}/viking_bridge.py grep \\
  --uri "viking://knowledge/{project}/build_logs/full_build.log" \\
  --pattern "FAIL:" \\
  --context 10
```"""
    },
    "deep_debugging": {
        "title": "Deep Full-Stack Debugging & Bug Hunting",
        "description": "Multi-service log tracing, reproduction script crafting, and root cause diagnosis.",
        "vfs_paths": [
            ("runtime_logs", "Aggregated container & server traces"),
            ("memory_dumps", "Heap/core dumps and profiler data"),
            ("repro_runs", "Automated reproduction run output")
        ],
        "states": [
            ("reproduce_issue", "Establish deterministic minimal reproduction test case", "Bug reproduced reliably in local environment"),
            ("trace_and_isolate", "Collect runtime logs into Viking and isolate root cause component", "Failure stack and faulty module confirmed"),
            ("implement_fix", "Apply minimal surgical code fix", "Faulty test case passes without regression"),
            ("stress_validation", "Run load/stress regression suite and store results in Viking", "Zero memory leaks or edge-case panics observed"),
            ("summary_and_postmortem", "Generate root cause analysis report and handover", "HANDOVER.md and postmortem generated")
        ],
        "custom_commands": """### 1. 运行时大日志采集与检索
```bash
# 采集多服务运行大日志至 Viking
python3 {skill_dir}/viking_bridge.py run \\
  --dest "viking://knowledge/{project}/runtime_logs/trace.log" \\
  --cmd "docker compose logs --tail=10000"

# 检索异常 Exception 与调用栈
python3 {skill_dir}/viking_bridge.py grep \\
  --uri "viking://knowledge/{project}/runtime_logs/trace.log" \\
  --pattern "Exception|Panic|Error" \\
  --context 15
```"""
    },
    "general_long_task": {
        "title": "General Long-Horizon Task Execution",
        "description": "Deterministic milestone progression and heavy context management.",
        "vfs_paths": [
            ("artifacts", "Intermediate outputs and artifacts"),
            ("logs", "Step execution traces"),
            ("knowledge", "Indexed references and documentation")
        ],
        "states": [
            ("discovery_and_planning", "Explore workspace, index existing context into Viking, and lock goal", "Task scope and plan verified"),
            ("phase1_execution", "Execute foundational step with heavy logs offloaded", "Phase 1 deliverables verified"),
            ("phase2_execution", "Execute core logic and integrate components", "Phase 2 integration tests pass"),
            ("verification_and_audit", "Comprehensive audit and quality checks", "All success criteria met"),
            ("delivery_and_handover", "Package final results and create distilled handover", "Final deliverables ready")
        ],
        "custom_commands": """### 1. 大数据与任务日志转存
```bash
python3 {skill_dir}/viking_bridge.py run \\
  --dest "viking://knowledge/{project}/logs/step_output.log" \\
  --cmd "<your_long_running_command>"
```"""
    }
}


def generate_agents_md(project_name: str, task_type: str, user_prompt: str, target_dir: str):
    tmpl = TEMPLATES.get(task_type, TEMPLATES["general_long_task"])
    skill_dir = SCRIPT_DIR

    # Check for historical macro recipes in Viking VFS
    recipe_section = ""
    recipe_file = os.path.expanduser(f"~/.openviking/local_vfs/memory/recipes/{task_type}.md")
    if os.path.exists(recipe_file):
        try:
            with open(recipe_file, "r", encoding="utf-8", errors="replace") as rf:
                recipe_text = rf.read().strip()
                if recipe_text:
                    recipe_section = f"""
---

## 💡 历史同类任务沉淀经验 (Historical Recipes & Playbook)
> [!TIP]
> 系统自动从 OpenViking 全局范式库 (`viking://memory/recipes/{task_type}.md`) 检索到以下历史成功经验：
>
{recipe_text}
"""
        except Exception:
            pass

    content = f"""# {project_name} Workspace Guidelines (Viking State Workflow)

- **Task Type**: {tmpl['title']}
- **Task Goal**: {user_prompt.strip() or tmpl['description']}
- **Active Skill**: [`viking-state-workflow`]({SKILL_MD_PATH})
- **Toolchain Path**: `{skill_dir}`
- **Runbook**: `runbook.yaml`
- **VFS Prefix**: `viking://knowledge/{project_name}/`
- **Handover File**: `HANDOVER.md` (human projection of `.viking_state/checkpoint.json`)
- **Working Set**: `.viking_state/checkpoint.json` + `.viking_state/discoveries.jsonl`

---

## 1. 核心约束与操作红线 (Core Redlines)
以下红线不可覆写。子 Agent 还会在 `.viking_state/sprint_prompt.txt` 收到同一套约束；主控只调度，不亲自探索：
1. **严禁裸跑 Raw Output**：执行大日志、长反编译、构建追踪或深层调试时，一律强制经过 `viking_bridge.py run` 拦截转存至 `viking://`；
2. **启动前必检**：每次任务启动或开辟新会话，第一步必须执行 `python3 {skill_dir}/viking_bridge.py doctor`；
3. **彻底强杀旧进程 (Mandatory Force-Kill)**：在构建、补丁、重签或启动测试前，**严禁使用普通 `pkill`**（macOS 守护进程会忽略 SIGTERM）。必须强制执行 `pkill -9 -f "<app_name>" 2>/dev/null || killall -9 "<app_name>" 2>/dev/null || true`，确保内存完全干净！
4. **严禁原始十六进制 Dump 毒化上下文 (Anti-Hex-Dump Shield)**：严禁在终端大段打印 `memory read` / `xxd` / `hexdump` 原始十六进制数据（大量零字节与重复十六进制会导致大模型注意力崩溃输出 `0,0,0,0...` 退化）。所有内存 Dump 必须使用 Python 脚本解析出关键结构，或通过管道转存至 `viking://`！
5. **调试重签必须注入 get-task-allow (AMFI & LLDB Bypass)**：重签 App 用于 LLDB 测试时，严禁使用裸 `codesign -s -`（会导致 AMFI 拦截报 error 9）。必须注入 `/tmp/debug_entitlements.plist`（包含 `get-task-allow` + `disable-library-validation`）！
6. **短冲刺子 Agent（Micro-Sprint）**：每个子 Agent 只做一道小题（`.viking_state/checkpoint.json` 的 `next_action`），禁止一次做完整个 runbook 阶段。探索类工具（`run`/`grep`/`ocr`）单次冲刺上限 8 次；第 6–7 次起 bridge 拒绝探索、只准 `note`/`checkpoint`/`sprint-done`；第 8 次自动结晶 checkpoint 并以退出码 20 让权。`note`/`checkpoint`/`doctor`/`sprint-reset`/`ask-ui`/`sprint-done` 不计入预算。
7. **工作集接力（Working Set）**：机器接力信源是 `.viking_state/checkpoint.json` 与 `discoveries.jsonl`（只追加合并，禁止覆盖已确认事实）。`HANDOVER.md` 只是给人看的渲染。子 Agent 最后一条命令必须是 `sprint-done`；closing message 只能是它打印的 4 行。严禁 `grep`/`cat`/`head` `work/disasm` 或 local_vfs。
8. **UI 验收必须人工（ask-ui）**：禁止自动截屏/OCR 重试。阶段 5 调用一次 `ask-ui`，人自己点进授权页并回答 y/n。`ASK_UI: NEED_HUMAN` 交给主控问人，禁止循环重试。
9. **多工作区进程物理隔离 (Multi-Workspace Process Shield)**：启动目标 App 前，必须清理其他工作区的同名常驻进程，严禁触发 macOS LaunchServices URL 跨工程静默路由劫持！
10. **本机架构优先渐进策略 (Native-First Architecture Strategy)**：面对 Universal 胖二进制时，**第一轮必须 100% 聚焦于本机原生架构（`uname -m`，如 Apple Silicon 下只跑 arm64）**！严禁在首轮分析或反编译非本机架构（x86_64）。待本机架构验证通过后，再按需镜像同步到另一架构并合成 Universal 胖二进制！
11. **监督模式职责分离**：主控只拆题、派一个短冲刺、读 checkpoint、判 Gate。`statem_supervisor.py` 与 `subagent` 必须同一回合连发，中间禁止 bash。本对话最多 4 个 subagent，第 4 个回来后新开对话。无 `SPRINT_STATUS` 或 closing 过长 = 假死，忽略正文，重派或新开。主控禁止 write/python 扫盘。派完立刻停轮。严禁 sleep/list_agents。乱码则停机读 checkpoint。
12. **状态机驱动**：严格按照 `runbook.yaml` 的阶段推进；短冲刺 DONE ≠ 阶段完成，阶段推进必须 `statem_driver.py --advance --gate-check`。
13. **系统稳定性优先**：防止上下文爆炸是物理底线，查看细节一律使用 `viking_bridge.py grep`，禁止裸 cat/grep `work/disasm`、local_vfs 或大文件。主控派子 agent 时只注入 supervisor 的 `DISPATCH_PROMPT`，禁止 cat `sprint_prompt.txt`。
{recipe_section}
---

## 2. 本项目专属快捷指令 (Project Quick Commands)

### 0. 前置体检
```bash
python3 {skill_dir}/viking_bridge.py doctor
```

### 1. 状态机推进与检查
```bash
# 查看当前任务阶段与 Gate 条件
python3 {skill_dir}/statem_driver.py --status

# 完成当前阶段后推进至下一阶段（短冲刺 DONE 不够，必须过 Gate）
python3 {skill_dir}/statem_driver.py --advance --gate-check
```

### 1b. 工作集与短冲刺 (Working Set + Micro-Sprint)
```bash
# 派发前重置冲刺预算，并注入一道小题（supervisor 合成 prompt 时会自动 sprint-reset）
python3 {skill_dir}/statem_supervisor.py --runbook runbook.yaml --sprint-goal "<one question>"

# 查看 / 写入工作集（不计入探索预算）
python3 {skill_dir}/viking_bridge.py checkpoint
python3 {skill_dir}/viking_bridge.py note --confirmed "<fact>" --rejected "<dead-end>" --next "<next question>"
python3 {skill_dir}/viking_bridge.py sprint-done --status DONE --confirmed "<fact>" --next "<next question>"
python3 {skill_dir}/viking_bridge.py sprint-status
python3 {skill_dir}/session_compactor.py --from-checkpoint --output HANDOVER.md
```

{tmpl['custom_commands'].format(skill_dir=skill_dir, project=project_name)}

### 3. 阶段成果存盘与会话压缩 (Session Handover)
优先用 checkpoint 渲染；不要把 harvest 当唯一信源。
```bash
python3 {skill_dir}/session_compactor.py --from-checkpoint --output HANDOVER.md
python3 {skill_dir}/session_compactor.py \\
  --project "{project_name}" \\
  --milestones "<已完成的阶段里程碑>" \\
  --discoveries "<关键技术发现与数据点>" \\
  --next-actions "<新会话的第一步行动>" \\
  --output HANDOVER.md
```
"""
    agents_file = os.path.join(target_dir, "AGENTS.md")
    with open(agents_file, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"✅ Generated tailored AGENTS.md: {agents_file}")


def _yaml_quote(s: str) -> str:
    text = (s or "").replace("\r", " ").replace("\n", " ")
    if '"' in text and "'" not in text:
        return f"'{text}'"
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def generate_runbook_yaml(project_name: str, task_type: str, user_prompt: str, target_dir: str):
    tmpl = TEMPLATES.get(task_type, TEMPLATES["general_long_task"])
    states_list = tmpl["states"]

    lines = [
        "version: '1.0'",
        f"task_name: {project_name}_{task_type}",
        f"description: {_yaml_quote(user_prompt.strip() or tmpl['description'])}",
        f"initial_state: {states_list[0][0]}",
        f"current_state: {states_list[0][0]}",
        "states:"
    ]

    for idx, (s_id, s_desc, s_gate) in enumerate(states_list):
        next_state = states_list[idx + 1][0] if idx + 1 < len(states_list) else "completed"
        lines.append(f"  {s_id}:")
        lines.append(f"    name: {s_id}")
        lines.append(f"    description: {_yaml_quote(s_desc)}")
        lines.append(f"    gate: {_yaml_quote(s_gate)}")
        lines.append("    transition:")
        lines.append(f"      on_success: {next_state}")
        lines.append(f"      on_failure: {s_id}")

    lines.append("  completed:")
    lines.append("    name: completed")
    lines.append("    description: \"All task milestones completed and verified.\"")
    lines.append("    gate: \"Deliverables generated and verified\"")

    runbook_content = "\n".join(lines) + "\n"
    runbook_file = os.path.join(target_dir, "runbook.yaml")
    with open(runbook_file, "w", encoding="utf-8") as f:
        f.write(runbook_content)
    print(f"✅ Generated tailored runbook.yaml: {runbook_file}")


def main():
    parser = argparse.ArgumentParser(description="Auto-Synthesize tailored AGENTS.md & runbook.yaml for any project")
    parser.add_argument("--project", required=True, help="Project / repository name (e.g. target_app, my_refactor)")
    parser.add_argument("--type", default="general_long_task", choices=["reverse_engineering", "code_refactor", "deep_debugging", "general_long_task"], help="Task archetype")
    parser.add_argument("--prompt", default="", help="User's original prompt description")
    parser.add_argument("--dir", default=".", help="Target workspace directory")

    args = parser.parse_args()
    target_dir = os.path.abspath(args.dir)
    os.makedirs(target_dir, exist_ok=True)

    print(f"🚀 Initializing Viking State Workflow for '{args.project}' ({args.type})...")
    generate_agents_md(args.project, args.type, args.prompt, target_dir)
    generate_runbook_yaml(args.project, args.type, args.prompt, target_dir)
    print(f"🎉 Project '{args.project}' is fully configured with zero context-overflow risk!\n")


if __name__ == "__main__":
    main()
