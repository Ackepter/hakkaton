/**
 * BuildLayer — everything the constructor adds inside the Canvas:
 *   * an invisible ground plane that turns the pointer into a snapped world position,
 *   * the translucent "ghost" of the object being placed (green = allowed, red = on a road / crosswalk),
 *   * pick / drag / select of existing objects, delete tool, and the interactive spawn tools in play mode.
 */
import { useEffect, useRef, useState } from 'react'
import { useThree } from '@react-three/fiber'
import SceneryObject from './SceneryModels'
import CameraModel from './CameraModel'
import { SCENE_TYPES, footprint, hitsRoad, nearestArm, crossingId, snap } from '../../builder/geometry'

export default function BuildLayer({ layout, tool, selection, setSelection, actions, settle, rotation, setDragging,
                                     onSpawn, mode, cameraStatus }) {
  const [cursor, setCursor] = useState(null)
  const drag = useRef(null)
  const { gl } = useThree()

  const place = tool && tool.startsWith('place:') ? tool.slice(6) : null
  const isCamera = tool === 'camera'
  const spawn = tool && tool.startsWith('spawn:') ? tool.slice(6) : null

  const ghost = place && cursor ? { id: 'ghost', type: place, x: cursor.x, z: cursor.z, rotation_deg: rotation, scale: 1,
                                    height: place === 'building' ? 12 : undefined } : null
  const ghostValid = ghost ? !hitsRoad(layout, ghost.x, ghost.z, footprint(ghost)) : true

  const world = (e) => ({ x: snap(e.point.x), z: snap(e.point.z) })

  useEffect(() => {                      // releasing the mouse outside the canvas must still end a drag
    const up = () => { if (drag.current) { finish(true) } }
    window.addEventListener('pointerup', up)
    return () => window.removeEventListener('pointerup', up)
  })

  const finish = (keep) => {
    const d = drag.current
    drag.current = null
    setDragging(false)
    if (!d) return
    if (keep && d.moved) {
      const o = d.kind === 'camera' ? layout.cameras.find(c => c.id === d.id) : layout.scenery.find(s => s.id === d.id)
      const bad = o && d.kind === 'scenery' && hitsRoad(layout, o.x, o.z, footprint(o))
      settle(!bad)                       // a drag that ends on a road is undone
    } else {
      settle(false)
    }
  }

  const onGroundMove = (e) => {
    const p = world(e)
    setCursor(p)
    if (drag.current) {
      drag.current.moved = true
      actions.move(drag.current.kind, drag.current.id, p.x, p.z)
    }
  }

  const onGroundClick = (e) => {
    if (e.delta > 4 || e.button !== 0) return             // a camera orbit gesture is not a click
    const p = world(e)
    if (spawn) {
      const arm = nearestArm(e.point.x, e.point.z)
      if (spawn === 'person') onSpawn({ kind: 'pedestrian', crossing: crossingId(arm) })
      else onSpawn({ kind: 'vehicle', arm, type: spawn })
      return
    }
    if (place && ghost && ghostValid) actions.addScenery(place, p.x, p.z, { rotation_deg: rotation, ...(place === 'building' ? { height: 12 } : {}) })
    else if (isCamera && layout.cameras.length < 4) actions.addCamera(p.x, p.z)
    else if (tool === 'select') setSelection(null)
  }

  const startDrag = (kind, id) => (e) => {
    if (mode !== 'build' || e.button !== 0) return
    e.stopPropagation()
    if (tool === 'delete') { actions.remove(kind, id); setSelection(null); return }
    if (tool !== 'select') return
    setSelection({ kind, id })
    drag.current = { kind, id, moved: false }
    setDragging(true)
    gl.domElement.style.cursor = 'grabbing'
  }

  const cursorStyle = () => {
    if (mode !== 'build') return spawn ? 'crosshair' : 'default'
    if (tool === 'delete') return 'not-allowed'
    if (place || isCamera) return ghostValid ? 'copy' : 'not-allowed'
    return 'default'
  }
  useEffect(() => { gl.domElement.style.cursor = cursorStyle() })

  return (
    <group>
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, 0.03, 0]}
            onPointerMove={onGroundMove} onClick={onGroundClick} onPointerLeave={() => setCursor(null)}>
        <planeGeometry args={[500, 500]} />
        <meshBasicMaterial transparent opacity={0} depthWrite={false} />
      </mesh>

      {mode === 'build' && layout.scenery.map(o => (
        <SceneryObject key={o.id} obj={o} pickable
                       ring={selection?.kind === 'scenery' && selection.id === o.id ? 'selected' : null}
                       onPointerDown={startDrag('scenery', o.id)} />
      ))}

      {mode === 'build' && layout.cameras.map(c => (
        <CameraModel key={c.id} label={c.id} mast={[c.x, c.z]} view={[c.x, c.z]} radius={c.radius_m}
                     healthy={cameraStatus(c.id)} dim={!c.enabled}
                     selected={selection?.kind === 'camera' && selection.id === c.id} pickable
                     onPointerDown={startDrag('camera', c.id)} />
      ))}

      {ghost && <SceneryObject obj={ghost} opacity={0.6} ring={ghostValid ? 'valid' : 'invalid'} />}
      {isCamera && cursor && (
        <CameraModel label="new camera" mast={[cursor.x, cursor.z]} view={[cursor.x, cursor.z]} radius={50} dim />
      )}
    </group>
  )
}

export { SCENE_TYPES }
