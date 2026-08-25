# Viking State Workflow (维京状态机工作流)

[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)
[![Python](https://img.shields.io/badge/Python-3.9+-green.svg)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/Platform-macOS%20%7C%20Linux-lightgrey.svg)]()
[![Status](https://img.shields.io/badge/Status-Active-brightgreen.svg)]()

[English](README.md) | [中文说明](README_CN.md)

**Viking State Workflow** 是专为 AI Agent（智能体）设计的长流程复杂任务执行框架。通过融合 **[StateM](https://github.com/henryqin1997/statem)**（确定性状态机与声明式 YAML Runbook）、**[OpenViking](https://github.com/volcengine/OpenViking)**（字节跳动火山引擎开源的分层 VFS 上下文数据库）以及 **macOS 原生 Vision OCR**（零显存文字识别），彻底杜绝大模型上下文爆炸、消除本地模型显存溢出（OOM）崩溃，并为多智能体提供结构化、可接力的执行体系。

---

## 🔗 上游开源项目与核心依赖引用

- **[OpenViking](https://github.com/volcengine/OpenViking)** (`volcengine/OpenViking`)：专为 AI Agent 设计的开源分层上下文数据库与虚拟文件系统 (`viking://`)。
- **[StateM](https://github.com/henryqin1997/statem)** (`henryqin1997/statem`)：用于驱动 Agent 执行声明式 Runbook 的轻量级确定性状态机引擎。

---

## 🎯 核心解决的痛点

在执行长周期、高复杂度的 Agent 任务时（例如：二进制逆向分析、大型代码库重构、全栈深度排障）：
- 随着多轮对话进行，工具调用产生的海量输出（如 `objdump` 反汇编、堆栈追踪、构建日志、多模态图片）在线性累积。
- 对话上下文剧烈膨胀（单会话高达 10万~30万 Tokens），极易触发 `400 Context Length Exceeded` 或本地 LLM 显存 OOM 崩溃。
- 会话死锁导致进度丢失，开发者不得不耗费大量精力手动提炼历史并重启对话。

---

## 🏗️ 架构设计

```
┌─────────────────────────────────────────────────────────────┐
│  Agent 执行层 (多智能体通用支持)                            │
│  [ DSH ] / [ Hermes ] / [ OpenCode ] / [ Claude Code ] ... │
└──────────────────────────────┬──────────────────────────────┘
                               │ 结构化指令与阶段门禁校验
┌──────────────────────────────▼──────────────────────────────┐
│  状态与控制层 (StateM)                                      │
│  - 基于 YAML 的声明式 Runbook 状态机                        │
│  - 严格的状态流转门禁 (Gate Check)                          │
│  - 检查点快照与自动回滚处理                                 │
└──────────────────────────────┬──────────────────────────────┘
                               │ VFS 查询与长日志截流转存
┌──────────────────────────────▼──────────────────────────────┐
│  上下文、记忆与视觉层 (OpenViking + 原生 Vision OCR)        │
│  - 重型输出自动拦截外挂 (`viking://`)                       │
│  - macOS 原生 Vision OCR (零显存占用 / 零 Token 消耗)       │
│  - L0/L1 渐进式发现 (先输出摘要，按需取用)                  │
│  - 精准代码切片检索 (`viking_bridge.py grep`)               │
│  - 持久化会话记忆提炼与无缝接力                             │
└─────────────────────────────────────────────────────────────┘
```

---

## 📁 仓库目录结构

```bash
viking-state-workflow/
├── SKILL.md                          # Agent 技能规范标准 (兼容 Antigravity 与 Skills-Manager)
├── README.md                         # 英文文档
├── README_CN.md                      # 中文文档
├── LICENSE                           # Apache-2.0 开源协议
├── scripts/
│   ├── workspace_init.py             # 通用工作区初始化脚手架 (支持任意任务类型)
│   ├── viking_bridge.py              # OpenViking VFS 客户端、前置体检与 capture-ocr 自动化
│   ├── statem_driver.py              # 纯标准库零依赖 StateM 状态机驱动引擎
│   ├── statem_supervisor.py          # 串行 Subagent 编排监督器与错误分类决策引擎
│   ├── session_compactor.py          # 会话状态提炼与主动接力工具
│   ├── mac_ocr.swift                 # 原生 macOS Vision OCR 提取器 (零依赖 / 零显存)
│   ├── viking_env.sh                 # 环境变量注入脚本 (激活透明拦截垫片)
│   └── bin/                          # 透明物理拦截垫片 (lldb, objdump, otool)
└── templates/
    ├── runbook_template.yaml         # 生产级 YAML Runbook 状态机模板
    └── ov.conf.template              # OpenViking 配置文件模板
```

---

## 🚀 快速上手与零门槛自动引导

### 🌟 零门槛使用体验（对普通用户只需一句话）
用户完全不需要记忆任何底层命令行。只需对任意 AI Agent 发送一句话：
> **“使用 `viking-state-workflow` 技能开始一个新任务：[描述你的任务目标]”**

Agent 将**全自动依次执行 4 步无感初始化闭环**：
1. `viking_bridge.py doctor` ➔ 自动进行前置体检，自愈探测服务端端口（如 1933）与鉴权凭证；
2. `workspace_init.py` ➔ 自动识别任务类型（逆向分析 `reverse_engineering`、代码重构 `code_refactor`、深度排障 `deep_debugging`、通用任务 `general_long_task`），生成定制版 `AGENTS.md` 与 `runbook.yaml`；
3. `statem_driver.py --status` ➔ 展示初始状态与阶段 Gate 要求；
4. 无需等待二次指令，**直接开始执行阶段 1 的具体开发与分析工作！**

---

### 🔧 开发者与底层工具链速查指南 (Manual Reference)

#### 1. 启动前置体检 (Mandatory Pre-flight Check)
自动验证 OpenViking 服务连通性、鉴权 Key 与端口状态（如 1933）：
```bash
python3 scripts/viking_bridge.py doctor
```

#### 2. 自动合成新项目工作区 (Workspace Init)
为任意类型的工程任务生成专属的 `AGENTS.md` 和状态机 `runbook.yaml`：
```bash
python3 scripts/workspace_init.py \
  --project "<项目名称>" \
  --type "reverse_engineering|code_refactor|deep_debugging|general_long_task" \
  --prompt "<任务目标描述>" \
  --dir "."
```

#### 3. 查看当前任务状态与门禁
```bash
python3 scripts/statem_driver.py --status
```

#### 4. 重型输出命令拦截转存 (VFS Offloading)
自动拦截超过 40 行的命令输出，将其转存至 OpenViking 虚拟文件系统，彻底防止上下文爆炸：
```bash
python3 scripts/viking_bridge.py run \
  --dest "viking://knowledge/myproject/disasm.asm" \
  --cmd "objdump -d /path/to/binary"
```
*终端仅打印 L0 前后 10 行预览及行数统计，完整大文件安全存放于 Viking。*

#### 5. 精准代码切片按需检索 (Grep Snippet)
只提取目标函数或关键词前后 10~15 行代码进入上下文，无需全量读取：
```bash
python3 scripts/viking_bridge.py grep \
  --uri "viking://knowledge/myproject/disasm.asm" \
  --pattern "目标函数或符号名" \
  --context 15
```

#### 6. 一体化 GUI 界面验证与 Vision OCR (零显存)
自动激活 App、窗口强制置顶抗遮挡、AppleScript 打开设置、截图并调用原生 Vision OCR 识别文字，支持人机协同超时自愈：
```bash
python3 scripts/viking_bridge.py capture-ocr \
  --app "work/MyApp.app" \
  --dest "viking://knowledge/myproject/ocr/ui.txt" \
  --ask-user \
  --timeout 600
```

#### 7. 推进阶段状态 (单 Agent 模式)
验证当前阶段 Gate 门禁达成后，推进至下一阶段：
```bash
python3 scripts/statem_driver.py --advance
```

#### 8. 串行 Subagent 编排与智能自愈 (多 Agent 监督模式)
自动调度轻量串行子智能体，执行阶段任务，并基于错误分类学进行智能自愈：
```bash
python3 scripts/statem_supervisor.py \
  --runbook runbook.yaml \
  --max-retries 3
```
* **自愈机制**：遇到逻辑错误、补丁崩溃（`SIGILL`/`SIGSEGV`）、OCR 显示未激活、文件占用等可恢复错误时，自动注入失败原因并**重建 Subagent 重试（最多 3 次）**；
* **安全熔断**：遇到系统权限（SIP）、缺失物料、基建宕机等致命错误时，**立即停机并请求人工介入**。

#### 9. 主动会话压缩与无缝接力 (Session Handover)
当多轮会话累积过长（> 20k Tokens）时，将关键技术发现提炼为极简报告（< 500 Tokens）：
```bash
python3 scripts/session_compactor.py \
  --project "myproject" \
  --milestones "完成第一阶段目标; Gate 门禁验证通过" \
  --discoveries "锁定核心地址 0x1004ffa38; 确认真 NOP 为 1F 20 03 D5" \
  --next-actions "对目标二进制写入 4 字节补丁并重签名" \
  --output HANDOVER.md
```
在新会话（Clean New Chat）中直接加载 `HANDOVER.md`，即可满血继续推进！

---

## 🛡️ 双层上下文防爆防御体系

1. **第一层：认知与规范红线 (`SKILL.md`)**：最高安全红线，严禁裸跑 `lldb`、`objdump`、`otool`、`strings` 或超长测试追踪日志。
2. **第二层：物理拦截垫片 (`scripts/bin/`)**：在操作系统层面提供透明代理，即便 Agent 偶尔裸跑命令，垫片也会在底层自动捕获超过 40 行的内容并转存至 OpenViking。

---

## 🤝 多智能体生态兼容性

本框架与特定 Agent 完全解耦，开箱即用支持各大主流智能体：
- **DSH (DeepSeek Harness)**
- **Hermes Agent**
- **OpenCode**
- **Claude Code**
- **Google Antigravity**
- **Aider / OpenClaw**

---

## 📄 开源协议

本项目采用 [Apache License 2.0](LICENSE) 开源协议。
