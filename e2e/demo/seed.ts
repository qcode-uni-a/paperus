import { readFileSync } from 'node:fs';
import { expect, type Browser, type BrowserContextOptions, type Page } from '@playwright/test';
import { makePdf } from '../fixtures/pdf.ts';
import { LOGGED_OUT } from '../tests/helpers.ts';

/** The demo library (README.md here), also in the homepage's screenshots: a
 * physics group's papers that everyone knows, details only (each with a
 * one-page PDF of our own that says so), and lecture notes written for it
 * (oscillator.tex, typeset by pdfs.sh). Made by Mira Kessler, a member of
 * the Theory group, who is not an administrator. */

export const MIRA = { username: 'mira', password: 'mira-demo-password', name: 'Mira Kessler' };

type Paper = readonly [
	string,
	readonly (readonly [string, string])[],
	number,
	string,
	readonly string[]
];

export const PAPERS: readonly Paper[] = [
	[
		'A Dynamical Theory of the Electromagnetic Field',
		[['Maxwell', 'J. Clerk']],
		1865,
		'Philosophical Transactions of the Royal Society of London',
		['electromagnetism', 'classic']
	],
	[
		'Ueber das Gesetz der Energieverteilung im Normalspectrum',
		[['Planck', 'Max']],
		1901,
		'Annalen der Physik',
		['quantum', 'classic']
	],
	[
		'Zur Elektrodynamik bewegter Körper',
		[['Einstein', 'Albert']],
		1905,
		'Annalen der Physik',
		['relativity', 'classic']
	],
	[
		'The scattering of α and β particles by matter and the structure of the atom',
		[['Rutherford', 'Ernest']],
		1911,
		'Philosophical Magazine',
		['classic']
	],
	[
		'On the constitution of atoms and molecules',
		[['Bohr', 'Niels']],
		1913,
		'Philosophical Magazine',
		['quantum', 'classic']
	],
	[
		'Invariante Variationsprobleme',
		[['Noether', 'Emmy']],
		1918,
		'Nachrichten der Gesellschaft der Wissenschaften zu Göttingen',
		['symmetry', 'to read']
	],
	[
		'Über quantentheoretische Umdeutung kinematischer und mechanischer Beziehungen',
		[['Heisenberg', 'Werner']],
		1925,
		'Zeitschrift für Physik',
		['quantum']
	],
	[
		'Quantisierung als Eigenwertproblem',
		[['Schrödinger', 'Erwin']],
		1926,
		'Annalen der Physik',
		['quantum']
	],
	[
		'The quantum theory of the electron',
		[['Dirac', 'P. A. M.']],
		1928,
		'Proceedings of the Royal Society of London A',
		['quantum', 'relativity']
	],
	[
		'Can quantum-mechanical description of physical reality be considered complete?',
		[
			['Einstein', 'Albert'],
			['Podolsky', 'Boris'],
			['Rosen', 'Nathan']
		],
		1935,
		'Physical Review',
		['quantum', 'to read']
	],
	[
		'A mathematical theory of communication',
		[['Shannon', 'Claude E.']],
		1948,
		'Bell System Technical Journal',
		['information']
	],
	[
		'On the Einstein Podolsky Rosen paradox',
		[['Bell', 'John S.']],
		1964,
		'Physics Physique Fizika',
		['quantum', 'to read']
	],
	[
		'Simulating physics with computers',
		[['Feynman', 'Richard P.']],
		1982,
		'International Journal of Theoretical Physics',
		['quantum computing']
	],
	[
		'Quantum computation with quantum dots',
		[
			['Loss', 'Daniel'],
			['DiVincenzo', 'David P.']
		],
		1998,
		'Physical Review A',
		['quantum computing', 'spin qubits']
	]
];

const COLOURS: Record<string, string> = {
	quantum: 'blue',
	classic: 'gray',
	'to read': 'yellow',
	electromagnetism: 'teal',
	relativity: 'violet',
	'quantum computing': 'emerald',
	'spin qubits': 'rose',
	symmetry: 'orange',
	information: 'sky',
	teaching: 'lime'
};

export type Seeded = { page: Page; ids: Record<string, string>; notes: string };

/** Makes the library with the administrator's ``admin`` page (a fresh
 * paperus) and returns a page logged in as Mira, in a context with
 * ``options``; ``pdfs``: the folder with pdfs.sh's output (without it, no
 * lecture notes). */
