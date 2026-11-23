export function readCsrfToken(cookieString: string): string | null {
	for (const entry of cookieString.split(';')) {
		const separator = entry.indexOf('=');
		if (separator < 0 || entry.slice(0, separator).trim() !== 'fidus_csrf') continue;
		const value = entry.slice(separator + 1).trim();
		try {
			return decodeURIComponent(value);
		} catch {
			return value;
		}
	}
	return null;
}

export function csrfHeaders(cookieString: string = document.cookie): Record<string, string> {
	const token = readCsrfToken(cookieString);
	return token ? { 'X-CSRF-Token': token } : {};
}
