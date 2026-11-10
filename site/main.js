// The homepage's few scripts: the latest release's version and installers
// (from GitHub's API; without it, the links go to the releases page), and
// the first screen's sequence.

const REPO = 'qcode-uni-a/paperus';

const INSTALLERS = [
	{ end: '.AppImage', system: 'linux', label: 'Linux, AppImage' },
	{ end: '.deb', system: 'linux', label: 'Debian and Ubuntu, .deb' },
	{ end: '.rpm', system: 'linux', label: 'Fedora and openSUSE, .rpm' },
	{ end: '-setup.exe', system: 'windows', label: 'Windows, setup' },
	{ end: '.msi', system: 'windows', label: 'Windows, .msi' },
	{ end: '.dmg', system: 'mac', label: 'macOS, Apple silicon and Intel' }
];
const NAMES = { linux: 'Linux', windows: 'Windows', mac: 'macOS' };

function system() {
	const platform = (navigator.userAgentData?.platform || navigator.platform || '').toLowerCase();
	const agent = navigator.userAgent.toLowerCase();
	if (/android|iphone|ipad/.test(agent)) return null;
	if (platform.startsWith('win')) return 'windows';
	if (platform.startsWith('mac')) return 'mac';
	if (platform.includes('linux')) return 'linux';
	return null;
}

async function release() {
	let latest;
	try {
		const response = await fetch(`https://api.github.com/repos/${REPO}/releases/latest`);
		if (!response.ok) return;
		latest = await response.json();
	} catch {
		return;
	}
	const version = latest.tag_name?.replace(/^v/, '');
	const status = document.querySelector('[data-version]');
	if (version && status) status.textContent = `Now in beta, version ${version}`;

	const found = INSTALLERS.map((kind) => ({
		...kind,
		asset: latest.assets.find((asset) => asset.name.endsWith(kind.end))
	})).filter((kind) => kind.asset);
	if (!found.length) return;
	const mine = system();
	const first = found.find((kind) => kind.system === mine);
	const button = document.querySelector('[data-download]');
	if (first && button) {
		button.href = first.asset.browser_download_url;
		button.textContent = `Download for ${NAMES[mine]}`;
	}
	const list = document.querySelector('[data-files]');
	for (const kind of found) {
		if (kind === first) continue;
		const item = document.createElement('li');
		const link = document.createElement('a');
		link.href = kind.asset.browser_download_url;
		link.textContent = kind.label;
		item.append(link);
		list?.append(item);
	}
}

const wait = (ms) => new Promise((done) => setTimeout(done, ms));

async function play() {
	const demo = document.querySelector('.demo');
	const typed = demo?.querySelector('[data-typed]');
	if (!demo || !typed || matchMedia('(prefers-reduced-motion: reduce)').matches) return;
	const text = typed.textContent;
	typed.textContent = '';
	demo.classList.add('play');
	await wait(700);
	for (const letter of text) {
		typed.textContent += letter;
		await wait(letter === ' ' ? 70 : 38);
	}
	await wait(450);
	demo.classList.add('searched');
	await wait(650);
	demo.classList.add('found');
	await wait(350);
	demo.classList.add('marked');
	await wait(1500);
	demo.classList.add('answered');
}

release();
play();
