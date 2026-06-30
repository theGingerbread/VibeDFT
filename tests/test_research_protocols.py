from vibedft.research.models import ClaimType, Route
from vibedft.research.protocols import default_protocol_for_route


def test_static_doping_protocol_requires_literature_epc_chain():
    protocol = default_protocol_for_route(Route.STATIC_DOPING)

    assert ClaimType.STABILITY in protocol.required_claim_types
    assert ClaimType.EPC_MECHANISM in protocol.required_claim_types
    assert "pristine_vs_doped" in protocol.minimum_comparisons
    assert "carrier_density_series" in protocol.minimum_comparisons
    assert "k_q_smearing_series" in protocol.minimum_comparisons
    assert "soc_vs_no_soc_for_heavy_elements" in protocol.minimum_comparisons
    assert "alpha2F" in protocol.required_observables
    assert "cumulative_lambda" in protocol.required_observables
    assert "lambda_qnu" in protocol.required_observables
    assert "mu_star_sensitivity" in protocol.required_sensitivity_checks
    assert any("finite-q soft mode" in stop for stop in protocol.stop_conditions)


def test_type3_protocol_blocks_shortcut_band_alignment():
    protocol = default_protocol_for_route(Route.TYPE3_HETEROSTRUCTURE)

    assert ClaimType.BAND_ALIGNMENT in protocol.required_claim_types
    assert "same_lattice_isolated_refs" in protocol.minimum_comparisons
    assert "soc_layer_projected_bands" in protocol.required_observables
    assert any(
        "isolated layer work functions alone" in shortcut
        for shortcut in protocol.forbidden_shortcuts
    )


def test_intercalation_protocol_requires_site_and_charge_mechanism():
    protocol = default_protocol_for_route(Route.INTERCALATION)

    assert "site_series" in protocol.minimum_comparisons
    assert "formation_or_binding_energy" in protocol.required_observables
    assert "charge_transfer" in protocol.required_observables
    assert "mode_resolved_epc" in protocol.required_observables
    assert "cutoff" in protocol.required_sensitivity_checks
    assert "k_grid" in protocol.required_sensitivity_checks
    assert "q_grid" in protocol.required_sensitivity_checks
    assert "2d_electrostatics" in protocol.required_sensitivity_checks
    assert "mode_following_for_soft_modes" in protocol.required_sensitivity_checks


def test_type3_protocol_requires_machine_usable_sensitivity_checks():
    protocol = default_protocol_for_route(Route.TYPE3_HETEROSTRUCTURE)

    assert "planar_average_grid" in protocol.required_sensitivity_checks
    assert "vacuum_plateau" in protocol.required_sensitivity_checks
    assert "vdw_or_functional" in protocol.required_sensitivity_checks
    assert "interface_spacing" in protocol.required_sensitivity_checks
    assert (
        "gamma_phonon_at_stationary_structure"
        in protocol.required_sensitivity_checks
    )


def test_main_protocol_routes_and_ids_are_stable():
    expected = {
        Route.STATIC_DOPING: "protocol.static_doping.literature",
        Route.INTERCALATION: "protocol.intercalation.literature",
        Route.TYPE3_HETEROSTRUCTURE: "protocol.type3_heterostructure.literature",
    }

    for route, protocol_id in expected.items():
        protocol = default_protocol_for_route(route)

        assert protocol.route == route
        assert protocol.id == protocol_id
