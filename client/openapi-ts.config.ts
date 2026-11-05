import { defineConfig } from '@hey-api/openapi-ts';

// The schema the website uses too (`npm run api` in web/ refreshes it).
export default defineConfig({
	input: '../web/src/lib/api/openapi.json',
	output: 'src/generated'
});
