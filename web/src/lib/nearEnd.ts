/** Loading a list's next page as its end comes near. An observer only says
 * when the end comes into or out of reach: a page asked for while another
 * was loading (and so not loaded), or one too short to push the end away,
 * would leave the list stuck with its end in reach. So it remembers, and
 * ``again()`` after each load goes on while the end is still near. */
export class NearEnd {
	#near = false;
	#next: () => void;

	/** ``next``: load the next page, if there is one and nothing loads now. */
	constructor(next: () => void) {
		this.#next = next;
	}

	/** For ``{@attach}`` on an element at the list's end. */
	attach = (node: HTMLElement) => {
		const observer = new IntersectionObserver(
			([entry]) => {
				this.#near = entry.isIntersecting;
				if (this.#near) this.#next();
			},
			{ rootMargin: '800px 0px' }
		);
		observer.observe(node);
		return () => {
			this.#near = false;
			observer.disconnect();
		};
	};

	/** After a page loaded: the next one, if the end is still near. */
	again(): void {
		if (this.#near) this.#next();
	}
}
