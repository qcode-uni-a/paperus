import { expect, test, type Page } from '@playwright/test';
import { LOGGED_OUT, unique } from './helpers.ts';

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
	await page.getByRole('link', { name: `${family}, Mónica` }).click();
	await expect(page.getByRole('heading', { level: 1, name: `${family}, Mónica` })).toBeVisible();
	await expect(page.getByText('3 papers in your library')).toBeVisible();
	await expect(
		page.getByRole('link', { name: new RegExp(`${platero.family}, Gloria`) })
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
	await expect(page.getByRole('heading', { name: `Others named ${family}, Mónica` })).toBeVisible();

	// A new paper by that name alone: which one is it? To check.
	const alone = await add(page, `${word} alone`, [benito]);
	expect((await page.request.post('/api/admin/jobs/authors')).status()).toBe(202);
	// Linked in the background: listed once that has run.
	await expect
		.poll(
			async () =>
				(await (await page.request.get('/api/authors-to-check')).json()).some(
					(e: { item: { id: string } }) => e.item.id === alone
				),
			{ timeout: 20_000 }
		)
		.toBe(true);
	await page.goto('/manage/authors');
	const entry = page.getByRole('listitem').filter({ hasText: `${word} alone` });
	await expect(entry).toBeVisible();
	await entry.getByRole('button', { name: /: 2 papers$/ }).click();
	await expect(entry).toBeHidden();
	expect((await (await page.request.get(`/api/items/${alone}`)).json()).author_ids[0]).toBe(
		physicist.split('/').pop()
	);

	// Found under Manage → Authors; and merged again after all.
	await page.getByRole('searchbox', { name: 'Find an author' }).fill(family);
	await expect(page.getByRole('link', { name: `${family}, Mónica` })).toHaveCount(2);
	await page.goto(physicist);
	await page.getByRole('button', { name: 'The same person' }).click();
	const compare = page.getByRole('dialog', { name: 'The same person?' });
	await compare.getByRole('button', { name: 'The same person' }).click();
	await expect(compare).toBeHidden();
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

	// Each fix is kept, and the merge can be taken back.
	const changes = page.locator('section').filter({ hasText: 'Changed by hand' });
	const merged = changes.getByRole('listitem').filter({ hasText: 'Merged with' });
	await expect(merged).toContainText('by you');
	await expect(
		changes.getByRole('listitem').filter({ hasText: 'Papers moved to another' })
	).toBeVisible();
	await merged.getByRole('button', { name: 'Undo' }).click();
	await expect(page.getByText('3 papers in your library')).toBeVisible();
	await expect(merged).toContainText('undone');
	await expect(merged.getByRole('button', { name: 'Undo' })).toHaveCount(0);
});

test('probably the same person: merged, or kept apart', async ({ page }) => {
	const family = unique('Burkard');
	const coauthor = { family: unique('Pályi'), given: 'András' };
	await add(page, unique('Full name '), [{ family, given: 'Guido' }, coauthor]);
	await add(page, unique('Initial '), [{ family, given: 'G.' }, coauthor]);
	const last = await add(page, unique('Other '), [{ family, given: 'Gerda' }]);
	await linked(page, last);

	await page.goto('/manage/authors');
	// Counted next to Manage → Authors in the menu.
	await expect(page.getByTitle(/pairs? probably the same/)).toBeVisible();
	const section = page.locator('section').filter({ hasText: 'Probably the same' });
	const pair = section.getByRole('listitem').filter({ hasText: `${family}, Guido` });
	await expect(pair).toContainText('1 co-author in common');
	await expect(pair).toContainText(`${family}, G.`);
	// Compared side by side, what both have marked.
	await pair.getByRole('button', { name: 'Compare…' }).click();
	const compare = page.getByRole('dialog', { name: 'The same person?' });
	await expect(compare.getByTitle('Both have this')).toHaveCount(2);
	await expect(compare.getByText('In common (green): 1 co-author.')).toBeVisible();
	await compare.getByRole('button', { name: 'The same person' }).click();
	await expect(page.getByText(`One person now: ${family}, Guido`)).toBeVisible();
	await expect(compare).toBeHidden();
	await expect(pair).toBeHidden();
	// "Gerda" never fits "Guido"; "G." did, but is merged now.
	await expect(section.getByRole('listitem').filter({ hasText: family })).toHaveCount(0);
});

test('a smart collection of an author’s papers', async ({ page }) => {
	const family = unique('Platero');
	const gloria = { family, given: 'Gloria' };
	const word = unique('Collected ');
	const first = await add(page, `${word} one`, [gloria]);
	await add(page, `${word} two`, [{ family: unique('Other'), given: 'O.' }, gloria]);
	await linked(page, first);

	const id = (await (await page.request.get(`/api/items/${first}`)).json()).author_ids[0];
	await page.goto(`/authors/${id}`);
	await page.getByRole('button', { name: 'Smart collection' }).click();
	const dialog = page.getByRole('dialog', { name: 'New collection' });
	await expect(dialog.getByRole('radio', { name: /^Smart/ })).toBeChecked();
	await expect(dialog.getByLabel('Name')).toHaveValue(`${family}, Gloria`);
	await expect(dialog.getByRole('button', { name: `Remove ${family}, Gloria` })).toBeVisible();
	await dialog.getByRole('button', { name: 'Create collection' }).click();
	await page.goto('/collections');
	await page
		.getByRole('link', { name: `${family}, Gloria` })
		.first()
		.click();
	await expect(page.getByText(`Papers by ${family}, Gloria.`)).toBeVisible();
	await expect(page.getByRole('heading', { name: '2 items' })).toBeVisible();
});

test('names written family name first, or as one chooses', async ({ page, browser }) => {
	// A person of their own: the choice is theirs, not the other tests'.
	const eve = { username: unique('eve'), password: 'eve-password-e2e' };
	expect((await page.request.post('/api/admin/users', { data: eve })).status()).toBe(201);
	const context = await browser.newContext({ storageState: LOGGED_OUT });
	const own = await context.newPage();
	await own.goto('/login');
	await own.getByLabel('Username').fill(eve.username);
	await own.getByLabel('Password').fill(eve.password);
	await own.getByRole('button', { name: 'Log in' }).click();
	await expect(own).toHaveURL(/\/$/);

	const family = unique('Loss');
	const id = await add(own, unique('Named '), [{ family, given: 'Daniel' }]);
	await own.goto(`/items/${id}`);
	await expect(own.getByRole('link', { name: `${family}, Daniel` })).toBeVisible();

	await own.goto('/settings');
	await own.getByRole('radio', { name: /Given name first/ }).check();
	await expect(own.getByText('Saved.')).toBeVisible();
	await own.goto(`/items/${id}`);
	await expect(own.getByRole('link', { name: `Daniel ${family}` })).toBeVisible();
	await context.close();
});
