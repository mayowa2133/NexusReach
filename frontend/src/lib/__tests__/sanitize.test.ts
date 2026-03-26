import { describe, it, expect } from 'vitest';
import { sanitizeHTML } from '../sanitize';

describe('sanitizeHTML', () => {
  it('strips script tags', () => {
    expect(sanitizeHTML('<p>Hello</p><script>alert("xss")</script>')).toBe('<p>Hello</p>');
  });

  it('strips onerror attributes', () => {
    const result = sanitizeHTML('<img onerror="alert(1)" src="x">');
    expect(result).not.toContain('onerror');
  });

  it('strips javascript: hrefs', () => {
    const result = sanitizeHTML('<a href="javascript:alert(1)">click</a>');
    expect(result).not.toContain('javascript:');
  });

  it('strips iframe tags', () => {
    expect(sanitizeHTML('<iframe src="https://evil.com"></iframe>')).toBe('');
  });

  it('strips style tags', () => {
    expect(sanitizeHTML('<style>body{display:none}</style><p>Hi</p>')).toBe('<p>Hi</p>');
  });

  it('preserves safe HTML from ATS descriptions', () => {
    const html = '<h2>Requirements</h2><ul><li><strong>Python</strong></li><li>React</li></ul><p>Apply <a href="https://example.com">here</a></p>';
    expect(sanitizeHTML(html)).toBe(html);
  });

  it('preserves table markup', () => {
    const html = '<table><thead><tr><th>Skill</th></tr></thead><tbody><tr><td>Python</td></tr></tbody></table>';
    expect(sanitizeHTML(html)).toBe(html);
  });

  it('returns empty string for empty input', () => {
    expect(sanitizeHTML('')).toBe('');
  });
});
