function escapeHtml(value: string): string {
	return value.replace(/[&<>"']/g, (character) => ({
		'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
	})[character] ?? character);
}

function renderInline(source: string): string {
	let text = escapeHtml(source);
	const tokens: string[] = [];
	const hold = (html: string): string => {
		const token = `\u0000${tokens.length}\u0000`;
		tokens.push(html);
		return token;
	};
	text = text.replace(/`([^`\n]+)`/g, (_match, code: string) => hold(`<code>${code}</code>`));
	text = text.replace(/\[([^\]]+)\]\(([^\s)]+)\)/g, (_match, label: string, href: string) => {
		if (!/^https?:\/\//i.test(href)) return `${label} (${href})`;
		return hold(`<a href="${href}" target="_blank" rel="noopener noreferrer">${label}</a>`);
	});
	text = text.replace(/\*\*([^*\n]+)\*\*/g, '<strong>$1</strong>');
	text = text.replace(/\*([^*\n]+)\*/g, '<em>$1</em>');
	return text.replace(/\u0000(\d+)\u0000/g, (_match, index: string) => tokens[Number(index)] ?? '');
}

/** Small, dependency-free Markdown subset. Input HTML is always escaped before formatting. */
export function renderMarkdown(source: string): string {
	const lines = source.replace(/\r\n?/g, '\n').split('\n');
	const output: string[] = [];
	let paragraph: string[] = [];
	let list: 'ul' | 'ol' | null = null;
	let code: string[] | null = null;
	const flushParagraph = () => {
		if (paragraph.length) output.push(`<p>${paragraph.map(renderInline).join('<br>')}</p>`);
		paragraph = [];
	};
	const closeList = () => {
		if (list) output.push(`</${list}>`);
		list = null;
	};
	for (const line of lines) {
		if (code) {
			if (/^\s*```/.test(line)) {
				output.push(`<pre><code>${escapeHtml(code.join('\n'))}</code></pre>`);
				code = null;
			} else code.push(line);
			continue;
		}
		if (/^\s*```/.test(line)) {
			flushParagraph(); closeList(); code = [];
			continue;
		}
		const unordered = /^\s*[-*+]\s+(.+)$/.exec(line);
		const ordered = /^\s*\d+\.\s+(.+)$/.exec(line);
		if (unordered || ordered) {
			flushParagraph();
			const kind = unordered ? 'ul' : 'ol';
			if (list !== kind) { closeList(); output.push(`<${kind}>`); list = kind; }
			output.push(`<li>${renderInline((unordered ?? ordered)?.[1] ?? '')}</li>`);
			continue;
		}
		if (!line.trim()) { flushParagraph(); closeList(); continue; }
		closeList(); paragraph.push(line);
	}
	if (code) output.push(`<pre><code>${escapeHtml(code.join('\n'))}</code></pre>`);
	flushParagraph(); closeList();
	return output.join('');
}
