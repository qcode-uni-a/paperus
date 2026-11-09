import { expect, test } from '@playwright/test';
import { unique } from './helpers.ts';

test('an extension’s report in the administration’s logs', async ({ page }) => {
	const message = unique('No PDF for a paper');
	const sent = await page.request.post('/api/logs', {
		data: {
			version: '0.0.19',
			entries: [{ level: 'warning', message, context: { page: 'https://example.org/paper' } }]
		}
	});
	expect(sent.status()).toBe(204);

	await page.goto('/admin/logs');
	await page.getByLabel('From').selectOption('extension');
	await page.getByLabel('Words').fill(message);
	const entry = page.getByRole('listitem').filter({ hasText: message });
	await expect(entry).toBeVisible();
	await expect(entry).toContainText('https://example.org/paper');
	await expect(entry).toContainText('extension 0.0.19');
});
