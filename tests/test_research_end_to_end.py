from pathlib import Path

from vibedft.research.gates import evaluate_claim
from vibedft.research.models import GateVerdict, Route
from vibedft.research.report import render_claim_report
from vibedft.research.scanner import scan_case
from vibedft.research.templates import build_route_claims


def test_na_finite_q_soft_mode_template_claim_blocks_tc_reporting():
    artifacts = scan_case(Path("tests/fixtures/research/na_finite_q_soft_mode"))
    claims = build_route_claims(Route.INTERCALATION, "Na_2-HfCl2")
    epc_claim = next(claim for claim in claims if claim.id == "claim.na_2_hfcl2.epc")

    decision = evaluate_claim(epc_claim, artifacts)
    report = render_claim_report([decision], title="Na_2-HfCl2 route claim report")

    assert "claim.na_2_hfcl2.epc" in report
    assert decision.verdict == GateVerdict.BLOCKED
    assert "- Verdict: `blocked`" in report
    assert "Do not report Tc" in report
