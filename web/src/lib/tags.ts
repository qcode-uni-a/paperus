import type { TagColor } from '#lib/api/generated/types.gen.ts';

/** The colours a tag can have, in the order the pickers show them. */
export const TAG_COLORS: { value: TagColor; label: string }[] = [
	{ value: 'gray', label: 'Gray' },
	{ value: 'brown', label: 'Brown' },
	{ value: 'red', label: 'Red' },
	{ value: 'rose', label: 'Rose' },
	{ value: 'orange', label: 'Orange' },
	{ value: 'amber', label: 'Amber' },
	{ value: 'yellow', label: 'Yellow' },
	{ value: 'lime', label: 'Lime' },
	{ value: 'green', label: 'Green' },
	{ value: 'emerald', label: 'Emerald' },
	{ value: 'teal', label: 'Teal' },
	{ value: 'cyan', label: 'Cyan' },
	{ value: 'sky', label: 'Sky' },
	{ value: 'blue', label: 'Blue' },
	{ value: 'indigo', label: 'Indigo' },
	{ value: 'violet', label: 'Violet' },
	{ value: 'purple', label: 'Purple' },
	{ value: 'pink', label: 'Pink' }
];
