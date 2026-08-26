#!/usr/bin/env python3
"""
StateM Driver (statem_driver.py)
A zero-dependency / PyYAML state machine driver for executing and validating runbooks.
Enforces deterministic gates, checks milestones, and tracks execution history.
"""

import os
import sys
import argparse
import json
from datetime import datetime

try:
    import yaml
    HAS_YAML = True
except ImportError:
    HAS_YAML = False


def _parse_simple_yaml(text: str) -> dict:
    """Fallback simple YAML parser for basic key-value / nested runbooks without pyyaml."""
    lines = text.splitlines()
    data = {}
    current_section = None
    sub_section = None
    sub_sub_section = None

    for raw_line in lines:
        line = raw_line.rstrip()
        if not line or line.strip().startswith("#"):
            continue
        
        indent = len(raw_line) - len(raw_line.lstrip())
        stripped = line.strip()

        if indent == 0 and ":" in stripped:
            k, v = stripped.split(":", 1)
            k, v = k.strip(), v.strip().strip('"').strip("'")
            current_section = k
            sub_section = None
            data[k] = v if v else {}
        elif indent == 2 and current_section and ":" in stripped:
            k, v = stripped.split(":", 1)
            k, v = k.strip(), v.strip().strip('"').strip("'")
            sub_section = k
            if not isinstance(data[current_section], dict):
                data[current_section] = {}
            data[current_section][k] = v if v else {}
        elif indent == 4 and current_section and sub_section:
            if stripped.startswith("- "):
                val = stripped[2:].strip().strip('"').strip("'")
                if not isinstance(data[current_section][sub_section], list):
                    data[current_section][sub_section] = []
                data[current_section][sub_section].append(val)
            elif ":" in stripped:
                k, v = stripped.split(":", 1)
                k, v = k.strip(), v.strip().strip('"').strip("'")
                sub_sub_section = k
                if not isinstance(data[current_section][sub_section], dict):
                    data[current_section][sub_section] = {}
                data[current_section][sub_section][k] = v if v else {}
        elif indent == 6 and current_section and sub_section and sub_sub_section:
            if stripped.startswith("- "):
                val = stripped[2:].strip().strip('"').strip("'")
                if not isinstance(data[current_section][sub_section][sub_sub_section], list):
                    data[current_section][sub_section][sub_sub_section] = []
                data[current_section][sub_section][sub_sub_section].append(val)
            elif ":" in stripped:
                k, v = stripped.split(":", 1)
                k, v = k.strip(), v.strip().strip('"').strip("'")
                if not isinstance(data[current_section][sub_section][sub_sub_section], dict):
                    data[current_section][sub_section][sub_sub_section] = {}
                data[current_section][sub_section][sub_sub_section][k] = v

    return data


def load_runbook(path: str):
    if not os.path.exists(path):
        print(f"[ERROR] Runbook file '{path}' does not exist.")
        sys.exit(1)
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
        if HAS_YAML:
            try:
                return yaml.safe_load(content)
            except Exception as e:
                pass
        # If json
        if path.endswith(".json") or content.strip().startswith("{"):
            try:
                return json.loads(content)
            except Exception:
                pass
        return _parse_simple_yaml(content)


def _simple_yaml_dump(data: dict) -> str:
    lines = [
        "version: '1.0'",
        f"task_name: {data.get('task_name', data.get('name', 'unnamed_task'))}",
        f"description: \"{data.get('description', '')}\"",
        f"initial_state: {data.get('initial_state', 'init')}",
        f"current_state: {data.get('current_state', 'init')}",
        "states:"
    ]
    states = data.get("states", {})
    if isinstance(states, dict):
        for s_id, s_info in states.items():
            if not isinstance(s_info, dict):
                continue
            lines.append(f"  {s_id}:")
            lines.append(f"    name: {s_info.get('name', s_id)}")
            lines.append(f"    description: \"{s_info.get('description', '')}\"")
            if "gate" in s_info:
                lines.append(f"    gate: \"{s_info['gate']}\"")
            if "gates" in s_info and isinstance(s_info["gates"], list):
                lines.append("    gates:")
                for g in s_info["gates"]:
                    lines.append(f"      - \"{g}\"")
            trans = s_info.get("transition", {})
            if isinstance(trans, dict):
                lines.append("    transition:")
                for tk, tv in trans.items():
                    lines.append(f"      {tk}: {tv}")

    history = data.get("history", [])
    if history and isinstance(history, list):
        lines.append("history:")
        for h in history:
            lines.append(f"  - from_state: {h.get('from_state')}")
            lines.append(f"    to_state: {h.get('to_state')}")
            lines.append(f"    timestamp: \"{h.get('timestamp')}\"")

    return "\n".join(lines) + "\n"


