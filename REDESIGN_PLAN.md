> **SUPERSEDED RELEASE PLANNING — 2026-10-27.** This earlier plan remains technical/historical reference, not a January commitment or production certificate. BIAVORA_PRODUCTION_READINESS_AUDIT/43_BIAVORA_PRODUCT_SCOPE_AND_RELEASE_ROADMAP_2027.md controls scope, dates and gates. The retained body must be revalidated before use; no new feature, Kubernetes requirement or cleanup is authorized by it.

# 🎨 Frontend Redesign Plan — Home / Signup / Login
> **For Codex**: Open this file and follow every section step by step.
> Goal: World-class redesign with powerful animations. No backend changes. No API/auth logic touched.

---

## 📌 Ground Rules (READ FIRST)

- ✅ Only touch: JSX structure, Tailwind classes, Framer Motion variants, CSS variables, `index.css`
- ❌ Never touch: `axios.js`, `endpoints.js`, `auth.js` (Zustand store), `App.jsx` routes, any API call logic
- ✅ Keep all existing `onClick`, `onSubmit`, `navigate()`, `authAPI.*` calls exactly as-is
- ✅ Keep all form field `name`, `id`, `value`, `onChange` attributes untouched
- ✅ Fix encoding bugs while redesigning (`ðŸŽ‰` → real emoji, `â†` → `←`, etc.)

---

## 🎨 Design System — Apply Globally

### Color Palette (add to `tailwind.config.js` + `index.css`)

```js
// tailwind.config.js — extend colors
colors: {
  brand: {
    950: '#03010a',
    900: '#080520',
    800: '#0f0a35',
    700: '#1a1060',
    600: '#2d1fa3',
    500: '#4535d4',   // primary CTA
    400: '#6c5ce7',
    300: '#a29bfe',
    200: '#d6d0ff',
    100: '#f0eeff',
  },
  fire: {
    600: '#e84393',
    500: '#ff2d78',   // hot pink accent
    400: '#ff6eb4',
  },
  amber: {
    500: '#ffb347',   // warm gold accent
    400: '#ffd580',
  },
  surface: {
    dark:  '#07041a',
    card:  'rgba(15,10,53,0.7)',
    glass: 'rgba(255,255,255,0.04)',
  }
}
```

```css
/* index.css — CSS variables */
:root {
  --c-bg:        #07041a;
  --c-primary:   #4535d4;
  --c-hot:       #ff2d78;
  --c-gold:      #ffb347;
  --c-text:      #e8e4ff;
  --c-muted:     #7b72b8;
  --c-card-bg:   rgba(15, 10, 53, 0.72);
  --c-border:    rgba(108, 92, 231, 0.25);
  --glow-purple: 0 0 40px rgba(69,53,212,0.45);
  --glow-pink:   0 0 40px rgba(255,45,120,0.35);
}
```

### Typography

```css
/* import in index.css */
@import url('https://fonts.googleapis.com/css2?family=Syne:wght@700;800&family=DM+Sans:wght@300;400;500&display=swap');

body      { font-family: 'DM Sans', sans-serif; background: var(--c-bg); color: var(--c-text); }
h1, h2    { font-family: 'Syne', sans-serif; }
```

---

## 🌌 Shared Background Component — `ParticleBackground.jsx`

> Create this new file: `src/components/ParticleBackground.jsx`
> Used on ALL three pages as a background layer.

### What it does:
- Dark deep-space background (`#07041a`)
- **Every 20 seconds**: scatter 12–15 mini analytics icons/shapes across the screen with a staggered burst animation, then fade out
- Continuously: 6 large soft blobs drifting slowly (purple, pink, gold tones)
- Subtle grid overlay (CSS, very faint, `opacity: 0.04`)

### Implementation sketch:

