"""Tests for HfCl2 recipe definitions and evidence stubs."""

from vibedft.generators.hfcl2_recipes import (
    hfcl2_k_fatband_v1,
    hfcl2_k_smearing_sensitivity_v1,
    hfcl2_pristine_rrkjus_reference_v1,
)


class TestRecipes:
    def test_k_fatband_recipe(self):
        recipe = hfcl2_k_fatband_v1()
        assert recipe.recipe_id == "qe.hfcl2_k_fatband.v1"
        assert len(recipe.stages) == 1
        assert recipe.stages[0].program == "projwfc.x"
        assert recipe.stages[0].input_pattern == "projwfc_fatband.in"
        assert "hfcl2.p2.fatband.location" in recipe.validation_rules
        assert "hfcl2.p2.fatband.kresolveddos" in recipe.validation_rules

    def test_k_smearing_sensitivity_recipe(self):
        recipe = hfcl2_k_smearing_sensitivity_v1()
        assert recipe.recipe_id == "qe.hfcl2_k_smearing_sensitivity.v1"
        assert len(recipe.stages) == 2
        assert all(s.program == "pw.x" for s in recipe.stages)
        assert recipe.stages[0].input_pattern == "nscf_degauss_002.in"
        assert recipe.stages[1].input_pattern == "nscf_degauss_005.in"
        assert len(recipe.expected_inputs) == 3
        assert "hfcl2.p3.smearing.degauss_values" in recipe.validation_rules

    def test_pristine_rrkjus_reference_recipe(self):
        recipe = hfcl2_pristine_rrkjus_reference_v1()
        assert recipe.recipe_id == "qe.hfcl2_pristine_rrkjus_reference.v1"
        assert len(recipe.stages) == 1
        assert recipe.stages[0].program == "pw.x"
        assert "hfcl2.b1.pristine.elements" in recipe.validation_rules
        assert "hfcl2.b1.pristine.ecut" in recipe.validation_rules
        assert "hfcl2.b1.pristine.cell" in recipe.validation_rules
        assert "c ≥ 30 Å vacuum" in recipe.acceptance_criteria
        assert "ecutwfc=90, ecutrho=720" in recipe.acceptance_criteria

    def test_all_recipes_have_unique_ids(self):
        recipes = [
            hfcl2_k_fatband_v1(),
            hfcl2_k_smearing_sensitivity_v1(),
            hfcl2_pristine_rrkjus_reference_v1(),
        ]
        ids = [r.recipe_id for r in recipes]
        assert len(ids) == len(set(ids)), "Recipe IDs must be unique"


class TestEvidenceStubs:
    from vibedft.agent.hfcl2_evidence import (
        FatbandInputEvidence,
        FatbandOutputEvidence,
        SmearingInputEvidence,
        SmearingOutputEvidence,
        PristineInputEvidence,
        PristineOutputEvidence,
    )

    def test_fatband_input_evidence(self):
        ev = self.FatbandInputEvidence(case="HfCl2-K-screening/K_1")
        assert ev.case == "HfCl2-K-screening/K_1"
        assert ev.stage == "P2_fatband"
        assert ev.status == "pending"
        assert "kresolveddos" in ev.inputs
        assert "prefix" in ev.inputs

    def test_fatband_output_evidence(self):
        ev = self.FatbandOutputEvidence(case="HfCl2-K-screening/K_1")
        assert ev.status == "pending"
        assert "hf_d_at_ef_pct" in ev.outputs
        assert "k_4s_at_ef_pct" in ev.outputs
        assert "cl_3p_at_ef_pct" in ev.outputs

    def test_smearing_input_evidence(self):
        ev = self.SmearingInputEvidence(case="HfCl2-K-screening/K_1")
        assert ev.stage == "P3_smearing"
        assert "degauss_ry" in ev.inputs
        assert "kmesh" in ev.inputs

    def test_smearing_output_evidence(self):
        ev = self.SmearingOutputEvidence(case="HfCl2-K-screening/K_1")
        assert "variants" in ev.outputs
        assert "verdict" in ev.outputs

    def test_pristine_input_evidence(self):
        ev = self.PristineInputEvidence(case="HfCl2-pristine")
        assert ev.stage == "B1_pristine_rrkjus"
        assert "pseudo_family" in ev.inputs
        assert "ecutwfc_ry" in ev.inputs
        assert "c_ang" in ev.inputs

    def test_pristine_output_evidence(self):
        ev = self.PristineOutputEvidence(case="HfCl2-pristine")
        assert "final_energy_ry" in ev.outputs
        assert "relax_converged" in ev.outputs
