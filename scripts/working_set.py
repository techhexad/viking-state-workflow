#!/usr/bin/env python3
"""
Working set for micro-sprint subagents.

Machine-relay source of truth (append/merge only):
  .viking_state/checkpoint.json
  .viking_state/discoveries.jsonl

HANDOVER.md is a human-readable projection of checkpoint.json.
Exploration budget lives in .viking_state/sprint_budget and is reset
per sprint (statem_supervisor.py resets it when synthesizing a prompt).
"""

import json
import os
import re
from datetime import datetime

STATE_DIR = ".viking_state"
CHECKPOINT_FILE = os.path.join(STATE_DIR, "checkpoint.json")
DISCOVERIES_FILE = os.path.join(STATE_DIR, "discoveries.jsonl")
BUDGET_FILE = os.path.join(STATE_DIR, "sprint_budget")
HANDOVER_FILE = "HANDOVER.md"

MAX_SPRINT_STEPS = 8
DRAIN_AFTER = 6  # 6-7 refuse exploration; 8 auto-crystallize and yield

VALUE_PAT = re.compile(
    r"(0x[0-9a-fA-F]{4,}|foff|vaddr|tbnz|tbz|cbz|cbnz|csel|adrp|"
    r"codesign|Unlicensed|Activated|isPro|Trial Expired|MATCH|"
    r"symbol|patch|NOP|BRK)",
    re.IGNORECASE,
)

EMPTY_CHECKPOINT = {
    "phase": "",
    "updated_at": "",
    "confirmed": [],
    "rejected": [],
    "next_action": "",
    "artifacts": [],
    "sprint": {"status": "", "reason": ""},
}


def ensure_state_dir():
    os.makedirs(STATE_DIR, exist_ok=True)


