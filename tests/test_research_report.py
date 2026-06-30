from vibedft.research.models import (
    AnalysisResult,
    ArtifactType,
    EvidenceMaturity,
    EvidenceRef,
    GateDecision,
    GateVerdict,
    PhysicsDescriptor,
    ReliabilityLevel,
    ResultStatus,
)
from vibedft.research.report import (
    build_evidence_pack_from_stages,
    render_claim_report,
    render_evidence_backed_summary,
    workflow_stage_from_analysis,
)


def _decision(
    claim_id: str = "claim.na2.epc",
    verdict: GateVerdict = GateVerdict.BLOCKED,
) -> GateDecision:
    return GateDecision(
        claim_id=claim_id,
        maturity=EvidenceMaturity.PHYSICALLY_USABLE,
        verdict=verdict,
        blocking_reasons=["Finite-q soft mode blocks stable-phase EPC."],
        forbidden_conclusions=["Do not report Tc for the high-symmetry Na_2 phase."],
        recommended_next_actions=["Run mode-following for the unstable branch."],
    )


def test_claim_report_renders_claim_first_markdown_sections():
    decision = _decision()

    report = render_claim_report([decision], title="Na_2 claim gate report")

    assert report.startswith("# Na_2 claim gate report")
    assert "claim.na2.epc" in report
    assert "Forbidden conclusions" in report
    assert "Do not report Tc" in report
    assert "Run mode-following" in report
    assert "Supporting artifacts\n- None" in report
    assert "Missing artifacts\n- None" in report


def test_claim_report_locks_single_decision_section_order_and_enum_format():
    report = render_claim_report([_decision()])

    ordered_markers = [
        "# VibeDFT research claim report",
        "## Claim claim.na2.epc",
        "- Claim id: claim.na2.epc",
        "- Verdict: `blocked`",
        "- Maturity: `physically_usable`",
        "### Blocking reasons",
        "### Supporting artifacts",
        "### Missing artifacts",
        "### Forbidden conclusions",
        "### Recommended next actions",
    ]

    positions = [report.index(marker) for marker in ordered_markers]
    assert positions == sorted(positions)
    assert report.endswith("\n")


def test_claim_report_includes_multiple_decisions_deterministically():
    report = render_claim_report(
        [
            _decision("claim.na2.epc", GateVerdict.BLOCKED),
            _decision("claim.k.negative", GateVerdict.PASS),
        ]
    )

    assert "## Claim claim.na2.epc" in report
    assert "## Claim claim.k.negative" in report
    assert report.index("## Claim claim.na2.epc") < report.index("## Claim claim.k.negative")
    assert "- Verdict: `blocked`" in report
    assert "- Verdict: `pass`" in report


def test_claim_report_renders_empty_decisions_body_and_trailing_newline():
    report = render_claim_report([])

    assert report == "# VibeDFT research claim report\n\nNo gate decisions were provided.\n"


def _analysis_result(
    *,
    status: ResultStatus = ResultStatus.PASS,
    with_evidence: bool = True,
) -> AnalysisResult:
    evidence = []
    if with_evidence:
        evidence = [
            EvidenceRef(
                artifact_path="remote://cluster-a/public-fixtures/K-HfCl2/fullq_8x8_20260623/phonon.freq.gp",
                artifact_type=ArtifactType.DYN,
                parser_name="vibedft.core.phonon.parse_freq_gp",
                parsed_quantity="signed_phonon_frequencies",
                raw_value={"min_frequency_cm1": -87.9888},
                summary="finite-q imaginary branch at -87.9888 cm^-1",
                reliability=ReliabilityLevel.MEDIUM,
            )
        ]
    descriptor = PhysicsDescriptor(
        name="phonon_stability",
        value={"min_frequency_cm1": -87.9888},
        unit="cm^-1",
        evidence=evidence,
        blockers=["finite-q imaginary mode blocks EPC/Tc"],
        reliability=ReliabilityLevel.MEDIUM,
    )
    return AnalysisResult(
        id="analysis.phonon_stability",
        parser_name="vibedft.core.phonon.parse_freq_gp",
        status=status,
        parsed_quantity="phonon_stability",
        evidence=evidence,
        descriptors=[descriptor],
        summary="Phonon stability analysis.",
        blockers=["finite-q imaginary mode blocks EPC/Tc"] if status == ResultStatus.BLOCKED else [],
        reliability=ReliabilityLevel.MEDIUM,
    )


def test_workflow_stage_from_analysis_preserves_evidence_and_blockers():
    analysis = _analysis_result(status=ResultStatus.BLOCKED)

    stage = workflow_stage_from_analysis(
        "05_phonon_dynamics",
        analysis,
        next_actions=["Run mode-following before EPC."],
    )

    assert stage.stage_id == "05_phonon_dynamics"
    assert stage.status == ResultStatus.BLOCKED
    assert stage.evidence[0].parser_name == "vibedft.core.phonon.parse_freq_gp"
    assert stage.descriptors[0].name == "phonon_stability"
    assert "finite-q imaginary mode" in stage.blockers[0]
    assert stage.next_actions == ["Run mode-following before EPC."]


def test_workflow_stage_from_pass_analysis_without_evidence_is_insufficient():
    analysis = _analysis_result(status=ResultStatus.PASS, with_evidence=False)

    stage = workflow_stage_from_analysis("05_phonon_dynamics", analysis)

    assert stage.status == ResultStatus.INSUFFICIENT_EVIDENCE
    assert any("evidence" in blocker.lower() for blocker in stage.blockers)


def test_render_evidence_backed_summary_traces_each_conclusion():
    stage = workflow_stage_from_analysis("05_phonon_dynamics", _analysis_result(status=ResultStatus.BLOCKED))

    report = render_evidence_backed_summary([stage], title="K-HfCl2 evidence summary")

    assert report.startswith("# K-HfCl2 evidence summary")
    assert "## 05_phonon_dynamics" in report
    assert "Status: `blocked`" in report
    assert "Conclusion: stage is blocked" in report
    assert "finite-q imaginary mode blocks EPC/Tc" in report
    assert "remote://cluster-a/public-fixtures/K-HfCl2/fullq_8x8_20260623/phonon.freq.gp" in report
    assert "vibedft.core.phonon.parse_freq_gp" in report
    assert "phonon_stability" in report
    assert "completed conclusion" not in report.lower()


def test_evidence_pack_from_stages_contains_traceable_descriptors():
    stage = workflow_stage_from_analysis("05_phonon_dynamics", _analysis_result(status=ResultStatus.BLOCKED))

    pack = build_evidence_pack_from_stages([stage])

    assert pack["stages"][0]["stage_id"] == "05_phonon_dynamics"
    assert pack["stages"][0]["status"] == "blocked"
    assert pack["stages"][0]["descriptors"][0]["name"] == "phonon_stability"
    assert pack["stages"][0]["evidence"][0]["artifact_path"].startswith("remote://cluster-a")
    assert pack["stages"][0]["evidence"][0]["parser_name"] == "vibedft.core.phonon.parse_freq_gp"
    assert pack["stages"][0]["evidence"][0]["parser_module"] == "vibedft.core.phonon"
    assert pack["stages"][0]["evidence"][0]["parser_version"] == "0.1.0"
    assert pack["unsupported_or_forbidden_conclusions"]
