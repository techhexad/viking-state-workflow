#!/usr/bin/env python3
"""
Viking Bridge (viking_bridge.py)
A lightweight CLI & Python client for OpenViking context offloading and retrieval.
Works seamlessly across DSH, Hermes, OpenCode, Claude Code, and other agent runtimes.
"""

import sys
import os
import time
import argparse
import subprocess
import json
import urllib.request
import urllib.error
import re

OPENVIKING_HOST = os.environ.get("OPENVIKING_HOST", "http://127.0.0.1:1933")
LOCAL_VFS_BACKUP = os.path.expanduser("~/.openviking/local_vfs")
MAX_INLINE_LINES = int(os.environ.get("VIKING_MAX_INLINE_LINES", "40"))
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


def _get_api_key():
    """Try to read user_key or api_key from ovcli config or environment."""
    key = os.environ.get("OPENVIKING_API_KEY") or os.environ.get("OV_USER_KEY")
    if key:
        return key
    conf_path = os.path.expanduser("~/.openviking/ovcli.conf")
    if os.path.exists(conf_path):
        try:
            with open(conf_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data.get("api_key") or data.get("user_key")
        except Exception:
            pass
    return None


def _http_request(endpoint: str, method="GET", data=None):
    url = f"{OPENVIKING_HOST.rstrip('/')}/{endpoint.lstrip('/')}"
    headers = {"Content-Type": "application/json"}
    api_key = _get_api_key()
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
        headers["X-OpenViking-Account"] = "default"
        headers["X-OpenViking-User"] = "admin"
        
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
    """Fallback local persistence if OpenViking daemon is restarting."""
    safe_rel = uri.replace("viking://", "").lstrip("/")
    target_path = os.path.join(LOCAL_VFS_BACKUP, safe_rel)
    os.makedirs(os.path.dirname(target_path), exist_ok=True)
    with open(target_path, "w", encoding="utf-8") as f:
        f.write(content)
    return target_path


def ping():
    res = _http_request("/health")
    if "error" in res or not res.get("healthy"):
        print(f"[STATUS] ⚠️ OpenViking server not reachable at {OPENVIKING_HOST}: {res.get('error')}")
        print(f"[STATUS] Local backup directory is active: {LOCAL_VFS_BACKUP}")
        return False
    print(f"[STATUS] ✅ OpenViking server is online at {OPENVIKING_HOST} (Version: {res.get('version', 'unknown')})")
    return True


def put_vfs(uri: str, content: str, tags=None):
    payload = {
        "uri": uri,
        "content": content
    }
    local_path = _write_local_backup(uri, content)
    
    res = _http_request("/api/v1/content/write", method="POST", data=payload)
    if "error" in res:
        print(f"[VFS] Saved to local fallback ({local_path}). Server note: {res['error']}")
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
    """Run native macOS Vision OCR and optionally persist to OpenViking."""
    if not os.path.exists(image_path):
        print(f"[ERROR] Image not found: {image_path}")
        return 1

    swift_ocr_path = os.path.join(SCRIPT_DIR, "mac_ocr.swift")
    if not os.path.exists(swift_ocr_path):
        print(f"[ERROR] OCR script not found at {swift_ocr_path}")
        return 1

    proc = subprocess.run([swift_ocr_path, image_path], capture_output=True, text=True)
    if proc.returncode != 0:
        print(f"[ERROR] OCR failed: {proc.stderr}")
        return proc.returncode

    ocr_text = proc.stdout.strip()
    if not ocr_text:
        print(f"[OCR] No text recognized in {image_path}.")
        return 0

    print(f"\n🔍 [macOS Vision OCR Result for {os.path.basename(image_path)}]:")
    print("-" * 50)
    print(ocr_text)
    print("-" * 50)

    if dest_uri:
        put_vfs(dest_uri, ocr_text, tags=["ocr_result", "ui_inspection"])
        print(f"📍 OCR result also saved to {dest_uri}")

    return 0


def capture_and_ocr(app_path: str, open_settings=True, dest_uri: str = None, screenshot_path="/tmp/viking_ui_capture.png"):
    """Activate app, optionally send Cmd+, to open settings, capture screenshot and run OCR."""
    app_name = os.path.basename(app_path).replace(".app", "")
    print(f"[AUTO-UI] Activating {app_path} ...")
    subprocess.run(["open", "-a", app_path], check=False)
    time.sleep(1.2)

    if open_settings:
        print(f"[AUTO-UI] Opening Settings (Cmd+,) via AppleScript ...")
        as_script = f'''
        tell application "{app_name}" to activate
        delay 0.5
        tell application "System Events"
            keystroke "," using command down
        end tell
        delay 1.0
        '''
        subprocess.run(["osascript", "-e", as_script], check=False)

    print(f"[AUTO-UI] Capturing screen to {screenshot_path} ...")
    subprocess.run(["screencapture", "-x", screenshot_path], check=False)
    time.sleep(0.5)

    return run_ocr(screenshot_path, dest_uri)


def main():
    parser = argparse.ArgumentParser(description="OpenViking Context & Memory Bridge")
    subparsers = parser.add_subparsers(dest="subcommand", required=True)

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

    # Capture & OCR (All-in-one UI Inspection)
    cap_parser = subparsers.add_parser("capture-ocr", help="Auto-activate App, trigger settings, screenshot & OCR")
    cap_parser.add_argument("--app", required=True, help="Path to .app bundle")
    cap_parser.add_argument("--no-settings", action="store_true", help="Do not trigger Cmd+, settings shortcut")
    cap_parser.add_argument("--dest", help="Optional Viking URI to store OCR text")
    cap_parser.add_argument("--output-png", default="/tmp/viking_ui_capture.png", help="Temporary screenshot path")

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

    if args.subcommand == "ping":
        sys.exit(0 if ping() else 1)
    elif args.subcommand == "run":
        sys.exit(run_command(args.cmd, args.dest, args.max_lines))
    elif args.subcommand == "ocr":
        sys.exit(run_ocr(args.image, args.dest))
    elif args.subcommand == "capture-ocr":
        sys.exit(capture_and_ocr(args.app, not args.no_settings, args.dest, args.output_png))
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
