import { useEffect, useState } from 'react'
import api from '../api/client'

/** Polls /api/vision/cameras once per second. `offline` = backend unreachable (never throws). */
export default function useVision(intervalMs = 1000) {
  const [vision, setVision] = useState(null)
  const [offline, setOffline] = useState(false)

  useEffect(() => {
    let alive = true
    const load = async () => {
      try {
        const r = await api.get('/api/vision/cameras')
        if (alive) { setVision(r.data); setOffline(false) }
      } catch {
        if (alive) setOffline(true)
      }
    }
    load()
    const t = setInterval(load, intervalMs)
    return () => { alive = false; clearInterval(t) }
  }, [intervalMs])

  return { vision, offline }
}
