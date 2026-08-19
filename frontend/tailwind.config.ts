import type { Config } from "tailwindcss";

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // The Sentinel palette, fixed.
        //
        // Colour carries meaning and nothing else carries it:
        //   red     critical / urgent
        //   amber   warning / upcoming
        //   green   success / insight / healthy
        //   blue    information
        //   purple  Sentinel itself - intelligence and the primary action
        //
        // The rule that keeps this readable is that ordinary text is never
        // coloured. If something is purple it is Sentinel acting or thinking;
        // if it is red it is genuinely critical. The moment purple leaks onto
        // headings and body copy the whole scheme stops meaning anything.
        ground: "#080A0D",
        surface: "#111418",
        "surface-2": "#171B21",
        // One step above elevated, for menus and selected rows - derived from
        // the ramp rather than invented, so the steps stay even.
        "surface-3": "#1E242C",
        border: "#1F2937",
        "border-strong": "#33415A",

        // Hairline rules: structure, not edges. Deliberately dimmer than
        // `border` - at border strength a full-page grid reads as a table.
        rule: "#161B22",
        "rule-strong": "#1F2937",

        ink: "#E5E7EB",
        "ink-dim": "#9CA3AF",
        "ink-faint": "#6B7280",

        // Purple is Sentinel. It fills the one primary action on a screen and
        // marks intelligence output (reasoning, memory, recommendations) -
        // never a status, because the four status hues below own that job.
        accent: "#6366F1",
        "accent-hover": "#7C3AED",
        "accent-text": "#818CF8", // legible purple on dark, for text/links
        "accent-ink": "#FFFFFF", // text on top of an accent fill
        brand: "#6366F1",
        "brand-bright": "#7C3AED",

        // Context identity: which "world" the user is in. Used at low opacity
        // on badges and borders, always paired with an icon and a word - see
        // components/context.ts - so colour alone never carries the meaning.
        "ctx-personal": "#3B82F6",
        "ctx-org": "#6366F1",
        "ctx-class": "#F59E0B",

        crit: "#EF4444",
        high: "#F97316",
        warn: "#F59E0B",
        good: "#10B981",
        // Information. Previously a periwinkle that sat a hair from the
        // purple; now unambiguously the palette's blue.
        watch: "#3B82F6",
        info: "#3B82F6",
      },
      fontFamily: {
        // One family for everything - hierarchy comes from size and weight
        // contrast, not a second typeface.
        sans: [
          "Inter",
          "-apple-system",
          "BlinkMacSystemFont",
          "SF Pro Display",
          "Segoe UI",
          "Helvetica Neue",
          "Arial",
          "sans-serif",
        ],
        // Kept as a distinct stack now: numeric/identifier labels genuinely
        // read better monospaced, and aliasing it to sans erased that
        // distinction everywhere it was deliberately applied.
        mono: ["ui-monospace", "SFMono-Regular", "SF Mono", "Menlo", "Consolas", "monospace"],
      },
      fontSize: {
        // The spec's scale: metadata 12, secondary 13, body 14, section
        // heading 14-16, page heading 24-28. The previous ramp topped out at
        // a 36px h1, which is why every page opened with a headline louder
        // than anything under it.
        micro: ["12px", { lineHeight: "1.45", letterSpacing: "0.01em" }],
        caption: ["13px", { lineHeight: "1.5" }],
        small: ["14px", { lineHeight: "1.55" }],
        body: ["15px", { lineHeight: "1.6" }],
        lead: ["16px", { lineHeight: "1.55" }],
        sub: ["18px", { lineHeight: "1.5" }],
        title: ["clamp(16px, 1.8vw, 18px)", { lineHeight: "1.4", letterSpacing: "-0.01em" }],
        h3: ["clamp(17px, 2.2vw, 20px)", { lineHeight: "1.35", letterSpacing: "-0.015em" }],
        h2: ["clamp(19px, 2.8vw, 24px)", { lineHeight: "1.3", letterSpacing: "-0.02em" }],
        h1: ["clamp(22px, 3.4vw, 28px)", { lineHeight: "1.2", letterSpacing: "-0.02em" }],
      },
      borderRadius: {
        // Near-square, verified against the rendered reference side by side
        // with the app's own first screenshot: its cards, inputs and code
        // panels all sit around 3-4px. The earlier 10px cards were the most
        // visible difference between the two.
        sm: "6px",
        DEFAULT: "8px",
        md: "8px",
        lg: "12px",
        xl: "16px",
      },
      boxShadow: {
        // The reference is completely flat - separation comes from the
        // border alone, never from elevation. Every surface token is
        // therefore none; only true overlays (modals, floating menus) keep
        // a drop shadow, since they genuinely sit above the page.
        card: "none",
        raised: "none",
        pill: "none",
        "accent-glow": "none",
        overlay: "0 24px 60px -12px rgba(0,0,0,0.9)",
      },
      transitionTimingFunction: {
        out: "cubic-bezier(0.22, 1, 0.36, 1)",
      },
    },
  },
  plugins: [],
} satisfies Config;
