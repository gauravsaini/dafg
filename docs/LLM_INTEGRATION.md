# LLM Integration Guide

How DAFG works with Copilot, Claude, ChatGPT, and any other LLM.
Core architectural fact: DAFG separates the **brain** (any LLM) from the **control plane**
(graph, gates, verifier). The only contract is `runner_fn(prompt, node) -> dict`.
The verifier (gates + stop-hook + external oracle) works on **any** workdir
regardless of who wrote the code.

## Pattern 1 — Instruction interlock (built)

`dafg init --agents <copilot|claude|codex|cursor|antigravity|all>` writes the agent's
native instructions file with the DAFG discipline (gates before code, `gates --run`
before claiming done, `stop-hook --json` must return `allow`):

- copilot → `.github/copilot-instructions.md`
- claude → `CLAUDE.md` + `.claude/settings.json` (Stop hook registered)
- codex → `AGENTS.md` + `.codex/hooks.json` (Stop hook registered)
- cursor → `.cursor/rules/dafg.mdc`
- antigravity → `AGENTS.md`

Enforcement is soft (the model must obey its instructions) unless the Stop hook is
wired into the agent loop or CI. Hard enforcement lives in Patterns 2 and 3.

## Pattern 2 — DAFG-driven CLI agents (built for claude/codex)

`agent_cli.py --mode real` shells out to a local CLI agent with `[bin, "-p", "--cwd", workdir, prompt]`.
DAFG owns the loop; the LLM is the prover. Dispatch order: `omp` → `claude` → `codex`
(first binary found wins). Any failure raises `RealAgentError` — a failed agent is
never silently replaced with staged code (that substitution scores 100% and fakes evidence).

- claude: `claude -p --cwd <workdir> "<prompt>"` — works today.
- codex: `codex exec -p` via `src/dafg/codex_mac.py` (`CodexMacRunner`) — proven in the
  20-trial Mac pilot (gpt-6-luna, true token usage from `--json` events).
- copilot: **not wired.** `gh copilot` documents a `-p "prompt"` non-interactive mode,
  but the Copilot CLI binary would not install in our environment, requires a Copilot
  subscription + auth, and its non-interactive codegen behavior (working-dir flags,
  output format, exit codes) is unverified. Wiring it blind would be theater.
  To wire it later: install the CLI, verify `gh copilot -p "<prompt>"` writes files
  and exits non-zero on failure, then add it to the dispatch list in `run_real_agent`
  following the exact claude/codex pattern.

## Pattern 3 — API runners (~100 lines per new LLM)

`src/dafg/real_model.py` (`GeminiRunner`) and `src/dafg/codex_mac.py` (`CodexMacRunner`)
are the template: `runner_fn(prompt, node) -> dict` with `{"status", "text", "usage"}`.
True token usage from the API response makes CPAD computable from real numbers.
To add an LLM: clone the pattern, point at the provider's `generateContent`-equivalent
endpoint, map the usage fields. Needs a credential (connector or key).

- Claude API → `AnthropicRunner`: not built (needs key).
- OpenAI API → `OpenAIRunner`: not built (needs key).

## Status matrix

- **Copilot**: interlock = built (`dafg init --agents copilot`); CLI-driven = missing (see finding above); API = n/a (no public Copilot API — use the CLI when verified).
- **Claude**: interlock = built; CLI-driven = built (`agent_cli --mode real`); API = missing.
- **ChatGPT**: interlock = built (via codex: `AGENTS.md` + hooks); CLI-driven = built (codex, pilot-proven); API = missing.

## Verifier separability — the zero-integration path

You do not need any integration to get DAFG's core value. Write code with whatever
LLM you like (Copilot completions, ChatGPT web paste, Claude Code), then point DAFG
at the workdir:

```bash
uv run gates --lint GATES.md      # ledger is valid
uv run gates --approve GATES.md   # approve check commands (first run / on change)
uv run gates --run GATES.md       # every gate: CHECK command + EXPECT match
uv run stop-hook GATES.md --json  # {"decision":"allow"} or {"decision":"block"}
```

Whoever wrote the code, the evidence decides. `block` means stay in the loop and fix;
`allow` means verified delivery. For a full external audit, see `dafg-eval/`
(`ExternalJudge` scores any workspace against ground-truth oracles).
