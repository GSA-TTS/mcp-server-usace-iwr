# Phoenix Evaluation Framework

This directory contains an [Arize Phoenix](https://docs.arize.com/phoenix) evaluation
framework for the USACE IWR River Mile Marker MCP server (`usace_iwr_mcp`). It runs a
LangChain agent connected to the MCP server over stdio and scores its answers with
LLM-as-judge evaluators.

## Structure

```
eval/phoenix/
├── create_dataset.py          # Unified dataset creation CLI
├── run_experiment.py          # Unified experiment runner CLI
├── datasets.yaml              # Dataset registry and configuration
├── README.md                  # This file
├── agent.py                   # RiverMileAgent class (launches usace_iwr_mcp over stdio)
├── judges/                    # Evaluation functions
│   ├── correctness_judge.py   # match_expected_response evaluator
│   └── relevance_judge.py     # check_answer_scope evaluator
├── prompts/                   # System prompt versions
│   ├── system_prompt_v1.txt   # Basic river mile marker analyst
│   └── system_prompt_v2.txt   # With scope boundaries
└── datasets/                  # Test datasets (CSVs)
    └── rivermile-eval-0/
        ├── evaluation.xml      # source question set (from mcp-builder Phase 4)
        └── examples/rivermile-eval-0.csv
```

## Prerequisites

Install the dev dependencies (Phoenix, LangChain, pandas, etc.):

```bash
uv sync --group dev
```

Set the following environment variables (e.g. in a `.env` at the repo root — see
`.env.example`):

```
USAI_API_KEY=...
USAI_BASE_URL=...     # judge + agent model gateway base URL
AGENT_MODEL=...       # model id used by the agent (e.g. claude_4_5_sonnet)
JUDGE_MODEL=...       # model id used by the judges (e.g. claude_4_6_sonnet)
```

The agent launches the MCP server with `uv run src/usace_iwr_server/app.py` from the
repo root (configured via `cwd` in `agent.py`), so no separate server process is needed.

## Quick Start

Run all commands from `eval/phoenix/`.

### 1. Start Phoenix

```bash
uv run arize-phoenix serve   # UI at http://localhost:6006, OTLP at :4317
```

### 2. Create the dataset in Phoenix

```bash
uv run create_dataset.py --dataset-name rivermile-eval-0
# validate only, no upload:
uv run create_dataset.py --dataset-name rivermile-eval-0 --dry-run
# list configured datasets:
uv run create_dataset.py --list
```

### 3. Run an experiment

```bash
uv run run_experiment.py --dataset-name rivermile-eval-0
# choose a system prompt version:
uv run run_experiment.py --dataset-name rivermile-eval-0 --system-prompt-version v2
```

View results in the Phoenix UI at http://localhost:6006.

## Dataset

**rivermile-eval-0** (10 questions) — spatial and attribute questions with a single
verifiable answer each (marker counts by river, mile-range filters, nearest-marker
lookup, bounding-box counts and mile lists, river code / river number, and data
source). Derived from `datasets/rivermile-eval-0/evaluation.xml`, the source question
set that lives alongside the dataset it produces. Answers were verified against the
live USACE service via `scripts/verify_live.py`.

CSV columns:
- `query` — the natural-language question (input)
- `responses` — the expected ground-truth answer (output / reference)

## System Prompts

- **v1 — Basic analyst:** river mile marker role, coordinate/geometry conventions,
  tool-selection guidance, unit caveats.
- **v2 — Scope boundaries:** adds explicit in-scope vs. out-of-scope guidance (refuses
  weather/general-knowledge/real-time-streamflow/lock-schedule/predictive/normative
  questions) while still answering factual River Mile Marker queries.

## Evaluators

Both use the `JUDGE_MODEL` (default `claude_4_6_sonnet`) via the USAi gateway.

### match_expected_response (`judges/correctness_judge.py`)
LLM-as-judge correctness: compares the agent's answer to the expected ground truth,
tolerating formatting differences (e.g. `111` vs `mile 111`, `RED` vs `RED River`, a
mile list regardless of ordering). Returns `correct` / `incorrect`.

### check_answer_scope (`judges/relevance_judge.py`)
Checks whether the agent answers in-scope River Mile Marker questions and refuses
out-of-scope ones. Returns `within_scope` / `out_of_scope`.

## Troubleshooting

- **Dataset not found in Phoenix:** run `create_dataset.py --dataset-name rivermile-eval-0` first.
- **System prompt file not found:** ensure `prompts/system_prompt_{version}.txt` exists (v1, v2).
- **Phoenix not running:** start it with `uv run arize-phoenix serve` and open http://localhost:6006.
- **MCP server fails to launch:** confirm `uv run src/usace_iwr_server/app.py` works from the repo root.
- **SSL certificate errors from the USACE service:** handled by the server's TLS context
  (`src/usace_iwr_server/utils.py`); if they persist, confirm your local trust store / certifi.
