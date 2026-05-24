const state = {
    status: "idle", sessionId: null, selectedSession: null,
    selectedTranscript: null, startTime: null, timerInterval: null,
    ws: null, vuData: new Float32Array(60).fill(0), vuIndex: 0,
    livePolling: null, ttyMode: false,
};

const el = (id) => document.getElementById(id);
const btnRecord = el("btn-record"), btnPause = el("btn-pause"), btnStop = el("btn-stop");
const statusBadge = el("status-badge"), timerEl = el("timer");
const sessionIdEl = el("session-id"), modelNameEl = el("model-name");
const liveTranscript = el("live-transcript"), sessionsList = el("sessions-list");
const detailTitle = el("detail-title"), detailContent = el("detail-content");
const detailFooter = el("detail-footer"), detailSessionId = el("detail-session-id");
const transcriptTabs = el("transcript-tabs");
const vuCanvas = el("vu-canvas"), vuCtx = vuCanvas.getContext("2d");
const configDialog = el("config-dialog");
const audioEl = el("audio-el"), playerPlay = el("player-play");
const playerSeek = el("player-seek"), playerTime = el("player-time");
const playerVolume = el("player-volume");
const playIcon = el("play-icon"), pauseIcon = el("pause-icon");
const langSelect = el("lang-select");
let btnBusy = false;

// --- Theme ---
document.querySelectorAll(".theme-btn").forEach(btn => {
    btn.addEventListener("click", () => {
        document.body.dataset.theme = btn.dataset.theme;
        document.querySelectorAll(".theme-btn").forEach(b => b.classList.remove("active"));
        btn.classList.add("active");
        localStorage.setItem("voice-io-theme", btn.dataset.theme);
    });
});
const savedTheme = localStorage.getItem("voice-io-theme");
if (savedTheme) {
    document.body.dataset.theme = savedTheme;
    document.querySelectorAll(".theme-btn").forEach(b =>
        b.classList.toggle("active", b.dataset.theme === savedTheme));
}

// --- Wake-word toggle ---
async function refreshWakewordState() {
    const d = await api("config", "GET");
    const btn = el("btn-wakeword");
    btn.classList.toggle("active", !!d.wakeword_enabled);
    btn.title = d.wakeword_enabled
        ? `Wake-word ON ("${d.wakeword}") — click to disable`
        : "Wake-word OFF — click to enable";
}
el("btn-wakeword").addEventListener("click", async () => {
    const btn = el("btn-wakeword");
    const nowOn = !btn.classList.contains("active");
    await fetch("/api/config", {
        method: "PUT", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({ wakeword_enabled: nowOn }),
    });
    await refreshWakewordState();
});
refreshWakewordState();

// --- Config ---
el("btn-config").addEventListener("click", async () => {
    const [d, devData] = await Promise.all([api("config", "GET"), api("devices", "GET")]);
    el("cfg-wakeword").value = d.wakeword;
    el("cfg-stop-phrase").value = d.stop_phrase;
    el("cfg-model").value = d.model;
    el("cfg-language").value = d.language;
    el("cfg-chunk").value = d.chunk_duration;
    el("cfg-silence-timeout").value = d.silence_timeout;
    el("cfg-silence-threshold").value = d.silence_threshold;
    el("cfg-sample-rate").value = d.sample_rate + " Hz";
    el("cfg-vault").value = d.vault_dir;
    const devSelect = el("cfg-device");
    devSelect.innerHTML = '<option value="default">System Default</option>' +
        devData.devices.map(dev => `<option value="${dev.name}">${dev.name} (${dev.channels}ch)</option>`).join("");
    devSelect.value = devData.current;
    configDialog.showModal();
});
el("cfg-close").addEventListener("click", () => configDialog.close());
el("cfg-save").addEventListener("click", async () => {
    await fetch("/api/config", {
        method: "PUT", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({
            stop_phrase: el("cfg-stop-phrase").value,
            model: el("cfg-model").value,
            language: el("cfg-language").value,
            chunk_duration: parseInt(el("cfg-chunk").value),
            silence_timeout: parseInt(el("cfg-silence-timeout").value),
            silence_threshold: parseFloat(el("cfg-silence-threshold").value),
            device: el("cfg-device").value,
        }),
    });
    configDialog.close();
});
configDialog.addEventListener("click", (e) => { if (e.target === configDialog) configDialog.close(); });

