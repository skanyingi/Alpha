"""Shared types for the deterministic multi-agent desk."""

from __future__ import annotations

from abc import ABC, abstractmethod
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class AgentRole(str, Enum):
    INGESTION = "INGESTION"
    JEV_ROUTER = "JEV_ROUTER"
    HAZARD_VULNERABILITY = "HAZARD_VULNERABILITY"
    HDC_MEMORY = "HDC_MEMORY"
    FINANCE_EXECUTOR = "FINANCE_EXECUTOR"
    ANALYTICS_GEOJSON = "ANALYTICS_GEOJSON"
    GEMINI_RAG = "GEMINI_RAG"


class AgentResult(BaseModel):
    agent_role: AgentRole
    status: str
    latency_ms: float
    outputs: dict[str, Any] = Field(default_factory=dict)
    audit_layer: int


class BaseSubAgent(ABC):
    role: AgentRole
    audit_layer: int

    @abstractmethod
    async def execute(self, payload: dict[str, Any]) -> AgentResult:
        """Run this agent's tool and return a timed result. Does not change Layer 4 math."""
