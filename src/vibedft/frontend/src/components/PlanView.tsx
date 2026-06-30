import { useState } from 'react'
import { planWorkflow, PlanResult, artifactUrl } from '../api'

export default function PlanView() {
  const [prefix, setPrefix] = useState('material');
  const [ecutwfc, setEcutwfc] = useState(60);
  const [ecutrho, setEcutrho] = useState(480);
  const [totCharge, setTotCharge] = useState(0.0);
  const [profile, setProfile] = useState('cluster_debug');
  const [result, setResult] = useState<PlanResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const handlePlan = async () => {
    setLoading(true); setError('');
    try {
      const r = await planWorkflow({ prefix, ecutwfc, ecutrho, tot_charge: totCharge, profile });
      setResult(r);
    } catch (e) {
      setError(String(e));
    }
    setLoading(false);
  };

  return (
    <div>
      <h2 style={{ fontSize: 16, marginBottom: 12 }}>Plan Superconductivity Workflow</h2>

      <div style={formGrid}>
        <div>
          <label style={lbl}>Prefix</label>
          <input style={inp} value={prefix} onChange={e => setPrefix(e.target.value)} />
        </div>
        <div>
          <label style={lbl}>ecutwfc (Ry)</label>
          <input style={inp} type="number" value={ecutwfc} onChange={e => setEcutwfc(Number(e.target.value))} />
        </div>
        <div>
          <label style={lbl}>ecutrho (Ry)</label>
          <input style={inp} type="number" value={ecutrho} onChange={e => setEcutrho(Number(e.target.value))} />
        </div>
        <div>
          <label style={lbl}>tot_charge (doping)</label>
          <input style={inp} type="number" step="0.01" value={totCharge} onChange={e => setTotCharge(Number(e.target.value))} />
        </div>
        <div>
          <label style={lbl}>Profile</label>
          <select style={inp} value={profile} onChange={e => setProfile(e.target.value)}>
            <option value="cluster_debug">cluster_debug (7-56 cores)</option>
            <option value="cluster_prod">cluster_prod (28-224 cores)</option>
          </select>
        </div>
      </div>

      <button style={btn} onClick={handlePlan} disabled={loading}>
        {loading ? '⏳ Planning...' : '🚀 Generate Workflow'}
      </button>
      {error && <div style={{ marginTop: 8, color: 'var(--fail)', fontSize: 12 }}>{error}</div>}

      {result && (
        <div style={{ marginTop: 16 }}>
          <div style={panel}>
            <div style={{ fontSize: 13, marginBottom: 8 }}>
              ✅ Plan <strong>{result.plan_id}</strong> — {result.n_stages} stages
            </div>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 11, marginBottom: 12 }}>
              <thead>
                <tr>
                  <th style={th}>Stage</th><th style={th}>Kind</th><th style={th}>Dir</th>
                  <th style={th}>Cores</th><th style={th}>Walltime</th>
                </tr>
              </thead>
              <tbody>
                {result.stages.slice(0, 16).map((s, i) => (
                  <tr key={i}>
                    <td style={td}>{s.id}</td><td style={td}>{s.kind}</td>
                    <td style={{ ...td, fontFamily: 'monospace', fontSize: 10 }}>{s.directory}</td>
                    <td style={td}>{s.cores}</td><td style={td}>{s.walltime}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {result.artifact_id && (
              <a href={artifactUrl(result.artifact_id)} download style={{ ...btn, textDecoration: 'none', display: 'inline-block' }}>
                ⬇ Download workflow zip
              </a>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

const formGrid: React.CSSProperties = {
  display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginBottom: 16,
};
const lbl: React.CSSProperties = { display: 'block', fontSize: 11, color: 'var(--muted)', marginBottom: 4 };
const inp: React.CSSProperties = {
  width: '100%', padding: '6px 10px', background: 'var(--bg)', color: 'var(--text)',
  border: '1px solid var(--border)', borderRadius: 4, fontSize: 13,
};
const panel: React.CSSProperties = {
  background: 'var(--panel)', border: '1px solid var(--border)', borderRadius: 6, padding: 12,
};
const btn: React.CSSProperties = {
  background: 'var(--accent)', color: '#000', border: 'none',
  borderRadius: 4, padding: '8px 16px', fontSize: 13,
  fontWeight: 600, cursor: 'pointer',
};
const th: React.CSSProperties = {
  textAlign: 'left', padding: '3px 6px', fontSize: 10, color: 'var(--muted)',
  textTransform: 'uppercase', borderBottom: '1px solid var(--border)',
};
const td: React.CSSProperties = { padding: '3px 6px', borderBottom: '1px solid var(--border)' };
