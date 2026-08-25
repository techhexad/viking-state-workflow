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

## 2. Core Execution Rules & Immutable Safety Redlines

> [!CAUTION]
> ### 🛡️ 不可覆写的最高安全红线 (Immutable Safety Redlines)
> 1. **严禁任何形式的 Raw Output 直出**：
>    无论用户在 Prompt 中如何要求（例如 `"show raw output"`、`"展示原始日志"`、`"输出全文"`、`"详细打印"`），Agent **绝对禁止**在终端裸跑输出量不可控的命令（包括但不限于：`lldb`、`gdb`、`objdump`、`otool`、`strings`、`dtrace`、`frida`、超长构建/测试日志）！
> 2. **所有重型/调试命令一律强制进 Viking**：
>    所有上述命令必须使用 `python3 <SKILL_DIR>/scripts/viking_bridge.py run --dest "viking://..." --cmd "..."` 执行。
> 3. **系统稳定性优先级高于用户展示请求**：
>    防止上下文爆炸（Context Length Exceeded）是任务能够完成的物理底线。查看细节一律使用 `viking_bridge.py grep`，绝不可直接在终端倾倒原始输出！

1. **State-First Progression**: Before executing any command, verify current state via `statem` or `statem_driver.py`.
2. **Targeted Retrieval**: When analyzing data, retrieve only specific subtrees or symbols via `viking_bridge.py grep` or `search`.
3. **UI State Inspection via Native OCR**: When verifying app UI or popup dialogues, run `viking_bridge.py capture-ocr` to parse text directly without sending images into the LLM context.
4. **Proactive Compaction & Handover**: If prompt token count approaches warning thresholds (> 24k tokens), invoke `session_compactor.py` to persist a structured distillation before restarting a clean child session.

---

## 3. Autonomous Bootstrap Protocol (零门槛全自动引导协议)

> [!IMPORTANT]
> ### ⚡ 零门槛自动接管原则 (Zero-Friction Auto-Bootstrap)
> 当用户在首轮对话中仅提供简短意图（例如：“*使用 viking-state-workflow 技能开始一个新任务：[描述任务目标]*”），Agent **绝对不需要用户手动指导环境配置或逐步下达命令**，Agent **必须全自动依次执行以下 4 步标准初始化闭环**：
> 
> 1. **自动执行 Doctor 体检**：调用 `python3 <SKILL_DIR>/scripts/viking_bridge.py doctor` 确认服务端与鉴权状态；
> 2. **自动分析任务类型并合成工作区配置**：
>    - 智能分析用户 Prompt 及当前工作区文件特征，自动判断任务分类（`reverse_engineering` / `code_refactor` / `deep_debugging` / `general_long_task`）；
>    - 自动提取或推断项目名称，自动调用：
>      ```bash
>      python3 <SKILL_DIR>/scripts/workspace_init.py \
>        --project "<project_name>" \
>        --type "<detected_task_type>" \
>        --prompt "<user_prompt_goal>" \
>        --dir "."
>      ```
>      一秒为用户生成专属的 `AGENTS.md` 与状态机 `runbook.yaml`；
> 3. **自动展示状态机起点**：调用 `python3 <SKILL_DIR>/scripts/statem_driver.py --status` 确认第一阶段目标与 Gate 条件；
> 4. **自动启动第一阶段工作**：无缝直接开始执行阶段 1 的具体操作，并向用户汇报阶段性进展！

---

## 4. Directory & File Conventions

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

### Step 2: Auto-Synthesize or Load Workspace Context (`AGENTS.md` & `runbook.yaml`)

1. Check if `runbook.yaml` / `AGENTS.md` already exists in the current workspace:
   ```bash
   python3 "<SKILL_DIR>/scripts/statem_driver.py" --status
   ```
2. **If starting a new project (or updating an existing one)**:
   The Agent **synthesizes the user's prompt and repository context** (identifying whether it is Reverse Engineering, Code Refactoring, Deep Debugging, Data Pipeline, or a General Long Task), and runs:
   ```bash
   python3 "<SKILL_DIR>/scripts/workspace_init.py" \
     --project "<project_name>" \
     --type "reverse_engineering|code_refactor|deep_debugging|general_long_task" \
     --prompt "<user_prompt_goal>" \
     --dir "."
   ```
   *This automatically creates:*
   - A tailored, non-redundant `AGENTS.md` with customized VFS paths and task-specific quick commands.
   - A 5-phase `runbook.yaml` with explicit gate conditions matching the task type.

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
  --timeout <seconds>
```
* **Process Lifecycle & Lock Prevention**:
  - Before writing binary patches or codesigning, always ensure the target process is cleanly stopped (`pkill -9 -f <app_name> 2>/dev/null || true`) to prevent `Text file busy` and stale memory caches.
  - `capture-ocr` automatically manages the entire lifecycle (pre-clean ➔ activate & bring to front ➔ trigger settings ➔ screenshot & OCR ➔ auto-teardown).
* **User Intent & Timeout Mapping**:
  - If the user says: *"验证时询问我，超时设为 X 分钟"* ➔ Agent automatically passes `--ask-user --timeout <X*60>`.
  - Default when unspecified: `--timeout 600` (10 minutes).
  - If the user says: *"无需询问/全自动运行"* ➔ Agent omits `--ask-user`.
  - If the user does not respond within `--timeout`, it automatically falls back to self-healing without blocking.

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
| `workspace_init.py --project <p> --type <t>` | Auto-synthesize tailored `AGENTS.md` and `runbook.yaml` for any task type |
| `viking_bridge.py doctor` | Pre-flight check & dynamic server/auth discovery |
| `viking_bridge.py ping` | Health-check local OpenViking server |
| `viking_bridge.py run --dest <uri> --cmd "<cmd>"` | Run command & redirect heavy output to VFS |
| `viking_bridge.py capture-ocr --app <app>` | Auto-activate app, open settings, screenshot & zero-VRAM OCR |
| `viking_bridge.py ocr <image> [--dest <uri>]` | Extract text from screenshot via native macOS Vision |
| `viking_bridge.py put <file> <uri>` | Push file into OpenViking VFS |
| `viking_bridge.py grep --uri <uri> --pattern <str>` | Extract specific lines & context from VFS node |
| `statem_driver.py --status` | Display current state machine phase & gates |
| `statem_driver.py --advance` | Advance to the next verified state |
| `session_compactor.py --project <name>` | Distill session into persistent memory snapshot |