// --- Audio Player ---
playerPlay.addEventListener("click", () => {
    if (audioEl.paused) { audioEl.play(); playIcon.style.display = "none"; pauseIcon.style.display = ""; }
    else { audioEl.pause(); playIcon.style.display = ""; pauseIcon.style.display = "none"; }
});
audioEl.addEventListener("timeupdate", () => {
    if (audioEl.duration) {
        playerSeek.value = (audioEl.currentTime / audioEl.duration) * 100;
        playerTime.textContent = fmtTime(audioEl.currentTime) + " / " + fmtTime(audioEl.duration);
    }
});
audioEl.addEventListener("ended", () => { playIcon.style.display = ""; pauseIcon.style.display = "none"; });
playerSeek.addEventListener("input", () => {
    if (audioEl.duration) audioEl.currentTime = (playerSeek.value / 100) * audioEl.duration;
});
playerVolume.addEventListener("input", () => { audioEl.volume = playerVolume.value / 100; });
audioEl.volume = 0.8;
playerVolume.value = 80;

function fmtTime(s) {
    const m = Math.floor(s / 60), sec = Math.floor(s % 60);
    return m + ":" + String(sec).padStart(2, "0");
}

// --- API ---
async function api(endpoint, method = "POST") {
    return (await fetch(`/api/${endpoint}`, { method })).json();
}

// --- Buttons ---
btnRecord.addEventListener("click", async () => {
    if (btnBusy || state.status !== "idle") return;
    btnBusy = true; btnRecord.disabled = true;
    _ttyPrev = ""; _ttyQueue = "";
    const selGloss = glossarySelect.value || "";
    const selMacros = macroSelect.value || "";
    await fetch(`/api/start?language=${langSelect.value}&glossaries=${selGloss}&macros=${selMacros}`, { method: "POST" });
    btnBusy = false;
});
btnPause.addEventListener("click", async () => {
    if (btnBusy) return;
    btnBusy = true; btnPause.disabled = true;
    if (state.status === "recording") await api("pause");
    else if (state.status === "paused") await api("resume");
    btnBusy = false;
});
btnStop.addEventListener("click", async () => {
    if (btnBusy || state.status === "idle") return;
    btnBusy = true; btnStop.disabled = true; btnPause.disabled = true;
    await api("stop");
    stopLivePolling();
    btnBusy = false;
    setTimeout(fetchSessions, 1000);
});

// --- UI Update (from WebSocket) ---
function updateUI(data) {
    const prev = state.status;
    state.status = data.state;
    state.sessionId = data.session_id;

    statusBadge.textContent = data.state.toUpperCase();
    statusBadge.className = `badge ${data.state}`;

    const idle = data.state === "idle";
    if (!btnBusy) {
        btnRecord.disabled = !idle;
        langSelect.disabled = !idle;
        btnPause.disabled = idle;
        btnStop.disabled = idle;
    }
    btnRecord.classList.toggle("active", data.state === "recording");
    liveTranscript.classList.toggle("terminal-green", data.state === "recording" && state.ttyMode);

    sessionIdEl.textContent = data.session_id || "\u2014";
    modelNameEl.textContent = (data.device || "default") + " | " + (data.model || "\u2014");

    // timer
    if ((data.state === "recording" || data.state === "paused") && !state.timerInterval) {
        showCheatSheet();
        state.startTime = Date.now();
        state.timerInterval = setInterval(updateTimer, 1000);
    } else if (idle && state.timerInterval) {
        clearInterval(state.timerInterval);
        state.timerInterval = null;
        timerEl.textContent = "00:00";
    }

    // start/stop live polling
    if (data.state === "recording" && !state.livePolling) startLivePolling();
    if (idle && prev !== "idle") {
        hideCheatSheet();
        stopLivePolling();
        // poll a few times with delay to catch final transcription
        setTimeout(pollLiveTranscript, 500);
        setTimeout(pollLiveTranscript, 2000);
        setTimeout(pollLiveTranscript, 5000);
        setTimeout(fetchSessions, 2000);
        setTimeout(fetchSessions, 6000);
    }

    // VU
    state.vuData[state.vuIndex % state.vuData.length] = data.state === "recording" ? (data.peak || 0) : 0;
    state.vuIndex++;
}

function updateTimer() {
    if (!state.startTime) return;
    const s = Math.floor((Date.now() - state.startTime) / 1000);
    timerEl.textContent = String(Math.floor(s/60)).padStart(2,"0") + ":" + String(s%60).padStart(2,"0");
}

// --- Live transcript polling (independent of WebSocket) ---
function startLivePolling() {
    stopLivePolling();
    state.livePolling = setInterval(pollLiveTranscript, 2000);
    pollLiveTranscript();
}
function stopLivePolling() {
    if (state.livePolling) { clearInterval(state.livePolling); state.livePolling = null; }
}
let _ttyPrev = "";
let _ttyQueue = "";
let _ttyTimer = null;

