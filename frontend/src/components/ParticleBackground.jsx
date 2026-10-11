import { useEffect, useMemo, useRef, useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import {
  BarChart2,
  TrendingUp,
  PieChart,
  Activity,
  Zap,
  Target,
  LineChart,
  Layers,
} from 'lucide-react'

const ICONS = [
  'BarChart2',
  'TrendingUp',
  'PieChart',
  'Activity',
  'Zap',
  'Target',
  'LineChart',
  'Layers',
]

const ICON_MAP = {
  BarChart2,
  TrendingUp,
  PieChart,
  Activity,
  Zap,
  Target,
  LineChart,
  Layers,
}

const BLOB_CONFIG = [
  { w: 700, h: 700, x: -15, y: -10, color: '#2d1fa3', dur: 18 },
  { w: 500, h: 500, x: 60, y: 50, color: '#e84393', dur: 22 },
  { w: 400, h: 400, x: 80, y: -20, color: '#ffb347', dur: 14 },
  { w: 600, h: 600, x: 10, y: 70, color: '#1a1060', dur: 20 },
  { w: 300, h: 300, x: 45, y: 30, color: '#4535d4', dur: 16 },
  { w: 350, h: 350, x: -5, y: 85, color: '#ff2d78', dur: 25 },
]

function randomPos() {
  return { x: Math.random() * 90 + 5, y: Math.random() * 80 + 10 }
}

export default function ParticleBackground() {
  const [burst, setBurst] = useState([])
  const timeoutRef = useRef(null)

  const burstPalette = useMemo(() => ['#6c5ce7', '#ff2d78', '#ffb347', '#a29bfe'], [])

  useEffect(() => {
    const fire = () => {
      const count = 12 + Math.floor(Math.random() * 4)
      const particles = Array.from({ length: count }, (_, i) => ({
        id: Date.now() + i,
        icon: ICONS[i % ICONS.length],
        ...randomPos(),
        rotate: Math.random() * 360,
        scale: 0.6 + Math.random() * 0.8,
        color: burstPalette[i % burstPalette.length],
      }))
      setBurst(particles)

      if (timeoutRef.current) {
        clearTimeout(timeoutRef.current)
      }
      timeoutRef.current = setTimeout(() => setBurst([]), 4000)
    }

    fire()
    const intervalId = setInterval(fire, 20000)

    return () => {
      clearInterval(intervalId)
      if (timeoutRef.current) {
        clearTimeout(timeoutRef.current)
      }
    }
  }, [burstPalette])

  return (
    <div className="fixed inset-0 -z-10 overflow-hidden bg-surface-dark" aria-hidden="true">
      <div
        className="absolute inset-0"
        style={{
          backgroundImage:
            'linear-gradient(rgba(108,92,231,0.04) 1px, transparent 1px), linear-gradient(90deg, rgba(108,92,231,0.04) 1px, transparent 1px)',
          backgroundSize: '60px 60px',
        }}
      />

      {BLOB_CONFIG.map((blob, index) => (
        <motion.div
          key={index}
          className="absolute rounded-full blur-[120px] opacity-20 pointer-events-none"
          style={{
            width: blob.w,
            height: blob.h,
            left: `${blob.x}%`,
            top: `${blob.y}%`,
            background: blob.color,
          }}
          animate={{
            x: [0, 40, -20, 0],
            y: [0, -30, 20, 0],
            scale: [1, 1.15, 0.95, 1],
          }}
          transition={{
            duration: blob.dur,
            repeat: Infinity,
            ease: 'easeInOut',
          }}
        />
      ))}

      <AnimatePresence>
        {burst.map((particle, index) => {
          const Icon = ICON_MAP[particle.icon] || BarChart2
          return (
            <motion.div
              key={particle.id}
              className="absolute pointer-events-none"
              style={{ left: `${particle.x}%`, top: `${particle.y}%`, color: particle.color }}
              initial={{ opacity: 0, scale: 0, rotate: particle.rotate - 40 }}
              animate={{
                opacity: [0, 0.7, 0.7, 0],
                scale: [0, particle.scale, particle.scale, 0],
                rotate: particle.rotate,
                y: [0, -30, -60],
              }}
              transition={{
                duration: 3.5,
                ease: 'easeOut',
                delay: index * 0.06,
              }}
              exit={{ opacity: 0 }}
            >
              <Icon size={22} strokeWidth={1.8} />
            </motion.div>
          )
        })}
      </AnimatePresence>
    </div>
  )
}
