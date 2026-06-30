"""Research-domain models for claim and evidence gating.

These models describe the scientific layer above raw QE artifacts: research
questions, claims, evidence requirements, lineage, and deterministic gate
decisions.  They intentionally stay lightweight and JSON-serialisable so they
can be used by CLIs, reports, and future review agents without depending on
runtime QE execution.
"""

from __future__ import annotations

import enum
import math
from dataclasses import asdict, dataclass, field, is_dataclass
from typing import Any

from vibedft import __version__ as VIBEDFT_VERSION


class Route(str, enum.Enum):
    """Scientific workflow route used to answer a research question."""

    STATIC_DOPING = "static_doping"
    INTERCALATION = "intercalation"
    TYPE3_HETEROSTRUCTURE = "type3_heterostructure"
    OTHER = "other"


class ClaimType(str, enum.Enum):
    """Type of scientific claim being evaluated."""

    STABILITY = "stability"
    ELECTRONIC_ORIGIN = "electronic_origin"
    CHARGE_TRANSFER = "charge_transfer"
    EPC_MECHANISM = "epc_mechanism"
    TC_ROBUSTNESS = "tc_robustness"
    BAND_ALIGNMENT = "band_alignment"
    NEGATIVE_RESULT = "negative_result"


class ClaimStatus(str, enum.Enum):
    """Current status of a scientific claim."""

    SUPPORTED = "supported"
    PROVISIONAL = "provisional"
    REFUTED = "refuted"
    BLOCKED = "blocked"


class EvidenceMaturity(str, enum.Enum):
    """How mature the available evidence is for scientific use."""

    RUN_FINISHED = "run_finished"
    NUMERICALLY_CONVERGED = "numerically_converged"
    PHYSICALLY_USABLE = "physically_usable"
    PAPER_GRADE = "paper_grade"


class GateVerdict(str, enum.Enum):
    """Deterministic gate decision for a claim."""

    PASS = "pass"
    FAIL = "fail"
    WARNING = "warning"
    BLOCKED = "blocked"


class ArtifactType(str, enum.Enum):
    """Kind of artifact referenced by lineage or evidence records."""

    INPUT = "input"
    OUTPUT = "output"
    SAVE_DIR = "save_dir"
    DYN = "dyn"
    A2F = "a2f"
    LAMBDAX = "lambdax"
    BANDS = "bands"
    PDOS = "pdos"
    CUBE = "cube"
    REPORT = "report"
    UNKNOWN = "unknown"


class ReliabilityLevel(str, enum.Enum):
    """Evidence reliability level used by descriptors and verdicts."""

    UNKNOWN = "unknown"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ResultStatus(str, enum.Enum):
    """Machine-readable status for analysis, verdict, and workflow stages."""

    PASS = "pass"
    WARNING = "warning"
    BLOCKED = "blocked"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    CANDIDATE_ONLY = "candidate_only"
    ERROR = "error"
    NOT_APPLICABLE = "not_applicable"


def _to_dict(obj: Any) -> Any:
    """Convert nested dataclasses and enums to JSON-safe Python values."""

    if is_dataclass(obj):
        return {key: _to_dict(value) for key, value in asdict(obj).items()}
    if isinstance(obj, enum.Enum):
        return obj.value
    if isinstance(obj, dict):
        return {key: _to_dict(value) for key, value in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_to_dict(value) for value in obj]
    if isinstance(obj, float) and not math.isfinite(obj):
        if math.isnan(obj):
            return "NaN"
        return "Infinity" if obj > 0 else "-Infinity"
    return obj


@dataclass
class EvidenceRef:
    """Traceable parser evidence extracted from one QE or derived artifact."""

    artifact_path: str
    artifact_type: ArtifactType
    parser_name: str
    parsed_quantity: str
    raw_value: Any | None = None
    summary: str = ""
    warnings: list[str] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)
    confidence: float | None = None
    reliability: ReliabilityLevel = ReliabilityLevel.UNKNOWN
    artifact_id: str = ""
    server: str = ""
    checksum: str = ""
    sample: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    parser_module: str = ""
    parser_version: str = VIBEDFT_VERSION

    def __post_init__(self) -> None:
        if not self.parser_module:
            self.parser_module = _parser_module_from_name(self.parser_name)
        if not self.parser_version:
            self.parser_version = VIBEDFT_VERSION

    def to_dict(self) -> dict[str, Any]:
        return _to_dict(self)


def _parser_module_from_name(parser_name: str) -> str:
    if "." not in parser_name:
        return parser_name
    return parser_name.rsplit(".", 1)[0]


@dataclass
class PhysicsDescriptor:
    """Machine-readable physical quantity derived from parser evidence."""

    name: str
    value: Any
    unit: str = ""
    evidence: list[EvidenceRef] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)
    confidence: float | None = None
    reliability: ReliabilityLevel = ReliabilityLevel.UNKNOWN
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return _to_dict(self)


@dataclass
class AnalysisResult:
    """Parser or analyzer output with descriptors, evidence, and blockers."""

    id: str
    parser_name: str
    status: ResultStatus
    parsed_quantity: str
    evidence: list[EvidenceRef] = field(default_factory=list)
    descriptors: list[PhysicsDescriptor] = field(default_factory=list)
    raw_value: Any | None = None
    summary: str = ""
    warnings: list[str] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)
    confidence: float | None = None
    reliability: ReliabilityLevel = ReliabilityLevel.UNKNOWN
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return _to_dict(self)


