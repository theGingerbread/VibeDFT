import json

from vibedft.research.models import (
    AnalysisResult,
    ArtifactLineage,
    ArtifactType,
    ClaimStatus,
    ClaimType,
    ComparisonSet,
    EvidenceMaturity,
    EvidenceRef,
    EvidenceRequirement,
    FixtureManifest,
    GateDecision,
    GateVerdict,
    PhysicsDescriptor,
    PhysicsVerdict,
    ReliabilityLevel,
    ResearchQuestion,
    ResultStatus,
    Route,
    ScientificClaim,
    WorkflowStageResult,
)


def test_scientific_claim_round_trips_to_dict():
    question = ResearchQuestion(
        id="rq.doping.hfx2",
        title="Can static doping produce stable EPC superconductivity in HfX2?",
        material_family="HfX2",
        route=Route.STATIC_DOPING,
        hypotheses=["Electron doping can increase N(EF) without destabilizing the layer."],
        scope="Monolayer HfX2 static charge doping",
        excluded_claims=["Final Tc ranking across halogens"],
    )
    claim = ScientificClaim(
        id="claim.hfi2.e005.stability",
        question_id=question.id,
        claim_type=ClaimType.STABILITY,
        statement="HfI2 e0.05 is dynamically stable under a consistent 2D protocol.",
        assumptions=["same pseudopotential family", "fresh prefix/outdir"],
        validity_domain="HfI2 e0.05 benchmark campaign",
        required_evidence_ids=["ev.force", "ev.fullq_phonon"],
        gate_policy_id="gate.stability.fullq",
        status=ClaimStatus.PROVISIONAL,
        status_reason="Legacy data exists but lacks 2D cutoff and SOC.",
    )

    data = claim.to_dict()

    assert data["id"] == "claim.hfi2.e005.stability"
    assert data["claim_type"] == "stability"
    assert data["status"] == "provisional"
    assert data["required_evidence_ids"] == ["ev.force", "ev.fullq_phonon"]


def test_gate_decision_records_forbidden_conclusions():
    decision = GateDecision(
        claim_id="claim.na2.epc",
        maturity=EvidenceMaturity.PHYSICALLY_USABLE,
        verdict=GateVerdict.BLOCKED,
        blocking_reasons=["Finite-q soft mode at q2 is negative."],
        supporting_artifacts=["artifact.ph.p3.q2"],
        missing_artifacts=["artifact.mode_following"],
        forbidden_conclusions=["Do not report Tc for the high-symmetry Na_2 phase."],
        recommended_next_actions=["Converge q2 soft mode before EPC."],
    )

    data = decision.to_dict()

    assert data["maturity"] == "physically_usable"
    assert data["verdict"] == "blocked"
    assert "Do not report Tc" in data["forbidden_conclusions"][0]


def test_artifact_lineage_serializes_parameter_fingerprint():
    artifact = ArtifactLineage(
        artifact_id="artifact.scf.hfi2.e005",
        artifact_type=ArtifactType.OUTPUT,
        server="local",
        path="/tmp/hfi2/scf.out",
        producer_program="pw.x",
        prefix="hfi2_e005",
        outdir="./out",
        parent_artifacts=["artifact.input.scf"],
        structure_source="relax.out final coordinates",
        parameter_fingerprint="ecutwfc=90|ecutrho=720|k=16x16x1|2d=true|soc=false",
        job_status="JOB_DONE",
        parse_status="ok",
        lineage_warnings=[],
    )

    data = artifact.to_dict()

    assert data["artifact_type"] == "output"
    assert data["parameter_fingerprint"].startswith("ecutwfc=90")


def test_future_facing_enum_values_are_available():
    assert Route.TYPE3_HETEROSTRUCTURE.value == "type3_heterostructure"
    assert ClaimType.ELECTRONIC_ORIGIN.value == "electronic_origin"
    assert ClaimType.CHARGE_TRANSFER.value == "charge_transfer"
    assert ClaimType.EPC_MECHANISM.value == "epc_mechanism"
    assert ClaimType.TC_ROBUSTNESS.value == "tc_robustness"
    assert ClaimType.BAND_ALIGNMENT.value == "band_alignment"
    assert ClaimType.NEGATIVE_RESULT.value == "negative_result"
    assert ClaimStatus.REFUTED.value == "refuted"
    assert EvidenceMaturity.RUN_FINISHED.value == "run_finished"
    assert EvidenceMaturity.NUMERICALLY_CONVERGED.value == "numerically_converged"
    assert EvidenceMaturity.PAPER_GRADE.value == "paper_grade"
    assert GateVerdict.WARNING.value == "warning"
    assert ArtifactType.SAVE_DIR.value == "save_dir"
    assert ArtifactType.DYN.value == "dyn"
    assert ArtifactType.A2F.value == "a2f"
    assert ArtifactType.LAMBDAX.value == "lambdax"
    assert ArtifactType.BANDS.value == "bands"
    assert ArtifactType.PDOS.value == "pdos"
    assert ArtifactType.CUBE.value == "cube"
    assert ArtifactType.UNKNOWN.value == "unknown"


