"""AgentHack CLI."""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from .config import load_config
from .schemas import RunConfig
from .orchestrator import Orchestrator, run_from_checkpoint
from .utils import output

app = typer.Typer(
    name="agenthack",
    help="Run an AI hackathon from your terminal.",
    add_completion=False,
)
console = Console()

OUTPUT_BASE = Path("runs")


def _make_run_dir(run_id: str) -> Path:
    p = OUTPUT_BASE / run_id
    p.mkdir(parents=True, exist_ok=True)
    return p


def _load_run_config(run_id: str) -> RunConfig | None:
    config_path = OUTPUT_BASE / run_id / "config.json"
    if not config_path.exists():
        console.print(f"[red]Run '{run_id}' not found.[/red]")
        return None
    data = output.read_json(config_path)
    return RunConfig(**data)


@app.command()
def run(
    domains: str = typer.Option(..., "--domains", "-d", help="Comma-separated domains, e.g. 'healthcare,devtools'"),
    depth: str = typer.Option("standard", "--depth", help="fast | standard | deep"),
    teams: Optional[int] = typer.Option(None, "--teams", help="Number of parallel teams (overrides depth default)"),
    top_k: int = typer.Option(3, "--top-k", help="Number of winners to build"),
    checkpoint_after_scout: bool = typer.Option(False, "--checkpoint-after-scout", help="Pause after scout phase"),
    checkpoint_after_judging: bool = typer.Option(False, "--checkpoint-after-judging", help="Pause after judging"),
    no_build: bool = typer.Option(False, "--no-build", help="Skip build phase (research + judge only)"),
    dangerously_skip_permissions: bool = typer.Option(False, "--dangerously-skip-permissions", help="Pass --dangerously-skip-permissions to Claude Code in the build phase"),
    config_file: Optional[str] = typer.Option(None, "--config", help="Path to agenthack.yaml"),
    run_id: Optional[str] = typer.Option(None, "--run-id", help="Custom run ID (auto-generated if not set)"),
) -> None:
    """Run the full hackathon pipeline."""
    app_config = load_config(config_file)

    # Depth defaults for team count
    depth_teams = {"fast": 5, "standard": 10, "deep": 15}
    if teams is None:
        teams = app_config.defaults.get("teams", depth_teams.get(depth, 10))

    run_id = run_id or f"run_{uuid.uuid4().hex[:8]}"
    run_dir = _make_run_dir(run_id)

    config = RunConfig(
        run_id=run_id,
        domains=[d.strip() for d in domains.split(",")],
        depth=depth,
        teams=teams,
        top_k=top_k,
        checkpoint_after_scout=checkpoint_after_scout,
        checkpoint_after_judging=checkpoint_after_judging,
        no_build=no_build,
        dangerously_skip_permissions=dangerously_skip_permissions,
        output_dir=str(run_dir),
        judge_weights={
            "market": app_config.judge_weights.get("market", 0.25),
            "technical": app_config.judge_weights.get("technical", 0.25),
            "user": app_config.judge_weights.get("user", 0.25),
            "vc": app_config.judge_weights.get("vc", 0.25),
        },
        models={
            "scout": app_config.models.get("scout", "claude-sonnet-4-6"),
            "analyst": app_config.models.get("analyst", "claude-sonnet-4-6"),
            "strategist": app_config.models.get("strategist", "claude-sonnet-4-6"),
            "judges": app_config.models.get("judges", "claude-sonnet-4-6"),
        },
        budget=app_config.budget or {},
        scraping=app_config.scraping or {},
    )

    asyncio.run(Orchestrator(config).run())


@app.command()
def resume(
    run_id: str = typer.Option(..., "--run-id", help="Run ID to resume"),
    exclude: Optional[str] = typer.Option(None, "--exclude", help="Comma-separated problem IDs to exclude"),
) -> None:
    """Resume a run from the scout checkpoint."""
    exclude_list = [e.strip() for e in exclude.split(",")] if exclude else None
    asyncio.run(run_from_checkpoint(run_id, str(OUTPUT_BASE), exclude=exclude_list))


@app.command(name="judge")
def judge_cmd(
    run_id: str = typer.Option(..., "--run-id", help="Run ID to re-judge"),
    weights: Optional[str] = typer.Option(None, "--weights", help="e.g. market=0.3,tech=0.3,user=0.25,vc=0.15"),
) -> None:
    """Re-run judging on an existing run (with optional new weights)."""
    from .phases import hackathon as hackathon_phase, judge as judge_phase
    from .schemas import Problem, ResearchBrief, ProductSpec

    config = _load_run_config(run_id)
    if not config:
        return

    if weights:
        for pair in weights.split(","):
            k, v = pair.split("=")
            key_map = {"market": "market", "tech": "technical", "user": "user", "vc": "vc"}
            config.judge_weights[key_map.get(k, k)] = float(v)

    # Load existing phase2 outputs
    phase2_dir = Path(config.output_dir) / "phase2"
    problems_data = output.read_json(Path(config.output_dir) / "phase1" / "problems.json")
    problems = [Problem(**p) for p in problems_data]

    teams = []
    for team_dir in sorted(phase2_dir.glob("team_*")):
        # Find matching problem
        spec_json = team_dir / "spec.json"
        research_json = team_dir / "research.json"
        if not spec_json.exists():
            continue
        spec_data = output.read_json(spec_json)
        prob_id = spec_data.get("problem_id")
        problem = next((p for p in problems if p.id == prob_id), None)
        if not problem:
            continue
        research = None
        if research_json.exists():
            research = ResearchBrief(**output.read_json(research_json))
        spec = ProductSpec(**spec_data)
        teams.append((problem, research, spec))

    async def _run():
        return await judge_phase.run_judging(teams, config)

    asyncio.run(_run())
    console.print(f"[green]Re-judging complete. See {config.output_dir}/phase3/[/green]")


