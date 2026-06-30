import { useState } from 'react'
import Dropzone from './Dropzone'
import IssueTable from './IssueTable'
import PhysicsCards from './PhysicsCards'
import AgentPanel from './AgentPanel'
import { reviewCase, ReviewResult } from '../api'

export default function ReviewView() {
  const [result, setResult] = useState<ReviewResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [lastFiles, setLastFiles] = useState<File[]>([]);

  const handleFiles = async (files: File[]) => {
    setLastFiles(files);
    setLoading(true); setError('');
    try {
      const r = await reviewCase(files);
      setResult(r);
    } catch (e) {
      setError(String(e));
    }
    setLoading(false);
  };

  return (
    <div>
      <h2 style={{ fontSize: 16, marginBottom: 12 }}>Case Review</h2>
      <Dropzone onFiles={handleFiles} />
      {loading && <div style={{ marginTop: 12, color: 'var(--muted)' }}>Reviewing case...</div>}
      {error && <div style={{ marginTop: 12, color: 'var(--fail)' }}>{error}</div>}

      {result && (
        <div style={{ marginTop: 16 }}>
          <div style={{
            display: 'flex', gap: 12, marginBottom: 12, flexWrap: 'wrap',
            background: 'var(--panel)', border: '1px solid var(--border)',
            borderRadius: 6, padding: 12,
          }}>
            <div><span style={statLabel}>Files</span><span style={statVal}>{result.files_scanned}</span></div>
            <div><span style={statLabel}>Tasks</span><span style={statVal}>{result.tasks.length}</span></div>
            <div><span style={statLabel}>Errors</span><span style={{ ...statVal, color: result.n_errors ? 'var(--fail)' : 'var(--pass)' }}>{result.n_errors}</span></div>
            <div><span style={statLabel}>Warnings</span><span style={{ ...statVal, color: result.n_warnings ? 'var(--warn)' : 'var(--pass)' }}>{result.n_warnings}</span></div>
          </div>

          {result.best_workflow && (
            <div style={panel}>
              <h3 style={h3}>Workflow: {result.best_workflow.label}</h3>
              <div style={{ fontSize: 12, color: 'var(--muted)', marginBottom: 6 }}>{result.summary}</div>
              <div style={{ fontSize: 12 }}>Next: {result.next_step}</div>
            </div>
          )}

          <div style={panel}>
            <h3 style={h3}>Physics Insights</h3>
            <PhysicsCards physics={result.physics} />
          </div>

          <div style={panel}>
            <h3 style={h3}>All Issues</h3>
            <IssueTable issues={result.validation_issues} />
          </div>

          <div style={panel}>
            <h3 style={h3}>🤖 AI Assistant</h3>
            <AgentPanel files={lastFiles} />
          </div>
        </div>
      )}
    </div>
  )
}

const statLabel: React.CSSProperties = { fontSize: 10, color: 'var(--muted)', textTransform: 'uppercase', display: 'block' };
const statVal: React.CSSProperties = { fontSize: 18, fontWeight: 600 };
const panel: React.CSSProperties = {
  background: 'var(--panel)', border: '1px solid var(--border)',
  borderRadius: 6, padding: 12, marginBottom: 12,
};
const h3: React.CSSProperties = { fontSize: 12, color: 'var(--muted)', marginBottom: 6, textTransform: 'uppercase' };
