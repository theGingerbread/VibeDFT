import { useState } from 'react'
import Dropzone from './Dropzone'
import { generateReport, artifactUrl } from '../api'

export default function ReportView() {
  const [artifactId, setArtifactId] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [preview, setPreview] = useState(false);

  const handleFiles = async (files: File[]) => {
    setLoading(true); setError('');
    try {
      const r = await generateReport(files);
      setArtifactId(r.artifact_id);
      setPreview(false);
    } catch (e) {
      setError(String(e));
    }
    setLoading(false);
  };

  const htmlUrl = artifactId ? artifactUrl(`${artifactId}.html`) : '';

  return (
    <div>
      <h2 style={{ fontSize: 16, marginBottom: 12 }}>Generate Report</h2>
      <Dropzone onFiles={handleFiles} />
      {loading && <div style={{ marginTop: 12, color: 'var(--muted)' }}>Generating report...</div>}
      {error && <div style={{ marginTop: 12, color: 'var(--fail)' }}>{error}</div>}

      {artifactId && (
        <div style={{ marginTop: 16 }}>
          <div style={{
            background: 'var(--panel)', border: '1px solid var(--border)',
            borderRadius: 6, padding: 12,
          }}>
            <div style={{ fontSize: 13, marginBottom: 8 }}>
              ✅ Report ready — <code style={{ color: 'var(--accent)' }}>{artifactId}.html</code>
            </div>
            <div style={{ display: 'flex', gap: 8 }}>
              <button style={btn} onClick={() => window.open(htmlUrl, '_blank')}>
                🔗 Open in new tab
              </button>
              <button style={btn} onClick={() => setPreview(!preview)}>
                {preview ? '🙈 Hide preview' : '👁 Preview inline'}
              </button>
              <a href={htmlUrl} download style={{ ...btn, textDecoration: 'none' }}>
                ⬇ Download
              </a>
            </div>
          </div>

          {preview && (
            <div style={{ marginTop: 12, border: '1px solid var(--border)', borderRadius: 6, overflow: 'hidden' }}>
              <iframe src={htmlUrl} style={{ width: '100%', height: 600, border: 0 }} />
            </div>
          )}
        </div>
      )}
    </div>
  )
}

const btn: React.CSSProperties = {
  background: 'var(--accent)', color: '#000', border: 'none',
  borderRadius: 4, padding: '6px 12px', fontSize: 12,
  fontWeight: 600, cursor: 'pointer', display: 'inline-block',
};
