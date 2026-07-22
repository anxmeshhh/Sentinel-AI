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
        // True black, neutral grays. The previous ramp carried a slight
        // blue-violet cast (#08080A / #2C2C36) that read "warm dark theme";
        // the reference is pure #000 with untinted gray borders, and the
        // difference is visible the moment the two sit side by side.
        ground: "#000000",
        surface: "#0A0A0A",
        "surface-2": "#141414",
        "surface-3": "#1E1E1E",
        border: "#2E2E2E",
        "border-strong": "#454545",

        // Ink ramp, contrast-checked against `ground`:
        //   ink        ~17:1   body and headings
        //   ink-dim    ~8.9:1  secondary text
        //   ink-faint  ~5.3:1  labels and metadata
        // ink-faint was #6B6B6B (~3.6:1), which fails WCAG AA for the 11-13px
        // text it was mostly used on. Small text is exactly where contrast
        // matters most, so it moved up rather than the sizes moving down.
        ink: "#F5F5F5",
        "ink-dim": "#B0B0B0",
        "ink-faint": "#8C8C8C",

        // Near-monochrome. Both x.ai and Resend drive emphasis with a white
        // pill CTA and keep hue for *status* only (Opened / Bounced /
        // Delivered) - which is what crit/warn/watch/good below already are.
        // An accent hue competing with those would make severity ambiguous,
        // so "accent" here is simply light ink.
        accent: "#EDEDED",
        "accent-hover": "#FFFFFF",
        "accent-text": "#EDEDED",
        "accent-ink": "#000000", // text on top of an accent fill

        // The one warm note, from the Hyperstudio reference: a desaturated
        // tan used as *punctuation* - eyebrow labels, the active-position
        // bar, the featured-panel tint - never as a fill on controls and
        // never competing with the severity hues. The restraint is the
        // point: the moment this shows up on buttons or headings the whole
        // surface stops being monochrome and starts being "a theme".
        brand: "#C9A06B",
        "brand-bright": "#DDB584",

        // Context identity: which "world" the user is currently in. Three
        // tones only, used at low opacity for glows/borders/badges - never
        // as a page fill, so Sentinel stays one product rather than three
        // themes. Always paired with an icon and a word (see
        // components/context.ts): colour alone must never carry the meaning.
        // ctx-personal is deliberately cyan-leaning rather than the obvious
        // periwinkle: that would have been the exact hex as `watch`, the
        // "Syncing" status colour, making "private context" and "still
        // syncing" indistinguishable wherever they appeared together.
        "ctx-personal": "#6FC3E8", // cool cyan-blue - private to you
        "ctx-org": "#9A8FE6", // indigo         - shared workspace
        "ctx-class": "#C9A06B", // warm amber     - shared class

        // Hairline rules used to draw the editorial grid. Deliberately
        // dimmer than `border`: these are structure, not edges, and at
        // `border` strength a full-page grid reads as a table.
        rule: "#1A1A1A",
        "rule-strong": "#242424",

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
        // Near-square, verified against the rendered reference side by side
        // with the app's own first screenshot: its cards, inputs and code
        // panels all sit around 3-4px. The earlier 10px cards were the most
        // visible difference between the two.
        sm: "3px",
        DEFAULT: "4px",
        md: "4px",
        lg: "6px",
        xl: "8px",
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
