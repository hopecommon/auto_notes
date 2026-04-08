// ==UserScript==
// @name         SJTU Live QR Auto Score
// @namespace    http://tampermonkey.net/
// @version      0.3.0
// @description  Unattended QR detection on playback page + worker tab for auto login/check-in.
// @author       auto_notes
// @match        *://*.sjtu.edu.cn/*
// @grant        GM_setClipboard
// @grant        GM_addStyle
// @grant        GM_openInTab
// @grant        GM_setValue
// @grant        GM_getValue
// @grant        GM_addValueChangeListener
// @require      https://cdn.jsdelivr.net/npm/jsqr@1.4.0/dist/jsQR.js
// @run-at       document-idle
// ==/UserScript==

(function () {
    "use strict";

    const SCRIPT_KEY = "__sjtu_live_qr_auto_score_v3__";
    if (window[SCRIPT_KEY]) {
        return;
    }
    window[SCRIPT_KEY] = true;

    const MODE = {
        scanner: "scanner",
        worker: "worker",
        idle: "idle",
    };

    const STORAGE = {
        task: "sjtu_qr_task_v1",
        result: "sjtu_qr_result_v1",
        loginUser: "sjtu_qr_login_user_v1",
        loginPass: "sjtu_qr_login_pass_v1",
        workerFlag: "sjtu_qr_worker_flag_v1",
        workerCurrentTask: "sjtu_qr_worker_current_task_v1",
        workerHeartbeat: "sjtu_qr_worker_heartbeat_v1",
        reloadRate: "sjtu_qr_reload_rate_v1",
    };

    const CONFIG = {
        scanIntervalMs: 220,
        samePayloadIgnoreMs: 1100,
        samePayloadQuietMs: 18000,
        samePayloadInFlightQuietMs: 45000,
        samePayloadSuccessQuietMs: 600000,
        mergeWindowMs: 120000,
        dispatchCooldownMs: 1800,
        dispatchRetryMs: 45000,
        dispatchSuccessLockMs: 600000,
        dispatchScanPageLockMs: 120000,
        maxFrameWidth: 1440,
        detectorRoiTargetWidth: 1400,
        detectorRoiMaxUpscale: 2.6,
        detectorRoiBatchSize: 2,
        heavyDecodeIntervalMs: 900,
        proxyRetryCooldownMs: 5000,
        proxyFailureBackoffMs: 30000,
        secondaryProbeEveryTicks: 4,
        proxySyncThresholdSec: 0.35,
        debugPreviewIntervalMs: 1200,
        maxSessions: 40,
        autoRecover: true,
        noVideoReloadMs: 150000,
        noFrameReloadMs: 120000,
        frozenFrameReloadMs: 90000,
        reloadCooldownMs: 120000,
        maxReloadPerHour: 6,
        workerBootUrl: "https://oc.sjtu.edu.cn/?sjtu_qr_worker=1#sjtu-qr-worker",
        workerMobileBootUrl: "https://mlearning.sjtu.edu.cn/lms/mobile/?sjtu_qr_worker=1#/pages/tab/ScanPage",
        workerActionIntervalMs: 1200,
        workerActionTimeoutMs: 120000,
        clickDebounceMs: 2500,
        workerHeartbeatMs: 3000,
        workerAliveWindowMs: 15000,
        skipDispatchForMobileScanPage: true,
        debugPreviewEnabled: true,
        debugMaxEvents: 12,
        autoStartOnLoad: false,
        loginUsername: "",
        loginPassword: "",
    };

    const VOLATILE_QUERY_KEYS = new Set([
        "t",
        "ts",
        "timestamp",
        "time",
        "nonce",
        "sign",
        "signature",
        "token",
        "access_token",
        "code",
        "ticket",
        "rand",
        "random",
        "expire",
        "expires",
        "expired",
        "refresh",
        "captcha",
    ]);

    const QUIZ_ID_KEYS = ["id", "quizid", "examid", "activityid", "taskid", "paperid", "homeworkid", "testid"];
    const SUCCESS_WORDS = ["签到成功", "登记成功", "提交成功", "已签到", "已登记", "成功", "success"];
    const EXPIRED_WORDS = ["过期", "失效", "expired", "invalid", "无效"];
    const LOGIN_BUTTON_WORDS = ["登录", "log in", "login", "统一身份认证", "jaccount", "去登录"];
    const CHECKIN_BUTTON_WORDS = ["签到", "登记", "提交", "确认", "加入", "参加", "立即", "下一步", "完成"];

    const runtimeMode = detectMode();
    if (runtimeMode === MODE.scanner) {
        void bootstrapScanner();
        return;
    }
    if (runtimeMode === MODE.worker) {
        bootstrapWorker();
    }

    function detectMode() {
        const href = location.href;
        const isPlayback =
            /\/lti\/app\/lti\/liveVideo\/index\.d2j/i.test(href) ||
            /\/lti\/app\/lti\/vodVideo\/playPage/i.test(href) ||
            href.startsWith("https://v.sjtu.edu.cn/jy-application-canvas-sjtu-ui/") ||
            href.startsWith("https://vshare.sjtu.edu.cn/play/");
        if (isPlayback) {
            return MODE.scanner;
        }

        let url;
        try {
            url = new URL(href);
        } catch {
            return MODE.idle;
        }
        const workerByHash = url.hash.includes("sjtu-qr-worker");
        const workerByQuery = url.searchParams.get("sjtu_qr_worker") === "1";
        const workerBySession = sessionStorage.getItem(STORAGE.workerFlag) === "1";
        if (workerByHash || workerByQuery || workerBySession) {
            sessionStorage.setItem(STORAGE.workerFlag, "1");
            return MODE.worker;
        }
        return MODE.idle;
    }

    async function bootstrapScanner() {
        const scanner = createScannerRuntime();
        injectScannerStyles();
        scanner.createPanel();
        await scanner.initDetector();
        scanner.observeDomChanges();
        scanner.bindWorkerResultChannel();
        if (CONFIG.autoStartOnLoad) {
            scanner.startScanning();
            scanner.setStatus("Scanner running. Waiting for QR from computer stream...", "ok");
        } else {
            scanner.setStatus("Idle. Click Start when you need QR detection.", "normal");
        }
    }

    function createScannerRuntime() {
        const state = {
            timerId: null,
            scanLocked: false,
            scanEpoch: 0,
            detector: null,
            running: false,
            canvas: document.createElement("canvas"),
            thresholdCanvas: document.createElement("canvas"),
            ctx: null,
            thresholdCtx: null,
            sessions: new Map(),
            currentSessionId: null,
            lastPayload: "",
            lastPayloadAt: 0,
            lastUrl: "",
            lastFrameSignature: "",
            lastFrameAt: 0,
            lastHeavyDecodeAt: 0,
            roiCursor: 0,
            probeTick: 0,
            panel: null,
            workerTab: null,
            workerLastResult: null,
            crossOriginBlockedHinted: false,
            noScanHintAt: 0,
            noScanSince: 0,
            collapsed: true,
            sourceMode: "both",
            playbackSignature: "",
            lastCandidateCount: 0,
            lastScanSourceLabel: "-",
            debugEnabled: CONFIG.debugPreviewEnabled,
            debugEvents: [],
            lastDebugMsg: "",
            lastDebugAt: 0,
            lastFramePreviewDataUrl: "",
            lastPreviewAt: 0,
            lastCandidateSnapshot: [],
            corsProxyVideos: new Map(),
            corsProxyTried: new Set(),
            proxyFailUntil: new Map(),
            sourceCanvasAccess: new Map(),
            els: {},
            health: {
                noVideoSince: 0,
                noFrameSince: 0,
                noProgressSince: 0,
                lastVideoTime: -1,
                lastReloadAt: 0,
                lastNudgeAt: 0,
            },
        };

        state.ctx = state.canvas.getContext("2d", { willReadFrequently: true });
        state.thresholdCtx = state.thresholdCanvas.getContext("2d", { willReadFrequently: true });

        function createPanel() {
            if (document.getElementById("sjtu-qr-auto-score-panel")) {
                return;
            }
            const panel = document.createElement("div");
            panel.id = "sjtu-qr-auto-score-panel";
            panel.innerHTML = `
                <div class="qr-panel-header">
                    <div class="qr-panel-title">QR Auto Score</div>
                    <div class="qr-panel-header-actions">
                        <button id="qr-toggle-btn">Start</button>
                        <button id="qr-collapse-btn">Expand</button>
                    </div>
                </div>
                <div class="qr-panel-status" id="qr-status-text">Booting...</div>
                <div class="qr-panel-body" id="qr-panel-body">
                    <div class="qr-panel-actions">
                        <button id="qr-open-worker-btn">Open Worker</button>
                        <button id="qr-open-mobile-btn">Open mLearning</button>
                        <button id="qr-source-btn">Source:both</button>
                        <button id="qr-debug-btn">Debug:on</button>
                        <button id="qr-set-cred-btn">Set Cred</button>
                        <button id="qr-copy-btn">Copy Last QR</button>
                        <button id="qr-manual-btn">Manual URL</button>
                        <button id="qr-clear-btn">Clear</button>
                    </div>
                    <div class="qr-panel-meta">
                        <div class="k">Current Session</div><div class="v" id="qr-current-session">-</div>
                        <div class="k">Worker Status</div><div class="v" id="qr-worker-status">-</div>
                        <div class="k">Scan Source</div><div class="v" id="qr-scan-source">-</div>
                        <div class="k">Credential</div><div class="v" id="qr-cred-status">-</div>
                        <div class="k">Last Payload</div><div class="v" id="qr-last-payload">-</div>
                    </div>
                    <div class="qr-debug-box" id="qr-debug-box" style="display:none;">
                        <div class="qr-debug-title">Debug</div>
                        <img id="qr-debug-preview" class="qr-debug-preview" alt="preview"/>
                        <pre id="qr-debug-text" class="qr-debug-text"></pre>
                    </div>
                    <div class="qr-panel-list" id="qr-session-list"></div>
                </div>
            `;
            document.body.appendChild(panel);
            state.panel = panel;
            state.els = {
                status: panel.querySelector("#qr-status-text"),
                toggle: panel.querySelector("#qr-toggle-btn"),
                collapse: panel.querySelector("#qr-collapse-btn"),
                body: panel.querySelector("#qr-panel-body"),
                openWorker: panel.querySelector("#qr-open-worker-btn"),
                openMobile: panel.querySelector("#qr-open-mobile-btn"),
                source: panel.querySelector("#qr-source-btn"),
                debug: panel.querySelector("#qr-debug-btn"),
                setCred: panel.querySelector("#qr-set-cred-btn"),
                copy: panel.querySelector("#qr-copy-btn"),
                manual: panel.querySelector("#qr-manual-btn"),
                clear: panel.querySelector("#qr-clear-btn"),
                currentSession: panel.querySelector("#qr-current-session"),
                workerStatus: panel.querySelector("#qr-worker-status"),
                scanSource: panel.querySelector("#qr-scan-source"),
                credStatus: panel.querySelector("#qr-cred-status"),
                lastPayload: panel.querySelector("#qr-last-payload"),
                debugBox: panel.querySelector("#qr-debug-box"),
                debugPreview: panel.querySelector("#qr-debug-preview"),
                debugText: panel.querySelector("#qr-debug-text"),
                list: panel.querySelector("#qr-session-list"),
            };

            state.els.toggle.addEventListener("click", () => {
                if (!state.running) {
                    startScanning();
                } else {
                    stopScanning();
                }
            });
            state.els.collapse.addEventListener("click", () => {
                state.collapsed = !state.collapsed;
                renderPanel();
            });
            state.els.openWorker.addEventListener("click", () => ensureWorkerTab(true));
            state.els.openMobile.addEventListener("click", openMobileScanPage);
            state.els.source.addEventListener("click", cycleSourceMode);
            state.els.debug.addEventListener("click", toggleDebugMode);
            state.els.setCred.addEventListener("click", promptCredential);
            state.els.copy.addEventListener("click", copyLastPayload);
            state.els.manual.addEventListener("click", manualDispatchUrl);
            state.els.clear.addEventListener("click", clearSessions);
            renderPanel();
        }

        async function initDetector() {
            if (!("BarcodeDetector" in window)) {
                setStatus("BarcodeDetector unavailable in this browser. Chrome/Edge is recommended.", "error");
                return;
            }
            try {
                const supportedFormats = await window.BarcodeDetector.getSupportedFormats();
                if (supportedFormats.includes("qr_code")) {
                    state.detector = new window.BarcodeDetector({ formats: ["qr_code"] });
                } else {
                    setStatus("BarcodeDetector exists but qr_code format is unsupported.", "error");
                }
            } catch (error) {
                console.warn("[qr-auto-score] BarcodeDetector unavailable:", error);
                setStatus("BarcodeDetector init failed.", "error");
            }
        }

        function bindWorkerResultChannel() {
            if (typeof GM_addValueChangeListener === "function") {
                GM_addValueChangeListener(STORAGE.result, (_key, _oldVal, newVal) => {
                    if (newVal) {
                        handleWorkerResult(newVal);
                    }
                });
            }
            const existing = safeGetValue(STORAGE.result, null);
            if (existing) {
                handleWorkerResult(existing);
            }
        }

        function handleWorkerResult(result) {
            if (!result || !result.taskId) {
                return;
            }
            state.workerLastResult = result;
            const session = result.sessionId ? state.sessions.get(result.sessionId) : null;
            if (session) {
                session.workerStatus = result.status || "-";
                session.workerMessage = result.message || "";
                session.lastWorkerAt = result.at || Date.now();
                if (result.score) {
                    session.score = String(result.score);
                }
                const statusText = String(result.status || "").toLowerCase();
                if (statusText.includes("success") || statusText.includes("score")) {
                    session.dispatchLockedUntil = Date.now() + CONFIG.dispatchSuccessLockMs;
                } else if (statusText.includes("needs-rescan") || statusText.includes("scanpage")) {
                    session.dispatchLockedUntil = Date.now() + CONFIG.dispatchScanPageLockMs;
                }
            }
            renderPanel();
        }

        function observeDomChanges() {
            const observer = new MutationObserver(() => {
                if (!state.panel || !document.body.contains(state.panel)) {
                    createPanel();
                }
            });
            observer.observe(document.documentElement, {
                childList: true,
                subtree: true,
            });
        }

        function startScanning() {
            if (state.timerId) {
                return;
            }
            resetActiveScanWindow();
            state.scanEpoch += 1;
            state.running = true;
            state.collapsed = false;
            state.els.toggle.textContent = "Stop";
            state.timerId = window.setInterval(scanTick, CONFIG.scanIntervalMs);
            void scanTick();
            renderPanel();
        }

        function stopScanning() {
            state.scanEpoch += 1;
            if (state.timerId) {
                clearInterval(state.timerId);
                state.timerId = null;
            }
            state.running = false;
            state.els.toggle.textContent = "Start";
            state.scanLocked = false;
            setStatus("Idle. Click Start when you need QR detection.", "normal");
            renderPanel();
        }

        function resetActiveScanWindow() {
            state.scanLocked = false;
            state.noScanSince = 0;
            state.noScanHintAt = 0;
            state.lastFrameSignature = "";
            state.lastFrameAt = 0;
            state.lastHeavyDecodeAt = 0;
            state.health.noFrameSince = 0;
            state.health.noVideoSince = 0;
            state.health.noProgressSince = 0;
            state.health.lastVideoTime = -1;
            state.health.lastNudgeAt = 0;
            state.lastScanSourceLabel = "-";
            state.lastCandidateCount = 0;
            state.lastCandidateSnapshot = [];
            state.lastFramePreviewDataUrl = "";
        }

        async function scanTick() {
            if (!state.running || state.scanLocked) {
                return;
            }
            const currentEpoch = state.scanEpoch;
            state.scanLocked = true;
            try {
                syncPlaybackContext();
                const videos = resolveCandidateVideos();
                state.probeTick += 1;
                state.lastCandidateCount = videos.length;
                state.lastCandidateSnapshot = videos.map((video, idx) => describeVideoCandidate(video, idx));
                if (!videos.length) {
                    onNoVideo();
                    return;
                }

                let hasReadyFrame = false;
                let attemptedDecode = false;
                const activeSession = state.currentSessionId ? state.sessions.get(state.currentSessionId) : null;
                const now = Date.now();
                const allowHeavyDecode = now - state.lastHeavyDecodeAt >= CONFIG.heavyDecodeIntervalMs;
                let heavyUsedInThisTick = false;
                const probeCandidates = pickProbeCandidates(videos);
                for (const candidate of probeCandidates) {
                    const { video, idx } = candidate;
                    primeReadableProxy(video);
                    if (!hasVideoDimensions(video)) {
                        continue;
                    }
                    state.lastScanSourceLabel = describeVideoCandidate(video, idx);
                    hasReadyFrame = true;
                    if (shouldSkipDecodeForStableFrame(video, idx, activeSession)) {
                        continue;
                    }
                    onHealthyFrame(video);
                    attemptedDecode = true;
                    if (!tryDrawFrame(video)) {
                        continue;
                    }
                    state.lastFrameSignature = buildFrameSignature(video, idx);
                    state.lastFrameAt = Date.now();
                    const shouldUseHeavy = allowHeavyDecode && !heavyUsedInThisTick && idx === 0;
                    const payload = await decodePayload(video, { fastOnly: !shouldUseHeavy });
                    if (!state.running || currentEpoch !== state.scanEpoch) {
                        return;
                    }
                    if (shouldUseHeavy) {
                        heavyUsedInThisTick = true;
                        state.lastHeavyDecodeAt = Date.now();
                    }
                    if (!payload) {
                        continue;
                    }
                    handlePayload(payload.trim());
                    return;
                }

                if (!hasReadyFrame) {
                    onNoFrame();
                    return;
                }
                if (!attemptedDecode) {
                    return;
                }
                onNoQrDetected();
            } catch (error) {
                pushDebugEvent(`scan error: ${String(error.message || error)}`);
                setStatus(`Scan error: ${String(error.message || error)}`, "error");
            } finally {
                state.scanLocked = false;
            }
        }

        function shouldSkipDecodeForStableFrame(video, idx, session) {
            if (!state.lastPayload) {
                return false;
            }
            const quietWindow = getSamePayloadQuietWindow(session);
            if (Date.now() - state.lastPayloadAt >= quietWindow) {
                return false;
            }
            const frameSig = buildFrameSignature(video, idx);
            if (frameSig && frameSig === state.lastFrameSignature && Date.now() - state.lastFrameAt < 2500) {
                return true;
            }
            return false;
        }

        function buildFrameSignature(video, idx) {
            const t = Number(video.currentTime || 0).toFixed(2);
            const paused = video.paused ? "p" : "r";
            return `${idx}|${video.videoWidth}x${video.videoHeight}|${t}|${paused}`;
        }

        function describeVideoCandidate(video, idx) {
            const role = video.closest(".cont-item-2")
                ? "cont2"
                : video.closest(".cont-item-1")
                    ? "cont1"
                    : "plain";
            const w = Math.floor(video.videoWidth || video.clientWidth || 0);
            const h = Math.floor(video.videoHeight || video.clientHeight || 0);
            const t = Number(video.currentTime || 0).toFixed(1);
            const paused = video.paused ? "paused" : "playing";
            return `#${idx + 1} ${role} ${w}x${h} t=${t} ${paused}`;
        }

        function pickProbeCandidates(videos) {
            if (!videos.length) {
                return [];
            }
            if (videos.length === 1 || state.sourceMode === "first" || state.sourceMode === "second") {
                return [{ video: videos[0], idx: 0 }];
            }

            const result = [{ video: videos[0], idx: 0 }];
            if (videos.length > 1 && state.probeTick % CONFIG.secondaryProbeEveryTicks === 0) {
                result.push({ video: videos[1], idx: 1 });
            }
            return result;
        }

        function primeReadableProxy(video) {
            const src = getVideoSourceUrl(video);
            if (!src || src.startsWith("blob:")) {
                return;
            }
            const proxy = ensureCorsProxyVideo(src);
            if (!proxy) {
                return;
            }

            if (proxy.readyState >= HTMLMediaElement.HAVE_METADATA) {
                try {
                    const sourceTime = Number(video.currentTime || 0);
                    if (!Number.isNaN(sourceTime) && Math.abs((proxy.currentTime || 0) - sourceTime) > CONFIG.proxySyncThresholdSec) {
                        proxy.currentTime = sourceTime;
                    }
                } catch {
                    // Ignore currentTime sync failures.
                }
            }

            if (!video.paused && proxy.paused) {
                proxy.play().catch(() => {
                    // Ignore autoplay failures.
                });
            }
        }

        function getPlaybackContextSignature() {
            const activeItem = document.querySelector(".lti-list .list-item--active");
            const activeId =
                activeItem?.id ||
                activeItem?.getAttribute("data-id") ||
                activeItem?.getAttribute("data-video-id") ||
                "";
            const activeHref =
                activeItem?.getAttribute("href") ||
                activeItem?.querySelector("a")?.getAttribute("href") ||
                "";
            const activeText = activeItem?.innerText?.replace(/\s+/g, " ").trim() || "";
            return [
                location.pathname,
                location.search,
                document.title.trim(),
                activeId,
                activeHref,
                activeText.slice(0, 80),
            ].join("||");
        }

        function syncPlaybackContext() {
            const next = getPlaybackContextSignature();
            if (next === state.playbackSignature) {
                return;
            }
            state.playbackSignature = next;
            state.noScanSince = 0;
            state.noScanHintAt = 0;
            state.health.noFrameSince = 0;
            state.health.noVideoSince = 0;
            state.sourceCanvasAccess.clear();
            state.proxyFailUntil.clear();
            state.corsProxyTried.clear();
            state.lastHeavyDecodeAt = 0;
            state.lastFrameSignature = "";
            state.lastFrameAt = 0;
        }

        function onNoVideo() {
            const now = Date.now();
            if (!state.health.noVideoSince) {
                state.health.noVideoSince = now;
            }
            setStatus("No playable video yet. Waiting...", "normal");
            if (CONFIG.autoRecover && now - state.health.noVideoSince > CONFIG.noVideoReloadMs) {
                triggerRecoveryReload("video-not-rendered");
            }
        }

        function onNoFrame() {
            const now = Date.now();
            if (!state.health.noFrameSince) {
                state.health.noFrameSince = now;
            }
            state.health.noVideoSince = 0;
            setStatus("Video found but frames not ready...", "normal");
            nudgeVideoPipeline(now);
            if (CONFIG.autoRecover && now - state.health.noFrameSince > CONFIG.noFrameReloadMs) {
                triggerRecoveryReload("frame-not-ready");
            }
        }

        function nudgeVideoPipeline(now) {
            if (now - state.health.lastNudgeAt < 5000) {
                return;
            }
            state.health.lastNudgeAt = now;
            const candidates = resolveCandidateVideos();
            candidates.forEach((video) => {
                try {
                    if (video.readyState < HTMLMediaElement.HAVE_CURRENT_DATA && Number(video.currentTime || 0) >= 0) {
                        video.currentTime = Number(video.currentTime || 0);
                    }
                    if (video.paused && Number(video.currentTime || 0) === 0) {
                        const maybePromise = video.play();
                        if (maybePromise && typeof maybePromise.then === "function") {
                            maybePromise
                                .then(() => {
                                    window.setTimeout(() => {
                                        try {
                                            video.pause();
                                        } catch {
                                            // Ignore pause errors.
                                        }
                                    }, 180);
                                })
                                .catch(() => {
                                    // Ignore autoplay rejection.
                                });
                        }
                    }
                } catch {
                    // Ignore nudge errors.
                }
            });
            pushDebugEvent("nudge video pipeline");
        }

        function onNoQrDetected() {
            const now = Date.now();
            if (!state.noScanSince) {
                state.noScanSince = now;
            }
            if (now - state.noScanSince < 20000) {
                return;
            }
            if (now - state.noScanHintAt < 8000) {
                return;
            }
            state.noScanHintAt = now;
            if (state.crossOriginBlockedHinted && !state.detector) {
                setStatus(
                    `No scan: VOD cross-origin + no BarcodeDetector (candidates=${state.lastCandidateCount}). Use latest Chrome/Edge, or readable proxy/CORS is required.`,
                    "error"
                );
                return;
            }
            if (state.crossOriginBlockedHinted && state.detector) {
                setStatus(
                    `No QR yet. BarcodeDetector-only mode, source=${state.sourceMode}, candidates=${state.lastCandidateCount}. Trying CORS-proxy decode when possible.`,
                    "normal"
                );
                return;
            }
            setStatus(
                `No QR detected yet. source=${state.sourceMode}, candidates=${state.lastCandidateCount}.`,
                "normal"
            );
        }

        function onHealthyFrame(video) {
            const now = Date.now();
            state.health.noVideoSince = 0;
            state.health.noFrameSince = 0;

            const t = Number(video.currentTime || 0);
            if (!video.paused && Math.abs(t - state.health.lastVideoTime) < 0.02) {
                if (!state.health.noProgressSince) {
                    state.health.noProgressSince = now;
                } else if (CONFIG.autoRecover && now - state.health.noProgressSince > CONFIG.frozenFrameReloadMs) {
                    triggerRecoveryReload("frozen-frame");
                }
            } else {
                state.health.noProgressSince = 0;
                state.health.lastVideoTime = t;
            }
        }

        function triggerRecoveryReload(reason) {
            const now = Date.now();
            if (now - state.health.lastReloadAt < CONFIG.reloadCooldownMs) {
                return;
            }
            if (!consumeReloadQuota(now)) {
                setStatus("Auto recover paused: hourly reload quota reached.", "error");
                return;
            }
            state.health.lastReloadAt = now;
            setStatus(`Recovering (${reason}), reloading page...`, "error");
            window.setTimeout(() => location.reload(), 250);
        }

        function consumeReloadQuota(now) {
            const hourKey = Math.floor(now / 3600000);
            const latest = sessionStorage.getItem(STORAGE.reloadRate);
            let payload = { hourKey, count: 0 };
            if (latest) {
                try {
                    payload = JSON.parse(latest);
                } catch {
                    payload = { hourKey, count: 0 };
                }
            }
            if (payload.hourKey !== hourKey) {
                payload = { hourKey, count: 0 };
            }
            if (payload.count >= CONFIG.maxReloadPerHour) {
                return false;
            }
            payload.count += 1;
            sessionStorage.setItem(STORAGE.reloadRate, JSON.stringify(payload));
            return true;
        }

        function resolveCandidateVideos() {
            const candidates = Array.from(document.querySelectorAll("video#kmd-video-player, video"))
                .filter(isVideoElement)
                .filter((video) => video.dataset.qrProxyVideo !== "1");
            if (!candidates.length) {
                return [];
            }

            if (state.sourceMode === "first") {
                return candidates[0] ? [candidates[0]] : [];
            }
            if (state.sourceMode === "second") {
                const second = candidates[1] || null;
                if (second) {
                    return [second];
                }
                return candidates[0] ? [candidates[0]] : [];
            }
            if (state.sourceMode === "both") {
                return pickTopCandidates(candidates, 2);
            }

            const preferred = document.querySelector(".cont-item-2 #kmd-video-player");
            if (isVideoElement(preferred)) {
                const others = candidates.filter((video) => video !== preferred);
                return [preferred, ...pickTopCandidates(others, 1)];
            }
            return pickTopCandidates(candidates, Math.min(2, candidates.length));
        }

        function pickTopCandidates(candidates, limit) {
            return [...candidates]
                .sort((a, b) => scoreVideoCandidate(b) - scoreVideoCandidate(a))
                .slice(0, limit);
        }

        function scoreVideoCandidate(video) {
            let score = 0;
            if (!hasVideoDimensions(video)) {
                score -= 260;
            }
            if (video.closest(".cont-item-2")) {
                score += 120;
            }
            if (video.closest(".cont-item-1")) {
                score += 60;
            }
            if (!video.paused) {
                score += 40;
            }
            if (video.readyState >= HTMLMediaElement.HAVE_CURRENT_DATA) {
                score += 20;
            }
            if (Number(video.currentTime || 0) > 0.2) {
                score += 20;
            }

            const area = videoArea(video);
            // Dual stream layout often uses smaller window for computer stream.
            score += Math.max(0, 200000 - Math.min(area, 200000)) / 4000;
            score += Math.min(area, 300000) / 50000;
            if (isElementVisible(video)) {
                score += 15;
            }
            return score;
        }

        function drawFrame(video) {
            const ratio = video.videoWidth > CONFIG.maxFrameWidth ? CONFIG.maxFrameWidth / video.videoWidth : 1;
            const width = Math.max(2, Math.floor(video.videoWidth * ratio));
            const height = Math.max(2, Math.floor(video.videoHeight * ratio));
            if (state.canvas.width !== width || state.canvas.height !== height) {
                state.canvas.width = width;
                state.canvas.height = height;
                state.thresholdCanvas.width = width;
                state.thresholdCanvas.height = height;
            }
            state.ctx.drawImage(video, 0, 0, width, height);
            if (state.debugEnabled) {
                updateDebugPreviewDataUrl();
            }
        }

        function tryDrawFrame(video) {
            try {
                drawFrame(video);
                return true;
            } catch {
                pushDebugEvent("draw frame failed");
                return false;
            }
        }

        function updateDebugPreviewDataUrl() {
            const now = Date.now();
            if (now - state.lastPreviewAt < CONFIG.debugPreviewIntervalMs) {
                return;
            }
            state.lastPreviewAt = now;
            try {
                state.lastFramePreviewDataUrl = state.canvas.toDataURL("image/jpeg", 0.55);
            } catch {
                state.lastFramePreviewDataUrl = "";
            }
        }

        async function decodePayload(video, options = {}) {
            const fastOnly = Boolean(options.fastOnly);
            const srcKey = getVideoSourceKey(video);
            if (state.detector) {
                const roiFound = await detectByBarcodeDetectorWithRoi(video, { fastOnly });
                if (roiFound) {
                    pushDebugEvent("detector roi decode success");
                    return roiFound;
                }
            }

            if (fastOnly) {
                return "";
            }

            if (typeof window.jsQR !== "function") {
                return "";
            }

            const accessMode = getCanvasAccessMode(srcKey);
            if (accessMode !== "tainted") {
                const roiFound = tryDecodeByJsQrWithRoi(video, srcKey);
                if (roiFound) {
                    return roiFound;
                }
            }

            pushDebugEvent("canvas tainted, trying proxy decode");
            const fromProxy = await tryDecodeFromCorsProxy(video);
            if (fromProxy) {
                pushDebugEvent("proxy decode success");
                return fromProxy;
            }
            if (!state.crossOriginBlockedHinted) {
                state.crossOriginBlockedHinted = true;
                setStatus(
                    "VOD cross-origin video tainted canvas. Switched to BarcodeDetector-only path.",
                    "normal"
                );
            }
            return "";
        }

        async function detectByBarcodeDetectorWithRoi(video, options = {}) {
            if (!state.detector || !isReadyVideoFrame(video)) {
                return "";
            }
            const fastOnly = Boolean(options.fastOnly);
            const w = video.videoWidth;
            const h = video.videoHeight;
            const rois = [
                { name: "full", x: 0, y: 0, w: 1, h: 1 },
                { name: "center", x: 0.12, y: 0.1, w: 0.76, h: 0.8 },
                { name: "center-tight", x: 0.24, y: 0.2, w: 0.52, h: 0.62 },
                { name: "right", x: 0.42, y: 0.1, w: 0.56, h: 0.82 },
                { name: "left", x: 0.02, y: 0.1, w: 0.56, h: 0.82 },
            ];

            const passCount = fastOnly ? 1 : Math.min(CONFIG.detectorRoiBatchSize, rois.length);
            for (let i = 0; i < passCount; i += 1) {
                const roi = rois[state.roiCursor % rois.length];
                state.roiCursor = (state.roiCursor + 1) % rois.length;
                const sx = Math.max(0, Math.floor(w * roi.x));
                const sy = Math.max(0, Math.floor(h * roi.y));
                const sw = Math.max(2, Math.floor(w * roi.w));
                const sh = Math.max(2, Math.floor(h * roi.h));
                drawCroppedFrame(video, sx, sy, sw, sh);
                try {
                    const found = await state.detector.detect(state.canvas);
                    if (found && found.length > 0 && found[0].rawValue) {
                        pushDebugEvent(`detector hit roi=${roi.name}`);
                        return found[0].rawValue;
                    }
                } catch {
                    // Ignore detector errors on a specific ROI.
                }
            }
            return "";
        }

        function tryDecodeByJsQrWithRoi(video, srcKey) {
            const w = video.videoWidth;
            const h = video.videoHeight;
            const rois = [
                { name: "center-tight", x: 0.24, y: 0.2, w: 0.52, h: 0.62 },
                { name: "center", x: 0.12, y: 0.1, w: 0.76, h: 0.8 },
                { name: "right", x: 0.42, y: 0.1, w: 0.56, h: 0.82 },
            ];

            for (const roi of rois) {
                const sx = Math.max(0, Math.floor(w * roi.x));
                const sy = Math.max(0, Math.floor(h * roi.y));
                const sw = Math.max(2, Math.floor(w * roi.w));
                const sh = Math.max(2, Math.floor(h * roi.h));
                drawCroppedFrame(video, sx, sy, sw, sh);
                const imageData = tryReadCanvasImageData(srcKey);
                if (!imageData) {
                    return "";
                }

                const direct = window.jsQR(imageData.data, imageData.width, imageData.height, {
                    inversionAttempts: "attemptBoth",
                });
                if (direct && direct.data) {
                    pushDebugEvent(`jsqr hit roi=${roi.name}`);
                    return direct.data;
                }

                const threshold = createThresholdImageData(imageData);
                const secondTry = window.jsQR(threshold.data, threshold.width, threshold.height, {
                    inversionAttempts: "attemptBoth",
                });
                if (secondTry && secondTry.data) {
                    pushDebugEvent(`jsqr threshold hit roi=${roi.name}`);
                    return secondTry.data;
                }
            }
            return "";
        }

        function drawCroppedFrame(video, sx, sy, sw, sh) {
            const upscale = Math.min(CONFIG.detectorRoiMaxUpscale, CONFIG.detectorRoiTargetWidth / sw);
            const outW = Math.max(2, Math.floor(sw * Math.max(1, upscale)));
            const outH = Math.max(2, Math.floor(sh * Math.max(1, upscale)));
            if (state.canvas.width !== outW || state.canvas.height !== outH) {
                state.canvas.width = outW;
                state.canvas.height = outH;
                state.thresholdCanvas.width = outW;
                state.thresholdCanvas.height = outH;
            }
            state.ctx.drawImage(video, sx, sy, sw, sh, 0, 0, outW, outH);
            if (state.debugEnabled) {
                updateDebugPreviewDataUrl();
            }
        }

        function tryReadCanvasImageData(srcKey) {
            try {
                const imageData = state.ctx.getImageData(0, 0, state.canvas.width, state.canvas.height);
                setCanvasAccessMode(srcKey, "readable");
                state.crossOriginBlockedHinted = false;
                return imageData;
            } catch (error) {
                if (isTaintedCanvasError(error)) {
                    setCanvasAccessMode(srcKey, "tainted");
                    return null;
                }
                throw error;
            }
        }

        async function tryDecodeFromCorsProxy(video) {
            const src = getVideoSourceUrl(video);
            if (!src || src.startsWith("blob:")) {
                pushDebugEvent("proxy skipped: no http src");
                return "";
            }
            const now = Date.now();
            const failUntil = Number(state.proxyFailUntil.get(src) || 0);
            if (failUntil && now < failUntil) {
                return "";
            }
            const proxy = ensureCorsProxyVideo(src);
            if (!proxy) {
                pushDebugEvent("proxy unavailable");
                state.proxyFailUntil.set(src, now + CONFIG.proxyRetryCooldownMs);
                return "";
            }
            if (proxy.readyState < HTMLMediaElement.HAVE_CURRENT_DATA || !proxy.videoWidth || !proxy.videoHeight) {
                return "";
            }

            // Best effort: keep proxy frame close to source frame.
            try {
                if (!Number.isNaN(video.currentTime) && video.currentTime > 0 && Math.abs(proxy.currentTime - video.currentTime) > 1.2) {
                    proxy.currentTime = video.currentTime;
                }
            } catch {
                // Ignore seek failure.
            }

            try {
                drawFrame(proxy);
                const imageData = state.ctx.getImageData(0, 0, state.canvas.width, state.canvas.height);
                const direct = window.jsQR(imageData.data, imageData.width, imageData.height, {
                    inversionAttempts: "attemptBoth",
                });
                if (direct && direct.data) {
                    return direct.data;
                }
                const threshold = createThresholdImageData(imageData);
                const secondTry = window.jsQR(threshold.data, threshold.width, threshold.height, {
                    inversionAttempts: "attemptBoth",
                });
                const decoded = secondTry && secondTry.data ? secondTry.data : "";
                if (!decoded) {
                    state.proxyFailUntil.set(src, Date.now() + CONFIG.proxyRetryCooldownMs);
                }
                return decoded;
            } catch {
                pushDebugEvent("proxy decode failed by security/runtime error");
                state.proxyFailUntil.set(src, Date.now() + CONFIG.proxyFailureBackoffMs);
                return "";
            }
        }

        function ensureCorsProxyVideo(src) {
            if (state.corsProxyVideos.has(src)) {
                return state.corsProxyVideos.get(src);
            }
            if (state.corsProxyTried.has(src)) {
                return null;
            }
            state.corsProxyTried.add(src);

            const proxy = document.createElement("video");
            proxy.crossOrigin = "anonymous";
            proxy.dataset.qrProxyVideo = "1";
            proxy.muted = true;
            proxy.playsInline = true;
            proxy.preload = "auto";
            proxy.style.display = "none";
            proxy.src = src;
            document.body.appendChild(proxy);
            try {
                proxy.load();
            } catch {
                // Ignore load failures.
            }
            proxy.play().catch(() => {
                // Autoplay can fail silently; frame may still load.
            });
            state.corsProxyVideos.set(src, proxy);
            return proxy;
        }

        function getVideoSourceUrl(video) {
            if (!video) {
                return "";
            }
            if (video.currentSrc && /^https?:\/\//i.test(video.currentSrc)) {
                return video.currentSrc;
            }
            if (video.src && /^https?:\/\//i.test(video.src)) {
                return video.src;
            }
            const source = video.querySelector("source[src]");
            if (source && source.src && /^https?:\/\//i.test(source.src)) {
                return source.src;
            }
            return "";
        }

        function getVideoSourceKey(video) {
            const src = getVideoSourceUrl(video);
            if (src) {
                return src;
            }
            const role = video.closest(".cont-item-2")
                ? "cont2"
                : video.closest(".cont-item-1")
                    ? "cont1"
                    : "plain";
            return `${role}|${video.videoWidth}x${video.videoHeight}`;
        }

        function getCanvasAccessMode(srcKey) {
            return state.sourceCanvasAccess.get(srcKey) || "unknown";
        }

        function setCanvasAccessMode(srcKey, mode) {
            if (!srcKey) {
                return;
            }
            state.sourceCanvasAccess.set(srcKey, mode);
        }

        function isTaintedCanvasError(error) {
            if (!error) {
                return false;
            }
            const name = String(error.name || "");
            const msg = String(error.message || "");
            return name === "SecurityError" || /tainted|cross-origin|getImageData/i.test(msg);
        }

        function createThresholdImageData(imageData) {
            const out = state.thresholdCtx.createImageData(imageData.width, imageData.height);
            let sum = 0;
            for (let i = 0; i < imageData.data.length; i += 4) {
                const gray = imageData.data[i] * 0.299 + imageData.data[i + 1] * 0.587 + imageData.data[i + 2] * 0.114;
                sum += gray;
            }
            const avg = sum / (imageData.data.length / 4);
            for (let i = 0; i < imageData.data.length; i += 4) {
                const gray = imageData.data[i] * 0.299 + imageData.data[i + 1] * 0.587 + imageData.data[i + 2] * 0.114;
                const v = gray > avg ? 255 : 0;
                out.data[i] = v;
                out.data[i + 1] = v;
                out.data[i + 2] = v;
                out.data[i + 3] = 255;
            }
            return out;
        }

        function handlePayload(payload) {
            const now = Date.now();
            const currentSession = state.currentSessionId ? state.sessions.get(state.currentSessionId) : null;
            const samePayloadQuietWindow = getSamePayloadQuietWindow(currentSession);
            if (payload === state.lastPayload && now - state.lastPayloadAt < samePayloadQuietWindow) {
                return;
            }
            state.noScanSince = 0;
            state.noScanHintAt = 0;
            pushDebugEvent(`decoded from ${state.lastScanSourceLabel}`);
            pushDebugEvent(`payload: ${safeShort(payload, 90)}`);

            const parsed = toHttpUrl(payload);
            const baseSessionId = buildSessionKey(payload);
            const current = currentSession;
            let sessionId = baseSessionId;
            if (current && now - current.lastSeenAt < CONFIG.mergeWindowMs && isLikelySameQuiz(current.latestPayload, payload)) {
                sessionId = current.id;
            }

            const session = getOrCreateSession(sessionId, now, parsed ? parsed.href : payload);
            const isNewVariant = payload !== session.latestPayload;

            session.lastSeenAt = now;
            session.hitCount += 1;
            if (isNewVariant) {
                session.variantCount += 1;
            }
            session.latestPayload = payload;
            session.latestUrl = parsed ? parsed.href : session.latestUrl;

            state.currentSessionId = session.id;
            state.lastPayload = payload;
            state.lastPayloadAt = now;
            if (parsed) {
                state.lastUrl = parsed.href;
            }

            let statusText = `QR detected. Session #${session.shortId}`;
            let statusLevel = "ok";
            if (parsed) {
                if (CONFIG.skipDispatchForMobileScanPage && isMobileScanPageUrl(parsed.href)) {
                    session.workerStatus = "scanpage_redirect";
                    session.workerMessage = "QR leads to generic ScanPage, needs app re-scan.";
                    session.lastDispatchedUrl = parsed.href;
                    session.lastDispatchedAt = now;
                    session.dispatchLockedUntil = now + CONFIG.dispatchScanPageLockMs;
                    statusText = "Payload points to mLearning ScanPage (likely intermediate page).";
                    statusLevel = "error";
                    pushDebugEvent("skip worker dispatch: scanpage redirect");
                } else {
                    dispatchTaskToWorker(session, parsed.href);
                }
            }
            setStatus(statusText, statusLevel);
            renderPanel();
        }

        function getSamePayloadQuietWindow(session) {
            if (!session) {
                return Math.max(CONFIG.samePayloadIgnoreMs, CONFIG.samePayloadQuietMs);
            }
            const status = String(session.workerStatus || "").toLowerCase();
            if (!status) {
                return Math.max(CONFIG.samePayloadIgnoreMs, CONFIG.samePayloadQuietMs);
            }
            if (status.includes("success") || status.includes("score")) {
                return CONFIG.samePayloadSuccessQuietMs;
            }
            if (
                status.includes("dispatched") ||
                status.includes("navigating") ||
                status.includes("login") ||
                status.includes("action") ||
                status.includes("needs-rescan")
            ) {
                return CONFIG.samePayloadInFlightQuietMs;
            }
            return Math.max(CONFIG.samePayloadIgnoreMs, CONFIG.samePayloadQuietMs);
        }

        function dispatchTaskToWorker(session, url) {
            const now = Date.now();
            if (session.dispatchLockedUntil && now < session.dispatchLockedUntil) {
                pushDebugEvent("skip dispatch: locked");
                return;
            }
            const sameUrl = url === session.lastDispatchedUrl;
            if (sameUrl && now - session.lastDispatchedAt < CONFIG.dispatchCooldownMs) {
                pushDebugEvent("skip dispatch: cooldown");
                return;
            }
            if (sameUrl && !shouldRetrySameUrl(session, now)) {
                pushDebugEvent("skip dispatch: waiting retry window");
                return;
            }
            ensureWorkerTab();
            const task = {
                taskId: `${now}_${Math.random().toString(36).slice(2, 7)}`,
                sessionId: session.id,
                shortId: session.shortId,
                url,
                createdAt: now,
            };
            safeSetValue(STORAGE.task, task);
            session.lastDispatchedUrl = url;
            session.lastDispatchedAt = now;
            session.workerStatus = "dispatched";
            session.dispatchCount += 1;
            pushDebugEvent(`dispatch worker: ${safeShort(url, 90)}`);
            renderPanel();
        }

        function shouldRetrySameUrl(session, now) {
            const status = String(session.workerStatus || "").toLowerCase();
            if (!status) {
                return now - session.lastDispatchedAt >= CONFIG.dispatchRetryMs;
            }
            if (status.includes("success") || status.includes("score")) {
                return now - session.lastDispatchedAt >= CONFIG.dispatchSuccessLockMs;
            }
            if (status.includes("scanpage_redirect")) {
                return now - session.lastDispatchedAt >= CONFIG.dispatchScanPageLockMs;
            }
            if (status.includes("expired") || status.includes("timeout") || status.includes("error")) {
                return now - session.lastDispatchedAt >= CONFIG.dispatchRetryMs;
            }
            if (
                status.includes("dispatched") ||
                status.includes("navigating") ||
                status.includes("login") ||
                status.includes("action") ||
                status.includes("needs-rescan")
            ) {
                return now - session.lastDispatchedAt >= CONFIG.dispatchRetryMs;
            }
            return now - session.lastDispatchedAt >= CONFIG.dispatchRetryMs;
        }

        function ensureWorkerTab(forceForeground = false) {
            const heartbeat = Number(safeGetValue(STORAGE.workerHeartbeat, 0) || 0);
            const workerAlive = Date.now() - heartbeat < CONFIG.workerAliveWindowMs;
            if (workerAlive && !forceForeground) {
                return;
            }
            if (state.workerTab && !state.workerTab.closed) {
                return;
            }
            if (typeof GM_openInTab !== "function") {
                if (forceForeground) {
                    window.open(CONFIG.workerBootUrl, "_blank", "noopener,noreferrer");
                }
                return;
            }
            state.workerTab = GM_openInTab(CONFIG.workerBootUrl, {
                active: forceForeground,
                insert: true,
                setParent: true,
            });
        }

        function openMobileScanPage() {
            if (typeof GM_openInTab === "function") {
                GM_openInTab(CONFIG.workerMobileBootUrl, { active: true, insert: true, setParent: true });
            } else {
                window.open(CONFIG.workerMobileBootUrl, "_blank", "noopener,noreferrer");
            }
            setStatus("Opened mLearning page. Note: desktop browser may not support its scan module.", "normal");
            pushDebugEvent("manual open mLearning ScanPage");
        }

        function cycleSourceMode() {
            const order = ["auto", "both", "first", "second"];
            const idx = order.indexOf(state.sourceMode);
            state.sourceMode = order[(idx + 1) % order.length];
            state.els.source.textContent = `Source:${state.sourceMode}`;
            setStatus(`Scan source switched to ${state.sourceMode}`, "ok");
            pushDebugEvent(`source switched: ${state.sourceMode}`);
        }

        function toggleDebugMode() {
            state.debugEnabled = !state.debugEnabled;
            renderPanel();
            setStatus(`Debug ${state.debugEnabled ? "enabled" : "disabled"}.`, "normal");
        }

        function manualDispatchUrl() {
            const initial = state.lastUrl || "https://";
            const input = window.prompt("Paste QR target URL:", initial);
            if (input === null) {
                return;
            }
            const url = toHttpUrl(input.trim());
            if (!url) {
                setStatus("Manual URL invalid. It must start with http/https.", "error");
                return;
            }
            const now = Date.now();
            const sessionId = buildSessionKey(url.href);
            const session = getOrCreateSession(sessionId, now, url.href);
            session.latestPayload = url.href;
            session.latestUrl = url.href;
            session.lastSeenAt = now;
            session.hitCount += 1;
            state.currentSessionId = session.id;
            state.lastPayload = url.href;
            state.lastPayloadAt = now;
            state.lastUrl = url.href;
            if (CONFIG.skipDispatchForMobileScanPage && isMobileScanPageUrl(url.href)) {
                session.workerStatus = "scanpage_redirect";
                session.workerMessage = "Manual URL points to ScanPage.";
                session.lastDispatchedUrl = url.href;
                session.lastDispatchedAt = now;
                session.dispatchLockedUntil = now + CONFIG.dispatchScanPageLockMs;
                setStatus("Manual URL is ScanPage. Skip dispatch.", "error");
                pushDebugEvent("manual url recognized as scanpage");
            } else {
                dispatchTaskToWorker(session, url.href);
                setStatus("Manual task dispatched to worker.", "ok");
            }
            renderPanel();
        }

        function promptCredential() {
            const oldUser = safeGetValue(STORAGE.loginUser, "") || "";
            const oldPass = safeGetValue(STORAGE.loginPass, "") || "";
            const newUser = window.prompt("Username (empty to clear):", oldUser);
            if (newUser === null) {
                return;
            }
            const newPass = window.prompt("Password (empty to clear):", oldPass ? "******" : "");
            if (newPass === null) {
                return;
            }

            safeSetValue(STORAGE.loginUser, newUser.trim());
            safeSetValue(STORAGE.loginPass, newPass === "******" ? oldPass : newPass.trim());
            setStatus("Credential updated.", "ok");
            renderPanel();
        }

        function copyLastPayload() {
            if (!state.lastPayload) {
                setStatus("No payload to copy.", "normal");
                return;
            }
            if (typeof GM_setClipboard === "function") {
                GM_setClipboard(state.lastPayload, "text");
                setStatus("Last payload copied.", "ok");
                return;
            }
            if (navigator.clipboard && typeof navigator.clipboard.writeText === "function") {
                navigator.clipboard.writeText(state.lastPayload).then(
                    () => setStatus("Last payload copied.", "ok"),
                    () => setStatus("Clipboard failed.", "error")
                );
                return;
            }
            setStatus("Clipboard API unavailable.", "error");
        }

        function pushDebugEvent(message) {
            if (!message) {
                return;
            }
            const now = Date.now();
            if (state.lastDebugMsg === message && now - state.lastDebugAt < 3000) {
                return;
            }
            const line = `${formatTime(Date.now())} ${message}`;
            state.debugEvents.unshift(line);
            if (state.debugEvents.length > CONFIG.debugMaxEvents) {
                state.debugEvents.length = CONFIG.debugMaxEvents;
            }
            state.lastDebugMsg = message;
            state.lastDebugAt = now;
        }

        function clearSessions() {
            state.sessions.clear();
            state.currentSessionId = null;
            state.lastPayload = "";
            state.lastUrl = "";
            state.lastPayloadAt = 0;
            renderPanel();
            setStatus("Session list cleared.", "ok");
        }

        function setStatus(text, level = "normal") {
            if (!state.els.status) {
                return;
            }
            const color = level === "error" ? "#ffb3b3" : level === "ok" ? "#ccffe4" : "#cfddff";
            state.els.status.style.color = color;
            state.els.status.textContent = text;
        }

        function getOrCreateSession(id, now, sampleUrl) {
            const existing = state.sessions.get(id);
            if (existing) {
                return existing;
            }
            const shortId = `${Math.abs(hashCode(id)).toString(16).slice(0, 6)}`;
            const created = {
                id,
                shortId,
                createdAt: now,
                lastSeenAt: now,
                hitCount: 0,
                variantCount: 0,
                latestPayload: "",
                latestUrl: toHttpUrl(sampleUrl)?.href || "",
                score: "",
                workerStatus: "",
                workerMessage: "",
                lastWorkerAt: 0,
                lastDispatchedAt: 0,
                lastDispatchedUrl: "",
                dispatchCount: 0,
                dispatchLockedUntil: 0,
            };
            state.sessions.set(id, created);
            trimSessions();
            return created;
        }

        function trimSessions() {
            if (state.sessions.size <= CONFIG.maxSessions) {
                return;
            }
            const sorted = [...state.sessions.values()].sort((a, b) => a.lastSeenAt - b.lastSeenAt);
            const removeCount = state.sessions.size - CONFIG.maxSessions;
            for (let i = 0; i < removeCount; i += 1) {
                state.sessions.delete(sorted[i].id);
            }
            trimCorsProxyVideos();
        }

        function trimCorsProxyVideos() {
            const entries = [...state.corsProxyVideos.entries()];
            if (entries.length <= 6) {
                return;
            }
            const removable = entries.slice(0, entries.length - 6);
            removable.forEach(([src, video]) => {
                try {
                    video.pause();
                    video.removeAttribute("src");
                    video.load();
                    video.remove();
                } catch {
                    // Ignore cleanup errors.
                }
                state.corsProxyVideos.delete(src);
            });
        }

        function renderPanel() {
            if (!state.els.list) {
                return;
            }
            const current = state.currentSessionId ? state.sessions.get(state.currentSessionId) : null;
            const latestWorker = state.workerLastResult
                ? `${state.workerLastResult.status || "-"} @ ${formatTime(state.workerLastResult.at || Date.now())}`
                : "-";
            const hasCred = Boolean(getEffectiveCredential().username && getEffectiveCredential().password);

            state.els.currentSession.textContent = current ? `#${current.shortId}` : "-";
            state.els.workerStatus.textContent = latestWorker;
            state.els.scanSource.textContent = state.lastScanSourceLabel || "-";
            state.els.credStatus.textContent = hasCred ? "configured" : "browser-autofill only";
            state.els.lastPayload.textContent = state.lastPayload ? safeShort(state.lastPayload, 84) : "-";
            if (state.els.toggle) {
                state.els.toggle.textContent = state.running ? "Stop" : "Start";
            }
            if (state.els.collapse) {
                state.els.collapse.textContent = state.collapsed ? "Expand" : "Hide";
            }
            state.panel.classList.toggle("qr-panel-collapsed", state.collapsed);
            if (state.els.body) {
                state.els.body.style.display = state.collapsed ? "none" : "block";
            }
            if (state.els.source) {
                state.els.source.textContent = `Source:${state.sourceMode}`;
            }
            if (state.els.debug) {
                state.els.debug.textContent = `Debug:${state.debugEnabled ? "on" : "off"}`;
            }
            if (state.els.debugBox) {
                state.els.debugBox.style.display = state.debugEnabled ? "block" : "none";
            }
            if (state.debugEnabled && state.els.debugPreview) {
                if (state.lastFramePreviewDataUrl) {
                    state.els.debugPreview.src = state.lastFramePreviewDataUrl;
                    state.els.debugPreview.style.display = "block";
                } else {
                    state.els.debugPreview.removeAttribute("src");
                    state.els.debugPreview.style.display = "none";
                }
            }
            if (state.debugEnabled && state.els.debugText) {
                const candidateLines = state.lastCandidateSnapshot.length
                    ? state.lastCandidateSnapshot
                    : ["(no candidates)"];
                const lines = [
                    `mode=${state.sourceMode} candidates=${state.lastCandidateCount}`,
                    `active=${state.lastScanSourceLabel || "-"}`,
                    "candidate list:",
                    ...candidateLines.map((line) => `- ${line}`),
                    "events:",
                    ...state.debugEvents,
                ];
                state.els.debugText.textContent = lines.join("\n");
            }

            const sorted = [...state.sessions.values()].sort((a, b) => b.lastSeenAt - a.lastSeenAt);
            if (!sorted.length) {
                state.els.list.innerHTML = `<div class="qr-muted">No QR sessions yet.</div>`;
                return;
            }

            state.els.list.innerHTML = sorted
                .map((s) => {
                    const urlText = s.latestUrl || s.latestPayload || "";
                    const scoreView = s.score ? `score:${s.score}` : "";
                    const workerView = s.workerStatus ? `worker:${s.workerStatus}` : "";
            const combined = [scoreView, workerView].filter(Boolean).join(" | ") || "-";
            const extraNote = s.workerMessage ? safeShort(s.workerMessage, 46) : "";
            return `
                <div class="qr-session">
                    <div class="qr-session-top">
                        <span>#${s.shortId}</span>
                        <span class="qr-session-score">${escapeHtml(combined)}</span>
                    </div>
                    <div class="qr-session-url" title="${escapeHtml(urlText)}">${escapeHtml(safeShort(urlText, 92))}</div>
                    ${extraNote ? `<div class="qr-muted">${escapeHtml(extraNote)}</div>` : ""}
                    <div class="qr-muted">hits:${s.hitCount}, variants:${s.variantCount}, seen:${formatTime(s.lastSeenAt)}</div>
                </div>
            `;
        })
                .join("");
        }

        return {
            createPanel,
            initDetector,
            startScanning,
            observeDomChanges,
            bindWorkerResultChannel,
            ensureWorkerTab,
            setStatus,
        };
    }

    function bootstrapWorker() {
        sessionStorage.setItem(STORAGE.workerFlag, "1");
        injectWorkerStyles();
        renderWorkerBadge("Worker idle");
        safeSetValue(STORAGE.workerHeartbeat, Date.now());
        window.setInterval(() => safeSetValue(STORAGE.workerHeartbeat, Date.now()), CONFIG.workerHeartbeatMs);

        const state = {
            currentTask: loadWorkerTaskFromSession(),
            actionTimer: null,
            actionStartedAt: 0,
            lastActionMark: new Map(),
            lastScoreReport: "",
            lastForcedNav: {
                taskId: "",
                at: 0,
            },
        };

        bindTaskChannel();
        if (state.currentTask) {
            handleTask(state.currentTask);
        } else {
            const latest = safeGetValue(STORAGE.task, null);
            if (latest) {
                handleTask(latest);
            }
        }

        function bindTaskChannel() {
            if (typeof GM_addValueChangeListener !== "function") {
                return;
            }
            GM_addValueChangeListener(STORAGE.task, (_key, _oldVal, newVal) => {
                if (newVal) {
                    handleTask(newVal);
                }
            });
        }

        function handleTask(task) {
            if (!task || !task.url || !task.taskId) {
                return;
            }
            state.currentTask = task;
            saveWorkerTaskToSession(task);
            reportStatus("navigating", `Open ${safeShort(task.url, 72)}`);
            renderWorkerBadge(`Working #${task.shortId || "?"}`);

            const needDirectOpen = !isSameUrl(location.href, task.url) && !isLikelyAuthPage();
            const justForced =
                state.lastForcedNav.taskId === task.taskId && Date.now() - state.lastForcedNav.at < 8000;

            if (needDirectOpen && !justForced) {
                state.lastForcedNav = {
                    taskId: task.taskId,
                    at: Date.now(),
                };
                location.assign(task.url);
                return;
            }
            startActionLoop();
        }

        function startActionLoop() {
            if (!state.currentTask) {
                return;
            }
            if (state.actionTimer) {
                clearInterval(state.actionTimer);
            }
            state.actionStartedAt = Date.now();
            state.actionTimer = window.setInterval(actionTick, CONFIG.workerActionIntervalMs);
            actionTick();
        }

        function stopActionLoop(finalStatus = "", finalMessage = "") {
            if (state.actionTimer) {
                clearInterval(state.actionTimer);
                state.actionTimer = null;
            }
            if (finalStatus) {
                reportStatus(finalStatus, finalMessage);
            }
        }

        function actionTick() {
            if (!state.currentTask) {
                return;
            }
            if (Date.now() - state.actionStartedAt > CONFIG.workerActionTimeoutMs) {
                stopActionLoop("timeout", "Worker timeout on this page");
                return;
            }
            safeSetValue(STORAGE.workerHeartbeat, Date.now());

            const pageText = normalizeText(document.body ? document.body.innerText : "");
            if (isMobileScanPageUrl(location.href)) {
                stopActionLoop("needs-rescan", "redirected to mLearning ScanPage; likely intermediate link");
                return;
            }
            if (containsAny(pageText, SUCCESS_WORDS)) {
                const score = tryExtractScoreFromPlainText(pageText);
                stopActionLoop("success", score ? `success score=${score}` : "success");
                return;
            }
            if (containsAny(pageText, EXPIRED_WORDS)) {
                stopActionLoop("expired", "QR expired or invalid");
                return;
            }

            const possibleScore = tryExtractScoreFromPlainText(pageText);
            if (possibleScore && state.lastScoreReport !== possibleScore) {
                state.lastScoreReport = possibleScore;
                reportStatus("score-detected", `score=${possibleScore}`, possibleScore);
            }

            tryFillCredentials();
            const clickedLogin = clickButtonByWords(LOGIN_BUTTON_WORDS, "login");
            if (clickedLogin) {
                reportStatus("login-clicked", clickedLogin);
                return;
            }
            const clickedCheckIn = clickButtonByWords(CHECKIN_BUTTON_WORDS, "checkin");
            if (clickedCheckIn) {
                reportStatus("action-clicked", clickedCheckIn);
            }
        }

        function tryFillCredentials() {
            const cred = getEffectiveCredential();
            if (!cred.username || !cred.password) {
                return;
            }

            const usernameInput = queryFirst([
                "input[name='username']",
                "input[name='user']",
                "input[name='j_username']",
                "input[id='username']",
                "input[id='j_username']",
                "input[type='email']",
                "input[autocomplete='username']",
                "input[name*='account' i]",
            ]);
            const passwordInput = queryFirst([
                "input[type='password']",
                "input[name='password']",
                "input[name='j_password']",
                "input[id='j_password']",
                "input[autocomplete='current-password']",
            ]);

            if (usernameInput && !usernameInput.value) {
                setInputValue(usernameInput, cred.username);
            }
            if (passwordInput && !passwordInput.value) {
                setInputValue(passwordInput, cred.password);
            }
        }

        function clickButtonByWords(words, category) {
            const candidates = queryVisibleClickables();
            for (const el of candidates) {
                const text = normalizeText(extractElementText(el));
                if (!text) {
                    continue;
                }
                if (!containsAny(text, words)) {
                    continue;
                }

                const key = `${category}|${text.slice(0, 48)}|${el.tagName}`;
                const lastAt = state.lastActionMark.get(key) || 0;
                if (Date.now() - lastAt < CONFIG.clickDebounceMs) {
                    continue;
                }
                state.lastActionMark.set(key, Date.now());
                el.click();
                return `clicked:${safeShort(text, 40)}`;
            }
            return "";
        }

        function reportStatus(status, message, score = "") {
            const task = state.currentTask;
            if (!task) {
                return;
            }
            const payload = {
                taskId: task.taskId,
                sessionId: task.sessionId,
                shortId: task.shortId,
                status,
                message,
                score,
                url: location.href,
                at: Date.now(),
            };
            safeSetValue(STORAGE.result, payload);
            renderWorkerBadge(`${status}: ${safeShort(message || "", 24)}`);
        }

        function isLikelyAuthPage() {
            const hasPassword = Boolean(document.querySelector("input[type='password']"));
            const urlText = normalizeText(location.href);
            const text = normalizeText(document.body ? document.body.innerText : "");
            const authHint =
                urlText.includes("login") ||
                urlText.includes("jaccount") ||
                text.includes("登录") ||
                text.includes("log in") ||
                text.includes("统一身份认证");
            return hasPassword || authHint;
        }
    }

    function queryVisibleClickables() {
        return Array.from(
            document.querySelectorAll("button, a, input[type='submit'], input[type='button'], [role='button'], .btn")
        ).filter((el) => isElementVisible(el) && !el.disabled);
    }

    function queryFirst(selectors) {
        for (const selector of selectors) {
            const node = document.querySelector(selector);
            if (node) {
                return node;
            }
        }
        return null;
    }

    function loadWorkerTaskFromSession() {
        const raw = sessionStorage.getItem(STORAGE.workerCurrentTask);
        if (!raw) {
            return null;
        }
        try {
            return JSON.parse(raw);
        } catch {
            return null;
        }
    }

    function saveWorkerTaskToSession(task) {
        sessionStorage.setItem(STORAGE.workerCurrentTask, JSON.stringify(task));
    }

    function isSameUrl(left, right) {
        try {
            const l = new URL(left);
            const r = new URL(right);
            return l.href === r.href;
        } catch {
            return left === right;
        }
    }

    function isMobileScanPageUrl(urlText) {
        try {
            const url = new URL(urlText);
            const joined = `${url.pathname}${url.hash}`.toLowerCase();
            return url.hostname.includes("mlearning.sjtu.edu.cn") && joined.includes("scanpage");
        } catch {
            return false;
        }
    }

    function buildSessionKey(rawPayload) {
        const url = toHttpUrl(rawPayload);
        if (!url) {
            return `text|${normalizeText(rawPayload).replace(/\d{6,}/g, "<num>")}`;
        }
        const stablePairs = [];
        const sortedEntries = Array.from(url.searchParams.entries()).sort((a, b) => a[0].localeCompare(b[0]));
        sortedEntries.forEach(([key, value]) => {
            const keyLower = key.toLowerCase();
            if (VOLATILE_QUERY_KEYS.has(keyLower) || looksVolatileValue(value)) {
                return;
            }
            stablePairs.push(`${key}=${value}`);
        });
        return `url|${url.origin}${url.pathname}?${stablePairs.join("&")}`;
    }

    function isLikelySameQuiz(leftPayload, rightPayload) {
        const leftUrl = toHttpUrl(leftPayload);
        const rightUrl = toHttpUrl(rightPayload);
        if (!leftUrl || !rightUrl) {
            return normalizeText(leftPayload) === normalizeText(rightPayload);
        }
        if (leftUrl.origin !== rightUrl.origin || leftUrl.pathname !== rightUrl.pathname) {
            return false;
        }
        const leftIdentity = getQuizIdentity(leftUrl);
        const rightIdentity = getQuizIdentity(rightUrl);
        if (leftIdentity && rightIdentity) {
            return leftIdentity === rightIdentity;
        }
        return true;
    }

    function getQuizIdentity(url) {
        for (const key of QUIZ_ID_KEYS) {
            const value = url.searchParams.get(key);
            if (value) {
                return `${key}:${value}`;
            }
        }
        return "";
    }

    function getEffectiveCredential() {
        const user = CONFIG.loginUsername || safeGetValue(STORAGE.loginUser, "");
        const pass = CONFIG.loginPassword || safeGetValue(STORAGE.loginPass, "");
        return {
            username: String(user || "").trim(),
            password: String(pass || "").trim(),
        };
    }

    function setInputValue(input, value) {
        const descriptor = Object.getOwnPropertyDescriptor(Object.getPrototypeOf(input), "value");
        if (descriptor && descriptor.set) {
            descriptor.set.call(input, value);
        } else {
            input.value = value;
        }
        input.dispatchEvent(new Event("input", { bubbles: true }));
        input.dispatchEvent(new Event("change", { bubbles: true }));
    }

    function tryExtractScoreFromPlainText(text) {
        if (!text) {
            return "";
        }
        const patterns = [
            /(?:score|grade|point|points|得分|分数|成绩)\s*[:：=]?\s*([0-9]+(?:\.[0-9]+)?)/i,
            /([0-9]+(?:\.[0-9]+)?)\s*\/\s*100/i,
            /([0-9]+(?:\.[0-9]+)?)\s*(?:pts?|points|分)\b/i,
        ];
        for (const pattern of patterns) {
            const match = text.match(pattern);
            if (match) {
                return match[1];
            }
        }
        return "";
    }

    function containsAny(text, words) {
        const lower = normalizeText(text);
        return words.some((w) => lower.includes(normalizeText(w)));
    }

    function normalizeText(text) {
        return String(text || "").toLowerCase().replace(/\s+/g, " ").trim();
    }

    function extractElementText(el) {
        if (!el) {
            return "";
        }
        if (el instanceof HTMLInputElement) {
            return el.value || el.getAttribute("value") || "";
        }
        return el.innerText || el.textContent || "";
    }

    function isElementVisible(el) {
        if (!el || !(el instanceof HTMLElement)) {
            return false;
        }
        const style = getComputedStyle(el);
        if (style.display === "none" || style.visibility === "hidden" || Number(style.opacity) < 0.05) {
            return false;
        }
        const rect = el.getBoundingClientRect();
        return rect.width > 2 && rect.height > 2;
    }

    function isVideoElement(video) {
        return Boolean(video && video instanceof HTMLVideoElement);
    }

    function isReadyVideoFrame(video) {
        return Boolean(
            isVideoElement(video) &&
                video.readyState >= HTMLMediaElement.HAVE_CURRENT_DATA &&
                hasVideoDimensions(video)
        );
    }

    function hasVideoDimensions(video) {
        return Boolean(isVideoElement(video) && video.videoWidth > 0 && video.videoHeight > 0);
    }

    function videoArea(video) {
        return video.clientWidth * video.clientHeight;
    }

    function toHttpUrl(raw) {
        if (!raw || typeof raw !== "string") {
            return null;
        }
        const text = raw.trim();
        if (!/^https?:\/\//i.test(text)) {
            return null;
        }
        try {
            return new URL(text);
        } catch {
            return null;
        }
    }

    function looksVolatileValue(value) {
        if (!value) {
            return false;
        }
        if (/^\d{11,}$/.test(value)) {
            return true;
        }
        if (/^[a-f0-9]{24,}$/i.test(value)) {
            return true;
        }
        return /^[A-Za-z0-9\-_]{28,}$/.test(value);
    }

    function hashCode(text) {
        let hash = 0;
        for (let i = 0; i < text.length; i += 1) {
            hash = (hash << 5) - hash + text.charCodeAt(i);
            hash |= 0;
        }
        return hash;
    }

    function safeShort(text, limit) {
        const str = String(text || "");
        if (str.length <= limit) {
            return str;
        }
        return `${str.slice(0, limit - 1)}…`;
    }

    function formatTime(timestamp) {
        const d = new Date(timestamp || Date.now());
        const h = `${d.getHours()}`.padStart(2, "0");
        const m = `${d.getMinutes()}`.padStart(2, "0");
        const s = `${d.getSeconds()}`.padStart(2, "0");
        return `${h}:${m}:${s}`;
    }

    function escapeHtml(text) {
        return String(text)
            .replaceAll("&", "&amp;")
            .replaceAll("<", "&lt;")
            .replaceAll(">", "&gt;")
            .replaceAll('"', "&quot;")
            .replaceAll("'", "&#39;");
    }

    function safeGetValue(key, fallback) {
        try {
            if (typeof GM_getValue === "function") {
                return GM_getValue(key, fallback);
            }
        } catch {
            // Ignore storage errors.
        }
        return fallback;
    }

    function safeSetValue(key, value) {
        try {
            if (typeof GM_setValue === "function") {
                GM_setValue(key, value);
            }
        } catch {
            // Ignore storage errors.
        }
    }

    function injectScannerStyles() {
        const css = `
            #sjtu-qr-auto-score-panel {
                position: fixed;
                right: 14px;
                bottom: 14px;
                width: 390px;
                max-height: 68vh;
                z-index: 2147483000;
                background: rgba(12, 18, 28, 0.95);
                color: #eef3ff;
                border: 1px solid rgba(166, 186, 255, 0.35);
                border-radius: 10px;
                box-shadow: 0 14px 36px rgba(0, 0, 0, 0.35);
                padding: 10px;
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
                font-size: 12px;
            }
            #sjtu-qr-auto-score-panel * {
                box-sizing: border-box;
            }
            .qr-panel-header {
                display: flex;
                align-items: center;
                justify-content: space-between;
                gap: 8px;
                margin-bottom: 8px;
            }
            .qr-panel-header-actions {
                display: flex;
                gap: 6px;
            }
            .qr-panel-title {
                font-weight: 700;
                font-size: 13px;
                margin-bottom: 0;
            }
            .qr-panel-status {
                margin-bottom: 8px;
                line-height: 1.35;
                color: #cfddff;
            }
            .qr-panel-actions {
                display: flex;
                gap: 6px;
                margin-bottom: 8px;
                flex-wrap: wrap;
            }
            .qr-panel-actions button {
                border: 1px solid rgba(162, 188, 255, 0.45);
                background: rgba(41, 73, 145, 0.35);
                color: #eef3ff;
                border-radius: 7px;
                padding: 4px 8px;
                cursor: pointer;
                font-size: 12px;
            }
            .qr-panel-actions button:hover {
                background: rgba(73, 112, 206, 0.42);
            }
            .qr-panel-meta {
                display: grid;
                grid-template-columns: 110px 1fr;
                row-gap: 4px;
                column-gap: 8px;
                margin-bottom: 8px;
            }
            .qr-panel-meta .k {
                color: #a4b7e8;
            }
            .qr-panel-meta .v {
                white-space: nowrap;
                overflow: hidden;
                text-overflow: ellipsis;
            }
            .qr-panel-list {
                border: 1px solid rgba(154, 184, 255, 0.35);
                border-radius: 8px;
                max-height: 240px;
                overflow: auto;
                padding: 6px;
                background: rgba(8, 11, 20, 0.45);
            }
            .qr-debug-box {
                border: 1px solid rgba(154, 184, 255, 0.35);
                border-radius: 8px;
                margin-bottom: 8px;
                padding: 6px;
                background: rgba(10, 14, 25, 0.72);
            }
            .qr-debug-title {
                color: #bcd0ff;
                font-size: 12px;
                margin-bottom: 4px;
            }
            .qr-debug-preview {
                display: block;
                width: 100%;
                max-height: 130px;
                object-fit: contain;
                border-radius: 6px;
                border: 1px solid rgba(120, 150, 230, 0.35);
                margin-bottom: 6px;
            }
            .qr-debug-text {
                margin: 0;
                max-height: 120px;
                overflow: auto;
                white-space: pre-wrap;
                word-break: break-word;
                color: #9fb6eb;
                font-size: 11px;
                line-height: 1.35;
            }
            .qr-session {
                border-bottom: 1px solid rgba(150, 179, 250, 0.24);
                padding: 6px 0;
            }
            .qr-session:last-child {
                border-bottom: 0;
                padding-bottom: 2px;
            }
            .qr-session-top {
                display: flex;
                justify-content: space-between;
                gap: 8px;
                margin-bottom: 2px;
            }
            .qr-session-score {
                color: #8cf3be;
                font-weight: 700;
            }
            .qr-session-url {
                color: #aec8ff;
                white-space: nowrap;
                overflow: hidden;
                text-overflow: ellipsis;
            }
            #sjtu-qr-auto-score-panel.qr-panel-collapsed {
                width: 220px;
                max-height: none;
            }
            #sjtu-qr-auto-score-panel.qr-panel-collapsed .qr-panel-status {
                margin-bottom: 0;
            }
            .qr-muted {
                color: #8fa3d9;
            }
        `;
        applyStyle(css);
    }

    function injectWorkerStyles() {
        const css = `
            #sjtu-qr-worker-badge {
                position: fixed;
                right: 12px;
                top: 12px;
                z-index: 2147483000;
                background: rgba(8, 25, 58, 0.88);
                color: #dbe9ff;
                border: 1px solid rgba(132, 172, 255, 0.55);
                border-radius: 8px;
                padding: 6px 9px;
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
                font-size: 12px;
            }
        `;
        applyStyle(css);
    }

    function renderWorkerBadge(text) {
        let badge = document.getElementById("sjtu-qr-worker-badge");
        if (!badge) {
            badge = document.createElement("div");
            badge.id = "sjtu-qr-worker-badge";
            document.body.appendChild(badge);
        }
        badge.textContent = `QR Worker: ${text || "-"}`;
    }

    function applyStyle(css) {
        if (typeof GM_addStyle === "function") {
            GM_addStyle(css);
            return;
        }
        const style = document.createElement("style");
        style.textContent = css;
        document.head.appendChild(style);
    }
})();
