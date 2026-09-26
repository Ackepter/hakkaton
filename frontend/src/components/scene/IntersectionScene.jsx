/**
 * IntersectionScene — R3F Canvas root.
 * Must be placed inside a container with explicit width + height.
 */
import { Canvas } from '@react-three/fiber'
import { OrbitControls } from '@react-three/drei'
import RoadSystem from './RoadSystem'
import VehicleModel from './VehicleModel'
import PedestrianModel from './PedestrianModel'
import TrafficLightModel from './TrafficLightModel'
import SceneEnvironment from './SceneEnvironment'

export default function IntersectionScene({ vehicles = [], pedestrians = [], lights = [] }) {
  return (
    <Canvas
      shadows
      camera={{ position: [0, 90, 90], fov: 45, near: 0.1, far: 1000 }}
      style={{ width: '100%', height: '100%', display: 'block', background: '#87ceeb' }}
    >
      <OrbitControls
        target={[0, 0, 0]}
        maxPolarAngle={Math.PI / 2.1}
        minDistance={20}
        maxDistance={300}
      />

      <ambientLight intensity={0.6} />
      <directionalLight
        castShadow
        position={[50, 100, 50]}
        intensity={1.2}
        shadow-mapSize-width={2048}
        shadow-mapSize-height={2048}
        shadow-camera-near={0.5}
        shadow-camera-far={500}
        shadow-camera-left={-150}
        shadow-camera-right={150}
        shadow-camera-top={150}
        shadow-camera-bottom={-150}
      />

      <SceneEnvironment />
      <RoadSystem />

      {lights.map(l => (
        <TrafficLightModel key={l.id} {...l} />
      ))}

      {vehicles.map(v => (
        <VehicleModel key={v.id} {...v} />
      ))}

      {pedestrians.map(p => (
        <PedestrianModel key={p.id} {...p} />
      ))}
    </Canvas>
  )
}
