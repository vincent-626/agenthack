"""Phase 4: Build Sprint — Top 3 demos via Claude Code."""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

from rich.console import Console

from ..schemas import Problem, ResearchBrief, ProductSpec, LeaderboardEntry, RunConfig
from ..utils import output

console = Console()

BUILD_PROMPT_TEMPLATE = """Build a working demo application based on the following product spec and market research.

## Product Spec

{spec_md}

## Market Research

{research_md}

## Instructions

1. Scaffold the project based on the demo_format specified in the spec
2. Implement all MVP features from the spec, following the user flows exactly
3. Include the seed/mock data described so the demo is immediately impressive when launched
4. Add a README.md with:
   - What the product does and what problem it solves
   - How to install and run it (step-by-step)
   - A walkthrough of key features
5. Make sure the application actually runs without errors

Use ONLY common, well-supported libraries. Keep the code clean and straightforward.
The demo should be production-quality in UX but MVP in scope.

IMPORTANT: The demo MUST work when run. Test your implementation."""


def _render_spec(spec: ProductSpec | None) -> str:
    if not spec:
        return "No spec available."
    lines = [
        f"# {spec.product_name}",
        f"**Pitch:** {spec.pitch}",
        f"**Value prop:** {spec.value_prop}",
        f"**Differentiator:** {spec.differentiator}",
        f"**Demo format:** {spec.demo_format}",
        f"\n## Tech Stack",
        f"- Frontend: {spec.tech_stack.frontend}",
        f"- Backend: {spec.tech_stack.backend}",
        f"- Database: {spec.tech_stack.database}",
        f"- Libraries: {', '.join(spec.tech_stack.key_libraries)}",
        f"\n## MVP Features",
    ]
    for f in spec.mvp_features:
        lines.append(f"### {f.name}\n{f.description}")
        if f.user_flow:
            lines.append("User flow: " + " → ".join(f.user_flow))
        if f.acceptance_criteria:
            lines += [f"- {c}" for c in f.acceptance_criteria]
    if spec.data_model.entities:
        lines.append("\n## Data Model")
        for e in spec.data_model.entities:
            lines.append(f"**{e.name}:** {', '.join(e.fields)}")
    if spec.seed_data:
        lines += ["\n## Seed Data", spec.seed_data]
    if spec.monetization:
        lines += ["\n## Monetization", spec.monetization]
    if spec.out_of_scope:
        lines += ["\n## Out of Scope", ", ".join(spec.out_of_scope)]
    return "\n".join(lines)


def _render_research(research: ResearchBrief | None) -> str:
    if not research:
        return "No research available."
    p = research.target_persona
    lines = [
        f"**Target user:** {p.role} at {p.company_size} — pays {p.willingness_to_pay}",
        f"**Current workflow:** {p.current_workflow}",
        f"**Key insight:** {research.key_insight}",
    ]
    if research.timing_signals:
        lines += ["\n**Timing signals:**"] + [f"- {s}" for s in research.timing_signals]
    if research.feasibility_flags:
        lines += ["\n**Feasibility flags:**"] + [f"- {f}" for f in research.feasibility_flags]
    if research.competitors:
        lines.append("\n**Competitors:**")
        for c in research.competitors:
            weak = "; ".join(c.weaknesses[:2])
            lines.append(f"- {c.name} ({c.pricing}) — gaps: {weak}")
    return "\n".join(lines)


