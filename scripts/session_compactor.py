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


def main():
    parser = argparse.ArgumentParser(description="Session State Distillation Tool")
    parser.add_argument("--project", default="general-task", help="Project name")
    parser.add_argument("--state", help="Current StateM state (auto-detected if omitted)")
    parser.add_argument("--milestones", help="Semicolon-separated completed milestones")
    parser.add_argument("--discoveries", help="Semicolon-separated technical discoveries")
    parser.add_argument("--next-actions", help="Semicolon-separated immediate next steps")
    parser.add_argument("--output", default="session_distilled_state.md", help="Output markdown path")

    args = parser.parse_args()

    state = args.state or auto_detect_state()
    m_list = [m.strip() for m in args.milestones.split(";")] if args.milestones else []
    d_list = [d.strip() for d in args.discoveries.split(";")] if args.discoveries else []
    n_list = [n.strip() for n in args.next_actions.split(";")] if args.next_actions else []

    distill(args.project, state, m_list, d_list, n_list, args.output)


if __name__ == "__main__":
    main()
