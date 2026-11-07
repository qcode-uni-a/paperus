import { expect, test, type Page } from '@playwright/test';
import { unique } from './helpers.ts';

/** The installation's date format, set through the API (to put it back
 * whatever happened in the test: the tests share one server). */
async function setDateFormat(page: Page, format: string): Promise<void> {
	const config = await (await page.request.get('/api/admin/config')).json();
	const saved = await page.request.put('/api/admin/config', {
		data: { ...config, date_format: format }
	});
	expect(saved.status()).toBe(200);
}

/** "07.11.2026" for a day from now (in this computer's time zone, as the
 * browser's). */
function european(daysFromNow: number): string {
	const day = new Date(Date.now() + daysFromNow * 24 * 3600 * 1000);
	const pad = (n: number) => String(n).padStart(2, '0');
	return `${pad(day.getDate())}.${pad(day.getMonth() + 1)}.${day.getFullYear()}`;
}

test('dates in the European form, typed and shown', async ({ page }) => {
	try {
		// The saved settings first (they would reset a choice made before).
		const loaded = page.waitForResponse((r) => r.url().endsWith('/api/admin/config'));
		await page.goto('/admin/settings?open=server');
		await loaded;
		await page.getByRole('radio', { name: /^Europe/ }).check();
		await expect(page.getByRole('button', { name: 'Save' })).toBeEnabled();
		await page.getByRole('button', { name: 'Save' }).click();
		await expect(page.getByText('Server settings saved')).toBeVisible();

		// Times of day in 24 hours.
		await page.goto('/admin/backups');
		const hours = page.getByLabel('At').locator('option');
		await expect(hours).toHaveCount(24);
		for (const hour of await hours.allTextContents()) expect(hour).toMatch(/^\d{2}:\d{2}$/);

		// A smart collection's dates are typed as DD.MM.YYYY.
		const name = unique('Since March ');
		await page.goto('/collections');
		await page
			.getByRole('button', { name: /^(Create the first collection|New collection)$/ })
			.click();
		const dialog = page.getByRole('dialog', { name: 'New collection' });
		await dialog.getByRole('radio', { name: /^Smart/ }).check();
		await dialog.getByLabel('Name').fill(name);
		const from = dialog.getByLabel('from', { exact: true });
		await expect(from).toHaveAttribute('placeholder', 'DD.MM.YYYY');
		await from.fill('31.02.2024');
		await from.blur();
		await expect(dialog.getByText('Not a date; write it as DD.MM.YYYY')).toBeVisible();
		await expect(from).toHaveAttribute('aria-invalid', 'true');
		await from.fill('15.3.2024');
		await from.blur();
		await expect(from).toHaveValue('15.03.2024');
		await expect(dialog.getByText('Not a date')).toBeHidden();
		// Not before the start.
		const to = dialog.getByLabel('to', { exact: true });
		await to.fill('01.01.2020');
		await to.blur();
		await expect(dialog.getByText('Not before 15.03.2024')).toBeVisible();
		await to.fill('');
		await dialog.getByRole('button', { name: 'Create collection' }).click();
		await expect(page).toHaveURL(/\/collections\/[0-9a-f-]+$/);
		await expect(page.getByText('published on 15 March 2024 or later')).toBeVisible();
		page.once('dialog', (confirm) => confirm.accept());
		await page.getByRole('button', { name: 'Collection actions' }).click();
		await page.getByRole('menuitem', { name: 'Delete' }).click();
		await expect(page).toHaveURL(/\/collections$/);

		// A list's dates: when an access token expires.
		const token = unique('Expiring ');
		await page.goto('/settings');
		await page.getByRole('button', { name: 'New token' }).click();
		const create = page.getByRole('dialog', { name: 'New access token' });
		await create.getByLabel('Name').fill(token);
		await create.getByRole('radio', { name: /^AI assistant search and read/ }).check();
		await create.getByLabel('Expires').selectOption({ label: 'In 30 days' });
		await create.getByRole('button', { name: 'Create token' }).click();
		await page
			.getByRole('dialog', { name: 'Token created' })
			.getByRole('button', { name: 'Done' })
			.click();
		const listed = page.getByRole('listitem').filter({ hasText: token });
		await expect(listed).toContainText(`expires ${european(30)}`);
		page.once('dialog', (confirm) => confirm.accept());
		await listed.getByRole('button', { name: 'Revoke' }).click();
		await expect(listed).toBeHidden();
	} finally {
		await setDateFormat(page, 'browser');
	}
});
