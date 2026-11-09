/** The annotations of the file open in the viewer, and the tool in hand.
 * See server/src/paperus/annotations.py: each kind is a standard PDF
 * annotation, positions are PDF points. */

import {
	addAnnotation,
	changeAnnotation,
	deleteAnnotation,
	errorMessage,
	fileAnnotations,
	shareAnnotations
} from '#lib/api/client.ts';
import type {
	AnnotationChange,
	AnnotationIn,
	AnnotationKind,
	AnnotationOut
} from '#lib/api/generated/types.gen.ts';
import { notify } from '#lib/toasts.svelte.ts';

export type { AnnotationKind, AnnotationOut };

/** What the pointer does on the pages. */
export type Tool = 'select' | AnnotationKind | 'eraser';

/** Zotero's colours, with names for those who do not see them. */
export const COLORS: { value: string; name: string }[] = [
	{ value: '#ffd400', name: 'Yellow' },
	{ value: '#ff6666', name: 'Red' },
	{ value: '#5fb236', name: 'Green' },
	{ value: '#2ea8e5', name: 'Blue' },
	{ value: '#a28ae5', name: 'Purple' },
	{ value: '#e56eee', name: 'Magenta' },
	{ value: '#f19837', name: 'Orange' },
	{ value: '#aaaaaa', name: 'Grey' }
];

export const colorName = (value: string) => COLORS.find((c) => c.value === value)?.name ?? value;

export const KIND_NAMES: Record<AnnotationKind, string> = {
	highlight: 'Highlight',
	underline: 'Underline',
	strikeout: 'Strike-through',
	note: 'Note',
	text: 'Text',
	image: 'Area',
	ink: 'Pen'
};

/** Pen widths, in PDF points. */
export const INK_WIDTHS = [1, 2, 4];
/** Words written on the page: their size in PDF points. */
export const FONT_SIZES = [10, 12, 14, 18, 24];

const STORAGE_KEY = 'paperus-annotation-tool';

function remembered(): { color: string; inkWidth: number } {
	try {
		const saved = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? '{}');
		return {
			color: COLORS.some((c) => c.value === saved.color) ? saved.color : COLORS[0].value,
			inkWidth: INK_WIDTHS.includes(saved.inkWidth) ? saved.inkWidth : 2
		};
	} catch {
		return { color: COLORS[0].value, inkWidth: 2 };
	}
}

export class FileAnnotations {
	list = $state<AnnotationOut[]>([]);
	loaded = $state(false);
	/** The PDF's own annotations left out when drawing its pages (taken
	 * in): where each sat. */
	hiddenMarks = $state.raw<{ page_index: number; rect: number[] }[]>([]);
	shared = $state(false);
	canShare = $state(false);
	tool = $state<Tool>('select');
	color = $state(COLORS[0].value);
	inkWidth = $state(2);
	fontSize = $state(12);
	/** The annotation open in its popup. */
	selected = $state<string | null>(null);

	readonly fileId: string;
	readonly itemId: string;

	constructor(fileId: string, itemId: string) {
		this.fileId = fileId;
		this.itemId = itemId;
		const saved = remembered();
		this.color = saved.color;
		this.inkWidth = saved.inkWidth;
	}

	/** The colour and pen width are kept for next time (this browser). */
	remember() {
		try {
			localStorage.setItem(
				STORAGE_KEY,
				JSON.stringify({ color: this.color, inkWidth: this.inkWidth })
			);
		} catch {
			// Not kept: private browsing or storage blocked.
		}
	}

	async load() {
		const { data } = await fileAnnotations({ path: { file_id: this.fileId } });
		if (data) {
			this.list = data.annotations;
			this.hiddenMarks = data.hidden_marks as { page_index: number; rect: number[] }[];
			this.shared = data.shared;
			this.canShare = data.can_share;
		}
		this.loaded = true;
	}

	onPage(index: number): AnnotationOut[] {
		return this.list.filter((a) => a.page_index === index);
	}

	get current(): AnnotationOut | undefined {
		return this.list.find((a) => a.id === this.selected);
	}

	async add(input: AnnotationIn, open = false): Promise<AnnotationOut | null> {
		const { data, error } = await addAnnotation({
			path: { file_id: this.fileId },
			body: input
		});
		if (!data) {
			notify({ kind: 'warning', title: 'Not saved', text: errorMessage(error) });
			return null;
		}
		this.list = [...this.list, data].sort(order);
		if (open) this.selected = data.id;
		return data;
	}

	async change(id: string, changes: AnnotationChange) {
		const { data, error } = await changeAnnotation({
			path: { annotation_id: id },
			body: changes
		});
		if (!data) {
			notify({ kind: 'warning', title: 'Not saved', text: errorMessage(error) });
			return;
		}
		this.list = this.list.map((a) => (a.id === id ? data : a)).sort(order);
	}

	async remove(id: string) {
		const before = this.list;
		this.list = this.list.filter((a) => a.id !== id);
		if (this.selected === id) this.selected = null;
		const { error } = await deleteAnnotation({ path: { annotation_id: id } });
		if (error) {
			this.list = before;
			notify({ kind: 'warning', title: 'Not removed', text: errorMessage(error) });
		}
	}

	async share(shared: boolean) {
		const { error } = await shareAnnotations({
			path: { item_id: this.itemId },
			body: { shared }
		});
		if (error) {
			notify({ kind: 'warning', title: 'Not saved', text: errorMessage(error) });
			return;
		}
		this.shared = shared;
	}
}

/** Reading order: by page, then from the top, then from the left (as the
 * server sorts them). */
function order(a: AnnotationOut, b: AnnotationOut): number {
	return a.page_index - b.page_index || top(b) - top(a) || left(a) - left(b);
}

function points(a: AnnotationOut): { xs: number[]; ys: number[] } {
	const rects = (a.position.rects ?? []) as number[][];
	const paths = (a.position.paths ?? []) as number[][];
	return {
		xs: [
			...rects.map((r) => Math.min(r[0], r[2])),
			...paths.flatMap((p) => p.filter((_, i) => i % 2 === 0))
		],
		ys: [
			...rects.map((r) => Math.max(r[1], r[3])),
			...paths.flatMap((p) => p.filter((_, i) => i % 2 === 1))
		]
	};
}

const top = (a: AnnotationOut) => Math.max(0, ...points(a).ys);
const left = (a: AnnotationOut) => Math.min(Infinity, ...points(a).xs);