```jsx
// src/components/ParticleBackground.jsx
import { useEffect, useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'

// Analytics mini-icons (SVG strings or lucide icons):
// BarChart2, TrendingUp, PieChart, Activity, Zap, Target, LineChart, Layers

const ICONS = ['BarChart2','TrendingUp','PieChart','Activity','Zap','Target','LineChart','Layers']

function randomPos() {
  return { x: Math.random() * 90 + 5, y: Math.random() * 80 + 10 }
}

export default function ParticleBackground() {
  const [burst, setBurst] = useState([])

  // Trigger burst every 20 seconds
  useEffect(() => {
    const fire = () => {
      const particles = Array.from({ length: 14 }, (_, i) => ({
        id: Date.now() + i,
        icon: ICONS[i % ICONS.length],
        ...randomPos(),
        rotate: Math.random() * 360,
        scale: 0.6 + Math.random() * 0.8,
        color: ['#6c5ce7','#ff2d78','#ffb347','#a29bfe'][i % 4],
      }))
      setBurst(particles)
      setTimeout(() => setBurst([]), 4000) // fade out after 4s
    }
    fire() // fire once on mount
    const id = setInterval(fire, 20000)
    return () => clearInterval(id)
  }, [])

  return (
    <div className="fixed inset-0 -z-10 overflow-hidden" aria-hidden="true">

      {/* Grid overlay */}
      <div className="absolute inset-0"
        style={{ backgroundImage: 'linear-gradient(rgba(108,92,231,0.04) 1px, transparent 1px), linear-gradient(90deg, rgba(108,92,231,0.04) 1px, transparent 1px)',
                 backgroundSize: '60px 60px' }} />

      {/* Drifting blobs */}
      {[
        { w:700, h:700, x:-15, y:-10, color:'#2d1fa3', dur:18 },
        { w:500, h:500, x:60,  y:50,  color:'#e84393', dur:22 },
        { w:400, h:400, x:80,  y:-20, color:'#ffb347', dur:14 },
        { w:600, h:600, x:10,  y:70,  color:'#1a1060', dur:20 },
        { w:300, h:300, x:45,  y:30,  color:'#4535d4', dur:16 },
        { w:350, h:350, x:-5,  y:85,  color:'#ff2d78', dur:25 },
      ].map((b, i) => (
        <motion.div key={i}
          className="absolute rounded-full blur-[120px] opacity-20 pointer-events-none"
          style={{ width: b.w, height: b.h, left: `${b.x}%`, top: `${b.y}%`,
                   background: b.color }}
          animate={{ x: [0, 40, -20, 0], y: [0, -30, 20, 0], scale: [1, 1.15, 0.95, 1] }}
          transition={{ duration: b.dur, repeat: Infinity, ease: 'easeInOut' }}
        />
      ))}

      {/* 20-second analytics burst */}
      <AnimatePresence>
        {burst.map(p => (
          <motion.div key={p.id}
            className="absolute pointer-events-none"
            style={{ left: `${p.x}%`, top: `${p.y}%`, color: p.color }}
            initial={{ opacity: 0, scale: 0, rotate: p.rotate - 40 }}
            animate={{ opacity: [0, 0.7, 0.7, 0], scale: [0, p.scale, p.scale, 0],
                       rotate: p.rotate, y: [0, -30, -60] }}
            transition={{ duration: 3.5, ease: 'easeOut' }}
            exit={{ opacity: 0 }}
          >
            {/* render lucide icon by name — use dynamic import or a map of components */}
            <span style={{ fontSize: 22 }}>📊</span>
            {/* Replace with actual lucide icon component per icon name */}
          </motion.div>
        ))}
      </AnimatePresence>
    </div>
  )
}
```

> **Codex note**: Replace the emoji placeholder with real lucide-react icon components mapped from `ICONS` array.

---

## 🏠 Page 1 — `Home.jsx`

### Current state:
- Navbar + Hero (badge, title, subtitle, 2 CTA buttons)
- Feature cards section (staggered entry)
- Bottom CTA section
- Floating blobs background
- Framer Motion: `pageVariants`, `homeVariants.js`

### Redesign Instructions:

#### Overall feel:
Deep space analytics dashboard landing. Dark, premium, electric. Think "Vercel meets Stripe meets a hacker's dream".

#### Navbar:
```
- Background: `bg-brand-950/80 backdrop-blur-xl border-b border-brand-700/30`
- Logo: Syne font, gradient text (purple → pink): `bg-gradient-to-r from-brand-300 to-fire-400 bg-clip-text text-transparent`
- Nav links: DM Sans, muted color, hover → white with underline slide animation
- CTA button: outlined with hot-pink border, hover fills with gradient
- Entry animation: slide down from -30px + fade, duration 0.6s
```

#### Hero Section:
```
- Badge: pill shape, glass bg, purple border, pulsing ring animation
  text: "✦ Next-Gen Analytics Platform"
- H1 (Syne 800): 
  Line 1: white — "Transform Your"
  Line 2: gradient animate — "Data Into Power"
  (gradient animates between purple/pink/gold, 6s loop — keep existing animate-gradient)
- Subtitle: DM Sans 300, muted, max-w-xl centered
- Buttons:
  Primary "Create Free Account": 
    bg gradient brand-500→fire-500, rounded-xl px-8 py-4
    hover: scale 1.04 + glow shadow (--glow-pink)
    tap: scale 0.97
  Secondary "Sign In":
    glass bg, brand border, hover: border brightens + bg lightens
- Layout: centered, generous vertical padding
```