function ttyFlush() {
    if (!_ttyQueue) { clearInterval(_ttyTimer); _ttyTimer = null; return; }
    const chunk = _ttyQueue.slice(0, 3);
    _ttyQueue = _ttyQueue.slice(3);
    liveTranscript.textContent += chunk;
    liveTranscript.scrollTop = liveTranscript.scrollHeight;
    if (!_ttyQueue && _ttyTimer) { clearInterval(_ttyTimer); _ttyTimer = null; }
}

async function pollLiveTranscript() {
    if (!state.sessionId) return;
    try {
        const d = await api(`sessions/${state.sessionId}`, "GET");
        if (d.transcripts) {
            const names = Object.keys(d.transcripts);
            if (names.length > 0) {
                const content = d.transcripts[names[names.length - 1]];
                const parts = content.split("---");
                const text = parts.length >= 3 ? parts.slice(2).join("---").trim() : "";
                if (text) {
                    if (state.ttyMode && state.status === "recording" && text.length > _ttyPrev.length) {
                        const newChars = text.slice(_ttyPrev.length);
                        _ttyQueue += newChars;
                        _ttyPrev = text;
                        if (!_ttyTimer) _ttyTimer = setInterval(ttyFlush, 30);
                    } else {
                        _ttyPrev = text;
                        liveTranscript.textContent = text;
                        liveTranscript.scrollTop = liveTranscript.scrollHeight;
                    }
                } else {
                    liveTranscript.innerHTML = '<p class="placeholder">Transcribing...</p>';
                }
            }
        }
    } catch(e) {}
}

async function fetchSessions() {
    const data = await api("sessions", "GET");
    renderSessions(data);
}

// --- Sessions List with Transcript Tree ---
function renderSessions(sessions) {
    if (!sessions || !sessions.length) {
        sessionsList.innerHTML = '<p class="placeholder">No sessions yet</p>';
        return;
    }
    sessionsList.innerHTML = sessions.map(s => {
        const sel = state.selectedSession === s.session_id ? " selected" : "";
        const dur = s.duration ? fmtTime(s.duration) : "";

        let treeHtml = "";
        if (s.transcripts && s.transcripts.length > 0) {
            treeHtml = '<div class="session-transcripts">' +
                s.transcripts.map(t =>
                    `<div class="session-transcript-item" onclick="event.stopPropagation();selectTranscript('${s.session_id}','${t.name}')">
                        <span class="t-name">${t.name.replace('.md','')}</span>
                        <span class="t-words">${t.words}w</span>
                        <button class="t-delete" onclick="event.stopPropagation();deleteTranscript('${s.session_id}','${t.name}')" title="Delete">\u00d7</button>
                    </div>`
                ).join("") +
                `<div class="session-transcript-item" onclick="event.stopPropagation();addTranscript('${s.session_id}')">
                    <span class="t-name" style="color:var(--accent-green)">+ add transcript</span>
                </div>` +
                '</div>';
        }

        return `<div class="session-item${sel}" data-id="${s.session_id}" onclick="selectSession('${s.session_id}')">
            <span class="session-id">${s.session_id}</span>
            <div class="session-meta">
                <span>${dur} \u2022 ${s.size_kb} KB</span>
                <div class="session-actions">
                    <button onclick="event.stopPropagation();renameSession('${s.session_id}')">rename</button>
                    <button class="danger" onclick="event.stopPropagation();deleteSession('${s.session_id}')">delete</button>
                </div>
            </div>
            ${treeHtml}
        </div>`;
    }).join("");
}

function esc(t) { const d = document.createElement("div"); d.textContent = t; return d.innerHTML; }

