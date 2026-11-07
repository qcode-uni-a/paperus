/** Dates and times as the installation shows them (Administration →
 * Settings → Server → Dates and times), the one place that formats them.
 * Times are in the browser's time zone; dates without a time
 * ("2024-03-15", e.g. a paper's publication date) are calendar days and
 * never shift. */

import type { User } from '#lib/api/client.ts';
import { session } from '#lib/session.svelte.ts';

export type DateFormat = NonNullable<User['date_format']>;

export const DATE_FORMATS: [DateFormat, string][] = [
	['browser', 'As each browser is set'],
	['europe', 'Europe'],
	['uk', 'UK'],
	['iso', 'ISO 8601'],
	['us', 'US']
];

/** The installation's choice, known after login ("browser" before). */
export function dateFormat(): DateFormat {
	return session.user?.date_format ?? 'browser';
}

type When = string | number | Date;

const CALENDAR_DAY = /^\d{4}-\d{2}-\d{2}$/;

/** A date and the time zone to read it in: a calendar day in UTC (it has
 * no time zone), a moment in the browser's. */
function moment(value: When): { date: Date; timeZone: 'UTC' | undefined } {
	if (typeof value === 'string' && CALENDAR_DAY.test(value))
		return { date: new Date(`${value}T00:00:00Z`), timeZone: 'UTC' };
	return { date: new Date(value), timeZone: undefined };
}

function parts(value: When): { year: string; month: string; day: string } {
	const { date, timeZone } = moment(value);
	const utc = timeZone === 'UTC';
	const pad = (n: number, width = 2) => String(n).padStart(width, '0');
	return {
		year: pad(utc ? date.getUTCFullYear() : date.getFullYear(), 4),
		month: pad((utc ? date.getUTCMonth() : date.getMonth()) + 1),
		day: pad(utc ? date.getUTCDate() : date.getDate())
	};
}

/** "31.12.2026", "31/12/2026", "2026-12-31", "12/31/2026", or the
 * browser's short date. */
export function formatDate(value: When, format: DateFormat = dateFormat()): string {
	if (format === 'browser') {
		const { date, timeZone } = moment(value);
		return date.toLocaleDateString(undefined, { timeZone });
	}
	const { year, month, day } = parts(value);
	if (format === 'europe') return `${day}.${month}.${year}`;
	if (format === 'uk') return `${day}/${month}/${year}`;
	if (format === 'us') return `${month}/${day}/${year}`;
	return `${year}-${month}-${day}`;
}

/** "31 December 2026"; "December 31, 2026" in the US. ISO 8601 has no
 * long form people read in a sentence, so it takes the European one, as
 * the browser's choice does (the website's words are English). */
export function formatLongDate(value: When, format: DateFormat = dateFormat()): string {
	const { date, timeZone } = moment(value);
	return date.toLocaleDateString(format === 'us' ? 'en-US' : 'en-GB', {
		day: 'numeric',
		month: 'long',
		year: 'numeric',
		timeZone
	});
}

/** "March 2024", for a whole month. */
export function formatMonth(value: When, format: DateFormat = dateFormat()): string {
	const { date, timeZone } = moment(value);
	return date.toLocaleDateString(format === 'us' ? 'en-US' : 'en-GB', {
		month: 'long',
		year: 'numeric',
		timeZone
	});
}

/** "14:30" (24-hour), "2:30 PM" in the US, or the browser's; with
 * ``seconds``: "14:30:05". */
export function formatTime(
	value: When,
	{ seconds = false, format = dateFormat() }: { seconds?: boolean; format?: DateFormat } = {}
): string {
	const date = new Date(value);
	if (format === 'browser')
		return date.toLocaleTimeString([], {
			hour: '2-digit',
			minute: '2-digit',
			...(seconds && { second: '2-digit' })
		});
	const pad = (n: number) => String(n).padStart(2, '0');
	const rest = `${pad(date.getMinutes())}${seconds ? `:${pad(date.getSeconds())}` : ''}`;
	if (format !== 'us') return `${pad(date.getHours())}:${rest}`;
	const hour = date.getHours() % 12 || 12;
	return `${hour}:${rest} ${date.getHours() < 12 ? 'AM' : 'PM'}`;
}

/** "31.12.2026, 14:30", or the browser's date and time. */
export function formatDateTime(value: When, format: DateFormat = dateFormat()): string {
	if (format === 'browser') return new Date(value).toLocaleString();
	return `${formatDate(new Date(value), format)}, ${formatTime(value, { format })}`;
}

/** A time of day stored in UTC (as the server's schedules are), in the
 * browser's time zone: "03:30". */
export function localTime(utcHour: number, minute = 0): string {
	const date = new Date();
	date.setUTCHours(utcHour, minute, 0, 0);
	return formatTime(date);
}

type Order = ('day' | 'month' | 'year')[];

/** The order of day, month and year in short dates, and what goes between. */
function layout(format: DateFormat): { order: Order; separator: string } {
	if (format === 'europe') return { order: ['day', 'month', 'year'], separator: '.' };
	if (format === 'uk') return { order: ['day', 'month', 'year'], separator: '/' };
	if (format === 'us') return { order: ['month', 'day', 'year'], separator: '/' };
	if (format === 'iso') return { order: ['year', 'month', 'day'], separator: '-' };
	const found = new Intl.DateTimeFormat(undefined, {
		day: '2-digit',
		month: '2-digit',
		year: 'numeric'
	}).formatToParts(new Date(2026, 11, 31));
	const order = found
		.map((part) => part.type)
		.filter((type): type is Order[number] => ['day', 'month', 'year'].includes(type));
	const separator = found.find((part) => part.type === 'literal')?.value.trim() || '/';
	return order.length === 3 ? { order, separator } : { order: ['day', 'month', 'year'], separator };
}

/** How to write a date, for placeholders: "DD.MM.YYYY". */
export function datePattern(format: DateFormat = dateFormat()): string {
	const { order, separator } = layout(format);
	const names = { day: 'DD', month: 'MM', year: 'YYYY' };
	return order.map((part) => names[part]).join(separator);
}

/** A date as written by a person, as "YYYY-MM-DD", or null if it is none:
 * "1.2.2026" and "01.02.2026" in Europe (any of . / - and spaces between),
 * and "2026-02-01" always. Years have four digits. */
export function parseDate(text: string, format: DateFormat = dateFormat()): string | null {
	const trimmed = text.trim();
	let year: string, month: string, day: string;
	const iso = /^(\d{4})-(\d{1,2})-(\d{1,2})$/.exec(trimmed);
	if (iso) [, year, month, day] = iso;
	else {
		const numbers = trimmed.split(/\s*[./\-\s]\s*/);
		if (numbers.length !== 3 || numbers.some((n) => !/^\d{1,4}$/.test(n))) return null;
		const { order } = layout(format);
		const found = Object.fromEntries(order.map((part, i) => [part, numbers[i]]));
		({ year, month, day } = found as { year: string; month: string; day: string });
		if (year.length !== 4) return null;
	}
	const date = new Date(Date.UTC(2000, +month - 1, +day));
	date.setUTCFullYear(+year);
	const valid = +year >= 1 && date.getUTCMonth() === +month - 1 && date.getUTCDate() === +day;
	if (!valid) return null;
	return `${year}-${month.padStart(2, '0')}-${day.padStart(2, '0')}`;
}
