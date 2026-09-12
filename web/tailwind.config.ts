import type { Config } from "tailwindcss";

const config: Config = {
  darkMode: "class",
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
  ],
  theme: {
    extend: {
      // Claude-inspired color tokens
      colors: {
        // Backgrounds (mirroring Claude's zinc/slate dark palette)
        bg: {
          primary:   "#1a1a1a",   // main canvas
          secondary: "#262626",   // sidebar / panel
          tertiary:  "#303030",   // input / cards
          hover:     "#3a3a3a",
        },
        // Text
        text: {
          primary:   "#ececec",
          secondary: "#a3a3a3",
          muted:     "#737373",
        },
        // Brand accent (white)
        brand: {
          DEFAULT:   "#ffffff",
          light:     "#e5e5e5",
          dark:      "#a3a3a3",
        },
        // Borders
        border: {
          DEFAULT:   "#404040",
          subtle:    "#303030",
        },
        // User / assistant message bubbles
        bubble: {
          user:      "#2a2a2a",
          assistant: "transparent",
        },
      },
      fontFamily: {
        sans: ["var(--font-geist-sans)", "system-ui", "sans-serif"],
        mono: ["var(--font-geist-mono)", "monospace"],
      },
      fontWeight: {
        semibold: "800",
      },
      animation: {
        "cursor-blink": "cursor-blink 1s step-end infinite",
        "fade-in": "fade-in 0.2s ease-out",
        "slide-up": "slide-up 0.25s ease-out",
      },
      keyframes: {
        "cursor-blink": {
          "0%, 100%": { opacity: "1" },
          "50%": { opacity: "0" },
        },
        "fade-in": {
          from: { opacity: "0" },
          to: { opacity: "1" },
        },
        "slide-up": {
          from: { opacity: "0", transform: "translateY(8px)" },
          to: { opacity: "1", transform: "translateY(0)" },
        },
      },
    },
  },
  plugins: [],
};

export default config;
