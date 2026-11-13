import { expect, test } from '@playwright/test';
import { makePdf } from '../fixtures/pdf.ts';
import { uploadPaper } from './helpers.ts';

// A cover a site put in front of the paper (IOP's): the PDF opens after it,
// and fluent mode leaves it out until asked for (#42).
test('a cover page in front of the paper is passed over', async ({ page }) => {
	const paper = await uploadPaper(page, 'Covered', [], (title, word) =>
		makePdf(
			[
				[
					'PAPER - OPEN ACCESS',
					title,
					'To cite this article: A. Tester et al 2026 New J. Phys. 28 000001',
					'View the article online for updates and enhancements.',
					'You may also like'
				],
				[title, 'A. Tester', '', `Abstract. We study the ${word} effect in libraries.`],
				['Results', `The ${word} effect is real and measurable.`]
			],
			title
		)
	);
	const pages = page.locator('.viewer .toolbar .muted').first();
	await expect(pages).toHaveText('2 / 3');

	// Noted with the file (its words left out of the paper's text).
	const file = await page.request.get(`/api/items/${paper.id}`);
	const [main] = (await file.json()).versions[0].files;
	expect(main.cover_pages).toEqual([1]);

	await page.getByRole('button', { name: 'Fluent mode' }).click();
	const bar = page.getByText('A cover page the site put in front of the paper');
	await expect(bar).toBeVisible();
	await page.getByRole('button', { name: 'Show', exact: true }).click();
	await expect(bar).toBeHidden();
});