async def _build_winner(
    rank: int,
    entry: LeaderboardEntry,
    problem: Problem,
    research: ResearchBrief | None,
    spec: ProductSpec | None,
    config: RunConfig,
) -> bool:
    """Build one winner's demo using Claude Code."""
    winner_dir = Path(config.output_dir) / "phase4" / f"winner_{rank}"
    demo_dir = winner_dir / "demo"
    output.ensure_dir(demo_dir)

    console.print(f"  [cyan]Building Winner #{rank}:[/cyan] {entry.problem_title}")

    spec_md = _render_spec(spec)
    research_md = _render_research(research)

    build_prompt = BUILD_PROMPT_TEMPLATE.format(
        spec_md=spec_md,
        research_md=research_md,
    )
    # Write into demo/ so it's within Claude Code's working directory sandbox
    prompt_file = demo_dir / "build_prompt.md"
    output.write_md(prompt_file, build_prompt)

    # Invoke Claude Code as a subprocess.
    # build_prompt.md lives in demo/ (the cwd), so Claude Code can read it freely.
    instruction = "Read build_prompt.md and follow the instructions exactly to build the application in this directory. Delete build_prompt.md when done."
    cmd = [
        "claude",
        "-p", instruction,
        "--output-format", "text",
        "--max-turns", "60",
    ]
    if config.dangerously_skip_permissions:
        cmd.append("--dangerously-skip-permissions")

    log_path = winner_dir / "build.log"
    err_path = winner_dir / "build_errors.log"
    console.print(f"    Running Claude Code for winner #{rank}... (tail -f {log_path})")
    try:
        with open(log_path, "w") as log_f, open(err_path, "w") as err_f:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=str(demo_dir),
                stdout=log_f,
                stderr=err_f,
            )
            await asyncio.wait_for(
                proc.wait(),
                timeout=1800,
            )

        build_log = log_path.read_text()
        build_err = err_path.read_text()

        # Check that real files were created (exclude the prompt file we seeded)
        generated_files = [f for f in demo_dir.iterdir() if f.name != "build_prompt.md"] if demo_dir.exists() else []

        if proc.returncode == 0 and generated_files:
            console.print(f"  [green]✓ Winner #{rank} built successfully ({len(generated_files)} files)[/green]")
            return True
        elif proc.returncode == 0 and not generated_files:
            console.print(f"  [red]✗ Winner #{rank}: Claude Code exited cleanly but created no files[/red]")
            if build_log:
                console.print(f"  [dim]{build_log[:500]}[/dim]")
            return False
        else:
            console.print(f"  [red]✗ Winner #{rank} build failed (exit code {proc.returncode})[/red]")
            if build_err:
                console.print(f"  [dim]{build_err[:500]}[/dim]")
            return False

    except asyncio.TimeoutError:
        console.print(f"  [red]✗ Winner #{rank} build timed out[/red]")
        return False
    except FileNotFoundError:
        console.print(f"  [red]✗ Claude Code CLI not found. Install it with: npm install -g @anthropic-ai/claude-code[/red]")
        # Write a placeholder README
        _write_placeholder_readme(demo_dir, entry, spec, research)
        return False
    except Exception as e:
        console.print(f"  [red]✗ Winner #{rank} build error: {e}[/red]")
        return False


def _write_placeholder_readme(
    demo_dir: Path,
    entry: LeaderboardEntry,
    spec: ProductSpec | None,
    research: ResearchBrief | None,
) -> None:
    """Write a placeholder README when Claude Code is unavailable."""
    lines = [f"# {entry.problem_title}", ""]
    if spec:
        lines += [
            f"> {spec.pitch}", "",
            f"## What is this?", "",
            spec.value_prop, "",
            f"## Why it's different", "",
            spec.differentiator, "",
            f"## MVP Features", "",
        ]
        for feat in spec.mvp_features:
            lines += [f"### {feat.name}", feat.description, ""]
        lines += [
            f"## Tech Stack", "",
            f"- **Frontend**: {spec.tech_stack.frontend}",
            f"- **Backend**: {spec.tech_stack.backend}",
            f"- **Database**: {spec.tech_stack.database}", "",
        ]
    lines += [
        "## Build Instructions",
        "",
        "> This demo was not built automatically because Claude Code CLI was not available.",
        "> To build it, run the `build_prompt.md` with Claude Code:",
        "",
        "```bash",
        "# Install Claude Code",
        "npm install -g @anthropic-ai/claude-code",
        "",
        "# Build the demo",
        f"mkdir -p demo && cd demo",
        f"cat ../build_prompt.md | claude",
        "```",
    ]
    output.write_md(demo_dir / "README.md", "\n".join(lines))


async def run_build_sprint(
    top3: list[LeaderboardEntry],
    teams: list[tuple[Problem, ResearchBrief | None, ProductSpec | None]],
    config: RunConfig,
) -> None:
    """Run Phase 4: build top 3 winners in parallel."""
    output.ensure_dir(Path(config.output_dir) / "phase4")

    teams_map = {p.id: (p, r, s) for p, r, s in teams}

    tasks = []
    for rank, entry in enumerate(top3[:3], 1):
        data = teams_map.get(entry.problem_id)
        if not data:
            console.print(f"  [yellow]No team data for {entry.problem_id}[/yellow]")
            continue
        problem, research, spec = data
        tasks.append(_build_winner(rank, entry, problem, research, spec, config))

    results = await asyncio.gather(*tasks, return_exceptions=True)

    successes = sum(1 for r in results if r is True)
    console.print(f"  [green]✓ Build sprint complete: {successes}/{len(tasks)} demos built[/green]")
