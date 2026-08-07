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

      // Three-tier type system (see index.css for the full rationale):
      //   sans (default)    — Inter. Everything you read or act on: nav,
      //                       buttons, labels, form fields, body copy.
      //   mono (default)    — Geist Mono. Everything the *system* is
      //                       saying: ids, slugs, timestamps, ARNs, JSON,
      //                       cost figures, the nav wordmark. Most of the
      //                       app already used `font-mono` for exactly
      //                       this content, so overriding the mono stack
      //                       here does most of the rollout for free.
      //   display (new)     — Geist Sans. Reserved deliberately narrowly:
      //                       page-level <h1> titles and the login
      //                       screen's wordmark only. Nothing else uses
      //                       it — that restraint is what makes it read
      //                       as a considered choice instead of a third
      //                       font competing for attention.
      fontFamily: {
        sans: [
          "Inter Variable",
          "Inter",
          "ui-sans-serif",
          "system-ui",
          "sans-serif",
        ],
        mono: [
          "Geist Mono Variable",
          "Geist Mono",
          "ui-monospace",
          "SFMono-Regular",
          "Menlo",
          "monospace",
        ],
        display: [
          "Geist Variable",
          "Geist",
          "Inter Variable",
          "ui-sans-serif",
          "sans-serif",
        ],
      },
    },
  },
  // NOTE: the Runbook tab renders markdown via react-markdown
  // and leans on @tailwindcss/typography's `prose` classes for readable
  // headings/tables/code blocks instead of hand-styling every markdown
  // element. Flagged here since it wasn't in the original stack list.
  plugins: [require("@tailwindcss/typography")],
};
