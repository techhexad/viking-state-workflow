# Viking State Workflow

[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)
[![Python](https://img.shields.io/badge/Python-3.9+-green.svg)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/Platform-macOS-lightgrey.svg)]()
[![Status](https://img.shields.io/badge/Status-Active-brightgreen.svg)]()

[English](README.md) | [中文说明](README_CN.md)

macOS app **cracking / Pro-license bypass** on a local machine with limited RAM, VRAM, and context. Frozen playbook: unpack → disassemble into OpenViking → String-XREF the license gate in the **main binary** → patch & re-sign → OCR-verify the Pro UI.

Progress lives in a YAML runbook. Heavy dumps go to `viking://`. Facts go to `checkpoint.json`. Each child agent answers **one** question.

Upstream: [OpenViking](https://github.com/volcengine/OpenViking) · [StateM](https://github.com/henryqin1997/statem)

This skill is not a general long-task OS. Do not use it for refactors, product apps, or incident debugging.

---

## Three layers (do not mix these up)

```
runbook phase (advance only after the Gate passes)
    └── many micro-sprints (one question each)
            └── at most 8 viking_bridge explore calls per sprint (run/grep/ocr)
                    └── facts land in .viking_state/checkpoint.json
```

| Term | Meaning | Who moves it |
|---|---|---|
| **Phase** | unpack → disasm → find the gate → patch & sign → OCR verify | Parent runs `--advance --gate-check` after the Gate is truly met |
| **Micro-sprint** | The child answers only `checkpoint.next_action` | Parent dispatches; child stops after `SPRINT_STATUS` |
| **8-call timeout** | Cap on `viking_bridge` explore calls in one sprint | **Enforced by the bridge**, not by the host's `step/start` counter |

Machine relay is `.viking_state/checkpoint.json` + `discoveries.jsonl`. `HANDOVER.md` is a human projection of that file.

---

## One-liner usage

Empty workspace, new chat:

> Use viking-state-workflow in supervisor mode to start a new task: reverse engineer `/path/to/App.dmg` Pro checks and deliver a cracked app.

Workspace that already has `runbook.yaml`:

> Use viking-state-workflow in supervisor mode to continue and finish the current task.

You do not need to mention micro-sprints, the 8-call cap, or checkpoint. The agent should: `doctor` → `workspace_init --type reverse_engineering` if there is no runbook → one question for the current phase → dispatch a child.

The parent only decomposes questions, reads the checkpoint, and judges Gates. It must not finish a whole phase itself.

After `statem_supervisor.py --sprint-goal` + one `subagent` call, **stop the turn**. Do not `sleep`, `list_agents`, grep a 200MB disasm, or spawn a watcher child. Local GPU runs one inference at a time — a watcher child stalls the sprint. Confirmed facts are clipped to 240 characters so a huge `note` cannot poison the next sprint. If this chat starts emitting mixed-language garbage, kill it and resume from `.viking_state/checkpoint.json` in a new chat — DSH will not detect degeneration.

DSH host knobs (not part of this repo): keep `streamIdleTimeoutMs` on the order of minutes, not 30; cap `maxTokens` (e.g. 2048) so one stuck generation cannot dump 32k garbage into history.

---

## Cracking playbook

Generated `runbook.yaml` phases:

1. **unpack_and_extract** — mount the DMG, slice the native thin binary (`uname -m` first)
2. **symbol_and_disasm** — symbols, strings, full disassembly into `viking://`
3. **analyze_gating** — String XREF in the **main binary** (not Paddle / Sparkle)
4. **craft_patch** — flip the branch, rebuild fat binary if needed, re-sign
5. **verify_and_deliver** — human opens the license page and answers `ask-ui` y/n

String XREF SOP (phase 3):

1. Find UI strings (`Pro License`, `Activated`, `Trial Expired`, `Unlicensed`) in `__cstring`
2. `viking_bridge.py grep` for `adrp` / `ldr` xrefs to that address
3. Walk 5–10 instructions up; the split is a `cbz` / `cbnz` / `tbz` / `b.eq`
4. Rewrite the branch so it always takes the Pro path

---

## What appears in a workspace

```
<project>/
├── runbook.yaml                 # cracking phases and Gates
├── AGENTS.md                    # redlines and commands
├── HANDOVER.md                  # human view of the checkpoint
├── .viking_state/
│   ├── checkpoint.json          # confirmed facts / rejected paths / next_action
│   ├── discoveries.jsonl        # append-only tool hits
│   └── sprint_budget            # explore counter for this sprint
└── work/                        # unpacked app, thin binaries, patched .app
```

Disasm, traces, and OCR live at `viking://knowledge/<project>/`, not in the chat.

---

## Command map

Scripts live under the skill's `scripts/`. In a real workspace, use the absolute paths from `AGENTS.md`.

**1. Health check and scaffold**

```bash
python3 scripts/viking_bridge.py doctor
python3 scripts/workspace_init.py \
  --project "<name>" \
  --type reverse_engineering \
  --prompt "crack <App> Pro license; deliver a patched app" \
  --dir "."
python3 scripts/statem_driver.py --status
```

**2. Explore (counts toward the 8-call cap)** — never dump `objdump` via raw bash.

```bash
python3 scripts/viking_bridge.py run \
  --dest "viking://knowledge/<project>/disasm/main.asm" \
  --cmd "objdump -d work/<binary>"

python3 scripts/viking_bridge.py grep \
  --uri "viking://knowledge/<project>/disasm/main.asm" \
  --pattern "<symbol or address>" --context 15

python3 scripts/viking_bridge.py ask-ui \
  --app "work/MyApp.app" \
  --open \
  --question "License/Pro page shows Activated or Pro? (y/n)" \
  --timeout 600
```

**3. Persist (does not count)**

```bash
python3 scripts/viking_bridge.py note \
  --confirmed "<fact>" --rejected "<dead end>" --next "<next question>"
python3 scripts/viking_bridge.py checkpoint
python3 scripts/session_compactor.py --from-checkpoint --output HANDOVER.md
```

**4. Dispatch one question / pass a Gate**

```bash
python3 scripts/statem_supervisor.py \
  --runbook runbook.yaml \
  --sprint-goal "<one question>" \
  --max-retries 3

# Sprint DONE ≠ phase complete. Empty checkpoint is rejected.
python3 scripts/statem_driver.py --advance --gate-check
# Emergency only: python3 scripts/statem_driver.py --advance --force
```

`statem_supervisor.py` resets the sprint budget, writes `.viking_state/sprint_prompt.txt`, and prints a short `DISPATCH_PROMPT`. The parent must pass **only** that one-liner to `subagent` — not the prompt file. A child exit 0 does **not** advance the runbook.

---

## 8-call exploration timeout

A bridge-level hard limit: stop one question before context bloats, and persist the working set **before** the sprint dies. It does not count host-agent conversation turns.

### What counts

| Counts (cap 8) | Does not count |
|---|---|
| `run` / `grep` / `ocr` | `note` / `checkpoint` / `doctor` / `ping` / `sprint-reset` / `sprint-status` / `ask-ui` / `sprint-done` |
| | Raw `bash`, `hdiutil`, `lipo`, `read_file` |
| | Parent `statem_driver` / `statem_supervisor` |

Counter file: `.viking_state/sprint_budget`. If you spawn a child without the supervisor, the counter keeps accumulating until:

```bash
python3 scripts/viking_bridge.py sprint-reset
python3 scripts/viking_bridge.py sprint-status    # 0/8 … 8/8
```

> If the child only uses raw bash, the host step count can reach 14–15 and **the timeout never fires**. Exploration must go through `viking_bridge.py run|grep|ocr`.

### Inside one sprint

| Explore # | Behavior | Exit | Command runs? |
|---|---|---|---|
| 1–4 | Run; hits append to `discoveries.jsonl` | command's own | yes |
| 5 | Run; yellow HUD: next call enters drain | command's own | yes |
| 6–7 | Drain: refuse exploration, demand `note` | **18** | no |
| 8 | Yield: crystallize checkpoint / HANDOVER, then yield | **20** | no |

On exit 18 / 20 or `SPRINT_STATUS: YIELD` the parent **must not** `--advance`. Read `next_action` and dispatch the next question.

Child last command is `viking_bridge.py sprint-done --status DONE|YIELD|FAIL ...`. It prints:

```
SPRINT_STATUS: DONE|YIELD|FAIL
CONFIRMED: ...
REJECTED: ...
NEXT: ...
```

That is the only allowed closing message (the host splices it into the parent).

### How to prove the timeout is firing

```bash
python3 scripts/viking_bridge.py sprint-reset
python3 scripts/viking_bridge.py sprint-status          # 0/8
# same grep, eight times; check sprint-status after each
python3 scripts/viking_bridge.py grep \
  --uri "viking://knowledge/<project>/disasm/main.asm" \
  --pattern "Unlicensed"
```

Expect grep hits on calls 1–5; `SPRINT DRAIN` + exit 18 on 6–7; `SPRINT_STATUS: YIELD` + exit 20 and an updated `checkpoint.json` on call 8. Eight raw bash calls leave the counter at `0/8`.

---

## Cracking redlines (separate from the 8-call cap)

- **Main binary first.** Do not grind third-party SDKs (`Paddle.framework`, Sparkle). The Pro flag lives in the app's own Swift state machine.
- **No raw dumps.** `lldb` / `objdump` / `otool` / `strings` / hex dumps go through `viking_bridge.py run`. Never paste `xxd` into chat.
- **Native-first.** On Universal binaries, phase 1 stays on `uname -m` (arm64 on Apple Silicon). Mirror x86_64 only after the native Gate is green.
- **Force-kill.** `pkill -9` / `killall -9` before patch, codesign, or launch — not a plain SIGTERM.
- **Multi-workspace shield.** Kill same-named processes from other directories before launching the target app.
- **Debug codesign.** LLDB tests need entitlements with `get-task-allow` + `disable-library-validation`. Do not use bare `codesign -s -`.
- **UI check is human.** `ask-ui` once. Do not auto-open + Cmd+, + screenshot. Empty OCR is not a crash.
- **Errors.** `SIGILL` / unlicensed UI / file busy → inject a negative constraint, rebuild up to 3 times. SIP / sudo password / missing DMG / daemon down → stop and ask a human.

On `completed`, recipes append to `viking://memory/recipes/reverse_engineering.md` and are injected by the next `workspace_init.py`.

---

## Prompt examples

**New crack**

> Use viking-state-workflow in supervisor mode to start a new task: reverse engineer `TargetApp.dmg` Pro checks and deliver a cracked app.

The agent: `doctor` → `workspace_init --type reverse_engineering` → one question (e.g. unpack and confirm the main binary path) → `statem_supervisor.py --sprint-goal "..."`. It keeps dispatching questions until the Gate passes. It does not hand a whole phase to one child.

**Resume**

> Use viking-state-workflow in supervisor mode to continue and finish the current task.

The agent loads `AGENTS.md` + `checkpoint.json` + `runbook.yaml` and dispatches from `next_action`.

**Heal a failure** (next sprint in the **same** phase — not an automatic `--advance`): child `SPRINT_STATUS: FAIL` → parent writes a negative constraint into the checkpoint → next child. `--advance --gate-check` only after the Gate is really met.

---

## Repository layout

```
viking-state-workflow/
├── SKILL.md
├── README.md / README_CN.md
├── LICENSE
├── scripts/
│   ├── workspace_init.py       # emit cracking AGENTS.md + runbook.yaml
│   ├── viking_bridge.py        # doctor / run / grep / ocr / note / 8-call timeout
│   ├── working_set.py          # checkpoint, discoveries, sprint_budget
│   ├── statem_driver.py        # phase + Gate
│   ├── statem_supervisor.py    # micro-sprint prompt + budget reset
│   ├── session_compactor.py    # render HANDOVER.md from checkpoint
│   ├── mac_ocr.swift
│   ├── viking_env.sh
│   └── bin/                    # lldb / objdump / otool shims (>40 lines → VFS)
└── templates/
```

Works with DSH, Hermes, OpenCode, Claude Code, Antigravity, Aider, and similar hosts. Parent dispatch lives in `SKILL.md` (kept short for local 27B). Project redlines are in generated `AGENTS.md`; child rules in `.viking_state/sprint_prompt.txt`. Sync with skills-manager.

---

## License

[Apache License 2.0](LICENSE)
