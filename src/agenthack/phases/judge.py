"""Phase 3: Demo Day — Judging."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from rich.console import Console

from ..schemas import (
    Problem, ResearchBrief, ProductSpec, RunConfig,
    JudgeScore, LeaderboardEntry
)
from ..utils import llm, output

console = Console()

# ── Judge prompts ─────────────────────────────────────────────────────────────

JUDGE_SYSTEM = """You are an expert judge at a startup hackathon.
Evaluate startup ideas based on research briefs and product specs.
Be critical, specific, and honest. Score on a 0-10 scale.
Always return valid JSON."""

MARKET_JUDGE_PROMPT = """You are a MARKET JUDGE evaluating a startup idea.

Focus ONLY on market opportunity:
- Is the market large enough to matter? ($100M+ TAM for venture scale)
- Is the competitive landscape favorable? (fragmented, or dominated by weak players)
- Is the timing right? (riding a wave, not fighting a tide)
- Is the evidence from research convincing or hand-wavy?

PROBLEM: {title}
DESCRIPTION: {description}

RESEARCH BRIEF:
{research_brief}

PRODUCT SPEC:
{product_spec}

Return JSON:
{{
  "problem_id": "{problem_id}",
  "judge_type": "market",
  "score": X.X,
  "strengths": ["specific strength 1", "specific strength 2"],
  "weaknesses": ["specific weakness 1", "specific weakness 2"],
  "verdict": "2-3 sentence honest assessment from market perspective"
}}"""

TECH_JUDGE_PROMPT = """You are a TECHNICAL JUDGE evaluating a startup idea.

Focus ONLY on technical feasibility:
- Is the proposed tech stack appropriate for the problem?
- Is the MVP scope realistic for a one-day build by one developer?
- How much effort to go from demo to real product?
- Are there technical risks the team didn't address?
- Is the architecture sound?

PROBLEM: {title}
DESCRIPTION: {description}

RESEARCH BRIEF:
{research_brief}

PRODUCT SPEC:
{product_spec}

Return JSON:
{{
  "problem_id": "{problem_id}",
  "judge_type": "technical",
  "score": X.X,
  "strengths": ["specific strength 1", "specific strength 2"],
  "weaknesses": ["specific weakness 1", "specific weakness 2"],
  "verdict": "2-3 sentence honest assessment from technical perspective"
}}"""

USER_JUDGE_PROMPT = """You are a USER EXPERIENCE JUDGE evaluating a startup idea.

Focus ONLY on user value and UX:
- Is the pain point real and urgent based on the evidence? (not just nice-to-have)
- Would the target user actually switch to this? (switching costs, habits)
- Does the proposed UX / user flow make sense?
- Is the persona well-defined or generic ("SMBs", "developers" — too vague)?
- Is the value proposition immediately clear to the target user?

PROBLEM: {title}
DESCRIPTION: {description}

RESEARCH BRIEF:
{research_brief}

PRODUCT SPEC:
{product_spec}

Return JSON:
{{
  "problem_id": "{problem_id}",
  "judge_type": "user",
  "score": X.X,
  "strengths": ["specific strength 1", "specific strength 2"],
  "weaknesses": ["specific weakness 1", "specific weakness 2"],
  "verdict": "2-3 sentence honest assessment from user perspective"
}}"""

VC_JUDGE_PROMPT = """You are a VC JUDGE evaluating a startup idea.

Focus ONLY on venture potential:
- Is this a venture-scale opportunity ($1B+ exit potential) or a lifestyle business?
- What's the defensibility / moat potential? (network effects, data, switching costs, IP)
- Is the unit economics story plausible? (CAC vs LTV)
- Would this get a second meeting from a seed-stage VC?
- Is the founding insight non-obvious?

PROBLEM: {title}
DESCRIPTION: {description}

RESEARCH BRIEF:
{research_brief}

PRODUCT SPEC:
{product_spec}

Return JSON:
{{
  "problem_id": "{problem_id}",
  "judge_type": "vc",
  "score": X.X,
  "strengths": ["specific strength 1", "specific strength 2"],
  "weaknesses": ["specific weakness 1", "specific weakness 2"],
  "verdict": "2-3 sentence honest assessment from VC perspective"
}}"""

JUDGE_PROMPTS = {
    "market": MARKET_JUDGE_PROMPT,
    "technical": TECH_JUDGE_PROMPT,
    "user": USER_JUDGE_PROMPT,
    "vc": VC_JUDGE_PROMPT,
}

DELIBERATOR_PROMPT = """You are the Chief Deliberator at a startup hackathon.
Produce the final ranked leaderboard based on all judge scores.

ALL JUDGE SCORES:
{all_scores_json}

PROBLEMS:
{problems_json}

WEIGHTED AVERAGE FORMULA:
market × {w_market} + technical × {w_technical} + user × {w_user} + vc × {w_vc}