def load_checkpoint() -> dict:
    if not os.path.exists(CHECKPOINT_FILE):
        return json.loads(json.dumps(EMPTY_CHECKPOINT))
    try:
        with open(CHECKPOINT_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return json.loads(json.dumps(EMPTY_CHECKPOINT))
        merged = json.loads(json.dumps(EMPTY_CHECKPOINT))
        merged.update({k: data.get(k, merged[k]) for k in merged})
        if not isinstance(merged.get("confirmed"), list):
            merged["confirmed"] = []
        if not isinstance(merged.get("rejected"), list):
            merged["rejected"] = []
        if not isinstance(merged.get("artifacts"), list):
            merged["artifacts"] = []
        if not isinstance(merged.get("sprint"), dict):
            merged["sprint"] = {"status": "", "reason": ""}
        return merged
    except Exception:
        return json.loads(json.dumps(EMPTY_CHECKPOINT))


def save_checkpoint(data: dict):
    ensure_state_dir()
    data["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(CHECKPOINT_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
        f.flush()
        os.fsync(f.fileno())


def _norm_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


def _has_fact(items: list, fact: str) -> bool:
    target = _norm_text(fact).lower()
    if not target:
        return True
    for item in items:
        if isinstance(item, dict):
            blob = _norm_text(str(item.get("fact") or item.get("try") or item.get("uri") or ""))
        else:
            blob = _norm_text(str(item))
        if blob.lower() == target:
            return True
    return False


def append_discovery(kind: str, text: str, source: str = "") -> bool:
    """Append one high-value line. Returns False if skipped (empty/dup/too long)."""
    line = _norm_text(text)
    if not line or len(line) > 240:
        return False
    ensure_state_dir()
    existing = []
    if os.path.exists(DISCOVERIES_FILE):
        try:
            with open(DISCOVERIES_FILE, "r", encoding="utf-8", errors="replace") as f:
                existing = f.readlines()[-200:]
        except Exception:
            existing = []
    for prev in existing:
        try:
            obj = json.loads(prev)
            if _norm_text(obj.get("text", "")).lower() == line.lower():
                return False
        except Exception:
            continue
    rec = {
        "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "kind": kind,
        "text": line,
        "source": source,
    }
    with open(DISCOVERIES_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        f.flush()
        os.fsync(f.fileno())
    return True


def crystallize_text(text: str, source: str = "tool") -> int:
    """Scan tool output and persist high-value lines into discoveries.jsonl."""
    if not text:
        return 0
    n = 0
    for raw in text.splitlines():
        s = raw.strip()
        if not s or len(s) > 240:
            continue
        if VALUE_PAT.search(s):
            if append_discovery("auto", s, source=source):
                n += 1
    return n


def merge_checkpoint(confirmed=None, rejected=None, next_action=None, artifacts=None,
                     phase=None, sprint_status=None, sprint_reason=None) -> dict:
    data = load_checkpoint()
    if phase:
        data["phase"] = phase
    for fact in confirmed or []:
        fact = _norm_text(fact)
        if fact and not _has_fact(data["confirmed"], fact):
            data["confirmed"].append({"fact": fact})
            append_discovery("confirmed", fact, source="note")
    for item in rejected or []:
        if isinstance(item, dict):
            try_text = _norm_text(item.get("try", ""))
            why = _norm_text(item.get("why", ""))
            blob = f"{try_text} :: {why}".strip(" :")
        else:
            blob = _norm_text(str(item))
            try_text, why = blob, ""
        if blob and not _has_fact(data["rejected"], try_text or blob):
            data["rejected"].append({"try": try_text or blob, "why": why})
            append_discovery("rejected", blob, source="note")
    if next_action:
        data["next_action"] = _norm_text(next_action)
    for uri in artifacts or []:
        uri = _norm_text(uri)
        if uri and uri not in data["artifacts"]:
            data["artifacts"].append(uri)
    if sprint_status:
        data["sprint"]["status"] = sprint_status
    if sprint_reason:
        data["sprint"]["reason"] = sprint_reason
    save_checkpoint(data)
    return data


def recent_discoveries(limit: int = 20) -> list:
    if not os.path.exists(DISCOVERIES_FILE):
        return []
    try:
        with open(DISCOVERIES_FILE, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except Exception:
        return []
    out = []
    for raw in lines[-limit:]:
        try:
            out.append(json.loads(raw))
        except Exception:
            continue
    return out


def auto_synthesize_checkpoint(reason: str = "sprint budget exhausted", phase: str = "") -> dict:
    """Guarantee a checkpoint exists before a sprint is killed."""
    data = load_checkpoint()
    if phase:
        data["phase"] = phase
    elif not data.get("phase"):
        data["phase"] = _detect_phase()
    for rec in recent_discoveries(30):
        text = rec.get("text", "")
        kind = rec.get("kind", "auto")
        if kind == "rejected":
            if text and not _has_fact(data["rejected"], text.split(" :: ")[0]):
                parts = text.split(" :: ", 1)
                data["rejected"].append({"try": parts[0], "why": parts[1] if len(parts) > 1 else ""})
        else:
            if text and not _has_fact(data["confirmed"], text):
                data["confirmed"].append({"fact": text, "how": rec.get("source", "auto")})
    if not data.get("next_action"):
        data["next_action"] = "Load checkpoint.json and continue from the latest confirmed facts."
    data["sprint"] = {"status": "yield", "reason": reason}
    save_checkpoint(data)
    render_handover(data)
    return data


def render_handover(data: dict = None, output_file: str = HANDOVER_FILE) -> str:
    data = data or load_checkpoint()
    confirmed = data.get("confirmed") or []
    rejected = data.get("rejected") or []
    artifacts = data.get("artifacts") or []
    c_lines = []
    for item in confirmed[-20:]:
        if isinstance(item, dict):
            c_lines.append(f"- {item.get('fact', '')}")
        else:
            c_lines.append(f"- {item}")
    r_lines = []
    for item in rejected[-15:]:
        if isinstance(item, dict):
            why = f" — {item['why']}" if item.get("why") else ""
            r_lines.append(f"- {item.get('try', '')}{why}")
        else:
            r_lines.append(f"- {item}")
    a_lines = [f"- {u}" for u in artifacts] or ["- None"]
    report = f"""# Session Distillation & Handover Report

## 1. Meta Information
- **Phase**: {data.get('phase') or 'unknown'}
- **Timestamp**: {data.get('updated_at') or datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
- **Sprint Status**: {data.get('sprint', {}).get('status') or 'n/a'}
- **Handover Reason**: Projection of `.viking_state/checkpoint.json` (working set).

---

## 2. Confirmed Facts
{chr(10).join(c_lines) if c_lines else '- None reported.'}

---

## 3. Rejected Paths
{chr(10).join(r_lines) if r_lines else '- None reported.'}

---

## 4. Artifacts
{chr(10).join(a_lines)}

---

## 5. Immediate Next Action
1. {data.get('next_action') or 'Continue following StateM runbook.'}

---
> [!TIP]
> The next sprint should load `.viking_state/checkpoint.json` rather than full chat history.
"""
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(report)
        f.flush()
        os.fsync(f.fileno())
    return output_file


def _detect_phase() -> str:
    if os.path.exists("runbook.yaml"):
        try:
            with open("runbook.yaml", "r", encoding="utf-8") as f:
                for line in f:
                    if line.strip().startswith("current_state:"):
                        return line.split(":", 1)[1].strip().strip('"').strip("'")
        except Exception:
            pass
    return ""


def checkpoint_prompt_slice(max_confirmed: int = 12) -> str:
    data = load_checkpoint()
    if not any([data.get("confirmed"), data.get("rejected"), data.get("next_action")]):
        return "(empty working set — no checkpoint.json facts yet)"
    slim = {
        "phase": data.get("phase"),
        "confirmed": data.get("confirmed", [])[-max_confirmed:],
        "rejected": data.get("rejected", [])[-8:],
        "next_action": data.get("next_action"),
        "artifacts": data.get("artifacts", [])[-8:],
    }
    return json.dumps(slim, ensure_ascii=False, indent=2)


def read_sprint_count() -> int:
    if not os.path.exists(BUDGET_FILE):
        return 0
    try:
        with open(BUDGET_FILE, "r") as f:
            return int(f.read().strip() or "0")
    except Exception:
        return 0


def reset_sprint_budget():
    ensure_state_dir()
    with open(BUDGET_FILE, "w") as f:
        f.write("0\n")


def sprint_guard(is_explore: bool = True) -> str:
    """
    Returns:
      ok     — run the exploration command
      drain  — refuse exploration; persist-only
      yield  — budget exhausted; caller must crystallize then exit 20
    Persist commands (is_explore=False) never increment the counter.
    """
    if not is_explore:
        return "ok"
    ensure_state_dir()
    cnt = read_sprint_count() + 1
    with open(BUDGET_FILE, "w") as f:
        f.write(str(cnt))
    if cnt >= MAX_SPRINT_STEPS:
        return "yield"
    if cnt >= DRAIN_AFTER:
        return "drain"
    return "ok"


def sprint_hud(status: str) -> str:
    cnt = read_sprint_count()
    remaining = max(0, MAX_SPRINT_STEPS - cnt)
    if status == "ok" and cnt == DRAIN_AFTER - 1:
        return (
            f"\n⚠️  [SPRINT HUD: EXPLORE {cnt}/{MAX_SPRINT_STEPS} — next call enters drain]\n"
            f"⚠️  Persist confirmed facts with `viking_bridge.py note` before further grep/run.\n"
        )
    if status == "drain":
        return (
            f"\n⚠️  [SPRINT DRAIN: EXPLORE {cnt}/{MAX_SPRINT_STEPS} — ONLY {remaining} LEFT]\n"
            f"⚠️  Exploration refused. Write the working set:\n"
            f"    python3 {os.path.abspath(__file__).replace('working_set.py', 'viking_bridge.py')} "
            f"note --confirmed \"<fact>\" --next \"<next_action>\"\n"
            f"⚠️  Then stop this sprint. Do not grep/run/ocr.\n"
        )
    if status == "yield":
        return (
            f"\n🛑 [SPRINT YIELD: {cnt}/{MAX_SPRINT_STEPS} EXPLORATION CALLS]\n"
            f"🛑 Auto-crystallized `.viking_state/checkpoint.json`. "
            f"SPRINT_STATUS: YIELD — dispatch the next micro-sprint.\n"
        )
    return ""
