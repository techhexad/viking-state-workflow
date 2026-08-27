#!/usr/bin/env python3
"""
Viking Bridge (viking_bridge.py)
A lightweight CLI & Python client for OpenViking context offloading and retrieval.
Features:
- Dynamic config auto-discovery & pre-flight doctor diagnostics
- Human UI gate (ask-ui): no auto-open/screenshot retries
- Optional OCR of a screenshot the human already took
- Zero-VRAM macOS Vision OCR & VFS integration
"""

import sys
import os
import time
import select
import argparse
import subprocess
import json
import glob
import shutil
import urllib.request
import urllib.error
import re
from collections import deque

import working_set

MAX_INLINE_LINES = int(os.environ.get("VIKING_MAX_INLINE_LINES", "40"))
MAX_HTTP_PUT_BYTES = int(os.environ.get("VIKING_MAX_HTTP_PUT_BYTES", "1000000"))
MAX_GREP_CONTEXT = 30
MAX_GREP_MATCHES = 20
MAX_GET_PRINT_LINES = 40
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
LOCAL_VFS_BACKUP = os.path.expanduser("~/.openviking/local_vfs")
DEFAULT_TIMEOUT_SEC = int(os.environ.get("VIKING_USER_TIMEOUT", "600"))  # 10 minutes default
DEFAULT_RUN_TIMEOUT_SEC = int(os.environ.get("VIKING_RUN_TIMEOUT", "600"))
BRIDGE_ACTIVE_ENV = "VIKING_BRIDGE_ACTIVE"


