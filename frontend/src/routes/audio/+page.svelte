<script lang="ts">
	import { page } from '$app/state';
	import {
		deleteMemo, fetchSpeech, formatDuration, getMemo, isActive, listMemos, pickRecorderFormat,
		retryMemo, uploadMemo, validateAudio, type Memo, type MemoDetail
	} from '$lib/api/audio';
	import { formatFileSize } from '$lib/api/files';
	import { formatDate } from '$lib/i18n';
	import type { MessageKey } from '$lib/i18n';
	import { getT } from '$lib/i18n/context';
	import { Alert, Button, TextField } from '$lib/ui';

	const t = getT();
	let memos = $state<Memo[]>([]);
	let loading = $state(true);
	let error = $state('');
	let title = $state('');
	let uploading = $state<{ name: string; progress: number } | null>(null);
	let recording = $state(false);
	let elapsed = $state(0);
	let details = $state<Record<string, MemoDetail>>({});
	let speech = $state<Record<string, { state: 'loading' | 'ready'; url?: string }>>({});
	let canRecord = $state(true);
	let recorder: MediaRecorder | null = null;
	let stream: MediaStream | null = null;
	let ticker: ReturnType<typeof setInterval> | undefined;
	let startedAt = 0;

	const errorKeys: Record<string, MessageKey> = {
		UNSUPPORTED_TYPE: 'audio.unsupportedType',
		FILE_TOO_LARGE: 'audio.tooLarge',
		EMPTY_FILE: 'audio.emptyFile',
		RATE_LIMITED: 'common.rateLimited'
	};
	const reasonKeys: Record<string, MessageKey> = {
		AI_NOT_CONFIGURED: 'audio.reasonAiNotConfigured',
		TRANSCRIPTION_FAILED: 'audio.reasonTranscriptionFailed',
		EMPTY_TRANSCRIPT: 'audio.reasonEmptyTranscript',
		CORRUPT_AUDIO: 'audio.reasonCorruptAudio',
		FFMPEG_UNAVAILABLE: 'audio.reasonFfmpeg'
	};

	function messageFor(code: string): string {
		return t(errorKeys[code] ?? 'audio.error');
	}

	async function refresh(quiet = false) {
		if (!quiet) loading = true;
		try {
			memos = await listMemos();
			error = '';
			for (const memo of memos) {
				const known = details[memo.id];
				if (known && (known.status !== memo.status || known.index_status !== memo.index_status)) await loadDetail(memo.id);
			}
		} catch {
			if (!quiet) error = t('audio.error');
		} finally {
			loading = false;
		}
	}

	async function loadDetail(id: string) {
		try { details = { ...details, [id]: await getMemo(id) }; }
		catch { error = t('audio.error'); }
	}

	$effect(() => { void refresh(); });

	$effect(() => {
		if (!memos.some(isActive)) return;
		const timer = setInterval(() => { void refresh(true); }, 3000);
		return () => clearInterval(timer);
	});

	$effect(() => {
		canRecord = typeof MediaRecorder !== 'undefined' && !!navigator.mediaDevices?.getUserMedia
			&& pickRecorderFormat((mime) => MediaRecorder.isTypeSupported(mime)) !== null;
		return () => {
			stopTracks();
			for (const entry of Object.values(speech)) if (entry.url) URL.revokeObjectURL(entry.url);
		};
	});

	function stopTracks() {
		clearInterval(ticker);
		stream?.getTracks().forEach((track) => track.stop());
		stream = null;
	}

	async function send(file: File) {
		const issue = validateAudio(file);
		if (issue) { error = messageFor(issue); return; }
		error = '';
		uploading = { name: file.name, progress: 0 };
		try {
			await uploadMemo(file, { title }, (progress) => { uploading = { name: file.name, progress }; });
			title = '';
			await refresh(true);
		} catch (cause) {
			error = messageFor(cause instanceof Error ? cause.message : '');
		} finally {
			uploading = null;
		}
	}

	async function selectFile(event: Event) {
		const input = event.currentTarget as HTMLInputElement;
		const file = input.files?.[0];
		input.value = '';
		if (file) await send(file);
	}

	async function startRecording() {
		error = '';
		const format = pickRecorderFormat((mime) => MediaRecorder.isTypeSupported(mime));
		if (!format) { canRecord = false; return; }
		try {
			stream = await navigator.mediaDevices.getUserMedia({ audio: true });
		} catch {
			error = t('audio.micDenied');
			return;
		}
		const parts: Blob[] = [];
		recorder = new MediaRecorder(stream, { mimeType: format.mime });
		recorder.ondataavailable = (event) => { if (event.data.size) parts.push(event.data); };
		recorder.onstop = () => {
			stopTracks();
			recording = false;
			void send(new File(parts, `recording${format.extension}`, { type: format.mime }));
		};
		recorder.start(1000);
		startedAt = Date.now();
		elapsed = 0;
		recording = true;
		ticker = setInterval(() => { elapsed = (Date.now() - startedAt) / 1000; }, 250);
	}

	function stopRecording() {
		recorder?.stop();
	}

	function statusLabel(memo: Memo): string {
		if (memo.status === 'pending') return t('audio.statusPending');
		if (memo.status === 'transcribing') return t('audio.statusTranscribing');
		if (memo.status === 'failed') {
			return t('audio.statusFailed', { reason: t(reasonKeys[memo.error_code ?? ''] ?? 'audio.reasonOther') });
		}
		if (memo.index_status === 'failed') return t('audio.indexFailed');
		if (memo.index_status === 'pending') return t('audio.indexPending');
		return `${t('audio.statusReady')} · ${t('audio.indexReady')}`;
	}

	const needsRetry = (memo: Memo) => memo.status === 'failed' || memo.index_status === 'failed';

	async function retry(memo: Memo) {
		try { await retryMemo(memo.id); await refresh(true); }
		catch { error = t('audio.error'); }
	}

	async function remove(memo: Memo) {
		if (!window.confirm(t('audio.deleteConfirm', { title: memo.title }))) return;
		try {
			await deleteMemo(memo.id);
			const url = speech[memo.id]?.url;
			if (url) URL.revokeObjectURL(url);
			await refresh(true);
		} catch { error = t('audio.error'); }
	}

	async function readAloud(memo: Memo) {
		if (speech[memo.id]) return;
		speech = { ...speech, [memo.id]: { state: 'loading' } };
		try {
			const url = URL.createObjectURL(await fetchSpeech(memo.id));
			speech = { ...speech, [memo.id]: { state: 'ready', url } };
		} catch (cause) {
			const { [memo.id]: _removed, ...rest } = speech;
			speech = rest;
			error = cause instanceof Error && cause.message === 'TEXT_TOO_LONG' ? t('audio.speechTooLong') : t('audio.speechFailed');
		}
	}
