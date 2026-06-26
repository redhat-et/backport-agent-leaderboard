# About the Backport Agent Leaderboard

This leaderboard evaluates automated backporting tools against a curated dataset of known-good backports from open-source projects.

## How It Works

1. Each tool is given an original commit and a target branch
2. The tool produces a candidate backport diff
3. The diff is compared to the known-good backport for semantic equivalence
4. Results are aggregated by tool and benchmark subset

## Metrics

- **Score**: Percentage of backports where the tool produced a semantically equivalent diff
- **Avg Cost Per Task**: Mean LLM API cost in USD per backport
- **Avg Seconds Per Task**: Mean wall-clock time per backport
- **Avg Input/Output Tokens**: Mean token usage per backport

## Submitting Results

Results are stored as JSON files. Contact the maintainers to submit benchmark results for a new tool.
