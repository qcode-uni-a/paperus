import adapter from '@sveltejs/adapter-static';
import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vite';

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
			adapter: adapter({ fallback: '200.html', precompress: true })
		})
	],
	server: {
		// `paperus serve` runs on port 8000 during development.
		proxy: { '/api': 'http://127.0.0.1:8000' }
	}
});
