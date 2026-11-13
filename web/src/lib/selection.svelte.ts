import { SvelteSet } from 'svelte/reactivity';

/** Papers picked in one list, for a change to all of them (BulkBar).
 * ``order``: the list's ids as shown, for ranges picked with Shift. */
export class Selection {
	ids = new SvelteSet<string>();
	/** Picking: every row shows its box, and a click on a row picks it. */
	active = $state(false);
	/** Every paper the list's filters match, also those not loaded yet
	 * ("Select all"): changed on the server by the filters, not by ids. */
	everything = $state(false);
	#anchor: string | null = null;
	#order: () => string[];

	constructor(order: () => string[]) {
		this.#order = order;
	}

	get size(): number {
		return this.ids.size;
	}

	has(id: string): boolean {
		return this.everything || this.ids.has(id);
	}

	/** One more or one less; with ``range``, every row from the last one
	 * picked to this one, as this one becomes. */
	toggle(id: string, range = false): void {
		if (this.everything) {
			// From all of them to the rows shown, as picked so far.
			this.everything = false;
			for (const each of this.#order()) this.ids.add(each);
		}
		const picked = !this.ids.has(id);
		const order = this.#order();
		const from = this.#anchor ? order.indexOf(this.#anchor) : -1;
		const to = order.indexOf(id);
		const ids =
			range && from >= 0 && to >= 0
				? order.slice(Math.min(from, to), Math.max(from, to) + 1)
				: [id];
		for (const each of ids) {
			if (picked) this.ids.add(each);
			else this.ids.delete(each);
		}
		this.#anchor = id;
		this.active = true;
	}

	/** Every row shown. */
	all(): void {
		for (const id of this.#order()) this.ids.add(id);
		this.active = true;
	}

	/** Every paper the list's filters match, loaded or not. */
	everyMatching(): void {
		this.all();
		this.everything = true;
	}

	clear(): void {
		this.everything = false;
		this.ids.clear();
		this.#anchor = null;
		this.active = false;
	}

	/** Only rows still shown stay picked (after the list changed). */
	keepShown(): void {
		const shown = new Set(this.#order());
		for (const id of [...this.ids]) if (!shown.has(id)) this.ids.delete(id);
	}
}