def test_evidence_requirement_uses_plan_field_names():
    requirement = EvidenceRequirement(
        id="evreq.fullq.stability",
        claim_type=ClaimType.STABILITY,
        required_artifacts=[ArtifactType.DYN, ArtifactType.OUTPUT],
        required_checks=["all q-points real", "ASR documented"],
        minimum_maturity=EvidenceMaturity.PHYSICALLY_USABLE,
        source_level="full_q_phonon",
        blocking_if_missing=True,
        notes=["Gamma-only PH is not sufficient."],
    )

    data = requirement.to_dict()

    assert data["claim_type"] == "stability"
    assert data["required_artifacts"] == ["dyn", "output"]
    assert data["source_level"] == "full_q_phonon"
    assert data["blocking_if_missing"] is True


def test_comparison_set_uses_plan_field_names():
    comparison = ComparisonSet(
        id="cmp.hfx2.static_doping",
        claim_id="claim.hfx2.tc_robustness",
        control_variables=["pseudo_family", "ecutrho", "kmesh"],
        varied_variables=["halogen", "charge"],
        members=["claim.hfcl2.e005", "claim.hfi2.e005"],
        comparability_requirements=["same 2D cutoff policy"],
        known_incompatibilities=["SOC mismatch"],
    )

    data = comparison.to_dict()

    assert data["claim_id"] == "claim.hfx2.tc_robustness"
    assert data["control_variables"] == ["pseudo_family", "ecutrho", "kmesh"]
    assert data["varied_variables"] == ["halogen", "charge"]
    assert data["members"] == ["claim.hfcl2.e005", "claim.hfi2.e005"]


def test_evidence_ref_round_trips_required_contract_fields():
    evidence = EvidenceRef(
        artifact_path="remote://cluster-b/public-fixtures/HfX2/fermiface/HfBr2/hfbr2_fs.bxsf",
        artifact_type=ArtifactType.BANDS,
        parser_name="vibedft.core.fs.parse_bxsf",
        parsed_quantity="fermi_surface_grid",
        raw_value={"fermi_energy_ev": -2.182511, "grid": [32, 32, 1]},
        summary="BXSF reports 4 EF-crossing bands.",
        warnings=["fs.out energy reference not checked yet"],
        blockers=[],
        confidence=0.82,
        reliability=ReliabilityLevel.MEDIUM,
        metadata={"remote": True, "sample_only": True},
    )

    data = evidence.to_dict()

    assert data["artifact_path"].startswith("remote://cluster-b")
    assert data["artifact_type"] == "bands"
    assert data["parser_name"] == "vibedft.core.fs.parse_bxsf"
    assert data["parser_module"] == "vibedft.core.fs"
    assert data["parser_version"] == "0.1.0"
    assert data["parsed_quantity"] == "fermi_surface_grid"
    assert data["raw_value"]["grid"] == [32, 32, 1]
    assert data["summary"].startswith("BXSF reports")
    assert data["warnings"] == ["fs.out energy reference not checked yet"]
    assert data["blockers"] == []
    assert data["confidence"] == 0.82
    assert data["reliability"] == "medium"

    round_trip = json.loads(json.dumps(data))
    assert round_trip["metadata"] == {"remote": True, "sample_only": True}


def test_analysis_result_and_descriptor_keep_evidence_traceability():
    evidence = EvidenceRef(
        artifact_path="remote://cluster-a/public-fixtures/HfCl2/intercalation/K/TOP_clean/postprocess/fullq_8x8_20260623/phonon.freq.gp",
        artifact_type=ArtifactType.DYN,
        parser_name="vibedft.core.phonon.parse_signed_frequencies",
        parsed_quantity="minimum_frequency_cm-1",
        raw_value=-87.9888,
        summary="Finite-q imaginary phonon branch.",
        warnings=[],
        blockers=["negative phonon frequency blocks EPC/Tc"],
        confidence=0.95,
        reliability=ReliabilityLevel.HIGH,
    )
    descriptor = PhysicsDescriptor(
        name="minimum_phonon_frequency",
        value=-87.9888,
        unit="cm^-1",
        evidence=[evidence],
        warnings=[],
        blockers=["dynamic instability"],
        reliability=ReliabilityLevel.HIGH,
    )
    result = AnalysisResult(
        id="analysis.k_hfcl2.phonon",
        parser_name="vibedft.core.phonon.parse_signed_frequencies",
        status=ResultStatus.BLOCKED,
        parsed_quantity="phonon_stability",
        evidence=[evidence],
        descriptors=[descriptor],
        warnings=[],
        blockers=["Tc cannot be reported for an unstable phase."],
        reliability=ReliabilityLevel.HIGH,
    )

    data = result.to_dict()

    assert data["status"] == "blocked"
    assert data["evidence"][0]["artifact_path"].endswith("phonon.freq.gp")
    assert data["descriptors"][0]["name"] == "minimum_phonon_frequency"
    assert data["blockers"] == ["Tc cannot be reported for an unstable phase."]
    assert data["reliability"] == "high"


