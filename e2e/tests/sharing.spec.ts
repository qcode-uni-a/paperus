import { expect, test, type Browser } from '@playwright/test';
import { itemAction, LOGGED_OUT, unique, uploadPaper } from './helpers.ts';

/** A browser of its own for another person, logged in through the form. */
async function logIn(browser: Browser, username: string, password: string) {
	const context = await browser.newContext({ storageState: LOGGED_OUT });
	const page = await context.newPage();
	await page.goto('/login');
	await page.getByLabel('Username').fill(username);
	await page.getByLabel('Password').fill(password);
	await page.getByRole('button', { name: 'Log in' }).click();
	await expect(page.getByTitle('Account')).toBeVisible();
	return { context, page };
}

test('a paper shared with a group is seen by its members only', async ({ page, browser }) => {
	const bob = { username: unique('bob'), password: 'bob-password-e2e' };
	const carol = { username: unique('carol'), password: 'carol-password-e2e' };
	const groupName = unique('Lab ');

	// The administrator adds two people.
	await page.goto('/admin/users');
	for (const person of [bob, carol]) {
		await page.getByRole('button', { name: 'New user' }).click();
		const dialog = page.getByRole('dialog', { name: 'New user' });
		await dialog.getByLabel('Username').fill(person.username);
		await dialog.getByLabel('Password').fill(person.password);
		await dialog.getByRole('button', { name: 'Create user' }).click();
		await expect(dialog).toBeHidden();
		await expect(page.getByRole('row').filter({ hasText: person.username })).toBeVisible();
	}

	// A group with the administrator and bob, not carol.
	await page.goto('/manage/groups');
	await page.getByRole('button', { name: 'New group' }).click();
	const groupDialog = page.getByRole('dialog', { name: 'New group' });
	await groupDialog.getByLabel('Name').fill(groupName);
	await groupDialog.getByRole('button', { name: 'Create group' }).click();
	await expect(groupDialog).toBeHidden();
	await page.getByRole('navigation', { name: 'Groups' }).getByText(groupName).click();
	const group = page.getByRole('region', { name: groupName });
	await expect(group).toBeVisible();
	await group.getByRole('combobox', { name: 'Person to add' }).fill(bob.username);
	await group.getByRole('combobox', { name: 'Role', exact: true }).selectOption('member');
	await group.getByRole('button', { name: 'Add', exact: true }).click();
	await expect(group.getByRole('combobox', { name: `Role of ${bob.username}` })).toHaveValue(
		'member'
	);

	// Now with a group to give papers to, the first upload explains owners
	// (once; modal, so it is closed whenever it shows up).
	const hint = page.getByRole('dialog', { name: 'Who owns your papers' });
	let hinted = false;
	await page.addLocatorHandler(
		hint,
		async () => {
			await hint.getByRole('button', { name: 'Got it' }).click();
			hinted = true;
		},
		{ times: 1 }
	);

	// A private paper, then shared with the group.
	const paper = await uploadPaper(page, 'Shared');
	await itemAction(page, 'Share with group…');
	const share = page.getByRole('dialog', { name: 'Share with group' });
	await share.getByLabel('Group').selectOption({ label: groupName });
	await share.getByRole('button', { name: 'Share' }).click();
	await expect(share).toBeHidden();
	await expect(page.getByText(/Added by you/)).toBeVisible();

	const privatePaper = await uploadPaper(page, 'Private');
	expect(hinted).toBe(true);

	// bob, in the group, finds the shared paper but not the private one.
	const asBob = await logIn(browser, bob.username, bob.password);
	// He is told, under the bell: the administrator added the paper.
	const bell = asBob.page.getByRole('button', { name: 'Notifications: 1 new' });
	await expect(bell).toBeVisible();
	await bell.click();
	const notices = asBob.page.getByRole('dialog', { name: 'Notifications' });
	await expect(
		notices.getByRole('link', { name: `admin added “${paper.title}” to ${groupName}` })
	).toBeVisible();
	await asBob.page.keyboard.press('Escape');
	await expect(
		asBob.page.getByRole('button', { name: 'Notifications', exact: true })
	).toBeVisible();
	await asBob.page.goto(`/?q=${paper.word}`);
	const found = asBob.page.locator('.results').getByRole('link', { name: paper.title });
	await expect(found).toBeVisible();
	await found.click();
	await expect(asBob.page.getByText(/Added by admin/)).toBeVisible();
	await asBob.page.goto(`/?q=${privatePaper.word}`);
	await expect(asBob.page.getByText(`Nothing found for “${privatePaper.word}”.`)).toBeVisible();
	await asBob.page.goto(`/items/${privatePaper.id}`);
	await expect(asBob.page.getByText('This item does not exist.')).toBeVisible();
	await asBob.context.close();

	// carol, in no group, sees neither.
	const asCarol = await logIn(browser, carol.username, carol.password);
	await asCarol.page.goto(`/?q=${paper.word}`);
	await expect(asCarol.page.getByText(`Nothing found for “${paper.word}”.`)).toBeVisible();
	await asCarol.page.goto(`/items/${paper.id}`);
	await expect(asCarol.page.getByText('This item does not exist.')).toBeVisible();
	await asCarol.context.close();
});

test("whose papers: all, only one's own, a group's", async ({ page, browser }) => {
	// A person of their own, in a group of their own.
	const dana = { username: unique('dana'), password: 'dana-password-e2e' };
	expect((await page.request.post('/api/admin/users', { data: dana })).status()).toBe(201);
	const { context, page: own } = await logIn(browser, dana.username, dana.password);
	const me = await (await own.request.get('/api/auth/me')).json();
	const name = unique('Owners lab ');
	const made = await page.request.post('/api/groups', { data: { name, admin_id: me.id } });
	expect(made.status()).toBe(201);
	const libraries = await (await own.request.get('/api/libraries')).json();
	const lab = libraries.find((l: { name: string }) => l.name === name);
	const word = unique('owned');
	for (const [title, library] of [
		[`Mine ${word}`, null],
		[`Ours ${word}`, lab.id]
	]) {
		const added = await own.request.post('/api/items', {
			data: { metadata: { title }, library_id: library }
		});
		expect(added.status()).toBe(201);
	}
	const mine = own.getByRole('link', { name: `Mine ${word}` });
	const ours = own.getByRole('link', { name: `Ours ${word}` });

	await own.goto('/');
	const whose = own.getByRole('combobox', { name: 'Whose papers' });
	await expect(whose).toHaveValue('');
	await expect(mine).toBeVisible();
	await expect(ours).toBeVisible();
	await whose.selectOption({ label: 'Only mine' });
	await expect(ours).toBeHidden();
	await expect(mine).toBeVisible();
	await whose.selectOption({ label: name });
	await expect(own).toHaveURL(new RegExp(`owner=${lab.id}`));
	await expect(mine).toBeHidden();
	await expect(ours).toBeVisible();
	await whose.selectOption({ label: 'All' });
	await expect(mine).toBeVisible();
	expect(new URL(own.url()).searchParams.has('owner')).toBe(false);
	await context.close();
});
