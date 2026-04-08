"""Data schemas for all phases."""

from __future__ import annotations

from typing import Any
from pydantic import BaseModel, Field


# ── Phase 1: Scout ────────────────────────────────────────────────────────────

class Evidence(BaseModel):
    source: str
    url: str
    snippet: str


class Problem(BaseModel):
    id: str
    title: str
    domain: str
    description: str
    frequency_score: float = Field(ge=0, le=10)
    intensity_score: float = Field(ge=0, le=10)
    solution_gap_score: float = Field(ge=0, le=10)
    overall_score: float = Field(ge=0, le=10)
    evidence: list[Evidence] = []
    existing_solutions: list[str] = []
    why_now: str = ""


# ── Phase 2: Hackathon ────────────────────────────────────────────────────────

class Competitor(BaseModel):
    name: str
    url: str = ""
    strengths: list[str] = []
    weaknesses: list[str] = []
    pricing: str = ""
    tech_stack: list[str] = []


class TargetPersona(BaseModel):
    role: str
    company_size: str = ""
    current_workflow: str = ""
    willingness_to_pay: str = ""


class MarketSize(BaseModel):
    tam: str = ""
    sam: str = ""
    som: str = ""


class ResearchBrief(BaseModel):
    problem_id: str
    market_size: MarketSize = Field(default_factory=MarketSize)
    competitors: list[Competitor] = []
    target_persona: TargetPersona = Field(default_factory=lambda: TargetPersona(role="Unknown"))
    timing_signals: list[str] = []
    feasibility_flags: list[str] = []
    key_insight: str = ""


class MVPFeature(BaseModel):
    name: str
    description: str
    user_flow: list[str] = []
    acceptance_criteria: list[str] = []


class Entity(BaseModel):
    name: str
    fields: list[str] = []


class DataModel(BaseModel):
    entities: list[Entity] = []


class TechStack(BaseModel):
    frontend: str = ""
    backend: str = ""
    database: str = ""
    key_libraries: list[str] = []


class ProductSpec(BaseModel):
    problem_id: str
    product_name: str
    value_prop: str
    differentiator: str
    mvp_features: list[MVPFeature] = []
    out_of_scope: list[str] = []
    demo_format: str = "web_app"
    tech_stack: TechStack = Field(default_factory=TechStack)
    data_model: DataModel = Field(default_factory=DataModel)
    seed_data: str = ""
    monetization: str = ""
    pitch: str = ""
    gtm: str = ""


# ── Phase 3: Demo Day ─────────────────────────────────────────────────────────

class JudgeScore(BaseModel):
    problem_id: str
    judge_type: str  # market | technical | user | vc
    score: float = Field(ge=0, le=10)
    strengths: list[str] = []
    weaknesses: list[str] = []
    verdict: str = ""


class LeaderboardEntry(BaseModel):
    problem_id: str
    problem_title: str
    final_score: float
    market_score: float
    technical_score: float
    user_score: float
    vc_score: float
    rank: int
    notable_disagreements: list[str] = []
    narrative: str = ""


# ── Run state ─────────────────────────────────────────────────────────────────

class RunConfig(BaseModel):
    run_id: str
    domains: list[str]
    depth: str = "standard"
    teams: int = 10
    top_k: int = 3
    checkpoint_after_scout: bool = False
    checkpoint_after_judging: bool = False
    no_build: bool = False
    output_dir: str = "output"
    judge_weights: dict[str, float] = Field(
        default_factory=lambda: {"market": 0.25, "technical": 0.25, "user": 0.25, "vc": 0.25}
    )
    models: dict[str, str] = Field(
        default_factory=lambda: {
            "scout": "claude-sonnet-4-6",
            "analyst": "claude-sonnet-4-6",
            "strategist": "claude-sonnet-4-6",
            "judges": "claude-sonnet-4-6",
        }
    )
    budget: dict[str, Any] = Field(
        default_factory=lambda: {
            "max_tokens_per_team": 200000,
            "max_tokens_per_build": 500000,
            "max_total_cost": 50.00,
        }
    )
    scraping: dict[str, Any] = Field(default_factory=dict)
