import { getContext, setContext } from 'svelte';
import { translate, type Locale, type MessageKey, type Params } from './index';

export type T = (key: MessageKey, params?: Params) => string;
const KEY = Symbol('t');

/** The getter keeps the helper reactive when the locale changes after navigation. */
export function provideT(getLocale: () => Locale): void {
	const t: T = (key, params) => translate(getLocale(), key, params);
	setContext(KEY, t);
}

export function getT(): T {
	return getContext<T>(KEY);
}