// --- Session + Transcript Selection ---
async function selectSession(sid) {
    state.selectedSession = sid;
    state.selectedTranscript = null;
    document.querySelectorAll(".session-item").forEach(e =>
        e.classList.toggle("selected", e.dataset.id === sid));
    detailTitle.textContent = sid;
    detailSessionId.textContent = sid;
    detailFooter.style.display = "";

    audioEl.src = `/api/sessions/${sid}/audio`;
    audioEl.load();
    playIcon.style.display = ""; pauseIcon.style.display = "none";
    playerSeek.value = 0; playerTime.textContent = "0:00";

    // on mobile, switch to detail panel
    if (window.innerWidth <= 1024) {
        document.querySelectorAll(".panel").forEach(p => p.classList.remove("active-panel"));
        document.getElementById("panel-right").classList.add("active-panel");
        document.querySelectorAll(".mobile-nav-btn").forEach(b => {
            b.classList.toggle("active", b.dataset.panel === "panel-right");
        });
    }

    try {
        const d = await api(`sessions/${sid}`, "GET");
        if (d.transcripts) {
            const names = Object.keys(d.transcripts);
            renderTranscriptTabs(sid, names);
            if (names.length > 0) {
                showTranscriptContent(d.transcripts[names[0]], names[0]);
            } else {
                detailContent.innerHTML = '<p class="placeholder">No transcripts. Use + to add one.</p>';
            }
        }
    } catch(e) {
        detailContent.innerHTML = '<p class="placeholder">Error loading session</p>';
    }
}

async function selectTranscript(sid, name) {
    if (state.selectedSession !== sid) {
        await selectSession(sid);
    }
    state.selectedTranscript = name;

    // on mobile, switch to detail panel
    if (window.innerWidth <= 1024) {
        document.querySelectorAll(".panel").forEach(p => p.classList.remove("active-panel"));
        document.getElementById("panel-right").classList.add("active-panel");
        document.querySelectorAll(".mobile-nav-btn").forEach(b => {
            b.classList.toggle("active", b.dataset.panel === "panel-right");
        });
    }

    try {
        const d = await api(`sessions/${sid}/transcript/${name}`, "GET");
        if (d.content) {
            showTranscriptContent(d.content, name);
            // update tabs
            transcriptTabs.querySelectorAll(".tab:not(.tab-add)").forEach(t =>
                t.classList.toggle("active", t.dataset.name === name));
        }
    } catch(e) {}
}

function showTranscriptContent(content, name) {
    state.selectedTranscript = name;
    const parts = content.split("---");
    let meta = "", text = "";
    if (parts.length >= 3) { meta = parts[1].trim(); text = parts.slice(2).join("---").trim(); }
    detailContent.innerHTML =
        `<div class="detail-meta">${esc(meta)}</div>` +
        `<div>${esc(text) || '<em class="placeholder">No text yet</em>'}</div>`;
    el("player-bar").style.display = text ? "" : "none";
}

function renderTranscriptTabs(sid, names) {
    let html = names.map(name => {
        const lang = name.split("_")[0].toUpperCase();
        const num = name.split("_")[1] || "";
        const active = state.selectedTranscript === name ? " active" : "";
        return `<button class="tab${active}" data-name="${name}" onclick="selectTranscript('${sid}','${name}')">${lang}${num ? ' #'+parseInt(num) : ''}</button>`;
    }).join("");
    html += `<button class="tab tab-add" onclick="addTranscript('${sid}')" title="Add transcript">+</button>`;
    if (state.selectedTranscript) {
        html += `<button class="tab" onclick="openCleanup('${sid}', state.selectedTranscript)" title="Clean up with LLM" style="color:var(--accent-yellow);border-color:var(--accent-yellow)">cleanup</button>`;
    }
    transcriptTabs.innerHTML = html;
}

async function addTranscript(sid) {
    const lang = prompt("Language (de, en, fr, es, ...):", "de");
    if (!lang) return;
    await fetch(`/api/sessions/${sid}/transcribe`, {
        method: "POST", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({ language: lang.trim().toLowerCase() }),
    });
    setTimeout(() => { fetchSessions(); selectSession(sid); }, 3000);
}

async function deleteTranscript(sid, name) {
    if (!confirm(`Delete ${name}?`)) return;
    await api(`sessions/${sid}/transcript/${name}`, "DELETE");
    fetchSessions();
    if (state.selectedSession === sid) selectSession(sid);
}


async function renameSession(sid) {
    const newName = prompt("New name for session:", sid);
    if (!newName || newName === sid) return;
    const resp = await fetch(`/api/sessions/${sid}/rename?new_name=${encodeURIComponent(newName)}`, { method: "PUT" });
    const data = await resp.json();
    if (data.error) { alert("Rename failed: " + data.error); return; }
    if (state.selectedSession === sid) state.selectedSession = data.new;
    fetchSessions();
    if (state.selectedSession === data.new) selectSession(data.new);
}

async function deleteSession(sid) {
    if (!confirm(`Delete session ${sid}?`)) return;
    audioEl.pause(); audioEl.src = "";
    await api(`sessions/${sid}`, "DELETE");
    if (state.selectedSession === sid) {
        state.selectedSession = null;
        detailTitle.textContent = "Transcript";
        detailContent.innerHTML = '<p class="placeholder">Select a session</p>';
        detailFooter.style.display = "none";
        el("player-bar").style.display = "none";
        transcriptTabs.innerHTML = "";
    }
    fetchSessions();
}