def _auto_discover_config():
    """Dynamically auto-discover port, host, and keys from ~/.openviking/."""
    host = os.environ.get("OPENVIKING_HOST")
    api_key = os.environ.get("OPENVIKING_API_KEY") or os.environ.get("OV_USER_KEY")
    account = "default"
    user = "admin"

    ov_conf_path = os.path.expanduser("~/.openviking/ov.conf")
    if not host and os.path.exists(ov_conf_path):
        try:
            with open(ov_conf_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                server_cfg = data.get("server", {})
                port = server_cfg.get("port", 1933)
                h = server_cfg.get("host", "127.0.0.1")
                if h == "0.0.0.0":
                    h = "127.0.0.1"
                host = f"http://{h}:{port}"
        except Exception:
            pass

    if not host:
        host = "http://127.0.0.1:1933"

    ovcli_conf_path = os.path.expanduser("~/.openviking/ovcli.conf")
    if os.path.exists(ovcli_conf_path):
        try:
            with open(ovcli_conf_path, "r", encoding="utf-8") as f:
                cli_data = json.load(f)
                if not api_key:
                    api_key = cli_data.get("api_key") or cli_data.get("user_key")
                account = cli_data.get("account") or account
                user = cli_data.get("user") or user
                if not os.environ.get("OPENVIKING_HOST") and cli_data.get("url"):
                    host = cli_data.get("url")
        except Exception:
            pass

    return host, api_key, account, user


OPENVIKING_HOST, OPENVIKING_KEY, VIKING_ACCOUNT, VIKING_USER = _auto_discover_config()


def _http_request(endpoint: str, method="GET", data=None):
    url = f"{OPENVIKING_HOST.rstrip('/')}/{endpoint.lstrip('/')}"
    headers = {"Content-Type": "application/json"}
    if OPENVIKING_KEY:
        headers["Authorization"] = f"Bearer {OPENVIKING_KEY}"
        headers["X-OpenViking-Account"] = VIKING_ACCOUNT
        headers["X-OpenViking-User"] = VIKING_USER
        
    body = json.dumps(data).encode("utf-8") if data else None
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            content = resp.read().decode("utf-8")
            return json.loads(content) if content else {}
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8") if e.fp else ""
        return {"error": f"HTTP {e.code}: {e.reason} - {err_body}"}
    except urllib.error.URLError as e:
        return {"error": f"Connection failed to OpenViking at {url}: {e}"}
    except Exception as e:
        return {"error": str(e)}


def vfs_relpath(uri: str) -> str:
    """Map viking://... to a relative path; reject traversal."""
    raw = (uri or "").replace("viking://", "").replace("\\", "/")
    parts = []
    for p in raw.split("/"):
        if p in ("", "."):
            continue
        if p == "..":
            raise ValueError(f"illegal VFS path (parent segment): {uri}")
        parts.append(p)
    if not parts:
        raise ValueError(f"empty VFS path: {uri}")
    return os.path.join(*parts)


def _write_local_backup(uri: str, content: str):
    safe_rel = vfs_relpath(uri)
    target_path = os.path.join(LOCAL_VFS_BACKUP, safe_rel)
    try:
        os.makedirs(os.path.dirname(target_path), exist_ok=True)
        with open(target_path, "w", encoding="utf-8") as f:
            f.write(content)
        return target_path
    except (PermissionError, OSError):
        # Sandbox fallback: write inside current working directory
        ws_backup = os.path.join(working_set.project_root(), ".viking_vfs", safe_rel)
        os.makedirs(os.path.dirname(ws_backup), exist_ok=True)
        with open(ws_backup, "w", encoding="utf-8") as f:
            f.write(content)
        return ws_backup


def local_node_candidates(uri: str):
    rel = vfs_relpath(uri)
    return [
        os.path.join(LOCAL_VFS_BACKUP, rel),
        os.path.join(working_set.project_root(), ".viking_vfs", rel),
    ]


def resolve_local_node(uri: str):
    for path in local_node_candidates(uri):
        if os.path.isfile(path):
            return path
    return None


def _prepare_dest_path(uri: str) -> str:
    rel = vfs_relpath(uri)
    primary = os.path.join(LOCAL_VFS_BACKUP, rel)
    try:
        os.makedirs(os.path.dirname(primary), exist_ok=True)
        return primary
    except (PermissionError, OSError):
        ws = os.path.join(working_set.project_root(), ".viking_vfs", rel)
        os.makedirs(os.path.dirname(ws), exist_ok=True)
        return ws


def _preview_file(path: str, head: int = 10, tail: int = 10):
    """Line count + head/tail without loading the whole file as one string."""
    if not path or not os.path.isfile(path):
        return 0, [], []
    head_lines = []
    tail_buf = deque(maxlen=max(0, tail))
    n = 0
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            n += 1
            if len(head_lines) < head:
                head_lines.append(line.rstrip("\n"))
            if tail:
                tail_buf.append(line.rstrip("\n"))
    last = list(tail_buf)
    if n <= head:
        last = []
    elif tail and n <= head + tail:
        last = last[-(n - head):]
    return n, head_lines, last


def put_file_vfs(uri: str, file_path: str, tags=None):
    """Copy a file into local VFS. HTTP upload only if the file is small."""
    dest = _prepare_dest_path(uri)
    src = os.path.abspath(file_path)
    if os.path.abspath(dest) != src:
        shutil.copyfile(src, dest)
    size = os.path.getsize(dest)
    if size <= MAX_HTTP_PUT_BYTES:
        with open(dest, "r", encoding="utf-8", errors="replace") as f:
            return put_vfs(uri, f.read(), tags=tags)
    print(f"[VFS] Stored locally at {dest} ({size} bytes). "
          f"Skipped HTTP put (>{MAX_HTTP_PUT_BYTES}).")
    return dest


def doctor():
    """Mandatory Pre-flight check: verifies all connections, auth, and models before running task."""
    print("=" * 65)
    print("🩺  [OpenViking Pre-flight Doctor Check]")
    print("=" * 65)
    print(f"📡 Discovered Server Endpoint : {OPENVIKING_HOST}")
    print(f"🔑 Auth User Key              : {'[Configured]' if OPENVIKING_KEY else '[MISSING ❌]'}")
    print(f"👤 Account / User Context     : {VIKING_ACCOUNT} / {VIKING_USER}")

    res = _http_request("/health")
    if "error" in res or not res.get("healthy"):
        print(f"\n❌ [ERROR] OpenViking server is NOT reachable at {OPENVIKING_HOST}!")
        print(f"   Reason: {res.get('error')}")
        print("\n👉 Action Required:")
        print("   Start the OpenViking daemon before running tasks:")
        print("   source ~/.openviking/venv/bin/activate && openviking-server &")
        return False

    print(f"✅ Server Status               : Healthy (v{res.get('version', 'unknown')})")

    if not OPENVIKING_KEY:
        print("\n⚠️  [WARNING] User API Key is missing. Tenant APIs will be rejected.")
        print("   Please configure user key via: ov config add ...")
        return False

    fs_test = _http_request("/api/v1/content/read", method="POST", data={"uri": "viking://resources"})
    if "error" in fs_test and "HTTP 401" in fs_test["error"]:
        print(f"\n❌ [AUTH ERROR] User API Key failed validation: {fs_test['error']}")
        return False
    print("✅ VFS & Auth Handshake        : Verified & Ready")
    print("=" * 65)
    print("🎉 All Pre-flight checks passed! Context offloading is 100% active.\n")
    return True


def ping():
    res = _http_request("/health")
    if "error" in res or not res.get("healthy"):
        print(f"[STATUS] ⚠️ OpenViking server not reachable at {OPENVIKING_HOST}: {res.get('error')}")
        return False
    print(f"[STATUS] ✅ OpenViking server is online at {OPENVIKING_HOST} (Version: {res.get('version', 'unknown')})")
    return True


def put_vfs(uri: str, content: str, tags=None):
    payload = {"uri": uri, "content": content}
    local_path = _write_local_backup(uri, content)
    res = _http_request("/api/v1/content/write", method="POST", data=payload)
    if "error" in res:
        print(f"[VFS WARNING] Saved to local fallback ({local_path}). Server note: {res['error']}")
        return local_path
    print(f"[VFS] Successfully saved to {uri}")
    return uri


def get_vfs(uri: str):
    payload = {"uri": uri}
    res = _http_request("/api/v1/content/read", method="POST", data=payload)
    if "error" not in res and "content" in res:
        return res["content"]
    try:
        safe_rel = vfs_relpath(uri)
    except ValueError as e:
        return f"[ERROR] {e}"
    target_path = os.path.join(LOCAL_VFS_BACKUP, safe_rel)
    if os.path.exists(target_path):
        with open(target_path, "r", encoding="utf-8") as f:
            return f.read()
    ws_path = os.path.join(working_set.project_root(), ".viking_vfs", safe_rel)
    if os.path.exists(ws_path):
        with open(ws_path, "r", encoding="utf-8") as f:
            return f.read()
    return f"[ERROR] Node {uri} not found."


def _materialize_node(uri: str):
    """Return a local path for uri. Prefer disk; only then fetch (and persist) via HTTP."""
    path = resolve_local_node(uri)
    if path:
        return path, None
    content = get_vfs(uri)
    if not content or content.startswith("[ERROR]"):
        return None, (content or f"[ERROR] Empty content in {uri}")
    return _write_local_backup(uri, content), None


def _grep_stream(path: str, uri: str, regex, context_lines: int, max_matches: int):
    match_lines = []
    total = 0
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for i, line in enumerate(f, 1):
            if regex.search(line.rstrip("\n")):
                total += 1
                if len(match_lines) < max_matches:
                    match_lines.append(i)
    if total == 0:
        print(f"[GREP] No matches found for pattern in {uri}.")
        return 1

    windows = []
    needed = set()
    for ln in match_lines:
        start = max(1, ln - context_lines)
        end = ln + context_lines
        windows.append((ln, start, end))
        needed.update(range(start, end + 1))
    collected = {}
    stop_after = max(w[2] for w in windows)
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for i, line in enumerate(f, 1):
            if i in needed:
                collected[i] = line.rstrip("\n")
            if i >= stop_after:
                break

    print(f"[GREP] Found {total} match(es) for '{regex.pattern}' in {uri}:\n")
    crystallized = 0
    for match_num, (line_no, start_line, end_line) in enumerate(windows, 1):
        print(f"--- Match #{match_num} (around line {line_no}) ---")
        for curr_no in range(start_line, end_line + 1):
            if curr_no not in collected:
                continue
            s_line = collected[curr_no]
            prefix = ">>" if curr_no == line_no else "  "
            print(f"{prefix} {curr_no:6d}: {s_line}")
            if curr_no == line_no and working_set.append_discovery("grep", s_line, source=uri):
                crystallized += 1
        print()
    if total > len(windows):
        print(f"... and {total - len(windows)} more matches truncated. "
              f"Pass a tighter --pattern to page.")
    if crystallized:
        print(f"📌 Crystallized {crystallized} hit(s) into .viking_state/discoveries.jsonl")
    return 0


def grep_vfs(uri: str, pattern: str, context_lines=5, ignore_case=True, max_matches=5):
    """Search a VFS node by streaming the local file. Never split() a 200MB blob."""
    enforce_explore_budget()
    context_lines = max(0, min(int(context_lines), MAX_GREP_CONTEXT))
    max_matches = max(1, min(int(max_matches), MAX_GREP_MATCHES))
    flags = re.IGNORECASE if ignore_case else 0
    try:
        regex = re.compile(pattern, flags)
    except re.error as e:
        print(f"[ERROR] Invalid regex {pattern!r}: {e}")
        return 2

    path, err = _materialize_node(uri)
    if err:
        print(err)
        return 1
    return _grep_stream(path, uri, regex, context_lines, max_matches)


def enforce_explore_budget():
    """Refuse or yield exploration so the working set is on disk before a sprint dies."""
    status = working_set.sprint_guard(is_explore=True)
    hud = working_set.sprint_hud(status)
    if hud:
        print(hud)
    if status == "drain":
        sys.exit(18)
    if status == "yield":
        working_set.auto_synthesize_checkpoint(reason="sprint exploration budget exhausted")
        print("SPRINT_STATUS: YIELD")
        print(f"NEXT: {working_set.load_checkpoint().get('next_action', '')}")
        sys.exit(20)


def run_command(cmd: str, dest_uri: str, max_lines=MAX_INLINE_LINES, timeout_sec=DEFAULT_RUN_TIMEOUT_SEC):
    """Run cmd with stdout streamed to a file. Never capture_output a 200MB objdump."""
    enforce_explore_budget()
    print(f"[EXECUTING] {cmd}")
    env = os.environ.copy()
    env[BRIDGE_ACTIVE_ENV] = "1"
    try:
        dest_path = _prepare_dest_path(dest_uri)
    except ValueError as e:
        print(f"[ERROR] {e}")
        return 2

    try:
        with open(dest_path, "wb") as out_f:
            proc = subprocess.run(
                cmd,
                shell=True,
                stdout=out_f,
                stderr=subprocess.PIPE,
                timeout=timeout_sec,
                env=env,
            )
    except subprocess.TimeoutExpired:
        print(f"[ERROR] Command timed out after {timeout_sec}s: {cmd}")
        return 124

    stderr = (proc.stderr or b"").decode("utf-8", errors="replace")
    failed = proc.returncode != 0
    n_lines, head, tail = _preview_file(dest_path, head=10, tail=10)

    if stderr.strip():
        err_lines = stderr.splitlines()
        print("[STDERR]")
        for line in err_lines[:20]:
            print(f"  {line}")
        if len(err_lines) > 20:
            print(f"  ... [{len(err_lines) - 20} stderr lines omitted]")

    if n_lines <= max_lines:
        _, body, _ = _preview_file(dest_path, head=max_lines, tail=0)
        print("\n".join(body))
        if not failed:
            working_set.crystallize_text("\n".join(body), source=dest_uri)
            working_set.merge_checkpoint(artifacts=[dest_uri])
        return proc.returncode

    try:
        if os.path.getsize(dest_path) <= MAX_HTTP_PUT_BYTES:
            put_file_vfs(dest_uri, dest_path, tags=["cmd_output", "auto_intercept"])
        else:
            print(f"[VFS] Stored locally at {dest_path} "
                  f"({os.path.getsize(dest_path)} bytes). Skipped HTTP put.")
    except ValueError as e:
        print(f"[ERROR] {e}")
        return 2

    print("\n" + "=" * 70)
    print(f"🛡️  [VIKING INTERCEPTOR: Heavy Output Detected ({n_lines} lines)]")
    print(f"📍 Stored at: {dest_uri}")
    print(f"📄 Local file: {dest_path}")
    if failed:
        print(f"⚠️  Command exited {proc.returncode}; output stored but not recorded as a gate artifact.")
    print("=" * 70)
    print("Top 10 lines preview:")
    for line in head:
        print(f"  {line}")
    omitted = max(0, n_lines - 20)
    print(f"\n... [{omitted} lines offloaded] ...\n")
    print("Bottom 10 lines preview:")
    for line in tail:
        print(f"  {line}")
    print("=" * 70)
    print("💡 Tip: python viking_bridge.py grep "
          f"--uri \"{dest_uri}\" --pattern \"<keyword>\"\n")
    if not failed:
        working_set.crystallize_text("\n".join(head + tail), source=dest_uri)
        working_set.merge_checkpoint(artifacts=[dest_uri])
    return proc.returncode


def print_vfs_preview(uri: str, max_lines=MAX_GET_PRINT_LINES):
    """Print size + a short preview. Never dump a whole VFS node to stdout."""
    path, err = _materialize_node(uri)
    if err:
        print(err)
        return 1
    size = os.path.getsize(path)
    n_lines, head, tail = _preview_file(path, head=min(20, max_lines), tail=10)
    print(f"[GET] {uri}")
    print(f"      file={path} bytes={size} lines={n_lines}")
    if n_lines <= max_lines:
        for line in head:
            print(line)
        return 0
    print(f"[GET] Node too large to dump ({n_lines} lines). Preview only. Use grep.")
    print("--- head ---")
    for line in head:
        print(line)
    print("--- tail ---")
    for line in tail:
        print(line)
    return 0


def sprint_done(status: str, confirmed=None, rejected=None, next_action=None):
    """Persist the working set and print exactly four handover lines."""
    status = (status or "").strip().upper()
    if status not in ("DONE", "YIELD", "FAIL"):
        print("[ERROR] sprint-done --status must be DONE, YIELD, or FAIL")
        return 2
    data = working_set.merge_checkpoint(
        confirmed=confirmed or [],
        rejected=rejected or [],
        next_action=next_action,
        sprint_status=status.lower(),
    )
    working_set.render_handover(data)
    conf = data.get("confirmed") or []
    rej = data.get("rejected") or []
    last_c = conf[-1]["fact"] if conf and isinstance(conf[-1], dict) else ""
    last_r = ""
    if rej:
        item = rej[-1]
        last_r = item.get("try", "") if isinstance(item, dict) else str(item)
    print(f"SPRINT_STATUS: {status}")
    print(f"CONFIRMED: {last_c}")
    print(f"REJECTED: {last_r}")
    print(f"NEXT: {data.get('next_action') or ''}")
    if status == "YIELD":
        return 20
    if status == "FAIL":
        return 1
    return 0


def run_ocr(image_path: str, dest_uri: str = None):
    enforce_explore_budget()
    if not os.path.exists(image_path):
        print(f"[ERROR] Image not found: {image_path}")
        return 1, ""

    swift_ocr_path = os.path.join(SCRIPT_DIR, "mac_ocr.swift")
    if not os.path.exists(swift_ocr_path):
        print(f"[ERROR] OCR script not found at {swift_ocr_path}")
        return 1, ""

    proc = subprocess.run([swift_ocr_path, image_path], capture_output=True, text=True)
    if proc.returncode != 0:
        print(f"[ERROR] OCR failed: {proc.stderr}")
        return proc.returncode, ""

    ocr_text = proc.stdout.strip()
    if not ocr_text:
        print(f"[OCR WARNING] No text recognized in {image_path}.")
        return 0, ""

    print(f"\n🔍 [macOS Vision OCR Result for {os.path.basename(image_path)}]:")
    print("-" * 50)
    print(ocr_text)
    print("-" * 50)

    if dest_uri:
        put_vfs(dest_uri, ocr_text, tags=["ocr_result", "ui_inspection"])
        print(f"📍 OCR result also saved to {dest_uri}")
        working_set.merge_checkpoint(artifacts=[dest_uri])
    working_set.crystallize_text(ocr_text, source=dest_uri or image_path)

    return 0, ocr_text


def _check_recent_crash(app_name: str):
    """Scan ~/Library/Logs/DiagnosticReports for fresh crash logs matching app_name."""
    diag_dir = os.path.expanduser("~/Library/Logs/DiagnosticReports")
    if not os.path.exists(diag_dir):
        return None

    now = time.time()
    matches = glob.glob(os.path.join(diag_dir, f"*{app_name}*.ips")) + glob.glob(os.path.join(diag_dir, f"*{app_name}*.crash"))
    recent = []
    for f in matches:
        if now - os.path.getmtime(f) < 60:
            recent.append(f)
            
    if not recent:
        return None
        
    latest_crash = max(recent, key=os.path.getmtime)
    try:
        with open(latest_crash, "r", encoding="utf-8", errors="replace") as cf:
            snippet = cf.read(2000)
            return f"Crash log detected: {os.path.basename(latest_crash)}\n{snippet[:500]}..."
    except Exception:
        return f"Crash log detected: {os.path.basename(latest_crash)}"


def prompt_user_confirmation(question: str, timeout_sec: int = DEFAULT_TIMEOUT_SEC) -> str:
    """Ask user for input with non-blocking timeout fallback."""
    if not sys.stdin.isatty():
        print(f"\n[NON-INTERACTIVE] Non-TTY environment detected. Proceeding automatically.")
        return ""

    print("\n" + "❓" * 30)
    print(f"🤔 {question}")
    print(f"⏳ 等待用户输入 (超时时间: {timeout_sec} 秒 / {timeout_sec // 60} 分钟，超时后将自动继续)...")
    print("👉 输入 'y' 确认通过，输入 'n' 判定失败，或直接输入修正说明 (直接回车或等待则自动继续): ", end="", flush=True)

    rlist, _, _ = select.select([sys.stdin], [], [], timeout_sec)
    if rlist:
        ans = sys.stdin.readline().strip()
        print(f"👤 用户输入: '{ans}'")
        return ans
    else:
        print(f"\n⏰ [超时提醒] 用户在 {timeout_sec} 秒内未应答，自动进入下一步自愈处理流程...")
        return ""


def clean_foreign_processes(app_name: str, target_app_path: str):
    """Kill other bundles with the same .app name, not arbitrary substring matches."""
    target_real = os.path.realpath(target_app_path)
    if not app_name or not target_real:
        return
    try:
        ps = subprocess.run(["ps", "-eo", "pid,command"], capture_output=True, text=True)
        for line in ps.stdout.splitlines():
            parts = line.strip().split(None, 1)
            if len(parts) != 2 or not parts[0].isdigit():
                continue
            pid, cmd = parts[0], parts[1]
            if "viking_bridge" in cmd:
                continue
            match = re.search(r"((?:\/|\A)[^\s]*\.app)", cmd)
            if not match:
                continue
            other_app = os.path.realpath(match.group(1))
            other_name = os.path.basename(other_app).replace(".app", "")
            if other_name.lower() != app_name.lower():
                continue
            if other_app == target_real or other_app.startswith(target_real + os.sep):
                continue
            print(f"[SHIELD] 🛡️ Terminating foreign/stale process PID {pid}: {cmd[:60]}...")
            subprocess.run(["kill", "-9", pid], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass


def ask_ui(app_path: str = "", question: str = "", timeout_sec: int = DEFAULT_TIMEOUT_SEC, open_app: bool = False) -> int:
    """Human-only UI gate. Does not screenshot, scrape AX, or retry."""
    question = (question or "授权/Pro 状态页是否显示 Activated / Pro / 已激活？(y=通过 n=未通过)").strip()
    app_name = os.path.basename(app_path).replace(".app", "") if app_path else ""

    print("\n" + "=" * 65)
    print("ASK-UI  (auto capture-ocr removed)")
    print("=" * 65)
    print("Do not retry this command. Blind open + Cmd+, + screenshot")
    print("does not open the license page; a human must.")
    print()
    print("1. Open the patched app (or use --open once).")
    print("2. Click through to the license / Pro / status page yourself.")
    print("3. Answer y or n. Optional: screenshot then `viking_bridge.py ocr <png>`.")
    if app_path:
        print(f"\nApp: {app_path}")
    print(f"Question: {question}")
    print("=" * 65)

    if open_app and app_path:
        if os.path.isdir(app_path) or os.path.exists(app_path):
            if app_name:
                clean_foreign_processes(app_name, app_path)
            subprocess.run(["open", app_path], check=False)
            print(f"[ASK-UI] opened once (no settings shortcut, no screenshot).")
        else:
            print(f"[ASK-UI] app path not found: {app_path}")

    if not sys.stdin.isatty():
        print("ASK_UI: NEED_HUMAN")
        print("Non-interactive TTY. Do not retry. Parent must ask the user in the main chat.")
        return 4

    ans = prompt_user_confirmation(question, timeout_sec=timeout_sec).lower()
    if ans in ("y", "yes", "true", "1", "pass", "ok", "pro", "activated"):
        print("ASK_UI: PASS")
        working_set.merge_checkpoint(
            confirmed=[f"Human UI gate PASS: {question}"],
            sprint_status="done",
        )
        return 0
    if ans in ("n", "no", "false", "0", "fail"):
        print("ASK_UI: FAIL")
        working_set.merge_checkpoint(
            rejected=[{"try": "UI verify", "why": f"Human UI gate FAIL: {question}"}],
            sprint_status="fail",
        )
        return 1

    print("ASK_UI: NEED_HUMAN")
    print("Empty/timeout answer. Do not treat as crash. Do not retry capture.")
    return 4


def main():
    parser = argparse.ArgumentParser(description="OpenViking Context & Memory Bridge")
    subparsers = parser.add_subparsers(dest="subcommand", required=True)

    # Doctor / Pre-flight
    subparsers.add_parser("doctor", help="Run full pre-flight verification before starting task")

    # Ping
    subparsers.add_parser("ping", help="Check server health")

    # Run
    run_parser = subparsers.add_parser("run", help="Execute command and offload heavy output")
    run_parser.add_argument("--cmd", required=True, help="Shell command to run")
    run_parser.add_argument("--dest", required=True, help="Viking URI (e.g. viking://knowledge/disasm.asm)")
    run_parser.add_argument("--max-lines", type=int, default=MAX_INLINE_LINES, help="Max inline lines before offload")
    run_parser.add_argument(
        "--timeout",
        type=int,
        default=DEFAULT_RUN_TIMEOUT_SEC,
        help=f"Kill the command after N seconds (default {DEFAULT_RUN_TIMEOUT_SEC}, env VIKING_RUN_TIMEOUT)",
    )

    # OCR
    ocr_parser = subparsers.add_parser("ocr", help="Extract text from screenshot using native macOS Vision")
    ocr_parser.add_argument("image", help="Path to image/screenshot file")
    ocr_parser.add_argument("--dest", help="Optional Viking URI to store OCR text (e.g. viking://knowledge/ocr/ui.txt)")

    ask_parser = subparsers.add_parser(
        "ask-ui",
        help="Human UI gate: open the license page yourself, answer y/n. No auto screenshot.",
    )
    ask_parser.add_argument("--app", default="", help="Optional .app path (used with --open)")
    ask_parser.add_argument(
        "--question",
        default="授权/Pro 状态页是否显示 Activated / Pro / 已激活？(y=通过 n=未通过)",
        help="Yes/no question for the human",
    )
    ask_parser.add_argument("--open", action="store_true", help="open(1) the app once; still does not navigate UI")
    ask_parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT_SEC)

    cap_parser = subparsers.add_parser(
        "capture-ocr",
        help="Removed. Alias of ask-ui (no auto-open/screenshot retries).",
    )
    cap_parser.add_argument("--app", default="")
    cap_parser.add_argument("--question", default="")
    cap_parser.add_argument("--open", action="store_true")
    cap_parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT_SEC)
    cap_parser.add_argument("--no-settings", action="store_true", help=argparse.SUPPRESS)
    cap_parser.add_argument("--dest", help=argparse.SUPPRESS)
    cap_parser.add_argument("--output-png", default="/tmp/viking_ui_capture.png", help=argparse.SUPPRESS)
    cap_parser.add_argument("--keep-running", action="store_true", help=argparse.SUPPRESS)
    cap_parser.add_argument("--retries", type=int, default=0, help=argparse.SUPPRESS)
    cap_parser.add_argument("--ask-user", action="store_true", help=argparse.SUPPRESS)

    # Put
    put_parser = subparsers.add_parser("put", help="Upload a file or string to VFS")
    put_parser.add_argument("file", help="Local file path")
    put_parser.add_argument("uri", help="Destination Viking URI")

    # Get
    get_parser = subparsers.add_parser("get", help="Preview a VFS node (never dumps the whole file)")
    get_parser.add_argument("uri", help="Target Viking URI")

    # Grep
    grep_parser = subparsers.add_parser("grep", help="Search pattern with context in VFS node")
    grep_parser.add_argument("--uri", required=True, help="Target Viking URI")
    grep_parser.add_argument("--pattern", required=True, help="Regex or string pattern")
    grep_parser.add_argument("--context", type=int, default=5, help=f"Lines of context around match (capped at {MAX_GREP_CONTEXT})")
    grep_parser.add_argument("--max-matches", type=int, default=5, help=f"Max match snippets to print (capped at {MAX_GREP_MATCHES})")
    grep_parser.add_argument(
        "--ignore-case",
        dest="ignore_case",
        action="store_true",
        default=True,
        help="Case-insensitive search (default)",
    )
    grep_parser.add_argument(
        "--case-sensitive",
        dest="ignore_case",
        action="store_false",
        help="Disable case-insensitive search",
    )

    # Working set (persist-only; does not consume sprint explore budget)
    note_parser = subparsers.add_parser("note", help="Append confirmed/rejected facts into checkpoint.json")
    note_parser.add_argument("--confirmed", action="append", default=[], help="Confirmed fact (repeatable)")
    note_parser.add_argument("--rejected", action="append", default=[], help="Rejected path (repeatable)")
    note_parser.add_argument("--next", dest="next_action", help="Next micro-sprint action")
    note_parser.add_argument("--artifact", action="append", default=[], help="Viking URI or local path (repeatable)")
    note_parser.add_argument("--phase", help="Runbook phase name")

    ck_parser = subparsers.add_parser("checkpoint", help="Print the slim working-set slice")
    ck_parser.add_argument("--full", action="store_true", help="Print raw checkpoint.json (debug only)")
    subparsers.add_parser("sprint-reset", help="Reset micro-sprint exploration budget to 0")
    subparsers.add_parser("sprint-status", help="Show micro-sprint exploration budget")
    done_parser = subparsers.add_parser(
        "sprint-done",
        help="Persist working set and print the 4-line child handover (does not count as explore)",
    )
    done_parser.add_argument("--status", required=True, help="DONE, YIELD, or FAIL")
    done_parser.add_argument("--confirmed", action="append", default=[], help="Confirmed fact (repeatable)")
    done_parser.add_argument("--rejected", action="append", default=[], help="Rejected path (repeatable)")
    done_parser.add_argument("--next", dest="next_action", help="Next micro-sprint action")

    args = parser.parse_args()

    if args.subcommand == "doctor":
        sys.exit(0 if doctor() else 1)
    elif args.subcommand == "ping":
        sys.exit(0 if ping() else 1)
    elif args.subcommand == "run":
        try:
            sys.exit(run_command(args.cmd, args.dest, args.max_lines, timeout_sec=args.timeout))
        except ValueError as e:
            print(f"[ERROR] {e}")
            sys.exit(2)
    elif args.subcommand == "ocr":
        code, _ = run_ocr(args.image, args.dest)
        sys.exit(code)
    elif args.subcommand in ("ask-ui", "capture-ocr"):
        if args.subcommand == "capture-ocr":
            print("[DEPRECATED] capture-ocr auto-launch/screenshot is removed.")
            print("Forwarding to ask-ui once. Do not retry this command.")
        sys.exit(ask_ui(
            app_path=getattr(args, "app", "") or "",
            question=getattr(args, "question", "") or "",
            timeout_sec=getattr(args, "timeout", DEFAULT_TIMEOUT_SEC),
            open_app=bool(getattr(args, "open", False)),
        ))
    elif args.subcommand == "put":
        if os.path.exists(args.file):
            try:
                put_file_vfs(args.uri, args.file)
            except ValueError as e:
                print(f"[ERROR] {e}")
                sys.exit(2)
        else:
            print(f"[ERROR] File not found: {args.file}")
            sys.exit(1)
    elif args.subcommand == "get":
        sys.exit(print_vfs_preview(args.uri) or 0)
    elif args.subcommand == "grep":
        sys.exit(grep_vfs(
            args.uri,
            args.pattern,
            args.context,
            ignore_case=getattr(args, "ignore_case", True),
            max_matches=getattr(args, "max_matches", 5),
        ) or 0)
    elif args.subcommand == "note":
        data = working_set.merge_checkpoint(
            confirmed=args.confirmed,
            rejected=args.rejected,
            next_action=args.next_action,
            artifacts=args.artifact,
            phase=args.phase,
        )
        working_set.render_handover(data)
        print("[WORKING SET] checkpoint.json updated:")
        print(json.dumps({
            "confirmed": data.get("confirmed", [])[-5:],
            "rejected": data.get("rejected", [])[-5:],
            "next_action": data.get("next_action"),
        }, ensure_ascii=False, indent=2))
    elif args.subcommand == "checkpoint":
        if getattr(args, "full", False):
            print(json.dumps(working_set.load_checkpoint(), ensure_ascii=False, indent=2))
        else:
            print(working_set.checkpoint_prompt_slice())
    elif args.subcommand == "sprint-done":
        sys.exit(sprint_done(
            args.status,
            confirmed=args.confirmed,
            rejected=args.rejected,
            next_action=args.next_action,
        ) or 0)
    elif args.subcommand == "sprint-reset":
        working_set.reset_sprint_budget()
        print("[SPRINT] exploration budget reset to 0/8")
    elif args.subcommand == "sprint-status":
        cnt = working_set.read_sprint_count()
        print(f"[SPRINT] explore {cnt}/{working_set.MAX_SPRINT_STEPS} "
              f"(drain at {working_set.DRAIN_AFTER}, yield at {working_set.MAX_SPRINT_STEPS})")


if __name__ == "__main__":
    main()
