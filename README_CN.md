# Viking State Workflow (维京状态机工作流)

[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)
[![Python](https://img.shields.io/badge/Python-3.9+-green.svg)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/Platform-macOS-lightgrey.svg)]()
[![Status](https://img.shields.io/badge/Status-Active-brightgreen.svg)]()

[English](README.md) | [中文说明](README_CN.md)

专门跑 **macOS 应用破解 / Pro 授权绕过**。本地小机器、显存和上下文都有限时，用冻结剧本：解包 → 反汇编进 OpenViking → 在**主二进制**里字符串 XREF 定位授权闸门 → 改跳转并重签 → OCR 验收 Pro 界面。

进度写在 YAML runbook。大 dump 进 `viking://`。事实进 `checkpoint.json`。每个子 Agent 只答**一道题**。

依赖：[OpenViking](https://github.com/volcengine/OpenViking) · [StateM](https://github.com/henryqin1997/statem)

本 skill **不是**通用长任务框架。不要拿来做仓库重构、产品开发或线上排障。

---

## 先建立这三层关系

不要把「阶段」「冲刺」「DSH 步数」混成一件事：

```
runbook 阶段（Gate 过了才能 --advance）
    └── 多轮短冲刺（每轮只答一道小题）
            └── 每轮最多 8 次 viking_bridge 探索（run/grep/ocr）
                    └── 事实写入 .viking_state/checkpoint.json
```

| 名词 | 是什么 | 谁推进 |
|---|---|---|
| **阶段** | 解包 → 反汇编 → 定位闸门 → 补丁重签 → OCR 验证 | 主控在 Gate 通过后 `--advance --gate-check` |
| **短冲刺** | 子 Agent 只做 `checkpoint.next_action` 这一题 | 主控派发；子 Agent 输出 `SPRINT_STATUS` 后结束 |
| **8 步超时** | 一次冲刺里 `viking_bridge` 探索调用的上限 | **bridge 硬限制**，不是 DSH 的 `step/start` |

机器接力信源是 `.viking_state/checkpoint.json` + `discoveries.jsonl`。`HANDOVER.md` 只是给人看的投影。

---

## 一句话怎么用

在**空目录**开新聊天：

> 使用 viking-state-workflow 监督模式开始新任务：逆向分析 `/path/to/App.dmg` 的 Pro 授权，最终交给我破解版 app。

已有 `runbook.yaml` 的目录里续跑：

> 使用 viking-state-workflow 监督模式，继续完成当前任务。

不必写「短冲刺 / 8 步 / checkpoint」。Agent 应自动：`doctor` → 没有 runbook 就 `workspace_init --type reverse_engineering` → 按当前阶段出一道小题 → 派子 Agent。

主控只拆题、读 checkpoint、判 Gate；不要一次做完整个阶段。

`statem_supervisor.py --sprint-goal` 之后只派 **一个** `subagent`，然后 **停轮**。禁止 `sleep` / `list_agents` 轮询、禁止主控 grep 200MB 反汇编、禁止再开一个子 agent 去盯另一个。本地 GPU 一次只跑一份推理，watcher 会把正在干活的冲刺拖死。checkpoint 里每条事实截断到 240 字。若本会话开始中英日韩法阿混杂乱码：**立刻停**，新开对话读 `.viking_state/checkpoint.json`。

DSH 侧（不在本仓库）：`streamIdleTimeoutMs` 用分钟级而不是 30 分钟；给默认模型加 `maxTokens`（例如 2048），避免一次生成把 32k 垃圾写进历史。

---

## 破解剧本

生成的 `runbook.yaml` 阶段：

1. **unpack_and_extract** — 挂载 DMG，切出本机架构 thin binary（先 `uname -m`）
2. **symbol_and_disasm** — 符号、字符串、完整反汇编进 `viking://`
3. **analyze_gating** — 在**主二进制**做字符串 XREF（不要在 Paddle / Sparkle 里打转）
4. **craft_patch** — 改跳转，必要时合成胖二进制，重签
5. **verify_and_deliver** — 人自己点进授权页，用 `ask-ui` 答 y/n

第三阶段秒杀 SOP（字符串 XREF）：

1. 在 `__cstring` 里定位 UI 字符串（`Pro License`、`Activated`、`Trial Expired`、`Unlicensed`）
2. `viking_bridge.py grep` 搜对该地址的 `adrp` / `ldr` 交叉引用
3. 往上倒 5～10 条指令，分流一般是 `cbz` / `cbnz` / `tbz` / `b.eq`
4. 改写跳转，强制走 Pro 分支

---

## 工作区里会有什么

```
<project>/
├── runbook.yaml                 # 破解阶段与 Gate
├── AGENTS.md                    # 红线与命令
├── HANDOVER.md                  # checkpoint 的人读版
├── .viking_state/
│   ├── checkpoint.json          # 已确认事实 / 已否决路径 / next_action
│   ├── discoveries.jsonl        # 工具命中，只追加
│   └── sprint_budget            # 本轮探索计数，派发时清零
└── work/                        # 解包、thin binary、打过补丁的 .app
```

反汇编、追踪、OCR 在 `viking://knowledge/<project>/`，不进对话。

---

## 命令怎么配合（开发者速查）

脚本默认在 skill 的 `scripts/` 下，工作区里请用 `AGENTS.md` 写明的绝对路径。

**1. 体检与建项目**

```bash
python3 scripts/viking_bridge.py doctor
python3 scripts/workspace_init.py \
  --project "<项目名>" \
  --type reverse_engineering \
  --prompt "破解 <App> Pro 授权，交付可运行的补丁版 app" \
  --dir "."
python3 scripts/statem_driver.py --status
```

**2. 探索（计入 8 步）** — 禁止裸 `objdump` / `cat` 大文件。

```bash
python3 scripts/viking_bridge.py run \
  --dest "viking://knowledge/<project>/disasm/main.asm" \
  --cmd "objdump -d work/<binary>"

python3 scripts/viking_bridge.py grep \
  --uri "viking://knowledge/<project>/disasm/main.asm" \
  --pattern "<符号或地址>" --context 15

python3 scripts/viking_bridge.py ask-ui \
  --app "work/MyApp.app" \
  --open \
  --question "License/Pro 页是否显示 Activated 或 Pro？(y/n)" \
  --timeout 600
```

**3. 落盘（不计入 8 步）**

```bash
python3 scripts/viking_bridge.py note \
  --confirmed "<事实>" --rejected "<死胡同>" --next "<下一题>"
python3 scripts/viking_bridge.py checkpoint
python3 scripts/session_compactor.py --from-checkpoint --output HANDOVER.md
```

**4. 派一题 / 过 Gate**

```bash
python3 scripts/statem_supervisor.py \
  --runbook runbook.yaml \
  --sprint-goal "<一道小题>" \
  --max-retries 3

# 短冲刺 DONE ≠ 阶段完成。空 checkpoint 会被拒绝。
python3 scripts/statem_driver.py --advance --gate-check
# 紧急跳过：python3 scripts/statem_driver.py --advance --force
```

`statem_supervisor.py` 会 `sprint-reset`，把完整 prompt 写到 `.viking_state/sprint_prompt.txt`，stdout 只打 `DISPATCH_PROMPT` 一行。主控把这一行交给 `subagent`，不要 cat prompt 文件。子进程 exit 0 **不会**自动推进阶段。

---

## 8 步探索超时

Bridge 硬限制：一道题在上下文胀起来之前停，并且**停之前工作集已经在磁盘上**。它数的不是宿主 Agent 的对话轮次。

### 计什么

| 计入（上限 8） | 不计入 |
|---|---|
| `run` / `grep` / `ocr` | `note` / `checkpoint` / `doctor` / `ping` / `sprint-reset` / `sprint-status` / `ask-ui` / `sprint-done` |
| | 裸 `bash`、`hdiutil`、`lipo`、`read_file` |
| | 主控的 `statem_driver` / `statem_supervisor` |

计数器：`.viking_state/sprint_budget`。不经 supervisor 派子 Agent 时，计数会跨会话累加，需手动：

```bash
python3 scripts/viking_bridge.py sprint-reset
python3 scripts/viking_bridge.py sprint-status    # 0/8 … 8/8
```

> 子 Agent 若全程裸 bash，DSH 步数可以到 14、15，**超时不会触发**。要生效，探索必须走 `viking_bridge.py run|grep|ocr`。

### 一次冲刺里

| 第几次探索 | 行为 | 退出码 | 命令执行吗 |
|---|---|---|---|
| 1–4 | 正常跑，命中写入 `discoveries.jsonl` | 命令自己的 | 会 |
| 5 | 正常跑，黄牌：下次进入 drain | 命令自己的 | 会 |
| 6–7 | Drain：拒绝探索，提示立刻 `note` | **18** | 不会 |
| 8 | Yield：先结晶 checkpoint / HANDOVER，再让权 | **20** | 不会 |

主控见到 18 / 20 或 `SPRINT_STATUS: YIELD`：**不要** `--advance`。读 `next_action`，再派下一题。

子 Agent 最后一条命令必须是 `viking_bridge.py sprint-done`，它会打印下面四行；closing message 只能是这四行（宿主会把 closing 全文拼进主控）：

```
SPRINT_STATUS: DONE|YIELD|FAIL
CONFIRMED: ...
REJECTED: ...
NEXT: ...
```

### 怎么验证超时真的在工作

```bash
python3 scripts/viking_bridge.py sprint-reset
python3 scripts/viking_bridge.py sprint-status          # 0/8
# 同一条 grep 重复 8 次，每次后再 sprint-status
python3 scripts/viking_bridge.py grep \
  --uri "viking://knowledge/<project>/disasm/main.asm" \
  --pattern "Unlicensed"
```

预期：1–5 有 grep 结果；6–7 出现 `SPRINT DRAIN` 且 exit 18；第 8 次 `SPRINT_STATUS: YIELD`、exit 20、`checkpoint.json` 已更新。八次都是裸 bash 则一直停在 `0/8`。

---

## 破解红线（和 8 步分开）

- **主二进制第一。** 不要在第三方 SDK（`Paddle.framework`、Sparkle）上死磕。Pro 开关在应用自己的 Swift 状态机里。
- **禁止裸跑大输出。** `lldb` / `objdump` / `otool` / `strings` / hex dump 走 `viking_bridge.py run`。禁止把 `xxd` 贴进对话。
- **本机架构优先。** Universal 二进制第一轮只做 `uname -m`（Apple Silicon 上即 arm64），过 Gate 再镜像 x86_64。
- **强杀旧进程。** 补丁、重签、拉起测试前用 `pkill -9` / `killall -9`，不要只发 SIGTERM。
- **多工作区隔离。** 启动目标 App 前清掉其它目录里的同名进程，避免 LaunchServices 串台。
- **调试重签。** LLDB 测试必须带 `get-task-allow` + `disable-library-validation` 的 entitlements，禁止裸 `codesign -s -`。
- **UI 必须人验。** 一次 `ask-ui`。禁止自动 open + Cmd+, + 截屏。空 OCR 不是崩溃。
- **错误分类。** `SIGILL` / 未授权 UI / 文件占用 → 注入负向约束后最多重建 3 次；SIP / sudo 密码 / 缺 DMG / 守护进程挂了 → 停下来问人。

任务 `completed` 时，成功经验会追加到 `viking://memory/recipes/reverse_engineering.md`，下次 `workspace_init.py` 自动注入。

---

## 对话示例

**新破解**

> 使用 viking-state-workflow 监督模式开始新任务：逆向分析 `TargetApp.dmg` 的 Pro 授权，交给我破解版 app。

Agent：`doctor` → `workspace_init --type reverse_engineering` → 当前阶段只出一道小题（例如确认主二进制路径）→ `statem_supervisor.py --sprint-goal "..."`。Gate 未过就派下一题，不把整个阶段交给一个人。

**续跑**

> 使用 viking-state-workflow 监督模式，继续完成当前任务。

Agent：读 `AGENTS.md` + `checkpoint.json` + `runbook.yaml` → 用 `next_action` 派下一冲刺。

**失败后的自愈**（同一阶段的下一冲刺，不是自动 `--advance`）：子 Agent `SPRINT_STATUS: FAIL` → 主控把负向约束写入 checkpoint → 派下一任。Gate 真过了才 `--advance --gate-check`。

---

## 仓库结构

```
viking-state-workflow/
├── SKILL.md
├── README.md / README_CN.md
├── LICENSE
├── scripts/
│   ├── workspace_init.py       # 生成破解用 AGENTS.md + runbook.yaml
│   ├── viking_bridge.py        # doctor / run / grep / ocr / note / 8 步超时
│   ├── working_set.py          # checkpoint、discoveries、sprint_budget
│   ├── statem_driver.py        # 阶段状态与 Gate
│   ├── statem_supervisor.py    # 合成短冲刺 prompt、reset 预算
│   ├── session_compactor.py    # 从 checkpoint 渲染 HANDOVER.md
│   ├── mac_ocr.swift
│   ├── viking_env.sh
│   └── bin/                    # lldb / objdump / otool 垫片（超 40 行转存 VFS）
└── templates/
```

兼容 DSH、Hermes、OpenCode、Claude Code、Antigravity、Aider 等。主控调度写在短的 `SKILL.md`（给本地 27B）；项目红线在生成的 `AGENTS.md`，子 Agent 规则在 `.viking_state/sprint_prompt.txt`。用 skills-manager 同步。

---

## 开源协议

[Apache License 2.0](LICENSE)
