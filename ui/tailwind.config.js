/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      // Custom colors that match the design system specified in the plan:
      // - page background: gray-950
      // - card/surface: gray-900 with gray-800 border
      // - interactive/accent: cyan-400
      // These are already in Tailwind's default palette; we add here for reference.
    },
  },
  // Runbook tab renders markdown via react-markdown and leans on
  // @tailwindcss/typography's `prose` classes for readable
  plugins: [require("@tailwindcss/typography")],
};
