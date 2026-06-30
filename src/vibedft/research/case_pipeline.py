"""Evidence-backed case pipeline orchestration.

This module is the conservative bridge from an arbitrary case directory to the
research-layer ``WorkflowStageResult`` contract.  Missing artifacts produce
``insufficient_evidence`` stages instead of optimistic defaults.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from vibedft.research.models import (
    AnalysisResult,
    ArtifactType,
    EvidenceRef,
    PhysicsDescriptor,
    ReliabilityLevel,
    ResultStatus,
    WorkflowStageResult,
)
from vibedft.research.report import (
    build_evidence_pack_from_stages,
    render_evidence_backed_summary,
    workflow_stage_from_analysis,
)


CASE_PIPELINE_STAGE_IDS = [
    "00_structure_validation",
    "01_scf_relax",
    "02_electronic_structure",
    "03_fermi_surface_analysis",
    "04_charge_bader_analysis",
    "05_phonon_dynamics",
    "06_epc_superconductivity",
    "07_mechanical_stability",
    "08_band_alignment",
    "09_md_stability",
    "10_final_report_generator",
]


PHYSICS_REPORT_SECTIONS = {
    "phonon_stability": ("05_phonon_dynamics", "phonon_stability_summary"),
    "mechanical_stability": ("07_mechanical_stability", "mechanical_stability_classification"),
    "thermal_stability": ("09_md_stability", "thermal_stability_verdict"),
    "electronic_classification": ("02_electronic_structure", "electronic_structure_summary"),
    "fermi_surface_topology": ("03_fermi_surface_analysis", "fs_topology_summary"),
    "nesting_score": ("03_fermi_surface_analysis", "nesting_score"),
    "charge_transfer_classification": ("04_charge_bader_analysis", "charge_transfer_classification"),
    "band_alignment_classification": ("08_band_alignment", "band_alignment_classification"),
    "superconductivity_reliability": ("06_epc_superconductivity", "superconductivity_reliability"),
}


@dataclass
class CaseEvidencePipelineResult:
    """End-to-end research-layer result for one case directory."""

    case_dir: str
    stages: list[WorkflowStageResult]
    evidence_pack: dict
    summary_markdown: str


@dataclass
class BatchEvidencePipelineResult:
    """Evidence pipeline result for a directory of independent case folders."""

    batch_root: str
    cases: list[CaseEvidencePipelineResult]


def case_evidence_pipeline_payload(result: CaseEvidencePipelineResult) -> dict:
    """Convert a case pipeline result to a stable JSON payload."""

    counts = {
        "pass": 0,
        "warning": 0,
        "blocked": 0,
        "insufficient_evidence": 0,
        "candidate_only": 0,
        "error": 0,
        "not_applicable": 0,
    }
    for stage in result.stages:
        counts[stage.status.value] = counts.get(stage.status.value, 0) + 1

    if counts.get("blocked", 0) or counts.get("error", 0):
        overall_status = "BLOCK"
    elif (
        counts.get("warning", 0)
        or counts.get("insufficient_evidence", 0)
        or counts.get("candidate_only", 0)
    ):
        overall_status = "CONCERN"
    else:
        overall_status = "PASS"

    return {
        "overall_status": overall_status,
        "case_dir": result.case_dir,
        "stage_counts": counts,
        "stages": [stage.to_dict() for stage in result.stages],
        "evidence_pack": result.evidence_pack,
        "physics_report": _physics_report_payload(result),
        "summary_markdown": result.summary_markdown,
    }


def batch_evidence_pipeline_payload(result: BatchEvidencePipelineResult) -> dict:
    """Convert a batch pipeline result to a stable JSON payload."""

    case_payloads = [case_evidence_pipeline_payload(case) for case in result.cases]
    ranked_cases, unranked_cases = _rank_batch_cases(case_payloads)
    counts = {"pass": 0, "concern": 0, "block": 0}
    for case_payload in case_payloads:
        status = case_payload["overall_status"]
        if status == "PASS":
            counts["pass"] += 1
        elif status == "BLOCK":
            counts["block"] += 1
        else:
            counts["concern"] += 1

    if counts["block"]:
        overall_status = "BLOCK"
    elif counts["concern"] or not case_payloads:
        overall_status = "CONCERN"
    else:
        overall_status = "PASS"

    return {
        "overall_status": overall_status,
        "batch_root": result.batch_root,
        "case_counts": counts,
        "ranking_basis": [
            "Only cases with overall_status=PASS are rankable.",
            "Sort keys use passed stage count and evidence count from passed stages only.",
        ],
        "ranked_cases": ranked_cases,
        "unranked_cases": unranked_cases,
        "cases": case_payloads,
    }


def run_case_evidence_pipeline(case_dir: Path | str) -> CaseEvidencePipelineResult:
    """Run available evidence analyzers and return all objective pipeline stages."""

    root = Path(case_dir).resolve()
    stages: list[WorkflowStageResult] = []

    stage_factories = [
        ("00_structure_validation", _structure_validation_stage),
        ("01_scf_relax", _scf_relax_stage),
        ("02_electronic_structure", _electronic_structure_stage),
        ("03_fermi_surface_analysis", _fermi_surface_stage),
        ("04_charge_bader_analysis", _charge_bader_stage),
        ("05_phonon_dynamics", _phonon_dynamics_stage),
        ("06_epc_superconductivity", _epc_superconductivity_stage),
        ("07_mechanical_stability", _mechanical_stability_stage),
        ("08_band_alignment", _band_alignment_stage),
        ("09_md_stability", _md_stability_stage),
    ]
    for stage_id, factory in stage_factories:
        try:
            stages.append(factory(root))
        except Exception as exc:  # pragma: no cover - defensive batch isolation
            stages.append(_error_stage(stage_id, exc))
    stages.append(_final_report_stage(stages))

    evidence_pack = build_evidence_pack_from_stages(stages)
    physics_report = _physics_report_payload_from_parts(stages, evidence_pack)
    summary = _render_case_summary(root, stages, physics_report)
    return CaseEvidencePipelineResult(
        case_dir=str(root),
        stages=stages,
        evidence_pack=evidence_pack,
        summary_markdown=summary,
    )


def discover_case_directories(batch_root: Path | str) -> list[Path]:
    """Return direct child directories that should be treated as case folders."""

    root = Path(batch_root).resolve()
    if not root.is_dir():
        return []
    return sorted(
        (
            child.resolve()
            for child in root.iterdir()
            if child.is_dir() and not child.name.startswith(".")
        ),
        key=lambda child: child.name,
    )


def run_batch_evidence_pipeline(batch_root: Path | str) -> BatchEvidencePipelineResult:
    """Run the evidence pipeline for every direct case directory in a batch."""

    root = Path(batch_root).resolve()
    cases = [run_case_evidence_pipeline(case_dir) for case_dir in discover_case_directories(root)]
    return BatchEvidencePipelineResult(batch_root=str(root), cases=cases)


def _physics_report_payload(result: CaseEvidencePipelineResult) -> dict:
    return _physics_report_payload_from_parts(result.stages, result.evidence_pack)


def _physics_report_payload_from_parts(stages: list[WorkflowStageResult], evidence_pack: dict) -> dict:
    stages_by_id = {stage.stage_id: stage.to_dict() for stage in stages}
    sections = {}
    for section_id, (stage_id, descriptor_name) in PHYSICS_REPORT_SECTIONS.items():
        stage = stages_by_id.get(stage_id)
        sections[section_id] = _physics_report_section(stage, stage_id, descriptor_name)
    return {
        "sections": sections,
        "unsupported_or_forbidden_conclusions": list(
            evidence_pack.get("unsupported_or_forbidden_conclusions", [])
        ),
    }


def _render_case_summary(root: Path, stages: list[WorkflowStageResult], physics_report: dict) -> str:
    workflow_summary = render_evidence_backed_summary(
        stages,
        title=f"VibeDFT evidence-backed case pipeline: {root.name}",
    ).rstrip()
    return "\n\n".join([workflow_summary, _render_physics_report_markdown(physics_report).rstrip()]) + "\n"


def _render_physics_report_markdown(report: dict) -> str:
    lines = ["## Physics Report", ""]
    sections = report.get("sections", {})
    if not sections:
        return "\n".join([*lines, "No physics report sections were generated."]) + "\n"

    for section_id, section in sections.items():
        lines.extend(
            [
                f"### {section_id}",
                "",
                f"- Stage: `{section['stage_id']}`",
                f"- Status: `{section['status']}`",
                f"- Reliability: `{section['reliability']}`",
                f"- Descriptor: `{section['descriptor_name']}`",
                f"- Value: {_compact_report_value(section['value'])}",
                "- Evidence:",
            ]
        )
        evidence_items = section.get("evidence", [])
        if evidence_items:
            for evidence in evidence_items:
                lines.append(
                    "  - "
                    f"path=`{evidence.get('artifact_path')}`; "
                    f"parser=`{evidence.get('parser_name')}`; "
                    f"quantity=`{evidence.get('parsed_quantity')}`; "
                    f"summary={evidence.get('summary') or _compact_report_value(evidence.get('raw_value'))}"
                )
        else:
            lines.append("  - None")

        lines.extend(["- Blockers:", *_indented_list(section.get("blockers", []))])
        lines.extend(["- Warnings:", *_indented_list(section.get("warnings", [])), ""])

    unsupported = report.get("unsupported_or_forbidden_conclusions", [])
    lines.extend(["### unsupported_or_forbidden_conclusions", ""])
    if unsupported:
        for item in unsupported:
            lines.append(
                "- "
                f"stage=`{item.get('stage_id')}`; "
                f"status=`{item.get('status')}`; "
                f"reason={item.get('reason')}"
            )
    else:
        lines.append("- None")
    return "\n".join(lines).rstrip() + "\n"


def _indented_list(items: list[str]) -> list[str]:
    if not items:
        return ["  - None"]
    return [f"  - {item}" for item in items]


def _compact_report_value(value: object) -> str:
    if value is None:
        return "None"
    text = str(value)
    if len(text) <= 180:
        return text
    return text[:177] + "..."


def _physics_report_section(stage: dict | None, stage_id: str, descriptor_name: str) -> dict:
    if stage is None:
        return {
            "stage_id": stage_id,
            "status": ResultStatus.INSUFFICIENT_EVIDENCE.value,
            "descriptor_name": descriptor_name,
            "value": None,
            "evidence": [],
            "warnings": [],
            "blockers": [f"{stage_id} did not run"],
            "reliability": ReliabilityLevel.LOW.value,
        }
    descriptor = next(
        (item for item in stage["descriptors"] if item["name"] == descriptor_name),
        None,
    )
    warnings = list(stage["warnings"])
    blockers = list(stage["blockers"])
    if descriptor is None:
        blockers.append(f"{descriptor_name} descriptor is missing from {stage_id}")
    return {
        "stage_id": stage_id,
        "status": stage["status"],
        "descriptor_name": descriptor_name,
        "value": descriptor["value"] if descriptor else None,
        "evidence": list(stage["evidence"]),
        "warnings": warnings,
        "blockers": blockers,
        "reliability": stage["reliability"],
    }


def _rank_batch_cases(case_payloads: list[dict]) -> tuple[list[dict], list[dict]]:
    rankable: list[dict] = []
    unranked: list[dict] = []
    for case_payload in case_payloads:
        status = case_payload["overall_status"]
        if status != "PASS":
            unranked.append(
                {
                    "case_dir": case_payload["case_dir"],
                    "overall_status": status,
                    "reason": _unranked_reason(case_payload),
                    "stage_counts": case_payload["stage_counts"],
                }
            )
            continue
        passed_stages = [
            stage for stage in case_payload["stages"] if stage["status"] == ResultStatus.PASS.value
        ]
        rankable.append(
            {
                "case_dir": case_payload["case_dir"],
                "overall_status": status,
                "rank_score": {
                    "passed_stage_count": len(passed_stages),
                    "passed_evidence_count": sum(len(stage["evidence"]) for stage in passed_stages),
                },
            }
        )

    rankable.sort(
        key=lambda item: (
            -item["rank_score"]["passed_stage_count"],
            -item["rank_score"]["passed_evidence_count"],
            Path(item["case_dir"]).name,
        )
    )
    for index, item in enumerate(rankable, start=1):
        item["rank"] = index
    return rankable, unranked


def _unranked_reason(case_payload: dict) -> str:
    status = case_payload["overall_status"]
    if status == "BLOCK":
        return "case has blocked or error stages; ranking is forbidden"
    counts = case_payload["stage_counts"]
    if counts.get("insufficient_evidence", 0):
        return "case has insufficient evidence; ranking is withheld"
    if counts.get("warning", 0) or counts.get("candidate_only", 0):
        return "case has warnings or candidate-only stages; ranking is withheld"
    return "case is not fully passed; ranking is withheld"


def _structure_validation_stage(root: Path) -> WorkflowStageResult:
    pw_path = _find_pw_input(root)
    if pw_path is None:
        return _missing_stage("00_structure_validation", "no pw.x input was selected for 2D validation")

    from vibedft.validators.two_d import analyze_2d_validity

    analysis = analyze_2d_validity(
        pw_input_path=pw_path,
        ph_input_path=_find_ph_input(root),
        claim_type="screening",
        is_heterostructure=_looks_like_heterostructure_case(root),
    )
    return _stage_from_analysis("00_structure_validation", analysis)


def _scf_relax_stage(root: Path) -> WorkflowStageResult:
    output_path = _first_file(
        root,
        [
            "relax.out",
            "vc-relax.out",
            "vc_relax.out",
            "scf.out",
            "pw.out",
            "pwx.out",
        ],
    )
    if output_path is None:
        return _missing_stage("01_scf_relax", "no SCF/relax pw.x output artifact found")

    from vibedft.core.analysis import parse_qe_output

    parsed = parse_qe_output(output_path)
    text = output_path.read_text(encoding="utf-8", errors="replace")
    job_done = "JOB DONE" in text
    explicit_not_converged = "convergence NOT achieved" in text
    blockers: list[str] = []
    warnings = list(parsed.raw_errors)
    if explicit_not_converged:
        blockers.append("SCF/relax output explicitly reports convergence NOT achieved")
    elif not parsed.scf_converged and not job_done:
        warnings.append("SCF convergence marker or JOB DONE marker was not found")

    evidence = [
        EvidenceRef(
            artifact_path=str(output_path),
            artifact_type=ArtifactType.OUTPUT,
            parser_name="vibedft.core.analysis.parse_qe_output",
            parsed_quantity="scf_relax_output",
            raw_value={
                "program": parsed.program,
                "version": parsed.version,
                "total_energy_ry": parsed.total_energy_ry,
                "fermi_energy_ev": parsed.fermi_energy_ev,
                "scf_converged": parsed.scf_converged,
                "job_done": job_done,
                "forces_count": len(parsed.forces),
            },
            summary=(
                f"SCF converged={parsed.scf_converged}, "
                f"JOB_DONE={job_done}, E={parsed.total_energy_ry} Ry"
            ),
            warnings=warnings,
            blockers=blockers,
            reliability=ReliabilityLevel.MEDIUM if job_done or parsed.scf_converged else ReliabilityLevel.LOW,
        )
    ]
    descriptor = PhysicsDescriptor(
        name="scf_relax_summary",
        value=evidence[0].raw_value,
        evidence=evidence,
        warnings=warnings,
        blockers=blockers,
        reliability=evidence[0].reliability,
    )
    if blockers:
        status = ResultStatus.BLOCKED
    elif warnings:
        status = ResultStatus.WARNING
    else:
        status = ResultStatus.PASS
    return _stage_from_analysis(
        "01_scf_relax",
        AnalysisResult(
            id="analysis.case.scf_relax",
            parser_name="vibedft.research.case_pipeline._scf_relax_stage",
            status=status,
            parsed_quantity="scf_relax_summary",
            evidence=evidence,
            descriptors=[descriptor],
            raw_value=evidence[0].raw_value,
            summary="Evidence-backed SCF/relax output summary.",
            warnings=warnings,
            blockers=blockers,
            reliability=evidence[0].reliability,
        ),
    )


def _electronic_structure_stage(root: Path) -> WorkflowStageResult:
    bands_path = _first_file(root, ["*.bands", "*.bands.dat", "*.bands.dat.gnu"])
    dos_path = _first_file(root, ["*.dos"])
    if bands_path is None and dos_path is None:
        return _missing_stage("02_electronic_structure", "no coupled bands/DOS artifacts found")

    from vibedft.core.analysis import parse_bands_output, parse_dos_output

    evidence: list[EvidenceRef] = []
    warnings: list[str] = []
    blockers: list[str] = []
    bands_summary = None
    dos_summary = None

    if bands_path is None:
        warnings.append("bands data artifact is missing")
    else:
        bands = parse_bands_output(bands_path, bands_output=_first_file(root, ["bands.out"]))
        bands_summary = {
            "n_bands": bands.n_bands,
            "n_kpoints": bands.n_kpoints,
        }
        if bands.n_bands <= 0 or bands.n_kpoints <= 0:
            warnings.append("bands data did not expose positive band/k-point counts")
        evidence.append(
            EvidenceRef(
                artifact_path=str(bands_path),
                artifact_type=ArtifactType.BANDS,
                parser_name="vibedft.core.analysis.parse_bands_output",
                parsed_quantity="bands",
                raw_value=bands_summary,
                summary=f"Bands={bands.n_bands}, k-points={bands.n_kpoints}",
                warnings=list(warnings),
                reliability=ReliabilityLevel.MEDIUM if bands.n_bands and bands.n_kpoints else ReliabilityLevel.LOW,
            )
        )

    if dos_path is None:
        warnings.append("DOS data artifact is missing")
    else:
        dos = parse_dos_output(dos_path, dos_output=_first_file(root, ["dos.out"]))
        dos_summary = {
            "n_points": dos.n_points,
            "e_fermi_ev": dos.e_fermi_ev,
            "e_min": dos.e_min,
            "e_max": dos.e_max,
        }
        if dos.n_points <= 0:
            warnings.append("DOS data did not expose numeric rows")
        evidence.append(
            EvidenceRef(
                artifact_path=str(dos_path),
                artifact_type=ArtifactType.OUTPUT,
                parser_name="vibedft.core.analysis.parse_dos_output",
                parsed_quantity="dos",
                raw_value=dos_summary,
                summary=f"DOS points={dos.n_points}, EF={dos.e_fermi_ev}",
                warnings=list(warnings),
                reliability=ReliabilityLevel.MEDIUM if dos.n_points else ReliabilityLevel.LOW,
            )
        )

    value = {"bands": bands_summary, "dos": dos_summary}
    descriptors = [
        PhysicsDescriptor(
            name="electronic_structure_summary",
            value=value,
            evidence=evidence,
            warnings=warnings,
            blockers=blockers,
            reliability=ReliabilityLevel.MEDIUM if bands_summary and dos_summary and not warnings else ReliabilityLevel.LOW,
        )
    ]
    status = ResultStatus.WARNING if warnings else ResultStatus.PASS
    return _stage_from_analysis(
        "02_electronic_structure",
        AnalysisResult(
            id="analysis.case.electronic_structure",
            parser_name="vibedft.research.case_pipeline._electronic_structure_stage",
            status=status,
            parsed_quantity="electronic_structure_summary",
            evidence=evidence,
            descriptors=descriptors,
            raw_value=value,
            summary="Evidence-backed bands/DOS case summary.",
            warnings=warnings,
            blockers=blockers,
            reliability=descriptors[0].reliability,
        ),
    )


def _fermi_surface_stage(root: Path) -> WorkflowStageResult:
    bxsf_path = _first_file(root, ["*.bxsf"])
    if bxsf_path is None:
        return _missing_stage("03_fermi_surface_analysis", "no BXSF Fermi-surface artifact found")

    from vibedft.core.fs import analyze_fermi_surface

    fs_out_path = _first_file(root, ["fs.out"])
    analysis = analyze_fermi_surface(bxsf_path, fs_out_path=fs_out_path)
    return _stage_from_analysis("03_fermi_surface_analysis", analysis)


def _charge_bader_stage(root: Path) -> WorkflowStageResult:
    acf_path = _first_acf_file(root)
    if acf_path is None:
        return _missing_stage("04_charge_bader_analysis", "no Bader ACF.dat artifact found")

    from vibedft.properties.charge import analyze_charge_evidence

    analysis = analyze_charge_evidence(
        hetero_acf_path=acf_path,
        planar_profile_path=_first_file(root, ["planar_avg.dat", "pot_z.dat", "rho_hetero.dat"]),
        cube_path=_first_file(root, ["*.cube"]),
    )
    return _stage_from_analysis("04_charge_bader_analysis", analysis)


def _phonon_dynamics_stage(root: Path) -> WorkflowStageResult:
    freq_path = _first_file(root, ["*.freq.gp", "freq.gp"])
    dynmat_path = _first_file(root, ["dynmat.out", "*dynmat*.out"])
    if freq_path is None and dynmat_path is None:
        return _missing_stage("05_phonon_dynamics", "no phonon freq.gp or dynmat output artifact found")

    if freq_path is not None:
        from vibedft.core.phonon import parse_freq_gp

        phonon = parse_freq_gp(freq_path)
        blockers: list[str] = []
        warnings: list[str] = []
        if not phonon.has_data:
            blockers.append("phonon frequency evidence is missing or empty")
        elif phonon.min_frequency_cm1 < 0:
            blockers.append(
                "negative phonon frequency indicates dynamic instability: "
                f"min_frequency_cm1={phonon.min_frequency_cm1:.3f}"
            )
        value = {
            "n_qpoints": phonon.n_qpoints,
            "n_branches": phonon.n_branches,
            "min_frequency_cm1": phonon.min_frequency_cm1 if phonon.has_data else None,
            "max_frequency_cm1": phonon.max_frequency_cm1 if phonon.has_data else None,
            "imaginary_modes": phonon.imaginary_modes,
        }
        evidence = [
            EvidenceRef(
                artifact_path=str(freq_path),
                artifact_type=ArtifactType.DYN,
                parser_name="vibedft.core.phonon.parse_freq_gp",
                parsed_quantity="phonon_dispersion",
                raw_value=value,
                summary=f"freq.gp qpoints={phonon.n_qpoints}, min={value['min_frequency_cm1']}",
                warnings=warnings,
                blockers=blockers,
                reliability=ReliabilityLevel.MEDIUM if phonon.has_data else ReliabilityLevel.LOW,
            )
        ]
        return _stage_from_analysis(
            "05_phonon_dynamics",
            AnalysisResult(
                id="analysis.case.phonon_dynamics",
                parser_name="vibedft.research.case_pipeline._phonon_dynamics_stage",
                status=ResultStatus.BLOCKED if blockers else ResultStatus.PASS,
                parsed_quantity="phonon_stability",
                evidence=evidence,
                descriptors=[
                    PhysicsDescriptor(
                        name="phonon_stability_summary",
                        value=value,
                        evidence=evidence,
                        warnings=warnings,
                        blockers=blockers,
                        reliability=evidence[0].reliability,
                    )
                ],
                raw_value=value,
                summary="Evidence-backed signed phonon stability summary.",
                warnings=warnings,
                blockers=blockers,
                reliability=evidence[0].reliability,
                metadata={
                    "forbidden_conclusions": [
                        "Do not claim dynamic stability when signed phonon frequencies are negative."
                    ] if blockers else [],
                },
            ),
        )

    from vibedft.core.phonon import parse_dynmat_output

    dynmat = parse_dynmat_output(dynmat_path) if dynmat_path is not None else None
    blockers = []
    if dynmat is None:
        blockers.append("dynmat output is missing or unparseable")
        value = {}
    else:
        value = {
            "q_point": dynmat.q_point,
            "n_modes": dynmat.n_modes,
            "min_frequency_cm1": min(dynmat.frequencies_cm1) if dynmat.frequencies_cm1 else None,
            "has_imaginary": dynmat.has_imaginary,
        }
        if dynmat.has_imaginary:
            blockers.append("dynmat output contains signed imaginary modes")
    evidence = [
        EvidenceRef(
            artifact_path=str(dynmat_path),
            artifact_type=ArtifactType.DYN,
            parser_name="vibedft.core.phonon.parse_dynmat_output",
            parsed_quantity="dynmat_modes",
            raw_value=value,
            summary=f"dynmat modes={value.get('n_modes')}, imaginary={value.get('has_imaginary')}",
            blockers=blockers,
            reliability=ReliabilityLevel.MEDIUM if dynmat is not None else ReliabilityLevel.LOW,
        )
    ]
    return _stage_from_analysis(
        "05_phonon_dynamics",
        AnalysisResult(
            id="analysis.case.phonon_dynamics",
            parser_name="vibedft.research.case_pipeline._phonon_dynamics_stage",
            status=ResultStatus.BLOCKED if blockers else ResultStatus.PASS,
            parsed_quantity="phonon_stability",
            evidence=evidence,
            descriptors=[
                PhysicsDescriptor(
                    name="phonon_stability_summary",
                    value=value,
                    evidence=evidence,
                    blockers=blockers,
                    reliability=evidence[0].reliability,
                )
            ],
            raw_value=value,
            summary="Evidence-backed dynmat stability summary.",
            blockers=blockers,
            reliability=evidence[0].reliability,
        ),
    )


def _epc_superconductivity_stage(root: Path) -> WorkflowStageResult:
    lambdax_path = _first_file(root, ["lambdax.out"])
    if lambdax_path is None:
        return _missing_stage("06_epc_superconductivity", "no lambdax.out EPC/Tc artifact found")

    from vibedft.core.tc import analyze_superconductivity_reliability

    analysis = analyze_superconductivity_reliability(
        lambdax_path,
        phonon_freq_path=_first_file(root, ["*.freq.gp", "freq.gp"]),
        alpha2f_path=_first_file(root, ["alpha2F.dat", "alpha2f.dat", "a2F.dat"]),
        lambda_dat_path=_first_file(root, ["lambda.dat"]),
    )
    return _stage_from_analysis("06_epc_superconductivity", analysis)


def _mechanical_stability_stage(root: Path) -> WorkflowStageResult:
    elastic_path = _first_file(root, ["elastic_tensor.dat", "*elastic*.dat", "*elastic*.txt"])
    if elastic_path is None:
        return _missing_stage("07_mechanical_stability", "no elastic strain-sweep tensor artifact found")

    from vibedft.properties.elastic import analyze_mechanical_stability

    analysis = analyze_mechanical_stability(elastic_tensor_path=elastic_path)
    return _stage_from_analysis("07_mechanical_stability", analysis)


def _band_alignment_stage(root: Path) -> WorkflowStageResult:
    band_edge_paths = sorted(root.rglob("*.band_edges"))
    if len(band_edge_paths) < 2:
        band_edge_paths = sorted(root.rglob("*band_edge*.txt"))
    if len(band_edge_paths) < 2:
        return _missing_stage("08_band_alignment", "fewer than two same-lattice band-edge reference artifacts found")

    from vibedft.properties.band_alignment import analyze_band_alignment

    reference_paths = {path.stem: path for path in band_edge_paths[:2]}
    analysis = analyze_band_alignment(
        reference_band_edge_paths=reference_paths,
        planar_profile_path=_first_file(root, ["planar_avg.dat", "pot_z.dat"]),
        heterostructure_input_path=_find_pw_input(root),
        layer_projected_bands_path=_first_file(root, ["*layer_projected*", "*projected_bands*"]),
        relaxed_structure_path=_first_file(root, ["relaxed_structure.out", "*relaxed_structure*", "relax.out", "vc-relax.out"]),
        bands_output_path=_first_file(root, ["bands.out"]),
    )
    return _stage_from_analysis("08_band_alignment", analysis)


def _md_stability_stage(root: Path) -> WorkflowStageResult:
    has_md_artifact = any(
        _first_file(root, [pattern]) is not None
        for pattern in ["T_K.dat", "md.out", "*md*.out", "traj.xyz"]
    )
    if not has_md_artifact:
        return _missing_stage("09_md_stability", "no MD temperature or trajectory artifacts found")

    from vibedft.properties.aimd_analyzer import analyze_md_stability

    analysis = analyze_md_stability(root)
    return _stage_from_analysis("09_md_stability", analysis)


def _final_report_stage(stages: list[WorkflowStageResult]) -> WorkflowStageResult:
    blocked = [
        stage.stage_id
        for stage in stages
        if stage.status in {ResultStatus.BLOCKED, ResultStatus.ERROR}
    ]
    insufficient = [
        stage.stage_id
        for stage in stages
        if stage.status == ResultStatus.INSUFFICIENT_EVIDENCE
    ]
    descriptors = [
        PhysicsDescriptor(
            name="case_pipeline_stage_status",
            value={stage.stage_id: stage.status.value for stage in stages},
            reliability=ReliabilityLevel.LOW,
        )
    ]

    if blocked:
        return WorkflowStageResult(
            stage_id="10_final_report_generator",
            status=ResultStatus.BLOCKED,
            descriptors=descriptors,
            blockers=[
                "upstream stage blocked; report must not promote final claims",
                f"blocked_upstream_stages={blocked}",
            ],
            next_actions=["resolve blocked upstream stages before publishing final claims"],
            reliability=ReliabilityLevel.LOW,
        )
    if insufficient:
        return WorkflowStageResult(
            stage_id="10_final_report_generator",
            status=ResultStatus.WARNING,
            descriptors=descriptors,
            warnings=[f"insufficient_evidence_upstream_stages={insufficient}"],
            next_actions=["treat missing stages as candidate-only or collect more evidence"],
            reliability=ReliabilityLevel.LOW,
        )
    return WorkflowStageResult(
        stage_id="10_final_report_generator",
        status=ResultStatus.PASS,
        descriptors=descriptors,
        next_actions=["render evidence-backed report from stage pack"],
        reliability=ReliabilityLevel.MEDIUM,
    )


def _stage_from_analysis(stage_id: str, analysis) -> WorkflowStageResult:
    stage = workflow_stage_from_analysis(stage_id, analysis)
    forbidden = analysis.metadata.get("forbidden_conclusions", [])
    if forbidden and stage.status in {ResultStatus.BLOCKED, ResultStatus.ERROR}:
        stage.blockers.extend(str(item) for item in forbidden)
    return stage


def _error_stage(stage_id: str, exc: Exception) -> WorkflowStageResult:
    return WorkflowStageResult(
        stage_id=stage_id,
        status=ResultStatus.ERROR,
        descriptors=[
            PhysicsDescriptor(
                name="stage_error",
                value=str(exc),
                blockers=[str(exc)],
                reliability=ReliabilityLevel.LOW,
            )
        ],
        blockers=[f"{type(exc).__name__}: {exc}"],
        next_actions=[f"inspect parser inputs for {stage_id}"],
        reliability=ReliabilityLevel.LOW,
    )


def _missing_stage(stage_id: str, reason: str) -> WorkflowStageResult:
    return WorkflowStageResult(
        stage_id=stage_id,
        status=ResultStatus.INSUFFICIENT_EVIDENCE,
        descriptors=[
            PhysicsDescriptor(
                name="stage_evidence_status",
                value="missing",
                blockers=[reason],
                reliability=ReliabilityLevel.LOW,
            )
        ],
        blockers=[reason],
        next_actions=[f"collect evidence for {stage_id}"],
        reliability=ReliabilityLevel.LOW,
    )


def _first_file(root: Path, patterns: list[str]) -> Path | None:
    for pattern in patterns:
        matches = sorted(path for path in root.rglob(pattern) if path.is_file())
        if matches:
            return matches[0]
    return None


def _find_pw_input(root: Path) -> Path | None:
    for path in sorted(root.rglob("*.in")):
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        lowered = text.lower()
        if "&inputph" in lowered:
            continue
        if "&system" in lowered or "atomic_positions" in lowered or "cell_parameters" in lowered:
            return path
    return None


def _find_ph_input(root: Path) -> Path | None:
    for path in sorted(root.rglob("*.in")):
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="replace").lower()
        if "&inputph" in text or "nq1" in text and "nq2" in text:
            return path
    return None


def _first_acf_file(root: Path) -> Path | None:
    candidates = sorted(root.rglob("ACF.dat"))
    if not candidates:
        return None
    preferred = [
        path
        for path in candidates
        if any(token in path.as_posix().lower() for token in ("hetero", "het", "bader_het"))
    ]
    return preferred[0] if preferred else candidates[0]


def _looks_like_heterostructure_case(root: Path) -> bool:
    name = root.as_posix().lower()
    if any(token in name for token in ("hetero", "type3", "type-iii", "type_iii")):
        return True
    return len(list(root.rglob("*.band_edges"))) >= 2
