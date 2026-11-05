# paperus

Server of [paperus](https://github.com/qcode-uni-a/paperus), a self-hosted
research library for groups: papers and notes in one shared library,
searchable by words and by meaning, with your own AI assistant connected.

This package contains the API, the background worker and the `paperus`
command. Most installations use the container images instead; see the
[installation guide](https://github.com/qcode-uni-a/paperus#installation).

```sh
pip install paperus
paperus migrate                     # needs PAPERUS_DATABASE_URL (Postgres + pgvector)
paperus user create alice --admin
paperus serve                       # API on port 8000
paperus worker                      # background jobs
```

Status: early version (0.0.x) for a pilot; expect breaking changes.
