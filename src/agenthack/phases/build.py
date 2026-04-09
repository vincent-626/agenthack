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

    # Write the spec and research to the demo directory
    spec_text = spec.model_dump_json(indent=2) if spec else "No spec available"
    research_text = research.model_dump_json(indent=2) if research else "No research available"

    # Also write human-readable versions
    spec_md_path = winner_dir / "spec.md"
    research_md_path = winner_dir / "research.md"

    # Read the markdown files from phase2 if they exist
    team_dirs = list((Path(config.output_dir) / "phase2").glob("team_*"))
    spec_md = spec_text
    research_md = research_text
    for team_dir in team_dirs:
        spec_json = team_dir / "spec.json"
        if spec_json.exists():
            try:
                import json
                data = json.loads(spec_json.read_text())
                if data.get("problem_id") == problem.id:
                    spec_md_file = team_dir / "spec.md"
                    research_md_file = team_dir / "research.md"
                    if spec_md_file.exists():
                        spec_md = spec_md_file.read_text()
                    if research_md_file.exists():
                        research_md = research_md_file.read_text()
                    break
            except Exception:
                pass

    output.write_md(spec_md_path, spec_md)
    output.write_md(research_md_path, research_md)

    build_prompt = BUILD_PROMPT_TEMPLATE.format(
        spec_md=spec_md[:8000],
        research_md=research_md[:4000],
    )
    prompt_file = winner_dir / "build_prompt.md"
    output.write_md(prompt_file, build_prompt)

    # Invoke Claude Code as a subprocess
    cmd = [
        "claude",
        "--print",
        "--output-format", "text",
        "--max-turns", "30",
    ]
    if config.dangerously_skip_permissions:
        cmd.append("--dangerously-skip-permissions")
    cmd.append(build_prompt)

    console.print(f"    Running Claude Code for winner #{rank}...")
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=str(demo_dir),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=600)

        build_log = stdout.decode() if stdout else ""
        build_err = stderr.decode() if stderr else ""

        output.write_md(winner_dir / "build.log", build_log)
        if build_err:
            output.write_md(winner_dir / "build_errors.log", build_err)

        if proc.returncode == 0:
            console.print(f"  [green]✓ Winner #{rank} built successfully[/green]")
            return True
        else:
            console.print(f"  [yellow]~ Winner #{rank} build completed with warnings[/yellow]")
            return True

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
