/**
 * HH Goa Voice Radar — RUN 2 Frontend
 *
 * Features:
 *   - Mode switcher (HOLOGRAM / TAP TO SPEAK) with state preservation
 *   - HOLOGRAM: animated orb state machine (idle/listening/processing/answering/refusal/error)
 *   - TAP TO SPEAK: recording + live transcription + structured response + sources accordion
 *   - Shared backend: both modes call the same /api/stt + /api/query pipeline
 *   - Performance dashboard: benchmark trigger + real P50/P70/P100 display
 *   - Structured API response consumption: refused/reason/latencies/strategy/context
 */

'use strict';

// ═══════════════════════════════════════════════════════════
// State
// ═══════════════════════════════════════════════════════════

const state = {
    mode: 'hologram',           // 'hologram' | 'tap'
    isRecording: false,
    mediaRecorder: null,
    audioChunks: [],
    stream: null,
    currentQuery: null,
    currentResult: null,
    benchmarkRunning: false,
    benchmarkPollInterval: null,
    strategySelected: () => document.getElementById('strategy-select').value,
};

// ═══════════════════════════════════════════════════════════
// DOM refs (lazily retrieved)
// ═══════════════════════════════════════════════════════════

const $ = id => document.getElementById(id);

// ═══════════════════════════════════════════════════════════
// Hologram state machine
// ═══════════════════════════════════════════════════════════

const HOLOGRAM_STATES = {
    idle:       { label: 'Ready to listen',        cls: '',                        btnText: 'Tap to Speak' },
    listening:  { label: 'Listening…',             cls: 'hologram-orb-listening',  btnText: 'Stop recording' },
    processing: { label: 'Finding the best answer…', cls: 'hologram-orb-processing', btnText: null },
    answering:  { label: 'Answer ready',           cls: 'hologram-orb-answering',  btnText: 'Ask again' },
    refusal:    { label: 'No answer available',    cls: 'hologram-orb-refusal',    btnText: 'Ask again' },
    error:      { label: 'Something went wrong',   cls: 'hologram-orb-error',      btnText: 'Try again' },
};

const ALL_ORB_CLASSES = Object.values(HOLOGRAM_STATES).map(s => s.cls).filter(Boolean);

function setHologramState(stateName) {
    const cfg = HOLOGRAM_STATES[stateName];
    if (!cfg) return;

    const orb = $('hologram-orb');
    const statusLabel = $('hologram-status');
    const actionBtn   = $('hologram-mic-btn');

    // Swap CSS state class
    orb.classList.remove(...ALL_ORB_CLASSES);
    if (cfg.cls) orb.classList.add(cfg.cls);

    statusLabel.textContent = cfg.label;

    if (cfg.btnText !== null) {
        actionBtn.textContent = cfg.btnText;
        actionBtn.style.display = '';
    } else {
        actionBtn.style.display = 'none';
    }
}

// ═══════════════════════════════════════════════════════════
// Mode switching
// ═══════════════════════════════════════════════════════════

function switchMode(targetMode) {
    if (state.mode === targetMode) return;

    // If recording, stop it cleanly
    if (state.isRecording) {
        cancelRecording();
    }

    state.mode = targetMode;

    document.querySelectorAll('.mode-tab').forEach(btn => {
        const active = btn.dataset.mode === targetMode;
        btn.classList.toggle('active', active);
        btn.setAttribute('aria-selected', String(active));
    });

    document.querySelectorAll('.mode-panel').forEach(panel => {
        panel.classList.toggle('active', panel.id === `${targetMode}-panel`);
    });
}

// ═══════════════════════════════════════════════════════════
// Recording (shared logic)
// ═══════════════════════════════════════════════════════════

