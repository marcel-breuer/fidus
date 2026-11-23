import { describe, expect, it } from 'vitest';
import { renderMarkdown } from './markdown';

describe('renderMarkdown', () => {
	it('renders paragraphs, emphasis, code, lists and safe links', () => {
		const html = renderMarkdown('**Bold** and *soft* with `code`\n\n- one\n- two\n\n1. first\n2. second\n\n[site](https://example.com/a?x=1&y=2)');
		expect(html).toContain('<strong>Bold</strong>');
		expect(html).toContain('<em>soft</em>');
		expect(html).toContain('<code>code</code>');
		expect(html).toContain('<ul><li>one</li><li>two</li></ul>');
		expect(html).toContain('<ol><li>first</li><li>second</li></ol>');
		expect(html).toContain('rel="noopener noreferrer"');
		expect(html).toContain('https://example.com/a?x=1&amp;y=2');
	});

	it('escapes script tags, event handlers and raw HTML', () => {
		const html = renderMarkdown('<script>alert(1)</script><img src=x onerror=alert(1)>');
		expect(html).toContain('&lt;script&gt;');
		expect(html).toContain('&lt;img');
		expect(html).not.toContain('<script');
		expect(html).not.toContain('<img');
	});

	it('refuses javascript links and escapes fenced code contents', () => {
		const html = renderMarkdown('[bad](javascript:alert(1))\n\n```html\n<img src=x onerror=alert(1)>\n```');
		expect(html).not.toContain('<a');
		expect(html).not.toContain('href="javascript:');
		expect(html).toContain('&lt;img src=x onerror=alert(1)&gt;');
		expect(html).not.toContain('<img');
	});
});
