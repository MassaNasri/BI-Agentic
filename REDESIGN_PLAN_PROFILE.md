> **SUPERSEDED RELEASE PLANNING — 2026-10-27.** This earlier plan remains technical/historical reference, not a January commitment or production certificate. BIAVORA_PRODUCTION_READINESS_AUDIT/43_BIAVORA_PRODUCT_SCOPE_AND_RELEASE_ROADMAP_2027.md controls scope, dates and gates. The retained body must be revalidated before use; no new feature, Kubernetes requirement or cleanup is authorized by it.

# 🎨 Frontend Redesign Plan — Profile Page
> **For Codex**: Open this file and follow every section step by step.
> Goal: World-class redesign consistent with REDESIGN_PLAN.md (Home/Login/Signup).
> No backend changes. No API/auth logic touched.

---

## 📌 Ground Rules (READ FIRST)

- ✅ Only touch: JSX structure, Tailwind classes, Framer Motion variants, CSS variables, `index.css`
- ✅ Must stay **visually consistent** with the design system defined in `REDESIGN_PLAN.md`
- ❌ Never touch: `axios.js`, `endpoints.js`, `auth.js` (Zustand store), `App.jsx` routes
- ❌ Never touch any API call logic: `loadProfile`, `PUT /user/profile/`, `POST /user/change-password/`, `DELETE /user/deactivate/`
- ✅ Keep all `updateUser()`, `logout()`, `navigate()` calls exactly as-is
- ✅ Keep all form `name`, `id`, `value`, `onChange`, `onSubmit` attributes untouched
- ✅ Keep all validation logic untouched (`errors`, `passwordErrors`, required fields, password match)
- ✅ Keep all Modal open/close state logic untouched (`showChangePasswordModal`, `showDeactivateModal`)
- ✅ Keep all loading states untouched (`isLoading`, `isChangingPassword`, `isDeactivating`)

---

## 🎨 Design System — Same as REDESIGN_PLAN.md

> If already applied from REDESIGN_PLAN.md, skip this section. If not, apply it now.

```css
/* Verify these exist in index.css */
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
/* Fonts: Syne (headings) + DM Sans (body) — already imported */
```

---

## 🌌 Background

> `ParticleBackground` component already created in `REDESIGN_PLAN.md`.

```jsx
// Add to Profile.jsx — same as other pages
import ParticleBackground from '../../components/ParticleBackground'

// Inside return:
<ParticleBackground />
```

---

## 🧩 Page Layout — `Profile.jsx`

### Overall Structure:

```
DashboardLayout
  └── AnimatedPage (keep existing wrapper)
        └── ParticleBackground
        └── Page content (max-w-4xl mx-auto)
              ├── Page Header
              ├── Card: Profile Information
              ├── Card: Security
              ├── Card: Account Information
              └── Card: Danger Zone
```

### Page Header:
```
- Title: Syne 700, white — "My Profile"
- Subtitle: DM Sans, muted — "Manage your personal information and account settings"
- Add a thin horizontal divider below: border-brand-700/30
- Entry animation: headerTitle variant (keep existing, just update colors)
```

### Cards — Global Style:
```
All 4 cards use the same base style:
  bg: var(--c-card-bg)
  border: 1px solid var(--c-border)
  backdrop-blur-xl
  rounded-2xl
  padding: p-6 sm:p-8
  shadow: 0 20px 60px rgba(0,0,0,0.4)

Section title inside each card:
  font: Syne 700
  color: white
  size: text-lg
  + small colored icon to the left (lucide, brand-400 color)

Divider between card title and content:
  border-brand-700/20 mb-6
```

---

## 👤 Card 1 — Profile Information

