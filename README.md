# Viking State Workflow

[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)
[![Python](https://img.shields.io/badge/Python-3.9+-green.svg)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/Platform-macOS%20%7C%20Linux-lightgrey.svg)]()
[![Status](https://img.shields.io/badge/Status-Active-brightgreen.svg)]()

[English](README.md) | [中文说明](README_CN.md)

A long-horizon AI agent execution framework combining **[StateM](https://github.com/henryqin1997/statem)** (deterministic state machine & YAML runbooks), **[OpenViking](https://github.com/volcengine/OpenViking)** (hierarchical VFS context database by Volcengine), and **macOS Vision OCR** (zero-VRAM native UI text extraction) to prevent LLM context window overflow, eliminate OOM crashes, and enforce structured execution across AI agents.

---

## 🔗 Upstream & Core Dependencies

- **[OpenViking](https://github.com/volcengine/OpenViking)** (`volcengine/OpenViking`): Open-source context database & virtual filesystem (`viking://`) designed for AI Agents.
- **[StateM](https://github.com/henryqin1997/statem)** (`henryqin1997/statem`): Lightweight deterministic state machine engine for agent runbook execution.

---

## 🎯 The Problem

When running complex, long-running agent tasks (e.g. binary reverse engineering, large-scale code refactoring, full-stack bug hunting):
- Agent turns linearly accumulate massive tool outputs (`objdump`, stack traces, compiler logs, multi-megabyte disassemblies).
- Context windows explode (> 100k–300k tokens), triggering `400 Context Length Exceeded` or local LLM Out-Of-Memory (OOM) crashes.
- Sessions deadlock, losing operational state and forcing humans to manually distill and restart conversations.

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
├── README.md                         # English documentation
├── README_CN.md                      # Chinese documentation
├── LICENSE                           # Apache-2.0 License
├── scripts/
│   ├── workspace_init.py             # Universal project & runbook synthesizer for any task type
│   ├── viking_bridge.py              # OpenViking VFS client, pre-flight doctor & capture-ocr automation
│   ├── statem_driver.py              # Zero-dependency StateM state machine engine
│   ├── statem_supervisor.py          # Sequential subagent supervisor & error classification engine
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

### 🌟 Zero-Friction User Experience (Single Prompt Activation)
Users do not need to memorize tool commands. Simply say to any AI agent:
> **"Use `viking-state-workflow` skill to start a new task: [Describe your task goal]"**

The Agent will **autonomously execute the 4-step initialization sequence**:
1. `viking_bridge.py doctor` ➔ Automatically runs pre-flight health check, sniffing live port (e.g. 1933) and auth keys.
2. `workspace_init.py` ➔ Automatically identifies task archetype (`reverse_engineering`, `code_refactor`, `deep_debugging`, `general_long_task`) and synthesizes tailored `AGENTS.md` and `runbook.yaml`.
3. `statem_driver.py --status` ➔ Displays initial state and gate requirements.
4. Immediately commences execution of Phase 1!

---

### 🔧 Developer & Toolchain Pipeline Reference

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

#### 3. Check State & Phase Gates
```bash
python3 scripts/statem_driver.py --status
```

#### 4. Execute Heavy Commands with Automatic VFS Offload
Prevent LLM context explosion by offloading commands that produce large output (> 40 lines):
```bash
python3 scripts/viking_bridge.py run \
  --dest "viking://knowledge/myproject/disasm.asm" \
  --cmd "objdump -d /path/to/binary"
```
*The command returns an L0 preview + line count, saving the full body into OpenViking.*

#### 5. Inspect Code Snippets On-Demand
Query specific functions or addresses without pulling the entire file into context:
```bash
python3 scripts/viking_bridge.py grep \
  --uri "viking://knowledge/myproject/disasm.asm" \
  --pattern "my_target_symbol" \
  --context 15
```

#### 6. All-in-One GUI Verification & Vision OCR (Zero-VRAM)
Auto-activate application, elevate window to front, open settings, capture screenshot, and run native macOS Vision OCR:
```bash
python3 scripts/viking_bridge.py capture-ocr \
  --app "work/MyApp.app" \
  --dest "viking://knowledge/myproject/ocr/ui.txt" \
  --ask-user \
  --timeout 600
```

#### 7. Advance State & Checkpoint (Single-Agent Mode)
Validate gate conditions and advance to the next state:
```bash
python3 scripts/statem_driver.py --advance
```

#### 8. Sequential Subagent Supervision & Auto-Healing (Multi-Agent Mode)
Orchestrate sequential subagents across states with automated error classification and negative-constraint injection:
```bash
python3 scripts/statem_supervisor.py \
  --runbook runbook.yaml \
  --max-retries 3
```
*Auto-heals logic/crash failures (`SIGILL`, `Unlicensed`, `Text file busy`) by rebuilding subagents up to 3 times, while instantly pausing and alerting on fatal barriers (SIP permissions, missing files).*

#### 9. Distill Session & Handover
When conversation history grows long (> 20k tokens), distill discoveries into a compact report (< 500 tokens):
```bash
python3 scripts/session_compactor.py \
  --project "myproject" \
  --milestones "Milestone 1 completed; Gate 2 verified" \
  --discoveries "Address 0x1004ffa38 locked; NOP is 1F 20 03 D5" \
  --next-actions "Apply 4-byte patch and codesign" \
  --output HANDOVER.md
```
Load `HANDOVER.md` in a fresh session (Clean New Chat) to resume at full speed!

---

## 💬 Conversational Interaction Scenarios

Users can naturally interact with AI Agents using everyday natural language, activating different capabilities at task initialization or during execution:

---

### 🌟 Scenario 1: Task Initialization (Standard Mode or Supervisor Mode)

#### A. Standard Autonomous Initialization:
> **👤 User**:
> "Use `viking-state-workflow` to start a new task: Refactor the ecommerce ORM layer from GORM to Ent."

> **🤖 Agent**:
> "Understood! Autonomously executing initialization loop:
> 1. ✅ **Pre-flight Health**: `viking_bridge.py doctor` verified, OpenViking online.
> 2. ✅ **Workspace Scaffold**: Identified as `code_refactor` archetype; generated tailored `AGENTS.md` and 5-phase `runbook.yaml`.
> 3. 🎯 **Initial Phase**: `dependency_audit` (Scan module boundaries and call sites).
> Starting Phase 1 execution now..."

#### B. Direct Activation of "Supervisor Auto-Healing Mode":
> **👤 User**:
> "Start a new task in **supervisor mode** with `viking-state-workflow`: Reverse engineer `TargetApp.dmg` Pro checks, auto-rebuilding subagents up to 3 retries on failure."

> **🤖 Agent**:
> "Pre-flight check passed and workspace scaffolded! Taking over in **Sequential Supervisor Mode**:
> ```bash
> python3 scripts/statem_supervisor.py --runbook runbook.yaml --max-retries 3
> ```
> Each phase will be executed by dedicated lightweight Subagents. Logic/crash failures will be auto-healed with negative constraints, while fatal barriers will instantly pause for human assistance."

---

### 🔍 Scenario 2: Heavy Command Offload & Code Snippet Retrieval
> **👤 User**:
> "Is disassembly ready? Search for critical Pro check logic around `fnStatus`."

> **🤖 Agent**:
> "Disassembly complete!
> 🛡️ **VFS Context Offload**: Main binary disassembly is 205MB. It was safely offloaded via `viking_bridge.py run` to `viking://knowledge/target_app/disasm/main_disasm.txt` without bloating our active prompt.
> 🔍 **Targeted Retrieval**: Retrieved key snippet via `viking_bridge.py grep`:
> ```asm
> 0x10051da58  bl  func.100507f68       ; Read Pro activation boolean -> w21
> 0x10051da68  tbz w21, #0, 0x10051db3c ; Branch to unlicensed path (Patch target)
> ```
> Recommend replacing the jump at `0x51da68` with true NOP (`1F 20 03 D5`)."

---

### 🖥️ Scenario 3: Automated GUI Verification & Human Confirmation
> **👤 User**:
> "Patch is applied. Launch the app to verify UI status. Prompt me for manual check and wait 3 minutes."

> **🤖 Agent**:
> "Running all-in-one UI verification pipeline:
> ```bash
> python3 scripts/viking_bridge.py capture-ocr \
>   --app "work/TargetApp.app" \
>   --dest "viking://knowledge/target_app/ocr/ui.txt" \
>   --ask-user --timeout 180
> ```
> *(Auto-activated app ➔ Brought window to front ➔ Cmd+, opened Settings ➔ Native Vision OCR extracted text)*
> 
> ❓ **Human Verification**: OCR recognized `Pro License Activated`. Please check your screen and type `y` to confirm (will auto-confirm and kill test process after 180s timeout)."

---

### 🔄 Scenario 4: Sequential Subagent Auto-Healing in Action
> **🤖 Agent (Main Supervisor Live Log)**:
> "Captured an error during current phase execution, auto-healing in progress:
> 1. 🚀 **[Attempt 1/3] Subagent-1** attempted patch at `0x51da68` ➔ App crashed with `SIGILL (EXC_BAD_INSTRUCTION)`.
> 2. 🔍 **Supervisor Error Classification**: Categorized as **`RECOVERABLE` (Illegal instruction BRK#0 written)**.
> 3. 🧠 **Feedback Injection**: Extracted crash trace into negative constraint: *“Avoid BRK instructions; use true NOP (1F 20 03 D5).”*
> 4. 🚀 **[Attempt 2/3] Auto-respawned Subagent-2** with updated constraints ➔ Re-calculated patch bytes ➔ App launched cleanly and passed Gate!
> 5. ✅ **Supervisor Transition**: Automatically ran `statem_driver.py --advance` to proceed to the next phase!"

---

### 📦 Scenario 5: Proactive Session Compaction & Clean Restart
> **👤 User**:
> "Our chat history is over 20k tokens. Create a handover summary and let's continue in a new chat."

> **🤖 Agent**:
> "Generated `HANDOVER.md` via `session_compactor.py`!
> 📊 Context compressed to ~400 tokens. Please open a **New Chat** and prompt:
> > *'Load AGENTS.md and HANDOVER.md, and continue with package_delivery phase.'*
> The new session will resume instantly with 100% clean context!"

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
