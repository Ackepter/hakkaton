/** Small shared controls for the constructor panels — Tailwind-styled, same props/API as before. */
export const C = {
  bg: '#111827', card: '#1e293b', line: '#334155', text: '#e2e8f0', dim: '#94a3b8', faint: '#64748b',
  green: '#16a34a', red: '#dc2626', yellow: '#eab308', blue: '#2563eb', accent: '#38bdf8',
}

export function Section({ title, children, right }) {
  return (
    <div className="mb-3.5">
      <div className="mb-1.5 flex items-center">
        <div className="text-[11px] font-bold uppercase tracking-wide text-muted-foreground">{title}</div>
        <div className="ml-auto">{right}</div>
      </div>
      {children}
    </div>
  )
}

export function Row({ label, children, hint }) {
  return (
    <label className="mb-1.5 flex items-center gap-2 text-xs" title={hint}>
      <span className="w-[92px] shrink-0 text-muted-foreground">{label}</span>
      <span className="flex min-w-0 flex-1 items-center gap-1.5">{children}</span>
    </label>
  )
}

export function Slider({ value, min, max, step = 1, onChange, unit = '', digits = 0, testid }) {
  return (
    <>
      <input type="range" min={min} max={max} step={step} value={value} data-testid={testid}
             onChange={e => onChange(parseFloat(e.target.value))} className="min-w-0 flex-1 accent-primary" />
      <span className="w-[52px] text-right font-mono text-[11px]">{Number(value).toFixed(digits)}{unit}</span>
    </>
  )
}

export function Toggle({ checked, onChange, label, testid }) {
  return (
    <label className="flex cursor-pointer items-center gap-1.5 text-xs">
      <input type="checkbox" checked={checked} data-testid={testid} onChange={e => onChange(e.target.checked)} className="accent-primary" /> {label}
    </label>
  )
}

export function Select({ value, onChange, options, testid, style }) {
  return (
    <select value={value} data-testid={testid} onChange={e => onChange(e.target.value)} style={style}
            className="rounded border border-input bg-background px-1.5 py-1 text-xs text-foreground">
      {options.map(o => <option key={o.value ?? o} value={o.value ?? o}>{o.label ?? o}</option>)}
    </select>
  )
}

export function NumberInput({ value, min, max, step = 1, onChange, width = 64, testid }) {
  return (
    <input type="number" value={value} min={min} max={max} step={step} data-testid={testid}
           onChange={e => { const v = parseFloat(e.target.value); if (!Number.isNaN(v)) onChange(Math.min(max, Math.max(min, v))) }}
           style={{ width }} className="rounded border border-input bg-background px-1.5 py-1 text-xs text-foreground" />
  )
}

export function Btn({ children, onClick, color = '#374151', disabled, title, testid, style, small }) {
  return (
    <button onClick={onClick} disabled={disabled} title={title} data-testid={testid}
            className={`rounded font-semibold text-white transition-opacity ${disabled ? 'cursor-default opacity-45' : 'cursor-pointer hover:opacity-90'} ${small ? 'px-2 py-1 text-[11px]' : 'px-3 py-1.5 text-xs'}`}
            style={{ background: color, ...style }}>{children}</button>
  )
}

export function Tabs({ tabs, value, onChange }) {
  return (
    <div className="mb-2.5 flex gap-0.5 border-b border-border">
      {tabs.map(t => (
        <button key={t.id} onClick={() => onChange(t.id)} data-testid={`tab-${t.id}`}
                className={`cursor-pointer border-b-2 px-2 py-1.5 text-xs font-semibold ${
                  value === t.id ? 'border-primary bg-secondary text-foreground' : 'border-transparent text-muted-foreground'
                }`}>{t.label}</button>
      ))}
    </div>
  )
}

export const Errors = ({ list }) => list && list.length ? (
  <div data-testid="errors" className="mb-2.5 rounded-md border border-destructive/60 bg-destructive/15 px-2 py-1.5 text-[11px] text-destructive">
    {list.map((e, i) => <div key={i}>⚠ {e}</div>)}
  </div>
) : null
