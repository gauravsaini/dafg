#!/bin/bash
# codex_run.sh [--json] <prompt_file> <timeout_s>
# Runs codex exec with the standing model recipe (gpt-6-luna, max reasoning).
# The prompt is passed via python argv (no shell interpolation), stdin is
# /dev/null (bare codex exec hangs on stdin). Prints model output to stdout.
# Exit 124 on timeout, otherwise codex's exit code.
# NEVER add --approve-for-me here (conflicts with sandbox flags); never touch ~/.codex/config.toml.
JSON=""
if [ "$1" = "--json" ]; then JSON="--json"; shift; fi
PROMPT_FILE="$1"
TIMEOUT_S="$2"
/usr/bin/python3 - "$JSON" "$PROMPT_FILE" "$TIMEOUT_S" <<'PYEOF'
import subprocess, sys
json_flag, prompt_file, timeout_s = sys.argv[1], sys.argv[2], int(sys.argv[3])
prompt = open(prompt_file, encoding="utf-8").read()
args = ["/Users/ektasaini/.local/bin/codex", "exec", "--skip-git-repo-check",
        "-m", "gpt-6-luna", "-c", "model_reasoning_effort=\"max\"", prompt]
if json_flag:
    args.insert(3, "--json")
p = subprocess.Popen(args, stdin=subprocess.DEVNULL,
                     stdout=subprocess.PIPE, stderr=subprocess.PIPE)
try:
    out, err = p.communicate(timeout=timeout_s)
except subprocess.TimeoutExpired:
    p.kill()
    out, err = p.communicate()
    sys.stdout.write(out.decode("utf-8", "replace"))
    sys.stderr.write(err.decode("utf-8", "replace"))
    sys.exit(124)
sys.stdout.write(out.decode("utf-8", "replace"))
sys.stderr.write(err.decode("utf-8", "replace"))
sys.exit(p.returncode)
PYEOF
