/**
 * Toolbar — the floating tool strip over the 3D view.
 * Build mode: select / delete + a hint for the active tool. Play mode: interactive spawn tools (add a vehicle or a
 * person by clicking next to a road while the simulation runs).
 */
import { C } from './ui'

const BUILD_TOOLS = [
  { id: 'select', icon: '✋', label: 'Select / move' },
  { id: 'delete', icon: '🗑', label: 'Delete' },
]
const SPAWN_TOOLS = [
  { id: 'spawn:car', icon: '🚗', label: 'Add car' }, { id: 'spawn:truck', icon: '🚚', label: 'Add truck' },
  { id: 'spawn:bus', icon: '🚌', label: 'Add bus' }, { id: 'spawn:tram', icon: '🚋', label: 'Add tram' },
  { id: 'spawn:emergency', icon: '🚑', label: 'Add ambulance' }, { id: 'spawn:person', icon: '🚶', label: 'Add pedestrian' },
]

export default function Toolbar({ mode, tool, setTool, hint }) {
  const tools = mode === 'build' ? BUILD_TOOLS : SPAWN_TOOLS
  return (
    <div style={{ position: 'absolute', top: 10, left: '50%', transform: 'translateX(-50%)', display: 'flex', flexDirection: 'column',
                  alignItems: 'center', gap: 6, pointerEvents: 'none' }}>
      <div data-testid="toolbar" style={{ display: 'flex', gap: 4, background: 'rgba(15,23,42,0.85)', borderRadius: 10, padding: 5,
                    pointerEvents: 'auto', border: `1px solid ${C.line}` }}>
        {tools.map(t => (
          <button key={t.id} onClick={() => setTool(tool === t.id && mode === 'play' ? null : t.id)} title={t.label} data-testid={`tool-${t.id}`}
                  style={{ width: 38, height: 38, fontSize: 19, borderRadius: 8, cursor: 'pointer', border: 'none',
                           background: tool === t.id ? C.blue : '#1e293b' }}>{t.icon}</button>
        ))}
      </div>
      {hint && <div style={{ background: 'rgba(0,0,0,0.7)', color: '#e2e8f0', fontSize: 11, padding: '3px 10px', borderRadius: 6 }}>{hint}</div>}
    </div>
  )
}
