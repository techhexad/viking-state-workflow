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

import hashlib
import json
import os
import re
from datetime import datetime

STATE_DIRNAME = ".viking_state"
MAX_SPRINT_STEPS = 8
DRAIN_AFTER = 6  # 6-7 refuse exploration; 8 auto-crystallize and yield
MAX_FACT_LEN = 240
MAX_NEXT_ACTION_LEN = 400

# Resolved from project root (runbook.yaml / .viking_state), not the process CWD.
_PROJECT_ROOT = None

VALUE_PAT = re.compile(
    r"(0x[0-9a-fA-F]{6,}|foff\s*[:=]|vaddr\s*[:=]|"
    r"\b(tbnz|tbz|cbz|cbnz|csel|adrp)\b|"
    r"codesign|Unlicensed|Activated|\bisPro\b|Trial Expired|\bMATCH\b)",
    re.IGNORECASE,
)

EMPTY_CHECKPOINT = {
    "phase": "",
    "updated_at": "",
    "confirmed": [],
    "rejected": [],
    "killed": [],
    "pending_patch": None,
    "next_action": "",
    "artifacts": [],
    "sprint": {"status": "", "reason": ""},
    "gate": {"last_evidence_count": 0, "last_from": "", "last_to": ""},
}

NEXT_AFTER_N = (
    "The last patch was falsified by human UI. Work from remaining non-killed "
    "license-key xrefs; find the flag reader/writer. Never patch a VA in killed[]. "
    "Do not ask the human about the license page this sprint."
)
NEXT_AFTER_CRASH = (
    "The patched app crashed. Diagnose the last patch (illegal insn vs SwiftUI trap). "
    "Do not treat crash as 'not a Pro gate'. Do not re-ask the license page until the app stays up."
)
NEXT_AFTER_Y = "Human UI PASS: Pro/license page activated. Run --advance --gate-check if the phase gate is met."
ASK_HUMAN_NEXT = "Human UI: is the Pro/license page activated? Reply y / n / crash open / crash <button> / wrong app"
ASK_UI_HINT = re.compile(
    r"(license.?page|ask.?ui|relay|y/n|专业页|是否.*激活|ask the (user|human)|awaiting_human)",
    re.IGNORECASE,
)


def set_project_root(path: str):
    """Pin working-set paths to a workspace (typically the runbook directory)."""
    global _PROJECT_ROOT
    _PROJECT_ROOT = os.path.abspath(path) if path else None


def project_root() -> str:
    env = os.environ.get("VIKING_PROJECT_ROOT")
    if env:
        return os.path.abspath(env)
    if _PROJECT_ROOT:
        return _PROJECT_ROOT
    here = os.path.abspath(os.getcwd())
    cur = here
    while True:
        if os.path.isfile(os.path.join(cur, "runbook.yaml")) or os.path.isdir(
            os.path.join(cur, STATE_DIRNAME)
        ):
            return cur
        parent = os.path.dirname(cur)
        if parent == cur:
            return here
        cur = parent


def state_dir() -> str:
    return os.path.join(project_root(), STATE_DIRNAME)


def checkpoint_file() -> str:
    return os.path.join(state_dir(), "checkpoint.json")


def discoveries_file() -> str:
    return os.path.join(state_dir(), "discoveries.jsonl")


def budget_file() -> str:
    return os.path.join(state_dir(), "sprint_budget")


def sprint_prompt_file() -> str:
    return os.path.join(state_dir(), "sprint_prompt.txt")


def handover_file() -> str:
    return os.path.join(project_root(), "HANDOVER.md")


def __getattr__(name):
    mapping = {
        "STATE_DIR": state_dir,
        "CHECKPOINT_FILE": checkpoint_file,
        "DISCOVERIES_FILE": discoveries_file,
        "BUDGET_FILE": budget_file,
        "HANDOVER_FILE": handover_file,
    }
    if name in mapping:
        return mapping[name]()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def ensure_state_dir():
    os.makedirs(state_dir(), exist_ok=True)


def load_checkpoint() -> dict:
    path = checkpoint_file()
    if not os.path.exists(path):
        return json.loads(json.dumps(EMPTY_CHECKPOINT))
    try:
        with open(path, "r", encoding="utf-8") as f:
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
        if not isinstance(merged.get("killed"), list):
            merged["killed"] = []
        pp = data.get("pending_patch", merged.get("pending_patch"))
        merged["pending_patch"] = pp if isinstance(pp, dict) and pp.get("va") else None
        if not isinstance(merged.get("sprint"), dict):
            merged["sprint"] = {"status": "", "reason": ""}
        if not isinstance(merged.get("gate"), dict):
            merged["gate"] = {"last_evidence_count": 0, "last_from": "", "last_to": ""}
        return merged
    except Exception:
        return json.loads(json.dumps(EMPTY_CHECKPOINT))


