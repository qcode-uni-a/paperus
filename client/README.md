# paperus (TypeScript client)

Typed client for the API of [paperus](https://github.com/qcode-uni-a/paperus),
a self-hosted research library for groups. Generated from the server's
OpenAPI schema; one function per endpoint.

```ts
import { configure, login, search } from 'paperus';

configure({ baseUrl: 'https://paperus.example.org' });
const { data: session } = await login({ body: { username: 'alice', password: '…' } });
configure({ baseUrl: 'https://paperus.example.org', token: session?.token });

const { data: passages } = await search({ query: { q: 'drought indices', mode: 'hybrid' } });
```

Status: early version (0.0.x); the API will change.
