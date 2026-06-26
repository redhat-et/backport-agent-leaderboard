import os
from pathlib import Path

import gradio as gr

from data_loader import build_leaderboard_df, build_runs_df, load_results

DEFAULT_RESULTS_DIR = Path(__file__).resolve().parent.parent / "results" / "aggregated"


def create_app(results_dir: Path | None = None) -> gr.Blocks:
    results_dir = Path(results_dir or DEFAULT_RESULTS_DIR)

    def load_data():
        results = load_results(results_dir)
        leaderboard_df = build_leaderboard_df(results)
        runs_df = build_runs_df(results)
        n_results = len(results)
        n_tools = leaderboard_df["Name"].nunique() if not leaderboard_df.empty else 0
        return leaderboard_df, runs_df, n_results, n_tools

    with gr.Blocks(title="Backport Agent Leaderboard") as app:
        gr.Markdown("# Backport Agent Leaderboard")

        leaderboard_df, runs_df, n_results, n_tools = load_data()

        gr.Markdown(
            f"**{n_results}** benchmark runs | **{n_tools}** tools"
        )

        with gr.Tabs():
            with gr.TabItem("Leaderboard"):
                search_box = gr.Textbox(label="Search by name", placeholder="Type to filter...")
                category_filter = gr.CheckboxGroup(
                    choices=["Open Source", "Proprietary"],
                    value=["Open Source", "Proprietary"],
                    label="Category",
                )
                leaderboard_table = gr.Dataframe(
                    value=leaderboard_df,
                    interactive=False,
                    wrap=True,
                )

            with gr.TabItem("Benchmark Runs"):
                default_cols = ["Category", "Name", "Benchmark", "Score", "Avg Cost Per Task"]
                all_cols = list(runs_df.columns) if not runs_df.empty else default_cols
                extra_cols = [c for c in all_cols if c not in default_cols]
                column_picker = gr.CheckboxGroup(
                    choices=extra_cols,
                    value=[],
                    label="Additional columns",
                )
                runs_table = gr.Dataframe(
                    value=runs_df[default_cols] if not runs_df.empty else runs_df,
                    interactive=False,
                    wrap=True,
                )

            with gr.TabItem("About"):
                about_path = Path(__file__).parent / "about.md"
                if about_path.exists():
                    gr.Markdown(about_path.read_text())
                else:
                    gr.Markdown("About content not available.")

    return app


if __name__ == "__main__":
    app = create_app()
    app.launch()