def save_checkpoint(data: dict):
    ensure_state_dir()
    data["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(checkpoint_file(), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
        f.flush()
        os.fsync(f.fileno())


def evidence_count(data: dict = None) -> int:
    data = data if data is not None else load_checkpoint()
    return len(data.get("confirmed") or []) + len(data.get("artifacts") or [])


def record_gate_pass(from_state: str, to_state: str) -> dict:
    data = load_checkpoint()
    data["phase"] = to_state
    data["gate"] = {
        "last_evidence_count": evidence_count(data),
        "last_from": from_state or "",
        "last_to": to_state or "",
    }
    save_checkpoint(data)
    return data


def _norm_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


def _clip(text: str, limit: int) -> str:
    text = _norm_text(text)
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


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
    if not line or len(line) > MAX_FACT_LEN:
        return False
    ensure_state_dir()
    existing = []
    dfile = discoveries_file()
    if os.path.exists(dfile):
        try:
            with open(dfile, "r", encoding="utf-8", errors="replace") as f:
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
    with open(dfile, "a", encoding="utf-8") as f:
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
        if not s or len(s) > MAX_FACT_LEN:
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
        fact = _clip(str(fact), MAX_FACT_LEN)
        if fact and not _has_fact(data["confirmed"], fact):
            data["confirmed"].append({"fact": fact})
            append_discovery("confirmed", fact, source="note")
    for item in rejected or []:
        if isinstance(item, dict):
            try_text = _clip(str(item.get("try", "")), MAX_FACT_LEN)
            why = _clip(str(item.get("why", "")), MAX_FACT_LEN)
            blob = f"{try_text} :: {why}".strip(" :")
        else:
            blob = _clip(str(item), MAX_FACT_LEN)
            try_text, why = blob, ""
        if blob and not _has_fact(data["rejected"], try_text or blob):
            data["rejected"].append({"try": try_text or blob, "why": why})
            append_discovery("rejected", blob, source="note")
    if next_action:
        data["next_action"] = _clip(str(next_action), MAX_NEXT_ACTION_LEN)
    for uri in artifacts or []:
        uri = _clip(str(uri), MAX_FACT_LEN)
        if uri and uri not in data["artifacts"]:
            data["artifacts"].append(uri)
    if sprint_status:
        data["sprint"]["status"] = sprint_status
    if sprint_reason:
        data["sprint"]["reason"] = sprint_reason
    save_checkpoint(data)
    return data


def norm_va(va: str) -> str:
    text = (va or "").strip().lower()
    if not text:
        return ""
    if not text.startswith("0x"):
        text = "0x" + text
    return text


def is_killed_va(va: str, data: dict = None) -> bool:
    va = norm_va(va)
    if not va:
        return False
    data = data if data is not None else load_checkpoint()
    for item in data.get("killed") or []:
        if isinstance(item, dict) and norm_va(item.get("va", "")) == va:
            return True
    return False


def looks_like_ask_ui(text: str) -> bool:
    return bool(ASK_UI_HINT.search(text or ""))


def app_macos_executable(app_path: str) -> str:
    if not app_path:
        return ""
    path = os.path.expanduser(app_path)
    if not os.path.isabs(path):
        path = os.path.join(project_root(), path)
    path = os.path.realpath(path)
    macos = os.path.join(path, "Contents", "MacOS")
    if os.path.isdir(macos):
        name = os.path.basename(path).replace(".app", "")
        cand = os.path.join(macos, name)
        if os.path.isfile(cand):
            return cand
        files = [
            os.path.join(macos, f)
            for f in os.listdir(macos)
            if os.path.isfile(os.path.join(macos, f)) and not f.startswith(".")
        ]
        return files[0] if files else ""
    return path if os.path.isfile(path) else ""


def sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def resolve_app_path(app_path: str) -> str:
    if not app_path:
        return ""
    path = os.path.expanduser(app_path)
    if not os.path.isabs(path):
        path = os.path.join(project_root(), path)
    return os.path.realpath(path)


def set_pending_patch(va: str, app_path: str, fileoff: str = "", before: str = "",
                      after: str = "", kind: str = "", hypothesis: str = "") -> dict:
    va = norm_va(va)
    app_path = resolve_app_path(app_path)
    if not va or not app_path:
        raise ValueError("pending patch requires --patch-va and --app")
    if is_killed_va(va):
        raise ValueError(f"VA {va} is in killed[]; will not set pending_patch")
    exe = app_macos_executable(app_path)
    sha = sha256_file(exe) if exe and os.path.isfile(exe) else ""
    data = load_checkpoint()
    data["pending_patch"] = {
        "va": va,
        "fileoff": (fileoff or "").strip().lower(),
        "bytes_before": (before or "").strip().lower(),
        "bytes_after": (after or "").strip().lower(),
        "kind": (kind or "").strip(),
        "hypothesis": _clip(hypothesis or "", MAX_FACT_LEN),
        "app_path": app_path,
        "exe_sha256": sha,
        "status": "awaiting_human",
        "crash_where": "",
    }
    data["next_action"] = ASK_HUMAN_NEXT
    data["sprint"]["status"] = "awaiting_human"
    data["sprint"]["reason"] = f"pending patch {va}"
    save_checkpoint(data)
    append_discovery("pending", f"pending_patch va={va} app={app_path}", source="sprint-done")
    return data


def parse_human_token(raw: str) -> tuple:
    """Return (kind, where) kind in y, n, crash, wrong-app, unknown."""
    text = (raw or "").strip()
    low = text.lower()
    if low in ("y", "yes", "true", "1", "pass", "ok", "pro", "activated"):
        return "y", ""
    if low in ("n", "no", "false", "0", "fail"):
        return "n", ""
    if low in ("wrong app", "wrong-app", "wrong_app"):
        return "wrong-app", ""
    if low.startswith("crash"):
        where = text[5:].strip(" :-/\t")
        if not where or where.lower() in ("open", "launch", "start"):
            return "crash", "open"
        return "crash", where
    return "unknown", text


def apply_verdict(kind: str, where: str = "") -> dict:
    """Bind a human UI token to pending_patch. Caller must fingerprint first."""
    data = load_checkpoint()
    pending = data.get("pending_patch") if isinstance(data.get("pending_patch"), dict) else None
    if kind == "wrong-app":
        raise ValueError("wrong-app")
    if not pending or not pending.get("va"):
        raise ValueError("no pending_patch")
    va = pending.get("va")
    if kind == "y":
        data["pending_patch"] = None
        data["sprint"]["status"] = "done"
        data["sprint"]["reason"] = "human UI PASS"
        data["next_action"] = NEXT_AFTER_Y
        fact = f"Human UI PASS for patch {va}"
        if not _has_fact(data["confirmed"], fact):
            data["confirmed"].append({"fact": fact})
        append_discovery("confirmed", fact, source="verdict")
        save_checkpoint(data)
        render_handover(data)
        return data
    if kind == "n":
        entry = {
            "va": va,
            "fileoff": pending.get("fileoff") or "",
            "why": "human n — app ran, Pro page not activated",
            "kind": pending.get("kind") or "patch",
            "bytes_before": pending.get("bytes_before") or "",
            "bytes_after": pending.get("bytes_after") or "",
        }
        if not is_killed_va(va, data):
            data["killed"].append(entry)
        try_text = f"killed patch va={va}"
        if not _has_fact(data["rejected"], try_text):
            data["rejected"].append({"try": try_text, "why": entry["why"]})
        data["pending_patch"] = None
        data["sprint"]["status"] = "falsified"
        data["sprint"]["reason"] = entry["why"]
        data["next_action"] = NEXT_AFTER_N
        append_discovery("killed", try_text, source="verdict")
        save_checkpoint(data)
        render_handover(data)
        return data
    if kind == "crash":
        pending["status"] = "crashed"
        pending["crash_where"] = where or "open"
        data["pending_patch"] = pending
        data["sprint"]["status"] = "crashed"
        data["sprint"]["reason"] = f"human crash {where or 'open'}"
        data["next_action"] = NEXT_AFTER_CRASH
        append_discovery("crash", f"crash where={where or 'open'} va={va}", source="verdict")
        save_checkpoint(data)
        render_handover(data)
        return data
    raise ValueError(f"unsupported verdict {kind}")


def resolve_sprint_goal(requested: str = None) -> tuple:
    """Pick the sprint question. Returns (goal_or_empty, mode).

    mode: awaiting_human | rewritten | ok
    """
    data = load_checkpoint()
    pending = data.get("pending_patch") if isinstance(data.get("pending_patch"), dict) else None
    if pending and pending.get("status") == "awaiting_human":
        return "", "awaiting_human"
    if pending and pending.get("status") == "crashed":
        return NEXT_AFTER_CRASH, "rewritten"
    goal = (requested or "").strip() or (data.get("next_action") or "").strip()
    if looks_like_ask_ui(goal):
        if data.get("killed"):
            return NEXT_AFTER_N, "rewritten"
        return (
            "Do not ask the human until a pending_patch exists. Continue from confirmed "
            "facts; if you byte-patch, sprint-done with --patch-va and --app.",
            "rewritten",
        )
    if goal:
        for item in data.get("killed") or []:
            va = norm_va((item or {}).get("va", "") if isinstance(item, dict) else "")
            if va and va in goal.lower() and re.search(r"nop|patch|b\.ne|tbnz", goal, re.I):
                return NEXT_AFTER_N, "rewritten"
    if not goal:
        return NEXT_AFTER_N if data.get("killed") else "", "ok"
    return goal, "ok"


def recent_discoveries(limit: int = 20) -> list:
    dfile = discoveries_file()
    if not os.path.exists(dfile):
        return []
    try:
        with open(dfile, "r", encoding="utf-8", errors="replace") as f:
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
        # Only promote human-noted facts. auto/harvest lines stay in discoveries.jsonl.
        if kind == "rejected":
            if text and not _has_fact(data["rejected"], text.split(" :: ")[0]):
                parts = text.split(" :: ", 1)
                data["rejected"].append({"try": parts[0], "why": parts[1] if len(parts) > 1 else ""})
        elif kind == "confirmed":
            if text and not _has_fact(data["confirmed"], text):
                data["confirmed"].append({"fact": text, "how": rec.get("source", "note")})
    if not data.get("next_action"):
        data["next_action"] = "Load checkpoint.json and continue from the latest confirmed facts."
    data["sprint"] = {"status": "yield", "reason": reason}
    save_checkpoint(data)
    render_handover(data)
    return data


def render_handover(data: dict = None, output_file: str = None) -> str:
    data = data or load_checkpoint()
    output_file = output_file or handover_file()
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
    path = os.path.join(project_root(), "runbook.yaml")
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    if line.strip().startswith("current_state:"):
                        return line.split(":", 1)[1].strip().strip('"').strip("'")
        except Exception:
            pass
    return ""


def _slim_fact(item):
    if isinstance(item, dict):
        out = {}
        if item.get("fact"):
            out["fact"] = _clip(str(item.get("fact")), MAX_FACT_LEN)
        if item.get("try"):
            out["try"] = _clip(str(item.get("try")), MAX_FACT_LEN)
        if item.get("why"):
            out["why"] = _clip(str(item.get("why")), 120)
        return out or item
    return _clip(str(item), MAX_FACT_LEN)


def checkpoint_prompt_slice(max_confirmed: int = 8) -> str:
    data = load_checkpoint()
    if not any([
        data.get("confirmed"),
        data.get("rejected"),
        data.get("killed"),
        data.get("pending_patch"),
        data.get("next_action"),
    ]):
        return "(empty working set — no checkpoint.json facts yet)"
    killed = []
    for item in data.get("killed") or []:
        if not isinstance(item, dict):
            continue
        killed.append({
            "va": item.get("va") or "",
            "why": _clip(str(item.get("why") or ""), 160),
            "kind": item.get("kind") or "",
        })
    pending = data.get("pending_patch") if isinstance(data.get("pending_patch"), dict) else None
    slim_pending = None
    if pending and pending.get("va"):
        slim_pending = {
            "va": pending.get("va"),
            "status": pending.get("status"),
            "app_path": pending.get("app_path"),
            "kind": pending.get("kind") or "",
            "crash_where": pending.get("crash_where") or "",
        }
    slim = {
        "phase": data.get("phase"),
        "confirmed": [_slim_fact(x) for x in (data.get("confirmed") or [])[-max_confirmed:]],
        "rejected": [_slim_fact(x) for x in (data.get("rejected") or [])[-6:]],
        "killed": killed,
        "pending_patch": slim_pending,
        "next_action": _clip(str(data.get("next_action") or ""), MAX_NEXT_ACTION_LEN),
        "artifacts": [
            _clip(str(u), MAX_FACT_LEN) for u in (data.get("artifacts") or [])[-4:]
        ],
    }
    return json.dumps(slim, ensure_ascii=False, indent=2)


def read_sprint_count() -> int:
    path = budget_file()
    if not os.path.exists(path):
        return 0
    try:
        with open(path, "r") as f:
            return int(f.read().strip() or "0")
    except Exception:
        return 0


def reset_sprint_budget():
    ensure_state_dir()
    with open(budget_file(), "w") as f:
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
    with open(budget_file(), "w") as f:
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
