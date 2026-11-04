# paperus website

SvelteKit app, built as a static single-page app and served by the paperus
server. See the main [README](../README.md#development) for running it.

- `src/lib/api/generated/`: API client generated from the server's OpenAPI
  schema with `npm run api` (do not edit).
- `#lib/...` imports need the file extension, e.g. `#lib/api/client.ts`
  (Node subpath imports, SvelteKit 3).
