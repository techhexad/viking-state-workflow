#!/usr/bin/env bash
# Source this file to activate Viking transparent interception in the current shell:
# source /Users/richliu/Git/viking-state-workflow/scripts/viking_env.sh

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export PATH="$SCRIPT_DIR/bin:$PATH"
export VIKING_MAX_INLINE_LINES=40
echo "[VIKING] 🛡️ Transparent Hard-Interception active for: lldb, objdump, otool"
