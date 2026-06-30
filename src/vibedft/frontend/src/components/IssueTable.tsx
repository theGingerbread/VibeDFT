import type { Issue } from '../api'

interface Props { issues: Issue[]; max?: number }

const SEV_COLOR: Record<string, string> = {
  error: 'var(--fail)', warning: 'var(--warn)', info: 'var(--muted)',
};

export default function IssueTable({ issues, max = 50 }: Props) {
  if (!issues.length) return <div style={{ color: 'var(--pass)', fontSize: 12 }}>✅ No issues found.</div>;

  const shown = issues.slice(0, max);
  const errors = shown.filter(i => i.severity === 'error').length;
  const warnings = shown.filter(i => i.severity === 'warning').length;

  return (
    <div>
      <div style={{ fontSize: 11, marginBottom: 8, color: 'var(--muted)' }}>
        {errors > 0 && <span style={{ color: 'var(--fail)', marginRight: 10 }}>❌ {errors} errors</span>}
        {warnings > 0 && <span style={{ color: 'var(--warn)', marginRight: 10 }}>⚠️ {warnings} warnings</span>}
      </div>
      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 11 }}>
        <thead>
          <tr>
            <th style={th}>Sev</th><th style={th}>Check</th>
            <th style={th}>Message</th><th style={th}>Source</th>
          </tr>
        </thead>
        <tbody>
          {shown.map((iss, i) => (
            <tr key={i}>
              <td style={{ ...td, color: SEV_COLOR[iss.severity] || 'var(--muted)', fontWeight: 600 }}>
                {iss.severity.toUpperCase()}
              </td>
              <td style={{ ...td, fontFamily: 'monospace', fontSize: 10 }}>{iss.id}</td>
              <td style={td}>{iss.message}</td>
              <td style={{ ...td, fontSize: 9, color: 'var(--muted)', maxWidth: 200, overflow: 'hidden', textOverflow: 'ellipsis' }}>
                {iss.source_file?.split('/').pop() || ''}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {issues.length > max && (
        <div style={{ fontSize: 10, color: 'var(--muted)', marginTop: 4 }}>
          ... and {issues.length - max} more
        </div>
      )}
    </div>
  )
}

const th: React.CSSProperties = {
  textAlign: 'left', padding: '4px 8px',
  color: 'var(--muted)', fontWeight: 600, fontSize: 10,
  textTransform: 'uppercase', borderBottom: '1px solid var(--border)',
};
const td: React.CSSProperties = {
  padding: '4px 8px', borderBottom: '1px solid var(--border)',
};