// --- Upload ---
el("btn-upload").addEventListener("click", () => el("upload-file").click());
el("upload-file").addEventListener("change", async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    const lang = el("upload-lang").value;
    const form = new FormData();
    form.append("file", file);
    const dlg = el("upload-progress-dialog");
    const fill = el("upload-progress-fill");
    const txt = el("upload-progress-text");
    fill.style.width = "0%";
    txt.textContent = "Uploading...";
    dlg.showModal();
    const resp = await fetch(`/api/upload?language=${lang}`, { method: "POST", body: form });
    el("upload-file").value = "";
    const data = await resp.json();
    if (!data.session_id) { dlg.close(); return; }
    txt.textContent = "0%";
    const poll = setInterval(async () => {
        const pr = await fetch(`/api/upload/progress/${data.session_id}`).then(r => r.json());
        if (pr.status === "converting") {
            fill.style.width = "0%";
            txt.textContent = "Converting audio...";
        } else if (pr.status === "transcribing" && pr.total > 0) {
            const pct = Math.round((pr.current / pr.total) * 100);
            fill.style.width = pct + "%";
            txt.textContent = `${pr.current}/${pr.total} chunks (${pct}%)`;
        } else if (pr.status === "done" || pr.status === "unknown") {
            fill.style.width = "100%";
            txt.textContent = "Done";
            clearInterval(poll);
            setTimeout(() => { dlg.close(); fetchSessions(); }, 600);
        }
    }, 1000);
});

// --- VU ---
function drawVU() {
    const w = vuCanvas.width, h = vuCanvas.height;
    const s = getComputedStyle(document.body);
    vuCtx.fillStyle = s.getPropertyValue("--vu-bg").trim();
    vuCtx.fillRect(0, 0, w, h);
    const green = s.getPropertyValue("--accent-green").trim();
    const yellow = s.getPropertyValue("--accent-yellow").trim();
    const red = s.getPropertyValue("--accent").trim();
    const len = state.vuData.length, bw = w / len;
    for (let i = 0; i < len; i++) {
        const v = state.vuData[(state.vuIndex + i) % len];
        const bh = Math.min(Math.max(v * h * 3, v > 0 ? 2 : 0), h * 0.95);
        vuCtx.fillStyle = v > 0.3 ? red : v > 0.1 ? yellow : green;
        vuCtx.fillRect(i * bw + 1, (h - bh) / 2, bw - 2, bh);
    }
    requestAnimationFrame(drawVU);
}

// --- WebSocket ---
function connectWS() {
    const ws = new WebSocket(`${location.protocol === "https:" ? "wss:" : "ws:"}//${location.host}/ws`);
    ws.onmessage = (e) => updateUI(JSON.parse(e.data));
    ws.onclose = () => setTimeout(connectWS, 2000);
    ws.onerror = () => ws.close();
    state.ws = ws;
}

// --- Resize ---
function initResize(handleId, panelId, dir) {
    const handle = el(handleId), panel = el(panelId);
    if (!handle || !panel) return;
    let startX, startW;
    handle.addEventListener("mousedown", (e) => {
        startX = e.clientX; startW = panel.offsetWidth;
        handle.classList.add("active");
        const onMove = (e) => {
            const delta = dir === "left" ? e.clientX - startX : startX - e.clientX;
            panel.style.width = Math.max(180, startW + delta) + "px";
        };
        const onUp = () => {
            handle.classList.remove("active");
            document.removeEventListener("mousemove", onMove);
            document.removeEventListener("mouseup", onUp);
        };
        document.addEventListener("mousemove", onMove);
        document.addEventListener("mouseup", onUp);
        e.preventDefault();
    });
}
initResize("resize-left", "panel-left", "left");
initResize("resize-right", "panel-right", "right");

// --- Mobile Nav ---
document.querySelectorAll(".mobile-nav-btn").forEach(btn => {
    btn.addEventListener("click", () => {
        document.querySelectorAll(".panel").forEach(p => p.classList.remove("active-panel"));
        document.getElementById(btn.dataset.panel).classList.add("active-panel");
        document.querySelectorAll(".mobile-nav-btn").forEach(b => b.classList.remove("active"));
        btn.classList.add("active");
    });
});


// --- Glossaries ---
const glossarySelect = el("glossary-select");
const glossDialog = el("glossary-dialog");
const glossList = el("gloss-list");
const glossEditor = el("gloss-editor");

