import type { Config } from "tailwindcss";

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ground: "#141A22",
        surface: "#1B222C",
        "surface-2": "#222B37",
        border: "#2D3745",
        ink: "#E6EAEF",
        "ink-dim": "#8C97A6",
        "ink-faint": "#5E6A78",
        accent: "#3FB3AB",
        "accent-text": "#7FD6CE",
        crit: "#E2685F",
        warn: "#E0A855",
        watch: "#7C9BD6",
        good: "#5FB37E",
      },
      fontFamily: {
        mono: [
          "ui-monospace",
          "Cascadia Code",
          "Roboto Mono",
          "Menlo",
          "Consolas",
          "monospace",
        ],
        sans: [
          "-apple-system",
          "BlinkMacSystemFont",
          "Segoe UI",
          "Roboto",
          "Helvetica",
          "Arial",
          "sans-serif",
        ],
      },
    },
  },
  plugins: [],
} satisfies Config;
