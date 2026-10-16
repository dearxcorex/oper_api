# OPER results as LLM tools

## Privacy rule

Station coordinates (`lat`, `lng`) and contacts (`contact_name`,
`contact_phone`, `contact_date`) reach the user directly, never the model.
This applies to every model hosted outside the developer's own machines:
Anthropic, OpenAI, DeepSeek, Gemini, any hosted endpoint. A project that
wants to send them to a model must say so explicitly, in code, with a
comment that names the model and the reason.

The pattern: the tool strips the private keys from what the model sees, and
carries them beside the result under a `Symbol` key. `JSON.stringify` skips
symbol keys, so serialising the tool result for the model drops them
automatically. The app reads them back and prints them under the model's
answer.

```ts
import { findStations, type FindStationsRequest, type StationSummary } from './operClient';

const PRIVATE_KEYS = new Set(['lat', 'lng', 'contact_name', 'contact_phone', 'contact_date']);
export const STATION_DETAILS = Symbol('stationDetails');

export async function findStationsTool(input: FindStationsRequest) {
  const out = await findStations(input);
  return {
    ...out,
    stations: out.stations.map((s) =>
      Object.fromEntries(Object.entries(s).filter(([k]) => !PRIVATE_KEYS.has(k))),
    ),
    [STATION_DETAILS]: out.stations as StationSummary[],
  };
}
```

Keep the symbol on the result as it travels through the agent loop, and
serialise for the model only with `JSON.stringify`. Then render the details
yourself: place, a Google Maps link `https://www.google.com/maps?q=<lat>,<lng>`
and the phone, with a placeholder such as ไม่มีข้อมูล for null.

## Tool definitions

Give the model the request fields from `operClient.ts`. Validate its input
before the call: clamp `limit` and drop a `source`/`result` that isn't in
`OPER_SOURCES`/`OPER_RESULTS`. In the tool description and system prompt:

- Tell the model coordinates and phones are shown under its answer, so it
  should leave them out of its own text.
- Explain `complete: false`: say the list is partial and give `shown` of
  `total`.
- Explain `as_of`: the date the saved register was built.
- Explain the counts: `inspections` is the headline number, and `stations`
  (distinct) goes in brackets.

On `OperError`, return a tool error with `detail`, so the model can fix a
place name and retry.

A working example is fm-station-tracker's `src/services/askTools.ts`
(`findOperStations`, `countOperInspections`) with `src/utils/askMessage.ts`
rendering the details.