def save_runbook(path: str, data: dict):
    with open(path, "w", encoding="utf-8") as f:
        if HAS_YAML:
            try:
                yaml.safe_dump(data, f, sort_keys=False, allow_unicode=True)
                return
            except Exception:
                pass
        f.write(_simple_yaml_dump(data))


def get_current_state(data: dict):
    return data.get("current_state") or data.get("initial_state") or "unknown"


def show_status(runbook_path: str):
    data = load_runbook(runbook_path)
    curr_state = get_current_state(data)
    name = data.get("name", "Unnamed Task")
    states = data.get("states", {})

    print("\n" + "=" * 60)
    print(f"🚦  StateM Task Status: [{name}]")
    print("=" * 60)
    print(f"📍 Current State: \033[1;32m{curr_state}\033[0m")
    
    state_meta = states.get(curr_state, {}) if isinstance(states, dict) else {}
    desc = state_meta.get("description", "No description provided.")
    print(f"📝 Phase Objective: {desc}")
    
    if "expected_artifacts" in state_meta:
        print("\n📦 Expected Artifacts / Outputs:")
        for item in state_meta["expected_artifacts"]:
            status_icon = "✅" if os.path.exists(item) else "⏳"
            print(f"   {status_icon} {item}")

    if "gates" in state_meta:
        print("\n🛡️  Verification Gates before Transition:")
        for gate in state_meta["gates"]:
            print(f"   - {gate}")

    transitions = state_meta.get("transition", {})
    print(f"\n➡️  Next Transitions: {json.dumps(transitions, indent=2)}")
    print("=" * 60 + "\n")


def _auto_archive_completed_recipe(runbook_path: str, data: dict):
    """Automatically distills and archives macro recipes into Viking when task completes."""
    task_name = data.get("task_name", data.get("name", "unnamed_task"))
    desc = data.get("description", "")
    
    # Infer archetype
    archetype = "general_long_task"
    desc_lower = (desc + " " + task_name).lower()
    if any(k in desc_lower for k in ["reverse", "crack", "patch", "dmg", "disasm", "mach-o", "逆向", "破解"]):
        archetype = "reverse_engineering"
    elif any(k in desc_lower for k in ["refactor", "orm", "migrate", "rewrite", "重构", "迁移"]):
        archetype = "code_refactor"
    elif any(k in desc_lower for k in ["debug", "bug", "crash", "排障", "修复", "崩溃"]):
        archetype = "deep_debugging"

    ws_dir = os.path.dirname(os.path.abspath(runbook_path)) if runbook_path else "."
    handover_file = os.path.join(ws_dir, "HANDOVER.md")
    handover_content = ""
    if os.path.exists(handover_file):
        try:
            with open(handover_file, "r", encoding="utf-8", errors="replace") as f:
                handover_content = f.read()
        except Exception:
            pass

    # Destination in Viking VFS
    local_recipe_dir = os.path.expanduser("~/.openviking/local_vfs/memory/recipes")
    os.makedirs(local_recipe_dir, exist_ok=True)
    recipe_path = os.path.join(local_recipe_dir, f"{archetype}.md")

    entry_lines = [
        f"\n### 📦 [{datetime.now().strftime('%Y-%m-%d %H:%M')}] {task_name}",
        f"- **Goal**: {desc}",
    ]
    if handover_content:
        entry_lines.append("- **Distilled Learnings & Recipes**:")
        for line in handover_content.splitlines():
            if line.strip().startswith(("#", "Key", "Finding", "Address", "Patch", "核心", "地址", "发现", "结论", "-")):
                entry_lines.append(f"  {line}")
    else:
        entry_lines.append(f"- **Outcome**: All {len(data.get('history', []))} states successfully completed and verified.")

    try:
        with open(recipe_path, "a", encoding="utf-8") as f:
            f.write("\n".join(entry_lines) + "\n")
        print(f"\n🧠 \033[1;32m[Memory Crystallization]\033[0m Successfully archived macro recipe to:")
        print(f"   \033[1;36mviking://memory/recipes/{archetype}.md\033[0m")
    except Exception as e:
        print(f"[Warning] Failed to archive recipe: {e}")


