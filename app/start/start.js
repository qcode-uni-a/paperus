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

// Changes made offline the libraries refused (offline/mod.rs, push).
const unsaved = document.getElementById('unsaved');
const unsavedList = document.getElementById('unsaved-list');

async function showUnsaved() {
	const changes = await invoke('unsaved_changes');
	unsaved.hidden = changes.length === 0;
	unsavedList.replaceChildren(
		...changes.map((change) => {
			const item = document.createElement('li');
			item.className = 'unsaved';
			const what = document.createElement('div');
			what.className = 'what';
			const title = document.createElement('strong');
			title.textContent = change.what;
			const why = document.createElement('span');
			why.className = 'where';
			why.textContent = `${change.name}: ${change.why}`;
			what.append(title, why);
			if (change.written) {
				const written = document.createElement('pre');
				written.textContent = change.written;
				what.append(written);
			}
			const dismiss = document.createElement('button');
			dismiss.className = 'forget';
			dismiss.type = 'button';
			dismiss.textContent = 'Dismiss';
			dismiss.addEventListener('click', async () => {
				await invoke('dismiss_unsaved', { library: change.library, seq: change.seq });
				await showUnsaved();
			});
			item.append(what, dismiss);
			return item;
		})
	);
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
showUnsaved();
// Logged out offline: what is still to be sent before the login ends.
invoke('logging_out').then((libraries) => {
	const note = document.getElementById('logging-out');
	note.hidden = libraries.length === 0;
	note.textContent = libraries
		.map(({ name, waiting }) =>
			waiting
				? `Logged out of ${name}: ${waiting === 1 ? '1 change' : `${waiting} changes`} made offline will be sent when it can be reached, then the login ends there.`
				: `Logged out of ${name}: the login ends there when it can be reached.`
		)
		.join(' ');
});
// Where the PDFs of the library on this computer are kept, and moving them.
const pdfs = document.getElementById('pdfs');
const choosePdfs = document.getElementById('choose-pdfs');
const pdfsError = document.getElementById('pdfs-error');
async function showPdfFolder() {
	const folder = await invoke('local_pdf_folder');
	pdfs.hidden = !folder;
	document.getElementById('pdf-folder').textContent = folder ?? '';
}
choosePdfs.addEventListener('click', async () => {
	choosePdfs.disabled = true;
	pdfsError.hidden = true;
	try {
		await invoke('choose_pdf_folder');
	} catch (message) {
		pdfsError.textContent = String(message);
		pdfsError.hidden = false;
	} finally {
		choosePdfs.disabled = false;
		await showPdfFolder();
	}
});
showPdfFolder();
// Where logins are kept, if not in the system's keyring.
invoke('logins_in_file').then((inFile) => {
	document.getElementById('logins-in-file').hidden = !inFile;
});
