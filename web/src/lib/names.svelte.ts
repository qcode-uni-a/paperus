/** People's names as the person reads them (Settings → Names), the one
 * place that formats them. A paper's authors come "Family, Given" from its
 * details; an author record has both forms (``name``, ``written``). */

import type { User } from '#lib/api/client.ts';
import { fullName } from '#lib/format.ts';
import { session } from '#lib/session.svelte.ts';

export type NameFormat = NonNullable<User['name_format']>;

export const NAME_FORMATS: { value: NameFormat; label: string; example: string }[] = [
	{ value: 'family-given', label: 'Family name first', example: 'Benito, Mónica' },
	{ value: 'given-family', label: 'Given name first', example: 'Mónica Benito' }
];

/** The person's choice (family name first before login). */
export function nameFormat(): NameFormat {
	return session.user?.name_format ?? 'family-given';
}

/** One of a paper's authors, given as "Family, Given". */
export function writtenName(written: string): string {
	return nameFormat() === 'given-family' ? fullName(written) : written;
}

/** A person: an author record, or anything with both forms. */
export function personName(person: { name: string; written?: string }): string {
	return nameFormat() === 'given-family' ? person.name : (person.written ?? person.name);
}

/** What goes between names in a line: "Benito, Mónica; Platero, Gloria". */
export function nameSeparator(): string {
	return nameFormat() === 'family-given' ? '; ' : ', ';
}