</script>

<svelte:head><title>{t('audio.title')} · {t('app.name')}</title></svelte:head>
<section class="glass-panel audio">
	<h1>{t('audio.title')}</h1>
	<p class="intro">{t('audio.intro')}</p>
	<div class="tools">
		<TextField label={t('audio.titleLabel')} bind:value={title} maxlength={255} disabled={recording || uploading !== null} />
		<div class="capture">
			{#if recording}
				<Button onclick={stopRecording}>{t('audio.stop')}</Button>
				<span class="timer" role="timer" aria-live="off">{t('audio.recording', { time: formatDuration(elapsed) })}</span>
			{:else}
				<Button onclick={startRecording} disabled={!canRecord || uploading !== null}>{t('audio.record')}</Button>
			{/if}
			<label class="file-picker"><span>{t('audio.upload')}</span>
				<input type="file" accept="audio/*,.webm,.ogg,.mp3,.m4a,.wav,.flac" onchange={selectFile} disabled={recording || uploading !== null} />
			</label>
		</div>
	</div>
	{#if !canRecord}<p class="hint">{t('audio.micUnsupported')}</p>{/if}
	{#if error}<Alert>{error}</Alert>{/if}
	{#if uploading}
		<p role="status">{t('audio.uploading', { name: uploading.name, progress: uploading.progress })}</p>
		<progress max="100" value={uploading.progress} aria-label={t('audio.uploading', { name: uploading.name, progress: uploading.progress })}></progress>
	{/if}
	{#if loading}<p role="status">{t('audio.loading')}</p>
	{:else if memos.length === 0}<p class="empty">{t('audio.empty')}</p>
	{:else}
		<ul class="memos">
			{#each memos as memo (memo.id)}
				<li>
					<div class="head">
						<h2>{memo.title}</h2>
						<span class="status" role="status">{statusLabel(memo)}</span>
					</div>
					<p class="meta">{formatDate(page.data.locale, new Date(memo.created_at))} · {formatFileSize(memo.size_bytes, page.data.locale)}</p>
					<audio controls preload="none" src={`/api/v1/audio/memos/${encodeURIComponent(memo.id)}/audio`} aria-label={t('audio.recordingLabel', { title: memo.title })}></audio>
					{#if speech[memo.id]?.url}
						<audio controls autoplay src={speech[memo.id].url} aria-label={t('audio.speechLabel', { title: memo.title })}></audio>
					{/if}
					<div class="actions">
						{#if memo.status === 'ready'}
							<Button variant="quiet" onclick={() => readAloud(memo)} disabled={speech[memo.id] !== undefined}>
								{speech[memo.id]?.state === 'loading' ? t('audio.readingAloud') : t('audio.readAloud')}
							</Button>
						{/if}
						{#if needsRetry(memo)}<Button variant="quiet" onclick={() => retry(memo)}>{t('audio.retry')}</Button>{/if}
						<Button variant="quiet" onclick={() => remove(memo)}>{t('audio.delete')}</Button>
					</div>
					{#if memo.status === 'ready'}
						<details ontoggle={(event) => { if ((event.currentTarget as HTMLDetailsElement).open) void loadDetail(memo.id); }}>
							<summary>{t('audio.transcript')}</summary>
							{#if details[memo.id]}
								<p class="transcript">{details[memo.id].transcript ?? t('audio.noTranscript')}</p>
							{:else}<p role="status">{t('audio.loading')}</p>{/if}
						</details>
					{/if}
				</li>
			{/each}
		</ul>
	{/if}
</section>

<style>
	.audio { padding: clamp(1rem, 3vw, 1.5rem); display: grid; gap: 1rem; }
	h1, h2 { margin: 0; }
	h2 { font-size: 1.05rem; overflow-wrap: anywhere; }
	.intro, .hint, .meta, .empty, .status { margin: 0; color: var(--muted); }
	.tools { display: flex; flex-wrap: wrap; align-items: end; justify-content: space-between; gap: 1rem; }
	.tools :global(.field) { flex: 1 1 16rem; }
	.capture { display: flex; flex-wrap: wrap; align-items: center; gap: 0.75rem; }
	.timer { font-variant-numeric: tabular-nums; color: var(--muted); }
	.file-picker { display: inline-flex; flex-wrap: wrap; align-items: center; gap: 0.5rem; min-width: 0; font-weight: 600; }
	.file-picker input { width: 100%; max-width: 100%; font: inherit; }
	progress { width: 100%; accent-color: var(--accent); }
	.memos { list-style: none; padding: 0; margin: 0; display: grid; gap: 0.75rem; }
	.memos > li { border: 1px solid var(--glass-rim); border-radius: 0.75rem; padding: 1rem; display: grid; gap: 0.75rem; }
	.head { display: flex; flex-wrap: wrap; justify-content: space-between; align-items: baseline; gap: 0.5rem 1rem; }
	audio { width: 100%; }
	.actions { display: flex; flex-wrap: wrap; gap: 0.5rem; }
	details summary { cursor: pointer; font-weight: 600; }
	.transcript { white-space: pre-wrap; overflow-wrap: anywhere; margin: 0.75rem 0 0; }
</style>
