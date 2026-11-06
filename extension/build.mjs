// Builds the extension for Chrome and Firefox (Manifest V3) into dist/,
// each also as a zip to load unpacked or to hand in at the stores.
import { execFileSync } from 'node:child_process';
import { cpSync, mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { build } from 'esbuild';

const { version, description } = JSON.parse(readFileSync('package.json', 'utf8'));

const base = {
	manifest_version: 3,
	name: 'paperus',
	version,
	description,
	icons: { 16: 'icons/icon-16.png', 32: 'icons/icon-32.png', 48: 'icons/icon-48.png', 128: 'icons/icon-128.png' },
	action: {
		default_title: 'Save to paperus',
		default_icon: { 16: 'icons/icon-16.png', 32: 'icons/icon-32.png' }
	},
	// activeTab: the page one clicks on, only then; scripting: to read its
	// details and fetch its PDF there; storage: the connection; contextMenus:
	// the button's menu (save to another owner).
	permissions: ['activeTab', 'scripting', 'storage', 'contextMenus'],
	host_permissions: ['https://arxiv.org/*'],
	// The person's own paperus, asked for when connecting.
	optional_host_permissions: ['https://*/*', 'http://*/*'],
	content_scripts: [
		{
			matches: [
				'https://arxiv.org/abs/*',
				'https://arxiv.org/list/*',
				'https://arxiv.org/search/*',
				'https://arxiv.org/catchup/*'
			],
			js: ['arxiv.js'],
			run_at: 'document_idle'
		}
	],
	web_accessible_resources: [{ resources: ['icons/icon-32.png'], matches: ['https://arxiv.org/*'] }],
	options_ui: { page: 'options.html', open_in_tab: true }
};

// Only for automated tests: a paperus address allowed up front, as a robot
// cannot click the browser's permission prompt.
if (process.env.PAPERUS_EXTENSION_TEST_HOST) {
	base.host_permissions = [...base.host_permissions, process.env.PAPERUS_EXTENSION_TEST_HOST];
}

const browsers = {
	chrome: { ...base, background: { service_worker: 'background.js', type: 'module' } },
	firefox: {
		...base,
		background: { scripts: ['background.js'], type: 'module' },
		browser_specific_settings: {
			gecko: {
				id: 'paperus@qcode-uni-a.github.io',
				// 140: Firefox's own consent dialog for the data below.
				strict_min_version: '140.0',
				// Sent to the person's own paperus only: the page's address and
				// details, its PDF, and the arXiv IDs on arXiv pages (to mark the
				// papers one has).
				data_collection_permissions: { required: ['browsingActivity', 'websiteContent'] }
			},
			// The same consent dialog on Android came with 142.
			gecko_android: { strict_min_version: '142.0' }
		}
	}
};

rmSync('dist', { recursive: true, force: true });
for (const [name, manifest] of Object.entries(browsers)) {
	const out = `dist/${name}`;
	mkdirSync(out, { recursive: true });
	await build({
		entryPoints: ['src/background.ts', 'src/options.ts', 'src/allow.ts'],
		bundle: true,
		define: { TEST: String(!!process.env.PAPERUS_EXTENSION_TEST_HOST) },
		format: 'esm',
		target: 'es2022',
		outdir: out,
		logLevel: 'warning'
	});
	// Content scripts are not modules.
	await build({
		entryPoints: ['src/arxiv.ts', 'src/site.ts'],
		bundle: true,
		format: 'iife',
		target: 'es2022',
		outdir: out,
		logLevel: 'warning'
	});
	cpSync('src/options.html', `${out}/options.html`);
	cpSync('src/allow.html', `${out}/allow.html`);
	cpSync('src/options.css', `${out}/options.css`);
	cpSync('icons', `${out}/icons`, { recursive: true });
	writeFileSync(`${out}/manifest.json`, JSON.stringify(manifest, null, '\t') + '\n');
	// With Python's zipfile, which is there wherever paperus is developed.
	const zip = `import os, sys, zipfile
folder, target = sys.argv[1], sys.argv[2]
with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
    for root, _, files in os.walk(folder):
        for name in sorted(files):
            path = os.path.join(root, name)
            archive.write(path, os.path.relpath(path, folder))`;
	execFileSync('python3', ['-c', zip, out, `dist/paperus-${name}-${version}.zip`]);
	console.log(`dist/${name} and dist/paperus-${name}-${version}.zip`);
}
