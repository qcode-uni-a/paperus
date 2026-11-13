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
	// Exactly: other tests' groups add "New group in …".
	await page.getByRole('button', { name: 'New group', exact: true }).click();
	const groupDialog = page.getByRole('dialog', { name: 'New group', exact: true });
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
	await itemAction(page, 'Share…');
	const share = page.getByRole('dialog', { name: 'Share' });
	await share.getByRole('radio', { name: 'With a group' }).check();
	await share.getByRole('combobox').selectOption({ label: groupName });
	await share.getByRole('button', { name: 'Share', exact: true }).click();
	await expect(share).toBeHidden();
	await expect(page.getByText(/Added by you/)).toBeVisible();

	const privatePaper = await uploadPaper(page, 'Private');
	expect(hinted).toBe(true);

	// bob, in the group, finds the shared paper but not the private one.
	const asBob = await logIn(browser, bob.username, bob.password);
	// He is told, under the bell: the administrator added him to the group,
	// and the paper.
	const bell = asBob.page.getByRole('button', { name: 'Notifications: 2 new' });
	await expect(bell).toBeVisible();
	await bell.click();
	const notices = asBob.page.getByRole('dialog', { name: 'Notifications' });
	await expect(
		notices.getByRole('link', { name: `admin added “${paper.title}” to ${groupName}` })
	).toBeVisible();
	await expect(
		notices.getByRole('link', { name: `admin added you to ${groupName}` })
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
	await expect(mine).toBeVisible();
	await expect(ours).toBeVisible();
	// In the filter: whose papers, a button each (none pressed: all).
	await own.getByRole('button', { name: 'Filter', exact: true }).click();
	const owners = own.getByRole('group', { name: 'Owned by' });
	await owners.getByRole('button', { name: 'Me', exact: true }).click();
	await expect(ours).toBeHidden();
	await expect(mine).toBeVisible();
	await owners.getByRole('button', { name: 'Me', exact: true }).click();
	await owners.getByRole('button', { name }).click();
	await expect(own).toHaveURL(new RegExp(`owner=${lab.id}`));
	await expect(mine).toBeHidden();
	await expect(ours).toBeVisible();
	await owners.getByRole('button', { name }).click();
	await expect(mine).toBeVisible();
	expect(new URL(own.url()).searchParams.has('owner')).toBe(false);
	await context.close();
});

test('a paper shared with a single person', async ({ page, browser }) => {
	// Two people of their own (a group of the admin's would change the other
	// tests' uploads: they would ask where to).
	const ann = { username: unique('ann'), password: 'ann-password-e2e' };
	const ben = { username: unique('ben'), password: 'ben-password-e2e' };
	for (const person of [ann, ben]) {
		expect((await page.request.post('/api/admin/users', { data: person })).status()).toBe(201);
	}
	const a = await logIn(browser, ann.username, ann.password);
	const b = await logIn(browser, ben.username, ben.password);
	// Their names as they show them.
	await a.page.request.put('/api/auth/profile', { data: { display_name: 'Ann Lee' } });
	await b.page.request.put('/api/auth/profile', { data: { display_name: 'Ben Ott' } });
	const title = unique('For Ben ');
	const made = await a.page.request.post('/api/items', { data: { metadata: { title } } });
	const paper = await made.json();

	await a.page.goto(`/items/${paper.id}`);
	await itemAction(a.page, 'Share…');
	const share = a.page.getByRole('dialog', { name: 'Share' });
	// Without groups: with people at once.
	await expect(share.getByRole('radio', { name: 'With people' })).toBeChecked();
	await share.getByRole('searchbox', { name: 'Find a person' }).fill('Ben');
	await share.getByRole('button', { name: /^Ben Ott/ }).click();
	await share.getByRole('button', { name: 'Share with Ben Ott' }).click();
	await expect(share).toBeHidden();
	await expect(
		a.page.getByText('Shared with Ann Lee & Ben Ott').filter({ visible: true })
	).toBeVisible();

	// Ben is told under the bell, and sees it; the two of them under
	// Groups, apart.
	await b.page.goto('/');
	const bell = b.page.getByRole('button', { name: 'Notifications: 1 new' });
	await bell.click();
	await expect(
		b.page
			.getByRole('dialog', { name: 'Notifications' })
			.getByRole('link', { name: `Ann Lee shared “${title}” with you` })
	).toBeVisible();
	// Dismissed: gone for good.
	const bobsNotices = b.page.getByRole('dialog', { name: 'Notifications' });
	await bobsNotices.getByRole('button', { name: 'Dismiss' }).click();
	await expect(bobsNotices.getByText('Nothing yet.')).toBeVisible();
	await b.page.keyboard.press('Escape');
	await expect(b.page.getByRole('link', { name: title })).toBeVisible();
	await b.page.goto('/manage/groups');
	await expect(b.page.getByRole('heading', { name: 'Shared with people' })).toBeVisible();
	await expect(b.page.getByRole('heading', { name: 'Ann Lee & Ben Ott', level: 2 })).toBeVisible();
	await a.context.close();
	await b.context.close();
});
