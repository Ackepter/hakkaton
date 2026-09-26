/**
 * BuilderPanel — the constructor's side panel: objects, roads, signals, traffic, layouts and the inspector.
 * It only edits the draft through `actions`; the simulation changes when the layout is applied.
 */
import { useRef, useState } from 'react'
import { ARMS, SCENE_TYPES } from '../../builder/geometry'
import { Btn, C, Errors, NumberInput, Row, Section, Select, Slider, Tabs, Toggle } from './ui'
import SignalEditor from './SignalEditor'

const VEHICLES = ['car', 'truck', 'bus', 'tram', 'emergency']
const ARM_LABEL = { north: 'North', south: 'South', east: 'East', west: 'West' }

function Inspector({ draft, selection, actions, clear }) {
  if (!selection) return <div style={{ color: C.faint, fontSize: 12 }}>Nothing selected. Use the ✋ tool and click an object.</div>
  const isCam = selection.kind === 'camera'
  const o = (isCam ? draft.cameras : draft.scenery).find(i => i.id === selection.id)
  if (!o) return null
  const set = (patch) => actions.update(selection.kind, o.id, patch)
  return (
    <div data-testid="inspector">
      <div style={{ fontWeight: 700, fontSize: 13, color: C.text, marginBottom: 6 }}>
        {isCam ? '📷 Camera' : `${SCENE_TYPES[o.type].icon} ${SCENE_TYPES[o.type].label}`} <span style={{ color: C.faint, fontWeight: 400 }}>{o.id}</span>
      </div>
      <Row label="Position X"><NumberInput value={Math.round(o.x)} min={-150} max={150} onChange={v => set({ x: v })} testid="insp-x" /></Row>
      <Row label="Position Z"><NumberInput value={Math.round(o.z)} min={-150} max={150} onChange={v => set({ z: v })} testid="insp-z" /></Row>
      {isCam ? (
        <>
          <Row label="View radius"><Slider value={o.radius_m} min={20} max={70} unit=" m" onChange={v => set({ radius_m: v })} testid="insp-radius" /></Row>
          <Row label="Enabled"><Toggle checked={o.enabled} onChange={v => set({ enabled: v })} label="camera is on" /></Row>
        </>
      ) : (
        <>
          <Row label="Rotation"><Slider value={o.rotation_deg} min={-180} max={180} step={5} unit="°" onChange={v => set({ rotation_deg: v })} /></Row>
          <Row label="Size"><Slider value={o.scale} min={0.5} max={3} step={0.1} digits={1} unit="×" onChange={v => set({ scale: v })} testid="insp-scale" /></Row>
          {(o.type === 'building' || o.type === 'house') && (
            <Row label="Height"><Slider value={o.height ?? 12} min={2} max={60} unit=" m" onChange={v => set({ height: v })} /></Row>
          )}
          {['building', 'house', 'tree', 'kiosk'].includes(o.type) && (
            <Row label="Colour"><input type="color" value={o.color || '#7c8fb0'} onChange={e => set({ color: e.target.value })} /></Row>
          )}
        </>
      )}
      <Btn color={C.red} onClick={() => { actions.remove(selection.kind, o.id); clear() }} testid="insp-delete">🗑 Delete</Btn>
    </div>
  )
}

function ObjectsTab({ draft, tool, setTool, rotation, setRotation, selection, actions, clear }) {
  return (
    <>
      <Section title="Place (click on the ground)">
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 4 }}>
          {Object.entries(SCENE_TYPES).map(([type, t]) => (
            <Btn key={type} small color={tool === `place:${type}` ? C.blue : '#374151'} onClick={() => setTool(`place:${type}`)}
                 testid={`tool-place-${type}`}>{t.icon} {t.label}</Btn>
          ))}
          <Btn small color={tool === 'camera' ? C.blue : '#374151'} onClick={() => setTool('camera')} testid="tool-camera"
               disabled={draft.cameras.length >= 4}>📷 Camera</Btn>
        </div>
        <Row label="Rotation"><Slider value={rotation} min={0} max={345} step={15} unit="°" onChange={setRotation} /></Row>
        <div style={{ fontSize: 11, color: C.faint }}>R rotates the ghost. Green ring = free spot, red = on a road or crosswalk.</div>
      </Section>
      <Section title="Selected object"><Inspector draft={draft} selection={selection} actions={actions} clear={clear} /></Section>
      <div style={{ fontSize: 11, color: C.faint }}>{draft.scenery.length} objects · {draft.cameras.length}/4 cameras</div>
    </>
  )
}

