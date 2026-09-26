/**
 * Parse SI XML state string into JavaScript objects.
 * Uses browser DOMParser — no external dependencies.
 */
export function parseIntersectionXML(xmlString) {
  const parser = new DOMParser()
  const doc = parser.parseFromString(xmlString, 'text/xml')

  const parserError = doc.querySelector('parsererror')
  if (parserError) {
    throw new Error('XML parse error: ' + parserError.textContent)
  }

  const root = doc.documentElement
  if (root.tagName !== 'intersectionSimulation') {
    throw new Error('Unexpected root element: ' + root.tagName)
  }

  return {
    version: root.getAttribute('version'),
    timestamp: parseFloat(root.getAttribute('timestamp') || '0'),
    simulation: parseSimulation(root),
    lights: parseLights(root),
    vehicles: parseVehicles(root),
    pedestrians: parsePedestrians(root),
    metrics: parseMetrics(root),
  }
}

function parseSimulation(root) {
  const el = root.querySelector('simulation')
  if (!el) return null
  return {
    id: el.getAttribute('id'),
    status: el.getAttribute('status'),
    sim_time: parseFloat(el.getAttribute('sim_time') || '0'),
    time_scale: parseFloat(el.getAttribute('time_scale') || '1'),
    scenario: el.getAttribute('scenario'),
    seed: parseInt(el.getAttribute('seed') || '42', 10),
  }
}

function parseLights(root) {
  const lights = []
  root.querySelectorAll('trafficLights > light').forEach(el => {
    lights.push({
      id: el.getAttribute('id'),
      direction: el.getAttribute('direction'),
      state: el.getAttribute('state'),
      phase_index: parseInt(el.getAttribute('phase_index') || '0', 10),
      phase_switches: parseInt(el.getAttribute('phase_switches') || '0', 10),
    })
  })
  return lights
}

function parseVehicles(root) {
  const vehicles = []
  root.querySelectorAll('vehicles > vehicle').forEach(el => {
    vehicles.push({
      id: el.getAttribute('id'),
      vehicle_type: el.getAttribute('type'),
      lane_id: el.getAttribute('lane_id'),
      direction: el.getAttribute('direction'),
      position_m: parseFloat(el.getAttribute('position_m') || '0'),
      speed_mps: parseFloat(el.getAttribute('speed_mps') || '0'),
      state: el.getAttribute('state'),
      wait_time: parseFloat(el.getAttribute('wait_time') || '0'),
    })
  })
  return vehicles
}

function parsePedestrians(root) {
  const peds = []
  root.querySelectorAll('pedestrians > pedestrian').forEach(el => {
    peds.push({
      id: el.getAttribute('id'),
      crossing_id: el.getAttribute('crossing_id'),
      state: el.getAttribute('state'),
      position_m: parseFloat(el.getAttribute('position_m') || '0'),
      wait_time: parseFloat(el.getAttribute('wait_time') || '0'),
      direction: parseInt(el.getAttribute('direction') || '1', 10),
      offset: parseFloat(el.getAttribute('offset') || '0'),
    })
  })
  return peds
}

function parseMetrics(root) {
  const el = root.querySelector('metrics')
  if (!el) return null
  return {
    vehicles_active: parseInt(el.getAttribute('vehicles_active') || '0', 10),
    vehicles_waiting: parseInt(el.getAttribute('vehicles_waiting') || '0', 10),
    passed_total: parseInt(el.getAttribute('passed_total') || '0', 10),
    avg_wait_s: parseFloat(el.getAttribute('avg_wait_s') || '0'),
    max_wait_s: parseFloat(el.getAttribute('max_wait_s') || '0'),
    throughput_per_min: parseFloat(el.getAttribute('throughput_per_min') || '0'),
    congestion_pct: parseFloat(el.getAttribute('congestion_pct') || '0'),
    efficiency_pct: parseFloat(el.getAttribute('efficiency_pct') || '100'),
  }
}
