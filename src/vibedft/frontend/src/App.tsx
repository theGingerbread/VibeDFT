import { useState } from 'react'
import InspectView from './components/InspectView'
import ReviewView from './components/ReviewView'
import ReportView from './components/ReportView'
import ConvergenceView from './components/ConvergenceView'
import PlanView from './components/PlanView'

const TABS = [
  { id: 'inspect', label: '1. Inspect', desc: 'Parse .in/.out files' },
  { id: 'review', label: '2. Review', desc: 'Full case audit + physics' },
  { id: 'report', label: '3. Report', desc: 'HTML report' },
  { id: 'convergence', label: '4. Convergence', desc: 'Batch analysis' },
  { id: 'plan', label: '5. Plan', desc: 'Generate workflow' },
] as const;

type TabId = typeof TABS[number]['id'];

export default function App() {
  const [tab, setTab] = useState<TabId>('inspect');

  return (
    <div style={{ display: 'flex', minHeight: '100vh' }}>
      <nav style={{
        width: 200, minWidth: 200, background: 'var(--panel)',
        borderRight: '1px solid var(--border)', padding: '16px 12px',
        position: 'sticky', top: 0, height: '100vh', overflowY: 'auto',
      }}>
        <h1 style={{ fontSize: 14, fontWeight: 600, marginBottom: 4 }}>⚛ VibeDFT</h1>
        <div style={{ fontSize: 10, color: 'var(--muted)', marginBottom: 16 }}>Workbench v0.2</div>
        {TABS.map(t => (
          <a key={t.id}
             onClick={() => setTab(t.id)}
             style={{
               display: 'block', padding: '6px 10px', borderRadius: 4,
               fontSize: 12, marginBottom: 2, cursor: 'pointer',
               color: tab === t.id ? 'var(--text)' : 'var(--muted)',
               background: tab === t.id ? 'rgba(88,166,255,.1)' : 'transparent',
               textDecoration: 'none',
             }}
          >
            <div>{t.label}</div>
            <div style={{ fontSize: 9, color: 'var(--muted)' }}>{t.desc}</div>
          </a>
        ))}
      </nav>
      <main style={{ flex: 1, padding: '20px 24px', maxWidth: 1100 }}>
        {tab === 'inspect' && <InspectView />}
        {tab === 'review' && <ReviewView />}
        {tab === 'report' && <ReportView />}
        {tab === 'convergence' && <ConvergenceView />}
        {tab === 'plan' && <PlanView />}
      </main>
    </div>
  )
}
