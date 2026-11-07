import { expect, type Page } from '@playwright/test';
import { makePdf } from '../fixtures/pdf.ts';

export const ADMIN = { username: 'admin', password: 'e2e-admin-password' };
/** The administrator's login, saved by setup.ts for the other tests. */
export const ADMIN_STATE = '.auth/admin.json';
/** No login: for tests that log in themselves. */
export const LOGGED_OUT = { cookies: [], origins: [] };

/** A word no other test uses, for titles and text that searches find. */
export function unique(prefix: string): string {
	return `${prefix}${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`;
}

export type Paper = { id: string; title: string; word: string };

/** Uploads a PDF through Add → Upload files, opens it and waits until the
 * worker has read it (its embedded title replaces the file name). */
export async function uploadPaper(page: Page, name: string): Promise<Paper> {
	const word = unique(name.toLowerCase());
	const title = `On the ${word} problem in end-to-end testing`;
	const pdf = makePdf(
		[
			[title, 'A. Tester', '', `Abstract. We study the ${word} effect in libraries.`],
			['Results', `The ${word} effect is real and measurable.`]
		],
		title
	);
	await page.goto('/');
	await page.getByTitle('Add papers and notes').click();
	const chooser = page.waitForEvent('filechooser');
	await page.getByRole('menuitem', { name: /Upload files/ }).click();
	await (await chooser).setFiles({ name: `${word}.pdf`, mimeType: 'application/pdf', buffer: pdf });

	const uploads = page.getByRole('complementary', { name: 'Uploads' });
	const row = uploads.getByRole('listitem').filter({ hasText: `${word}.pdf` });
	await row.getByRole('link', { name: 'Open' }).click();
	await expect(page).toHaveURL(/\/items\/[0-9a-f-]+$/);
	const id = page.url().split('/').pop() ?? '';
	// The item page reloads itself while the worker reads the file.
	await expect(page.getByRole('heading', { level: 1 })).toHaveText(title, { timeout: 30_000 });
	return { id, title, word };
}

/** Opens a menu item in the paper's "Item actions" menu. */
export async function itemAction(page: Page, action: string | RegExp): Promise<void> {
	await page.getByRole('button', { name: 'Item actions' }).click();
	await page.getByRole('menuitem', { name: action }).click();
}
