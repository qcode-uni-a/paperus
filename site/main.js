// The homepage's few scripts: the latest release's version and installers
// (from GitHub's API; without it, the links go to the releases page), and
// the animations. Without scripts, or with less motion wished for, every
// picture shows its last frame.

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

const motion = !matchMedia('(prefers-reduced-motion: reduce)').matches;
const sleep = (ms) => new Promise((done) => setTimeout(done, ms));

// A scene's clock: it only runs while the scene is on screen, the tab is
// shown, and nobody pressed its pause button.
function clock(scene) {
	const state = { visible: false, paused: false };
	new IntersectionObserver(([entry]) => (state.visible = entry.isIntersecting), {
		threshold: 0.3
	}).observe(scene);
	const button = scene.querySelector('.pause');
	const label = button?.querySelector('.visually-hidden');
	if (button && label) {
		button.hidden = false;
		button.addEventListener('click', () => {
			state.paused = !state.paused;
			button.setAttribute('aria-pressed', String(state.paused));
			label.textContent = state.paused ? 'Play the example' : 'Pause the example';
			scene.classList.toggle('paused', state.paused);
		});
	}
	return async (ms) => {
		for (let left = ms; left > 0;) {
			await sleep(40);
			if (state.visible && !state.paused && !document.hidden) left -= 40;
		}
	};
}

// Wraps each word in a span, numbered, so they can appear one by one.
function words(element) {
	let i = 0;
	for (const node of [...element.childNodes]) {
		if (node.nodeType === Node.TEXT_NODE) {
			const pieces = node.textContent.split(/(\s+)/);
			const spans = pieces.map((piece) => {
				if (!piece.trim()) return document.createTextNode(piece);
				const span = document.createElement('span');
				span.className = 'w';
				span.style.setProperty('--i', String(i++));
				span.textContent = piece;
				return span;
			});
			node.replaceWith(...spans);
		} else if (node instanceof HTMLElement) {
			node.classList.add('w');
			node.style.setProperty('--i', String(i++ + 2));
		}
	}
}

// The first screen: a question typed, the library searched, the passage
// found and marked, the answer with its citation; then again.
async function hero() {
	const demo = document.querySelector('.demo');
	const typed = demo?.querySelector('[data-typed]');
	const tool = demo?.querySelector('[data-tool]');
	const answer = demo?.querySelector('[data-words]');
	if (!demo || !typed || !tool || !answer) return;
	const question = typed.textContent;
	const ghost = document.createElement('span');
	ghost.className = 'ghost';
	ghost.setAttribute('aria-hidden', 'true');
	ghost.textContent = question;
	typed.closest('.ask')?.prepend(ghost);
	words(answer);
	const wait = clock(demo);
	const steps = ['searching', 'found', 'marked', 'answered', 'leaving'];

	typed.textContent = '';
	demo.classList.add('play');
	await wait(700);
	for (;;) {
		for (const letter of question) {
			typed.textContent += letter;
			await wait(letter === ' ' ? 80 : 42);
		}
		await wait(500);
		tool.textContent = 'Searching your library by meaning';
		demo.classList.add('searching');
		await wait(1300);
		tool.textContent = 'Searched your library by meaning';
		demo.classList.add('found');
		await wait(800);
		demo.classList.add('marked');
		await wait(2600);
		demo.classList.add('answered');
		await wait(8000);
		demo.classList.add('leaving');
		await wait(800);
		typed.textContent = '';
		demo.classList.remove(...steps);
		await wait(700);
	}
}

// The round trip: the assistant asks, paperus searches and checks, the
// cited passage comes back. Each time with another assistant.
async function relay() {
	const scene = document.querySelector('.relay');
	const name = scene?.querySelector('[data-name]');
	if (!scene || !name) return;
	const wait = clock(scene);
	const names = ['Claude', 'ChatGPT', 'a local model'];
	const steps = ['asked', 'sent', 's1', 's2', 's3', 'returned', 'answered', 'leaving'];
	const step = async (name, ms) => {
		scene.classList.add(name);
		await wait(ms);
	};

	name.textContent = names[0];
	scene.classList.add('play');
	for (let round = 0; ; round++) {
		await wait(600);
		await step('asked', 900);
		await step('sent', 1500);
		await step('s1', 550);
		await step('s2', 550);
		await step('s3', 700);
		await step('returned', 1500);
		await step('answered', 4200);
		await step('leaving', 600);
		scene.classList.remove(...steps);
		scene.classList.add('switching');
		await wait(300);
		name.textContent = names[(round + 1) % names.length];
		scene.classList.remove('switching');
	}
}

// The screenshot straightens as it comes up the screen.
function tilt() {
	const window_ = document.querySelector('[data-tilt]');
	if (!window_) return;
	let queued = false;
	const update = () => {
		queued = false;
		const top = window_.getBoundingClientRect().top;
		const height = innerHeight;
		const p = Math.min(1, Math.max(0, (height - top) / (height * 0.75)));
		window_.style.setProperty('--p', p.toFixed(3));
	};
	const queue = () => {
		if (!queued) requestAnimationFrame(update);
		queued = true;
	};
	addEventListener('scroll', queue, { passive: true });
	addEventListener('resize', queue);
	update();
}

// The four small pictures: played from the start each time they come into
// view, and again on pointing at them.
function pictures() {
	const replay = (idea) => {
		for (const animation of idea.getAnimations({ subtree: true })) {
			animation.currentTime = 0;
			animation.play();
		}
	};
	const observer = new IntersectionObserver(
		(entries) => {
			for (const { target, isIntersecting } of entries) {
				if (isIntersecting) replay(target);
				else
					for (const animation of target.getAnimations({ subtree: true })) {
						animation.pause();
						animation.currentTime = 0;
					}
			}
		},
		{ threshold: 0.6 }
	);
	for (const idea of document.querySelectorAll('[data-play]')) {
		observer.observe(idea);
		idea.addEventListener('pointerenter', () => {
			const done = idea
				.getAnimations({ subtree: true })
				.every((animation) => animation.playState === 'finished');
			if (done) replay(idea);
		});
	}
}

release();
if (motion) {
	hero();
	relay();
	tilt();
	pictures();
}
