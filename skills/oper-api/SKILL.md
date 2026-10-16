---
name: oper-api
description: Connect a project to the NBTC OPER API (broadcast station search, inspection counts), including LLM tools over it.
---

# Connect to the NBTC OPER API

The API answers station searches and inspection counts for NBTC เขต 23 over
HTTP. The contract is in [`REFERENCE.md`](REFERENCE.md), and the client
is [`operClient.ts`](operClient.ts). Copy the client; never write your own.

## 1. Check access

The project needs `OPER_API_URL` and `OPER_API_TOKEN` in its env (`.env.local`,
the deploy's secrets, …), and the env file must be gitignored. Run:

```bash
curl -fsS "$OPER_API_URL/health"
```

**Done when** it prints `"ok":true`. If either variable is missing or the call
fails, stop and tell the developer to ask the API owner for the URL and token.
The token lives only in env and is read at runtime.

## 2. Add the client

Copy `operClient.ts` into the project's lib folder unchanged, apart from
import style and env access if the project reads env differently. In
non-TypeScript projects, port it one function per route and keep the
`OperError` kinds. Call sites use `findStations`, `countStations` and
`operHealth`. `refreshRegister` is admin-only, so wire it in only when the
developer asks for it.

Handle at each call site:

- `complete: false`: the list is partial; show `shown` of `total`.
- `OperError` kind `unknown_place`: show `detail`, and let the user fix the name.
- kind `timeout`: suggest a narrower search (a sub-district or frequency for
  stations, a shorter date range for counts).
- `as_of`: show it as the data's date when present.

The server answers one request at a time, so make calls in sequence.

## 3. Test

Write tests with `fetch` mocked: one success per route the project uses, a
`complete: false` reply, and a `{error, detail}` reply that becomes an
`OperError`. Then make one live call:

```ts
await findStations({ province: 'ชัยภูมิ', frequency: 91.75 });
```

**Done when** the mocked tests pass and the live call returns `complete: true`
with an `as_of`.

## 4. LLM tools

If the project passes OPER results to a language model, read
[`LLM-TOOLS.md`](LLM-TOOLS.md) before you write the tool.
