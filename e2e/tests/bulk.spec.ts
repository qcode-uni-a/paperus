import { expect, test } from '@playwright/test';
import { LOGGED_OUT, unique } from './helpers.ts';

test('pick papers in a collection, tag them, trash them, undo', async ({ page }) => {
	const word = unique('Picked');
	const tag = unique('batch');
	const shelf = await (
		await page.request.post('/api/collections', { data: { name: unique('Shelf') } })
	).json();
	const ids: string[] = [];
	for (const n of ['one', 'two', 'three']) {
		const added = await page.request.post('/api/items', {
			data: { metadata: { title: `${word} ${n}` } }
		});
		ids.push((await added.json()).id);
	}
	await page.request.post(`/api/collections/${shelf.id}/items`, { data: { item_ids: ids } });

	await page.goto(`/collections/${shelf.id}`);
	await expect(page.getByRole('heading', { name: '3 items' })).toBeVisible();
	await page.getByRole('button', { name: 'Select', exact: true }).click();
	const bar = page.getByRole('toolbar', { name: 'Selected papers' });
	await expect(bar.getByText('0 selected')).toBeVisible();

	// A click on a row picks it while picking; Shift picks the rows between.
	await page.getByRole('link', { name: `${word} three` }).click();
	await expect(page).toHaveURL(new RegExp(`/collections/${shelf.id}$`));
	await page
		.getByRole('checkbox', { name: `Select “${word} two”` })
		.click({ modifiers: ['Shift'] });
	await expect(bar.getByText('2 selected')).toBeVisible();

	await bar.getByRole('button', { name: 'Tag' }).click();
	await page.getByLabel('Add a tag').fill(tag);
	await page.getByLabel('Add a tag').press('Enter');
	await expect(bar.getByRole('status')).toHaveText(`Tagged 2 papers “${tag}”.`);
	await expect(page.getByRole('listitem').filter({ hasText: tag })).toHaveCount(2);

	await bar.getByRole('button', { name: 'Trash' }).click();
	await expect(bar.getByRole('status')).toContainText('2 papers in the trash.');
	await expect(page.getByRole('heading', { name: '1 item' })).toBeVisible();
	await bar.getByRole('button', { name: 'Undo' }).click();
	await expect(bar.getByRole('status')).toHaveText('2 papers back from the trash.');
	await expect(page.getByRole('heading', { name: '3 items' })).toBeVisible();

	// Esc lets go.
	await page.keyboard.press('Escape');
	await expect(bar).toBeHidden();
});

test('select all: every paper of the collection, also those not loaded yet', async ({
	page,
	browser
}) => {
	// A person of their own: the other tests' lists keep their few papers.
	const kim = { username: unique('kim'), password: 'kim-password-e2e' };
	expect((await page.request.post('/api/admin/users', { data: kim })).status()).toBe(201);
	const context = await browser.newContext({ storageState: LOGGED_OUT });
	const own = await context.newPage();
	await own.goto('/login');
	await own.getByLabel('Username').fill(kim.username);
	await own.getByLabel('Password').fill(kim.password);
	await own.getByRole('button', { name: 'Log in' }).click();
	await expect(own).toHaveURL(/\/$/);

	const word = unique('Many');
	const tag = unique('all');
	const shelf = await (
		await own.request.post('/api/collections', { data: { name: unique('Shelf') } })
	).json();
	// More than the list loads at first (50).
	const ids: string[] = [];
	for (let n = 0; n < 60; n++) {
		const added = await own.request.post('/api/items', {
			data: { metadata: { title: `${word} ${n}` } }
		});
		ids.push((await added.json()).id);
	}
	await own.request.post(`/api/collections/${shelf.id}/items`, { data: { item_ids: ids } });

	await own.goto(`/collections/${shelf.id}`);
	await expect(own.getByRole('heading', { name: '60 items' })).toBeVisible();
	await own.getByRole('button', { name: 'Select', exact: true }).click();
	const bar = own.getByRole('toolbar', { name: 'Selected papers' });
	await bar.getByRole('button', { name: 'Select all 60' }).click();
	await expect(bar.getByText('60 selected')).toBeVisible();

	await bar.getByRole('button', { name: 'Tag' }).click();
	await own.getByLabel('Add a tag').fill(tag);
	await own.getByLabel('Add a tag').press('Enter');
	await expect(bar.getByRole('status')).toHaveText(`Tagged 60 papers “${tag}”.`);
	const tags = await (await own.request.get('/api/tags')).json();
	const made = tags.find((t: { name: string }) => t.name === tag);
	const tagged = await own.request.get(`/api/items?tag=${made.id}&limit=1`);
	expect(tagged.headers()['x-total-count']).toBe('60');

	// Unticking one: back to picking by hand, the rows shown.
	await own.getByRole('checkbox', { name: `Select “${word} 59”` }).click();
	await expect(bar.getByText(/^\d+ selected$/)).not.toHaveText('60 selected');
	await expect(bar.getByRole('button', { name: 'Select all 60' })).toBeVisible();
	await context.close();
});
