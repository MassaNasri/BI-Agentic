import { create } from 'zustand'

export const THEME_STORAGE_KEY = 'bi-theme'
export const THEMES = {
  DARK: 'dark',
  LIGHT: 'light',
}

const VALID_THEMES = new Set(Object.values(THEMES))

export const normalizeTheme = (theme) => {
  const normalizedTheme = String(theme || '').toLowerCase()
  return VALID_THEMES.has(normalizedTheme) ? normalizedTheme : THEMES.DARK
}

const readStoredTheme = () => {
  if (typeof window === 'undefined') return THEMES.DARK

  try {
    return normalizeTheme(window.localStorage.getItem(THEME_STORAGE_KEY))
  } catch {
    return THEMES.DARK
  }
}

const persistTheme = (theme) => {
  if (typeof window === 'undefined') return

  try {
    window.localStorage.setItem(THEME_STORAGE_KEY, normalizeTheme(theme))
  } catch {
    // Theme preference is non-critical; keep the active runtime theme.
  }
}

export const applyTheme = (theme) => {
  const nextTheme = normalizeTheme(theme)

  if (typeof document !== 'undefined') {
    document.documentElement.setAttribute('data-theme', nextTheme)
  }

  return nextTheme
}

export const useThemeStore = create((set, get) => ({
  theme: readStoredTheme(),

  setTheme: (theme) => {
    const nextTheme = applyTheme(theme)
    persistTheme(nextTheme)
    set({ theme: nextTheme })
  },

  toggleTheme: () => {
    const nextTheme = get().theme === THEMES.DARK ? THEMES.LIGHT : THEMES.DARK
    get().setTheme(nextTheme)
  },
}))

export const initializeTheme = () => {
  const initialTheme = applyTheme(readStoredTheme())
  useThemeStore.setState({ theme: initialTheme })
  return initialTheme
}

