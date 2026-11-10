import { defineConfig, devices } from '@playwright/test';
import base from './playwright.config.ts';

/** Records the demo (demo/README.md) from a fresh paperus:
 * `npm run demo`, which runs scripts/demo.sh. */

export default defineConfig({
	...base,
	testDir: '.',
	projects: [
		{ name: 'setup', testMatch: /tests\/setup\.ts$/, use: devices['Desktop Chrome'] },
		{
			name: 'demo',
			dependencies: ['setup'],
			testMatch: /demo\/record\.ts$/,
			use: { ...devices['Desktop Chrome'], storageState: '.auth/admin.json' }
		}
	]
});
