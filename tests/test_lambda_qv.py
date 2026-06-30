import math
import tempfile
from pathlib import Path
import pytest
from vibedft.postprocess.lambda_qv import (
    LambdaQvResult,
    compute_lambda_qv,
    write_lambda_qv,
    write_lambda_qv_gp,
    _read_numbers,
)

FREQ_GP = "0.0000   0.001   0.001   56.40\n0.5773   0.002  82.56   56.40\n1.0000  17.57   82.56   56.40\n"
GAMMA   = "0.0000 0.0000 0.0000   1.0   2.0   3.0\n0.5773 0.0000 0.0000   4.0   5.0   6.0\n1.0000 0.0000 0.0000   7.0   8.0   9.0\n"


def _write_tmp(content, suffix=".txt"):
    p = Path(tempfile.mktemp(suffix=suffix))
    p.write_text(content)
    return p


class TestComputeLambdaQv:

    def test_basic(self):
        fp = _write_tmp(FREQ_GP, ".freq.gp")
        gf = _write_tmp(GAMMA)
        try:
            r = compute_lambda_qv(fp, gf, n_ef=10.0)
            assert r.n_qpoints == 3
            assert r.n_modes == 3
            assert r.lambda_qv[0][0] == 0.0  # ω≈0 → λ=0
            expected = 5.0 / (math.pi * 10.0 * 82.56 ** 2)
            assert r.lambda_qv[1][1] == pytest.approx(expected, rel=1e-6)
        finally:
            fp.unlink(missing_ok=True)
            gf.unlink(missing_ok=True)

    def test_neg_freq(self):
        freq = "0.0  10.0\n1.0  20.0\n"
        gamma = "0 0 0  0.5\n1 0 0  0.5\n"
        fp = _write_tmp(freq, ".freq.gp")
        gf = _write_tmp(gamma)
        try:
            r = compute_lambda_qv(fp, gf, n_ef=1.0)
            w = 10.0
            expected = 0.5 / (math.pi * 1.0 * w * w)
            assert r.lambda_qv[0][0] == pytest.approx(expected, rel=1e-6)
        finally:
            fp.unlink(missing_ok=True)
            gf.unlink(missing_ok=True)


class TestReadNumbers:
    def test_skip_comments(self):
        p = _write_tmp("# c\n1.0 2.0\n# c\n3.0 4.0\n")
        rows = _read_numbers(p)
        assert len(rows) == 2
        p.unlink(missing_ok=True)


class TestWriteOutputs:
    def test_write_lambda_qv(self):
        r = LambdaQvResult(n_qpoints=2, n_modes=2, n_ef=10.0,
                           lambda_qv=[[0.1, 0.2], [0.3, 0.4]])
        out = Path(tempfile.mktemp())
        write_lambda_qv(r, out)
        assert "n_ef = 10.0" in out.read_text()
        out.unlink(missing_ok=True)

    def test_write_gp(self):
        r = LambdaQvResult(n_qpoints=2, n_modes=2, n_ef=1.0,
                           lambda_qv=[[0.1, 0.2], [0.3, 0.4]],
                           omega_cm1=[[10.0, 20.0], [30.0, 40.0]])
        fp = _write_tmp("0.0\n1.0\n")
        out = Path(tempfile.mktemp())
        write_lambda_qv_gp(r, fp, out)
        data = [l for l in out.read_text().splitlines() if not l.startswith("#") and l.strip()]
        assert len(data) >= 4
        fp.unlink(missing_ok=True)
        out.unlink(missing_ok=True)
