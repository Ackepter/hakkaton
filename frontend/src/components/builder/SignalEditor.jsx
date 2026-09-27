/**
 * SignalEditor — visual programming of the traffic signal.
 *   Adaptive: the controller reacts to demand; you tune the timings (green, yellow, all-red).
 *   Program: a sequence of blocks [phase: north-south lamp, east-west lamp, duration] executed exactly, in a loop.
 * The strip below the blocks previews one full cycle for both directions.
 */
import { Btn, C, NumberInput, Row, Section, Select, Slider } from './ui'
import { ARMS, enabledArms, isSplit } from '../../builder/geometry'

const LAMP = { RED: '#ef4444', YELLOW: '#facc15', GREEN: '#22c55e' }
const LAMPS = ['RED', 'YELLOW', 'GREEN']

const TEMPLATES = {
  'Standard cycle': (g = 30) => [
    { name: 'NS green', ns: 'GREEN', ew: 'RED', duration: g }, { name: 'NS yellow', ns: 'YELLOW', ew: 'RED', duration: 3 },
    { name: 'all red', ns: 'RED', ew: 'RED', duration: 3 }, { name: 'EW green', ns: 'RED', ew: 'GREEN', duration: g },
    { name: 'EW yellow', ns: 'RED', ew: 'YELLOW', duration: 3 }, { name: 'all red', ns: 'RED', ew: 'RED', duration: 3 }],
  'Main street priority': () => [
    { name: 'NS long green', ns: 'GREEN', ew: 'RED', duration: 45 }, { name: 'NS yellow', ns: 'YELLOW', ew: 'RED', duration: 3 },
    { name: 'all red', ns: 'RED', ew: 'RED', duration: 4 }, { name: 'EW short green', ns: 'RED', ew: 'GREEN', duration: 15 },
    { name: 'EW yellow', ns: 'RED', ew: 'YELLOW', duration: 3 }, { name: 'all red', ns: 'RED', ew: 'RED', duration: 4 }],
  'Pedestrian scramble': () => [
    { name: 'NS green', ns: 'GREEN', ew: 'RED', duration: 25 }, { name: 'NS yellow', ns: 'YELLOW', ew: 'RED', duration: 3 },
    { name: 'walk (all red)', ns: 'RED', ew: 'RED', duration: 14 }, { name: 'EW green', ns: 'RED', ew: 'GREEN', duration: 25 },
    { name: 'EW yellow', ns: 'RED', ew: 'YELLOW', duration: 3 }, { name: 'walk (all red)', ns: 'RED', ew: 'RED', duration: 14 }],
}

/** Junctions with turn lanes: one protected stage per arm (green -> yellow -> all red), in the order of the arms. */
const armByArm = (arms, g = 25) => arms.flatMap(a => [
  { name: `${a} green`, ns: 'RED', ew: 'RED', duration: g, arms: Object.fromEntries(arms.map(x => [x, x === a ? 'GREEN' : 'RED'])) },
  { name: `${a} yellow`, ns: 'RED', ew: 'RED', duration: 3, arms: Object.fromEntries(arms.map(x => [x, x === a ? 'YELLOW' : 'RED'])) },
  { name: 'all red', ns: 'RED', ew: 'RED', duration: 3, arms: Object.fromEntries(arms.map(x => [x, 'RED'])) }])

const ARM_SHORT = { north: 'N', south: 'S', east: 'E', west: 'W' }
const GROUP = { north: 'ns', south: 'ns', east: 'ew', west: 'ew' }
const lampOf = (p, arm) => p.arms?.[arm] ?? p[GROUP[arm]]

function LampPicker({ value, onChange, testid }) {
  return (
    <span style={{ display: 'inline-flex', gap: 3 }}>
      {LAMPS.map(s => (
        <button key={s} onClick={() => onChange(s)} title={s} data-testid={`${testid}-${s}`}
                style={{ width: 18, height: 18, borderRadius: '50%', cursor: 'pointer', background: LAMP[s],
                         opacity: value === s ? 1 : 0.28, border: value === s ? '2px solid #fff' : '2px solid transparent' }} />
      ))}
    </span>
  )
}

function Timeline({ program, arms, split }) {
  const total = program.reduce((s, p) => s + p.duration, 0) || 1
  const row = (label, lamp) => (
    <div key={label} style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 3 }}>
      <span style={{ width: 22, fontSize: 10, color: C.dim }}>{label}</span>
      <div style={{ flex: 1, display: 'flex', height: 12, borderRadius: 3, overflow: 'hidden' }}>
        {program.map((p, i) => <div key={i} title={`${p.name || 'phase'} ${p.duration}s`}
                                    style={{ width: `${(p.duration / total) * 100}%`, background: LAMP[lamp(p)] }} />)}
      </div>
    </div>
  )
  return <div style={{ marginTop: 8 }}>
    {split ? arms.map(a => row(ARM_SHORT[a], p => lampOf(p, a))) : [row('N–S', p => p.ns), row('E–W', p => p.ew)]}
    <div style={{ fontSize: 10, color: C.faint, textAlign: 'right' }}>cycle {total.toFixed(0)} s</div></div>
}

