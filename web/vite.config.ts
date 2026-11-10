import adapter from '@sveltejs/adapter-static';
import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vite';

// The build's settings for the demo (scripts/demo.sh in e2e/); Node's
// process, without its types here.
const env =
	(globalThis as { process?: { env: Record<string, string | undefined> } }).process?.env ?? {};
const demoBase = env.PAPERUS_WEB_BASE as `/${string}` | undefined;

export default defineConfig({
	plugins: [
		sveltekit({
			compilerOptions: {
				// Force runes mode for the project, except for libraries. Can be removed in svelte 6.
				runes: ({ filename }) =>
					filename.split(/[/\\]/).includes('node_modules') ? undefined : true
			},
			// A static single-page app, served by the paperus server (see
			// server/src/paperus/web.py); 200.html is the entry for every route.
			// The demo (web/demo/) builds it once more, below the homepage's
			// path, into a folder of its own.
			adapter: adapter({
				pages: env.PAPERUS_WEB_OUT ?? 'build',
				fallback: '200.html',
				precompress: !env.PAPERUS_WEB_OUT
			}),
			// Absolute asset paths there: GitHub Pages serves the entry as 404.html
			// at any depth.
			paths: demoBase ? { base: demoBase, relative: false } : undefined
		})
	],
	server: {
		// `paperus serve` runs on port 8000 during development. Keep the
		// browser's Host header, so links the server builds (e.g. for AI
		// assistants) point at this address, not at port 8000.
		proxy: {
			'/api': { target: 'http://127.0.0.1:8000', changeOrigin: false },
			'/mcp': { target: 'http://127.0.0.1:8000', changeOrigin: false }
		}
	}
});