async function loadGlossaryList() {
    const data = await api("glossaries", "GET");
    const prev = glossarySelect.value;
    glossarySelect.innerHTML = '<option value="">Glossar</option>' +
        data.map(g => `<option value="${g.name}">${g.name} (${g.entries})</option>`).join("");
    if (prev) glossarySelect.value = prev;
    glossList.innerHTML = data.map(g =>
        `<option value="${g.name}">${g.name} (${g.entries} entries)</option>`
    ).join("");
}

el("btn-glossary-edit").addEventListener("click", async () => {
    await loadGlossaryList();
    if (glossList.options.length > 0) {
        await loadGlossaryEditor(glossList.value);
    } else {
        glossEditor.value = "";
    }
    glossDialog.showModal();
});

glossList.addEventListener("change", () => loadGlossaryEditor(glossList.value));

async function loadGlossaryEditor(name) {
    if (!name) { glossEditor.value = ""; return; }
    const data = await api(`glossaries/${name}`, "GET");
    glossEditor.value = data.entries.map(e =>
        e.description ? `${e.word} | ${e.description}` : e.word
    ).join("\n");
}

el("gloss-new").addEventListener("click", async () => {
    const name = prompt("Glossary name:");
    if (!name) return;
    const safeName = name.trim().toLowerCase().replace(/[^a-z0-9_-]/g, "_");
    await fetch(`/api/glossaries/${safeName}`, {
        method: "PUT", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({ entries: [] }),
    });
    await loadGlossaryList();
    glossList.value = safeName;
    glossEditor.value = "";
});

el("gloss-del").addEventListener("click", async () => {
    const name = glossList.value;
    if (!name || !confirm(`Delete glossary "${name}"?`)) return;
    await api(`glossaries/${name}`, "DELETE");
    await loadGlossaryList();
    glossEditor.value = "";
});

el("gloss-save").addEventListener("click", async () => {
    const name = glossList.value;
    if (!name) { alert("Select or create a glossary first"); return; }
    const lines = glossEditor.value.split("\n").filter(l => l.trim());
    const entries = lines.map(line => {
        if (line.includes("|")) {
            const [word, desc] = line.split("|", 2);
            return { word: word.trim(), description: desc.trim() };
        }
        return { word: line.trim(), description: "" };
    });
    await fetch(`/api/glossaries/${name}`, {
        method: "PUT", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({ entries }),
    });
    await loadGlossaryList();
});

el("gloss-close").addEventListener("click", () => glossDialog.close());
glossDialog.addEventListener("click", (e) => { if (e.target === glossDialog) glossDialog.close(); });


// --- Macros ---
const macroSelect = el("macro-select");
const macroDialog = el("macro-dialog");
const macroList = el("macro-list");
const macroEditor = el("macro-editor");
const cheatSheet = el("cheat-sheet");

async function loadMacroList() {
    const data = await api("macros", "GET");
    const prev = macroSelect.value;
    macroSelect.innerHTML = '<option value="">Makros</option>' +
        data.map(m => `<option value="${m.name}">${m.name} (${m.entries})</option>`).join("");
    if (prev) macroSelect.value = prev;
    macroList.innerHTML = data.map(m =>
        `<option value="${m.name}">${m.name} (${m.entries} macros)</option>`
    ).join("");
}

el("btn-macro-edit").addEventListener("click", async () => {
    await loadMacroList();
    if (macroList.options.length > 0) await loadMacroEditor(macroList.value);
    else macroEditor.value = "";
    macroDialog.showModal();
});

macroList.addEventListener("change", () => loadMacroEditor(macroList.value));

async function loadMacroEditor(name) {
    if (!name) { macroEditor.value = ""; return; }
    const data = await api(`macros/${name}`, "GET");
    macroEditor.value = data.entries.map(e => {
        const rep = e.replacement.replace(/\n/g, "\\n").replace(/\t/g, "\\t");
        return `${e.trigger} | ${rep}`;
    }).join("\n");
}

el("macro-new").addEventListener("click", async () => {
    const name = prompt("Macro set name:");
    if (!name) return;
    const safeName = name.trim().toLowerCase().replace(/[^a-z0-9_-]/g, "_");
    await fetch(`/api/macros/${safeName}`, {
        method: "PUT", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({ entries: [] }),
    });
    await loadMacroList();
    macroList.value = safeName;
    macroEditor.value = "";
});

