# AgentHack

Run an AI hackathon from your terminal.

Given a set of domains, AgentHack discovers real-world problems, spins up parallel agent teams to research and strategize, judges the results, then builds working demos for the top 3 winners.

```
agenthack run --domains "healthcare,devtools" --depth standard
```

---

## How It Works

AgentHack runs a four-phase pipeline:

```
Phase 1: Scout       Discover real problems people have in your domains
    ↓
Phase 2: Hackathon   N teams research + design a product spec in parallel
    ↓
Phase 3: Demo Day    4 judges score every idea, deliberator picks top 3
    ↓
Phase 4: Build       Claude Code builds working demos for the top 3 only
```

**Why only build the top 3?** Building is the most expensive phase (~$5–15 per demo). By filtering first through research and judging, build compute goes only to ideas that have already passed a quality bar — producing better demos at 70–80% lower cost than building everything.

---

## Installation

**Requirements**: Python 3.11+, an Anthropic API key.

```bash
uv sync
export ANTHROPIC_API_KEY=your_key_here
```

Optional — for deeper web scraping in the research phase:

```bash
export FIRECRAWL_API_KEY=your_key_here
```

---

## Usage

### Run a full hackathon

```bash
agenthack run --domains "healthcare,devtools"
```

### Common options

```bash
# Choose depth (affects team count and research depth)
agenthack run --domains "fintech" --depth fast        # 5 teams, quick
agenthack run --domains "fintech" --depth standard    # 10 teams, balanced (default)
agenthack run --domains "fintech" --depth deep        # 15 teams, thorough

# Pause for review between phases
agenthack run --domains "edtech" --checkpoint-after-scout
agenthack run --domains "edtech" --checkpoint-after-judging

# Skip building (research + judge only, much cheaper)
agenthack run --domains "healthcare" --no-build

# Multiple domains
agenthack run --domains "healthcare,devtools,fintech"
```

### Other commands

```bash
# Resume from a checkpoint (optionally exclude specific problems)
agenthack resume --run-id <id>
agenthack resume --run-id <id> --exclude prob_003,prob_007

# Re-run judging with different weights
agenthack judge --run-id <id> --weights market=0.3,tech=0.3,user=0.25,vc=0.15

# Build a specific team's idea from a past run
agenthack build --run-id <id> --team 5

# List past runs
agenthack history

# View run output
agenthack show --run-id <id>
agenthack show --run-id <id> --team 3
```

---

## Phases in Detail

### Phase 1 — Scout

Discovers real problems people have in your domains by searching Reddit, Hacker News, Product Hunt, G2/Capterra reviews, and Twitter. Each problem is scored on:

- **Frequency** — how often it's mentioned
- **Intensity** — how frustrated users are (mild annoyance vs. hair-on-fire)
- **Solution gap** — how poorly existing tools address it

The top N problems (one per team) advance to the hackathon.

**Output**: `problems.json`, `problems_detailed.md`, `raw_signals/`

### Phase 2 — Hackathon

Each problem gets its own team with two sequential agents running in parallel across all teams:

**Analyst** — deep market research:
- Market sizing (TAM/SAM/SOM)
- Competitor analysis (strengths, weaknesses, pricing, tech stack)
- Target user persona and willingness to pay
- Timing signals (regulatory changes, tech shifts, trends)
- Feasibility check

**Strategist** — product design:
- Value proposition and differentiator
- Ruthlessly scoped MVP (1–3 features max, buildable in a day)
- Demo format selection (web app, CLI, Chrome extension, etc.)
- Tech stack with specific libraries
- Data model and seed data
- Monetization and go-to-market angle
- **Self-contained build spec** — detailed enough for Claude Code to build from cold

**Output per team**: `research.json`, `research.md`, `spec.json`, `spec.md`

### Phase 3 — Demo Day

Four judge agents evaluate every idea independently on the research and spec (not a working demo):

| Judge | Focus |
|-------|-------|
| **Market** | Market size, competitive landscape, timing, evidence quality |
| **Technical** | Stack appropriateness, MVP realism, path to production, technical risks |
| **User** | Pain point urgency, switching likelihood, UX sense, persona clarity |
| **VC** | Venture scale, defensibility/moat, unit economics, fundability |

A **Deliberator** then computes weighted scores, flags notable judge disagreements, ranks all ideas, and selects the top 3 with narrative explanations.

**Output**: `leaderboard.json`, `leaderboard.md`, `top3_report.md`, `judge_scores/`

### Phase 4 — Build Sprint

The top 3 ideas are built in parallel by Claude Code. Each build receives the self-contained spec and research brief from Phase 2 — no context carried over from the research agents.

Each demo includes:
- Working application code
- Seed/mock data so it's immediately impressive
- README with install + run instructions

**Output per winner**: `demo/` directory with runnable app

---

## Output Structure

```
runs/<run-id>/
├── config.json
├── summary.md
├── phase1/
│   ├── problems.json
│   ├── problems_detailed.md
│   └── raw_signals/
├── phase2/
│   ├── team_001/
│   │   ├── research.json
│   │   ├── research.md
│   │   ├── spec.json
│   │   └── spec.md
│   └── team_002/ ...
├── phase3/
│   ├── leaderboard.json
│   ├── leaderboard.md
│   ├── top3_report.md
│   └── judge_scores/
└── phase4/
    ├── winner_1/demo/
    ├── winner_2/demo/
    └── winner_3/demo/
```

Every phase writes both JSON (machine-readable) and Markdown (human-readable) so you can inspect, re-run, or fork any stage independently.

---

## Configuration

Copy `agenthack.yaml.example` to `agenthack.yaml` to customize defaults:

```yaml
defaults:
  depth: standard
  teams: 10
  top_k: 3
  checkpoint_after_scout: false
  checkpoint_after_judging: false

models:
  scout: claude-sonnet-4-6
  analyst: claude-sonnet-4-6
  strategist: claude-sonnet-4-6
  judges: claude-sonnet-4-6

judge_weights:
  market: 0.25
  technical: 0.25
  user: 0.25
  vc: 0.25

budget:
  max_tokens_per_team: 200000
  max_tokens_per_build: 500000
  max_total_cost: 50.00

scraping:
  firecrawl_api_key: ${FIRECRAWL_API_KEY}
  max_pages_per_team: 30
  max_pages_scout: 100
```

---

## Data Gathering

Two tools handle web research:

**Anthropic web search** — built into Claude API calls. Used for broad discovery, market sizing, quick lookups, and any time search snippets are sufficient.

**Firecrawl** — scrapes full page content as clean markdown. Used when you need the complete text of a competitor pricing page, a Reddit thread, or a G2 review page. Returns LLM-ready markdown (67% fewer tokens than raw HTML). Free tier gives 500 credits; a standard run uses ~200–300 pages.

---

## Cost Estimates

| Mode | Teams | Research + Judge | Build (top 3) | Total |
|------|-------|-----------------|---------------|-------|
| Fast | 5 | $5–10 | $10–30 | **$15–40** |
| Standard | 10 | $10–20 | $15–40 | **$25–60** |
| Deep | 15 | $15–30 | $20–50 | **$35–80** |

Firecrawl adds ~$5–10 per run (or free on the free tier for smaller runs).

**To cut costs:**
- Use `--no-build` to run research-only passes for ~$10–20
- Use `--depth fast` for quick exploration
- Set `max_tokens_per_team` in config to cap runaway research sessions
