/** Fluent mode on layout twins of real papers' pages (``twins/``): built
 * when the tests run (``twins.py``), each read like the viewer reads a
 * page, and checked (``twins/check.ts``). Run with ``npm run test:layout``. */

import { execFileSync } from 'node:child_process';
import { mkdtempSync, readFileSync, readdirSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { after, before, test } from 'node:test';
import { createCanvas } from '@napi-rs/canvas';
import { getDocument } from 'pdfjs-dist/legacy/build/pdf.mjs';
import { analysePage } from '../src/lib/pageAnalysis.ts';
import { check, type Spec } from './twins/check.ts';

const HERE = import.meta.dirname;
const specs = readdirSync(join(HERE, 'twins', 'pages'))
	.filter((file) => file.endsWith('.json'))
	.sort()
	.map((file) => JSON.parse(readFileSync(join(HERE, 'twins', 'pages', file), 'utf8')) as Spec);

let out = '';
before(() => {
	out = mkdtempSync(join(tmpdir(), 'paperus-twins-'));
	execFileSync('python3', [join(HERE, 'twins', 'twins.py'), out]);
});
after(() => rmSync(out, { recursive: true, force: true }));

for (const spec of specs) {
	test(`${spec.name}: ${spec.source}`, { todo: spec.todo }, async () => {
		const task = getDocument({
			data: new Uint8Array(readFileSync(join(out, `${spec.name}.pdf`))),
			verbosity: 0
		});
		try {
			const page = await (await task.promise).getPage(1);
			const make = (w: number, h: number) => createCanvas(w, h) as unknown as HTMLCanvasElement;
			const { layout } = await analysePage(page, make, spec.first);
			const { problems } = check(spec, layout);
			if (problems.length) throw new Error(problems.join('\n'));
		} finally {
			await task.destroy();
		}
	});
}