async function startRecording(mode) {
    state.audioChunks = [];

    try {
        state.stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch (err) {
        console.error('Mic access failed:', err.name, err.message);
        handleRecordError(mode, `Microphone access denied: ${err.message}`);
        return;
    }

    const options = getBestMimeType();
    state.mediaRecorder = new MediaRecorder(state.stream, options);

    state.mediaRecorder.ondataavailable = e => {
        if (e.data && e.data.size > 0) state.audioChunks.push(e.data);
    };

    state.mediaRecorder.onstop = async () => {
        releaseMic();
        const audioBlob = new Blob(state.audioChunks, { type: state.mediaRecorder.mimeType || 'audio/webm' });
        await processAudio(audioBlob, mode);
    };

    state.mediaRecorder.start(200); // collect chunks every 200ms for waveform reactivity
    state.isRecording = true;

    if (mode === 'hologram') {
        setHologramState('listening');
    } else {
        $('tap-mic-btn').classList.add('recording');
        $('tap-label').textContent = 'Recording… tap to stop';
        $('tap-transcript-live').classList.remove('hidden');
        $('tap-transcript-text').textContent = 'Listening…';
        $('tap-cancel-btn').classList.remove('hidden');
    }
}

function stopRecording(mode) {
    if (!state.isRecording || !state.mediaRecorder) return;
    state.isRecording = false;
    state.mediaRecorder.stop();

    if (mode === 'hologram') {
        setHologramState('processing');
    } else {
        $('tap-mic-btn').classList.remove('recording');
        $('tap-label').textContent = 'Processing…';
        $('tap-transcript-text').textContent = 'Transcribing…';
    }
}

function cancelRecording() {
    if (!state.isRecording || !state.mediaRecorder) return;
    state.isRecording = false;

    // Remove the onstop handler so processAudio is not called
    state.mediaRecorder.onstop = null;
    state.mediaRecorder.stop();
    releaseMic();
    resetRecordingUI();
}

function releaseMic() {
    if (state.stream) {
        state.stream.getTracks().forEach(t => t.stop());
        state.stream = null;
    }
}

function resetRecordingUI() {
    $('tap-mic-btn').classList.remove('recording');
    $('tap-label').textContent = 'Tap to Speak';
    $('tap-transcript-live').classList.add('hidden');
    $('tap-cancel-btn').classList.add('hidden');
    setHologramState('idle');
}

function getBestMimeType() {
    const types = ['audio/webm;codecs=opus', 'audio/webm', 'audio/ogg', ''];
    for (const t of types) {
        if (t === '' || MediaRecorder.isTypeSupported(t)) {
            return t ? { mimeType: t } : {};
        }
    }
    return {};
}

function handleRecordError(mode, msg) {
    console.error('Recording error:', msg);
    if (mode === 'hologram') {
        setHologramState('error');
        $('hologram-status').textContent = msg.slice(0, 80);
    } else {
        $('tap-label').textContent = 'Error: ' + msg.slice(0, 60);
    }
    resetRecordingUI();
}

// ═══════════════════════════════════════════════════════════
// Audio → STT → Query pipeline
// ═══════════════════════════════════════════════════════════

async function processAudio(audioBlob, mode) {
    const ext = (state.mediaRecorder?.mimeType || '').includes('webm') ? 'webm' : 'wav';
    const formData = new FormData();
    formData.append('file', audioBlob, `audio.${ext}`);

    let transcript = null, languageCode = null;

    try {
        const sttRes = await fetch('/api/stt', { method: 'POST', body: formData });

        if (!sttRes.ok) {
            const err = await sttRes.json().catch(() => ({}));
            throw new Error(err.detail || `STT failed (${sttRes.status})`);
        }

        const sttData = await sttRes.json();
        transcript  = sttData.transcript?.trim();
        languageCode = sttData.language_code || null;

        if (!transcript) {
            if (mode === 'hologram') {
                setHologramState('idle');
                $('hologram-status').textContent = 'No speech detected';
            } else {
                $('tap-transcript-text').textContent = 'No speech detected';
            }
            return;
        }

        // Show transcript in TAP mode
        if (mode === 'tap') {
            $('tap-transcript-text').textContent = `"${transcript}"`;
        }

    } catch (err) {
        console.error('[STT] Error:', err);
        if (mode === 'hologram') {
            setHologramState('error');
            $('hologram-status').textContent = 'STT error: ' + err.message.slice(0, 60);
        } else {
            $('tap-label').textContent = 'STT failed';
            $('tap-transcript-text').textContent = err.message;
        }
        return;
    }

    await submitQuery(transcript, languageCode, mode);
}

// ═══════════════════════════════════════════════════════════
// Submit query to /api/query
// ═══════════════════════════════════════════════════════════

async function submitQuery(queryText, languageCode = null, mode = null) {
    if (!queryText?.trim()) return;
    mode = mode || state.mode;
    const strategy = state.strategySelected();

    // Update UI to processing state
    if (mode === 'hologram') {
        setHologramState('processing');
        $('hologram-answer-wrap').classList.add('hidden');
    } else {
        $('tap-results').classList.add('hidden');
        $('tap-label').textContent = 'Generating answer…';
    }

    let result = null;

    try {
        const res = await fetch('/api/query', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ query: queryText, language_code: languageCode, strategy }),
        });

        if (!res.ok) {
            const errData = await res.json().catch(() => ({}));
            throw new Error(errData.detail || `Query failed (${res.status})`);
        }

        result = await res.json();
    } catch (err) {
        console.error('[Query] Error:', err);
        if (mode === 'hologram') {
            setHologramState('error');
            $('hologram-status').textContent = 'Error: ' + err.message.slice(0, 70);
        } else {
            $('tap-label').textContent = 'Query failed';
            showTapError(queryText, err.message);
        }
        return;
    }

    state.currentQuery  = queryText;
    state.currentResult = result;

    if (mode === 'hologram') {
        renderHologramResult(result);
    } else {
        renderTapResult(queryText, result);
    }
}