function RoadsTab({ draft, actions }) {
  return (
    <>
      {ARMS.map(arm => {
        const a = draft.arms[arm]
        return (
          <div key={arm} data-testid={`arm-${arm}`} style={{ background: C.card, borderRadius: 8, padding: 8, marginBottom: 8,
                                                             opacity: a.enabled ? 1 : 0.6 }}>
            <div style={{ display: 'flex', alignItems: 'center', marginBottom: 6 }}>
              <span style={{ fontWeight: 700, fontSize: 13, color: C.text }}>{ARM_LABEL[arm]} road</span>
              <span style={{ marginLeft: 'auto' }}>
                <Toggle checked={a.enabled} onChange={v => actions.updateArm(arm, { enabled: v })} label="exists" testid={`arm-${arm}-enabled`} />
              </span>
            </div>
            {a.enabled && (
              <>
                <Row label="Length"><Slider value={a.length_m} min={30} max={80} unit=" m" onChange={v => actions.updateArm(arm, { length_m: v })}
                                            testid={`arm-${arm}-length`} /></Row>
                <Row label="Lane type">
                  <Select value={a.lane_type} testid={`arm-${arm}-lane`} onChange={v => actions.updateArm(arm, { lane_type: v })}
                          options={[{ value: 'mixed', label: 'Cars, trucks, buses' }, { value: 'bus', label: 'Bus lane' }, { value: 'tram', label: 'Tram track' }]} />
                </Row>
                <Row label="Speed limit"><Slider value={a.speed_limit_mps * 3.6} min={15} max={90} step={5} unit=" km/h"
                                                  onChange={v => actions.updateArm(arm, { speed_limit_mps: v / 3.6 })} /></Row>
                <Row label="Traffic share"><Slider value={a.weight} min={0} max={5} step={0.5} digits={1} unit="×"
                                                    onChange={v => actions.updateArm(arm, { weight: v })} /></Row>
                <Row label="Crosswalk"><Toggle checked={a.crossing} onChange={v => actions.updateArm(arm, { crossing: v })}
                                                label="pedestrian crossing" testid={`arm-${arm}-crossing`} /></Row>
              </>
            )}
          </div>
        )
      })}
      <div style={{ fontSize: 11, color: C.faint }}>
        Cars drive straight through. A missing opposite road becomes a dead end with a barrier.
      </div>
    </>
  )
}

function TrafficTab({ draft, actions }) {
  const t = draft.traffic
  const total = VEHICLES.reduce((s, k) => s + (t.type_probs[k] || 0), 0) || 1
  const setProb = (k, v) => actions.updateTraffic({ type_probs: { ...t.type_probs, [k]: v } })
  return (
    <>
      <Section title="Flow">
        <Row label="Vehicles"><Slider value={t.spawn_rate} min={0} max={100} unit="/min" onChange={v => actions.updateTraffic({ spawn_rate: v })} testid="traffic-rate" /></Row>
        <Row label="Pedestrians"><Slider value={t.ped_spawn_rate} min={0} max={60} unit="/min" onChange={v => actions.updateTraffic({ ped_spawn_rate: v })} testid="traffic-ped" /></Row>
      </Section>
      <Section title="Vehicle mix">
        {VEHICLES.map(k => (
          <Row key={k} label={k}>
            <Slider value={t.type_probs[k] || 0} min={0} max={1} step={0.01} digits={2} onChange={v => setProb(k, v)} />
            <span style={{ width: 34, fontSize: 10, color: C.faint }}>{Math.round(((t.type_probs[k] || 0) / total) * 100)}%</span>
          </Row>
        ))}
        <div style={{ fontSize: 11, color: C.faint }}>Bus lanes and tram tracks override the mix on their road.</div>
      </Section>
      <Section title="Live changes">
        <div style={{ fontSize: 11, color: C.faint }}>
          Press ▶ Play, then use the 🚗 🚚 🚌 🚋 🚑 🚶 tools in the top bar and click next to a road to add a vehicle or a person right now.
        </div>
      </Section>
    </>
  )
}

