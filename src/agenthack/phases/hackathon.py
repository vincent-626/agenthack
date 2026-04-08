"""Phase 2: Hackathon — Parallel Research + Strategy teams."""

from __future__ import annotations

import asyncio
from pathlib import Path

from rich.console import Console

from ..schemas import (
    Problem, ResearchBrief, ProductSpec, RunConfig,
    Competitor, TargetPersona, MarketSize, MVPFeature, TechStack, DataModel, Entity
)
from ..utils import llm, scraper, output

console = Console()

# ── Analyst ───────────────────────────────────────────────────────────────────

ANALYST_SYSTEM = """You are an expert market analyst and startup researcher.
Your job is to deeply research a specific problem domain to understand the market opportunity.
Be specific, evidence-based, and cite real companies and data points.
Always return valid JSON when asked."""

ANALYST_PROMPT = """Conduct deep market research on this problem:

PROBLEM: {title}
DESCRIPTION: {description}
DOMAIN: {domain}
WHY NOW: {why_now}
KNOWN COMPETITORS: {existing_solutions}

Research the following thoroughly using web search:

1. MARKET SIZE
   - Total Addressable Market (TAM)
   - Serviceable Addressable Market (SAM)
   - Serviceable Obtainable Market (SOM)
   - Growth rate and trajectory

2. COMPETITOR ANALYSIS (research 3-5 competitors)
   For each competitor:
   - What they do and their positioning
   - What they do well (based on positive reviews)
   - Where they fall short (based on negative reviews, complaints)
   - Their pricing model
   - Estimated tech stack

3. TARGET USER PERSONA
   - Who is the primary user? (role, seniority, company size)
   - What is their current workflow/workaround?
   - What would they reasonably pay per month?
   - Where do they hang out online?

4. TIMING SIGNALS
   - Any regulatory changes creating opportunity?
   - Technology shifts (new APIs, cost reductions)?
   - Behavioral/cultural trends?
   - Recent competitor failures or pivots?

5. FEASIBILITY CHECK
   - Is this buildable as a solo software project?
   - Any hardware requirements?
   - Heavy regulatory burden?
   - Network effect dependencies?

6. KEY INSIGHT
   - What is the ONE non-obvious insight from your research?

Return a JSON object:
{{
  "problem_id": "{problem_id}",
  "market_size": {{
    "tam": "$X billion",
    "sam": "$X million",
    "som": "$X million"
  }},
  "competitors": [
    {{
      "name": "...",
      "url": "https://...",
      "strengths": ["..."],
      "weaknesses": ["..."],
      "pricing": "...",
      "tech_stack": ["..."]
    }}
  ],
  "target_persona": {{
    "role": "...",
    "company_size": "...",
    "current_workflow": "...",
    "willingness_to_pay": "$X/month"
  }},
  "timing_signals": ["..."],
  "feasibility_flags": ["..."],
  "key_insight": "..."
}}"""

# ── Strategist ────────────────────────────────────────────────────────────────

STRATEGIST_SYSTEM = """You are an expert product strategist and startup founder.
Your job is to take market research and design the optimal MVP product concept.
Be ruthlessly focused on what's buildable in one day by a single developer.
Write specs detailed enough that another engineer could build from cold — no context carried over.
Always return valid JSON when asked."""

STRATEGIST_PROMPT = """Design a buildable MVP product for this problem and research.

PROBLEM: {title}
DESCRIPTION: {description}

RESEARCH BRIEF:
{research_md}

Design the optimal MVP product concept. Your spec must be self-contained — a developer will build from this spec alone with no additional context.

Choose the best demo format:
- "web_app": React/Next.js — for SaaS tools, dashboards, productivity apps
- "chrome_extension": For browser-based utilities, tab management, reading tools
- "cli_tool": For developer tools, automation scripts, data processing
- "landing_page_mockup": For marketplace/platform concepts (landing + interactive demo)
- "api_frontend": For data/AI services (simple API + minimal frontend)

Return a JSON spec:
{{
  "problem_id": "{problem_id}",
  "product_name": "Product Name",
  "value_prop": "One sentence: what it does and for whom",
  "differentiator": "What makes this different from existing solutions",
  "mvp_features": [
    {{
      "name": "Feature Name",
      "description": "What it does",
      "user_flow": ["Step 1: user does X", "Step 2: system does Y", "Step 3: user sees Z"],
      "acceptance_criteria": ["It should...", "It should..."]
    }}
  ],
  "out_of_scope": ["Feature X (post-MVP)", "Feature Y (v2)"],
  "demo_format": "web_app",
  "tech_stack": {{
    "frontend": "React + Tailwind CSS",
    "backend": "Next.js API routes",
    "database": "SQLite with better-sqlite3",
    "key_libraries": ["lib1", "lib2"]
  }},
  "data_model": {{
    "entities": [
      {{
        "name": "EntityName",
        "fields": ["id: string", "name: string", "created_at: timestamp"]
      }}
    ]
  }},
  "seed_data": "Describe what mock/seed data to include so demo is immediately impressive",
  "monetization": "freemium — $X/mo for pro features",
  "pitch": "One sentence pitch for the product",
  "gtm": "Go-to-market angle — how to reach first 100 users"
}}

RULES:
- Maximum 3 MVP features
- Must be buildable in one day by one developer
- Include realistic seed/mock data description
- Tech stack must use common, well-supported libraries"""


