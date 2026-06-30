"""Real-data regression manifest coverage checks."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from vibedft.research.models import (
    AnalysisResult,
    FixtureManifest,
    PhysicsDescriptor,
    ReliabilityLevel,
    ResultStatus,
)


@dataclass(frozen=True)
class RealDataFixtureRequirement:
    """One required fixture category from the objective real-data suite."""

    key: str
    module: str
    description: str


REALDATA_REGRESSION_REQUIREMENTS: tuple[RealDataFixtureRequirement, ...] = (
    RealDataFixtureRequirement(
        "fs_hfbr2_bxsf", "fs", "HfBr2 fermiface BXSF fixture"
    ),
    RealDataFixtureRequirement(
        "fs_hfcl2_bxsf", "fs", "HfCl2 fermiface BXSF fixture"
    ),
    RealDataFixtureRequirement(
        "fs_hfi2_bxsf", "fs", "HfI2 fermiface BXSF fixture"
    ),
    RealDataFixtureRequirement(
        "electronic_hfbr2_e0p05_bands_dos",
        "electronic",
        "HfBr2 e0p05 bands/DOS fixture",
    ),
    RealDataFixtureRequirement(
        "electronic_hfbr2_e0p10_bands_dos",
        "electronic",
        "HfBr2 e0p10 bands/DOS fixture",
    ),
    RealDataFixtureRequirement(
        "electronic_hfbr2_e0p15_bands_dos",
        "electronic",
        "HfBr2 e0p15 bands/DOS fixture",
    ),
    RealDataFixtureRequirement(
        "bader_hfbr2_tise2_het_acf",
        "charge",
        "HfBr2/TiSe2 heterostructure ACF.dat fixture",
    ),
    RealDataFixtureRequirement(
        "bader_hfbr2_tise2_hfbr2_ref_acf",
        "charge",
        "HfBr2/TiSe2 HfBr2 reference ACF.dat fixture",
    ),
    RealDataFixtureRequirement(
        "bader_hfbr2_tise2_tise2_ref_acf",
        "charge",
        "HfBr2/TiSe2 TiSe2 reference ACF.dat fixture",
    ),
    RealDataFixtureRequirement(
        "charge_hfbr2_tise2_rho_cube",
        "charge",
        "HfBr2/TiSe2 rho.cube metadata fixture",
    ),
    RealDataFixtureRequirement(
        "charge_hfbr2_tise2_rho_hetero",
        "charge",
        "HfBr2/TiSe2 rho_hetero.dat redistribution fixture",
    ),
    RealDataFixtureRequirement(
        "planar_hfbr2_tise2_planar_avg",
        "planar",
        "HfBr2/TiSe2 planar_avg.dat fixture",
    ),
    RealDataFixtureRequirement(
        "planar_hfbr2_tise2_pot_z",
        "planar",
        "HfBr2/TiSe2 pot_z.dat fixture",
    ),
    RealDataFixtureRequirement(
        "epc_positive_hfi2_ph48_ph64",
        "epc",
        "HfI2 ph48/ph64 positive EPC fixture",
    ),
    RealDataFixtureRequirement(
        "epc_positive_hfbr2_e0p02",
        "epc",
        "HfBr2 e0p02 positive EPC fixture",
    ),
    RealDataFixtureRequirement(
        "epc_negative_k_hfcl2_top",
        "epc",
        "K-HfCl2 TOP negative EPC/Tc gate fixture",
    ),
    RealDataFixtureRequirement(
        "phonon_asr_na2_p3_asr",
        "phonon",
        "Na2 P3 ASR phonon sensitivity fixture",
    ),
    RealDataFixtureRequirement(
        "phonon_asr_na2_p3_no_asr",
        "phonon",
        "Na2 P3 no-ASR phonon sensitivity fixture",
    ),
    RealDataFixtureRequirement(
        "type3_blocker_hfbr2_tise2_gamma_unstable",
        "band_alignment",
        "HfBr2/TiSe2 Gamma-unstable Type-III blocker fixture",
    ),
    RealDataFixtureRequirement(
        "md_snse2_md300k_nvt",
        "md",
        "SnSe2 md300k_nvt QE MD fixture",
    ),
    RealDataFixtureRequirement(
        "elastic_synthetic_until_real_strain",
        "elastic",
        "Synthetic elastic fixture until real strain-sweep data exists",
    ),
)


def validate_realdata_regression_manifest(
    manifest: FixtureManifest,
    *,
    required_keys: Iterable[str] | None = None,
) -> AnalysisResult:
    """Validate coverage and expected outcomes for the real-data regression suite."""

    selected_keys = tuple(required_keys) if required_keys is not None else None
    requirements = _selected_requirements(selected_keys)
    required_key_set = {requirement.key for requirement in requirements}
    artifacts_by_key = {
        str(artifact.metadata.get("fixture_key")): artifact
        for artifact in manifest.artifacts
        if artifact.metadata.get("fixture_key")
    }

    warnings = list(manifest.warnings)
    blockers = list(manifest.blockers)

    missing_keys = [
        requirement.key for requirement in requirements if requirement.key not in artifacts_by_key
    ]
    for key in missing_keys:
        blockers.append(f"missing required real-data fixture: {key}")

    duplicate_keys = _duplicate_fixture_keys(manifest)
    for key in duplicate_keys:
        blockers.append(f"duplicate real-data fixture key: {key}")

    for artifact in manifest.artifacts:
        fixture_key = str(artifact.metadata.get("fixture_key") or "")
        if selected_keys is not None and fixture_key not in required_key_set:
            continue
        if not fixture_key:
            warnings.append(f"artifact has no fixture_key: {artifact.artifact_path}")
        if not artifact.artifact_path:
            blockers.append("real-data fixture artifact_path is required")
        for artifact_blocker in artifact.blockers:
            if artifact_blocker in {
                "artifact_path is required",
                "raw_value is non-finite",
            }:
                blockers.append(f"{fixture_key or artifact.artifact_path}: {artifact_blocker}")
        blockers.extend(_expectation_blockers(fixture_key, artifact.metadata))

    covered_keys = [requirement.key for requirement in requirements if requirement.key in artifacts_by_key]
    known_negative = _expectations_by_outcome(
        manifest,
        required_key_set,
        {"negative_gate", "known_negative", "blocker", "type3_blocker"},
    )
    missing_data = _expectations_by_outcome(
        manifest,
        required_key_set,
        {"missing_data", "insufficient_evidence"},
    )
    coverage = {
        "required_count": len(requirements),
        "present_count": len(covered_keys),
        "covered_keys": covered_keys,
        "missing_keys": missing_keys,
    }
    descriptors = [
        PhysicsDescriptor(
            name="realdata_fixture_coverage",
            value=coverage,
            evidence=list(manifest.artifacts),
            warnings=warnings,
            blockers=blockers,
            reliability=ReliabilityLevel.MEDIUM if not blockers else ReliabilityLevel.LOW,
        ),
        PhysicsDescriptor(
            name="realdata_known_negative_expectations",
            value=known_negative,
            evidence=list(manifest.artifacts),
            warnings=warnings,
            blockers=blockers,
            reliability=ReliabilityLevel.MEDIUM if not blockers else ReliabilityLevel.LOW,
        ),
        PhysicsDescriptor(
            name="realdata_missing_data_expectations",
            value=missing_data,
            evidence=list(manifest.artifacts),
            warnings=warnings,
            blockers=blockers,
            reliability=ReliabilityLevel.MEDIUM if not blockers else ReliabilityLevel.LOW,
        ),
    ]

    status = ResultStatus.BLOCKED if blockers else ResultStatus.PASS
    return AnalysisResult(
        id="analysis.realdata_regression_manifest",
        parser_name="vibedft.research.regression.validate_realdata_regression_manifest",
        status=status,
        parsed_quantity="realdata_regression_fixture_coverage",
        evidence=list(manifest.artifacts),
        descriptors=descriptors,
        raw_value={
            "coverage": coverage,
            "known_negative": known_negative,
            "missing_data": missing_data,
        },
        summary="Real-data regression manifest coverage and gate expectation check.",
        warnings=warnings,
        blockers=blockers,
        reliability=ReliabilityLevel.MEDIUM if status == ResultStatus.PASS else ReliabilityLevel.LOW,
    )


def run_realdata_parser_smoke(
    manifest: FixtureManifest,
    *,
    fixture_keys: Iterable[str] | None = None,
    fixture_root: str | Path | None = None,
) -> AnalysisResult:
    """Run parser/gate smoke checks for manifest entries with local samples."""

    selected_keys = tuple(fixture_keys) if fixture_keys is not None else tuple(
        str(artifact.metadata.get("fixture_key"))
        for artifact in manifest.artifacts
        if artifact.metadata.get("fixture_key") and artifact.metadata.get("sample_path")
    )
    root = Path(fixture_root) if fixture_root is not None else Path.cwd()
    artifacts_by_key = {
        str(artifact.metadata.get("fixture_key")): artifact
        for artifact in manifest.artifacts
        if artifact.metadata.get("fixture_key")
    }

    warnings: list[str] = []
    blockers: list[str] = []
    has_insufficient = False
    smoke_results: dict[str, dict[str, object]] = {}

    for fixture_key in selected_keys:
        artifact = artifacts_by_key.get(fixture_key)
        if artifact is None:
            blockers.append(f"fixture key not found in manifest: {fixture_key}")
            smoke_results[fixture_key] = {
                "parser_status": ResultStatus.INSUFFICIENT_EVIDENCE.value,
                "status_matches_expectation": False,
                "summary": "Fixture key is absent from manifest.",
            }
            continue

        expected_status = str(artifact.metadata.get("expected_status") or "")
        expected_outcome = str(artifact.metadata.get("expected_outcome") or "")
        if expected_outcome in {"missing_data", "insufficient_evidence"}:
            parser_status = ResultStatus.INSUFFICIENT_EVIDENCE.value
            smoke_results[fixture_key] = {
                "parser_status": parser_status,
                "expected_status": expected_status,
                "status_matches_expectation": expected_status == parser_status,
                "summary": "Fixture is explicitly marked as missing real data.",
                "sample_path": str(artifact.metadata.get("sample_path") or ""),
            }
            if expected_status != parser_status:
                blockers.append(
                    f"missing-data fixture {fixture_key} must expect insufficient_evidence"
                )
            continue

        sample_path = str(artifact.metadata.get("sample_path") or "")
        if not sample_path:
            has_insufficient = True
            blockers.append(f"sample_path is required for parser smoke: {fixture_key}")
            smoke_results[fixture_key] = {
                "parser_status": ResultStatus.INSUFFICIENT_EVIDENCE.value,
                "expected_status": expected_status,
                "status_matches_expectation": False,
                "summary": "No local parser-smoke sample is registered.",
            }
            continue

        resolved_sample = _resolve_sample_path(sample_path, root)
        if not resolved_sample.exists():
            has_insufficient = True
            blockers.append(f"sample_path not found for parser smoke: {fixture_key}")
            smoke_results[fixture_key] = {
                "parser_status": ResultStatus.INSUFFICIENT_EVIDENCE.value,
                "expected_status": expected_status,
                "status_matches_expectation": False,
                "sample_path": str(resolved_sample),
                "summary": "Registered sample file is missing.",
            }
            continue

        parser_status, parser_name, summary, parser_warnings, parser_blockers = _run_smoke_parser(
            artifact.metadata,
            resolved_sample,
            root,
        )
        warnings.extend(parser_warnings)
        if parser_status == ResultStatus.INSUFFICIENT_EVIDENCE.value:
            has_insufficient = True
        status_matches = _status_matches_expected(parser_status, expected_status)
        if not status_matches:
            blockers.append(
                f"parser smoke status mismatch for {fixture_key}: expected {expected_status}, got {parser_status}"
            )
        smoke_results[fixture_key] = {
            "parser_status": parser_status,
            "expected_status": expected_status,
            "status_matches_expectation": status_matches,
            "parser_name": parser_name,
            "sample_path": str(resolved_sample),
            "summary": summary,
            "warnings": parser_warnings,
            "blockers": parser_blockers,
        }

    status = ResultStatus.PASS
    if blockers:
        status = ResultStatus.INSUFFICIENT_EVIDENCE if has_insufficient else ResultStatus.BLOCKED

    descriptors = [
        PhysicsDescriptor(
            name="realdata_parser_smoke_results",
            value=smoke_results,
            evidence=list(manifest.artifacts),
            warnings=warnings,
            blockers=blockers,
            reliability=ReliabilityLevel.MEDIUM if status == ResultStatus.PASS else ReliabilityLevel.LOW,
        )
    ]
    return AnalysisResult(
        id="analysis.realdata_parser_smoke",
        parser_name="vibedft.research.regression.run_realdata_parser_smoke",
        status=status,
        parsed_quantity="realdata_parser_smoke",
        evidence=list(manifest.artifacts),
        descriptors=descriptors,
        raw_value=smoke_results,
        summary="Parser smoke checks for hydrated real-data regression manifest samples.",
        warnings=warnings,
        blockers=blockers,
        reliability=ReliabilityLevel.MEDIUM if status == ResultStatus.PASS else ReliabilityLevel.LOW,
    )


def _selected_requirements(
    required_keys: tuple[str, ...] | None,
) -> tuple[RealDataFixtureRequirement, ...]:
    if required_keys is None:
        return REALDATA_REGRESSION_REQUIREMENTS
    requirement_by_key = {
        requirement.key: requirement for requirement in REALDATA_REGRESSION_REQUIREMENTS
    }
    return tuple(
        requirement_by_key.get(
            key,
            RealDataFixtureRequirement(key=key, module="custom", description=key),
        )
        for key in required_keys
    )


def _duplicate_fixture_keys(manifest: FixtureManifest) -> list[str]:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for artifact in manifest.artifacts:
        key = str(artifact.metadata.get("fixture_key") or "")
        if not key:
            continue
        if key in seen:
            duplicates.add(key)
        seen.add(key)
    return sorted(duplicates)


def _expectation_blockers(fixture_key: str, metadata: dict[str, object]) -> list[str]:
    expected_outcome = str(metadata.get("expected_outcome") or "")
    expected_status = str(metadata.get("expected_status") or "")
    blockers: list[str] = []

    if expected_outcome in {"negative_gate", "known_negative", "blocker", "type3_blocker"}:
        if expected_status in {"pass", "supported", "ready", "paper_grade"}:
            blockers.append(
                f"negative fixture {fixture_key} must not expect positive status {expected_status}"
            )
    if expected_outcome in {"missing_data", "insufficient_evidence"}:
        if expected_status != ResultStatus.INSUFFICIENT_EVIDENCE.value:
            blockers.append(
                f"missing-data fixture {fixture_key} must expect insufficient_evidence"
            )
    return blockers


def _expectations_by_outcome(
    manifest: FixtureManifest,
    required_keys: set[str],
    outcomes: set[str],
) -> dict[str, dict[str, str]]:
    values: dict[str, dict[str, str]] = {}
    for artifact in manifest.artifacts:
        fixture_key = str(artifact.metadata.get("fixture_key") or "")
        if fixture_key not in required_keys:
            continue
        expected_outcome = str(artifact.metadata.get("expected_outcome") or "")
        if expected_outcome not in outcomes:
            continue
        values[fixture_key] = {
            "artifact_path": artifact.artifact_path,
            "expected_outcome": expected_outcome,
            "expected_status": str(artifact.metadata.get("expected_status") or ""),
            "module": str(artifact.metadata.get("module") or ""),
        }
    return values


def _run_smoke_parser(
    metadata: dict[str, object],
    sample_path: Path,
    fixture_root: Path,
) -> tuple[str, str, str, list[str], list[str]]:
    smoke_parser = str(metadata.get("smoke_parser") or "")
    if smoke_parser == "fs.bxsf":
        from vibedft.core.fs import analyze_fermi_surface

        result = analyze_fermi_surface(sample_path)
        return (
            _status_value(result.status),
            result.parser_name,
            result.summary,
            list(result.warnings),
            list(result.blockers),
        )
    if smoke_parser == "tc.reliability":
        from vibedft.core.tc import analyze_superconductivity_reliability

        phonon_sample = str(metadata.get("phonon_freq_sample_path") or "")
        phonon_path = _resolve_sample_path(phonon_sample, fixture_root) if phonon_sample else None
        result = analyze_superconductivity_reliability(
            sample_path,
            phonon_freq_path=phonon_path if phonon_path and phonon_path.is_file() else None,
        )
        return (
            _status_value(result.status),
            result.parser_name,
            result.summary,
            list(result.warnings),
            list(result.blockers),
        )
    if smoke_parser == "elastic.mechanical":
        return (
            ResultStatus.INSUFFICIENT_EVIDENCE.value,
            "vibedft.properties.elastic.analyze_mechanical_stability",
            "Real strain-sweep elastic evidence is not available; synthetic schema fixture is metadata-only.",
            [],
            [],
        )
    if smoke_parser == "charge.analysis":
        from vibedft.properties.charge import analyze_charge_evidence

        reference_paths = _resolve_sample_mapping(
            metadata.get("reference_acf_sample_paths"),
            fixture_root,
        )
        planar_profile_path = _resolve_optional_metadata_path(
            metadata.get("planar_profile_sample_path"),
            fixture_root,
        )
        cube_path = _resolve_optional_metadata_path(
            metadata.get("cube_sample_path"),
            fixture_root,
        )
        result = analyze_charge_evidence(
            hetero_acf_path=sample_path,
            reference_acf_paths=reference_paths,
            layer_atom_indices=_metadata_int_lists(metadata.get("layer_atom_indices")),
            planar_profile_path=planar_profile_path,
            cube_path=cube_path,
        )
        return (
            _status_value(result.status),
            result.parser_name,
            result.summary,
            list(result.warnings),
            list(result.blockers),
        )
    if smoke_parser == "charge.acf":
        from vibedft.properties.charge import parse_acf_dat

        data = parse_acf_dat(sample_path)
        if data.parse_errors or not data.has_data:
            parser_status = ResultStatus.INSUFFICIENT_EVIDENCE.value
        elif data.warnings:
            parser_status = ResultStatus.WARNING.value
        else:
            parser_status = ResultStatus.PASS.value
        return (
            parser_status,
            "vibedft.properties.charge.parse_acf_dat",
            f"Parsed ACF table with {data.n_atoms} atoms.",
            list(data.warnings),
            list(data.parse_errors),
        )
    if smoke_parser == "charge.cube_metadata":
        from vibedft.properties.charge import parse_cube_metadata

        cube = parse_cube_metadata(sample_path)
        parser_status = (
            ResultStatus.PASS.value
            if cube.has_data and not cube.parse_errors
            else ResultStatus.INSUFFICIENT_EVIDENCE.value
        )
        return (
            parser_status,
            "vibedft.properties.charge.parse_cube_metadata",
            f"Parsed cube metadata grid={cube.grid}, atoms={cube.n_atoms}.",
            [],
            list(cube.parse_errors),
        )
    if smoke_parser == "charge.planar_profile":
        from vibedft.properties.charge import parse_planar_profile

        profile = parse_planar_profile(sample_path)
        if not profile.has_data and profile.parse_errors:
            parser_status = ResultStatus.INSUFFICIENT_EVIDENCE.value
        elif profile.blockers:
            parser_status = ResultStatus.BLOCKED.value
        elif profile.warnings or profile.parse_errors:
            parser_status = ResultStatus.WARNING.value
        else:
            parser_status = ResultStatus.PASS.value
        return (
            parser_status,
            "vibedft.properties.charge.parse_planar_profile",
            f"Parsed planar profile with {profile.n_points} points.",
            list(profile.warnings + profile.parse_errors),
            list(profile.blockers),
        )
    if smoke_parser == "phonon.freq_gp":
        from vibedft.core.phonon import parse_freq_gp

        dispersion = parse_freq_gp(sample_path)
        if not dispersion.has_data:
            parser_status = ResultStatus.INSUFFICIENT_EVIDENCE.value
            parser_warnings: list[str] = []
            parser_blockers = ["phonon freq.gp sample has no parseable data"]
        elif dispersion.min_frequency_cm1 < 0.0:
            parser_status = ResultStatus.WARNING.value
            parser_warnings = [
                f"signed negative phonon frequency retained: {dispersion.min_frequency_cm1:.6f} cm-1"
            ]
            parser_blockers = []
        else:
            parser_status = ResultStatus.PASS.value
            parser_warnings = []
            parser_blockers = []
        asr_policy = str(metadata.get("asr_policy") or "unspecified")
        return (
            parser_status,
            "vibedft.core.phonon.parse_freq_gp",
            (
                f"Parsed {asr_policy} phonon dispersion with "
                f"{dispersion.n_qpoints} q-points, min={dispersion.min_frequency_cm1:.6f} cm-1."
            ),
            parser_warnings,
            parser_blockers,
        )
    if smoke_parser == "md.stability":
        from vibedft.properties.aimd_analyzer import analyze_md_stability

        result = analyze_md_stability(sample_path)
        return (
            _status_value(result.status),
            result.parser_name,
            result.summary,
            list(result.warnings),
            list(result.blockers),
        )
    if smoke_parser == "electronic.bands_dos":
        return _run_electronic_bands_dos_smoke(metadata, sample_path, fixture_root)
    if smoke_parser == "phonon.dynmat_blocker":
        from vibedft.core.phonon import parse_dynmat_output

        dynmat = parse_dynmat_output(sample_path)
        if dynmat is None:
            return (
                ResultStatus.INSUFFICIENT_EVIDENCE.value,
                "vibedft.core.phonon.parse_dynmat_output",
                "Dynmat sample is missing or not parseable.",
                [],
                ["dynmat output could not be parsed"],
            )
        if dynmat.has_imaginary:
            minimum = min(dynmat.frequencies_cm1) if dynmat.frequencies_cm1 else None
            return (
                ResultStatus.BLOCKED.value,
                "vibedft.core.phonon.parse_dynmat_output",
                f"Gamma phonon instability blocks final Type-III verdict; min={minimum} cm-1.",
                [],
                ["Gamma phonon instability blocks final Type-III verdict"],
            )
        return (
            ResultStatus.PASS.value,
            "vibedft.core.phonon.parse_dynmat_output",
            "Dynmat sample has no imaginary Gamma modes.",
            [],
            [],
        )
    return (
        ResultStatus.INSUFFICIENT_EVIDENCE.value,
        "unknown",
        f"No smoke parser is registered for {smoke_parser or 'empty parser key'}.",
        [],
        [f"unknown smoke_parser: {smoke_parser or 'empty'}"],
    )


def _resolve_sample_path(sample_path: str, fixture_root: Path) -> Path:
    path = Path(sample_path)
    if path.is_absolute():
        return path
    return fixture_root / path


def _run_electronic_bands_dos_smoke(
    metadata: dict[str, object],
    sample_path: Path,
    fixture_root: Path,
) -> tuple[str, str, str, list[str], list[str]]:
    from vibedft.core.analysis import parse_bands_output, parse_dos_output

    bands_path = _resolve_optional_metadata_path(metadata.get("bands_sample_path"), fixture_root)
    dos_path = _resolve_optional_metadata_path(metadata.get("dos_sample_path"), fixture_root)
    if bands_path is None:
        bands_path = _first_matching_sample(sample_path, ("*.bands", "*bands*.dat", "bands.dat"))
    if dos_path is None:
        dos_path = _first_matching_sample(sample_path, ("*.dos", "*dos*.dat", "dos.dat"))

    blockers: list[str] = []
    warnings: list[str] = []

    if bands_path is None or not bands_path.is_file():
        blockers.append("bands data sample is required for electronic smoke")
    if dos_path is None or not dos_path.is_file():
        blockers.append("DOS data sample is required for electronic smoke")
    if blockers:
        return (
            ResultStatus.INSUFFICIENT_EVIDENCE.value,
            "vibedft.research.regression.electronic_bands_dos_smoke",
            "Electronic bands/DOS smoke lacks required sample files.",
            warnings,
            blockers,
        )

    bands = parse_bands_output(bands_path)
    dos = parse_dos_output(dos_path)
    if bands.n_bands <= 0 or bands.n_kpoints <= 0:
        blockers.append("bands parser produced no band/k-point data")
    if dos.n_points <= 0:
        blockers.append("DOS parser produced no data points")
    if dos.e_fermi_ev is None:
        warnings.append("DOS sample does not report EFermi")

    status = ResultStatus.PASS.value
    if blockers:
        status = ResultStatus.INSUFFICIENT_EVIDENCE.value
    elif warnings:
        status = ResultStatus.WARNING.value
    return (
        status,
        "vibedft.research.regression.electronic_bands_dos_smoke",
        (
            f"Parsed bands n_bands={bands.n_bands}, n_kpoints={bands.n_kpoints}; "
            f"DOS n_points={dos.n_points}, EF={dos.e_fermi_ev} eV."
        ),
        warnings,
        blockers,
    )


def _first_matching_sample(root: Path, patterns: tuple[str, ...]) -> Path | None:
    if root.is_file():
        return root
    if not root.is_dir():
        return None
    for pattern in patterns:
        matches = sorted(root.glob(pattern))
        if matches:
            return matches[0]
    return None


def _resolve_optional_metadata_path(value: object, fixture_root: Path) -> Path | None:
    if not isinstance(value, str) or not value:
        return None
    return _resolve_sample_path(value, fixture_root)


def _resolve_sample_mapping(value: object, fixture_root: Path) -> dict[str, Path]:
    if not isinstance(value, dict):
        return {}
    resolved: dict[str, Path] = {}
    for key, item in value.items():
        if isinstance(key, str) and isinstance(item, str) and item:
            resolved[key] = _resolve_sample_path(item, fixture_root)
    return resolved


def _metadata_int_lists(value: object) -> dict[str, list[int]]:
    if not isinstance(value, dict):
        return {}
    result: dict[str, list[int]] = {}
    for key, items in value.items():
        if not isinstance(key, str) or not isinstance(items, list):
            continue
        int_items: list[int] = []
        for item in items:
            try:
                int_items.append(int(item))
            except (TypeError, ValueError):
                continue
        result[key] = int_items
    return result


def _status_matches_expected(parser_status: str, expected_status: str) -> bool:
    if expected_status == "warning":
        return parser_status in {"warning", "pass"}
    return parser_status == expected_status


def _status_value(status: object) -> str:
    return status.value if isinstance(status, ResultStatus) else str(status)
