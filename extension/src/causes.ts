/** Why a PDF could not be had from a publisher, from what the page (or the
 * answer where the PDF should have been) shows: a check for robots, a login
 * or paywall, or no PDF at all. */

export type Cause = 'robot-check' | 'access' | 'no-pdf' | 'error';

export interface Signals {
	title: string;
	text: string;
	/** A captcha or robot-check element (reCAPTCHA, hCaptcha, Cloudflare, …). */
	captcha: boolean;
	/** A password field: a login form. */
	password: boolean;
	status?: number;
}

const ROBOT_CHECK =
	/just a moment|attention required|verify (that )?you are (a )?human|are you a robot|not a robot|captcha|unusual traffic|checking (if the site connection is secure|your browser)|bot (protection|detection)|press (and|&) hold|security check/i;
const NO_ACCESS =
	/sign in|log ?in|institutional (access|login)|access through your (institution|organization)|purchase (this )?(article|pdf)|buy (this )?article|rent this|subscribe|get access|access options|check access|shibboleth|openathens|seamless access/i;

const ERROR_PAGE =
	/unable to load (the )?page|page not found|page (could not|cannot) be (found|loaded|displayed)|access denied|^\s*(400|403|404|500|502|503)\b|forbidden|internal server error|service (temporarily )?unavailable|bad gateway/i;

/** The page did not load (IEEE Xplore's "Unable to Load Page", a 404): its
 * title names no paper. By the title only. */
export function isErrorPage(signals: Signals): boolean {
	return ERROR_PAGE.test(signals.title);
}

/** The page itself is a check for robots (Cloudflare's "Just a moment…"),
 * not the paper: by its captcha or its title only (an article may well
 * mention captchas). */
export function isRobotCheck(signals: Signals): boolean {
	return signals.captcha || ROBOT_CHECK.test(signals.title);
}

export function causeOf(signals: Signals): Cause {
	const words = `${signals.title}\n${signals.text}`;
	if (signals.captcha || ROBOT_CHECK.test(words)) return 'robot-check';
	if (signals.password || signals.status === 401 || signals.status === 403) {
		return 'access';
	}
	if (NO_ACCESS.test(words)) return 'access';
	return 'no-pdf';
}

export const EXPLAINED: Record<Cause, string> = {
	'robot-check':
		'The publisher shows a check for robots (a captcha). Open the paper there, pass the check once, then try again or save it with the paperus button.',
	access:
		'No access: the publisher asks for a login or payment. On the campus network or with your institution’s login it may work.',
	'no-pdf': 'The publisher’s page offers no PDF.',
	error: 'Something went wrong.'
};

/** Signals from an HTML answer (where the PDF should have been). */
export function signalsOfHtml(html: string, status: number): Signals {
	const title = html.match(/<title[^>]*>([^<]*)<\/title>/i)?.[1] ?? '';
	const text = html
		.replace(/<script[\s\S]*?<\/script>|<style[\s\S]*?<\/style>/gi, ' ')
		.replace(/<[^>]+>/g, ' ')
		.slice(0, 20000);
	return {
		title,
		text,
		captcha: /g-recaptcha|h-captcha|cf-turnstile|challenge-platform|captcha-delivery|px-captcha/i.test(html),
		password: /type=["']?password/i.test(html),
		status
	};
}
