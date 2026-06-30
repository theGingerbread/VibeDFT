from vibedft.research.models import ClaimType, Route
from vibedft.research.templates import build_route_claims


def test_intercalation_template_builds_negative_and_epc_claims_for_material():
    claims = build_route_claims(Route.INTERCALATION, "Na_2-HfCl2", question_id="rq.na2")

    claim_types = {claim.claim_type for claim in claims}

    assert ClaimType.NEGATIVE_RESULT in claim_types
    assert ClaimType.EPC_MECHANISM in claim_types
    assert all("Na_2-HfCl2" in claim.statement for claim in claims)


def test_type3_template_builds_soc_band_alignment_claim():
    claims = build_route_claims(Route.TYPE3_HETEROSTRUCTURE, "HfBr2/TiSe2")

    assert [claim.claim_type for claim in claims] == [ClaimType.BAND_ALIGNMENT]
    assert "SOC" in claims[0].statement
