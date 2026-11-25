<script lang="ts">
	import { page } from '$app/state';
	import {
		deleteMemo, fetchSpeech, formatDuration, getMemo, isActive, listMemos, pickRecorderFormat,
		retryMemo, uploadMemo, validateAudio, type Memo, type MemoDetail
	} from '#lib/api/audio.ts';
	import { formatFileSize } from '#lib/api/files.ts';
	import { formatDate } from '#lib/i18n/index.ts';
	import type { MessageKey } from '#lib/i18n/index.ts';
	import { getT } from '#lib/i18n/context.ts';
	import { Alert, AlertDescription } from '#lib/components/ui/alert/index.ts';
	import { Button } from '#lib/components/ui/button/index.ts';
	import { Card } from '#lib/components/ui/card/index.ts';
	import { Input } from '#lib/components/ui/input/index.ts';
	import { Label } from '#lib/components/ui/label/index.ts';

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
<Card class="grid gap-4 p-[clamp(1rem,3vw,1.5rem)]">
	<h1 class="m-0">{t('audio.title')}</h1>
	<p class="m-0 text-muted-foreground">{t('audio.intro')}</p>
	<div class="flex flex-wrap items-end justify-between gap-4">
		<div class="grid flex-[1_1_16rem] gap-1.5">
			<Label for="audio-title" class="font-semibold">{t('audio.titleLabel')}</Label>
			<Input id="audio-title" bind:value={title} maxlength={255} disabled={recording || uploading !== null} />
		</div>
		<div class="flex flex-wrap items-center gap-3">
			{#if recording}
				<Button type="button" onclick={stopRecording}>{t('audio.stop')}</Button>
				<span class="text-muted-foreground tabular-nums" role="timer" aria-live="off">{t('audio.recording', { time: formatDuration(elapsed) })}</span>
			{:else}
				<Button type="button" onclick={startRecording} disabled={!canRecord || uploading !== null}>{t('audio.record')}</Button>
			{/if}
			<div class="flex min-w-0 flex-wrap items-center gap-2">
				<Label for="audio-upload" class="font-semibold">{t('audio.upload')}</Label>
				<Input id="audio-upload" type="file" accept="audio/*,.webm,.ogg,.mp3,.m4a,.wav,.flac" onchange={selectFile} disabled={recording || uploading !== null} />
			</div>
		</div>
	</div>
	{#if !canRecord}<p class="m-0 text-muted-foreground">{t('audio.micUnsupported')}</p>{/if}
	{#if error}<Alert variant="destructive"><AlertDescription class="text-foreground">{error}</AlertDescription></Alert>{/if}
	{#if uploading}
		<p class="m-0" role="status">{t('audio.uploading', { name: uploading.name, progress: uploading.progress })}</p>
		<progress class="w-full accent-primary" max="100" value={uploading.progress} aria-label={t('audio.uploading', { name: uploading.name, progress: uploading.progress })}></progress>
	{/if}
	{#if loading}<p class="m-0" role="status">{t('audio.loading')}</p>
	{:else if memos.length === 0}<p class="m-0 text-muted-foreground">{t('audio.empty')}</p>
	{:else}
		<ul class="m-0 grid list-none gap-3 p-0">
			{#each memos as memo (memo.id)}
				<li class="glass-inset grid gap-3 p-4">
					<div class="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-2">
						<h2 class="m-0 text-[1.05rem] [overflow-wrap:anywhere]">{memo.title}</h2>
						<span class="text-muted-foreground" role="status">{statusLabel(memo)}</span>
					</div>
					<p class="m-0 text-muted-foreground">{formatDate(page.data.locale, new Date(memo.created_at))} · {formatFileSize(memo.size_bytes, page.data.locale)}</p>
					<audio class="w-full" controls preload="none" src={`/api/v1/audio/memos/${encodeURIComponent(memo.id)}/audio`} aria-label={t('audio.recordingLabel', { title: memo.title })}></audio>
					{#if speech[memo.id]?.url}
						<audio class="w-full" controls autoplay src={speech[memo.id].url} aria-label={t('audio.speechLabel', { title: memo.title })}></audio>
					{/if}
					<div class="flex flex-wrap gap-2">
						{#if memo.status === 'ready'}
							<Button type="button" variant="outline" onclick={() => readAloud(memo)} disabled={speech[memo.id] !== undefined}>
								{speech[memo.id]?.state === 'loading' ? t('audio.readingAloud') : t('audio.readAloud')}
							</Button>
						{/if}
						{#if needsRetry(memo)}<Button type="button" variant="outline" onclick={() => retry(memo)}>{t('audio.retry')}</Button>{/if}
						<Button type="button" variant="outline" onclick={() => remove(memo)}>{t('audio.delete')}</Button>
					</div>
					{#if memo.status === 'ready'}
						<details ontoggle={(event) => { if ((event.currentTarget as HTMLDetailsElement).open) void loadDetail(memo.id); }}>
							<summary class="cursor-pointer font-semibold">{t('audio.transcript')}</summary>
							{#if details[memo.id]}
								<p class="mx-0 mt-3 mb-0 whitespace-pre-wrap [overflow-wrap:anywhere]">{details[memo.id].transcript ?? t('audio.noTranscript')}</p>
							{:else}<p role="status">{t('audio.loading')}</p>{/if}
						</details>
					{/if}
				</li>
			{/each}
		</ul>
	{/if}
</Card>
