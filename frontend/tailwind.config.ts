import type { Config } from "tailwindcss";

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // Dark, near-monochrome system: color is reserved almost entirely
        // for severity, so hierarchy has to come from surface elevation and
        // ink contrast instead.
        //
        // The surfaces step in even, perceptible increments. Previously
        // `surface` and `surface-2` sat close enough together that a card on
        // a panel read as one flat plane, which is why the UI felt airless
        // regardless of spacing.
        ground: "#08080A",
        surface: "#111114",
        "surface-2": "#191920",
        "surface-3": "#22222B",
        border: "#2C2C36",
        "border-strong": "#3D3D4A",

        // Ink ramp, contrast-checked against `ground`:
        //   ink        ~17:1   body and headings
        //   ink-dim    ~8.9:1  secondary text
        //   ink-faint  ~5.3:1  labels and metadata
        // ink-faint was #6B6B6B (~3.6:1), which fails WCAG AA for the 11-13px
        // text it was mostly used on. Small text is exactly where contrast
        // matters most, so it moved up rather than the sizes moving down.
        ink: "#F4F4F6",
        "ink-dim": "#AFAFBA",
        "ink-faint": "#8A8A98",

        // Near-monochrome. Both x.ai and Resend drive emphasis with a white
        // pill CTA and keep hue for *status* only (Opened / Bounced /
        // Delivered) - which is what crit/warn/watch/good below already are.
        // An accent hue competing with those would make severity ambiguous,
        // so "accent" here is simply light ink.
        accent: "#EDEDF2",
        "accent-hover": "#FFFFFF",
        "accent-text": "#EDEDF2",
        "accent-ink": "#08080A", // text on top of an accent fill

        // Hairline rules used to draw the editorial grid. Deliberately
        // dimmer than `border`: these are structure, not edges, and at
        // `border` strength a full-page grid reads as a table.
        rule: "#17171C",
        "rule-strong": "#22222A",

        crit: "#F0736A",
        warn: "#E8B25E",
        watch: "#7FA3E0",
        good: "#5FBF87",
      },
      fontFamily: {
        // One family for everything - hierarchy comes from size and weight
        // contrast, not a second typeface.
        sans: [
          "-apple-system",
          "BlinkMacSystemFont",
          "Inter",
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
        // A named scale, so sizes stop being invented per component.
        //
        // Every step moved up: the app's most common body size was 12.5px
        // with 10.5px labels, which is below comfortable reading size on a
        // normal monitor. Body is now 15px and the smallest label is 12px.
        // Line heights are bundled in - they were being omitted at call
        // sites, leaving small text cramped.
        // The two smallest steps carry most of the UI (labels, metadata,
        // list rows), so they were raised again after the first pass: at
        // 12/13px the bulk of the interface was still small even though the
        // scale itself looked reasonable in isolation. Nothing is below
        // 12.5px now, and ordinary body copy is 15.5px.
        micro: ["12.5px", { lineHeight: "1.45", letterSpacing: "0.01em" }],
        caption: ["13.5px", { lineHeight: "1.5" }],
        small: ["14.5px", { lineHeight: "1.55" }],
        body: ["15.5px", { lineHeight: "1.6" }],
        lead: ["17px", { lineHeight: "1.55" }],
        sub: ["18px", { lineHeight: "1.5" }],
        // Display sizes are fluid. A fixed 36px h1 is right on a laptop and
        // overwhelming on a 360px phone, and clamping here makes every
        // heading in the app responsive without a single `md:` prefix at a
        // call site. Body sizes stay fixed - they're already at a
        // comfortable reading size and shrinking them on mobile would undo
        // the point of the scale.
        title: ["clamp(18px, 2.2vw, 20px)", { lineHeight: "1.4", letterSpacing: "-0.01em" }],
        h3: ["clamp(20px, 3.2vw, 24px)", { lineHeight: "1.35", letterSpacing: "-0.015em" }],
        h2: ["clamp(23px, 4.2vw, 29px)", { lineHeight: "1.25", letterSpacing: "-0.02em" }],
        h1: ["clamp(28px, 5.6vw, 36px)", { lineHeight: "1.15", letterSpacing: "-0.025em" }],
      },
      borderRadius: {
        // Softened from a near-flat 2px. At 2px every card, input and button
        // read as an unfinished box; these values are still restrained but
        // let surfaces look intentional.
        sm: "6px",
        DEFAULT: "8px",
        md: "10px",
        lg: "14px",
        xl: "18px",
      },
      boxShadow: {
        // Depth on a near-black ground can't come from dark shadows - they
        // are invisible. Elevation is a hairline top highlight plus a soft
        // ambient shadow, which is what actually separates a card from the
        // panel behind it here.
        card: "0 1px 0 0 rgba(255,255,255,0.04) inset, 0 2px 8px -2px rgba(0,0,0,0.6)",
        raised: "0 1px 0 0 rgba(255,255,255,0.06) inset, 0 8px 24px -8px rgba(0,0,0,0.75)",
        overlay: "0 24px 60px -12px rgba(0,0,0,0.85)",
        // The primary CTA in the reference is a light pill that looks
        // physically raised off the black ground.
        pill: "0 1px 0 0 rgba(255,255,255,0.5) inset, 0 4px 14px -4px rgba(0,0,0,0.9)",
        "accent-glow": "0 0 0 1px rgba(237,237,242,0.16), 0 6px 20px -6px rgba(0,0,0,0.6)",
      },
      transitionTimingFunction: {
        out: "cubic-bezier(0.22, 1, 0.36, 1)",
      },
    },
  },
  plugins: [],
} satisfies Config;
