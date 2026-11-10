// The demo's papers (papers.json): public-domain scans from Wikimedia
// Commons, downloaded into the folder given (CI caches it), never checked
// in. Each file is checked: Commons still marks it public domain, and it is
// the very file listed (its SHA-1). Files there already, and right, are kept.
// Run with Node: `node demo/fetch.ts <folder>`.
import { createHash } from 'node:crypto';
import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';

type Paper = { file: string; commons: string; sha1: string };

const LICENCES = ['Public domain'];
// Wikimedia asks scripts to say who they are.
const HEADERS = { 'User-Agent': 'paperus-demo/1.0 (https://github.com/qcode-uni-a/paperus)' };

const folder = process.argv[2];
if (!folder) throw new Error('usage: node demo/fetch.ts <folder>');
mkdirSync(folder, { recursive: true });
const papers: Paper[] = JSON.parse(readFileSync(new URL('papers.json', import.meta.url), 'utf8'));

const sha1 = (data: Uint8Array) => createHash('sha1').update(data).digest('hex');

for (const paper of papers) {
	const path = join(folder, paper.file);
	if (existsSync(path) && sha1(readFileSync(path)) === paper.sha1) {
		console.log(`kept ${paper.file}`);
		continue;
	}
	const query = new URLSearchParams({
		action: 'query',
		titles: paper.commons,
		prop: 'imageinfo',
		iiprop: 'url|sha1|extmetadata',
		iiextmetadatafilter: 'LicenseShortName',
		format: 'json'
	});
	const answer = await fetch(`https://commons.wikimedia.org/w/api.php?${query}`, {
		headers: HEADERS
	});
	const pages = Object.values((await answer.json()).query.pages) as {
		imageinfo?: { url: string; sha1: string; extmetadata: Record<string, { value: string }> }[];
	}[];
	const info = pages[0]?.imageinfo?.[0];
	if (!info) throw new Error(`${paper.file}: not on Commons (${paper.commons})`);
	const licence = info.extmetadata.LicenseShortName?.value;
	if (!LICENCES.includes(licence)) {
		throw new Error(`${paper.file}: Commons says ${licence}, not public domain`);
	}
	if (info.sha1 !== paper.sha1) throw new Error(`${paper.file}: another file on Commons now`);
	const download = await fetch(info.url, { headers: HEADERS });
	if (!download.ok) throw new Error(`${paper.file}: ${download.status} from Commons`);
	const data = new Uint8Array(await download.arrayBuffer());
	if (sha1(data) !== paper.sha1) throw new Error(`${paper.file}: not the file listed`);
	writeFileSync(path, data);
	console.log(`downloaded ${paper.file} (${licence})`);
}