@dataclass
class PhysicsVerdict:
    """Deterministic physics verdict tied to supporting evidence."""

    claim_type: ClaimType | str
    status: ResultStatus
    conclusion: str
    supporting_evidence: list[EvidenceRef] = field(default_factory=list)
    descriptors: list[PhysicsDescriptor] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)
    confidence: float | None = None
    reliability: ReliabilityLevel = ReliabilityLevel.UNKNOWN
    forbidden_conclusions: list[str] = field(default_factory=list)
    next_actions: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.status == ResultStatus.PASS and not self.supporting_evidence:
            self.status = ResultStatus.INSUFFICIENT_EVIDENCE
            if not any("supporting evidence" in blocker for blocker in self.blockers):
                self.blockers.append("supporting evidence is required for a pass verdict")

    def to_dict(self) -> dict[str, Any]:
        return _to_dict(self)


@dataclass
class WorkflowStageResult:
    """Evidence-backed result for one stage in the VibeDFT workflow."""

    stage_id: str
    status: ResultStatus
    descriptors: list[PhysicsDescriptor] = field(default_factory=list)
    evidence: list[EvidenceRef] = field(default_factory=list)
    verdicts: list[PhysicsVerdict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)
    next_actions: list[str] = field(default_factory=list)
    reliability: ReliabilityLevel = ReliabilityLevel.UNKNOWN
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return _to_dict(self)


@dataclass
class FixtureManifest:
    """Manifest for local or remote regression fixtures without heavy copies."""

    id: str
    source: str
    artifacts: list[EvidenceRef] = field(default_factory=list)
    import_policy: str = "metadata_only"
    description: str = ""
    warnings: list[str] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return _to_dict(self)


@dataclass
class ResearchQuestion:
    """A bounded scientific question and route under investigation."""

    id: str
    title: str
    material_family: str
    route: Route
    hypotheses: list[str] = field(default_factory=list)
    scope: str = ""
    excluded_claims: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return _to_dict(self)


@dataclass
class LiteratureProtocol:
    """Literature-derived evidence protocol for a research route."""

    id: str
    route: Route
    research_focus: str
    required_claim_types: list[ClaimType]
    minimum_comparisons: list[str]
    required_observables: list[str]
    required_sensitivity_checks: list[str]
    stop_conditions: list[str]
    forbidden_shortcuts: list[str]
    source_basis: str = "literature"
    llm_notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return _to_dict(self)


@dataclass
class ScientificClaim:
    """A scientific claim tied to a research question and gate policy."""

    id: str
    question_id: str
    claim_type: ClaimType
    statement: str
    assumptions: list[str] = field(default_factory=list)
    validity_domain: str = ""
    required_evidence_ids: list[str] = field(default_factory=list)
    gate_policy_id: str = ""
    status: ClaimStatus = ClaimStatus.PROVISIONAL
    status_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return _to_dict(self)


@dataclass
class EvidenceRequirement:
    """Evidence expected before a claim can pass a gate."""

    id: str
    claim_type: ClaimType
    required_artifacts: list[ArtifactType] = field(default_factory=list)
    required_checks: list[str] = field(default_factory=list)
    minimum_maturity: EvidenceMaturity = EvidenceMaturity.RUN_FINISHED
    source_level: str = ""
    blocking_if_missing: bool = True
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return _to_dict(self)


@dataclass
class ComparisonSet:
    """A controlled set of claims or artifacts intended for comparison."""

    id: str
    claim_id: str
    control_variables: list[str] = field(default_factory=list)
    varied_variables: list[str] = field(default_factory=list)
    members: list[str] = field(default_factory=list)
    comparability_requirements: list[str] = field(default_factory=list)
    known_incompatibilities: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return _to_dict(self)


@dataclass
class ArtifactLineage:
    """Provenance and parse state for a calculation or report artifact."""

    artifact_id: str
    artifact_type: ArtifactType
    server: str
    path: str
    producer_program: str = ""
    producer_command: str = ""
    created_at_or_mtime: str = ""
    prefix: str = ""
    outdir: str = ""
    parent_artifacts: list[str] = field(default_factory=list)
    structure_source: str = ""
    parameter_fingerprint: str = ""
    job_status: str = ""
    parse_status: str = ""
    lineage_warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return _to_dict(self)


@dataclass
class GateDecision:
    """Decision record for whether a claim is allowed to be reported."""

    claim_id: str
    maturity: EvidenceMaturity
    verdict: GateVerdict
    blocking_reasons: list[str] = field(default_factory=list)
    supporting_artifacts: list[str] = field(default_factory=list)
    missing_artifacts: list[str] = field(default_factory=list)
    forbidden_conclusions: list[str] = field(default_factory=list)
    recommended_next_actions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return _to_dict(self)


@dataclass
class LLMTaskCard:
    """Bounded instructions for an LLM reviewer acting on a gate decision."""

    id: str
    claim_id: str
    task_type: str
    allowed_actions: list[str]
    forbidden_actions: list[str]
    required_files: list[str]
    required_checks: list[str]
    expected_outputs: list[str]
    stop_if: list[str]
    escalate_if: list[str]
    response_schema: dict[str, str]

    def to_dict(self) -> dict[str, Any]:
        return _to_dict(self)
