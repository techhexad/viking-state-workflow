#!/usr/bin/env python3
"""
Session Compactor (session_compactor.py)
Distills long agent conversations and heavy operational discoveries into a
compact, structured handover document, preventing context limit deadlock.
"""

import os
import sys
import argparse
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)
import working_set


MARKDOWN_TEMPLATE = """# Session Distillation & Handover Report

## 1. Meta Information
- **Project**: {project}
- **Timestamp**: {timestamp}
- **Current State**: {current_state}
- **Handover Reason**: Proactive context compaction to prevent token overflow.

---

## 2. Key Milestones Completed
{milestones_formatted}

---

## 3. Technical Discoveries & Artifacts
{discoveries_formatted}

---

## 4. Immediate Next Steps (Clean Start)
{next_actions_formatted}

---
> [!TIP]
> The next Agent session should load only this document instead of parsing full chat history.
"""


def distill(project: str, current_state: str, milestones: list, discoveries: list, next_actions: list, output_file: str):
    m_text = "\n".join([f"- [x] {m}" for m in milestones]) if milestones else "- None reported."
    d_text = "\n".join([f"- {d}" for d in discoveries]) if discoveries else "- No new technical findings."
    n_text = "\n".join([f"1. {n}" for n in next_actions]) if next_actions else "1. Continue following StateM runbook."

    report = MARKDOWN_TEMPLATE.format(
        project=project,
        timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        current_state=current_state,
        milestones_formatted=m_text,
        discoveries_formatted=d_text,
        next_actions_formatted=n_text
    )

    with open(output_file, "w", encoding="utf-8") as f:
        f.write(report)

    print(f"\n✨ [COMPACTOR] Handover report generated successfully: \033[1;32m{output_file}\033[0m")
    print(f"📊 Token footprint: ~{len(report) // 4} tokens (vs 400k+ tokens raw history)")
    return output_file


def auto_detect_state(runbook_path="runbook.yaml") -> str:
    if os.path.exists(runbook_path):
        try:
            with open(runbook_path, "r", encoding="utf-8") as f:
                for line in f:
                    if line.strip().startswith("current_state:"):
                        return line.split(":", 1)[1].strip().strip('"').strip("'")
        except Exception:
            pass
    return "in_progress"


def harvest_latest_discoveries(workspace_dir=".", output_file="HANDOVER.md") -> str:
    """
    Salvage high-value lines from the newest DSH session log and MERGE them
    into discoveries.jsonl / checkpoint.json. Never clobber confirmed facts.
    HANDOVER.md is re-rendered from the checkpoint (projection), not from the scrape.
    """
    import subprocess, glob, re, json

    session_files = glob.glob(os.path.expanduser("~/.dsh/sessions/**/session.jsonl.zstd"), recursive=True) + \
                    glob.glob(os.path.expanduser("~/.dsh/sessions/**/session.jsonl"), recursive=True)
    salvaged = []
    if session_files:
        session_files.sort(key=os.path.getmtime, reverse=True)
        latest_session = session_files[0]
        raw_lines = []
        try:
            if latest_session.endswith(".zstd"):
                proc = subprocess.run(["zstd", "-dc", latest_session], capture_output=True, text=True)
                raw_lines = proc.stdout.splitlines()
            else:
                with open(latest_session, "r", encoding="utf-8", errors="replace") as f:
                    raw_lines = f.readlines()
        except Exception:
            raw_lines = []

        keyword_pat = re.compile(
            r"(foff|vaddr|0x[0-9a-fA-F]{4,}|patch|offset|tbnz|tbz|csel|Status:|codesign|MATCH|symbol)",
            re.IGNORECASE,
        )
        for line in raw_lines[-100:]:
            try:
                entry = json.loads(line)
                text_content = ""
                if entry.get("type") == "tool/result":
                    for item in entry.get("data", {}).get("message", {}).get("content", []):
                        if item.get("type") == "tool-result":
                            for c in item.get("content", []):
                                text_content += c.get("text", "") + "\n"
                elif entry.get("type") == "assistant/message":
                    for item in entry.get("data", {}).get("message", {}).get("content", []):
                        if item.get("type") == "text":
                            text_content += item.get("text", "") + "\n"
                for subline in text_content.splitlines():
                    s = subline.strip()
                    if s and len(s) < 200 and keyword_pat.search(s) and s not in salvaged:
                        salvaged.append(s)
            except Exception:
                continue

    added = 0
    for s in salvaged:
        if working_set.append_discovery("harvest", s, source="session-log"):
            added += 1
    data = working_set.auto_synthesize_checkpoint(
        reason="session harvest merge",
        phase=auto_detect_state(),
    )
    working_set.render_handover(data, output_file=output_file)
    print(f"🛡️  [Working Set] merged {added} harvested line(s) into checkpoint.json → {output_file}")
    return output_file


def main():
    parser = argparse.ArgumentParser(description="Session State Distillation Tool")
    parser.add_argument("--project", default="general-task", help="Project name")
    parser.add_argument("--state", help="Current StateM state (auto-detected if omitted)")
    parser.add_argument("--milestones", help="Semicolon-separated completed milestones")
    parser.add_argument("--discoveries", help="Semicolon-separated technical discoveries")
    parser.add_argument("--next-actions", help="Semicolon-separated immediate next steps")
    parser.add_argument("--output", default="HANDOVER.md", help="Output markdown path")
    parser.add_argument("--harvest", action="store_true", help="Merge session-log hits into checkpoint.json (does not clobber)")
    parser.add_argument("--from-checkpoint", action="store_true", help="Render HANDOVER.md from checkpoint.json only")

    args = parser.parse_args()

    if args.from_checkpoint:
        working_set.render_handover(output_file=args.output)
        print(f"✨ Rendered {args.output} from .viking_state/checkpoint.json")
        return

    if args.harvest:
        harvest_latest_discoveries(output_file=args.output)
        return

    state = args.state or auto_detect_state()
    m_list = [m.strip() for m in args.milestones.split(";")] if args.milestones else []
    d_list = [d.strip() for d in args.discoveries.split(";")] if args.discoveries else []
    n_list = [n.strip() for n in args.next_actions.split(";")] if args.next_actions else []

    distill(args.project, state, m_list, d_list, n_list, args.output)


if __name__ == "__main__":
    main()
