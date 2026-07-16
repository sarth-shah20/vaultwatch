/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  theme: {
    extend: {
      fontFamily: {
        display: ['"Fraunces"', "Georgia", "serif"],
        sans: ['"Instrument Sans"', "system-ui", "-apple-system", "sans-serif"],
        mono: ['"JetBrains Mono"', "ui-monospace", "monospace"],
      },
      colors: {
        // Single restrained accent: deep marine navy.
        vault: {
          50: "#f4f7fa",
          100: "#e6edf4",
          200: "#c7d7e6",
          500: "#33628c",
          600: "#24507a",
          700: "#1a4066",
          800: "#12324f",
          900: "#0c2439",
          950: "#081a2b",
        },
        // Domain identities (subtle tints, not competing brights).
        ps1: { tint: "#f5f2fb", edge: "#ddd2f0", ink: "#5b4a8a", deep: "#43356b" },
        ps2: { tint: "#eff8f7", edge: "#cfe8e5", ink: "#20706b", deep: "#175450" },
      },
      boxShadow: {
        card: "0 1px 2px rgba(12,36,57,0.06), 0 4px 16px rgba(12,36,57,0.05)",
        lift: "0 2px 4px rgba(12,36,57,0.08), 0 12px 32px rgba(12,36,57,0.10)",
      },
      keyframes: {
        rise: {
          "0%": { opacity: "0", transform: "translateY(8px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
        fadein: { "0%": { opacity: "0" }, "100%": { opacity: "1" } },
        pulseDot: {
          "0%, 100%": { opacity: "1" },
          "50%": { opacity: "0.35" },
        },
      },
      animation: {
        rise: "rise 0.45s cubic-bezier(0.22,1,0.36,1) both",
        fadein: "fadein 0.35s ease-out both",
        pulseDot: "pulseDot 2.4s ease-in-out infinite",
      },
    },
  },
  plugins: [],
};
