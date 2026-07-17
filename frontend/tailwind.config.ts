import type { Config } from "tailwindcss";

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // Dark, near-monochrome system: same restraint as bymonolog.com's
        // black/white minimalism (single accent, color reserved entirely
        // for severity), just inverted to a black ground for eye comfort.
        ground: "#0A0A0A",
        surface: "#131313",
        "surface-2": "#1E1E1E",
        border: "#2A2A2A",
        ink: "#F2F2F2",
        "ink-dim": "#A3A3A3",
        "ink-faint": "#6B6B6B",
        accent: "#F2F2F2",
        "accent-text": "#F2F2F2",
        // Severity is the one place color appears - tuned for contrast on
        // a black ground.
        crit: "#E2685F",
        warn: "#E0A855",
        watch: "#7C9BD6",
        good: "#5FB37E",
      },
      fontFamily: {
        // One family for everything (headings, body, and every existing
        // font-mono usage alike, aliased below) - hierarchy comes from
        // size/weight contrast, not a second typeface. No custom font
        // file: on Mac this resolves to SF Pro Display/Text, elsewhere to
        // the OS's own equivalent.
        sans: [
          "-apple-system",
          "BlinkMacSystemFont",
          "SF Pro Display",
          "Segoe UI",
          "Helvetica Neue",
          "Arial",
          "sans-serif",
        ],
        // Aliased to the same stack rather than removing every existing
        // font-mono className individually - flips every currently-mono
        // label/number to the single sans family in one place.
        mono: [
          "-apple-system",
          "BlinkMacSystemFont",
          "SF Pro Display",
          "Segoe UI",
          "Helvetica Neue",
          "Arial",
          "sans-serif",
        ],
      },
      borderRadius: {
        // Flattens every existing rounded-md/rounded-lg usage across the
        // app to a near-flat 2px in one place, matching the reference
        // site's minimal-radius chrome - `rounded-full` (pills, dots,
        // toggles, the brand mark) is untouched since those are
        // functional/conventional shapes, not decorative chrome.
        sm: "2px",
        DEFAULT: "2px",
        md: "2px",
        lg: "2px",
      },
    },
  },
  plugins: [],
} satisfies Config;