# Register as 'judge' command
@app.command(name="build")
def build_cmd(
    run_id: str = typer.Option(..., "--run-id", help="Run ID"),
    team: int = typer.Option(..., "--team", help="Team number to build"),
    dangerously_skip_permissions: bool = typer.Option(False, "--dangerously-skip-permissions", help="Pass --dangerously-skip-permissions to Claude Code"),
) -> None:
    """Build a specific team's demo from a past run."""
    from .phases import build as build_phase
    from .schemas import Problem, ResearchBrief, ProductSpec, LeaderboardEntry

    config = _load_run_config(run_id)
    if not config:
        return

    config.dangerously_skip_permissions = dangerously_skip_permissions

    team_dir = Path(config.output_dir) / "phase2" / f"team_{team:03d}"
    if not team_dir.exists():
        console.print(f"[red]Team {team} not found.[/red]")
        raise typer.Exit(1)

    spec_json = team_dir / "spec.json"
    research_json = team_dir / "research.json"
    problems_data = output.read_json(Path(config.output_dir) / "phase1" / "problems.json")
    problems = [Problem(**p) for p in problems_data]

    spec_data = output.read_json(spec_json) if spec_json.exists() else {}
    prob_id = spec_data.get("problem_id", "")
    problem = next((p for p in problems if p.id == prob_id), None)

    if not problem:
        console.print(f"[red]Could not find problem for team {team}[/red]")
        raise typer.Exit(1)

    research = ResearchBrief(**output.read_json(research_json)) if research_json.exists() else None
    spec = ProductSpec(**spec_data) if spec_data else None

    entry = LeaderboardEntry(
        problem_id=problem.id,
        problem_title=problem.title,
        final_score=0,
        market_score=0,
        technical_score=0,
        user_score=0,
        vc_score=0,
        rank=1,
    )

    async def _run():
        await build_phase._build_winner(1, entry, problem, research, spec, config)

    asyncio.run(_run())


@app.command()
def history() -> None:
    """List past runs."""
    if not OUTPUT_BASE.exists():
        console.print("[dim]No runs found.[/dim]")
        return

    table = Table(title="Past Runs")
    table.add_column("Run ID", style="bold")
    table.add_column("Domains")
    table.add_column("Depth")
    table.add_column("Teams")
    table.add_column("Status")

    for run_dir in sorted(OUTPUT_BASE.iterdir(), reverse=True):
        if not run_dir.is_dir():
            continue
        config_path = run_dir / "config.json"
        if not config_path.exists():
            continue
        try:
            data = output.read_json(config_path)
            has_phase4 = (run_dir / "phase4").exists()
            has_phase3 = (run_dir / "phase3").exists()
            has_phase2 = (run_dir / "phase2").exists()
            has_phase1 = (run_dir / "phase1").exists()
            status = (
                "complete" if has_phase4 else
                "judged" if has_phase3 else
                "researched" if has_phase2 else
                "scouted" if has_phase1 else
                "started"
            )
            table.add_row(
                data.get("run_id", run_dir.name),
                ", ".join(data.get("domains", [])),
                data.get("depth", "?"),
                str(data.get("teams", "?")),
                status,
            )
        except Exception:
            table.add_row(run_dir.name, "?", "?", "?", "error")

    console.print(table)


@app.command()
def show(
    run_id: str = typer.Option(..., "--run-id", help="Run ID"),
    team: Optional[int] = typer.Option(None, "--team", help="Show specific team output"),
) -> None:
    """View output from a past run."""
    run_dir = OUTPUT_BASE / run_id
    if not run_dir.exists():
        console.print(f"[red]Run '{run_id}' not found.[/red]")
        raise typer.Exit(1)

    if team:
        team_dir = run_dir / "phase2" / f"team_{team:03d}"
        if not team_dir.exists():
            console.print(f"[red]Team {team} not found.[/red]")
            raise typer.Exit(1)
        for fname in ["spec.md", "research.md"]:
            fpath = team_dir / fname
            if fpath.exists():
                console.print(f"\n[bold]── {fname} ──[/bold]")
                console.print(fpath.read_text())
    else:
        # Show summary or leaderboard
        summary = run_dir / "summary.md"
        if summary.exists():
            console.print(summary.read_text())
        else:
            leaderboard = run_dir / "phase3" / "leaderboard.md"
            if leaderboard.exists():
                console.print(leaderboard.read_text())
            else:
                problems = run_dir / "phase1" / "problems_detailed.md"
                if problems.exists():
                    console.print(problems.read_text())


if __name__ == "__main__":
    app()
