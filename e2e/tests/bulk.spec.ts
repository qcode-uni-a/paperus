import { expect, test } from '@playwright/test';
import { unique } from './helpers.ts';

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
	await page.getByRole('checkbox', { name: `Select “${word} two”` }).click({ modifiers: ['Shift'] });
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
