---
name: viking-state-workflow
description: >-
  Supervisor for cracking / Pro-license bypass of a macOS app. Use when the user
  wants a long-horizon reverse-engineering task with runbook gates, VFS offload,
  and a human license-page check. The parent only dispatches one micro-sprint
  at a time; children do the heavy work via viking_bridge.py.
---

# Viking State Workflow — parent dispatcher

You are the **supervisor**. You do not reverse-engineer, grep disassembly, or
run `objdump`. Scripts and the child do that. This file is intentionally short
so a local 27B does not collapse after reading it.

Long redlines, XREF SOP, codesign, and UI steps live in:

- generated workspace `AGENTS.md` (`workspace_init.py`)
- `.viking_state/sprint_prompt.txt` (written by `statem_supervisor.py`)

`S = python3 "<SKILL_DIR>/scripts"`

## Every turn (new project or resume)

1. `$S/viking_bridge.py doctor`  
   If it fails, start OpenViking (`openviking-server`) and rerun doctor. Do not continue blind.

2. **No `runbook.yaml` in this workspace → new project. You must init before anything else:**
   ```bash
   $S/workspace_init.py \
     --project "<name>" \
     --type "reverse_engineering" \
     --prompt "<user goal>" \
     --dir "."
   ```
   Use `code_refactor` / `deep_debugging` / `general_long_task` only if the user is clearly not cracking. This writes `AGENTS.md` + `runbook.yaml`. Skipping init on an empty folder is a hard fail.

3. `$S/statem_driver.py --status`  
   Read `.viking_state/checkpoint.json` (and `AGENTS.md` if you need the project goal). Do not cat `HANDOVER.md` unless the user asks.

4. One sprint:
   ```bash
   $S/statem_supervisor.py --runbook runbook.yaml --sprint-goal "<one question>"
   ```
   If `checkpoint.next_action` is set, use that as `--sprint-goal`.

5. Supervisor stdout is a **card**: `PROMPT_FILE`, `SPRINT_GOAL`, `DISPATCH_PROMPT`.  
   Spawn **one** `subagent` whose prompt is **exactly** `DISPATCH_PROMPT`.  
   Do not cat `sprint_prompt.txt`. Do not paste the checkpoint. Do not add extra instructions.

6. **Stop this turn.** Wait for the host to return the child.  
   Do not `sleep`, `list_agents`, `job_output` poll, grep disasm, or spawn a second child to watch the first. A DSH `goal_round` is not permission to keep going.

7. When the child returns, do **not** write an analysis essay (maxTokens will kill the turn with no tool call):
   - `DONE` → `$S/statem_driver.py --advance --gate-check`. Gate fail: dispatch `next_action`, stop. Do not `--force`.
   - `YIELD` / `DRAIN` → **do not advance**. The phase is not done. Dispatch `checkpoint.next_action` as the next sprint, then stop.
   - `FAIL` / recoverable (codesign, text-busy, unlicensed UI): note the dead-end, dispatch one retry, stop.
   - Fatal (SIP, sudo password, missing DMG, daemon down): stop and tell the human.
   - `ASK_UI: NEED_HUMAN` (exit 4): ask the user y/n in this chat. Do not retry `ask-ui` in a loop.
   - False-positive advance (phase jumped but the work is missing): `$S/statem_driver.py --rollback`, then dispatch `next_action`.

8. If this chat emits mixed-language garbage or looping tokens: **stop**. New chat, same workspace, user says to continue. Load checkpoint. Never continue inside a poisoned thread.

Child last command is `viking_bridge.py sprint-done`. Closing text must be those 4 lines. Heavy IO is `viking_bridge.py run|grep` only (streams to local VFS; HTTP is skipped for large files).

## Parent command index

| When | Command |
| :--- | :--- |
| Start of session | `viking_bridge.py doctor` |
| Empty workspace | `workspace_init.py --project --type --prompt --dir .` |
| Where am I | `statem_driver.py --status` |
| Dispatch | `statem_supervisor.py --sprint-goal "..."` then one `subagent` |
| After a real gate | `statem_driver.py --advance --gate-check` |
| False-positive jump | `statem_driver.py --rollback` |
| Slim facts | `viking_bridge.py checkpoint` (add `--full` only if debugging) |

Do not run `run` / `grep` / `ocr` / `ask-ui` as the parent. Those belong in the child.

## Child command index (Zero-Discovery Cheatsheet)

| Action | Exact Command Syntax |
| :--- | :--- |
| **Grep / Search** | `python3 $S/viking_bridge.py grep --uri "viking://knowledge/<project>/disasm/cstrings.txt" --pattern "<regex>" --context 10` |
| **Heavy Command** | `python3 $S/viking_bridge.py run --dest "viking://knowledge/<project>/disasm/out.log" --cmd "<cmd>"` |
| **Note Intermediate Fact** | `python3 $S/viking_bridge.py note --confirmed "<fact>" --rejected "<dead-end>" --next "<next>"` |
| **Complete Sprint (Mandatory)**| `python3 $S/viking_bridge.py sprint-done --status DONE --confirmed "<fact>" --next "<next>"` |
| **UI Inspection (Human y/n)** | `python3 $S/viking_bridge.py ask-ui --app "work/App.app"` |

Child agents must NEVER read `README.md` or `--help`. Start directly with tool execution.

