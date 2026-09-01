import { fileURLToPath } from "node:url";

import react from "@vitejs/plugin-react";
import { defineConfig, type Plugin } from "vite";

/**
 * Builds the landing page on its own, into ../deploy, as a folder that can be
 * dragged straight onto Netlify.
 *
 * Separate from vite.config.ts on purpose: the application build is unchanged
 * and still produces the full SPA. This one has a different entry (no auth
 * providers, no router), a different HTML head (real title and description
 * rather than the app shell's) and aliases react-router-dom to a shim, since
 * a single static page has no routes for its links to reach.
 */
const path = (rel: string) => fileURLToPath(new URL(rel, import.meta.url));

/**
 * Rollup names the HTML output after its input, so the entry lands as
 * landing.html. Netlify serves a folder from index.html, and renaming after
 * the fact would be a build step nobody remembers to run.
 */
function netlifyFolder(): Plugin {
  return {
    name: "netlify-folder",
    enforce: "post",
    generateBundle(_options, bundle) {
      const html = bundle["landing.html"];
      if (html) {
        delete bundle["landing.html"];
        html.fileName = "index.html";
        bundle["index.html"] = html;
      }

      // One page, so every path resolves to it rather than to Netlify's
      // 404 - a stale /welcome link should still land somewhere real.
      this.emitFile({
        type: "asset",
        fileName: "_redirects",
        source: "/*  /index.html  200\n",
      });
    },
  };
}

export default defineConfig({
  plugins: [react(), netlifyFolder()],
  resolve: {
    alias: [{ find: /^react-router-dom$/, replacement: path("./deploy-src/router-shim.tsx") }],
  },
  build: {
    outDir: path("../deploy"),
    emptyOutDir: true,
    rollupOptions: { input: path("./landing.html") },
  },
});