def test_physics_verdict_without_supporting_evidence_cannot_default_to_pass():
    verdict = PhysicsVerdict(
        claim_type=ClaimType.TC_ROBUSTNESS,
        status=ResultStatus.PASS,
        conclusion="Tc is reliable.",
        supporting_evidence=[],
    )

    data = verdict.to_dict()

    assert data["status"] == "insufficient_evidence"
    assert data["supporting_evidence"] == []
    assert "supporting evidence" in data["blockers"][0]


def test_workflow_stage_result_lists_status_descriptors_evidence_and_next_actions():
    evidence = EvidenceRef(
        artifact_path="remote://cluster-b/public-fixtures/Type3/hetero/HfBr2_TiSe2/outputs/bader_het/ACF.dat",
        artifact_type=ArtifactType.OUTPUT,
        parser_name="vibedft.properties.bader_parser.parse_acf",
        parsed_quantity="atom_resolved_bader_charge",
        summary="ACF table with atom charge, min distance, and volume.",
        warnings=[],
        blockers=[],
        reliability=ReliabilityLevel.MEDIUM,
    )
    descriptor = PhysicsDescriptor(
        name="layer_charge_transfer",
        value=0.0533,
        unit="e",
        evidence=[evidence],
        reliability=ReliabilityLevel.MEDIUM,
    )
    verdict = PhysicsVerdict(
        claim_type=ClaimType.CHARGE_TRANSFER,
        status=ResultStatus.WARNING,
        conclusion="Charge transfer is present but not a final Type-III proof.",
        supporting_evidence=[evidence],
        warnings=["same-lattice isolated references still required"],
        reliability=ReliabilityLevel.MEDIUM,
    )
    stage = WorkflowStageResult(
        stage_id="04_charge_bader_analysis",
        status=ResultStatus.WARNING,
        descriptors=[descriptor],
        evidence=[evidence],
        verdicts=[verdict],
        warnings=["Bader evidence alone cannot confirm Type-III alignment."],
        blockers=[],
        next_actions=["Parse same-lattice isolated references before final alignment."],
    )

    data = stage.to_dict()

    assert data["stage_id"] == "04_charge_bader_analysis"
    assert data["status"] == "warning"
    assert data["descriptors"][0]["evidence"][0]["parser_name"].endswith("parse_acf")
    assert data["verdicts"][0]["supporting_evidence"][0]["parsed_quantity"] == "atom_resolved_bader_charge"
    assert data["next_actions"] == ["Parse same-lattice isolated references before final alignment."]


def test_fixture_manifest_records_remote_heavy_artifact_metadata_without_importing():
    manifest = FixtureManifest(
        id="fixture.fs.hfbr2",
        source="remote://cluster-b/public-fixtures/HfX2/fermiface/HfBr2",
        artifacts=[
            EvidenceRef(
                artifact_path="remote://cluster-b/public-fixtures/HfX2/fermiface/HfBr2/hfbr2_fs.bxsf",
                artifact_type=ArtifactType.BANDS,
                parser_name="manifest",
                parsed_quantity="artifact_metadata",
                summary="Remote BXSF fixture registered by path and metadata only.",
                metadata={"size_bytes": 7340032, "checksum": "sha256:sample", "sample_lines": 20},
                reliability=ReliabilityLevel.UNKNOWN,
            )
        ],
        import_policy="metadata_only",
        warnings=["heavy artifacts are not copied unless explicitly imported"],
    )

    data = manifest.to_dict()

    assert data["source"].startswith("remote://cluster-b")
    assert data["import_policy"] == "metadata_only"
    assert data["artifacts"][0]["metadata"]["checksum"] == "sha256:sample"
    assert data["artifacts"][0]["raw_value"] is None
    assert "not copied" in data["warnings"][0]
