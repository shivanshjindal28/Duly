/**
 * Duly design tokens. Single source of truth: applied to :root as CSS variables at startup.
 *
 * Base palette from the hackathon deck (docs/brief). WCAG AA checks (contrast on white / canvas):
 *   text #0B1F44 16.2 / 15.1 · textSecondary #5B6B82 5.4 / 5.05 · primary #1D5FB5 6.3
 *   magenta #D6006E 5.1 · cyanText #0A7189 5.5 / 5.1
 * Bright cyan (2.97), green (3.15) and amber (2.03) fail AA as text on white, so they are used
 * only as fills, on navy, or next to an icon + text label; text uses the *Text variants:
 *   approveText #157A42 on approveBg 4.8 · flagText #8A5A00 on flagBg 5.4 · blockText #B0005B on blockBg 6.0
 * Sidebar: navyText #AFC0DA on navy 8.8, cyan on navy 5.5.
 */
export const tokens = {
  color: {
    navy: "#0B1F44",
    navy2: "#132B57",
    navyText: "#AFC0DA",
    primary: "#1D5FB5",
    primaryHover: "#164E96",
    primarySoft: "#E8F0FA",
    cyan: "#13A3C6",
    cyanText: "#0A7189",
    magenta: "#D6006E",
    green: "#1FA65A",
    amber: "#F5A623",
    approveText: "#157A42",
    approveBg: "#E8F6EE",
    flagText: "#8A5A00",
    flagBg: "#FEF4E2",
    blockText: "#B0005B",
    blockBg: "#FCE8F1",
    canvas: "#F4F7FA",
    surface: "#FFFFFF",
    border: "#DCE3EC",
    borderStrong: "#B9C5D6",
    text: "#0B1F44",
    textSecondary: "#5B6B82",
    focus: "#0A7189",
  },
  font: {
    sans: '"IBM Plex Sans", system-ui, -apple-system, "Segoe UI", sans-serif',
    mono: '"IBM Plex Mono", ui-monospace, "Cascadia Mono", Menlo, monospace',
  },
  radius: { sm: "3px", md: "6px" },
  space: { 1: "4px", 2: "8px", 3: "12px", 4: "16px", 5: "24px", 6: "32px", 7: "48px" },
  sidebarWidth: "232px",
  topbarHeight: "52px",
} as const;

function kebab(s: string): string {
  return s.replace(/[A-Z]/g, (m) => "-" + m.toLowerCase());
}

/** Write every token to :root as a CSS custom property, e.g. --color-cyan-text. */
export function applyTokens(root: HTMLElement = document.documentElement): void {
  for (const [group, values] of Object.entries(tokens)) {
    if (typeof values === "string") {
      root.style.setProperty(`--${kebab(group)}`, values);
      continue;
    }
    for (const [name, value] of Object.entries(values)) {
      root.style.setProperty(`--${group}-${kebab(name)}`, value);
    }
  }
}
