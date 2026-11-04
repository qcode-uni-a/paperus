import { defineConfig } from '@hey-api/openapi-ts';

// `npm run api` exports the server's schema and generates the client.
export default defineConfig({
	input: 'src/lib/api/openapi.json',
	output: 'src/lib/api/generated'
});
