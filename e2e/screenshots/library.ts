import { expect, test } from '@playwright/test';
import { makePdf } from '../fixtures/pdf.ts';

/** A physics group's library, with papers everyone knows (and small PDFs
 * of our own, with only their titles: their text is not in the picture). */
const PAPERS = [
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
] as const;

const COLOURS: Record<string, string> = {
	quantum: 'blue',
	classic: 'gray',
	'to read': 'yellow',
	electromagnetism: 'teal',
	relativity: 'violet',
	'quantum computing': 'emerald',
	'spin qubits': 'rose',
	symmetry: 'orange',
	information: 'sky'
};

test('the library', async ({ page }) => {
	await page.request.put('/api/auth/hints/getting-started');
	await page.request.put('/api/auth/profile', { data: { display_name: 'Mira Kessler' } });
	const group = await (
		await page.request.post('/api/groups', { data: { name: 'Theory group' } })
	).json();
	for (const [name, color] of Object.entries(COLOURS)) {
		await page.request.post('/api/tags', { data: { name, color, library_id: group.library_id } });
	}
	const ids: Record<string, string> = {};
	for (const [title, authors, year, journal, tags] of PAPERS) {
		const added = await page.request.post('/api/items', {
			data: {
				library_id: group.library_id,
				metadata: {
					type: 'article-journal',
					title,
					author: authors.map(([family, given]) => ({ family, given })),
					issued: { 'date-parts': [[year]] },
					'container-title': journal
				}
			}
		});
		expect(added.status()).toBe(201);
		const { id } = await added.json();
		ids[title] = id;
		const pdf = makePdf([[title, authors.map(([family]) => family).join(', ')]], title);
		await page.request.post(`/api/items/${id}/files`, {
			multipart: { upload: { name: 'paper.pdf', mimeType: 'application/pdf', buffer: pdf } }
		});
		for (const name of tags) await page.request.post(`/api/items/${id}/tags`, { data: { name } });
	}
	const collection = async (name: string, titles: string[]) => {
		const made = await (
			await page.request.post('/api/collections', { data: { name, library_id: group.library_id } })
		).json();
		await page.request.post(`/api/collections/${made.id}/items`, {
			data: { item_ids: titles.map((title) => ids[title]) }
		});
		await page.request.put(`/api/collections/${made.id}/pin`);
	};
	await collection('Foundations seminar', [PAPERS[9][0], PAPERS[11][0], PAPERS[6][0]]);
	await collection('Thesis, chapter 2', [PAPERS[12][0], PAPERS[13][0]]);

	// Once the PDFs are read (nothing missing in the menu).
	await expect
		.poll(async () => (await (await page.request.get('/api/manage/counts')).json()).missing ?? 0, {
			timeout: 30_000
		})
		.toBe(0);
	// And their details looked up (the list says so while it runs).
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
	await page.screenshot({ path: '../site/screenshots/library.png' });
	// The website follows the device: dark for a dark homepage.
	await page.emulateMedia({ colorScheme: 'dark' });
	await page.screenshot({ path: '../site/screenshots/library-dark.png' });
});
