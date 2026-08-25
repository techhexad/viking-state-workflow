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
│   ├── mac_ocr.swift                 # Native macOS Vision OCR extractor (Zero dependencies / VRAM)
│   ├── viking_bridge.py              # OpenViking VFS client & command output interceptor
│   ├── statem_driver.py              # Zero-dependency StateM state machine engine
│   └── session_compactor.py          # Session state distillation & handover compactor
└── templates/
    ├── runbook_template.yaml         # Production-ready YAML runbook template
    └── ov.conf.template              # OpenViking configuration template
```

---

## 🚀 Quick Start

### 1. Prerequisites
- macOS 12+ (for native Apple Vision OCR support)
- Python 3.9+
- OpenViking daemon running locally (optional, built-in fallback directory is enabled if server is offline).

### 2. Verify OpenViking Connection
```bash
python3 scripts/viking_bridge.py ping
```

### 3. Initialize Task Runbook
Copy the runbook template into your workspace:
```bash
cp templates/runbook_template.yaml runbook.yaml
```

Check current phase & gates:
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

### 5. Extract UI Text via Native OCR (No Vision Model Needed)
When verifying GUI popups, settings screens, or error dialogs:
```bash
python3 scripts/viking_bridge.py ocr \
  screenshot.png \
  --dest "viking://knowledge/myproject/ocr/ui.txt"
```

### 6. Inspect Code Snippets On-Demand
Query specific functions or addresses without pulling the entire file into context:
```bash
python3 scripts/viking_bridge.py grep \
  --uri "viking://knowledge/myproject/disasm.asm" \
  --pattern "fnStatus" \
  --context 10
```

### 7. Advance State & Checkpoint
Validate gate conditions and advance to the next state:
```bash
python3 scripts/statem_driver.py --advance
```

### 8. Distill Session & Handover
When conversation history grows too long, distill discoveries into a compact report (< 500 tokens):
```bash
python3 scripts/session_compactor.py \
  --project "myproject" \
  --milestones "Fixed crash at 0x51da68; Identified 3 gates in fnStatus" \
  --next-actions "Patch KeyPath Getter at 0x1004ffa38" \
  --output session_distilled_state.md
```

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
