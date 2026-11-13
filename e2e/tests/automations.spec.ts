import { expect, test } from '@playwright/test';
import { LOGGED_OUT, unique } from './helpers.ts';

// Settings → Automations: one's own library's switches, one's groups' (on
// their pages, switched by their admins), and the server's.
test('automations: one’s own switched, a group’s on its page', async ({ page, browser }) => {
	// A person of their own: the admin's library and groups stay as they are.
	const lu = { username: unique('lu'), password: 'lu-password-e2e' };
	const made = await page.request.post('/api/admin/users', { data: lu });
	expect(made.status()).toBe(201);
	const lab = unique('Lab ');
	const group = await (
		await page.request.post('/api/groups', {
			data: { name: lab, admin_id: (await made.json()).id }
		})
	).json();
	const context = await browser.newContext({ storageState: LOGGED_OUT });
	const own = await context.newPage();
	await own.goto('/login');
	await own.getByLabel('Username').fill(lu.username);
	await own.getByLabel('Password').fill(lu.password);
	await own.getByRole('button', { name: 'Log in' }).click();
	await expect(own).toHaveURL(/\/$/);

	await own.goto('/settings?open=automations');
	const section = own.locator('#automations');
	// One's papers: where one's new papers go, or an owner one chooses.
	const into = section.getByRole('combobox', { name: 'Into' });
	await expect(into).toHaveValue('new papers');
	await into.selectOption({ label: lab });
	await expect(section.getByText('Saved.')).toBeVisible();
	const mine = section.getByRole('checkbox', { name: /Add my papers/ });
	await expect(mine).toBeChecked();
	await mine.uncheck();
	await own.reload();
	await expect(section.getByRole('checkbox', { name: /Add my papers/ })).not.toBeChecked();
	await expect(section.getByText('published versions on, free PDFs on')).toBeVisible();

	// The group's, on its page: its admin switches them.
	await section.getByRole('link', { name: lab }).click();
	const theirs = own.getByRole('checkbox', { name: /Published versions/ });
	await expect(theirs).toBeChecked();
	await theirs.uncheck();
	await expect(own.getByText('Saved.')).toBeVisible();
	await context.close();

	// The site administrator, not a member, sees and may switch them too.
	await page.goto(`/manage/groups?group=${group.id}`);
	await expect(page.getByRole('checkbox', { name: /Published versions/ })).not.toBeChecked();
	await expect(page.getByRole('checkbox', { name: /Published versions/ })).toBeEnabled();
});
