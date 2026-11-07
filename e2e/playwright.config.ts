import { defineConfig, devices } from '@playwright/test';
import { ADMIN_STATE } from './tests/helpers.ts';

/** End-to-end tests: a real browser against a real paperus (API serving the
 * built website, worker, fresh database `paperus_e2e`); see README.md. */

const port = Number(process.env.PAPERUS_E2E_PORT ?? 8100);
const baseURL = `http://127.0.0.1:${port}`;

export default defineConfig({
	testDir: 'tests',
	outputDir: 'test-results',
	timeout: 30_000,
	expect: { timeout: 10_000 },
	forbidOnly: !!process.env.CI,
	retries: 0,
	workers: process.env.CI ? 2 : 4,
	reporter: process.env.CI ? [['list'], ['html', { open: 'never' }]] : [['list']],
	use: {
		baseURL,
		trace: 'retain-on-failure',
		screenshot: 'only-on-failure'
	},
	projects: [
		// The first run: creates the administrator, whose login the others use.
		{ name: 'setup', testMatch: /setup\.ts$/ },
		{
			name: 'chromium',
			dependencies: ['setup'],
			testIgnore: [/setup\.ts$/, /sharing\.spec\.ts$/],
			use: { ...devices['Desktop Chrome'], storageState: ADMIN_STATE }
		},
		// Last: once the administrator is in a group, dialogs ask whose
		// things to use, which the tests above don't expect.
		{
			name: 'sharing',
			dependencies: ['chromium'],
			testMatch: /sharing\.spec\.ts$/,
			use: { ...devices['Desktop Chrome'], storageState: ADMIN_STATE }
		}
	],
	webServer: {
		command: 'bash scripts/serve.sh',
		url: `${baseURL}/api/health`,
		// Never someone else's server on this port (e.g. a dev server).
		reuseExistingServer: false,
		timeout: 180_000,
		gracefulShutdown: { signal: 'SIGTERM', timeout: 15_000 },
		// The API's and worker's own logs are in server-logs/.
		stdout: 'pipe',
		stderr: 'pipe',
		env: { PAPERUS_E2E_PORT: String(port) }
	}
});