export async function seed(
	admin: Page,
	browser: Browser,
	{ pdfs, options = {} }: { pdfs?: string; options?: BrowserContextOptions } = {}
): Promise<Seeded> {
	const user = await admin.request.post('/api/admin/users', {
		data: { username: MIRA.username, password: MIRA.password }
	});
	expect(user.status()).toBe(201);
	const group = await (
		await admin.request.post('/api/groups', {
			data: { name: 'Theory group', admin_id: (await user.json()).id }
		})
	).json();

	const context = await browser.newContext({ ...options, storageState: LOGGED_OUT });
	const page = await context.newPage();
	const login = await page.request.post('/api/auth/login', {
		data: { username: MIRA.username, password: MIRA.password }
	});
	expect(login.ok()).toBe(true);
	for (const hint of ['getting-started', 'handed-over']) {
		await page.request.put(`/api/auth/hints/${hint}`);
	}
	await page.request.put('/api/auth/profile', { data: { display_name: MIRA.name } });
	// Hers is the group's library: what she adds goes there.
	await page.request.put('/api/me/default-library', { data: { library_id: group.library_id } });
	for (const [name, color] of Object.entries(COLOURS)) {
		await page.request.post('/api/tags', { data: { name, color, library_id: group.library_id } });
	}

	const ids: Record<string, string> = {};
	const add = async (metadata: object, pdf: Buffer, tags: readonly string[]): Promise<string> => {
		const added = await page.request.post('/api/items', {
			data: { library_id: group.library_id, metadata }
		});
		expect(added.status()).toBe(201);
		const { id } = await added.json();
		const uploaded = await page.request.post(`/api/items/${id}/files`, {
			multipart: { upload: { name: 'paper.pdf', mimeType: 'application/pdf', buffer: pdf } }
		});
		expect(uploaded.status()).toBe(201);
		for (const name of tags) await page.request.post(`/api/items/${id}/tags`, { data: { name } });
		return id;
	};
	for (const [title, authors, year, journal, tags] of PAPERS) {
		const names = authors.map(([family, given]) => `${given} ${family}`).join(', ');
		const pdf = makePdf(
			[
				[
					title,
					names,
					`${journal}, ${year}`,
					'',
					'This demo has the details of this paper, not the paper itself.'
				]
			],
			title
		);
		ids[title] = await add(
			{
				type: 'article-journal',
				title,
				author: authors.map(([family, given]) => ({ family, given })),
				issued: { 'date-parts': [[year]] },
				'container-title': journal
			},
			pdf,
			tags
		);
	}
	const lecture = 'The quantum harmonic oscillator';
	if (pdfs) {
		ids[lecture] = await add(
			{
				type: 'document',
				title: lecture,
				author: [{ family: 'Kessler', given: 'Mira' }],
				issued: { 'date-parts': [[2026, 11]] },
				publisher: 'Theory group, lecture notes for Quantum Mechanics II'
			},
			readFileSync(`${pdfs}/oscillator.pdf`),
			['quantum', 'teaching']
		);
	}

	const collection = async (name: string, titles: string[]) => {
		const made = await (
			await page.request.post('/api/collections', { data: { name, library_id: group.library_id } })
		).json();
		await page.request.post(`/api/collections/${made.id}/items`, {
			data: { item_ids: titles.filter((title) => ids[title]).map((title) => ids[title]) }
		});
		await page.request.put(`/api/collections/${made.id}/pin`);
	};
	await collection('Foundations seminar', [PAPERS[9][0], PAPERS[11][0], PAPERS[6][0]]);
	await collection('Thesis, chapter 2', [PAPERS[12][0], PAPERS[13][0], lecture]);
	for (const title of [PAPERS[0][0], PAPERS[11][0], lecture]) {
		if (ids[title]) await page.request.put(`/api/items/${ids[title]}/favourite`);
	}

	const note = await page.request.post('/api/notes', {
		data: {
			library_id: group.library_id,
			text: [
				'# Foundations seminar, 12 November',
				'',
				'We read Einstein, Podolsky and Rosen (1935) next to Bell (1964).',
				'',
				'- EPR: if quantum mechanics is complete, measuring one particle cannot fix the',
				'  other at a distance; so, they argue, it is incomplete.',
				'- Bell: any local hidden-variable theory obeys an inequality that quantum',
				'  mechanics violates. Experiment decides.',
				'',
				'Next time: the loophole-free tests, and what they rule out.'
			].join('\n'),
			items: [{ item_id: ids[PAPERS[9][0]] }, { item_id: ids[PAPERS[11][0]] }]
		}
	});
	expect(note.status()).toBe(201);

	// Ready once the PDFs are read (nothing missing) and their details looked
	// up (the list says so while that runs).
	await expect
		.poll(async () => (await (await page.request.get('/api/manage/counts')).json()).missing ?? 0, {
			timeout: 60_000
		})
		.toBe(0);
	await expect
		.poll(
			async () => {
				await page.goto('/');
				await expect(page.getByRole('link', { name: PAPERS[0][0] })).toBeVisible();
				return page.getByText('Looking up details').count();
			},
			{ timeout: 90_000, intervals: [2_000] }
		)
		.toBe(0);
	return { page, ids, notes: (await note.json()).id };
}
