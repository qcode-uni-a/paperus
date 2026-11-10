import { defineConfig, devices } from '@playwright/test';
import base from './playwright.config.ts';
import { ADMIN_STATE } from './tests/helpers.ts';

/** The homepage's screenshots (site/screenshots/), from a fresh paperus
 * with the demo's library (demo/seed.ts): `npm run screenshots`. */

export default defineConfig({
	...base,
	testDir: '.',
	projects: [
		{ name: 'setup', testMatch: /tests\/setup\.ts$/, use: devices['Desktop Chrome'] },
		{
			name: 'screenshots',
			dependencies: ['setup'],
			testMatch: /screenshots\/.*\.ts$/,
			use: {
				...devices['Desktop Chrome'],
				storageState: ADMIN_STATE,
				viewport: { width: 1440, height: 900 },
				deviceScaleFactor: 2,
				colorScheme: 'light'
			}
		}
	]
});
