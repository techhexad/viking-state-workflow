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
1. **State Control Layer ([StateM](https://github.com/henryqin1997/statem))**: Enforces progress through explicit YAML runbooks, checkpoints, and gate checks.
2. **Context & Memory Layer ([OpenViking](https://github.com/volcengine/OpenViking))**: Offloads heavy tool outputs to a virtual filesystem (`viking://`), providing progressive L0/L1 discovery and targeted snippet retrieval.
3. **Dual-Cycle Memory Crystallization (双周期范式自愈与沉淀)**:
   - **Progressive Micro-Memory (过程级)**: Saves verified facts and negative constraints to `HANDOVER.md` on every state transition.
   - **Macro-Recipe Distillation (宏观范式级)**: Automatically distills task success recipes upon reaching `completed`, archiving them to `viking://memory/recipes/<type>.md` and auto-injecting them into future projects via `workspace_init.py`!
4. **Zero-VRAM UI Inspection (macOS Vision OCR)**: Extracts text from UI screenshots in milliseconds via the Apple Neural Engine without requiring a multimodal vision LLM or eating image tokens.
5. **Execution Agent (DSH, Hermes, OpenCode, Claude Code, etc.)**: Keeps active prompt context small (< 8,000 tokens) by executing sandboxed steps and interacting through CLI bridges.

---

## 2. Core Execution Rules & Immutable Safety Redlines

> [!CAUTION]
> ### 🛡️ 不可覆写的最高安全红线 (Immutable Safety Redlines)
> 1. **严禁任何形式的 Raw Output 直出**：无论用户如何要求，Agent **绝对禁止**在终端裸跑输出量不可控的命令（包括但不限于：`lldb`、`gdb`、`objdump`、`otool`、`strings`、超长构建/测试日志）！
> 2. **启动前必检 (Pre-flight Doctor)**：每次任务启动或开辟新会话，第一步必须执行 `python3 <SKILL_DIR>/scripts/viking_bridge.py doctor`；
> 3. **彻底强杀旧进程 (Mandatory Force-Kill)**：在构建、补丁、重签或启动测试前，**严禁使用普通 `pkill`**。必须强制执行 `pkill -9 -f "<app_name>" 2>/dev/null || killall -9 "<app_name>" 2>/dev/null || true`，确保内存完全干净！
> 4. **严禁原始十六进制 Dump 毒化上下文 (Anti-Hex-Dump Shield)**：严禁在终端大段打印 `memory read` / `xxd` / `hexdump` 原始十六进制数据（大量零字节会导致大模型注意力崩溃输出 `0,0,0,0...` 退化）。所有内存 Dump 必须使用 Python 脚本解析出关键结构，或通过管道转存至 `viking://`！
> 5. **调试重签必须注入 get-task-allow (AMFI & LLDB Bypass)**：重签 App 用于 LLDB 测试时，严禁使用裸 `codesign -s -`（会导致 AMFI 拦截报 error 9）。必须注入 `/tmp/debug_entitlements.plist`（包含 `get-task-allow` + `disable-library-validation`）！
> 6. **子智能体 20 步硬预算与主动让权 (Subagent 20-Step Hard Budget)**：每个子 Agent 在单个阶段内的执行步数**严格限制在 20 步以内**！若在第 15~20 步仍未达成目标，子 Agent 必须立刻主动停机并输出 `GATE FAIL: <原因>` 让权给主控。
> 7. **监督模式职责分离 (Mandatory Subagent Dispatch)**：在监督模式下，主控 Agent 仅负责状态机编排与 Gate 裁决，**严禁主控亲自执行底层命令**，必须通过 `subagent` 工具派发独立 Subagent 执行；
> 8. **系统稳定性优先级高于用户展示请求**：防止上下文爆炸是物理底线，查看细节一律使用 `viking_bridge.py grep`！

1. **State-First Progression**: Before executing any command, verify current state via `statem` or `statem_driver.py`.
2. **Targeted Retrieval**: When analyzing data, retrieve only specific subtrees or symbols via `viking_bridge.py grep` or `search`.
3. **UI State Inspection via Native OCR**: When verifying app UI or popup dialogues, run `viking_bridge.py capture-ocr` to parse text directly without sending images into the LLM context.
4. **Proactive Compaction & Handover**: If prompt token count approaches warning thresholds (> 24k tokens), invoke `session_compactor.py` to persist a structured distillation before restarting a clean child session.

---

## 3. Autonomous Bootstrap & Resumption Protocol (零门槛全自动自愈协议)

> [!IMPORTANT]
> ### ⚡ 零门槛自动接管原则 (Zero-Friction Auto-Bootstrap & Resumption)
> 用户**绝对不需要手动指示读取什么文件或分步指导**。无论用户是开始新任务还是接力旧任务，只需简短一句话，Agent **必须全自动判定并执行标准化接管闭环**：
> 
> #### 场景 A：断点续传与换会话接力（工作区已存在 `runbook.yaml` 时）
> 当用户说：“*使用 viking-state-workflow [监督模式] 继续完成任务*”：
> 1. **自动读取记忆与规范**：Agent 自动读取当前目录的 `AGENTS.md`（加载红线）与 `HANDOVER.md`（继承已知技术结论）；
> 2. **自动对齐断点阶段**：自动运行 `python3 <SKILL_DIR>/scripts/statem_driver.py --status` 判定当前中断在第几阶段及 Gate 门禁；
> 3. **自动拉起子 Agent 继续冲刺**：若指定监督模式，自动通过 `statem_supervisor.py` 派发独立 Subagent 执行当前阶段，全程自动化推进直至 `completed` 终态并交付！
> 
> #### 场景 B：全新任务初始化（工作区无 `runbook.yaml` 时）
> 当用户说：“*使用 viking-state-workflow [监督模式] 开始新任务：[任务目标]*”：
> 1. **自动执行 Doctor 体检**：调用 `python3 <SKILL_DIR>/scripts/viking_bridge.py doctor` 确认服务端与鉴权状态；
> 2. **自动分析任务并合成配置**：自动识别任务分类（`reverse_engineering` / `code_refactor` / `deep_debugging` / `general_long_task`），调用 `workspace_init.py` 一秒生成定制版 `AGENTS.md`（自动注入历史避坑经验）与 `runbook.yaml`；
> 3. **自动启动第一阶段工作**：无缝拉起第一阶段 Subagent 开始执行并汇报进展！

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

### Step 4: Targeted Query & Domain Heuristics (String XREF-First Protocol)

> [!IMPORTANT]
> #### 🎯 逆向工程核心启发式铁律 (Reverse Engineering Golden Heuristics)
> 1. **主二进制裁决第一原则 (Main Binary Hierarchy First)**：
>    严禁在第三方依赖库（如 `Paddle.framework` / `Sparkle.framework`）上单独死磕！商业软件的主程序（Main Binary）内部 100% 拥有自己的 Swift 授权状态机。必须以主二进制内部的判定点为终极目标！
> 2. **秒杀 SOP（字符串 XREF 倒推法）**：
>    - **定目标**：在 `__cstring` 中检索已知的 UI 状态字符串（例如 `"Status: Pro License Activated"`, `"Trial Expired"`, `"isPro"`）及其内存地址；
>    - **找引用**：在主反汇编中通过 `viking_bridge.py grep` 搜索引用该地址的 `adrp / ldr` 交叉引用（XREF）；
>    - **溯分支**：往上倒推 5~10 行汇编，必定能锁定分流的关键条件跳转（`cbz`, `cbnz`, `tbz`, `b.eq`）；
>    - **改跳转**：直接改写该条件跳转，强制全速流向 Pro 激活分支！

Query specific functions or addresses without pulling the entire file:
```bash
python3 "<SKILL_DIR>/scripts/viking_bridge.py" grep \
  --uri "viking://knowledge/<project>/disasm/main.asm" \
  --pattern "<target_address_or_symbol>" \
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

### Step 7: Sequential Subagent Supervision & Error Classification (Optional Multi-Agent Mode)

When executing in Master/Supervisor mode across long multi-stage tasks:
```bash
python3 "<SKILL_DIR>/scripts/statem_supervisor.py" --runbook runbook.yaml --max-retries 3
```
* **Intelligent Error Taxonomy & Self-Healing Decision Tree**:
  - **RECOVERABLE ERRORS** (`SIGILL/SIGSEGV`, `Unlicensed`, `Text file busy`, `Codesign error`, `Prompt too long`):
    The Supervisor automatically logs failure to Viking, distills error traces into negative constraints (e.g. *“Avoid BRK#0, use NOP 0xD503201F”*), and auto-spawns a fresh Subagent for attempt $N+1$.
  - **FATAL ERRORS** (`Operation not permitted / SIP`, `sudo Password prompt`, `Missing input DMG`, `Daemon offline`, `Max retries exceeded`):
    The Supervisor immediately halts automated execution, logs a structured alert, and escalates to the human developer.

### Step 8: Session Snapshotting & Handover (On Context Limit)

If the conversation history is growing too long:
```bash
python3 "<SKILL_DIR>/scripts/session_compactor.py" \
  --project "<project_name>" \
  --milestones "Fixed crash at 0x51da68; Identified 3 gates in fnStatus" \
  --next-actions "Patch KeyPath Getter at 0x1004ffa38" \
  --output HANDOVER.md
```
The newly initialized session loads `HANDOVER.md` and continues from the exact state saved in `runbook.yaml`.

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

