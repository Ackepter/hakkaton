/** Small dark-theme controls shared by the constructor panels. */
export const C = {
  bg: '#111827', card: '#1e293b', line: '#334155', text: '#e2e8f0', dim: '#94a3b8', faint: '#64748b',
  green: '#16a34a', red: '#dc2626', yellow: '#eab308', blue: '#2563eb', accent: '#38bdf8',
}

export function Section({ title, children, right }) {
  return (
    <div style={{ marginBottom: 14 }}>
      <div style={{ display: 'flex', alignItems: 'center', marginBottom: 6 }}>
        <div style={{ color: C.dim, fontSize: 11, fontWeight: 700, textTransform: 'uppercase', letterSpacing: 0.8 }}>{title}</div>
        <div style={{ marginLeft: 'auto' }}>{right}</div>
      </div>
      {children}
    </div>
  )
}

export function Row({ label, children, hint }) {
  return (
    <label style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6, fontSize: 12, color: C.text }} title={hint}>
      <span style={{ width: 92, flexShrink: 0, color: C.dim }}>{label}</span>
      <span style={{ flex: 1, display: 'flex', alignItems: 'center', gap: 6, minWidth: 0 }}>{children}</span>
    </label>
  )
}

export function Slider({ value, min, max, step = 1, onChange, unit = '', digits = 0, testid }) {
  return (
    <>
      <input type="range" min={min} max={max} step={step} value={value} data-testid={testid}
             onChange={e => onChange(parseFloat(e.target.value))} style={{ flex: 1, minWidth: 0 }} />
      <span style={{ width: 52, textAlign: 'right', fontFamily: 'monospace', fontSize: 11 }}>{Number(value).toFixed(digits)}{unit}</span>
    </>
  )
}

export function Toggle({ checked, onChange, label, testid }) {
  return (
    <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12, color: C.text, cursor: 'pointer' }}>
      <input type="checkbox" checked={checked} data-testid={testid} onChange={e => onChange(e.target.checked)} /> {label}
    </label>
  )
}

export function Select({ value, onChange, options, testid, style }) {
  return (
    <select value={value} data-testid={testid} onChange={e => onChange(e.target.value)}
            style={{ background: C.bg, color: C.text, border: `1px solid ${C.line}`, borderRadius: 4, padding: '3px 5px',
                     fontSize: 12, ...style }}>
      {options.map(o => <option key={o.value ?? o} value={o.value ?? o}>{o.label ?? o}</option>)}
    </select>
  )
}

export function NumberInput({ value, min, max, step = 1, onChange, width = 64, testid }) {
  return (
    <input type="number" value={value} min={min} max={max} step={step} data-testid={testid}
           onChange={e => { const v = parseFloat(e.target.value); if (!Number.isNaN(v)) onChange(Math.min(max, Math.max(min, v))) }}
           style={{ width, background: C.bg, color: C.text, border: `1px solid ${C.line}`, borderRadius: 4, padding: '3px 5px', fontSize: 12 }} />
  )
}

export function Btn({ children, onClick, color = '#374151', disabled, title, testid, style, small }) {
  return (
    <button onClick={onClick} disabled={disabled} title={title} data-testid={testid}
            style={{ background: color, color: '#fff', border: 'none', borderRadius: 5, cursor: disabled ? 'default' : 'pointer',
                     opacity: disabled ? 0.45 : 1, padding: small ? '3px 8px' : '6px 12px', fontSize: small ? 11 : 12,
                     fontWeight: 600, ...style }}>{children}</button>
  )
}

export function Tabs({ tabs, value, onChange }) {
  return (
    <div style={{ display: 'flex', gap: 2, borderBottom: `1px solid ${C.line}`, marginBottom: 10 }}>
      {tabs.map(t => (
        <button key={t.id} onClick={() => onChange(t.id)} data-testid={`tab-${t.id}`}
                style={{ background: value === t.id ? C.card : 'transparent', color: value === t.id ? C.text : C.dim,
                         border: 'none', borderBottom: value === t.id ? `2px solid ${C.accent}` : '2px solid transparent',
                         padding: '6px 8px', fontSize: 12, fontWeight: 600, cursor: 'pointer' }}>{t.label}</button>
      ))}
    </div>
  )
}

export const Errors = ({ list }) => list && list.length ? (
  <div data-testid="errors" style={{ background: '#450a0a', border: '1px solid #b91c1c', color: '#fecaca', borderRadius: 6,
                                     padding: '6px 8px', fontSize: 11, marginBottom: 10 }}>
    {list.map((e, i) => <div key={i}>⚠ {e}</div>)}
  </div>
) : null