el("macro-del").addEventListener("click", async () => {
    const name = macroList.value;
    if (!name || !confirm(`Delete macro set "${name}"?`)) return;
    await api(`macros/${name}`, "DELETE");
    await loadMacroList();
    macroEditor.value = "";
});

el("macro-save").addEventListener("click", async () => {
    const name = macroList.value;
    if (!name) { alert("Select or create a macro set first"); return; }
    const lines = macroEditor.value.split("\n").filter(l => l.trim() && l.includes("|"));
    const entries = lines.map(line => {
        const [trigger, rep] = line.split("|", 2);
        return { trigger: trigger.trim(), replacement: rep.trim() };
    });
    await fetch(`/api/macros/${name}`, {
        method: "PUT", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({ entries }),
    });
    await loadMacroList();
});

el("macro-close").addEventListener("click", () => macroDialog.close());
macroDialog.addEventListener("click", (e) => { if (e.target === macroDialog) macroDialog.close(); });

async function showCheatSheet() {
    const selMacros = Array.from(macroSelect.selectedOptions).map(o => o.value);
    if (selMacros.length === 0) { cheatSheet.style.display = "none"; return; }

    let rows = "";
    for (const name of selMacros) {
        const data = await api(`macros/${name}`, "GET");
        for (const e of data.entries) {
            const rep = e.replacement.replace(/\n/g, "↵").replace(/\t/g, "⇥");
            rows += `<tr><td class="trigger">${esc(e.trigger)}</td><td class="replacement">${esc(rep)}</td></tr>`;
        }
    }

    if (rows) {
        cheatSheet.innerHTML = `<h4>Dictation Macros</h4><table>${rows}</table>`;
        cheatSheet.style.display = "";
    } else {
        cheatSheet.style.display = "none";
    }
}

function hideCheatSheet() {
    cheatSheet.style.display = "none";
}


// --- Cleanup ---
const cleanupDialog = el("cleanup-dialog");
const promptDialog = el("prompt-dialog");
let cleanupTarget = { sid: null, name: null };

async function loadPromptProfiles() {
    const data = await api("prompts", "GET");
    el("cleanup-profiles").innerHTML = data.map(p =>
        `<option value="${p.name}" ${p.name === "standard" ? "selected" : ""}>${p.name}</option>`
    ).join("");
    el("prompt-list").innerHTML = data.map(p =>
        `<option value="${p.name}">${p.name}</option>`
    ).join("");
    // populate recorder prompt dropdown
    const pa = el("prompt-active");
    if (pa) {
        const prev = pa.value;
        pa.innerHTML = '<option value="">Prompt</option>' +
            data.map(p => `<option value="${p.name}">${p.name}</option>`).join("");
        if (prev) pa.value = prev;
    }
}

function openCleanup(sid, transcriptName) {
    cleanupTarget = { sid, name: transcriptName };
    loadPromptProfiles();
    cleanupDialog.showModal();
}

el("cleanup-go").addEventListener("click", async () => {
    const profiles = Array.from(el("cleanup-profiles").selectedOptions).map(o => o.value);
    const provider = el("cleanup-provider").value;
    const model = el("cleanup-model").value;
    await fetch(`/api/sessions/${cleanupTarget.sid}/cleanup`, {
        method: "POST", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({
            transcript_name: cleanupTarget.name,
            profiles, provider, model,
        }),
    });
    cleanupDialog.close();
    setTimeout(() => { fetchSessions(); selectSession(cleanupTarget.sid); }, 5000);
});

el("cleanup-cancel").addEventListener("click", () => cleanupDialog.close());
cleanupDialog.addEventListener("click", (e) => { if (e.target === cleanupDialog) cleanupDialog.close(); });

// --- Prompt Editor ---
el("btn-prompt-edit").addEventListener("click", async () => {
    await loadPromptProfiles();
    if (el("prompt-list").options.length > 0) {
        await loadPromptEditor(el("prompt-list").value);
    }
    promptDialog.showModal();
});

el("prompt-list").addEventListener("change", () => loadPromptEditor(el("prompt-list").value));

async function loadPromptEditor(name) {
    if (!name) { el("prompt-editor").value = ""; return; }
    const data = await api(`prompts/${name}`, "GET");
    el("prompt-editor").value = data.content;
}

el("prompt-new").addEventListener("click", async () => {
    const name = prompt("Profile name:");
    if (!name) return;
    const safeName = name.trim().toLowerCase().replace(/[^a-z0-9_-]/g, "_");
    await fetch(`/api/prompts/${safeName}`, {
        method: "PUT", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({ content: "" }),
    });
    await loadPromptProfiles();
    el("prompt-list").value = safeName;
    el("prompt-editor").value = "";
});

