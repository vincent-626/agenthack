"""Main orchestrator — manages phase transitions and run state."""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from rich.console import Console
from rich.rule import Rule

from .schemas import Problem, ResearchBrief, ProductSpec, LeaderboardEntry, RunConfig
from .utils import output
from .phases import scout, hackathon, judge, build

console = Console()


class Orchestrator:
    def __init__(self, config: RunConfig) -> None:
        self.config = config
        self.output_dir = Path(config.output_dir)

    def _save_config(self) -> None:
        output.ensure_dir(self.output_dir)
        output.write_json(self.output_dir / "config.json", self.config)

    def _checkpoint(self, phase_name: str) -> bool:
        """Pause and ask user to continue. Returns True to continue, False to abort."""
        console.print(f"\n[bold yellow]⏸  CHECKPOINT after {phase_name}[/bold yellow]")
        console.print(f"[dim]Output saved to: {self.output_dir}[/dim]")
        console.print("Review the output, then press [bold]Enter[/bold] to continue or [bold]Ctrl+C[/bold] to stop.")
        try:
            input()
            return True
        except (KeyboardInterrupt, EOFError):
            console.print("\n[yellow]Run paused. Resume with: agenthack resume --run-id {self.config.run_id}[/yellow]")
            return False

    async def run(self) -> None:
        """Execute the full pipeline."""
        self._save_config()

        console.print(Rule("[bold blue]AgentHack[/bold blue]"))
        console.print(f"Run ID: [bold]{self.config.run_id}[/bold]")
        console.print(f"Domains: {', '.join(self.config.domains)}")
        console.print(f"Depth: {self.config.depth} | Teams: {self.config.teams} | Top K: {self.config.top_k}")
        console.print()

        # ── Phase 1: Scout ────────────────────────────────────────────────────
        console.print(Rule("[cyan]Phase 1: Scout — Problem Discovery[/cyan]"))
        problems = await scout.run_scout(self.config)

        if not problems:
            console.print("[red]No problems discovered. Aborting.[/red]")
            return

        if self.config.checkpoint_after_scout:
            if not self._checkpoint("Scout"):
                return

        # ── Phase 2: Hackathon ────────────────────────────────────────────────
        console.print(Rule("[cyan]Phase 2: Hackathon — Research & Strategy[/cyan]"))
        teams = await hackathon.run_hackathon(problems, self.config)

        # ── Phase 3: Demo Day ─────────────────────────────────────────────────
        console.print(Rule("[cyan]Phase 3: Demo Day — Judging[/cyan]"))
        leaderboard = await judge.run_judging(teams, self.config)

        if self.config.checkpoint_after_judging:
            if not self._checkpoint("Demo Day"):
                return

        # ── Phase 4: Build Sprint ─────────────────────────────────────────────
        if not self.config.no_build:
            console.print(Rule("[cyan]Phase 4: Build Sprint — Top 3 Demos[/cyan]"))
            top3 = leaderboard[:self.config.top_k]
            await build.run_build_sprint(top3, teams, self.config)

        # ── Summary ───────────────────────────────────────────────────────────
        self._write_summary(leaderboard, teams)

        console.print(Rule("[bold green]Complete![/bold green]"))
        console.print(f"\n[bold]Top 3 Winners:[/bold]")
        for entry in leaderboard[:3]:
            console.print(f"  {entry.rank}. [bold]{entry.problem_title}[/bold] ({entry.final_score:.2f}/10)")
        console.print(f"\n[dim]Full output: {self.output_dir}/[/dim]")

    def _write_summary(
        self,
        leaderboard: list[LeaderboardEntry],
        teams: list[tuple[Problem, ResearchBrief | None, ProductSpec | None]],
    ) -> None:
        teams_map = {p.id: (p, r, s) for p, r, s in teams}
        lines = [
            f"# AgentHack Run Summary",
            f"",
            f"**Run ID**: {self.config.run_id}  ",
            f"**Domains**: {', '.join(self.config.domains)}  ",
            f"**Depth**: {self.config.depth} | **Teams**: {self.config.teams}",
            f"",
            f"## Leaderboard",
            f"",
            f"| Rank | Idea | Score |",
            f"|------|------|-------|",
        ]
        for e in leaderboard:
            trophy = "🥇" if e.rank == 1 else "🥈" if e.rank == 2 else "🥉" if e.rank == 3 else ""
            lines.append(f"| {e.rank} {trophy} | {e.problem_title} | {e.final_score:.2f} |")

        lines += ["", "## Top 3 Details", ""]
        for entry in leaderboard[:3]:
            data = teams_map.get(entry.problem_id)
            lines.append(f"### #{entry.rank}: {entry.problem_title}")
            if data:
                _, _, spec = data
                if spec:
                    lines.append(f"**{spec.product_name}** — {spec.pitch}")
                    lines.append(f"> {spec.value_prop}")
            if entry.narrative:
                lines.append(f"\n{entry.narrative}")
            if not self.config.no_build:
                lines.append(f"\n[Demo](phase4/winner_{entry.rank}/demo/)")
            lines.append("")

        output.write_md(self.output_dir / "summary.md", "\n".join(lines))


async def run_from_checkpoint(
    run_id: str,
    output_base: str = "output",
    exclude: list[str] | None = None,
) -> None:
    """Resume a run from after the scout checkpoint."""
    run_dir = Path(output_base) / run_id
    config_path = run_dir / "config.json"

    if not config_path.exists():
        console.print(f"[red]Run {run_id} not found at {run_dir}[/red]")
        return

    config_data = output.read_json(config_path)
    config = RunConfig(**config_data)
    config.output_dir = str(run_dir)

    # Load existing problems
    problems_path = run_dir / "phase1" / "problems.json"
    if not problems_path.exists():
        console.print("[red]No scout output found. Run from scratch.[/red]")
        return

    problems_data = output.read_json(problems_path)
    problems = [Problem(**p) for p in problems_data]

    # Apply exclusions
    if exclude:
        problems = [p for p in problems if p.id not in exclude]
        console.print(f"Excluded {len(exclude)} problem(s). Running with {len(problems)} problems.")

    orch = Orchestrator(config)

    # Continue from hackathon
    console.print(Rule("[cyan]Phase 2: Hackathon — Research & Strategy[/cyan]"))
    teams = await hackathon.run_hackathon(problems, config)

    console.print(Rule("[cyan]Phase 3: Demo Day — Judging[/cyan]"))
    leaderboard = await judge.run_judging(teams, config)

    if not config.no_build:
        console.print(Rule("[cyan]Phase 4: Build Sprint — Top 3 Demos[/cyan]"))
        top3 = leaderboard[:config.top_k]
        await build.run_build_sprint(top3, teams, config)

    orch._write_summary(leaderboard, teams)
    console.print(Rule("[bold green]Complete![/bold green]"))