export default function SignalEditor({ signal, actions, layout }) {
  const fixed = signal.mode === 'fixed'
  const program = signal.program
  const arms = layout ? enabledArms(layout) : ARMS
  const split = !!layout && isSplit(layout)
  const templates = split ? { 'Arm by arm': () => armByArm(arms) } : TEMPLATES
  const roundabout = layout?.junction === 'roundabout'
  const setLamp = (i, arm, v) => setPhase(i, { arms: { ...Object.fromEntries(arms.map(a => [a, lampOf(program[i], a)])), [arm]: v } })
  const setPhase = (i, patch) => actions.setProgram(program.map((p, k) => (k === i ? { ...p, ...patch } : p)))
  const move = (i, d) => {
    const j = i + d
    if (j < 0 || j >= program.length) return
    const next = [...program]
    ;[next[i], next[j]] = [next[j], next[i]]
    actions.setProgram(next)
  }

  return (
    <>
      <Section title="Signal mode">
        <Row label="Mode">
          <Select value={signal.mode} testid="signal-mode" onChange={v => actions.updateSignal({ mode: v })}
                  options={[{ value: 'adaptive', label: 'Adaptive (reacts to traffic)' }, { value: 'fixed', label: 'My program (fixed)' }]} />
        </Row>
        {roundabout && <div style={{ fontSize: 11, color: C.faint }}>A roundabout has no lights: vehicles give way on the ring. These settings apply when you switch back to traffic lights.</div>}
        {split && <div style={{ fontSize: 11, color: C.faint }}>This junction has turn lanes: every arm gets its own protected green, so the program sets one lamp per arm.</div>}
      </Section>

      {!fixed && (
        <Section title="Adaptive timings">
          <Row label="Base green"><Slider value={signal.base_green} min={5} max={90} unit=" s" onChange={v => actions.updateSignal({
            base_green: v, min_green: Math.min(signal.min_green, v), max_green: Math.max(signal.max_green, v) })} /></Row>
          <Row label="Min green"><Slider value={signal.min_green} min={3} max={Math.min(60, signal.base_green)} unit=" s"
                                          onChange={v => actions.updateSignal({ min_green: v })} /></Row>
          <Row label="Max green"><Slider value={signal.max_green} min={Math.max(10, signal.base_green)} max={180} unit=" s"
                                          onChange={v => actions.updateSignal({ max_green: v })} /></Row>
          <Row label="Yellow"><Slider value={signal.yellow} min={1} max={10} unit=" s" onChange={v => actions.updateSignal({ yellow: v })} /></Row>
          <Row label="All-red"><Slider value={signal.all_red} min={1} max={15} unit=" s" onChange={v => actions.updateSignal({ all_red: v })} /></Row>
          <div style={{ fontSize: 11, color: C.faint }}>
            Green is cut short when nobody waits, extended (up to max) while cars keep coming, and given to crowds of pedestrians.
          </div>
        </Section>
      )}

      {fixed && (
        <Section title="Program (loops forever)"
                 right={<Select value="" onChange={v => v && actions.setProgram(templates[v]())}
                                options={[{ value: '', label: 'Templates…' }, ...Object.keys(templates)]} testid="program-templates" />}>
          {program.map((p, i) => (
            <div key={i} data-testid={`phase-${i}`} style={{ position: 'relative', background: C.card,
                                      borderLeft: `5px solid ${LAMP[split ? (arms.find(a => lampOf(p, a) !== 'RED') ? lampOf(p, arms.find(a => lampOf(p, a) !== 'RED')) : 'RED') : p.ns]}`,
                                      borderRight: `5px solid ${LAMP[split ? 'RED' : p.ew]}`, borderRadius: 6, padding: '6px 8px', marginBottom: 4 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 4 }}>
                <span style={{ fontSize: 10, color: C.faint }}>{i + 1}</span>
                <input value={p.name} maxLength={40} onChange={e => setPhase(i, { name: e.target.value })} placeholder="phase name"
                       style={{ flex: 1, minWidth: 0, background: 'transparent', color: C.text, border: 'none',
                                borderBottom: `1px solid ${C.line}`, fontSize: 12 }} />
                <Btn small onClick={() => move(i, -1)} disabled={i === 0} title="up">↑</Btn>
                <Btn small onClick={() => move(i, 1)} disabled={i === program.length - 1} title="down">↓</Btn>
                <Btn small color={C.red} onClick={() => actions.setProgram(program.filter((_, k) => k !== i))} testid={`phase-${i}-remove`}>✕</Btn>
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 10, fontSize: 11, color: C.dim, flexWrap: 'wrap' }}>
                {split ? arms.map(a => (
                  <span key={a}>{ARM_SHORT[a]} <LampPicker value={lampOf(p, a)} onChange={v => setLamp(i, a, v)} testid={`phase-${i}-${a}`} /></span>
                )) : (
                  <>
                    N–S <LampPicker value={p.ns} onChange={v => setPhase(i, { ns: v })} testid={`phase-${i}-ns`} />
                    E–W <LampPicker value={p.ew} onChange={v => setPhase(i, { ew: v })} testid={`phase-${i}-ew`} />
                  </>
                )}
                <span style={{ marginLeft: 'auto' }}>
                  <NumberInput value={p.duration} min={1} max={180} width={52} onChange={v => setPhase(i, { duration: v })}
                               testid={`phase-${i}-duration`} /> s
                </span>
              </div>
            </div>
          ))}
          <Btn small onClick={() => actions.setProgram([...program, { name: '', ns: 'RED', ew: 'RED', duration: 5,
                                                                       ...(split ? { arms: Object.fromEntries(arms.map(a => [a, 'RED'])) } : {}) }])}
               testid="phase-add" disabled={program.length >= 24}>+ Add phase</Btn>
          <Timeline program={program} arms={arms} split={split} />
          <div style={{ fontSize: 11, color: C.faint, marginTop: 6 }}>
            {split
              ? 'Arms whose traffic would cross (left turns, U-turns) must never be open together. Give every arm a green. '
              : 'North–south and east–west must never be open together. Give every direction a green. '}
            Pedestrians cross an arm only while the lights that serve it stay red long enough.
          </div>
        </Section>
      )}
    </>
  )
}
