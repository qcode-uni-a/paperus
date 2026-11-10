import { resolve } from '$app/paths';
import { DEMO } from '#lib/demo.ts';

/** In the demo, its service worker answers the API: started, and in charge
 * of this page, before the website asks anything. */
export async function init(): Promise<void> {
	if (!DEMO || !('serviceWorker' in navigator)) return;
	const container = navigator.serviceWorker;
	if (container.controller) return;
	const inCharge = new Promise((done) => container.addEventListener('controllerchange', done));
	// Not a static file of the website: put there by the demo's build.
	const root = resolve('/').replace(/\/$/, '');
	await container.register(`${root}/demo-service-worker.js`, { scope: `${root}/` });
	await inCharge;
}