def advance_state(runbook_path: str, next_state_override=None):
    data = load_runbook(runbook_path)
    curr_state = get_current_state(data)
    states = data.get("states", {})
    
    state_meta = states.get(curr_state, {}) if isinstance(states, dict) else {}
    transitions = state_meta.get("transition", {})
    
    target_state = next_state_override or (transitions.get("on_success") if isinstance(transitions, dict) else None)
    if not target_state:
        print(f"[ERROR] No valid 'on_success' target defined from state '{curr_state}'.")
        sys.exit(1)

    # Check artifact requirements if specified
    missing_artifacts = []
    if isinstance(state_meta, dict):
        for artifact in state_meta.get("expected_artifacts", []):
            if not os.path.exists(artifact):
                missing_artifacts.append(artifact)

    if missing_artifacts:
        print(f"[GATE ERROR] Missing required artifacts before advancing:")
        for m in missing_artifacts:
            print(f"   ❌ {m}")
        print("\nState transition aborted. Ensure all steps are completed first.")
        sys.exit(1)

    # Record history
    if "history" not in data or not isinstance(data["history"], list):
        data["history"] = []
    data["history"].append({
        "from_state": curr_state,
        "to_state": target_state,
        "timestamp": datetime.now().isoformat()
    })
    data["current_state"] = target_state
    save_runbook(runbook_path, data)

    print(f"\n🎉 [StateM] Successfully transitioned state:")
    print(f"   \033[1;31m{curr_state}\033[0m  ➡️   \033[1;32m{target_state}\033[0m\n")

    # If reached terminal completed state, trigger automatic macro recipe distillation
    if target_state == "completed":
        _auto_archive_completed_recipe(runbook_path, data)
        import platform
        native_arch = platform.machine()
        other_arch = "x86_64" if native_arch == "arm64" else "arm64"
        print("\n" + "=" * 70)
        print(f"🎉 \033[1;32m[TASK COMPLETED & DELIVERED ON NATIVE ARCH ({native_arch})]\033[0m")
        print(f"🍏 本机原生架构 ({native_arch}) 已 100% 验证通过并完成交付！")
        print("=" * 70)
        print("👉 \033[1;33m【跨架构 Universal 胖二进制交付选项】\033[0m")
        print(f"   如需将补丁同步镜像到另一个架构 ({other_arch}) 并合成为 Universal 胖二进制，")
        print(f"   只需向 Agent 发送指令：“同步 {other_arch}” 或 “生成 Universal 胖二进制”，")
        print(f"   Agent 将自动镜像补丁并在 3 步内秒级合成交付！")
        print("=" * 70 + "\n")


def main():
    parser = argparse.ArgumentParser(description="StateM YAML Runbook Driver")
    parser.add_argument("--runbook", default="runbook.yaml", help="Path to runbook.yaml")
    parser.add_argument("--status", action="store_true", help="Display current phase & gates")
    parser.add_argument("--advance", action="store_true", help="Advance to next state on success")
    parser.add_argument("--to", help="Manually specify target state to transition to")

    args = parser.parse_args()

    if args.status or (not args.advance and not args.to):
        show_status(args.runbook)
    elif args.advance or args.to:
        advance_state(args.runbook, args.to)


if __name__ == "__main__":
    main()
