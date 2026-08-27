/**
 * Design tokens — the single source of truth for the visual system.
 *
 * Pure data, zero imports, so it can be consumed by the Ant Design theme
 * (`antdTheme.ts`) and by TSX that needs a raw value.
 *
 * Hand-written CSS reads the SAME values as custom properties from the `:root`
 * block at the top of `styles.css`. That duplication is deliberate: antd's JS
 * theme needs numbers, our stylesheet needs custom properties. Keeping both in
 * sync is the seam a future dark mode overrides — re-declare `:root` and add
 * `algorithm: theme.darkAlgorithm`, and nothing else has to move.
 *
 * Rule that keeps that promise: no colour literal may appear in `.tsx` outside
 * this file, and none may appear in `styles.css` below its `:root` block.
 */

/** Raw ramp. Prefer `semantic` at call sites so dark mode has one place to look. */
export const palette = {
  n0: '#ffffff',
  n50: '#f7f9fc',
  n100: '#eef2f8',
  n200: '#e2e8f2',
  n300: '#cbd4e3',
  n400: '#9aa7bf',
  n500: '#6b7a95',
  n600: '#4a5872',
  n700: '#333f56',
  n800: '#1f2940',
  n900: '#131b2e',
  // One value per accent. Replaces the 4 greens / 3 reds / 2 oranges that had
  // drifted between App.tsx, styles.css and ui.tsx.
  blue50: '#eaf1ff',
  blue500: '#4e8cff',
  blue600: '#3a73e0',
  green50: '#e6f7f1',
  green500: '#2fb08a',
  amber50: '#fdf3e3',
  amber500: '#e8992e',
  red50: '#fdecef',
  red500: '#e8556b',
  violet500: '#8b7cf0',
} as const

export const semantic = {
  bgApp: palette.n50,
  bgSurface: palette.n0,
  bgSubtle: palette.n100,
  textPrimary: palette.n800,
  textSecondary: palette.n500,
  textMuted: palette.n400,
  textHeading: palette.n900,
  border: palette.n200,
  borderStrong: palette.n300,
  accent: palette.blue500,
  accentHover: palette.blue600,
  accentSubtle: palette.blue50,
  positive: palette.green500,
  caution: palette.amber500,
  critical: palette.red500,
  navBg: palette.n900,
  navText: '#a9b6d2',
  navTextActive: palette.n0,
  navItemSelectedBg: '#1b2b54',
  navItemHoverBg: '#172447',
  /** Avatar has no background ComponentToken, so this is applied inline. */
  navAvatarBg: '#30477c',
  navAvatarText: '#c9d5f3',
  /** Progress fill on the dark report hero, passed as a prop rather than a
   *  CSS override — antd sets the bar colour inline, which no selector beats. */
  onDarkAccent: '#74a4ff',
} as const

/** Quality-score thresholds share the accent scale (see `QualityScore`). */
export const qualityColor = {
  a: semantic.positive,
  b: semantic.accent,
  c: semantic.caution,
  d: semantic.critical,
} as const

export const radius = { sm: 6, md: 10, lg: 14, xl: 20, pill: 999 } as const

/** 4px grid, matching antd's own `sizeUnit: 4` so both land on one rhythm. */
export const space = { x1: 4, x2: 8, x3: 12, x4: 16, x5: 24, x6: 32, x7: 48 } as const

/**
 * Two-part shadows: a tight contact shadow plus a wide ambient one. This is
 * what reads as depth; a single large blur reads as a smudge.
 */
export const elevation = {
  e1: '0 1px 2px rgba(19, 27, 46, .04), 0 1px 3px rgba(19, 27, 46, .06)',
  e2: '0 2px 4px rgba(19, 27, 46, .04), 0 8px 16px -4px rgba(19, 27, 46, .08)',
  e3: '0 4px 8px rgba(19, 27, 46, .05), 0 16px 32px -8px rgba(19, 27, 46, .10)',
} as const

/**
 * `Inter var` is self-hosted (see `public/fonts/`). It degrades to Segoe UI
 * Variable on Windows 11 rather than to Arial, so dropping the webfont later
 * stays a one-line change. CJK deliberately falls through to system faces —
 * a Chinese webfont would be megabytes.
 */
export const fontStack =
  "'Inter var', Inter, 'Segoe UI Variable Text', 'Segoe UI', system-ui, -apple-system, BlinkMacSystemFont, 'Noto Sans SC', 'Microsoft YaHei', sans-serif"

/**
 * Ligatures are disabled wherever this is used (see `styles.css`): `->`, `!=`
 * and `::` inside mangled C++ symbols must survive a copy into WinDbg.
 */
export const monoStack =
  "'JetBrains Mono', 'Cascadia Mono', Consolas, 'SFMono-Regular', ui-monospace, monospace"
