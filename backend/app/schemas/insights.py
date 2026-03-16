"""Pydantic schemas for the Insights Dashboard — Phase 8."""

from pydantic import BaseModel


class DashboardSummary(BaseModel):
    total_contacts: int
    total_messages_sent: int
    total_jobs_tracked: int
    overall_response_rate: float
    upcoming_follow_ups: int
    active_conversations: int


class ResponseRateBreakdown(BaseModel):
    label: str
    sent: int
    responded: int
    rate: float


class AngleEffectiveness(BaseModel):
    goal: str
    sent: int
    responded: int
    rate: float


class NetworkGrowthPoint(BaseModel):
    date: str
    cumulative_contacts: int


class NetworkGap(BaseModel):
    category: str  # "industry" or "role"
    label: str
    count: int


class WarmPathPerson(BaseModel):
    name: str
    title: str | None
    status: str


class WarmPath(BaseModel):
    company_name: str
    connected_persons: list[WarmPathPerson]


class CompanyOpenness(BaseModel):
    company_name: str
    total_outreach: int
    responses: int
    rate: float


class InsightsDashboard(BaseModel):
    summary: DashboardSummary
    response_by_channel: list[ResponseRateBreakdown]
    response_by_role: list[ResponseRateBreakdown]
    response_by_company: list[ResponseRateBreakdown]
    angle_effectiveness: list[AngleEffectiveness]
    network_growth: list[NetworkGrowthPoint]
    network_gaps: list[NetworkGap]
    warm_paths: list[WarmPath]
    company_openness: list[CompanyOpenness]
