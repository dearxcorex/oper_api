// Client for the NBTC OPER HTTP API (github.com/dearxcorex/oper_api, server/app.py).
// One file, no dependencies: fetch and AbortSignal.timeout (Node 18+, browsers, edge).
// Reads OPER_API_URL and OPER_API_TOKEN from the environment.
//
// tests/test_skill_client.py in oper_api checks these types against the server;
// edit both together.

/** The server's live portal walk stops at 20 s; this leaves room for the reply. */
const TIMEOUT_MS = 30_000;

export const OPER_SOURCES = ['ASMS', 'WEB', 'BCS', 'BCS2', 'BCS3', 'OPER'] as const;
export type OperSource = (typeof OPER_SOURCES)[number];

export const OPER_RESULTS = ['ตรงตามมาตรฐาน', 'ไม่ตรงตามมาตรฐาน'] as const;
export type OperResult = (typeof OPER_RESULTS)[number];

/** At least one of province, district, frequency or name. */
export interface FindStationsRequest {
  province?: string;
  district?: string;
  subdistrict?: string;
  frequency?: number;
  name?: string;
  source?: OperSource;
  limit?: number;
  details?: boolean;
}

export interface CountStationsRequest {
  inspected_from: string;
  inspected_to: string;
  province?: string;
  district?: string;
  result?: OperResult;
  limit?: number;
}

/** Private fields: lat, lng and contact_* never go to an external model. */
export interface StationSummary {
  stn_id: number;
  name: string | null;
  frequency_mhz: number | null;
  station_code: string | null;
  station_subtype: string | null;
  source: string | null;
  subdistrict: string | null;
  district: string | null;
  province: string | null;
  location: string | null;
  lat?: number | null;
  lng?: number | null;
  contact_name?: string | null;
  contact_phone?: string | null;
  contact_date?: string | null;
  licence_no?: string | null;
  licence_expires?: string | null;
  operator?: string | null;
  nbtc_code?: string | null;
  station_id?: string | null;
}

export interface FindStationsResponse {
  total: number;
  shown: number;
  truncated: boolean;
  complete: boolean;
  as_of?: string;
  provinces?: string[];
  stations: StationSummary[];
}

export interface ResultCount {
  inspections: number;
  stations: number;
}

/** One station among the counted inspections, from its latest one. */
export interface InspectedStation {
  station_name: string | null;
  frequency_mhz: number | null;
  station_code: string | null;
  licence_no: string | null;
  subdistrict: string | null;
  district: string | null;
  province: string | null;
  location: string | null;
  inspected_date: string | null;
  result: string | null;
  warning_doc_no: string | null;
  warning_doc_date: string | null;
  chk_id: number | null;
  inspections: number;
}

export interface CountStationsResponse {
  inspections: number;
  stations: number;
  by_result: Record<string, ResultCount>;
  complete: boolean;
  station_list: InspectedStation[];
  truncated: boolean;
  inspected_from: string;
  inspected_to: string;
}

export interface HealthResponse {
  ok: boolean;
  as_of: string | null;
  refreshing: boolean;
}

/** `kind` is the server's error code, `http_<status>` when it sent none, or timeout / network / not_configured. */
export class OperError extends Error {
  constructor(
    readonly kind: string,
    readonly detail: string,
    readonly status?: number,
  ) {
    super(`OPER ${kind}: ${detail}`);
    this.name = 'OperError';
  }
}

export function operConfigured(): boolean {
  return Boolean(process.env.OPER_API_URL && process.env.OPER_API_TOKEN);
}

async function operRequest<T>(method: 'GET' | 'POST', path: string, body?: object): Promise<T> {
  const url = process.env.OPER_API_URL;
  const token = process.env.OPER_API_TOKEN;
  if (!url || (!token && path !== '/health')) {
    throw new OperError('not_configured', 'OPER_API_URL and OPER_API_TOKEN must be set');
  }

  let res: Response;
  try {
    res = await fetch(`${url.replace(/\/+$/, '')}${path}`, {
      method,
      headers: {
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...(body ? { 'Content-Type': 'application/json' } : {}),
      },
      body: body ? JSON.stringify(body) : undefined,
      signal: AbortSignal.timeout(TIMEOUT_MS),
    });
  } catch (error) {
    // AbortSignal.timeout rejects with a DOMException, not always an Error subclass.
    const { name, message } = (error ?? {}) as { name?: unknown; message?: unknown };
    if (name === 'TimeoutError' || name === 'AbortError') {
      throw new OperError('timeout', `no answer within ${TIMEOUT_MS / 1000} s`);
    }
    throw new OperError('network', typeof message === 'string' ? message : String(error));
  }
  const data = (await res.json().catch(() => null)) as Record<string, unknown> | null;
  if (!res.ok) {
    // The server answers {error, detail}; FastAPI's own 401/422 answer {detail}.
    const kind = typeof data?.error === 'string' ? data.error : `http_${res.status}`;
    const detail = typeof data?.detail === 'string' ? data.detail : JSON.stringify(data?.detail ?? '');
    throw new OperError(kind, detail, res.status);
  }
  return data as T;
}

export function operHealth(): Promise<HealthResponse> {
  return operRequest('GET', '/health');
}

export function findStations(request: FindStationsRequest): Promise<FindStationsResponse> {
  return operRequest('POST', '/find-stations', request);
}

export function countStations(request: CountStationsRequest): Promise<CountStationsResponse> {
  return operRequest('POST', '/count-stations', request);
}

/** Admin: starts a register rebuild (~35 min). OperError kind 'busy' when one is running. */
export function refreshRegister(): Promise<{ started: boolean }> {
  return operRequest('POST', '/refresh');
}
