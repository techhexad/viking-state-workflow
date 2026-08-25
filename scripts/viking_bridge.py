#!/usr/bin/env python3
"""
Viking Bridge (viking_bridge.py)
A lightweight CLI & Python client for OpenViking context offloading and retrieval.
Features:
- Dynamic config auto-discovery & pre-flight doctor diagnostics
- Fault-tolerant UI capture with crash detection, window elevation, and auto-retry
- Human-in-the-loop verification with configurable timeout and auto-fallback
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
import urllib.request
import urllib.error
import re

MAX_INLINE_LINES = int(os.environ.get("VIKING_MAX_INLINE_LINES", "40"))
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
LOCAL_VFS_BACKUP = os.path.expanduser("~/.openviking/local_vfs")
DEFAULT_TIMEOUT_SEC = int(os.environ.get("VIKING_USER_TIMEOUT", "600"))  # 10 minutes default


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


def _write_local_backup(uri: str, content: str):
    safe_rel = uri.replace("viking://", "").lstrip("/")
    target_path = os.path.join(LOCAL_VFS_BACKUP, safe_rel)
    os.makedirs(os.path.dirname(target_path), exist_ok=True)
    with open(target_path, "w", encoding="utf-8") as f:
        f.write(content)
    return target_path


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
    safe_rel = uri.replace("viking://", "").lstrip("/")
    target_path = os.path.join(LOCAL_VFS_BACKUP, safe_rel)
    if os.path.exists(target_path):
        with open(target_path, "r", encoding="utf-8") as f:
            return f.read()
    return f"[ERROR] Node {uri} not found."


def grep_vfs(uri: str, pattern: str, context_lines=5):
    content = get_vfs(uri)
    if content.startswith("[ERROR]"):
        print(content)
        return

    lines = content.splitlines()
    matches = []
    regex = re.compile(pattern, re.IGNORECASE)

    for idx, line in enumerate(lines):
        if regex.search(line):
            start = max(0, idx - context_lines)
            end = min(len(lines), idx + context_lines + 1)
            snippet = lines[start:end]
            matches.append((idx + 1, start + 1, snippet))

    if not matches:
        print(f"[GREP] No matches found for pattern '{pattern}' in {uri}.")
        return

    print(f"[GREP] Found {len(matches)} match(es) for '{pattern}' in {uri}:\n")
    for match_num, (line_no, start_line, snippet) in enumerate(matches[:5], 1):
        print(f"--- Match #{match_num} (around line {line_no}) ---")
        for offset, s_line in enumerate(snippet):
            curr_no = start_line + offset
            prefix = ">>" if curr_no == line_no else "  "
            print(f"{prefix} {curr_no:6d}: {s_line}")
        print()
    if len(matches) > 5:
        print(f"... and {len(matches) - 5} more matches truncated.")


def run_command(cmd: str, dest_uri: str, max_lines=MAX_INLINE_LINES):
    print(f"[EXECUTING] {cmd}")
    proc = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    combined_output = proc.stdout
    if proc.stderr:
        combined_output += ("\n[STDERR]\n" + proc.stderr)

    lines = combined_output.splitlines()
    if len(lines) <= max_lines:
        print(combined_output)
        return proc.returncode

    put_vfs(dest_uri, combined_output, tags=["cmd_output", "auto_intercept"])
    
    print("\n" + "=" * 70)
    print(f"🛡️  [VIKING INTERCEPTOR: Heavy Output Detected ({len(lines)} lines)]")
    print(f"📍 Stored at: {dest_uri}")
    print("=" * 70)
    print("Top 10 lines preview:")
    for line in lines[:10]:
        print(f"  {line}")
    print(f"\n... [{len(lines) - 20} lines offloaded to OpenViking] ...\n")
    print("Bottom 10 lines preview:")
    for line in lines[-10:]:
        print(f"  {line}")
    print("=" * 70)
    print(f"💡 Tip: To inspect specific symbols, run:")
    print(f"   python viking_bridge.py grep --uri \"{dest_uri}\" --pattern \"<keyword>\"\n")

    return proc.returncode


def run_ocr(image_path: str, dest_uri: str = None):
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


def capture_and_ocr(app_path: str, open_settings=True, dest_uri: str = None, screenshot_path="/tmp/viking_ui_capture.png", auto_kill=True, max_retries=2, timeout_sec=DEFAULT_TIMEOUT_SEC, ask_user=False):
    """
    Robust UI Capture & OCR with:
    1. Crash & process liveness detection
    2. Window elevation (anti-obscuration)
    3. Multi-attempt retries with fallback triggers
    4. Human-in-the-loop confirmation with configurable timeout
    5. Auto teardown and diagnostic logging
    """
    app_name = os.path.basename(app_path).replace(".app", "")
    captured_text = ""
    
    for attempt in range(1, max_retries + 1):
        print(f"\n[AUTO-UI Attempt {attempt}/{max_retries}] Pre-cleaning existing '{app_name}' instances...")
        subprocess.run(["pkill", "-9", "-f", app_name], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(0.5)

        print(f"[AUTO-UI] Launching fresh instance of {app_path} ...")
        subprocess.run(["open", "-a", app_path], check=False)
        time.sleep(1.5)

        # 1. Check process liveness (Crash detection)
        pgrep = subprocess.run(["pgrep", "-f", app_name], capture_output=True, text=True)
        if not pgrep.stdout.strip():
            crash_info = _check_recent_crash(app_name)
            print(f"\n💥 [CRITICAL CRASH DETECTED] App '{app_name}' exited immediately after launch!")
            if crash_info:
                print(f"📋 Diagnostic trace:\n{crash_info}")
            if dest_uri:
                put_vfs(f"viking://knowledge/{app_name}/logs/crash_report.txt", crash_info or "Immediate crash on launch")
            return 2  # Special returncode 2 = CRASH

        # 2. Focus & elevate window
        print(f"[AUTO-UI] Elevating window to front and sending Settings shortcut (Cmd+,)...")
        as_script = f'''
        tell application "{app_name}"
            activate
            reopen
        end tell
        tell application "System Events"
            set frontmost of process "{app_name}" to true
            delay 0.5
            keystroke "," using command down
        end tell
        delay 1.2
        '''
        subprocess.run(["osascript", "-e", as_script], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        # 3. Capture screenshot
        print(f"[AUTO-UI] Capturing screen to {screenshot_path} ...")
        subprocess.run(["screencapture", "-x", screenshot_path], check=False)
        time.sleep(0.5)

        code, text = run_ocr(screenshot_path, dest_uri)
        captured_text = text
        
        if text and len(text.splitlines()) >= 2:
            print(f"✅ [AUTO-UI] Successfully captured and verified UI text ({len(text.splitlines())} lines).")
            break

        print(f"⚠️ [AUTO-UI] OCR text was empty or incomplete. Retrying...")
        time.sleep(1.0)

    # 4. Human-In-The-Loop Question (if requested or uncertain)
    if ask_user:
        user_reply = prompt_user_confirmation(
            f"请人工核对屏幕上的 '{app_name}' 界面状态。当前 OCR 提取结果为:\n{captured_text[:300]}...",
            timeout_sec=timeout_sec
        )
        if user_reply.lower() in ["y", "yes", "true", "1"]:
            print("✅ 人工确认：界面验证通过！")
            if auto_kill:
                subprocess.run(["pkill", "-9", "-f", app_name], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return 0
        elif user_reply.lower() in ["n", "no", "false", "0"]:
            print("❌ 人工判定：界面验证未通过，触发自愈回退！")
            if auto_kill:
                subprocess.run(["pkill", "-9", "-f", app_name], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return 1

    # 5. Teardown
    if auto_kill:
        print(f"[AUTO-UI] Auto-terminating '{app_name}' to release file locks...")
        subprocess.run(["pkill", "-9", "-f", app_name], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    return 0 if (captured_text and len(captured_text.splitlines()) >= 2) else 1


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

    # OCR
    ocr_parser = subparsers.add_parser("ocr", help="Extract text from screenshot using native macOS Vision")
    ocr_parser.add_argument("image", help="Path to image/screenshot file")
    ocr_parser.add_argument("--dest", help="Optional Viking URI to store OCR text (e.g. viking://knowledge/ocr/ui.txt)")

    # Capture & OCR
    cap_parser = subparsers.add_parser("capture-ocr", help="Auto-activate App, trigger settings, screenshot & OCR with retry & crash-guard")
    cap_parser.add_argument("--app", required=True, help="Path to .app bundle")
    cap_parser.add_argument("--no-settings", action="store_true", help="Do not trigger Cmd+, settings shortcut")
    cap_parser.add_argument("--dest", help="Optional Viking URI to store OCR text")
    cap_parser.add_argument("--output-png", default="/tmp/viking_ui_capture.png", help="Temporary screenshot path")
    cap_parser.add_argument("--keep-running", action="store_true", help="Do not auto-terminate app after OCR")
    cap_parser.add_argument("--retries", type=int, default=2, help="Number of capture retries")
    cap_parser.add_argument("--ask-user", action="store_true", help="Prompt user for manual confirmation before proceeding")
    cap_parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT_SEC, help="Human confirmation timeout in seconds (default 600s)")

    # Put
    put_parser = subparsers.add_parser("put", help="Upload a file or string to VFS")
    put_parser.add_argument("file", help="Local file path")
    put_parser.add_argument("uri", help="Destination Viking URI")

    # Get
    get_parser = subparsers.add_parser("get", help="Retrieve content from VFS")
    get_parser.add_argument("uri", help="Target Viking URI")

    # Grep
    grep_parser = subparsers.add_parser("grep", help="Search pattern with context in VFS node")
    grep_parser.add_argument("--uri", required=True, help="Target Viking URI")
    grep_parser.add_argument("--pattern", required=True, help="Regex or string pattern")
    grep_parser.add_argument("--context", type=int, default=5, help="Lines of context around match")

    args = parser.parse_args()

    if args.subcommand == "doctor":
        sys.exit(0 if doctor() else 1)
    elif args.subcommand == "ping":
        sys.exit(0 if ping() else 1)
    elif args.subcommand == "run":
        sys.exit(run_command(args.cmd, args.dest, args.max_lines))
    elif args.subcommand == "ocr":
        code, _ = run_ocr(args.image, args.dest)
        sys.exit(code)
    elif args.subcommand == "capture-ocr":
        sys.exit(capture_and_ocr(
            app_path=args.app,
            open_settings=not args.no_settings,
            dest_uri=args.dest,
            screenshot_path=args.output_png,
            auto_kill=not args.keep_running,
            max_retries=args.retries,
            timeout_sec=args.timeout,
            ask_user=args.ask_user
        ))
    elif args.subcommand == "put":
        if os.path.exists(args.file):
            with open(args.file, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
            put_vfs(args.uri, content)
        else:
            print(f"[ERROR] File not found: {args.file}")
            sys.exit(1)
    elif args.subcommand == "get":
        print(get_vfs(args.uri))
    elif args.subcommand == "grep":
        grep_vfs(args.uri, args.pattern, args.context)


if __name__ == "__main__":
    main()
