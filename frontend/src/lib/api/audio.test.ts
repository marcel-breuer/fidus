import { describe, expect, it } from 'vitest';
import { formatDuration, isActive, MAX_MEMO_BYTES, pickRecorderFormat, validateAudio } from './audio';

describe('audio helpers', () => {
	it('picks the first supported recorder container', () => {
		expect(pickRecorderFormat((mime) => mime === 'audio/webm')).toEqual({ mime: 'audio/webm', extension: '.webm' });
		expect(pickRecorderFormat((mime) => mime === 'audio/mp4')).toEqual({ mime: 'audio/mp4', extension: '.m4a' });
		expect(pickRecorderFormat(() => false)).toBeNull();
	});

	it('validates extension, emptiness and size', () => {
		expect(validateAudio({ name: 'Memo.M4A', size: 10 })).toBeNull();
		expect(validateAudio({ name: 'memo.txt', size: 10 })).toBe('UNSUPPORTED_TYPE');
		expect(validateAudio({ name: 'memo', size: 10 })).toBe('UNSUPPORTED_TYPE');
		expect(validateAudio({ name: 'memo.mp3', size: 0 })).toBe('EMPTY_FILE');
		expect(validateAudio({ name: 'memo.mp3', size: MAX_MEMO_BYTES + 1 })).toBe('FILE_TOO_LARGE');
	});

	it('formats recording time', () => {
		expect(formatDuration(0)).toBe('0:00');
		expect(formatDuration(65.9)).toBe('1:05');
		expect(formatDuration(-3)).toBe('0:00');
	});

	it('keeps polling only while work is outstanding', () => {
		expect(isActive({ status: 'pending', index_status: null })).toBe(true);
		expect(isActive({ status: 'ready', index_status: 'pending' })).toBe(true);
		expect(isActive({ status: 'ready', index_status: 'ready' })).toBe(false);
		expect(isActive({ status: 'failed', index_status: null })).toBe(false);
	});
});
