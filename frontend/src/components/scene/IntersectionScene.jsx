/**
 * IntersectionScene — the R3F canvas: the city of a layout plus (in play mode) live traffic, or (in build mode)
 * the constructor's interaction layer. Must sit in a container with an explicit width and height.
 */
import { useState } from 'react'
import { Canvas } from '@react-three/fiber'
import { OrbitControls } from '@react-three/drei'
import RoadSystem from './RoadSystem'
import VehicleModel from './VehicleModel'
import PedestrianModel from './PedestrianModel'
import PedestrianLightModel from './PedestrianLightModel'
import TrafficLightModel from './TrafficLightModel'
import CameraModel from './CameraModel'
import { SceneryLayer } from './SceneryModels'
import BuildLayer from './BuildLayer'
import { ARMS, crossingId, defaultCamera, hasCrossing, lightPole, pedestrianLightPole } from '../../builder/geometry'

const MOUSE_BUILD = { LEFT: -1, MIDDLE: 1, RIGHT: 0 }      // build mode: left click is for tools, right drag orbits

export default function IntersectionScene({
  layout, vehicles = [], pedestrians = [], lights = [], pedestrianLights = [], cameraStatus = () => true, mode = 'play',
  tool = 'select', selection = null, setSelection = () => {}, actions = null, settle = () => {}, rotation = 0,
  onSpawn = () => {},
}) {
  const [dragging, setDragging] = useState(false)
  const build = mode === 'build'
  const shownLights = (build
    ? ARMS.filter(a => layout.arms[a].enabled).map(a => ({ id: `TL-${a[0].toUpperCase()}`, direction: a, state: 'RED' }))
    : lights).map(l => ({ ...l, pos: lightPole(layout, l.direction) }))
  const shownPedLights = (build
    ? ARMS.filter(a => hasCrossing(layout, a)).map(a => ({ id: crossingId(a), direction: a, state: 'RED' }))
    : pedestrianLights).map(p => ({ ...p, pos: pedestrianLightPole(layout, p.direction) }))

  return (
    <Canvas shadows camera={{ position: [0, 90, 90], fov: 45, near: 1, far: 900 }}
            style={{ width: '100%', height: '100%', display: 'block', background: '#87ceeb' }}>
      <OrbitControls target={[0, 0, 0]} maxPolarAngle={Math.PI / 2.1} minDistance={20} maxDistance={300}
                     enabled={!dragging} mouseButtons={build ? MOUSE_BUILD : undefined} />
      <ambientLight intensity={0.6} />
      <directionalLight castShadow position={[50, 100, 50]} intensity={1.2}
                        shadow-mapSize-width={2048} shadow-mapSize-height={2048}
                        shadow-camera-near={0.5} shadow-camera-far={500}
                        shadow-camera-left={-150} shadow-camera-right={150}
                        shadow-camera-top={150} shadow-camera-bottom={-150} />

      <RoadSystem layout={layout} />
      {!build && <SceneryLayer objects={layout.scenery} />}

      {!build && layout.cameras.filter(c => c.enabled).map(c => (
        <CameraModel key={c.id} cam={c} label={c.id} healthy={cameraStatus(c.id)} />
      ))}
      {!build && layout.cameras.filter(c => c.enabled).length === 0 && (
        <CameraModel cam={defaultCamera(layout)} label="CAM-01" overhead healthy={cameraStatus('CAM-01')} />
      )}

      {shownLights.map(l => <TrafficLightModel key={l.id} {...l} />)}
      {shownPedLights.map(p => <PedestrianLightModel key={p.id} {...p} />)}
      {!build && vehicles.map(v => <VehicleModel key={v.id} {...v} />)}
      {!build && pedestrians.map(p => <PedestrianModel key={p.id} {...p} />)}

      {actions && (
        <BuildLayer layout={layout} tool={tool} selection={selection} setSelection={setSelection} actions={actions}
                    settle={settle} rotation={rotation} setDragging={setDragging} onSpawn={onSpawn} mode={mode}
                    cameraStatus={cameraStatus} />
      )}
    </Canvas>
  )
}
