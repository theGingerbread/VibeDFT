"""Configuration placeholders for the VibeDFT v2 platform."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class PlatformConfig:
    """Top-level platform configuration boundary."""

    calculator_backend: str = "qe"
    analysis_profile: str = "default"
    project_layout_version: str = "0.1"
    extras: dict[str, str] = field(default_factory=dict)
