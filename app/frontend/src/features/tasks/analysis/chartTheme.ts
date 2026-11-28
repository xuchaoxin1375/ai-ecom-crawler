export interface ChartTheme {
  accent: string;
  success: string;
  danger: string;
  warning: string;
  info: string;
  ink: string;
  ink2: string;
  ink3: string;
  line: string;
  lineStrong: string;
  surface: string;
  surfaceMuted: string;
}

const FALLBACKS: ChartTheme = {
  accent: "#1f5c4a",
  success: "#2c6a4d",
  danger: "#a23a2e",
  warning: "#8f5f00",
  info: "#2c5c78",
  ink: "#1a1d19",
  ink2: "#4f564d",
  ink3: "#666d63",
  line: "#e0e3da",
  lineStrong: "#c7cbc0",
  surface: "#ffffff",
  surfaceMuted: "#f8f9f5",
};

function token(style: CSSStyleDeclaration, name: string, fallback: string): string {
  const value = style.getPropertyValue(name).trim();
  return value || fallback;
}

export function readChartTheme(element: HTMLElement): ChartTheme {
  const style = getComputedStyle(element);
  return {
    accent: token(style, "--color-accent", FALLBACKS.accent),
    success: token(style, "--color-success", FALLBACKS.success),
    danger: token(style, "--color-danger", FALLBACKS.danger),
    warning: token(style, "--color-warning", FALLBACKS.warning),
    info: token(style, "--color-info", FALLBACKS.info),
    ink: token(style, "--color-ink", FALLBACKS.ink),
    ink2: token(style, "--color-ink-2", FALLBACKS.ink2),
    ink3: token(style, "--color-ink-3", FALLBACKS.ink3),
    line: token(style, "--color-line", FALLBACKS.line),
    lineStrong: token(style, "--color-line-strong", FALLBACKS.lineStrong),
    surface: token(style, "--color-surface", FALLBACKS.surface),
    surfaceMuted: token(style, "--color-surface-muted", FALLBACKS.surfaceMuted),
  };
}

export function colorForToken(theme: ChartTheme, value: string): string {
  const match = /^var\(([^)]+)\)$/.exec(value.trim());
  if (!match) return value;
  const name = match[1].trim();
  const key = name
    .replace(/^--color-/, "")
    .replace(/-([a-z])/g, (_, letter: string) => letter.toUpperCase());
  const resolved = theme[key as keyof ChartTheme];
  return typeof resolved === "string" ? resolved : value;
}
