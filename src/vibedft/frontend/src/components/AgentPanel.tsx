import { useState } from 'react'

interface Props {
  files: File[];
  disabled?: boolean;
}

export default function AgentPanel({ files, disabled }: Props) {
  const [explain, setExplain] = useState('');
  const [fixes, setFixes] = useState<{issue_id: string; fix: string; severity: string}[]>([]);
  const [steps, setSteps] = useState<string[]>([]);
  const [loading, setLoading] = useState('');
  const [error, setError] = useState('');

  const callAgent = async (endpoint: string, setter: (d: any) => void) => {
    if (!files.length) { setError('Upload files first'); return; }
    setLoading(endpoint); setError('');
    try {
      const fd = new FormData();
      files.forEach(f => fd.append('files', f));
      const r = await fetch(`/api/agent/${endpoint}`, { method: 'POST', body: fd });
      const data = await r.json();
      setter(data);
    } catch (e) {
      setError(String(e));
    }
    setLoading('');
  };

  return (
    <div>
      <div style={{ display: 'flex', gap: 8, marginBottom: 12, flexWrap: 'wrap' }}>
        <button style={btn} disabled={!!loading || disabled}
          onClick={() => callAgent('explain-review', d => setExplain(d.explanation || ''))}>
          {loading === 'explain-review' ? '⏳' : '🔍'} Explain
        </button>
        <button style={btn} disabled={!!loading || disabled}
          onClick={() => callAgent('suggest-fixes', d => setFixes(d.suggestions || []))}>
          {loading === 'suggest-fixes' ? '⏳' : '🔧'} Fixes
        </button>
        <button style={btn} disabled={!!loading || disabled}
          onClick={() => callAgent('next-steps', d => setSteps(d.steps || []))}>
          {loading === 'next-steps' ? '⏳' : '📋'} Next Steps
        </button>
      </div>

      {error && <div style={{ color: 'var(--fail)', fontSize: 12, marginBottom: 8 }}>{error}</div>}

      {explain && (
        <div style={panel}>
          <h3 style={h3}>Explanation</h3>
          <div style={{ fontSize: 13, lineHeight: 1.6, whiteSpace: 'pre-wrap' }}>{explain}</div>
        </div>
      )}

      {fixes.length > 0 && (
        <div style={panel}>
          <h3 style={h3}>Suggested Fixes ({fixes.length})</h3>
          {fixes.map((f, i) => (
            <div key={i} style={{
              padding: '6px 10px', margin: '4px 0',
              borderLeft: `3px solid ${f.severity === 'error' ? 'var(--fail)' : 'var(--warn)'}`,
              background: 'rgba(255,255,255,.01)', borderRadius: '0 4px 4px 0',
            }}>
              <div style={{ fontSize: 10, color: 'var(--muted)' }}>[{f.issue_id}]</div>
              <div style={{ fontSize: 12 }}>{f.fix}</div>
            </div>
          ))}
        </div>
      )}

      {steps.length > 0 && (
        <div style={panel}>
          <h3 style={h3}>Recommended Next Steps</h3>
          {steps.map((s, i) => (
            <div key={i} style={{ fontSize: 12, padding: '4px 0', borderBottom: '1px solid var(--border)' }}>
              {i + 1}. {s}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

const panel: React.CSSProperties = {
  background: 'var(--panel)', border: '1px solid var(--border)',
  borderRadius: 6, padding: 12, marginBottom: 12,
};
const h3: React.CSSProperties = { fontSize: 12, color: 'var(--muted)', marginBottom: 6, textTransform: 'uppercase' };
const btn: React.CSSProperties = {
  background: 'var(--accent)', color: '#000', border: 'none',
  borderRadius: 4, padding: '8px 14px', fontSize: 13,
  fontWeight: 600, cursor: 'pointer',
};
