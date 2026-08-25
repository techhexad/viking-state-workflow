# Viking State Workflow

[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)
[![Python](https://img.shields.io/badge/Python-3.9+-green.svg)](https://www.python.org/)
[![Status](https://img.shields.io/badge/Status-Active-brightgreen.svg)]()

A long-horizon agent execution framework combining **StateM** (deterministic state machine & YAML runbooks), **OpenViking** (hierarchical VFS context database), and **macOS Vision OCR** (zero-VRAM native UI text extraction) to prevent LLM context window overflow, eliminate OOM crashes, and enforce structured execution across AI agents.

---

## 🎯 The Problem

When running complex, long-running agent tasks (e.g. binary reverse engineering, code refactoring, system diagnostics):
- Agent turns linearly accumulate massive tool outputs (`objdump`, stack traces, build logs, multimodal images).
- Context windows explode (> 300k tokens), triggering `400 Context Length Exceeded` or local LLM Out-Of-Memory (OOM) crashes.
- Sessions deadlock, losing state and forcing humans to manually distill and restart conversations.

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  Agent Execution Layer (Multi-Agent Support)                │
│  [ DSH ] / [ Hermes ] / [ OpenCode ] / [ Claude Code ] ... │
└──────────────────────────────┬──────────────────────────────┘
                               │ Structured commands & step gates
┌──────────────────────────────▼──────────────────────────────┐
│  State & Control Layer (StateM)                             │
│  - YAML-based declarative Runbooks                          │
│  - Gate validation before step transitions                  │
│  - Checkpoints & automatic rollback handling                │
└──────────────────────────────┬──────────────────────────────┘
                               │ VFS queries & offloaded logs
┌──────────────────────────────▼──────────────────────────────┐
│  Context, Memory & OCR Layer (OpenViking + Vision OCR)      │
│  - Heavy command output interception (`viking://`)          │
│  - Native macOS Vision OCR (Zero VRAM / token usage)        │
│  - L0/L1 progressive disclosure (summary first)             │
│  - Targeted snippet extraction (`viking_bridge.py grep`)    │
│  - Persistent session memory distillation                   │
└─────────────────────────────────────────────────────────────┘
```

---

## 📁 Repository Structure

```bash
viking-state-workflow/
├── SKILL.md                          # Agent Skill specification (Antigravity & Skills-Manager compliant)
├── README.md                         # Project documentation
├── LICENSE                           # Apache-2.0 License
├── scripts/
│   ├── workspace_init.py             # Universal project & runbook synthesizer for any task type
│   ├── viking_bridge.py              # OpenViking VFS client, pre-flight doctor & capture-ocr automation
│   ├── statem_driver.py              # Zero-dependency StateM state machine engine
│   ├── session_compactor.py          # Session state distillation & handover compactor
│   ├── mac_ocr.swift                 # Native macOS Vision OCR extractor (Zero dependencies / VRAM)
│   ├── viking_env.sh                 # Environment activation script for transparent shims
│   └── bin/                          # Transparent physical shims (lldb, objdump, otool)
└── templates/
    ├── runbook_template.yaml         # Production-ready YAML runbook template
    └── ov.conf.template              # OpenViking configuration template
```

---

## 🚀 Quick Start & Zero-Friction Auto-Bootstrap

### 🌟 零门槛使用（对普通用户只需一句话）：
用户无需了解底层工具，只需对任意 Agent 说一句话：
> **“使用 `viking-state-workflow` 技能开始一个新任务：[描述你的任务目标]”**

Agent 会**全自动执行 4 步初始化闭环**：
1. `viking_bridge.py doctor` ➔ 自动体检并嗅探端口与鉴权；
2. `workspace_init.py` ➔ 自动识别任务类型（重构/逆向/排障/通用）并生成专属 `AGENTS.md` 与 `runbook.yaml`；
3. `statem_driver.py --status` ➔ 确认第一阶段起点；
4. 立即开始执行阶段 1 工作！

---

### 🔧 开发者与底层工具链流水线 (Manual Reference)

#### 1. Pre-flight Doctor Check (Mandatory First Step)
Automatically verify OpenViking server availability, auth keys, and port alignment (e.g. 1933):
```bash
python3 scripts/viking_bridge.py doctor
```

#### 2. Auto-Synthesize New Project Workspace
Synthesize a customized `AGENTS.md` and tailored `runbook.yaml` for any task type:
```bash
python3 scripts/workspace_init.py \
  --project "<my_project>" \
  --type "reverse_engineering|code_refactor|deep_debugging|general_long_task" \
  --prompt "<task_description>" \
  --dir "."
```

### 3. Check State & Phase Gates
```bash
python3 scripts/statem_driver.py --status
```

### 4. Execute Heavy Commands with Automatic VFS Offload
Prevent LLM context explosion by offloading commands that produce large output (> 40 lines):
```bash
python3 scripts/viking_bridge.py run \
  --dest "viking://knowledge/myproject/disasm.asm" \
  --cmd "objdump -d /path/to/binary"
```
*The command returns an L0 preview + line count, saving the full body into OpenViking.*

### 5. Inspect Code Snippets On-Demand
Query specific functions or addresses without pulling the entire file into context:
```bash
python3 scripts/viking_bridge.py grep \
  --uri "viking://knowledge/myproject/disasm.asm" \
  --pattern "my_target_symbol" \
  --context 15
```

### 6. All-in-One GUI Verification & Vision OCR (Zero-VRAM)
Auto-activate application, elevate window to front, open settings, capture screenshot, and run native macOS Vision OCR:
```bash
python3 scripts/viking_bridge.py capture-ocr \
  --app "work/MyApp.app" \
  --dest "viking://knowledge/myproject/ocr/ui.txt" \
  --ask-user \
  --timeout 600
```

### 7. Advance State & Checkpoint
Validate gate conditions and advance to the next state:
```bash
python3 scripts/statem_driver.py --advance
```

### 8. Distill Session & Handover
When conversation history grows long (> 20k tokens), distill discoveries into a compact report (< 500 tokens):
```bash
python3 scripts/session_compactor.py \
  --project "myproject" \
  --milestones "Milestone 1 completed; Gate 2 verified" \
  --discoveries "Address 0x1004ffa38 locked; NOP is 1F 20 03 D5" \
  --next-actions "Apply 4-byte patch and codesign" \
  --output HANDOVER.md
```

---

## 🛡️ Dual-Layer Context Overflow Prevention

1. **Layer 1: Cognitive Redlines (`SKILL.md`)**: Strict prohibition against raw dumping of `lldb`, `objdump`, `otool`, `strings`, or long test traces directly to stdout.
2. **Layer 2: Physical Shims (`scripts/bin/`)**: Transparent command wrappers intercept raw binary invocations and auto-pipe outputs exceeding 40 lines into OpenViking.

---

## 🤝 Multi-Agent Compatibility

This workflow is agent-agnostic. It works out-of-the-box with:
- **DSH (DeepSeek Harness)**
- **Hermes Agent**
- **OpenCode**
- **Claude Code**
- **Google Antigravity**
- **Aider / OpenClaw**

---

## 📄 License

Apache License 2.0. See [LICENSE](LICENSE) for details.
