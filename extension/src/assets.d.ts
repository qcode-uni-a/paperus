/** Images built into a script (esbuild's dataurl loader, build.mjs). */
declare module '*.png' {
	const url: string;
	export default url;
}