### Layout:
```
- Avatar area at top:
    Large circle (w-20 h-20)
    bg: gradient brand-700 → brand-500
    initials of first_name + last_name (Syne font, white, text-2xl)
    Subtle pulsing ring: animate border-color between brand-500/40 and brand-300/60 (3s loop)
    Below avatar: display full name (Syne, white) + role Badge

- Below avatar: 2-column grid (sm:grid-cols-2) for input fields
    Fields: first_name, last_name
    email: read-only field — styled differently:
      bg: rgba(255,255,255,0.02)
      border: dashed, brand-700/40
      text: muted color
      add a small lock icon (lucide Lock, size 14) on the right
      tooltip or small text below: "Email cannot be changed"
```

### Input fields style (consistent with Login/Signup):
```
bg: rgba(255,255,255,0.04)
border: 1px solid rgba(108,92,231,0.3)
focus border: brand-400
focus glow: 0 0 0 3px rgba(69,53,212,0.2)
label: DM Sans, brand-300
border-radius: rounded-xl
```

### Action buttons:
```
"Save Changes":
  gradient bg: brand-500 → fire-500
  rounded-xl px-6 py-2.5
  hover: scale 1.03 + glow (--glow-purple)
  tap: scale 0.97
  loading: spinner + "Saving..."

"Reset Changes":
  glass bg: rgba(255,255,255,0.04)
  border: brand-700/40
  text: muted
  hover: border brightens, text white
```

---

## 🔒 Card 2 — Security

### Layout:
```
- Card icon: ShieldCheck (lucide), brand-400
- Single prominent button: "Change Password"
    Style: outlined, border fire-500/60, text fire-400
    hover: bg fire-500/10, border fire-400, glow (--glow-pink)
    Icon: KeyRound (lucide) to the left of text
- Below button: small muted text — "Last changed: [date if available, else 'Never']"
```

### Change Password Modal — redesign:
```
Modal overlay: bg black/70 backdrop-blur-sm

Modal card:
  bg: var(--c-card-bg)
  border: var(--c-border)
  backdrop-blur-2xl
  rounded-2xl
  max-w-md w-full
  padding: p-8

Modal header:
  Icon: KeyRound in gradient circle (same style as Login icon)
  Title: "Change Password" (Syne 700)
  Close button: top-right, muted, hover white

Fields: current_password, new_password, confirm_new_password
  Same input style as Card 1
  Show/hide password toggle (eye icon) — if not present, add visual only, keep logic as-is

Submit button:
  Same gradient style as Save Changes
  Full width
  loading: "Updating password..."

Entry animation:
  Modal slides up + scale from 0.95 → 1 (formContainerVariants)
  Fields stagger in (formFieldVariants)
```

---

## ℹ️ Card 3 — Account Information

### Layout:
```
- Read-only info grid (2 columns on sm+):
    Items: Role, Account Status, Email Verified, Member Since
    Each item:
      label: DM Sans, brand-300, text-sm
      value: DM Sans 500, white

- Badges:
    Role badge:
      admin   → gradient bg brand-500/20, border brand-500/40, text brand-300
      manager → same tones, slightly different shade
      analyst → amber tones: amber-500/20 border, amber-400 text
      executive → fire tones: fire-500/20 border, fire-400 text

    Active badge: green-500/20 bg, green-400 text, green dot pulse
    Verified badge: brand-300/20 bg, brand-200 text, checkmark icon

- Entry: scaleFade variant (keep existing, update colors)
```

---

## ⚠️ Card 4 — Danger Zone

### Layout:
```
Card border: 1px solid rgba(255, 45, 120, 0.25)   ← fire/red tone
Card bg: rgba(30, 5, 15, 0.6)   ← darker reddish tint

Header:
  Icon: AlertTriangle (lucide), fire-500
  Title: "Danger Zone" (Syne 700, fire-400)

Warning text:
  DM Sans, muted/warm tone
  "Deactivating your account is permanent and cannot be undone."

"Deactivate Account" button:
  bg: fire-500/10
  border: fire-500/50
  text: fire-400
  hover: bg fire-500/20, border fire-500, text white, glow (--glow-pink)
  tap: scale 0.97
  Icon: PowerOff (lucide) left of text
```