// ═══════════════════════════════════════════════════════════
// HOLOGRAM result render
// ═══════════════════════════════════════════════════════════

function renderHologramResult(result) {
    const wrap      = $('hologram-answer-wrap');
    const answerEl  = $('hologram-answer-text');
    const stratEl   = $('hologram-strategy-chip');
    const latEl     = $('hologram-latency-chip');
    const chunksEl  = $('hologram-chunks-chip');
    const badge     = $('hologram-refused-badge');

    if (result.error) {
        setHologramState('error');
        $('hologram-status').textContent = 'Pipeline error: ' + (result.error_message || '').slice(0, 80);
        return;
    }

    answerEl.textContent = result.answer || '';
    stratEl.textContent  = `Strategy: ${result.strategy}`;
    latEl.textContent    = `${(result.excl_stt_latency * 1000).toFixed(0)}ms (excl. STT)`;
    chunksEl.textContent = `${result.retrieved_chunk_count} chunks`;

    if (result.refused) {
        wrap.classList.add('is-refusal');
        badge.textContent = result.refusal_reason?.replace(/_/g, ' ') || 'Refused';
        setHologramState('refusal');
    } else {
        wrap.classList.remove('is-refusal');
        setHologramState('answering');
    }

    wrap.classList.remove('hidden');
}

// ═══════════════════════════════════════════════════════════
// TAP result render
// ═══════════════════════════════════════════════════════════

function renderTapResult(queryText, result) {
    const resultsEl   = $('tap-results');
    const questionEl  = $('tap-question');
    const answerEl    = $('tap-answer');
    const metaEl      = $('tap-answer-meta');
    const refusedPill = $('tap-refused-pill');
    const sourcesAcc  = $('tap-sources-accordion');
    const sourcesBody = $('tap-sources-body');
    const sourcesCnt  = $('tap-sources-count');

    if (result.error) {
        showTapError(queryText, result.error_message || 'Unknown pipeline error');
        return;
    }

    questionEl.textContent = queryText;
    answerEl.textContent   = result.answer || '';

    // Refusal pill
    if (result.refused) {
        refusedPill.textContent = (result.refusal_reason || 'refused').replace(/_/g, ' ');
        refusedPill.classList.remove('hidden');
    } else {
        refusedPill.classList.add('hidden');
    }

    // Meta chips
    metaEl.innerHTML = '';
    const chips = [
        { label: `Strategy: ${result.strategy}` },
        { label: `${(result.excl_stt_latency * 1000).toFixed(0)}ms excl. STT` },
        { label: `${result.retrieved_chunk_count} chunks` },
    ];
    if (result.refused) chips.push({ label: `Reason: ${result.refusal_reason?.replace(/_/g,' ')}` });
    chips.forEach(c => {
        const span = document.createElement('span');
        span.className = 'meta-chip';
        span.textContent = c.label;
        metaEl.appendChild(span);
    });

    // Sources (collapsed by default)
    sourcesBody.innerHTML = '';
    const chunks = result.context || [];
    sourcesCnt.textContent = `${chunks.length} sources`;

    if (chunks.length === 0) {
        sourcesAcc.style.display = 'none';
    } else {
        sourcesAcc.style.display = '';
        sourcesAcc.removeAttribute('open'); // collapsed by default

        chunks.forEach((chunk, i) => {
            const item = document.createElement('div');
            item.className = 'source-item';

            const score = chunk.relevance_score ?? (1 / (1 + (chunk.distance ?? 0)));
            item.innerHTML = `
                <div class="source-item-header">
                    <span class="source-chip">Source ${i + 1}</span>
                    <span class="source-chip ${chunk.is_selected ? 'highlight' : ''}">
                        ${chunk.is_selected ? '★ Relevant' : 'Context'}
                    </span>
                    <span class="source-chip">Relevance: ${(score * 100).toFixed(1)}%</span>
                    <span class="source-chip">L2 dist: ${(chunk.distance ?? 0).toFixed(3)}</span>
                    <span class="source-chip">Strategy: ${chunk.strategy || result.strategy}</span>
                    ${chunk.query_type ? `<span class="source-chip">${chunk.query_type}</span>` : ''}
                </div>
                <p class="source-text">${escapeHtml(chunk.text || '')}</p>
            `;
            sourcesBody.appendChild(item);
        });
    }

    // Update status label
    $('tap-label').textContent = result.refused ? 'Answer refused' : 'Completed';
    $('tap-transcript-live').classList.add('hidden');
    $('tap-cancel-btn').classList.add('hidden');

    resultsEl.classList.remove('hidden');
}