#### Feature Cards:
```
- 3–4 cards in a responsive grid
- Card style:
    bg: var(--c-card-bg)
    border: 1px solid var(--c-border)
    backdrop-blur-md
    rounded-2xl
    padding: p-6
- Icon container: gradient bg circle (brand-700→brand-600), icon white
- Hover animation:
    translateY(-8px)
    border-color: brand-400/60
    box-shadow: var(--glow-purple)
- Entry: stagger 0.1s delay per card, slide-up + fade
```

#### Animation variants to update (`homeVariants.js`):
```js
export const cardVariants = {
  hidden: { opacity: 0, y: 40 },
  visible: (i) => ({
    opacity: 1, y: 0,
    transition: { delay: i * 0.12, duration: 0.55, ease: [0.22, 1, 0.36, 1] }
  }),
  hover: {
    y: -8,
    boxShadow: '0 0 40px rgba(69,53,212,0.45)',
    transition: { duration: 0.25 }
  }
}

export const heroTextVariants = {
  hidden: { opacity: 0, y: 30 },
  visible: { opacity: 1, y: 0, transition: { duration: 0.7, ease: [0.22, 1, 0.36, 1] } }
}
```

#### Bottom CTA:
```
- Full-width section, bg: subtle radial gradient centered (brand-800 core, transparent edges)
- Border top: brand-700/30
- Shield icon: pulsing glow animation (keep existing pulse, update colors)
- Button: large, full gradient, strong glow on hover
```

---

## 🔐 Page 2 — `Login.jsx`

### Current state:
- Centered card with backdrop-blur
- Email + Password fields
- Submit button with loading state
- Links to Signup / Forgot Password / Home
- Floating blobs bg
- Framer Motion: `formVariants.js`

### Redesign Instructions:

#### Layout:
```
- Full viewport height, flex center
- Left side (hidden on mobile): decorative panel — large gradient mesh, 
  floating analytics icons, tagline in Syne font
- Right side: the login card
- On mobile: card only, centered
```

#### Login Card:
```
- Width: max-w-md w-full
- bg: var(--c-card-bg)
- border: 1px solid var(--c-border)
- backdrop-blur-2xl
- rounded-3xl
- padding: p-8 sm:p-10
- shadow: 0 25px 80px rgba(0,0,0,0.5)
```

#### Icon at top:
```
- Circle bg: gradient brand-700→brand-600
- Icon: ShieldCheck from lucide, white
- Animate: spring bounce on enter (keep existing iconContainerVariants, update colors)
- Add: subtle continuous glow pulse around circle
```

#### Title + Subtitle:
```
- Title: Syne 700, white, "Welcome Back"
- Subtitle: DM Sans, muted — "Sign in to your analytics workspace"
```

#### Input Fields:
```
Keep existing Input component, update styles:
- bg: rgba(255,255,255,0.04)
- border: 1px solid rgba(108,92,231,0.3)
- focus border: brand-400
- focus glow: 0 0 0 3px rgba(69,53,212,0.2)
- label: DM Sans, brand-300 color
- icons inside inputs: brand-400 color
```

#### Submit Button:
```
- Full width, rounded-xl, py-3.5
- bg: gradient from brand-500 to fire-500 (left→right)
- hover: scale 1.02 + increase glow
- tap: scale 0.98
- Loading: spinner + "Signing in..." text (keep existing logic)
```

#### Fix encoding bugs:
```
- Replace ðŸŽ‰  with  🎉
- Replace â†   with  ←
- Replace â€¢â€¢â€¢ with  •••  or use type="password" default masking
```

#### Animation variants to update (`formVariants.js`):
```js
export const formContainerVariants = {
  hidden: { opacity: 0, y: 50, scale: 0.97 },
  visible: {
    opacity: 1, y: 0, scale: 1,
    transition: { duration: 0.6, ease: [0.22, 1, 0.36, 1] }
  }
}

export const errorShakeVariants = {
  shake: {
    x: [0, -12, 12, -8, 8, -4, 4, 0],
    transition: { duration: 0.5, ease: 'easeInOut' }
  }
}
```

---

## 📝 Page 3 — `Signup.jsx`

