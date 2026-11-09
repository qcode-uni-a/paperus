import { expect, test } from '@playwright/test';
import { makeLinkedPdf } from '../fixtures/pdf.ts';
import { uploadPaper } from './helpers.ts';

test("the paper's links: to a place in it and back, to the web, never a script", async ({
	page
}) => {
	await uploadPaper(page, 'Linked', [], makeLinkedPdf);
	const links = page.locator('#page-1 .linkLayer a');
	await expect(links).toHaveCount(2, { timeout: 20_000 });

	// A web page: in a tab of its own that cannot reach back.
	const web = links.filter({ has: page.locator(':scope[target="_blank"]') });
	await expect(
		page.locator('#page-1 .linkLayer a[href="https://example.org/paper"]')
	).toHaveAttribute('rel', /noopener noreferrer/);
	await expect(web).toHaveCount(1);
	// The script's address is no link at all.
	await expect(page.locator('.linkLayer a[href^="javascript"]')).toHaveCount(0);

	// A place in the paper: there, and Back.
	const pages = page.locator('.viewer .toolbar .muted').first();
	await expect(pages).toHaveText('1 / 2');
	await page.locator('#page-1 .linkLayer a[href="#"]').click();
	await expect(pages).toHaveText('2 / 2');
	await page.getByRole('button', { name: 'Back' }).click();
	await expect(pages).toHaveText('1 / 2');
	await expect(page.getByRole('button', { name: 'Back' })).toBeHidden();
});
