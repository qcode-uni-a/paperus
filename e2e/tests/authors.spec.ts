import { expect, test, type Page } from '@playwright/test';
import { unique } from './helpers.ts';

type Name = { family: string; given: string };

async function add(page: Page, title: string, authors: Name[]): Promise<string> {
	const added = await page.request.post('/api/items', {
		data: { metadata: { title, author: authors } }
	});
	expect(added.status()).toBe(201);
	return (await added.json()).id;
}

/** Link authors now (the job runs every 5 minutes by itself), and wait for
 * the paper's authors to be people. */
async function linked(page: Page, id: string): Promise<void> {
	expect((await page.request.post('/api/admin/jobs/authors')).status()).toBe(202);
	await expect
		.poll(async () => (await (await page.request.get(`/api/items/${id}`)).json()).author_ids, {
			timeout: 20_000
		})
		.not.toBeNull();
}

test('authors as people: their page, split, to check, merge', async ({ page }) => {
	const family = unique('Benito');
	const benito = { family, given: 'Mónica' };
	const platero = { family: unique('Platero'), given: 'Gloria' };
	const smith = { family: unique('Smith'), given: 'Jane' };
	const word = unique('Authored ');
	await add(page, `${word} qubits`, [benito, platero]);
	await add(page, `${word} dots`, [benito, platero]);
	const proteins = await add(page, `${word} proteins`, [benito, smith]);
	await linked(page, proteins);

	// From a paper to its author's page.
	await page.goto(`/items/${proteins}`);
	await page.getByRole('link', { name: `Mónica ${family}` }).click();
	await expect(page.getByRole('heading', { level: 1, name: `Mónica ${family}` })).toBeVisible();
	await expect(page.getByText('3 papers in your library')).toBeVisible();
	await expect(
		page.getByRole('link', { name: new RegExp(`Gloria ${platero.family}`) })
	).toBeVisible();
	const physicist = page.url();

	// The protein paper is by another Mónica Benito: split it off.
	await page.getByRole('button', { name: 'Some are by someone else' }).click();
	await page
		.getByRole('listitem')
		.filter({ hasText: `${word} proteins` })
		.getByLabel('By someone else')
		.check();
	await page.getByRole('button', { name: /^Move 1 paper to another/ }).click();
	await expect(page.getByText(/1 paper moved to another/)).toBeVisible();
	await expect(page.getByText('2 papers in your library')).toBeVisible();
	await expect(page.getByRole('heading', { name: `Others named Mónica ${family}` })).toBeVisible();

	// A new paper by that name alone: which one is it? To check.
	const alone = await add(page, `${word} alone`, [benito]);
	expect((await page.request.post('/api/admin/jobs/authors')).status()).toBe(202);
	await page.goto('/manage/authors');
	const entry = page.getByRole('listitem').filter({ hasText: `${word} alone` });
	await expect(entry).toBeVisible({ timeout: 20_000 });
	await entry.getByRole('button', { name: /: 2 papers$/ }).click();
	await expect(entry).toBeHidden();
	expect((await (await page.request.get(`/api/items/${alone}`)).json()).author_ids[0]).toBe(
		physicist.split('/').pop()
	);

	// Found under Manage → Authors; and merged again after all.
	await page.getByRole('searchbox', { name: 'Find an author' }).fill(family);
	await expect(page.getByRole('link', { name: `Mónica ${family}` })).toHaveCount(2);
	await page.goto(physicist);
	page.once('dialog', (dialog) => dialog.accept());
	await page.getByRole('button', { name: 'The same person' }).click();
	await expect(page.getByText('4 papers in your library')).toBeVisible();

	// On a phone: nothing wider than the screen.
	await page.setViewportSize({ width: 360, height: 740 });
	await page.reload();
	await expect(page.getByText('4 papers in your library')).toBeVisible();
	const widths = await page.evaluate(() => ({
		scroll: document.documentElement.scrollWidth,
		client: document.documentElement.clientWidth
	}));
	expect(widths.scroll).toBeLessThanOrEqual(widths.client);
});