function showTapError(queryText, errorMsg) {
    const resultsEl  = $('tap-results');
    const questionEl = $('tap-question');
    const answerEl   = $('tap-answer');

    questionEl.textContent = queryText;
    answerEl.textContent   = `Error: ${errorMsg}`;
    $('tap-refused-pill').classList.add('hidden');
    $('tap-answer-meta').innerHTML = '';
    $('tap-sources-accordion').style.display = 'none';
    resultsEl.classList.remove('hidden');
}

function escapeHtml(str) {
    return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

// ═══════════════════════════════════════════════════════════
// Performance Dashboard
// ═══════════════════════════════════════════════════════════

async function loadBenchmarkResults() {
    try {
        const res = await fetch('/api/benchmark/results');
        if (!res.ok) return;
        const data = await res.json();

        if (data.running) {
            showBenchmarkRunning(data.progress);
        } else {
            hideBenchmarkRunning();
        }

        if (data.results && Object.keys(data.results).length > 0) {
            renderBenchmarkResults(data.results);
        }
    } catch (err) {
        console.warn('[Benchmark] Failed to load results:', err);
    }
}

function showBenchmarkRunning(progress) {
    const bar = $('benchmark-status-bar');
    bar.classList.remove('hidden');
    $('run-benchmark-btn').disabled = true;

    if (progress && progress.total > 0) {
        $('benchmark-progress-text').textContent =
            `${progress.done} / ${progress.total} queries`;
    }
}

function hideBenchmarkRunning() {
    $('benchmark-status-bar').classList.add('hidden');
    $('run-benchmark-btn').disabled = false;
    state.benchmarkRunning = false;

    if (state.benchmarkPollInterval) {
        clearInterval(state.benchmarkPollInterval);
        state.benchmarkPollInterval = null;
    }
}

function renderBenchmarkResults(report) {
    const table    = $('perf-table');
    const tbody    = $('perf-table-body');
    const emptyMsg = $('perf-empty-msg');
    const notes    = $('perf-notes');

    emptyMsg.classList.add('hidden');
    table.classList.remove('hidden');
    notes.classList.remove('hidden');
    tbody.innerHTML = '';

    const overall = report.overall || {};
    const excl    = overall.excl_stt_latency_s || {};

    // Overall row
    tbody.appendChild(makeRow('Overall (excl. STT)', excl, true));

    // Per-stage rows
    const stages = report.per_stage_s || {};
    const stageLabels = {
        validate_input:      'Validate input',
        stt:                 'STT (voice only)',
        normalize:           'Lang detect',
        guardrail_pre:       'Guardrail pre',
        embedding_retrieval: 'Embed + Retrieve',
        guardrail_post:      'Guardrail post',
        generation:          'LLM Generation',
        grounding_check:     'Grounding check',
    };

    for (const [key, label] of Object.entries(stageLabels)) {
        if (stages[key]) {
            tbody.appendChild(makeRow(label, stages[key]));
        }
    }

    // Notes
    const meta = report.metadata || {};
    const meets = report.meets_200ms_target;
    $('perf-meets-target').innerHTML =
        `<strong>200ms target (P50, excl. STT):</strong> ` +
        (meets === true  ? '✅ MET' :
         meets === false ? '❌ NOT MET' : '—');

    $('perf-bottleneck').innerHTML =
        `<strong>Bottleneck stage:</strong> ${report.bottleneck_stage || '—'}`;

    $('perf-stt-note').textContent =
        meta.stt_note || 'STT stage excluded from latency calculations.';
}

function makeRow(label, stats, isOverall = false) {
    const tr = document.createElement('tr');
    if (isOverall) tr.className = 'row-overall';

    const fmt = v => v != null ? (v * 1000).toFixed(1) + 'ms' : '—';
    tr.innerHTML = `
        <td>${label}</td>
        <td>${fmt(stats.p50)}</td>
        <td>${fmt(stats.p70)}</td>
        <td>${fmt(stats.p100)}</td>
        <td>${fmt(stats.avg)}</td>
        <td>${fmt(stats.min)}</td>
        <td>${fmt(stats.max)}</td>
        <td>${stats.n ?? '—'}</td>
    `;
    return tr;
}

async function triggerBenchmark() {
    const strategy = state.strategySelected();
    $('run-benchmark-btn').disabled = true;

    try {
        const res = await fetch('/api/benchmark/run', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ strategy, max_queries: 100 }),
        });

        if (!res.ok) {
            const err = await res.json().catch(() => ({}));
            throw new Error(err.error || `Failed (${res.status})`);
        }

        state.benchmarkRunning = true;
        showBenchmarkRunning({ done: 0, total: 100 });

        // Poll for results
        state.benchmarkPollInterval = setInterval(async () => {
            await loadBenchmarkResults();
            if (!state.benchmarkRunning) {
                clearInterval(state.benchmarkPollInterval);
                state.benchmarkPollInterval = null;
            }
        }, 3000);

    } catch (err) {
        console.error('[Benchmark] Trigger failed:', err);
        $('run-benchmark-btn').disabled = false;
        alert('Failed to start benchmark: ' + err.message);
    }
}

