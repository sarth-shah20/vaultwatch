/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  theme: {
    extend: {
      fontFamily: {
        sans: ['"Inter Variable"', "Inter", "system-ui", "-apple-system", "Segoe UI", "sans-serif"],
        mono: ['"JetBrains Mono"', "ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
      },
      colors: {
        // Deep ink ground — blue-black, not neutral grey, so the two domain
        // hues read as light sources against it.
        ink: {
          950: "#080B10",
          900: "#0B0F14",
          850: "#10151C",
          800: "#151C25",
          700: "#1E2833",
          600: "#2A3644",
          500: "#3A4757",
        },
        chalk: {
          DEFAULT: "#E7ECF3",
          dim: "#95A2B3",
          faint: "#5D6B7D",
        },
        // PS1 = human behaviour -> warm. PS2 = money/machine -> cool.
        // Deliberately opposite temperatures, so their convergence reads as
        // two genuinely different things meeting.
        ps1: { DEFAULT: "#E8A33D", soft: "#F0C177", deep: "#8A5A15", ghost: "#2A2116" },
        ps2: { DEFAULT: "#3DC5E8", soft: "#7ADCF3", deep: "#12626F", ghost: "#12242A" },
        alert: { DEFAULT: "#E5484D", soft: "#F27579", deep: "#7A1D22", ghost: "#2A1416" },
        good: "#3DD68C",
      },
      fontSize: {
        micro: ["12px", { lineHeight: "1.35", letterSpacing: "0.08em" }],
        tiny: ["13.5px", { lineHeight: "1.45", letterSpacing: "0.03em" }],
        xs: ["13.5px", { lineHeight: "1.5" }],
        sm: ["15px", { lineHeight: "1.55" }],
        base: ["16.5px", { lineHeight: "1.6" }],
      },
      keyframes: {
        riseIn: { "0%": { opacity: 0, transform: "translateY(10px)" }, "100%": { opacity: 1, transform: "none" } },
        fadeIn: { "0%": { opacity: 0 }, "100%": { opacity: 1 } },
        breathe: { "0%,100%": { opacity: 1 }, "50%": { opacity: 0.3 } },
        landing: {
          "0%": { transform: "scale(.3)", opacity: 0 },
          "60%": { transform: "scale(1.3)", opacity: 1 },
          "100%": { transform: "scale(1)", opacity: 1 },
        },
        sweep: { "0%": { transform: "translateX(-100%)" }, "100%": { transform: "translateX(220%)" } },
        growY: { "0%": { transform: "scaleY(0)" }, "100%": { transform: "scaleY(1)" } },
        growX: { "0%": { transform: "scaleX(0)" }, "100%": { transform: "scaleX(1)" } },
        drawIn: { "0%": { strokeDashoffset: "var(--len, 1000)" }, "100%": { strokeDashoffset: "0" } },
      },
      animation: {
        riseIn: "riseIn .5s cubic-bezier(.22,1,.36,1) both",
        fadeIn: "fadeIn .4s ease-out both",
        breathe: "breathe 2.4s ease-in-out infinite",
        landing: "landing .6s cubic-bezier(.34,1.56,.64,1) both",
        sweep: "sweep 1.6s ease-in-out infinite",
        growY: "growY .7s cubic-bezier(.22,1,.36,1) both",
        growX: "growX .7s cubic-bezier(.22,1,.36,1) both",
        drawIn: "drawIn 1s cubic-bezier(.22,1,.36,1) both",
      },
    },
  },
  plugins: [],
};
