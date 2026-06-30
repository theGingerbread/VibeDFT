import { useState } from 'react'
import Dropzone from './Dropzone'
import IssueTable from './IssueTable'
import { inspectFiles, InspectResult } from '../api'

export default function InspectView() {
  const [result, setResult] = useState<InspectResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const handleFiles = async (files: File[]) => {
    setLoading(true); setError('');
    try {
      const r = await inspectFiles(files);
      setResult(r);
    } catch (e) {
      setError(String(e));
    }
    setLoading(false);
  };

  return (
    <div>
      <h2 style={{ fontSize: 16, marginBottom: 12 }}>Inspect QE Files</h2>
      <Dropzone onFiles={handleFiles} />
      {loading && <div style={{ marginTop: 12, color: 'var(--muted)' }}>Analyzing...</div>}
      {error && <div style={{ marginTop: 12, color: 'var(--fail)' }}>{error}</div>}

      {result && (
        <div style={{ marginTop: 16 }}>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginBottom: 16 }}>
            <div style={panel}>
              <h3 style={h3}>Files ({result.files.length})</h3>
              {result.files.map((f, i) => (
                <div key={i} style={{ fontSize: 11, padding: '3px 0', borderBottom: '1px solid var(--border)' }}>
                  <span style={{ color: 'var(--muted)' }}>{f.parse_status === 'ok' ? '✅' : '❌'}</span>
                  {' '}{f.path?.split('/').pop()}
                  <span style={{ color: 'var(--muted)', marginLeft: 8 }}>{f.program} · {f.summary}</span>
                </div>
              ))}
            </div>
            <div style={panel}>
              <h3 style={h3}>Tasks ({result.tasks.length})</h3>
              {result.tasks.map((t, i) => (
                <div key={i} style={{ fontSize: 11, padding: '3px 0', borderBottom: '1px solid var(--border)' }}>
                  {t.program} → <strong>{t.task_type}</strong>
                  <span style={{ color: 'var(--muted)', marginLeft: 8 }}>{t.confidence}</span>
                </div>
              ))}
            </div>
          </div>
          <div style={panel}>
            <h3 style={h3}>Issues</h3>
            <IssueTable issues={result.issues} />
          </div>
        </div>
      )}
    </div>
  )
}

const panel: React.CSSProperties = {
  background: 'var(--panel)', border: '1px solid var(--border)',
  borderRadius: 6, padding: 12,
};
const h3: React.CSSProperties = { fontSize: 12, color: 'var(--muted)', marginBottom: 6, textTransform: 'uppercase' };
