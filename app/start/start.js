// The app's own page: the libraries it knows, and connecting to another.
const { invoke } = window.__TAURI__.core;

const list = document.getElementById('libraries');
const known = document.getElementById('known');
const form = document.getElementById('add');
const address = document.getElementById('address');
const error = document.getElementById('error');
const local = document.getElementById('local');
const makeLocal = document.getElementById('make-local');
const localError = document.getElementById('local-error');
const localProgress = document.getElementById('local-progress');

function showError(message) {
	error.textContent = message;
	error.hidden = !message;
}

async function open(url) {
	try {
		await invoke('open_library', { url });
	} catch (message) {
		showError(String(message));
	}
}

// What the library on this computer is doing while it gets ready (also
// when the app opens it by itself at its start).
setInterval(async () => {
	const text = await invoke('local_progress');
	localProgress.textContent = text;
	localProgress.hidden = !text;
}, 400);

makeLocal.addEventListener('click', async () => {
	makeLocal.disabled = true;
	localError.hidden = true;
	try {
		await invoke('make_local_library');
	} catch (message) {
		localError.textContent = String(message);
		localError.hidden = false;
	} finally {
		makeLocal.disabled = false;
	}
});

async function show() {
	const libraries = await invoke('libraries');
	known.hidden = libraries.length === 0;
	local.hidden = libraries.some((library) => library.local);
	list.replaceChildren(
		...libraries.map((library) => {
			const item = document.createElement('li');
			const button = document.createElement('button');
			button.className = 'library';
			button.type = 'button';
			const name = document.createElement('span');
			name.className = 'name';
			name.textContent = library.name;
			const where = document.createElement('span');
			where.className = 'where';
			where.textContent = library.local ? 'On this computer' : library.url;
			button.append(name, where);
			button.addEventListener('click', () => open(library.url));
			const forget = document.createElement('button');
			forget.className = 'forget';
			forget.type = 'button';
			forget.textContent = 'Remove';
			forget.setAttribute('aria-label', `Remove ${library.name} from this list`);
			forget.addEventListener('click', async () => {
				await invoke('forget_library', { url: library.url });
				await show();
			});
			// The one on this computer stays: removing it from the list would
			// not remove its papers.
			item.append(...(library.local ? [button] : [button, forget]));
			return item;
		})
	);
	if (libraries.length === 0) address.focus();
}

form.addEventListener('submit', async (event) => {
	event.preventDefault();
	const button = form.querySelector('button');
	button.disabled = true;
	button.textContent = 'Connecting…';
	showError('');
	try {
		const library = await invoke('add_library', { address: address.value });
		address.value = '';
		await open(library.url);
	} catch (message) {
		showError(String(message));
	} finally {
		button.disabled = false;
		button.textContent = 'Connect';
	}
});

show();
