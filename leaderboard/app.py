import os
from pathlib import Path

import gradio as gr

from data_loader import (
    build_leaderboard_df, build_runs_df,
    fetch_log, extract_log_section, load_results,
)

_env_dir = os.environ.get("RESULTS_DIR")
DEFAULT_RESULTS_DIR = (
    Path(_env_dir) if _env_dir
    else Path(__file__).resolve().parent.parent / "results" / "aggregated"
)

_DISPLAY_COLS = [
    "Tool", "Repo", "Slug", "Difficulty",
    "Apply", "Reason", "Test", "Baseline",
    "Diff Lines", "Cost $", "Secs",
]

# Map column name → log section to show when that column is clicked
_COL_TO_LOG_SECTION = {
    "Baseline": "Baseline test (pre-patch)",
    "Test":     "Post-pipeline test",
    "Apply":    "Measure diff size",
    "Diff Lines": "Measure diff size",
}


def _load():
    results, source = load_results(DEFAULT_RESULTS_DIR)
    lb_df   = build_leaderboard_df(results)
    runs_df = build_runs_df(results)
    return lb_df, runs_df, len(results), source


def create_app() -> gr.Blocks:
    lb_df, runs_df, n_results, source = _load()
    display_df = runs_df[_DISPLAY_COLS] if not runs_df.empty else runs_df
    n_tools = lb_df["Tool"].nunique() if not lb_df.empty else 0

    with gr.Blocks(title="Backport Agent Leaderboard", theme=gr.themes.Soft()) as app:
        gr.Markdown("# 🏆 Backport Agent Leaderboard")

        stats_md = gr.Markdown(
            f"**{n_results}** benchmark runs · **{n_tools}** tools · source: *{source}*"
        )
        runs_state = gr.State(runs_df)

        with gr.Tabs():

            # ── Leaderboard ──────────────────────────────────────────────────
            with gr.TabItem("Leaderboard"):
                gr.Markdown("""
Each cell shows **Apply Rate / Full Pass Rate** for that repo.

| Symbol | Meaning |
|--------|---------|
| **Apply Rate** | Did the agent produce a non-empty patch that applied cleanly? |
| **Full Pass Rate** | Did the patch apply AND the unit tests pass AND the baseline was clean? |
| ⏳ | Jobs are still running — no results yet for this tool + repo |
| 0.0% | Results are in, but all cases failed |
| — | No data (unexpected) |
                """)
                lb_table = gr.Dataframe(value=lb_df, interactive=False, wrap=True)

            # ── All Runs ─────────────────────────────────────────────────────
            with gr.TabItem("All Runs"):
                gr.Markdown(
                    "One row per benchmark case. "
                    "**Click any row** to view the pod log. "
                    "Clicking the **Test**, **Baseline**, or **Apply** column "
                    "jumps to that specific section of the log."
                )
                runs_table = gr.Dataframe(
                    value=display_df,
                    interactive=False,
                    wrap=True,
                )

                gr.Markdown("### 📋 Log Viewer")
                log_header  = gr.Markdown("*Click a row above to load its log.*")
                log_section = gr.Markdown("")   # shows which section is highlighted
                log_viewer  = gr.Code(
                    value="",
                    language=None,
                    lines=35,
                    label="Pod log",
                    interactive=False,
                )

            # ── About ────────────────────────────────────────────────────────
            with gr.TabItem("About"):
                gr.Markdown("""
## What is this leaderboard?

We are evaluating AI tools on their ability to **automatically backport bug fixes** — taking a fix that was applied to the latest version of a codebase and applying it cleanly to an older version.

---

## Repos under evaluation

| Repo | Language | Build tool |
|------|----------|------------|
| `crate/crate` | Java | Maven |
| `cri-o/cri-o` | Go | make / go build |
| `django/django` | Python | runtests.py |

---

## Tools being compared

**Raw Claude (Opus 4.6)**
A single LLM call. We show Claude the original fix diff and ask it to produce a backport patch. No retries, no build check.

**Amalgamator / Opus 4.6**
The full Amalgamator pipeline, which runs multiple phases automatically:
1. **Semantic triage** — Claude analyzes the commit to assess difficulty and whether to proceed
2. **Prerequisite detection** — identifies and applies any dependency commits needed first
3. **Test file porting** — ports relevant test cases to the target branch
4. **Cherry-pick** — attempts `git cherry-pick` with multiple merge strategies
5. **LLM conflict resolution** — if cherry-pick has conflicts, Claude resolves them iteratively
6. **Build + test verification** — runs the build and test suite to confirm correctness
7. **Semantic equivalence check** — compares the result against the ground truth

---

## What each metric means

**Apply** (was the patch applied?)
> Did the agent produce any code changes at all, and did those changes apply cleanly to the target branch?
> PASS = yes. FAIL = the patch was empty, didn't apply, or caused errors.

**Baseline** (were tests passing before?)
> We run the test suite on the clean target branch *before* any backporting happens.
> PASS = the repo was in a healthy state before we touched it.
> FAIL = the tests were already broken — so any later failure is not caused by our backport.

**Test** (do tests pass after?)
> We run the same test suite *after* applying the backport.
> PASS = the backport did not break anything.
> FAIL = something broke after backporting.

**Semantic Equivalence** (does the agent match the real backport?)
> We compare the agent's patch to the **ground-truth backport commit** in the repository.
> PASS = the agent produced exactly the same code changes as the real human backport.
> FAIL = the changes differ from the ground truth (the agent got the right idea, but the code was different).
> This is the gold standard — it tells us whether the agent replicated what a human engineer actually did.

**Apply Rate**
> Out of all benchmark cases, what fraction did the agent successfully patch (Apply = PASS)?

**Full Pass Rate**
> Out of all benchmark cases, what fraction had Apply = PASS AND Test = PASS AND Baseline = PASS?
> This is the strictest measure — the backport was applied *and* verified to be correct.

**Diff Lines**
> How many lines of code did the agent's patch change?

**Cost $**
> How much did the LLM API calls cost (USD) for this case?

---

## How the pipeline works (step by step)

1. **Clone** the target branch at the pre-fix commit
2. **Baseline test** — run the test suite to confirm the branch is healthy
3. **Apply backport** — Raw Claude generates a diff; Amalgamator does cherry-pick + conflict resolution
4. **Post-patch test** — run the same test suite again
5. **Save results** — metrics are stored in OpenShift ConfigMaps and shown here live

Click any row in **All Runs** to see the full step-by-step log for that case.
                """)

        # ── Refresh ──────────────────────────────────────────────────────────
        with gr.Row():
            refresh_btn = gr.Button("🔄 Refresh results", variant="secondary")
            gr.Markdown("*(auto-refreshes every 60 s while jobs are running)*")

        def refresh():
            lb, runs, n_r, src = _load()
            disp = runs[_DISPLAY_COLS] if not runs.empty else runs
            n_t  = lb["Tool"].nunique() if not lb.empty else 0
            return (
                lb, disp, runs,
                f"**{n_r}** benchmark runs · **{n_t}** tools · source: *{src}*",
                "", "*Refreshed — click a row to load its log.*", "",
            )

        _refresh_outputs = [lb_table, runs_table, runs_state, stats_md,
                            log_viewer, log_header, log_section]

        refresh_btn.click(fn=refresh, outputs=_refresh_outputs)

        # Auto-refresh every 60 s
        timer = gr.Timer(60)
        timer.tick(fn=refresh, outputs=_refresh_outputs)

        # ── Row / cell click → log viewer ────────────────────────────────────
        def on_select(evt: gr.SelectData, full_df):
            if full_df is None or full_df.empty:
                return "*No data*", "", ""

            row_idx = evt.index[0]
            col_idx = evt.index[1] if isinstance(evt.index, (list, tuple)) and len(evt.index) > 1 else None

            if row_idx >= len(full_df):
                return "*Index out of range*", "", ""

            row      = full_df.iloc[row_idx]
            slug     = str(row.get("_slug",     row.get("Slug", "")))
            tool_key = str(row.get("_tool_key", ""))
            repo     = str(row.get("_repo",     row.get("Repo", "")))
            tool_lbl = str(row.get("Tool", ""))

            test_cmd = str(row.get("_test_cmd", ""))

            header = (
                f"**{tool_lbl}** · `{repo}` · slug `{slug}` · "
                f"{row.get('Difficulty','')} · "
                f"Apply: **{row.get('Apply','')}** · "
                f"Test: **{row.get('Test','')}** · "
                f"Baseline: **{row.get('Baseline','')}**"
            )
            if test_cmd:
                header += f"\n\n🧪 **Test command:** `{test_cmd}`"

            log_text = fetch_log(slug, tool_key, repo)

            # If user clicked a specific column, jump to that log section
            col_name = _DISPLAY_COLS[col_idx] if col_idx is not None and col_idx < len(_DISPLAY_COLS) else None
            section_name = _COL_TO_LOG_SECTION.get(col_name)

            if section_name:
                snippet = extract_log_section(log_text, section_name)
                section_md = (
                    f"**Showing section:** `=== {section_name} ===`\n\n"
                    f"```\n{snippet[:3000]}\n```"
                )
                return header, section_md, log_text
            else:
                return header, "", log_text

        runs_table.select(
            fn=on_select,
            inputs=[runs_state],
            outputs=[log_header, log_section, log_viewer],
        )

    return app


if __name__ == "__main__":
    app = create_app()
    app.launch(server_name="0.0.0.0", server_port=7860)
