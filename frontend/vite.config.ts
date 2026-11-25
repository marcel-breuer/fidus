import adapter from '@sveltejs/adapter-node';
import tailwindcss from '@tailwindcss/vite';
import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vitest/config';

export default defineConfig({
	plugins: [
		tailwindcss(),
		sveltekit({
			adapter: adapter(),
			// Scripts only from this origin (SvelteKit adds nonces for its inline bootstrap script).
			// Inline styles stay allowed because components set style attributes; blob: is the
			// MediaRecorder preview and playback of recorded audio.
			csp: {
				mode: 'auto',
				directives: {
					'default-src': ['self'],
					'script-src': ['self'],
					'style-src': ['self', 'unsafe-inline'],
					'img-src': ['self', 'data:', 'blob:'],
					'media-src': ['self', 'blob:', 'data:'],
					'connect-src': ['self'],
					'font-src': ['self'],
					'object-src': ['none'],
					'base-uri': ['self'],
					'form-action': ['self'],
					'frame-ancestors': ['none']
				}
			}
		})
	],
	server: { proxy: { '/api': 'http://localhost:8000' } },
	test: { include: ['src/**/*.test.ts'], environment: 'node' }
});