### Deactivate Confirm Modal — redesign:
```
Same modal card style as Change Password modal

Header:
  Icon: AlertTriangle in red/fire gradient circle
  Title: "Confirm Deactivation" (Syne 700, fire-400)

Body text: clear warning, DM Sans, warm-muted color

Buttons row:
  Cancel: glass style, muted
  Confirm Deactivate: solid fire-500 bg, white text
    hover: deeper red, glow (--glow-pink)
    loading: spinner + "Deactivating..."
```

---

## ⚡ Animation Plan for Profile

### Page & Section Entry:
```js
// uiVariants.js — update/add these variants

export const sectionCardVariants = {
  hidden:  { opacity: 0, y: 30 },
  visible: (i) => ({
    opacity: 1, y: 0,
    transition: { delay: i * 0.1, duration: 0.55, ease: [0.22, 1, 0.36, 1] }
  })
}

export const avatarVariants = {
  hidden:  { opacity: 0, scale: 0.8 },
  visible: { opacity: 1, scale: 1,
             transition: { type: 'spring', stiffness: 280, damping: 22 } }
}

export const badgeVariants = {
  hidden:  { opacity: 0, scale: 0.7 },
  visible: { opacity: 1, scale: 1,
             transition: { type: 'spring', stiffness: 300, delay: 0.15 } }
}
```

### Animation Summary Table:
| Element | Animation | Duration | Notes |
|---|---|---|---|
| Page enter | fade + y offset | 0.5s | AnimatedPage — keep as-is |
| Each Card | slide-up + fade, staggered | 0.55s | 0.1s delay per card |
| Avatar circle | spring scale | spring | bounce on load |
| Badges | spring scale | spring | slight delay |
| Save button hover | scale + glow | 0.2s | --glow-purple |
| Danger button hover | scale + fire glow | 0.2s | --glow-pink |
| Modal enter | slide-up + scale | 0.4s | formContainerVariants |
| Modal fields | stagger 0.07s | 0.35s | formFieldVariants |
| Alert/error enter | slide down + fade | 0.3s | AnimatePresence |
| Avatar ring pulse | border-color loop | 3s | CSS animation, Infinity |

---

## 📁 Files to Modify

| Action | File |
|---|---|
| ✏️ Modify | `src/pages/profile/Profile.jsx` |
| ✏️ Modify | `src/animations/uiVariants.js` |
| ✏️ Modify | `src/components/Card.jsx` (update default card style) |
| ✏️ Modify | `src/components/Badge.jsx` (update badge color variants) |
| ✏️ Modify | `src/components/Modal.jsx` (update modal card style) |
| ✅ Already done | `src/styles/index.css` (from REDESIGN_PLAN.md) |
| ✅ Already done | `tailwind.config.js` (from REDESIGN_PLAN.md) |
| ✅ Already done | `src/components/ParticleBackground.jsx` (from REDESIGN_PLAN.md) |
| ❌ Do NOT touch | `src/api/axios.js` |
| ❌ Do NOT touch | `src/api/endpoints.js` |
| ❌ Do NOT touch | `src/store/auth.js` |
| ❌ Do NOT touch | `src/App.jsx` |
| ❌ Do NOT touch | `src/layouts/DashboardLayout.jsx` (sidebar logic) |

---

## ✅ Final Checklist for Codex

- [ ] `ParticleBackground` added to Profile page
- [ ] All 4 cards use the unified glass card style (var --c-card-bg, border, blur)
- [ ] Avatar circle with initials + pulsing ring added
- [ ] Role/Status/Verified badges updated with new color variants
- [ ] Email field styled as read-only with lock icon
- [ ] "Change Password" modal redesigned (glass card, gradient icon, stagger fields)
- [ ] "Deactivate Account" modal redesigned (fire/red tones, warning icon)
- [ ] Danger Zone card has fire-toned border and bg
- [ ] All API calls untouched (`loadProfile`, `PUT`, `POST`, `DELETE`)
- [ ] All form validation logic untouched
- [ ] All navigation/logout logic untouched
- [ ] Animation variants updated in `uiVariants.js`
- [ ] Design is visually consistent with Home / Login / Signup redesign
