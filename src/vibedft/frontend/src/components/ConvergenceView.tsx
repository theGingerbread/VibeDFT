import { useState } from 'react'
import Dropzone from './Dropzone'
import { convergenceAnalysis, ConvergenceResult } from '../api'

const CONF_COLOR: Record<string, string> = { high: 'var(--pass)', medium: 'var(--warn)', low: 'var(--fail)' };

export default function ConvergenceView() {
  const [result, setResult] = useState<ConvergenceResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const handleFiles = async (files: File[]) => {
    setLoading(true); setError('');
    try {
      const r = await convergenceAnalysis(files);
      setResult(r);
    } catch (e) {
      setError(String(e));
    }
    setLoading(false);
  };

  return (
    <div>
      <h2 style={{ fontSize: 16, marginBottom: 12 }}>Convergence Analysis</h2>
      <div style={{ fontSize: 11, color: 'var(--muted)', marginBottom: 8 }}>
        Upload case subdirectories (e.g. ph64/lambdax.out, ph96/lambdax.out).
        Use folder paths in filenames: "ph64/output/lambdax.out".
      </div>
      <Dropzone onFiles={handleFiles} />
      {loading && <div style={{ marginTop: 12, color: 'var(--muted)' }}>Analyzing convergence...</div>}
      {error && <div style={{ marginTop: 12, color: 'var(--fail)' }}>{error}</div>}

      {result && (
        <div style={{ marginTop: 16 }}>
          <div style={{ ...panel, marginBottom: 12 }}>
            <span style={{ fontSize: 13 }}>Cases: <strong>{result.n_cases}</strong></span>
            <span style={{
              display: 'inline-block', marginLeft: 12, padding: '2px 10px',
              borderRadius: 4, fontWeight: 600, fontSize: 12,
              color: '#000', background: CONF_COLOR[result.overall_confidence] || 'var(--muted)',
            }}>
              {result.overall_confidence.toUpperCase()}
            </span>
            {result.varying_params.length > 0 && (
              <span style={{ marginLeft: 12, fontSize: 11, color: 'var(--muted)' }}>
                Varying: {result.varying_params.join(', ')}
              </span>
            )}
          </div>

          {result.rows.length > 0 && (
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 11 }}>
              <thead>
                <tr>
                  <th style={th}>Case</th><th style={th}>k-grid</th><th style={th}>q-grid</th>
                  <th style={th}>λ</th><th style={th}>Tc (K)</th><th style={th}>ωlog</th><th style={th}>Conf</th>
                </tr>
              </thead>
              <tbody>
                {result.rows.map((r, i) => (
                  <tr key={i}>
                    <td style={td}>{r.case}</td>
                    <td style={td}>{r.k_grid}</td><td style={td}>{r.q_grid}</td>
                    <td style={td}>{r.lambda_max?.toFixed(3) || '—'}</td>
                    <td style={td}>{r.tc_max_K?.toFixed(1) || '—'}</td>
                    <td style={td}>{r.omega_log_K?.toFixed(0) || '—'}</td>
                    <td style={{ ...td, color: CONF_COLOR[r.confidence] || 'var(--muted)' }}>
                      {r.confidence.toUpperCase()}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}

          {result.warnings.length > 0 && (
            <div style={{ marginTop: 8 }}>
              {result.warnings.map((w, i) => (
                <div key={i} style={{ fontSize: 11, color: 'var(--warn)' }}>⚠ {w}</div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

const panel: React.CSSProperties = {
  background: 'var(--panel)', border: '1px solid var(--border)', borderRadius: 6, padding: 12,
};
const th: React.CSSProperties = {
  textAlign: 'left', padding: '4px 8px', fontSize: 10, color: 'var(--muted)',
  textTransform: 'uppercase', borderBottom: '1px solid var(--border)',
};
const td: React.CSSProperties = { padding: '4px 8px', borderBottom: '1px solid var(--border)' };
