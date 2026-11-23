import { createApiClient } from './http';
import type { components } from './schema';

export type Usage = components['schemas']['UsageOut'];
export type UsageAmounts = components['schemas']['UsageAmounts'];

export const USAGE_PERIODS = [7, 30, 90] as const;
export type UsagePeriod = (typeof USAGE_PERIODS)[number];
export const DEFAULT_USAGE_PERIOD: UsagePeriod = 30;

/** Counters in display order; each maps to a `usage.metric.<key>` label. */
export const USAGE_METRICS = [
	'chat_requests',
	'input_tokens',
	'output_tokens',
	'transcription_minutes',
	'embedding_chunks',
	'mcp_calls'
] as const satisfies readonly (keyof UsageAmounts)[];
export type UsageMetric = (typeof USAGE_METRICS)[number];

const api = createApiClient(fetch, '');

export const getUsage = async (days: UsagePeriod = DEFAULT_USAGE_PERIOD): Promise<Usage> => {
	const { data, response } = await api.GET('/api/v1/usage', { params: { query: { days } } });
	if (!response.ok) throw new Error(`Usage request failed: ${response.status}`);
	return data as Usage;
};

/** True when nothing was counted in the period, so the page can show an empty state. */
export const isEmptyUsage = (usage: Pick<Usage, 'daily'>): boolean => usage.daily.length === 0;

export const formatAmount = (locale: string, metric: UsageMetric, value: number): string =>
	new Intl.NumberFormat(locale, {
		maximumFractionDigits: metric === 'transcription_minutes' ? 1 : 0
	}).format(value);

/** `YYYY-MM-DD` from the API is a calendar day; format it without a timezone shift. */
export const formatDay = (locale: string, day: string): string =>
	new Intl.DateTimeFormat(locale, { dateStyle: 'medium', timeZone: 'UTC' }).format(
		new Date(`${day}T00:00:00Z`)
	);
