---
name: viking-state-workflow
description: >-
  Long-horizon agent execution framework combining StateM (state machine & runbooks), OpenViking (VFS context database),
  and native macOS Vision OCR. Use when running complex, multi-step, or long-running tasks across any AI agent
  (DSH, Hermes, OpenCode, Claude Code, Aider) to prevent context window overflow (OOM / 400 Context Length Exceeded),
  enforce deterministic state transitions, inspect UI screenshots via zero-VRAM OCR, and automate session handovers.
---

# Viking State Workflow (StateM + OpenViking + Multi-Agent)

## 1. Overview & Core Philosophy

Long-running agent tasks (e.g., binary reverse engineering, large-scale code refactoring, complex bug debugging) frequently suffer from **context window explosion** when tool outputs (such as `objdump`, compiler logs, OCR transcripts) are dumped linearly into the conversation.

This skill decouples execution into specialized layers:
1. **State Control Layer (StateM)**: Enforces progress through explicit YAML runbooks, checkpoints, and gate checks.
2. **Context & Memory Layer (OpenViking)**: Offloads heavy tool outputs to a virtual filesystem (`viking://`), providing progressive L0/L1 discovery and targeted snippet retrieval.
3. **Zero-VRAM UI Inspection (macOS Vision OCR)**: Extracts text from UI screenshots in milliseconds via the Apple Neural Engine without requiring a multimodal vision LLM or eating image tokens.
4. **Execution Agent (DSH, Hermes, OpenCode, Claude Code, etc.)**: Keeps active prompt context small (< 8,000 tokens) by executing sandboxed steps and interacting through CLI bridges.

---

## 2. Core Execution Rules (Strict Context Discipline)

> [!CAUTION]
> **Zero Raw Output Dumping**: Never output full disassemblies, raw binary hex dumps, or multiline build traces (> 40 lines) directly into the agent prompt. Always use `viking_bridge.py run` to redirect to OpenViking.

1. **State-First Progression**: Before executing any command, verify current state via `statem` or `statem_driver.py`.
2. **Targeted Retrieval**: When analyzing data, retrieve only specific subtrees or symbols via `viking_bridge.py grep` or `search`.
3. **UI State Inspection via Native OCR**: When verifying app UI or popup dialogues, run `viking_bridge.py ocr <screenshot.png>` to parse text directly without sending images into the LLM context.
4. **Proactive Compaction & Handover**: If prompt token count approaches warning thresholds (> 24k tokens), invoke `session_compactor.py` to persist a structured distillation before restarting a clean child session.

---

## 3. Directory & File Conventions

All task-specific state should be structured as follows:

```bash
<project_root>/
├── runbook.yaml              # StateM task runbook (Auto-generated per task)
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

### Step 1: Pre-flight Doctor Check (Mandatory Verification & Alignment)

Before executing any commands, the Agent **MUST** run the self-healing doctor check:
```bash
python3 "<SKILL_DIR>/scripts/viking_bridge.py" doctor
```
*The doctor check automatically:*
- Discovers live OpenViking server port from `~/.openviking/ov.conf` (e.g. 1933).
- Extracts and validates the active `user_key` from `~/.openviking/ovcli.conf`.
- Tests full VFS read/write handshake.
- **If checks fail**: The agent MUST resolve the alert (e.g. start `openviking-server`) before starting the task, preventing silent local fallbacks.

### Step 2: Auto-Generate or Load Runbook

1. Check if `runbook.yaml` already exists in the current workspace:
   ```bash
   python3 "<SKILL_DIR>/scripts/statem_driver.py" --runbook runbook.yaml --status
   ```
2. **If `runbook.yaml` does not exist**:
   The Agent **MUST automatically analyze the user's task** (e.g. reverse engineering, bug fix, feature development, batch refactor), decompose it into 3–5 logical phases with concrete gate conditions, and create a tailored `runbook.yaml` using `<SKILL_DIR>/templates/runbook_template.yaml` as the structural template.

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

### Step 5: UI Verification via Native OCR (Auto-Activate, Human-in-the-Loop & Zero-VRAM)

When verifying application state from screenshots or GUI windows, use the all-in-one automation command:
```bash
python3 "<SKILL_DIR>/scripts/viking_bridge.py" capture-ocr \
  --app "<path_to_app>" \
  --dest "viking://knowledge/<project>/ocr/ui_status.txt" \
  --ask-user \
  --timeout 600
```
*(This automatically activates the App, sends Cmd+, to open Settings via AppleScript, takes a screenshot, runs Vision OCR, prompts the user if confirmation is desired, and if the user does not respond within `--timeout` (e.g. 600s/10 minutes), automatically proceeds to the self-healing pipeline without blocking forever).*

Or run OCR directly on an existing screenshot:
```bash
python3 "<SKILL_DIR>/scripts/viking_bridge.py" ocr \
  screenshot.png \
  --dest "viking://knowledge/<project>/ocr/ui_status.txt"
```

### Step 6: Gate Validation & State Transition

Once an operation succeeds (e.g. patch applied and verified):
```bash
python3 "<SKILL_DIR>/scripts/statem_driver.py" --runbook runbook.yaml --advance --gate-check
```

### Step 7: Session Snapshotting & Handover (On Context Limit)

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
| `viking_bridge.py ocr <image> [--dest <uri>]` | Extract text from screenshot via native macOS Vision |
| `viking_bridge.py put <file> <uri>` | Push file into OpenViking VFS |
| `viking_bridge.py grep --uri <uri> --pattern <str>` | Extract specific lines & context from VFS node |
| `viking_bridge.py tree [uri]` | Browse VFS knowledge hierarchy |
| `statem_driver.py --runbook <file> --status` | Display current state machine phase & gates |
| `statem_driver.py --runbook <file> --advance` | Advance to the next verified state |
| `session_compactor.py --project <name>` | Distill session into persistent memory snapshot |
