/**
 * HH Goa Voice Radar — RUN 3 Frontend
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

const BACKEND_URL = window.location.protocol === 'file:'
    ? 'http://127.0.0.1:8000'
    : (window.location.origin.includes('localhost') || window.location.origin.includes('127.0.0.1')
        ? ''
        : 'https://hh-goa-voice-radar.onrender.com');

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
    wakeWordEnabled: true,
    wakeWordRecognition: null,
    ttsEnabled: true,
    history: [],
    isSessionActive: false,
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
    awakened:   { label: 'Listening for query…',   cls: 'hologram-orb-awakened',   btnText: null },
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

    if (stateName === 'idle' && state.mode === 'hologram') {
        startWakeWordListener();
    }
}

// ═══════════════════════════════════════════════════════════
// Mode switching
// ═══════════════════════════════════════════════════════════

function switchMode(targetMode) {
    if (state.mode === targetMode) return;

    if (state.isSessionActive) {
        state.isSessionActive = false;
        const exitBtn = $('hologram-exit-session');
        if (exitBtn) exitBtn.classList.add('hidden');
    }

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

    if (targetMode === 'hologram') {
        startWakeWordListener();
    } else {
        stopWakeWordListener();
    }
}

// ═══════════════════════════════════════════════════════════
// Recording (shared logic)
// ═══════════════════════════════════════════════════════════

async function startRecording(mode) {
    state.audioChunks = [];
    state.recordingStartTime = Date.now();

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
        const duration = Date.now() - (state.recordingStartTime || 0);
        if (duration < 1000) {
            handleRecordError(mode, 'Recording too short. Please speak for at least 1 second.');
            return;
        }
        const audioBlob = new Blob(state.audioChunks, { type: state.mediaRecorder.mimeType || 'audio/webm' });
        await processAudio(audioBlob, mode);
    };

    state.mediaRecorder.start(200); // collect chunks every 200ms for waveform reactivity
    state.isRecording = true;

    if (mode === 'hologram') {
        setHologramState('listening');
        startAmplitudeAnalyzer(state.stream);
        startWakeWordListener(); // Start concurrent live stop phrase listener
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
        stopWakeWordListener(); // Pause concurrent stop phrase listener during processing
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
    stopAmplitudeAnalyzer();
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
        const sttRes = await fetch(`${BACKEND_URL}/api/stt`, { method: 'POST', body: formData });

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
            setTimeout(() => {
                if (getCurrentOrbState() === 'error') {
                    setHologramState('idle');
                    if (state.isSessionActive) {
                        startSessionListening();
                    } else if (state.wakeWordEnabled) {
                        startWakeWordListener();
                    }
                }
            }, 3000);
        } else {
            $('tap-label').textContent = 'STT failed';
            $('tap-transcript-text').textContent = err.message;
        }
        return;
    }

    await submitQuery(transcript, languageCode, mode);
}

// ═══════════════════════════════════════════════════════════
// Helper: Parse strategy changes from voice commands
// ═══════════════════════════════════════════════════════════

function parseStrategyCommand(text) {
    if (!text) return null;
    const clean = text.toLowerCase().trim().replace(/[,.?!]/g, '');

    // Differentiate: avoid treating informational questions/queries about strategies as commands
    if (clean.startsWith('what') || 
        clean.startsWith('how') || 
        clean.startsWith('why') || 
        clean.startsWith('explain') || 
        clean.startsWith('tell me about')) {
        return null;
    }

    let targetStrategy = null;
    if (clean.includes('hybrid')) targetStrategy = 'hybrid';
    else if (clean.includes('metadata')) targetStrategy = 'metadata';
    else if (clean.includes('sentence')) targetStrategy = 'sentence';
    else if (clean.includes('fixed')) targetStrategy = 'fixed';

    if (!targetStrategy) return null;

    const commandWords = ['change', 'switch', 'set', 'use', 'select', 'activate', 'toggle'];
    const hasCommandWord = commandWords.some(w => clean.includes(w));
    const hasStrategyWord = clean.includes('strategy') || clean.includes('retrieval') || clean.includes('mode');

    if (hasCommandWord || hasStrategyWord) {
        return targetStrategy;
    }

    return null;
}

// ═══════════════════════════════════════════════════════════
// Submit query to /api/query
// ═══════════════════════════════════════════════════════════

async function submitQuery(queryText, languageCode = null, mode = null) {
    if (!queryText?.trim()) return;
    mode = mode || state.mode;

    // Check for explicit session stop phrases if session is active
    if (mode === 'hologram' && state.isSessionActive) {
        const cleanText = queryText.toLowerCase().trim().replace(/[,.?!]/g, '');
        if (cleanText.includes('stop') || 
            cleanText.includes('exit') || 
            cleanText.includes('quit')) {
            console.log('[Session] Explicit stop phrase detected:', cleanText);
            endConversationalSession();
            return;
        }
    }

    // ── Voice Strategy Change Command ────────────────────────
    const targetStrategy = parseStrategyCommand(queryText);
    if (targetStrategy) {
        console.log('[Voice Command] Strategy change detected via voice:', targetStrategy);
        const stratSel = $('strategy-select');
        if (stratSel) {
            stratSel.value = targetStrategy;
            stratSel.dispatchEvent(new Event('change'));
        }

        // Voice read out confirmation
        speakAnswer(`Strategy switched to ${targetStrategy}.`, languageCode);

        // Reset state so user can speak the next actual query
        if (mode === 'hologram') {
            setHologramState('idle');
        } else {
            $('tap-label').textContent = `Strategy: ${targetStrategy}`;
            setTimeout(() => {
                resetRecordingUI();
            }, 1800);
        }
        return;
    }

    let cleanQuery = queryText;
    if (mode === 'hologram' && state.isSessionActive) {
        // Strip ending stop command phrases like "that's all", "thats all", "that is all"
        cleanQuery = cleanQuery.replace(/\b(that's all|thats all|that is all)\b/gi, '').trim();
        if (!cleanQuery) {
            console.log('[Session] Query contains only stop phrase, skipping submission.');
            return;
        }
    }

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
        const queryPayload = {
            query: cleanQuery,
            language_code: languageCode,
            strategy: strategy
        };
        if (state.history && state.history.length > 0) {
            queryPayload.history = state.history;
        }

        const res = await fetch(`${BACKEND_URL}/api/query`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(queryPayload),
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
            setTimeout(() => {
                if (getCurrentOrbState() === 'error') {
                    setHologramState('idle');
                    if (state.isSessionActive) {
                        startSessionListening();
                    } else if (state.wakeWordEnabled) {
                        startWakeWordListener();
                    }
                }
            }, 3000);
        } else {
            $('tap-label').textContent = 'Query failed';
            showTapError(queryText, err.message);
        }
        return;
    }

    state.currentQuery  = cleanQuery;
    state.currentResult = result;

    if (mode === 'hologram') {
        renderHologramResult(result, cleanQuery);
    } else {
        renderTapResult(cleanQuery, result);
    }

    // TTS voice readout callback (supports both modes)
    speakAnswer(result.answer, languageCode);
}

// ═══════════════════════════════════════════════════════════
// HOLOGRAM result render
// ═══════════════════════════════════════════════════════════

function renderHologramResult(result, queryText = '') {
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

    // ── Append to history ──
    if (queryText && queryText.trim()) {
        if (!state.history) state.history = [];
        state.history.push({ question: queryText, answer: result.answer || '' });
        if (state.history.length > 3) {
            state.history.shift(); // Keep last 3 exchanges
        }

        // Render history items
        const historyContainer = $('hologram-history-container');
        const historyChat = $('hologram-chat-history');
        if (historyChat && historyContainer) {
            historyChat.innerHTML = '';
            state.history.forEach(item => {
                const div = document.createElement('div');
                div.className = 'history-item';
                div.innerHTML = `
                    <div class="history-q">Q: ${escapeHtml(item.question)}</div>
                    <div class="history-a">${escapeHtml(item.answer)}</div>
                `;
                historyChat.appendChild(div);
            });
            historyContainer.classList.remove('hidden');
        }
    }

    // ── Collapsible sources accordion for Hologram Mode ──
    const sourcesAcc  = $('hologram-sources-accordion');
    const sourcesBody = $('hologram-sources-body');
    const sourcesCnt  = $('hologram-sources-count');
    if (sourcesAcc && sourcesBody && sourcesCnt) {
        sourcesBody.innerHTML = '';
        const chunks = result.context || [];
        sourcesCnt.textContent = `${chunks.length} sources`;

        if (chunks.length === 0) {
            sourcesAcc.classList.add('hidden');
        } else {
            sourcesAcc.classList.remove('hidden');
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
    }
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
        const res = await fetch(`${BACKEND_URL}/api/benchmark/results`);
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
    if (!bar) return;
    bar.classList.remove('hidden');
    const btn = $('run-benchmark-btn');
    if (btn) btn.disabled = true;

    if (progress && progress.total > 0) {
        $('benchmark-progress-text').textContent =
            `${progress.done} / ${progress.total} queries`;
    }
}

function hideBenchmarkRunning() {
    const bar = $('benchmark-status-bar');
    if (bar) bar.classList.add('hidden');
    const btn = $('run-benchmark-btn');
    if (btn) btn.disabled = false;
    state.benchmarkRunning = false;

    if (state.benchmarkPollInterval) {
        clearInterval(state.benchmarkPollInterval);
        state.benchmarkPollInterval = null;
    }
}

function renderBenchmarkResults(report) {
    const table    = $('perf-table');
    if (!table) return;
    const tbody    = $('perf-table-body');
    const emptyMsg = $('perf-empty-msg');
    const notes    = $('perf-notes');

    if (emptyMsg) emptyMsg.classList.add('hidden');
    table.classList.remove('hidden');
    if (notes) notes.classList.remove('hidden');
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
    const meetsEl = $('perf-meets-target');
    if (meetsEl) {
        meetsEl.innerHTML =
            `<strong>200ms target (P50, excl. STT):</strong> ` +
            (meets === true  ? '✅ MET' :
             meets === false ? '❌ NOT MET' : '—');
    }

    const bnEl = $('perf-bottleneck');
    if (bnEl) {
        bnEl.innerHTML =
            `<strong>Bottleneck stage:</strong> ${report.bottleneck_stage || '—'}`;
    }

    const sttNoteEl = $('perf-stt-note');
    if (sttNoteEl) {
        sttNoteEl.textContent =
            meta.stt_note || 'STT stage excluded from latency calculations.';
    }
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
        const res = await fetch(`${BACKEND_URL}/api/benchmark/run`, {
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
        } else if (['answering', 'refusal'].includes(getCurrentOrbState())) {
            // Touch-barge-in: cancel speech and start recording immediately
            window.speechSynthesis.cancel();
            startRecording('hologram');
        } else if (getCurrentOrbState() === 'error') {
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

    const exitSessionBtn = $('hologram-exit-session');
    if (exitSessionBtn) {
        exitSessionBtn.addEventListener('click', () => {
            console.log('[Session] Exit button clicked.');
            endConversationalSession();
        });
    }

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
    const runBench = $('run-benchmark-btn');
    if (runBench) {
        runBench.addEventListener('click', triggerBenchmark);
    }
    const testRefusal = $('test-refusal-btn');
    if (testRefusal) {
        testRefusal.addEventListener('click', () => {
            const mode = state.mode;
            const offTopicQuery = 'What is the current stock price of Apple Inc?';
            submitQuery(offTopicQuery, 'en', mode);
        });
    }

    // ── Strategy → footer update ──────────────────────
    const stratSel = $('strategy-select');
    $('footer-strategy').textContent = `Strategy: ${stratSel.value}`;
    stratSel.addEventListener('change', () => {
        $('footer-strategy').textContent = `Strategy: ${stratSel.value}`;
    });

    // ── Initial load: fetch any existing benchmark data ──
    loadBenchmarkResults();

    // Wake word is permanently active by default, listening for "Hey Hacker House"

    // ── TTS voice toggle wiring ───────────────────────
    const ttsToggle = $('hologram-tts-toggle');
    if (ttsToggle) {
        ttsToggle.addEventListener('click', () => {
            state.ttsEnabled = !state.ttsEnabled;
            ttsToggle.classList.toggle('active', state.ttsEnabled);
            if (state.ttsEnabled) {
                ttsToggle.innerHTML = '<span class="tts-status-dot"></span> Voice Readout: On';
            } else {
                ttsToggle.innerHTML = '<span class="tts-status-dot"></span> Voice Readout: Muted';
                window.speechSynthesis.cancel();
            }
        });
    }

    // Initial hologram state
    setHologramState('idle');
    initWakeWordListener();

    // ── Introduction Voice Logic ─────────────────────
    let hasIntroduced = false;
    function triggerIntroduction() {
        if (hasIntroduced) return;
        hasIntroduced = true;

        // Clean up event listeners immediately
        document.removeEventListener('click', triggerIntroduction);
        document.removeEventListener('touchstart', triggerIntroduction);

        const introText = "Hello Sir, I am the Hacker House Assistant. Welcome to Hacker House Goa 2026. How can I help you today?";

        // Wait for voices to populate if they aren't loaded yet
        if (window.speechSynthesis.getVoices().length === 0) {
            const handleVoicesChanged = () => {
                speakAnswer(introText, 'en');
            };
            window.speechSynthesis.addEventListener('voiceschanged', handleVoicesChanged, { once: true });
        } else {
            speakAnswer(introText, 'en');
        }
    }

    // Try auto-play after 800ms delay
    setTimeout(() => {
        try {
            triggerIntroduction();
        } catch (e) {
            console.log('[TTS] Auto-play introduction blocked. Awaiting user interaction.');
        }
    }, 800);

    // Fallback: Trigger on first user interaction anywhere on the document
    document.addEventListener('click', triggerIntroduction);
    document.addEventListener('touchstart', triggerIntroduction);
});

// Helper to read current orb state
function getCurrentOrbState() {
    const orb = $('hologram-orb');
    for (const [name, cfg] of Object.entries(HOLOGRAM_STATES)) {
        if (cfg.cls && orb.classList.contains(cfg.cls)) return name;
    }
    return 'idle';
}

// ═══════════════════════════════════════════════════════════
// Wake Word Activation Logic
// ═══════════════════════════════════════════════════════════

function initWakeWordListener() {
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SpeechRecognition) {
        console.warn('Web Speech API (SpeechRecognition) is not supported in this browser.');
        state.wakeWordEnabled = false;
        return;
    }

    const recognition = new SpeechRecognition();
    recognition.continuous = true;
    recognition.interimResults = true;
    recognition.lang = 'en-IN'; // Optimized for Indian accent transcription speed and accuracy

    recognition.onresult = async event => {
        const currentOrb = getCurrentOrbState();

        // 1. Wake word matching (only when idle/passive)
        if (state.wakeWordEnabled && !state.isRecording && currentOrb === 'idle') {
            for (let i = event.resultIndex; i < event.results.length; ++i) {
                const transcript = (event.results[i][0].transcript || '').toLowerCase().trim();
                console.log('[WakeWord] Passive check:', transcript);
                const cleaned = transcript.replace(/[,.?!]/g, '').trim();
                if (cleaned.includes('hey hacker house') || cleaned.includes('hey hackerhouse') || 
                    cleaned.includes('hacker house') || cleaned.includes('hackerhouse')) {
                    console.log('[WakeWord] Phrase matched! Activating...');
                    triggerWakeActivation();
                    break;
                }
            }
            return;
        }

        // 2. Continuous session stop phrase real-time detection (while recording)
        if (state.isSessionActive && state.isRecording && currentOrb === 'listening') {
            for (let i = event.resultIndex; i < event.results.length; ++i) {
                const transcript = (event.results[i][0].transcript || '').toLowerCase().trim();
                console.log('[Session] Real-time stop check:', transcript);
                const cleaned = transcript.replace(/[,.?!]/g, '').trim();
                if (cleaned.includes('stop') || cleaned.includes('exit') || cleaned.includes('quit')) {
                    console.log('[Session] Live stop word triggered! Ending session instantly.');
                    endConversationalSession();
                    break;
                }
                if (cleaned.includes('thats all') || cleaned.includes("that's all") || cleaned.includes('that is all')) {
                    console.log('[Session] Live submit command triggered! Completing and proposing query.');
                    stopRecording('hologram');
                    break;
                }
            }
        }
    };

    recognition.onerror = event => {
        console.warn('[WakeWord] Recognition error:', event.error);
        const shouldRun = state.wakeWordEnabled || (state.isSessionActive && state.isRecording);
        if (shouldRun && state.mode === 'hologram' && ['idle', 'listening'].includes(getCurrentOrbState())) {
            setTimeout(() => {
                try { recognition.start(); } catch(_) {}
            }, 1000);
        }
    };

    recognition.onend = () => {
        const shouldRun = state.wakeWordEnabled || (state.isSessionActive && state.isRecording);
        if (shouldRun && state.mode === 'hologram' && ['idle', 'listening'].includes(getCurrentOrbState())) {
            try { recognition.start(); } catch(_) {}
        }
    };

    state.wakeWordRecognition = recognition;
    startWakeWordListener();
}

function startWakeWordListener() {
    const shouldRun = state.wakeWordEnabled || (state.isSessionActive && state.isRecording);
    if (!shouldRun || !state.wakeWordRecognition || state.mode !== 'hologram') return;
    const currentOrb = getCurrentOrbState();
    if (currentOrb !== 'idle' && currentOrb !== 'listening') return;

    try {
        state.wakeWordRecognition.start();
        console.log('[WakeWord] Listener started');
    } catch (err) {
        // Safe to ignore
    }
}

function stopWakeWordListener() {
    if (state.wakeWordRecognition) {
        try {
            state.wakeWordRecognition.stop();
            console.log('[WakeWord] Listener stopped');
        } catch (err) {
            // Safe to ignore
        }
    }
}

async function triggerWakeActivation() {
    state.isSessionActive = true;
    setHologramState('awakened');
    stopWakeWordListener();
    playWakeSound();

    const exitBtn = $('hologram-exit-session');
    if (exitBtn) exitBtn.classList.remove('hidden');

    // 0.8s pause for visual expansion and audio chime before starting mic stream
    await new Promise(resolve => setTimeout(resolve, 800));
    await startRecording('hologram');
}

function playWakeSound() {
    try {
        const AudioContext = window.AudioContext || window.webkitAudioContext;
        if (!AudioContext) return;
        const ctx = new AudioContext();
        
        // High, crisp rising Jarvis-style chime
        const osc = ctx.createOscillator();
        const gain = ctx.createGain();
        
        osc.connect(gain);
        gain.connect(ctx.destination);
        
        osc.type = 'sine';
        const now = ctx.currentTime;
        
        // Double tone frequency sweep: 600Hz -> 880Hz
        osc.frequency.setValueAtTime(600, now);
        osc.frequency.exponentialRampToValueAtTime(880, now + 0.15);
        
        gain.gain.setValueAtTime(0.08, now); // low, polite volume
        gain.gain.exponentialRampToValueAtTime(0.001, now + 0.35);
        
        osc.start(now);
        osc.stop(now + 0.35);
    } catch (err) {
        console.warn('Audio feedback failed:', err);
    }
}

// ═══════════════════════════════════════════════════════════
// Live Microphone Waveform Amplitude Analyzer
// ═══════════════════════════════════════════════════════════

let audioCtx = null;
let analyser = null;
let animFrameId = null;

function startAmplitudeAnalyzer(stream) {
    try {
        const AudioContext = window.AudioContext || window.webkitAudioContext;
        if (!AudioContext) return;

        audioCtx = new AudioContext();
        analyser = audioCtx.createAnalyser();
        analyser.fftSize = 64;
        
        const source = audioCtx.createMediaStreamSource(stream);
        source.connect(analyser);

        const bufferLength = analyser.frequencyBinCount;
        const dataArray = new Uint8Array(bufferLength);
        const spans = document.querySelectorAll('#hologram-waveform span');

        let lastActiveTime = Date.now();
        let hasSignal = false;

        function updateWaveform() {
            if (!analyser) return;
            analyser.getByteFrequencyData(dataArray);

            spans.forEach((span, i) => {
                const binValue = dataArray[i % bufferLength] || 0;
                const percent = binValue / 255;
                if (percent > 0.04) {
                    hasSignal = true;
                }
                const height = 4 + (percent * 36);
                span.style.height = `${height}px`;
            });

            if (hasSignal) {
                lastActiveTime = Date.now();
            }

            if (state.isSessionActive) {
                const elapsed = Date.now() - lastActiveTime;
                const secondsLeft = Math.ceil((8000 - elapsed) / 1000);
                
                if (elapsed >= 8000) {
                    console.log('[Session] Silence timeout triggered.');
                    handleSessionTimeout();
                    return; // Stop animation loop
                } else {
                    const statusLabel = $('hologram-status');
                    if (statusLabel) {
                        statusLabel.textContent = `Listening… (Auto-mute in ${secondsLeft}s)`;
                    }
                }
            }

            hasSignal = false; // Reset for next frame
            animFrameId = requestAnimationFrame(updateWaveform);
        }

        $('hologram-orb').classList.add('live-reactive');
        updateWaveform();
    } catch (err) {
        console.warn('Failed to start audio analyzer:', err);
    }
}

function stopAmplitudeAnalyzer() {
    if (animFrameId) {
        cancelAnimationFrame(animFrameId);
        animFrameId = null;
    }
    if (audioCtx) {
        audioCtx.close();
        audioCtx = null;
    }
    analyser = null;
    
    const spans = document.querySelectorAll('#hologram-waveform span');
    spans.forEach(span => {
        span.style.height = '';
    });
    $('hologram-orb').classList.remove('live-reactive');
}

// ═══════════════════════════════════════════════════════════
// Text to Speech (TTS) Output with Language Matching
// ═══════════════════════════════════════════════════════════

function speakAnswer(text, langHint = null) {
    if (!text) return;

    if (!state.ttsEnabled) {
        console.log('[TTS] Muted. Resuming wake/session listening directly.');
        if (state.mode === 'hologram') {
            if (state.isSessionActive) {
                startSessionListening();
            } else if (state.wakeWordEnabled) {
                startWakeWordListener();
            }
        }
        return;
    }

    // Stop any active speech synthesis
    window.speechSynthesis.cancel();

    // Pause wake-word listener so assistant doesn't hear itself
    const originalWakeWordState = state.wakeWordEnabled;
    if (originalWakeWordState) {
        stopWakeWordListener();
    }

    const utterance = new SpeechSynthesisUtterance(text);

    // Resolve target language code
    let lang = 'en';
    if (langHint) {
        const h = langHint.toLowerCase();
        if (h.startsWith('hi')) lang = 'hi';
        else if (h.startsWith('te')) lang = 'te';
        else if (h.startsWith('kn')) lang = 'kn';
        else if (h.startsWith('bn')) lang = 'bn';
        else if (h.startsWith('ta')) lang = 'ta';
        else if (h.startsWith('mr') || h.startsWith('mar')) lang = 'hi'; // fallback to Hindi voice for Devanagari
        else if (h.startsWith('ru')) lang = 'ru';
    } else {
        lang = detectTextLanguage(text);
    }

    let synthLang = 'en-US';
    if (lang === 'hi') synthLang = 'hi-IN';
    else if (lang === 'te') synthLang = 'te-IN';
    else if (lang === 'kn') synthLang = 'kn-IN';
    else if (lang === 'bn') synthLang = 'bn-IN';
    else if (lang === 'ta') synthLang = 'ta-IN';
    else if (lang === 'ru') synthLang = 'ru-RU';

    utterance.lang = synthLang;

    // Fetch voices and find the best available voice matching the language prefix
    const voices = window.speechSynthesis.getVoices();
    let matchedVoice = null;
    const matchingVoices = voices.filter(v => v.lang.toLowerCase().startsWith(lang.toLowerCase()));
    
    if (matchingVoices.length > 0) {
        // Prioritize: 1. Google Web Voices (highly natural)
        matchedVoice = matchingVoices.find(v => v.name.toLowerCase().includes('google'));
        
        // 2. Apple Natural / Premium / Enhanced Voices
        if (!matchedVoice) {
            matchedVoice = matchingVoices.find(v => 
                v.name.toLowerCase().includes('natural') || 
                v.name.toLowerCase().includes('premium') || 
                v.name.toLowerCase().includes('enhanced')
            );
        }
        
        // 3. Known natural standard voice names
        if (!matchedVoice) {
            const premiumNames = ['samantha', 'daniel', 'alex', 'karen', 'moira', 'tessa', 'veena', 'rishi'];
            for (const name of premiumNames) {
                const found = matchingVoices.find(v => v.name.toLowerCase().includes(name));
                if (found) {
                    matchedVoice = found;
                    break;
                }
            }
        }
        
        // 4. Default fallback
        if (!matchedVoice) {
            matchedVoice = matchingVoices[0];
        }
    }

    if (matchedVoice) {
        utterance.voice = matchedVoice;
        utterance.rate = 0.96;  // Measured speaking rate for high clarity
        utterance.pitch = 1.0;
        console.log(`[TTS] Speaking using voice: ${matchedVoice.name} (${matchedVoice.lang})`);
    } else {
        console.warn(`[TTS] No matching browser voice found for prefix: ${lang} (${synthLang}). Skipping playback.`);
        // Restore wake-word listener
        if (originalWakeWordState) {
            startWakeWordListener();
        }
        if (state.mode === 'hologram' && state.isSessionActive) {
            startSessionListening();
        }
        return;
    }

    utterance.onend = () => {
        console.log('[TTS] Speech finished.');
        if (originalWakeWordState) {
            startWakeWordListener();
        }
        if (state.mode === 'hologram' && state.isSessionActive) {
            startSessionListening();
        }
    };

    utterance.onerror = (e) => {
        console.error('[TTS] Speech error:', e);
        if (originalWakeWordState) {
            startWakeWordListener();
        }
        if (state.mode === 'hologram' && state.isSessionActive) {
            startSessionListening();
        }
    };

    window.speechSynthesis.speak(utterance);
}

function detectTextLanguage(text) {
    if (!text) return 'en';
    
    // Check Unicode ranges
    // Hindi/Devanagari: \u0900-\u097F
    if (/[\u0900-\u097F]/.test(text)) return 'hi';
    // Bengali: \u0980-\u09FF
    if (/[\u0980-\u09FF]/.test(text)) return 'bn';
    // Telugu: \u0c00-\u0c7f
    if (/[\u0C00-\u0C7F]/.test(text)) return 'te';
    // Kannada: \u0c80-\u0cff
    if (/[\u0C80-\u0CFF]/.test(text)) return 'kn';
    // Tamil: \u0b80-\u0bff
    if (/[\u0B80-\u0BFF]/.test(text)) return 'ta';
    // Russian/Cyrillic: \u0400-\u04FF
    if (/[\u0400-\u04FF]/.test(text)) return 'ru';
    
    return 'en';
}

// ═══════════════════════════════════════════════════════════
// Conversational Session Controllers
// ═══════════════════════════════════════════════════════════

function startSessionListening() {
    if (state.mode !== 'hologram' || !state.isSessionActive) return;
    if (state.isRecording) return;
    
    console.log('[Session] Starting next turn...');
    startRecording('hologram');
}

function clearConversationalHistory() {
    state.history = [];
    const historyContainer = $('hologram-history-container');
    const historyChat = $('hologram-chat-history');
    if (historyChat && historyContainer) {
        historyChat.innerHTML = '';
        historyContainer.classList.add('hidden');
    }
}

function endConversationalSession() {
    console.log('[Session] Terminating conversational session.');
    state.isSessionActive = false;
    window.speechSynthesis.cancel();
    
    if (state.isRecording) {
        cancelRecording();
    }
    
    const exitBtn = $('hologram-exit-session');
    if (exitBtn) exitBtn.classList.add('hidden');
    
    clearConversationalHistory();
    setHologramState('idle');
    startWakeWordListener();
}

function handleSessionTimeout() {
    console.log('[Session] Silence timeout: returning to passive idle.');
    state.isSessionActive = false;
    
    if (state.isRecording) {
        cancelRecording();
    }
    
    const exitBtn = $('hologram-exit-session');
    if (exitBtn) exitBtn.classList.add('hidden');
    
    clearConversationalHistory();
    setHologramState('idle');
    $('hologram-status').textContent = 'Session timed out due to silence';
    startWakeWordListener();
}



