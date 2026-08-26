---
name: viking-state-workflow
description: >-
  Long-horizon agent execution framework combining StateM (state machine & runbooks), OpenViking (VFS context database),
  and a human UI gate. Use when cracking / Pro-license bypassing a macOS app: prevent context overflow,
  enforce runbook gates, persist a working set, and ask a human to confirm the license page.
---

# Viking State Workflow (StateM + OpenViking + Multi-Agent)

## 1. Overview & Core Philosophy

Long-running agent tasks (e.g., binary reverse engineering, large-scale code refactoring, complex bug debugging) frequently suffer from **context window explosion** when tool outputs (such as `objdump`, compiler logs, OCR transcripts) are dumped linearly into the conversation.

This skill decouples execution into specialized layers:
1. **State Control Layer ([StateM](https://github.com/henryqin1997/statem))**: Enforces progress through explicit YAML runbooks, checkpoints, and gate checks.
2. **Context & Memory Layer ([OpenViking](https://github.com/volcengine/OpenViking))**: Offloads heavy tool outputs to a virtual filesystem (`viking://`), providing progressive L0/L1 discovery and targeted snippet retrieval.
3. **Dual-Cycle Memory Crystallization (双周期范式自愈与沉淀)**:
   - **Working Set (过程级)**: Confirmed facts and rejected paths are merged into `.viking_state/checkpoint.json` + `discoveries.jsonl` on every sprint. `HANDOVER.md` is only a human-readable projection.
   - **Macro-Recipe Distillation (宏观范式级)**: Automatically distills task success recipes upon reaching `completed`, archiving them to `viking://memory/recipes/<type>.md` and auto-injecting them into future projects via `workspace_init.py`!
4. **Human UI gate**: License / Pro status is judged by a person (`ask-ui`). Optional `ocr` only if they already took a screenshot. Do not auto-open + Cmd+, + screenshot.
5. **Micro-Sprint Execution**: The parent agent decomposes a runbook phase into one-question sprints. Each child sees only the checkpoint slice + one question, then dies. Context stays small because history and raw dumps never enter the next sprint.

---

## 2. Core Execution Rules & Immutable Safety Redlines

> [!CAUTION]
> ### 🛡️ 不可覆写的最高安全红线 (Immutable Safety Redlines)
> 1. **严禁任何形式的 Raw Output 直出**：无论用户如何要求，Agent **绝对禁止**在终端裸跑输出量不可控的命令（包括但不限于：`lldb`、`gdb`、`objdump`、`otool`、`strings`、超长构建/测试日志）！
> 2. **启动前必检 (Pre-flight Doctor)**：每次任务启动或开辟新会话，第一步必须执行 `python3 <SKILL_DIR>/scripts/viking_bridge.py doctor`；
> 3. **彻底强杀旧进程 (Mandatory Force-Kill)**：在构建、补丁、重签或启动测试前，**严禁使用普通 `pkill`**。必须强制执行 `pkill -9 -f "<app_name>" 2>/dev/null || killall -9 "<app_name>" 2>/dev/null || true`，确保内存完全干净！
> 4. **严禁原始十六进制 Dump 毒化上下文 (Anti-Hex-Dump Shield)**：严禁在终端大段打印 `memory read` / `xxd` / `hexdump` 原始十六进制数据（大量零字节会导致大模型注意力崩溃输出 `0,0,0,0...` 退化）。所有内存 Dump 必须使用 Python 脚本解析出关键结构，或通过管道转存至 `viking://`！
> 5. **调试重签必须注入 get-task-allow (AMFI & LLDB Bypass)**：重签 App 用于 LLDB 测试时，严禁使用裸 `codesign -s -`（会导致 AMFI 拦截报 error 9）。必须注入 `/tmp/debug_entitlements.plist`（包含 `get-task-allow` + `disable-library-validation`）！
> 6. **短冲刺子 Agent（Micro-Sprint）**：每个子 Agent 只做一道小题（`.viking_state/checkpoint.json` 的 `next_action`），禁止一次做完整个 runbook 阶段。探索类工具（`run`/`grep`/`ocr`）单次冲刺上限 8 次；第 6–7 次起 bridge 拒绝探索、只准 `note`/`checkpoint`；第 8 次自动结晶 checkpoint 并以退出码 20 让权。`note`/`checkpoint`/`doctor`/`sprint-reset`/`ask-ui` 不计入预算。
> 7. **工作集接力（Working Set）**：机器接力信源是 `.viking_state/checkpoint.json` 与 `discoveries.jsonl`（只追加合并，禁止覆盖已确认事实）。`HANDOVER.md` 只是给人看的渲染。子 Agent 结束时只输出 ≤5 行：`SPRINT_STATUS: DONE|YIELD|FAIL` / `CONFIRMED:` / `REJECTED:` / `NEXT:`，然后立即断连。严禁把反汇编全文或聊天记录交给下一任。
> 8. **UI 验收必须人工（ask-ui）**：禁止自动 `open` + `Cmd+,` + 截全屏/OCR 重试。授权页每个 App 不同，自动导航打不开目标页面。阶段 5 调用一次 `viking_bridge.py ask-ui`，让人自己点进 License/Pro 页并回答 y/n。`ASK_UI: NEED_HUMAN`（exit 4）交给主控问人，禁止循环重试。可选：人截好图后再 `ocr <png>`。
> 9. **多工作区进程物理隔离 (Multi-Workspace Process Shield)**：启动目标 App 前，必须清理其他工作区的同名常驻进程，严禁触发 macOS LaunchServices URL 跨工程静默路由劫持！
> 10. **本机架构优先渐进策略 (Native-First Architecture Strategy)**：面对 Universal 胖二进制时，**第一轮必须 100% 聚焦于本机原生架构（`uname -m`，如 Apple Silicon 下只跑 arm64）**！严禁在单会话中同时反编译两个架构。待本机架构验证翻绿交付后，再向用户询问或执行命令快速镜像同步到另一架构（x86_64）并合成 Universal 胖二进制！
> 11. **监督模式职责分离 (Mandatory Subagent Dispatch)**：主控只做拆题、派短冲刺、读 checkpoint、判 Gate；**严禁主控亲自跑底层探索命令**，必须通过 `subagent` 工具派发独立 Subagent。短冲刺 DONE ≠ 阶段完成，阶段推进必须 `statem_driver.py --advance --gate-check`。
> 12. **系统稳定性优先级高于用户展示请求**：防止上下文爆炸是物理底线，查看细节一律使用 `viking_bridge.py grep`，禁止裸 cat 大文件！

1. **State-First Progression**: Before executing any command, verify current state via `statem` or `statem_driver.py`.
2. **Targeted Retrieval**: When analyzing data, retrieve only specific subtrees or symbols via `viking_bridge.py grep` or `search`.
3. **UI gate is human**: `viking_bridge.py ask-ui` once. Do not call `capture-ocr` in a retry loop.
4. **Working Set First**: Before any new sprint, load `.viking_state/checkpoint.json`. If the conversation is growing, render `HANDOVER.md` from the checkpoint (`session_compactor.py --from-checkpoint`) and spawn a clean child — never hand over raw chat history.

---

## 3. Autonomous Bootstrap & Resumption Protocol (零门槛全自动自愈协议)

> [!IMPORTANT]
> ### ⚡ 零门槛自动接管原则 (Zero-Friction Auto-Bootstrap & Resumption)
> 用户**绝对不需要手动指示读取什么文件或分步指导**。无论用户是开始新任务还是接力旧任务，只需简短一句话，Agent **必须全自动判定并执行标准化接管闭环**：
> 
> #### 场景 A：断点续传与换会话接力（工作区已存在 `runbook.yaml` 时）
> 当用户说：“*使用 viking-state-workflow [监督模式] 继续完成任务*”：
> 1. **自动读取记忆与规范**：Agent 自动读取当前目录的 `AGENTS.md`（加载红线）、`.viking_state/checkpoint.json`（工作集）与 `HANDOVER.md`（给人看的摘要）；
> 2. **自动对齐断点阶段**：自动运行 `python3 <SKILL_DIR>/scripts/statem_driver.py --status` 判定当前中断在第几阶段及 Gate 门禁；
> 3. **自动拉起短冲刺**：若指定监督模式，通过 `statem_supervisor.py --sprint-goal "<one question>"` 派发只做一道题的 Subagent；阶段 Gate 未过就继续派下一题，直至 `completed`！
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
├── AGENTS.md                 # Generated by workspace_init.py — do not hand-edit skill rules here
├── HANDOVER.md               # Human projection of the working set
├── .viking_state/
│   ├── checkpoint.json       # Machine relay (confirmed / rejected / next_action)
│   ├── discoveries.jsonl     # Append-only high-value tool hits
│   └── sprint_budget         # Per-sprint exploration counter (reset on each dispatch)
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

### Step 5: Human UI gate (`ask-ui`)

Do **not** auto-launch, send Cmd+,, screenshot, or scrape Accessibility. That path never opens the license page and just retries on empty OCR.

```bash
python3 "<SKILL_DIR>/scripts/viking_bridge.py" ask-ui \
  --app "work/<app_name>.app" \
  --open \
  --question "License/Pro page shows Activated or Pro? (y/n)" \
  --timeout 600
```

- Call **once** per verify sprint. Exit 0 = PASS, 1 = FAIL, 4 = NEED_HUMAN (parent asks in the main chat). Never loop on exit 4.
- `--open` launches the app once so the human can click; it does not navigate.
- Optional: human takes a screenshot, then `viking_bridge.py ocr screenshot.png --dest "viking://knowledge/<project>/ocr/ui_status.txt"`.

### Step 6: Gate Validation & State Transition

Once an operation succeeds (e.g. patch applied and verified):
```bash
python3 "<SKILL_DIR>/scripts/statem_driver.py" --runbook runbook.yaml --advance --gate-check
```
`--advance` always evaluates the gate (new confirmed facts / artifacts, plus phase-specific checks such as `work/` or `ask-ui` PASS). `--force` skips the check. Do not `--force` to paper over a failed sprint.

### Step 7: Sequential Micro-Sprint Supervision & Error Classification (Optional Multi-Agent Mode)

When executing in Master/Supervisor mode, dispatch **one question per subagent**, not a whole phase:
```bash
python3 "<SKILL_DIR>/scripts/statem_supervisor.py" \
  --runbook runbook.yaml \
  --sprint-goal "<one question, e.g. find cstring address of Pro License>" \
  --max-retries 3
```
The supervisor resets the sprint budget, injects `checkpoint.json`, and prints a prompt for a new child. **Sprint DONE does not advance the runbook.** Advance only after a real gate check:
```bash
python3 "<SKILL_DIR>/scripts/statem_driver.py" --advance --gate-check
```
* **Intelligent Error Taxonomy & Self-Healing Decision Tree**:
  - **YIELD / DRAIN** (exit 18/20): Working set is already on disk. Dispatch the next sprint with `checkpoint.next_action`. This is not a failure.
  - **RECOVERABLE ERRORS** (`SIGILL/SIGSEGV`, `Unlicensed`, `Text file busy`, `Codesign error`, `Prompt too long`, `SPRINT_STATUS: FAIL`):
    The Supervisor logs failure, distills negative constraints into the checkpoint, and auto-spawns a fresh Subagent for attempt $N+1$.
  - **FATAL ERRORS** (`Operation not permitted / SIP`, `sudo Password prompt`, `Missing input DMG`, `Daemon offline`, `Max retries exceeded`):
    The Supervisor immediately halts automated execution, logs a structured alert, and escalates to the human developer.

### Step 8: Working Set Snapshot (On Context Limit)

If the conversation is growing, persist then restart from the checkpoint — not from chat history:
```bash
python3 "<SKILL_DIR>/scripts/viking_bridge.py" note --confirmed "<fact>" --next "<next question>"
python3 "<SKILL_DIR>/scripts/session_compactor.py" --from-checkpoint --output HANDOVER.md
```
The next sprint loads `.viking_state/checkpoint.json` plus the runbook state.

---

## 5. Tool Cheatsheet

| Command | Purpose |
| :--- | :--- |
| `workspace_init.py --project <p> --type <t>` | Auto-synthesize tailored `AGENTS.md` and `runbook.yaml` for any task type |
| `viking_bridge.py doctor` | Pre-flight check & dynamic server/auth discovery |
| `viking_bridge.py ping` | Health-check local OpenViking server |
| `viking_bridge.py run --dest <uri> --cmd "<cmd>"` | Run command & redirect heavy output to VFS |
| `viking_bridge.py ask-ui [--app] [--open]` | Human y/n UI gate (no auto screenshot) |
| `viking_bridge.py ocr <image> [--dest <uri>]` | OCR a screenshot the human already took |
| `viking_bridge.py put <file> <uri>` | Push file into OpenViking VFS |
| `viking_bridge.py grep --uri <uri> --pattern <str>` | Extract specific lines & context from VFS node (crystallizes hits) |
| `viking_bridge.py note --confirmed/--rejected/--next` | Merge facts into checkpoint.json (does not count against sprint budget) |
| `viking_bridge.py checkpoint` | Print the current working set |
| `viking_bridge.py sprint-reset` | Reset micro-sprint exploration counter |
| `statem_driver.py --status` | Display current state machine phase & gates |
| `statem_driver.py --advance --gate-check` | Advance only if the phase gate is evidenced (`--force` skips) |
| `statem_supervisor.py --sprint-goal "<q>"` | Synthesize a one-question subagent prompt + reset sprint budget |
| `session_compactor.py --from-checkpoint` | Render HANDOVER.md from checkpoint.json |