// ═══════════════════════════════════════════════════════════
// Event wiring
// ═══════════════════════════════════════════════════════════

document.addEventListener('DOMContentLoaded', () => {

    // ── Mode switcher ────────────────────────────────────
    document.querySelectorAll('.mode-tab').forEach(btn => {
        btn.addEventListener('click', () => switchMode(btn.dataset.mode));
    });

    // ── HOLOGRAM mode ────────────────────────────────────
    const hologramBtn = $('hologram-mic-btn');
    hologramBtn.addEventListener('click', () => {
        if (state.isRecording) {
            stopRecording('hologram');
        } else if (['answering', 'refusal', 'error'].includes(getCurrentOrbState())) {
            // Reset for new question
            setHologramState('idle');
            $('hologram-answer-wrap').classList.add('hidden');
        } else {
            startRecording('hologram');
        }
    });

    $('hologram-text-btn').addEventListener('click', () => {
        const q = prompt('Type your query:');
        if (q?.trim()) submitQuery(q.trim(), null, 'hologram');
    });

    // ── TAP mode ─────────────────────────────────────────
    const tapMicBtn = $('tap-mic-btn');
    tapMicBtn.addEventListener('click', () => {
        if (state.isRecording) {
            stopRecording('tap');
        } else {
            startRecording('tap');
        }
    });

    $('tap-cancel-btn').addEventListener('click', () => {
        cancelRecording();
    });

    // Text fallback
    const tapTextInput  = $('tap-text-input');
    const tapTextSubmit = $('tap-text-submit');

    tapTextSubmit.addEventListener('click', () => {
        const q = tapTextInput.value.trim();
        if (q) {
            tapTextInput.value = '';
            submitQuery(q, null, 'tap');
        }
    });

    tapTextInput.addEventListener('keydown', e => {
        if (e.key === 'Enter') tapTextSubmit.click();
    });

    // ── Performance dashboard ─────────────────────────
    $('run-benchmark-btn').addEventListener('click', triggerBenchmark);

    $('test-refusal-btn').addEventListener('click', () => {
        const mode = state.mode;
        const offTopicQuery = 'What is the current stock price of Apple Inc?';
        submitQuery(offTopicQuery, 'en', mode);
    });

    // ── Strategy → footer update ──────────────────────
    const stratSel = $('strategy-select');
    $('footer-strategy').textContent = `Strategy: ${stratSel.value}`;
    stratSel.addEventListener('change', () => {
        $('footer-strategy').textContent = `Strategy: ${stratSel.value}`;
    });

    // ── Initial load: fetch any existing benchmark data ──
    loadBenchmarkResults();

    // Initial hologram state
    setHologramState('idle');
});

// Helper to read current orb state
function getCurrentOrbState() {
    const orb = $('hologram-orb');
    for (const [name, cfg] of Object.entries(HOLOGRAM_STATES)) {
        if (cfg.cls && orb.classList.contains(cfg.cls)) return name;
    }
    return 'idle';
}
