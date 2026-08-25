---
name: viking-state-workflow
description: >-
  Long-horizon agent execution framework combining StateM (state machine & runbooks) and OpenViking (VFS context database).
  Use when running complex, multi-step, or long-running tasks across any AI agent (DSH, Hermes, OpenCode, Claude Code, Aider)
  to prevent context window overflow (OOM / 400 Context Length Exceeded), enforce deterministic state transitions,
  and automate session handovers with persistent memory.
---

# Viking State Workflow (StateM + OpenViking + Multi-Agent)

## 1. Overview & Core Philosophy

Long-running agent tasks (e.g., binary reverse engineering, large-scale code refactoring, complex bug debugging) frequently suffer from **context window explosion** when tool outputs (such as `objdump`, compiler logs, OCR transcripts) are dumped linearly into the conversation.

This skill decouples execution into three specialized layers:
1. **State Control Layer (StateM)**: Enforces progress through explicit YAML runbooks, checkpoints, and gate checks.
2. **Context & Memory Layer (OpenViking)**: Offloads heavy tool outputs to a virtual filesystem (`viking://`), providing progressive L0/L1 discovery and targeted snippet retrieval.
3. **Execution Agent (DSH, Hermes, OpenCode, Claude Code, etc.)**: Keeps active prompt context small (< 8,000 tokens) by executing sandboxed steps and interacting through CLI bridges.

---

## 2. Core Execution Rules (Strict Context Discipline)

> [!CAUTION]
> **Zero Raw Output Dumping**: Never output full disassemblies, raw binary hex dumps, or multiline build traces (> 40 lines) directly into the agent prompt. Always use `viking_bridge.py run` to redirect to OpenViking.

1. **State-First Progression**: Before executing any command, verify current state via `statem` or `statem_driver.py`.
2. **Targeted Retrieval**: When analyzing data, retrieve only specific subtrees or symbols via `viking_bridge.py grep` or `search`.
3. **Proactive Compaction & Handover**: If prompt token count approaches warning thresholds (> 24k tokens), invoke `session_compactor.py` to persist a structured distillation before restarting a clean child session.

---

## 3. Directory & File Conventions

All task-specific state should be structured as follows:

```bash
<project_root>/
├── runbook.yaml              # StateM task runbook
├── .viking_state/            # Local cache & snapshot metadata
└── scripts/                  # Skill utilities
```

In the OpenViking Virtual Filesystem (`viking://`):
- `viking://knowledge/<project>/disasm/` : Full disassembly dumps
- `viking://knowledge/<project>/logs/`   : Full build and runtime logs
- `viking://knowledge/<project>/ocr/`    : Image/OCR extracted text
- `viking://memory/<project>/sessions/`  : Distilled handover notes (`session_distilled_state.md`)

---

## 4. Standard Operational Procedure (SOP)

### Step 1: Verify Infrastructure Services

Verify OpenViking server availability:
```bash
python3 "<SKILL_DIR>/scripts/viking_bridge.py" ping
```
*If offline, start OpenViking in its dedicated environment:*
```bash
openviking-server --storage-dir ~/.openviking/storage &
```

### Step 2: Initialize or Load Runbook

Check the current active phase:
```bash
python3 "<SKILL_DIR>/scripts/statem_driver.py" --runbook runbook.yaml --status
```
If starting a new task, generate a `runbook.yaml` using the template at `<SKILL_DIR>/templates/runbook_template.yaml`.

### Step 3: Sandboxed Execution with VFS Offloading

Execute heavy commands using the interception wrapper:
```bash
python3 "<SKILL_DIR>/scripts/viking_bridge.py" run \
  --dest "viking://knowledge/<project>/disasm/main.asm" \
  --cmd "objdump -d <binary_path>"
```
*The wrapper returns a concise summary (L0) and line ranges rather than the raw output.*

### Step 4: Targeted Query & Patching

Query specific functions or addresses without pulling the entire file:
```bash
python3 "<SKILL_DIR>/scripts/viking_bridge.py" grep \
  --uri "viking://knowledge/<project>/disasm/main.asm" \
  --pattern "fnStatus" \
  --context 15
```

### Step 5: Gate Validation & State Transition

Once an operation succeeds (e.g. patch applied and verified):
```bash
python3 "<SKILL_DIR>/scripts/statem_driver.py" --runbook runbook.yaml --advance --gate-check
```

### Step 6: Session Snapshotting & Handover (On Context Limit)

If the conversation history is growing too long:
```bash
python3 "<SKILL_DIR>/scripts/session_compactor.py" \
  --project "<project_name>" \
  --milestones "Fixed crash at 0x51da68; Identified 3 gates in fnStatus" \
  --next-actions "Patch KeyPath Getter at 0x1004ffa38" \
  --output session_distilled_state.md
```
The newly initialized session loads `session_distilled_state.md` and continues from the exact state saved in `runbook.yaml`.

---

## 5. Tool Cheatsheet

| Command | Purpose |
| :--- | :--- |
| `viking_bridge.py ping` | Health-check local OpenViking server |
| `viking_bridge.py run --dest <uri> --cmd "<cmd>"` | Run command & redirect heavy output to VFS |
| `viking_bridge.py put <file> <uri>` | Push file into OpenViking VFS |
| `viking_bridge.py grep --uri <uri> --pattern <str>` | Extract specific lines & context from VFS node |
| `viking_bridge.py tree [uri]` | Browse VFS knowledge hierarchy |
| `statem_driver.py --runbook <file> --status` | Display current state machine phase & gates |
| `statem_driver.py --runbook <file> --advance` | Advance to the next verified state |
| `session_compactor.py --project <name>` | Distill session into persistent memory snapshot |