function LayoutsTab({ draft, actions, saved, presets, onSave, onLoadSaved, onLoadPreset, onDeleteSaved, onDownload, onUpload }) {
  const file = useRef(null)
  const [name, setName] = useState(draft.name)
  const valid = /^[A-Za-z0-9][A-Za-z0-9 _-]{0,39}$/.test(name)
  return (
    <>
      <Section title="This city">
        <Row label="Name">
          <input value={name} data-testid="layout-name" maxLength={40}
                 onChange={e => { setName(e.target.value); if (/^[A-Za-z0-9][A-Za-z0-9 _-]{0,39}$/.test(e.target.value)) actions.rename(e.target.value) }}
                 style={{ flex: 1, minWidth: 0, background: C.bg, color: C.text, border: `1px solid ${valid ? C.line : C.red}`,
                          borderRadius: 4, padding: '3px 6px', fontSize: 12 }} />
        </Row>
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
          <Btn small onClick={onSave} disabled={!valid} testid="layout-save" color={C.green}>💾 Save</Btn>
          <Btn small onClick={onDownload} testid="layout-download">⬇ Download JSON</Btn>
          <Btn small onClick={() => file.current?.click()}>⬆ Upload JSON</Btn>
          <input ref={file} type="file" accept="application/json" style={{ display: 'none' }}
                 onChange={e => { const f = e.target.files?.[0]; if (f) onUpload(f); e.target.value = '' }} />
        </div>
      </Section>
      <Section title="Saved cities">
        {saved.length === 0 && <div style={{ fontSize: 11, color: C.faint }}>Nothing saved yet.</div>}
        {saved.map(n => (
          <div key={n} style={{ display: 'flex', gap: 6, alignItems: 'center', marginBottom: 4 }}>
            <Btn small onClick={() => onLoadSaved(n)} style={{ flex: 1, textAlign: 'left' }} testid={`load-${n}`}>📂 {n}</Btn>
            <Btn small color={C.red} onClick={() => onDeleteSaved(n)} title="delete">✕</Btn>
          </div>
        ))}
      </Section>
      <Section title="Ready-made layouts">
        {Object.keys(presets).map(n => (
          <Btn key={n} small onClick={() => onLoadPreset(n)} style={{ display: 'block', width: '100%', textAlign: 'left', marginBottom: 4 }}
               testid={`preset-${n}`}>🏙 {n}</Btn>
        ))}
      </Section>
    </>
  )
}

export default function BuilderPanel(props) {
  const { draft, dirty, canUndo, canRedo, undo, redo, errors, busy, message, onApply, onPlay, tab, setTab } = props
  return (
    <div data-testid="builder-panel" style={{ color: C.text, fontSize: 12 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 8 }}>
        <div style={{ fontWeight: 700, fontSize: 14 }}>🏗 City builder</div>
        <span style={{ marginLeft: 'auto', display: 'flex', gap: 4 }}>
          <Btn small onClick={undo} disabled={!canUndo} title="Undo (Ctrl+Z)" testid="undo">↶</Btn>
          <Btn small onClick={redo} disabled={!canRedo} title="Redo (Ctrl+Y)" testid="redo">↷</Btn>
        </span>
      </div>
      <div style={{ display: 'flex', gap: 6, marginBottom: 8 }}>
        <Btn onClick={onApply} disabled={busy} color={dirty ? '#ca8a04' : '#374151'} testid="apply" style={{ flex: 1 }}>
          {dirty ? '✔ Apply changes' : '✔ Applied'}
        </Btn>
        <Btn onClick={onPlay} disabled={busy} color={C.green} testid="play" style={{ flex: 1 }}>▶ Play</Btn>
      </div>
      {message && <div data-testid="message" style={{ color: '#86efac', fontSize: 11, marginBottom: 6 }}>{message}</div>}
      <Errors list={errors} />
      <Tabs value={tab} onChange={setTab} tabs={[
        { id: 'objects', label: 'Objects' }, { id: 'roads', label: 'Roads' }, { id: 'signals', label: 'Signals' },
        { id: 'traffic', label: 'Traffic' }, { id: 'layouts', label: 'Cities' }]} />
      {tab === 'objects' && <ObjectsTab {...props} />}
      {tab === 'roads' && <RoadsTab {...props} />}
      {tab === 'signals' && <SignalEditor signal={draft.signal} actions={props.actions} />}
      {tab === 'traffic' && <TrafficTab {...props} />}
      {tab === 'layouts' && <LayoutsTab {...props} />}
    </div>
  )
}