### Current state:
- Similar card layout to Login
- More fields: name, email, password + possibly workspace fields
- Validation logic exists — DO NOT TOUCH
- Success → navigate to `/verify-email`

### Redesign Instructions:

#### Layout:
```
Same split layout as Login (decorative left panel + card right)
Left panel: different tagline — "Start your analytics journey"
Show animated stats/numbers floating (use ParticleBackground mini version)
```

#### Signup Card:
```
Same card styling as Login card (glass, blur, rounded-3xl)
Icon: UserPlus or Sparkles lucide icon, same animated circle
Title: "Create Your Account" (Syne 700)
Subtitle: "Join thousands of analysts worldwide"
```

#### Multi-step feel (visual only, no logic change):
```
Add a thin progress indicator at top of card:
- 3 dots / steps shown as small circles
- Step 1 active (brand-500), steps 2-3 muted
- This is PURELY decorative — do not add actual step logic
```

#### Fields:
```
Same input styling as Login
Add: password strength indicator bar below password field
  - Visual only: calculate strength client-side (length + special chars)
  - Colors: red (weak) → amber (ok) → green (strong)
  - Animate width with Framer Motion layout animation
```

#### Submit Button:
```
Same as Login button
Text: "Create Account" / loading: "Creating account..."
```

#### Workspace invite banner (if applicable):
```
When invite token present, show a highlighted banner above the card:
- bg: gradient brand-800→brand-700, border brand-500/50
- Icon: Users from lucide
- Text: "You've been invited to join [workspace name]"
- Animate: slide down + fade on enter
```

---

## ⚡ Animation Master Plan

### Page transitions (all 3 pages):
```js
// variants.js — update pageVariants
export const pageVariants = {
  hidden:  { opacity: 0, filter: 'blur(8px)' },
  visible: { opacity: 1, filter: 'blur(0px)',
             transition: { duration: 0.5, ease: [0.22, 1, 0.36, 1] } },
  exit:    { opacity: 0, filter: 'blur(8px)',
             transition: { duration: 0.3 } }
}
```

### Shared animation principles:
| Element | Animation | Duration | Easing |
|---|---|---|---|
| Page enter | fade + deblur | 0.5s | cubic-bezier(0.22,1,0.36,1) |
| Card enter | slide-up + scale | 0.6s | same |
| Form fields | stagger 0.07s each | 0.4s | easeOut |
| Buttons hover | scale 1.03 + glow | 0.2s | easeOut |
| Error shake | horizontal oscillate | 0.5s | easeInOut |
| Icon enter | spring bounce | — | spring(stiffness:300) |
| Blob drift | x/y/scale loop | 14–25s | easeInOut, Infinity |
| Analytics burst | scatter + float up + fade | 3.5s | easeOut, every 20s |
| Gradient text | hue-shift loop | 6s | linear, Infinity |

---

## 📁 Files to Create / Modify

| Action | File |
|---|---|
| 🆕 Create | `src/components/ParticleBackground.jsx` |
| ✏️ Modify | `src/pages/Home.jsx` |
| ✏️ Modify | `src/pages/auth/Login.jsx` |
| ✏️ Modify | `src/pages/auth/Signup.jsx` |
| ✏️ Modify | `src/animations/homeVariants.js` |
| ✏️ Modify | `src/animations/formVariants.js` |
| ✏️ Modify | `src/animations/variants.js` |
| ✏️ Modify | `src/styles/index.css` |
| ✏️ Modify | `tailwind.config.js` |
| ❌ Do NOT touch | `src/api/axios.js` |
| ❌ Do NOT touch | `src/api/endpoints.js` |
| ❌ Do NOT touch | `src/store/auth.js` |
| ❌ Do NOT touch | `src/App.jsx` (routes) |

---

## ✅ Final Checklist for Codex

- [ ] `ParticleBackground` added and used in all 3 pages
- [ ] Color system updated in `tailwind.config.js` and `index.css`
- [ ] Fonts (Syne + DM Sans) imported in `index.css`
- [ ] All encoding bugs fixed (`ðŸŽ‰`, `â†`, etc.)
- [ ] All API calls / form submit handlers untouched
- [ ] All `navigate()` calls untouched
- [ ] Auth store (`zustand`) untouched
- [ ] Analytics burst fires every 20 seconds
- [ ] Password strength bar added to Signup (visual only)
- [ ] Split layout implemented on Login + Signup (responsive)
- [ ] Page transitions use blur + fade
- [ ] No purple-on-white clichés — dark theme throughout