async def run_team(
    team_id: int,
    problem: Problem,
    config: RunConfig,
) -> tuple[ResearchBrief | None, ProductSpec | None]:
    """Run one team's analyst + strategist pipeline for a problem."""
    team_dir = Path(config.output_dir) / "phase2" / f"team_{team_id:03d}"
    output.ensure_dir(team_dir)

    console.print(f"  [cyan]Team {team_id:03d}:[/cyan] {problem.title[:60]}")

    analyst_model = config.models.get("analyst", "claude-sonnet-4-6")
    strategist_model = config.models.get("strategist", "claude-sonnet-4-6")

    # ── Analyst ──────────────────────────────────────────────────────────────
    analyst_response = llm.call_with_search(
        model=analyst_model,
        system=ANALYST_SYSTEM,
        prompt=ANALYST_PROMPT.format(
            problem_id=problem.id,
            title=problem.title,
            description=problem.description,
            domain=problem.domain,
            why_now=problem.why_now,
            existing_solutions=", ".join(problem.existing_solutions),
        ),
        max_tokens=8192,
    )

    output.write_md(team_dir / "research.md", analyst_response)

    research: ResearchBrief | None = None
    try:
        data = llm.extract_json(analyst_response)
        market = MarketSize(**data.get("market_size", {}))
        competitors = [Competitor(**c) for c in data.get("competitors", [])]
        persona_data = data.get("target_persona", {})
        persona = TargetPersona(
            role=persona_data.get("role", "Unknown"),
            company_size=persona_data.get("company_size", ""),
            current_workflow=persona_data.get("current_workflow", ""),
            willingness_to_pay=persona_data.get("willingness_to_pay", ""),
        )
        research = ResearchBrief(
            problem_id=problem.id,
            market_size=market,
            competitors=competitors,
            target_persona=persona,
            timing_signals=data.get("timing_signals", []),
            feasibility_flags=data.get("feasibility_flags", []),
            key_insight=data.get("key_insight", ""),
        )
        output.write_json(team_dir / "research.json", research)
    except Exception as e:
        console.print(f"    [yellow]Research parse error for team {team_id}: {e}[/yellow]")

    # ── Strategist ────────────────────────────────────────────────────────────
    strategist_response = llm.call(
        model=strategist_model,
        system=STRATEGIST_SYSTEM,
        prompt=STRATEGIST_PROMPT.format(
            problem_id=problem.id,
            title=problem.title,
            description=problem.description,
            research_md=analyst_response[:6000],
        ),
        max_tokens=8192,
    )

    output.write_md(team_dir / "spec.md", strategist_response)

    spec: ProductSpec | None = None
    try:
        data = llm.extract_json(strategist_response)
        features = []
        for f in data.get("mvp_features", []):
            features.append(MVPFeature(
                name=f.get("name", ""),
                description=f.get("description", ""),
                user_flow=f.get("user_flow", []),
                acceptance_criteria=f.get("acceptance_criteria", []),
            ))
        ts_data = data.get("tech_stack", {})
        ts = TechStack(
            frontend=ts_data.get("frontend", ""),
            backend=ts_data.get("backend", ""),
            database=ts_data.get("database", ""),
            key_libraries=ts_data.get("key_libraries", []),
        )
        dm_data = data.get("data_model", {})
        entities = [Entity(name=e.get("name", ""), fields=e.get("fields", []))
                    for e in dm_data.get("entities", [])]
        dm = DataModel(entities=entities)
        spec = ProductSpec(
            problem_id=problem.id,
            product_name=data.get("product_name", "Untitled"),
            value_prop=data.get("value_prop", ""),
            differentiator=data.get("differentiator", ""),
            mvp_features=features,
            out_of_scope=data.get("out_of_scope", []),
            demo_format=data.get("demo_format", "web_app"),
            tech_stack=ts,
            data_model=dm,
            seed_data=data.get("seed_data", ""),
            monetization=data.get("monetization", ""),
            pitch=data.get("pitch", ""),
            gtm=data.get("gtm", ""),
        )
        output.write_json(team_dir / "spec.json", spec)
    except Exception as e:
        console.print(f"    [yellow]Spec parse error for team {team_id}: {e}[/yellow]")

    status = "✓" if (research and spec) else "~"
    console.print(f"  [green]{status} Team {team_id:03d} done[/green]")
    return research, spec


async def run_hackathon(
    problems: list[Problem],
    config: RunConfig,
) -> list[tuple[Problem, ResearchBrief | None, ProductSpec | None]]:
    """Run Phase 2: all teams in parallel."""
    output.ensure_dir(Path(config.output_dir) / "phase2")

    # Run all teams concurrently
    tasks = [
        run_team(i + 1, problem, config)
        for i, problem in enumerate(problems)
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    combined = []
    for i, (problem, result) in enumerate(zip(problems, results)):
        if isinstance(result, Exception):
            console.print(f"  [red]Team {i+1} failed: {result}[/red]")
            combined.append((problem, None, None))
        else:
            research, spec = result
            combined.append((problem, research, spec))

    console.print(f"  [green]✓ {len(combined)} teams completed[/green]")
    return combined