el("prompt-del").addEventListener("click", async () => {
    const name = el("prompt-list").value;
    if (!name || !confirm(`Delete profile "${name}"?`)) return;
    await api(`prompts/${name}`, "DELETE");
    await loadPromptProfiles();
    el("prompt-editor").value = "";
});

el("prompt-save").addEventListener("click", async () => {
    const name = el("prompt-list").value;
    if (!name) return;
    await fetch(`/api/prompts/${name}`, {
        method: "PUT", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({ content: el("prompt-editor").value }),
    });
    await loadPromptProfiles();
});

el("prompt-close").addEventListener("click", () => promptDialog.close());
promptDialog.addEventListener("click", (e) => { if (e.target === promptDialog) promptDialog.close(); });

// --- Current Settings (left panel top) ---
async function updateCurrentSettings() {
    try {
        const d = await api("config", "GET");
        const box = el("current-settings");
        if (!box) return;
        box.innerHTML = [
            ["Device", d.device || "default"],
            ["Model", d.realtime_model + " / " + d.model],
            ["Stop", d.stop_phrase],
        ].map(([k, v]) =>
            `<div class="ls-row"><span>${k}</span><span class="ls-val">${v}</span></div>`
        ).join("");
    } catch(e) {}
}

// --- Right panel resource lists ---
async function loadRightResources() {
    try {
        const [glossaries, macros, prompts] = await Promise.all([
            api("glossaries", "GET"),
            api("macros", "GET"),
            api("prompts", "GET"),
        ]);
        const rg = el("right-glossary");
        const rm = el("right-macros");
        const rp = el("right-prompts");
        if (rg) rg.innerHTML = glossaries.map(g => `<option value="${g.name}">${g.name} (${g.entries})</option>`).join("");
        if (rm) rm.innerHTML = macros.map(m => `<option value="${m.name}">${m.name} (${m.entries})</option>`).join("");
        if (rp) rp.innerHTML = prompts.map(p => `<option value="${p.name}">${p.name}</option>`).join("");
    } catch(e) {}
}

async function previewResource(type, name) {
    if (!name) return;
    let heading = type + ": " + name;
    let body = "";
    try {
        if (type === "glossary") {
            const data = await api(`glossaries/${name}`, "GET");
            body = '<table class="res-table">' +
                data.entries.map(e =>
                    `<tr><td class="res-term">${esc(e.word)}</td><td class="res-desc">${esc(e.description || "")}</td></tr>`
                ).join("") + '</table>';
        } else if (type === "macro") {
            const data = await api(`macros/${name}`, "GET");
            body = '<table class="res-table">' +
                data.entries.map(e => {
                    const rep = e.replacement.replace(/\n/g, "↵").replace(/\t/g, "⇥");
                    return `<tr><td class="res-term">${esc(e.trigger)}</td><td class="res-desc">${esc(rep)}</td></tr>`;
                }).join("") + '</table>';
        } else if (type === "prompt") {
            const data = await api(`prompts/${name}`, "GET");
            body = `<div style="white-space:pre-wrap">${esc(data.content)}</div>`;
        }
    } catch(e) { body = "Error loading " + name; }
    detailContent.innerHTML = `<div class="detail-meta">${esc(heading)}</div>${body}`;
}

function setupRightList(selectId, type, otherIds) {
    const sel = el(selectId);
    if (!sel) return;
    sel.addEventListener("click", () => {
        if (sel.value) {
            otherIds.forEach(id => { const o = el(id); if (o) o.selectedIndex = -1; });
            previewResource(type, sel.value);
        }
    });
}
setupRightList("right-glossary", "glossary", ["right-macros", "right-prompts"]);
setupRightList("right-macros", "macro", ["right-glossary", "right-prompts"]);
setupRightList("right-prompts", "prompt", ["right-glossary", "right-macros"]);

// --- TTY Mode Toggle ---
el("btn-tty")?.addEventListener("click", () => {
    state.ttyMode = !state.ttyMode;
    el("btn-tty").classList.toggle("active", state.ttyMode);
    localStorage.setItem("voice-io-tty", state.ttyMode ? "1" : "0");
});
state.ttyMode = localStorage.getItem("voice-io-tty") === "1";
if (state.ttyMode) el("btn-tty")?.classList.add("active");

// --- Init ---
api("status", "GET").then(updateUI);
updateCurrentSettings();
fetchSessions();
loadGlossaryList();
loadMacroList();
loadPromptProfiles();
loadRightResources();
connectWS();
drawVU();
