/**
 * Toolbar — the floating tool strip over the 3D view.
 * Build mode: select / delete + a hint for the active tool. Play mode: interactive spawn tools (add a vehicle or a
 * person by clicking next to a road while the simulation runs).
 */
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
    <div className="pointer-events-none absolute left-1/2 top-2.5 flex -translate-x-1/2 flex-col items-center gap-1.5">
      <div data-testid="toolbar" className="pointer-events-auto flex gap-1 rounded-xl border border-border bg-card/90 p-1.5 shadow-sm">
        {tools.map(t => (
          <button key={t.id} onClick={() => setTool(tool === t.id && mode === 'play' ? null : t.id)} title={t.label} data-testid={`tool-${t.id}`}
                  className={`h-[38px] w-[38px] cursor-pointer rounded-lg text-lg transition-colors ${
                    tool === t.id ? 'bg-primary text-primary-foreground' : 'bg-secondary hover:bg-accent'
                  }`}>{t.icon}</button>
        ))}
      </div>
      {hint && <div className="rounded-md bg-black/70 px-2.5 py-1 text-xs text-foreground">{hint}</div>}
    </div>
  )
}
