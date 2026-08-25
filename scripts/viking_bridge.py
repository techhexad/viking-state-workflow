#!/usr/bin/env python3
"""
Viking Bridge (viking_bridge.py)
A lightweight CLI & Python client for OpenViking context offloading and retrieval.
Works seamlessly across DSH, Hermes, OpenCode, Claude Code, and other agent runtimes.
"""

import sys
import os
import argparse
import subprocess
import json
import urllib.request
import urllib.error
import re

OPENVIKING_HOST = os.environ.get("OPENVIKING_HOST", "http://127.0.0.1:8080")
LOCAL_VFS_BACKUP = os.path.expanduser("~/.openviking/local_vfs")
MAX_INLINE_LINES = int(os.environ.get("VIKING_MAX_INLINE_LINES", "40"))


def _http_request(endpoint: str, method="GET", data=None):
    url = f"{OPENVIKING_HOST.rstrip('/')}/{endpoint.lstrip('/')}"
    headers = {"Content-Type": "application/json"}
    body = json.dumps(data).encode("utf-8") if data else None
    
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            content = resp.read().decode("utf-8")
            return json.loads(content) if content else {}
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
    res = _http_request("/api/v1/health")
    if "error" in res:
        print(f"[STATUS] ⚠️ OpenViking server not reachable at {OPENVIKING_HOST}: {res['error']}")
        print(f"[STATUS] Local backup directory is active: {LOCAL_VFS_BACKUP}")
        return False
    print(f"[STATUS] ✅ OpenViking server is online at {OPENVIKING_HOST}")
    return True


def put_vfs(uri: str, content: str, tags=None):
    payload = {
        "uri": uri,
        "content": content,
        "tags": tags or []
    }
    res = _http_request("/api/v1/vfs/write", method="POST", data=payload)
    # Always write to local backup as well
    local_path = _write_local_backup(uri, content)
    if "error" in res:
        print(f"[VFS] Saved to local fallback ({local_path}). Remote error: {res['error']}")
        return local_path
    print(f"[VFS] Successfully saved to {uri}")
    return uri


def get_vfs(uri: str):
    payload = {"uri": uri}
    res = _http_request("/api/v1/vfs/read", method="POST", data=payload)
    if "error" not in res and "content" in res:
        return res["content"]
    
    # Check local fallback
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
    
    # If output is concise, print directly
    if len(lines) <= max_lines:
        print(combined_output)
        return proc.returncode

    # Otherwise, offload to OpenViking VFS
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
