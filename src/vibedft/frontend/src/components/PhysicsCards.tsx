import type { PhysicsReport } from '../api'

interface Props { physics: PhysicsReport | null }

const SCORE_COLOR = (v: number) => v >= 7 ? 'var(--pass)' : v >= 4 ? 'var(--warn)' : 'var(--fail)';
const REC_LABEL: Record<string, string> = {
  continue: '✅ Continue', convergence_test: '⚠ Convergence Test',
  needs_review: '🔍 Needs Review', abandon: '❌ Abandon',
};

export default function PhysicsCards({ physics }: Props) {
  if (!physics) return <div style={{ color: 'var(--muted)', fontSize: 12 }}>No physics analysis available.</div>;

  const { scores } = physics;
  const cards = [
    ['Stability', scores.stability, 'Phonon stability'],
    ['Electronic', scores.electronic, 'DOS, gap, orbitals'],
    ['Superconductivity', scores.superconductivity, 'λ, Tc, α²F'],
    ['Confidence', scores.workflow_confidence, 'Convergence quality'],
  ];

  return (
    <div>
      <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', marginBottom: 12 }}>
        {cards.map(([label, val, desc]) => (
          <div key={label} style={{
            textAlign: 'center', padding: '10px 16px',
            border: '1px solid var(--border)', borderRadius: 6,
            background: 'rgba(255,255,255,.01)',
          }}>
            <div style={{ fontSize: 24, fontWeight: 700, color: SCORE_COLOR(val as number) }}>
              {(val as number).toFixed(1)}
            </div>
            <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 2 }}>{label}</div>
            <div style={{ fontSize: 9, color: 'var(--muted)' }}>{desc}</div>
          </div>
        ))}
      </div>

      <div style={{
        padding: '8px 12px', borderLeft: `3px solid ${REC_LABEL[physics.recommendation] ? 'var(--warn)' : 'var(--pass)'}`,
        background: 'rgba(255,255,255,.02)', borderRadius: '0 4px 4px 0', marginBottom: 12,
      }}>
        <strong style={{ fontSize: 13 }}>{REC_LABEL[physics.recommendation] || physics.recommendation}</strong>
        <span style={{ fontSize: 12, color: 'var(--muted)', marginLeft: 8 }}>{physics.overall_verdict}</span>
      </div>

      {physics.insights?.length > 0 && (
        <div>
          {physics.insights.slice(0, 20).map((ins, i) => (
            <div key={i} style={{
              padding: '6px 10px', margin: '4px 0',
              borderLeft: `3px solid ${ins.level === 'positive' ? 'var(--pass)' : ins.level === 'negative' ? 'var(--fail)' : ins.level === 'warning' ? 'var(--warn)' : 'var(--muted)'}`,
              background: 'rgba(255,255,255,.01)',
              borderRadius: '0 4px 4px 0',
            }}>
              <div style={{ fontSize: 12 }}>{ins.message}</div>
              {ins.detail && <div style={{ fontSize: 10, color: 'var(--muted)', marginTop: 2 }}>{ins.detail}</div>}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