For each problem:
1. Compute the weighted average final score
2. Identify notable disagreements (when one judge scores 3+ points above/below average)
3. Write a 2-3 sentence narrative for the top 3 winners explaining why they won

Return JSON:
{{
  "leaderboard": [
    {{
      "problem_id": "prob_001",
      "problem_title": "...",
      "final_score": X.XX,
      "market_score": X.X,
      "technical_score": X.X,
      "user_score": X.X,
      "vc_score": X.X,
      "rank": 1,
      "notable_disagreements": ["Market Judge loved it (9.0) but Tech Judge flagged feasibility concerns (4.5)"],
      "narrative": "Only for top 3: why this idea won"
    }}
  ]
}}

Sort by final_score descending. Assign ranks 1, 2, 3... sequentially."""


async def _judge_one(
    judge_type: str,
    problem: Problem,
    research: ResearchBrief | None,
    spec: ProductSpec | None,
    model: str,
    output_dir: Path,
) -> JudgeScore | None:
    """Run one judge on one problem."""
    prompt_template = JUDGE_PROMPTS[judge_type]

    research_text = research.model_dump_json(indent=2) if research else "No research available"
    spec_text = spec.model_dump_json(indent=2) if spec else "No spec available"

    prompt = prompt_template.format(
        problem_id=problem.id,
        title=problem.title,
        description=problem.description,
        research_brief=research_text[:4000],
        product_spec=spec_text[:4000],
    )

    response = llm.call(
        model=model,
        system=JUDGE_SYSTEM,
        prompt=prompt,
        max_tokens=2048,
    )

    judge_dir = output_dir / "judge_scores"
    output.ensure_dir(judge_dir)
    output.write_md(judge_dir / f"{problem.id}_{judge_type}.md", response)

    try:
        data = llm.extract_json(response)
        raw_score = float(data.get("score", 5.0))
        score = JudgeScore(
            problem_id=problem.id,
            judge_type=judge_type,
            score=max(0.0, min(10.0, raw_score)),
            strengths=data.get("strengths", []),
            weaknesses=data.get("weaknesses", []),
            verdict=data.get("verdict", ""),
        )
        output.write_json(judge_dir / f"{problem.id}_{judge_type}.json", score)
        return score
    except Exception as e:
        console.print(f"    [yellow]Judge parse error ({judge_type}, {problem.id}): {e}[/yellow]")
        return None


async def run_judging(
    teams: list[tuple[Problem, ResearchBrief | None, ProductSpec | None]],
    config: RunConfig,
) -> list[LeaderboardEntry]:
    """Run Phase 3: all judges on all problems, then deliberate."""
    output_dir = Path(config.output_dir) / "phase3"
    output.ensure_dir(output_dir)

    judge_model = config.models.get("judges", "claude-sonnet-4-6")
    weights = config.judge_weights

    console.print(f"  Running {len(JUDGE_PROMPTS)} judges × {len(teams)} problems in parallel...")

    # Run all judges on all problems concurrently
    tasks = []
    task_keys = []
    for problem, research, spec in teams:
        for judge_type in JUDGE_PROMPTS:
            tasks.append(_judge_one(judge_type, problem, research, spec, judge_model, output_dir))
            task_keys.append((problem.id, judge_type))

    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Organize scores by problem
    scores_by_problem: dict[str, dict[str, float]] = {}
    for (problem_id, judge_type), result in zip(task_keys, results):
        if isinstance(result, JudgeScore):
            if problem_id not in scores_by_problem:
                scores_by_problem[problem_id] = {}
            scores_by_problem[problem_id][judge_type] = result.score

    # Build problems map
    problems_map = {p.id: p for p, _, _ in teams}

    # Run deliberator
    all_scores_data = []
    for problem_id, judge_scores in scores_by_problem.items():
        all_scores_data.append({
            "problem_id": problem_id,
            "problem_title": problems_map.get(problem_id, Problem(
                id=problem_id, title="Unknown", domain="", description="",
                frequency_score=5, intensity_score=5, solution_gap_score=5, overall_score=5
            )).title,
            "scores": judge_scores,
        })

    problems_data = [
        {"id": p.id, "title": p.title, "domain": p.domain}
        for p, _, _ in teams
    ]

    delib_response = llm.call(
        model=judge_model,
        system=JUDGE_SYSTEM,
        prompt=DELIBERATOR_PROMPT.format(
            all_scores_json=json.dumps(all_scores_data, indent=2),
            problems_json=json.dumps(problems_data, indent=2),
            w_market=weights.get("market", 0.25),
            w_technical=weights.get("technical", 0.25),
            w_user=weights.get("user", 0.25),
            w_vc=weights.get("vc", 0.25),
        ),
        max_tokens=4096,
    )

    output.write_md(output_dir / "deliberation.md", delib_response)

    leaderboard: list[LeaderboardEntry] = []
    try:
        data = llm.extract_json(delib_response)
        entries = data.get("leaderboard", data) if isinstance(data, dict) else data
        for entry in entries:
            leaderboard.append(LeaderboardEntry(
                problem_id=entry.get("problem_id", ""),
                problem_title=entry.get("problem_title", ""),
                final_score=float(entry.get("final_score", 5.0)),
                market_score=float(entry.get("market_score", 5.0)),
                technical_score=float(entry.get("technical_score", 5.0)),
                user_score=float(entry.get("user_score", 5.0)),
                vc_score=float(entry.get("vc_score", 5.0)),
                rank=int(entry.get("rank", 99)),
                notable_disagreements=entry.get("notable_disagreements", []),
                narrative=entry.get("narrative", ""),
            ))
    except Exception as e:
        console.print(f"  [yellow]Deliberation parse error: {e}[/yellow]")
        # Fallback: compute manually
        leaderboard = _compute_leaderboard_fallback(scores_by_problem, problems_map, weights)

    leaderboard.sort(key=lambda e: e.final_score, reverse=True)
    for i, e in enumerate(leaderboard):
        e.rank = i + 1

    # Write outputs
    output.write_json(output_dir / "leaderboard.json", leaderboard)
    _write_leaderboard_md(output_dir / "leaderboard.md", leaderboard)
    _write_top3_report(output_dir / "top3_report.md", leaderboard[:3], teams)

    console.print(f"  [green]✓ Judging complete. Top 3 selected.[/green]")
    return leaderboard


def _compute_leaderboard_fallback(
    scores_by_problem: dict[str, dict[str, float]],
    problems_map: dict[str, Problem],
    weights: dict[str, float],
) -> list[LeaderboardEntry]:
    """Compute leaderboard without LLM if deliberation fails."""
    entries = []
    for prob_id, judge_scores in scores_by_problem.items():
        m = judge_scores.get("market", 5.0)
        t = judge_scores.get("technical", 5.0)
        u = judge_scores.get("user", 5.0)
        v = judge_scores.get("vc", 5.0)
        final = (
            m * weights.get("market", 0.25)
            + t * weights.get("technical", 0.25)
            + u * weights.get("user", 0.25)
            + v * weights.get("vc", 0.25)
        )
        problem = problems_map.get(prob_id)
        entries.append(LeaderboardEntry(
            problem_id=prob_id,
            problem_title=problem.title if problem else prob_id,
            final_score=round(final, 2),
            market_score=m,
            technical_score=t,
            user_score=u,
            vc_score=v,
            rank=0,
        ))
    entries.sort(key=lambda e: e.final_score, reverse=True)
    for i, e in enumerate(entries):
        e.rank = i + 1
    return entries


def _write_leaderboard_md(path: Path, leaderboard: list[LeaderboardEntry]) -> None:
    lines = ["# Phase 3: Hackathon Leaderboard\n"]
    lines.append("| Rank | Idea | Final | Market | Tech | User | VC |")
    lines.append("|------|------|-------|--------|------|------|----|")
    for e in leaderboard:
        trophy = "🥇" if e.rank == 1 else "🥈" if e.rank == 2 else "🥉" if e.rank == 3 else ""
        lines.append(
            f"| {e.rank} {trophy} | {e.problem_title} | **{e.final_score:.2f}** | "
            f"{e.market_score:.1f} | {e.technical_score:.1f} | {e.user_score:.1f} | {e.vc_score:.1f} |"
        )
    lines.append("\n## Judge Commentary\n")
    for e in leaderboard[:5]:
        lines.append(f"### {e.rank}. {e.problem_title}")
        if e.notable_disagreements:
            for d in e.notable_disagreements:
                lines.append(f"- {d}")
        if e.narrative:
            lines.append(f"\n{e.narrative}")
        lines.append("")
    output.write_md(path, "\n".join(lines))


def _write_top3_report(
    path: Path,
    top3: list[LeaderboardEntry],
    teams: list[tuple[Problem, ResearchBrief | None, ProductSpec | None]],
) -> None:
    teams_map = {p.id: (p, r, s) for p, r, s in teams}
    lines = ["# Top 3 Winners — Demo Day Report\n"]
    for entry in top3:
        data = teams_map.get(entry.problem_id)
        if not data:
            continue
        problem, research, spec = data
        lines.append(f"## #{entry.rank}: {entry.problem_title}")
        lines.append(f"**Score**: {entry.final_score:.2f}/10\n")
        if entry.narrative:
            lines.append(entry.narrative + "\n")
        if spec:
            lines.append(f"**Product**: {spec.product_name}")
            lines.append(f"**Pitch**: {spec.pitch}")
            lines.append(f"**Value Prop**: {spec.value_prop}")
            lines.append(f"**Demo Format**: {spec.demo_format}")
            lines.append(f"**Tech Stack**: {spec.tech_stack.frontend} / {spec.tech_stack.backend}\n")
        if research:
            lines.append(f"**Market**: {research.market_size.tam} TAM")
            lines.append(f"**Key Insight**: {research.key_insight}\n")
        lines.append("---\n")
    output.write_md(path, "\n".join(lines))
