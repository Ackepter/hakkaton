import { useCallback, useMemo, useRef, useState } from 'react'
import { ARMS, BUILDING_COLORS, footprint, hitsRoad, minArmLength, nextId } from './geometry'

const clone = (o) => JSON.parse(JSON.stringify(o))

/** After a road change: lengthen arms the bigger centre needs, drop decoration that now stands on the asphalt (undo restores it). */
function refit(l) {
  const need = minArmLength(l)
  for (const k of ARMS) if (l.arms[k].enabled && l.arms[k].length_m < need) l.arms[k].length_m = Math.min(80, Math.ceil(need))
  l.scenery = l.scenery.filter(o => !hitsRoad(l, o.x, o.z, footprint(o)))
}

/** A newly placed camera: 12 m mast, 70 degrees, aimed at the middle of the junction (yaw / pitch null = automatic). */
export const NEW_CAMERA = { radius_m: 90, enabled: true, height_m: 12, fov_deg: 70, yaw_deg: null, pitch_deg: null }
const MAX_HISTORY = 60

/**
 * The layout being edited (draft) with undo / redo.
 * The current value lives in a ref so state updaters stay pure (StrictMode safe).
 * `commit` = one undoable edit. `move` + `settle` = a drag: many live updates, one history entry.
 */
export default function useLayoutDraft() {
  const cur = useRef(null)
  const past = useRef([])
  const future = useRef([])
  const dragStart = useRef(null)
  const [draft, setDraftState] = useState(null)
  const [dirty, setDirty] = useState(false)

  const set = useCallback((v) => { cur.current = v; setDraftState(v) }, [])

  const reset = useCallback((layout, markDirty = false) => {
    past.current = []
    future.current = []
    dragStart.current = null
    set(clone(layout))
    setDirty(markDirty)
  }, [set])

  const push = (stack, item) => { stack.push(item); if (stack.length > MAX_HISTORY) stack.shift() }

  const commit = useCallback((mutate) => {
    const prev = cur.current
    if (!prev) return
    const next = clone(prev)
    mutate(next)
    push(past.current, prev)
    future.current = []
    set(next)
    setDirty(true)
  }, [set])

  const live = useCallback((mutate) => {
    const prev = cur.current
    if (!prev) return
    if (!dragStart.current) dragStart.current = prev
    const next = clone(prev)
    mutate(next)
    set(next)
  }, [set])

  const settle = useCallback((keep = true) => {
    const start = dragStart.current
    dragStart.current = null
    if (!start) return
    if (keep) {
      push(past.current, start)
      future.current = []
      setDirty(true)
    } else {
      set(start)
    }
  }, [set])

  const undo = useCallback(() => {
    if (!past.current.length) return
    push(future.current, cur.current)
    set(past.current.pop())
    setDirty(true)
  }, [set])

  const redo = useCallback(() => {
    if (!future.current.length) return
    push(past.current, cur.current)
    set(future.current.pop())
    setDirty(true)
  }, [set])

  const actions = useMemo(() => ({
    addScenery: (type, x, z, extra = {}) => {
      let id = null
      commit(l => {
        id = nextId(l, type)
        const o = { id, type, x, z, rotation_deg: 0, scale: 1, ...extra }
        if (type === 'building' && o.height == null) o.height = 12
        if (type === 'building' && !o.color) o.color = BUILDING_COLORS[l.scenery.length % BUILDING_COLORS.length]
        l.scenery.push(o)
      })
      return id
    },
    addCamera: (x, z) => {
      let id = null
      commit(l => {
        id = nextId(l, 'CAM')
        l.cameras.push({ id, x, z, ...NEW_CAMERA })
      })
      return id
    },
    update: (kind, id, patch) => commit(l => {
      const o = (kind === 'camera' ? l.cameras : l.scenery).find(i => i.id === id)
      if (o) Object.assign(o, patch)
    }),
    remove: (kind, id) => commit(l => {
      if (kind === 'camera') l.cameras = l.cameras.filter(c => c.id !== id)
      else l.scenery = l.scenery.filter(o => o.id !== id)
    }),
    move: (kind, id, x, z) => live(l => {
      const o = (kind === 'camera' ? l.cameras : l.scenery).find(i => i.id === id)
      if (o) { o.x = x; o.z = z }
    }),
    updateArm: (arm, patch) => commit(l => {
      const a = l.arms[arm]
      Object.assign(a, patch)
      if (patch.lanes_in !== undefined && a.turns) {              // keep one movement list per inbound lane
        while (a.turns.length < a.lanes_in) a.turns.push(['straight'])
        a.turns.length = a.lanes_in
      }
      refit(l)
    }),
    setLaneTurns: (arm, lane, moves) => commit(l => {              // moves: at least one of left / straight / right / uturn
      const a = l.arms[arm]
      if (!a.turns) a.turns = Array.from({ length: a.lanes_in ?? 1 }, () => ['straight'])
      a.turns[lane] = moves.length ? moves : ['straight']
    }),
    setJunction: (junction) => commit(l => {
      l.junction = junction
      if (junction === 'roundabout') for (const k of ARMS) {
        const a = l.arms[k]
        a.lanes_in = Math.min(a.lanes_in ?? 1, 2); a.lanes_out = Math.min(a.lanes_out ?? 1, 2)
        if (a.turns) a.turns.length = a.lanes_in
      }
      refit(l)
    }),
    updateSignal: (patch) => commit(l => { Object.assign(l.signal, patch) }),
    setProgram: (program) => commit(l => { l.signal.program = program }),
    updateTraffic: (patch) => commit(l => { Object.assign(l.traffic, patch) }),
    rename: (name) => commit(l => { l.name = name }),
  }), [commit, live])

  return {
    draft, dirty, setDirty, reset, settle, undo, redo, actions,
    canUndo: past.current.length > 0, canRedo: future.current.length > 0,
  }
}
