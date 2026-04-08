"""Phase 1: Scout — Problem Discovery."""

from __future__ import annotations

import json
from pathlib import Path

from rich.console import Console

from ..schemas import Problem, Evidence, RunConfig
from ..utils import llm, scraper, output

console = Console()

DEPTH_QUERIES = {
    "fast": 2,
    "standard": 4,
    "deep": 6,
}

SCOUT_SYSTEM = """You are an expert market researcher and problem discovery analyst.
Your job is to identify real, painful problems that people experience and that could be solved with software.
Focus on problems with strong evidence from actual user complaints — not hypothetical needs.
Always return valid JSON."""

DISCOVERY_PROMPT = """Research pain points and problems in the domain: {domain}

Search for complaints, frustrations, and unmet needs across:
- Reddit (subreddit complaints, "I hate that..." posts, feature requests)
- Hacker News (Ask HN, frustrated developer posts)
- Product Hunt reviews (low-rated products, repeated criticisms)
- G2/Capterra reviews (1-2 star reviews, recurring negative themes)
- Twitter/X frustrated user threads

For each source, look for problems that are:
1. Frequently mentioned (many people have this problem)
2. High intensity (people are genuinely frustrated, not mildly annoyed)
3. Poorly solved by existing tools (no good solution exists)

Return a JSON array of problems found. Each problem:
{{
  "title": "Short, specific problem title (5-10 words)",
  "description": "2-3 sentence problem statement with specific pain points",
  "sources_found": ["reddit", "hackernews", etc.],
  "example_quotes": ["actual quote from user", "another quote"],
  "existing_solutions": ["tool A", "tool B"],
  "why_solutions_fail": "Why current solutions don't fully solve this",
  "why_now": "Any timing signal — new tech, regulation change, trend"
}}

Return 5-8 distinct problems. Be specific and evidence-based."""

SCORE_PROMPT = """You are evaluating a list of discovered problems to rank them for a hackathon.

Problems discovered:
{problems_json}

Score each problem on three dimensions (0-10 each):
- frequency_score: How often is this problem mentioned? (10 = extremely common)
- intensity_score: How frustrated are users? (10 = hair-on-fire, mission-critical)
- solution_gap_score: How poorly do existing solutions address this? (10 = no good solution exists)

Also compute: overall_score = (frequency * 0.3 + intensity * 0.4 + solution_gap * 0.3)

Return a JSON array with ALL problems scored and ranked by overall_score descending.
Each entry:
{{
  "id": "prob_001",  (sequential, zero-padded)
  "title": "...",
  "domain": "{domain}",
  "description": "...",
  "frequency_score": X.X,
  "intensity_score": X.X,
  "solution_gap_score": X.X,
  "overall_score": X.X,
  "evidence": [
    {{"source": "reddit", "url": "", "snippet": "actual user quote"}}
  ],
  "existing_solutions": ["..."],
  "why_now": "..."
}}"""


async def run_scout(config: RunConfig) -> list[Problem]:
    """Run Phase 1: discover and rank problems across all domains."""
    output_dir = Path(config.output_dir) / "phase1"
    output.ensure_dir(output_dir)
    output.ensure_dir(output_dir / "raw_signals")

    model = config.models.get("scout", "claude-sonnet-4-6")
    num_queries = DEPTH_QUERIES.get(config.depth, 4)
    all_problems: list[dict] = []
    problem_counter = 1

    for domain in config.domains:
        console.print(f"  [cyan]Scouting domain:[/cyan] {domain}")

        # Discover problems using web search
        discovery_result = llm.call_with_search(
            model=model,
            system=SCOUT_SYSTEM,
            prompt=DISCOVERY_PROMPT.format(domain=domain),
            max_tokens=8192,
        )

        # Save raw signals
        output.write_md(output_dir / "raw_signals" / f"{domain.replace(' ', '_')}_raw.md", discovery_result)

        # Parse discovered problems
        try:
            raw_problems = llm.extract_json(discovery_result)
            if not isinstance(raw_problems, list):
                raw_problems = [raw_problems]
        except ValueError:
            console.print(f"  [yellow]Warning: Could not parse problems for {domain}[/yellow]")
            raw_problems = []

        # Score and rank problems for this domain
        if raw_problems:
            score_result = llm.call(
                model=model,
                system=SCOUT_SYSTEM,
                prompt=SCORE_PROMPT.format(
                    problems_json=json.dumps(raw_problems, indent=2),
                    domain=domain,
                ),
                max_tokens=8192,
            )
            try:
                scored = llm.extract_json(score_result)
                if not isinstance(scored, list):
                    scored = [scored]
                # Re-assign IDs sequentially across domains
                for p in scored:
                    p["id"] = f"prob_{problem_counter:03d}"
                    p["domain"] = domain
                    problem_counter += 1
                all_problems.extend(scored)
            except ValueError:
                console.print(f"  [yellow]Warning: Could not score problems for {domain}[/yellow]")

    # Global deduplication + final ranking
    if not all_problems:
        console.print("[red]No problems discovered.[/red]")
        return []

    all_problems.sort(key=lambda p: p.get("overall_score", 0), reverse=True)

    # Take top N problems (one per team)
    top_problems = all_problems[:config.teams]

    # Parse into schema
    problems: list[Problem] = []
    for p in top_problems:
        try:
            evidence = [Evidence(**e) for e in p.get("evidence", [])]
            problems.append(Problem(
                id=p["id"],
                title=p.get("title", "Untitled"),
                domain=p.get("domain", config.domains[0]),
                description=p.get("description", ""),
                frequency_score=float(p.get("frequency_score", 5)),
                intensity_score=float(p.get("intensity_score", 5)),
                solution_gap_score=float(p.get("solution_gap_score", 5)),
                overall_score=float(p.get("overall_score", 5)),
                evidence=evidence,
                existing_solutions=p.get("existing_solutions", []),
                why_now=p.get("why_now", ""),
            ))
        except Exception as e:
            console.print(f"  [yellow]Skipping malformed problem: {e}[/yellow]")

    # Write outputs
    output.write_json(output_dir / "problems.json", problems)
    _write_problems_md(output_dir / "problems_detailed.md", problems)

    console.print(f"  [green]✓ Discovered {len(problems)} problems[/green]")
    return problems


def _write_problems_md(path: Path, problems: list[Problem]) -> None:
    lines = ["# Phase 1: Discovered Problems\n"]
    for i, p in enumerate(problems, 1):
        lines.append(f"## {i}. {p.title} (Score: {p.overall_score:.1f})")
        lines.append(f"**Domain**: {p.domain}  ")
        lines.append(f"**Scores**: Frequency {p.frequency_score}/10 | Intensity {p.intensity_score}/10 | Solution Gap {p.solution_gap_score}/10\n")
        lines.append(p.description + "\n")
        if p.why_now:
            lines.append(f"**Why Now**: {p.why_now}\n")
        if p.existing_solutions:
            lines.append(f"**Existing Solutions**: {', '.join(p.existing_solutions)}\n")
        if p.evidence:
            lines.append("**Evidence**:")
            for ev in p.evidence[:3]:
                lines.append(f"- [{ev.source}] {ev.snippet[:200]}")
        lines.append("")
    output.write_md(path, "\n".join(lines))
