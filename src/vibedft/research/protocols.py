"""Literature-derived research protocols for common VibeDFT routes."""

from __future__ import annotations

from vibedft.research.models import ClaimType, LiteratureProtocol, Route


def default_protocol_for_route(route: Route) -> LiteratureProtocol:
    """Return the default literature protocol for a scientific route."""

    if route == Route.STATIC_DOPING:
        return LiteratureProtocol(
            id="protocol.static_doping.literature",
            route=Route.STATIC_DOPING,
            research_focus=(
                "Static carrier doping superconductivity claims must connect "
                "dynamical stability, electronic origin, EPC mechanism, and "
                "Tc robustness under a consistent 2D protocol."
            ),
            required_claim_types=[
                ClaimType.STABILITY,
                ClaimType.ELECTRONIC_ORIGIN,
                ClaimType.EPC_MECHANISM,
                ClaimType.TC_ROBUSTNESS,
            ],
            minimum_comparisons=[
                "pristine_vs_doped",
                "carrier_density_series",
                "k_q_smearing_series",
                "soc_vs_no_soc_for_heavy_elements",
            ],
            required_observables=[
                "signed_phonon_frequencies",
                "alpha2F",
                "cumulative_lambda",
                "lambda_qnu",
                "projected_phonon_dos",
                "orbital_pdos",
            ],
            required_sensitivity_checks=[
                "q_grid",
                "electronic_grid",
                "smearing",
                "mu_star_sensitivity",
                "soc",
                "2d_electrostatics",
            ],
            stop_conditions=[
                "finite-q soft mode before EPC",
                "NaN omega_log or Tc",
                "missing upstream relax provenance",
            ],
            forbidden_shortcuts=[
                (
                    "ranking Tc from legacy data without 2D cutoff/SOC/q "
                    "convergence"
                ),
                "treating ph64/ph96 as q-grid convergence",
            ],
            llm_notes=[
                (
                    "Do not collapse a finished EPC run into a paper-grade Tc "
                    "claim without the route-level stability and sensitivity chain."
                )
            ],
        )

    if route == Route.INTERCALATION:
        return LiteratureProtocol(
            id="protocol.intercalation.literature",
            route=Route.INTERCALATION,
            research_focus=(
                "Intercalation claims must compare adsorption sites and "
                "concentrations while preserving charge-transfer and EPC "
                "mechanism provenance."
            ),
            required_claim_types=[
                ClaimType.STABILITY,
                ClaimType.CHARGE_TRANSFER,
                ClaimType.ELECTRONIC_ORIGIN,
                ClaimType.EPC_MECHANISM,
                ClaimType.NEGATIVE_RESULT,
            ],
            minimum_comparisons=[
                "site_series",
                "concentration_series",
                "pristine_baseline",
                "same_protocol_li_na_k",
            ],
            required_observables=[
                "formation_or_binding_energy",
                "charge_transfer",
                "planar_potential",
                "orbital_pdos",
                "signed_phonon_frequencies",
                "mode_resolved_epc",
            ],
            required_sensitivity_checks=[
                "cutoff",
                "k_grid",
                "q_grid",
                "2d_electrostatics",
                "mode_following_for_soft_modes",
                "site_relaxation_protocol",
                "concentration_cell_size",
                "charge_partition_method",
            ],
            stop_conditions=[
                "finite-q soft mode before Tc",
                "missing pristine or same-protocol alkali baseline",
            ],
            forbidden_shortcuts=[
                "mixing different-owner Li references in one quantitative comparison",
                "reporting Tc when a finite-q soft mode remains unresolved",
            ],
            llm_notes=[
                (
                    "Negative intercalation results are valid outputs when site, "
                    "charge, and phonon evidence are comparable."
                )
            ],
        )

    if route == Route.TYPE3_HETEROSTRUCTURE:
        return LiteratureProtocol(
            id="protocol.type3_heterostructure.literature",
            route=Route.TYPE3_HETEROSTRUCTURE,
            research_focus=(
                "Type-III heterostructure claims require same-lattice isolated "
                "references, electrostatic alignment checks, SOC-resolved bands, "
                "and independent stability evidence."
            ),
            required_claim_types=[
                ClaimType.BAND_ALIGNMENT,
                ClaimType.CHARGE_TRANSFER,
                ClaimType.STABILITY,
            ],
            minimum_comparisons=[
                "same_lattice_isolated_refs",
                "stacking_series",
                "soc_vs_no_soc",
                "top_bottom_vacuum_plateau",
            ],
            required_observables=[
                "macro_potential",
                "work_function",
                "interface_dipole",
                "bader_charge",
                "soc_layer_projected_bands",
                "binding_energy",
            ],
            required_sensitivity_checks=[
                "planar_average_grid",
                "vacuum_plateau",
                "vdw_or_functional",
                "interface_spacing",
                "gamma_phonon_at_stationary_structure",
                "vacuum_thickness",
                "dipole_correction",
                "stacking_registry",
                "soc",
            ],
            stop_conditions=[
                "invalid planar average",
                "non-stationary phonon",
                "missing same-lattice refs",
                "invalid deltaV",
            ],
            forbidden_shortcuts=[
                "using isolated layer work functions alone for band alignment",
                "using invalid deltaV from a non-plateau planar average",
            ],
            llm_notes=[
                (
                    "Band alignment is blocked when electrostatic plateaus or "
                    "same-lattice isolated references are absent."
                )
            ],
        )

    return LiteratureProtocol(
        id="protocol.other.basic",
        route=Route.OTHER,
        research_focus=(
            "Basic stability-first protocol for routes without a dedicated "
            "literature-derived policy."
        ),
        required_claim_types=[ClaimType.STABILITY],
        minimum_comparisons=[],
        required_observables=["signed_phonon_frequencies"],
        required_sensitivity_checks=[],
        stop_conditions=["route-specific protocol missing for paper-grade claims"],
        forbidden_shortcuts=[
            "making paper-grade claims without a route-specific literature protocol"
        ],
        llm_notes=[
            (
                "Warning: do not make paper-grade claims until a route-specific "
                "protocol is defined."
            )
        ],
    )
