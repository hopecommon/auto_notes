// ==UserScript==
// @name         SJTU AI 学习助手 Pro
// @namespace    http://tampermonkey.net/
// @version      3.1.1
// @description  智能化课程笔记生成助手 - 一键下载、转录、生成精美笔记
// @author       AI Learning Assistant Team
// @match        *://oc.sjtu.edu.cn/*
// @match        *://courses.sjtu.edu.cn/*
// @match        *://v.sjtu.edu.cn/*
// @grant        GM_xmlhttpRequest
// @grant        GM_addStyle
// @connect      localhost
// @run-at       document-idle
// @priority     1
// ==/UserScript==

(function () {
    "use strict";

    // 防止与其他脚本冲突的全局标识
    const SCRIPT_ID = "AI_HELPER_PRO_V3";
    if (window[SCRIPT_ID]) {
        console.log("[AI助手 Pro] 脚本已运行，避免重复初始化");
        return;
    }
    window[SCRIPT_ID] = true;

    console.log("[AI助手 Pro] 初始化中...");

    // 状态变量
    let detectedUrls = new Set();
    let panelCreated = false;
    let activeTasks = new Map(); // task_id -> polling interval
    const SERVER_URL = "http://localhost:5000";
    let tasksRestored = false; // 标记是否已从服务器恢复任务
    const PANEL_ID = "sjtu-ai-helper-pro-panel";
    let actionButtons = [];
    const PANEL_SELECTORS = [
        "#sjtu-ai-helper-panel",
        "#sjtu-ai-helper-pro-panel",
        ".ai-helper-panel",
        ".ai-helper-pro-panel",
    ];

    function resetTaskPolling() {
        activeTasks.forEach((interval) => clearInterval(interval));
        activeTasks.clear();
    }

    function reconcilePanels() {
        const seen = new Set();
        const candidates = [];

        PANEL_SELECTORS.forEach((selector) => {
            document.querySelectorAll(selector).forEach((el) => {
                if (!seen.has(el)) {
                    seen.add(el);
                    candidates.push(el);
                }
            });
        });

        let activePanel = null;
        candidates.forEach((panel) => {
            const isCurrentPanel =
                panel.id === PANEL_ID ||
                panel.getAttribute("data-script") === SCRIPT_ID;
            if (isCurrentPanel && !activePanel) {
                activePanel = panel;
                return;
            }
            panel.remove();
        });

        panelCreated = Boolean(activePanel);
        return activePanel;
    }

    function hasEmbeddedCourseFrame() {
        if (window.self !== window.top) {
            return false;
        }

        const frameSelectors = [
            'iframe[src*="courses.sjtu.edu.cn"]',
            'iframe[src*="v.sjtu.edu.cn"]',
            'iframe[src*="oc.sjtu.edu.cn"]',
        ];
        return frameSelectors.some((selector) =>
            document.querySelector(selector)
        );
    }

    function shouldOwnPanel() {
        // 顶层页面如果只是一个课程 iframe 容器，不再额外创建自己的面板，
        // 由 iframe 内实际课程页持有面板，避免一左一右两个 Notes Helper。
        return !hasEmbeddedCourseFrame();
    }

    function isTaskSubmissionPage() {
        const url = window.location.href;
        if (
            url.includes("/login") ||
            url.includes("/dashboard") ||
            url === "https://oc.sjtu.edu.cn/"
        ) {
            return false;
        }
        return (
            url.includes("/courses/") ||
            url.includes("/lti/") ||
            url.includes("/v.sjtu.edu.cn/")
        );
    }

    function updateActionAvailability() {
        const canSubmit = isTaskSubmissionPage() && detectedUrls.size > 0;
        actionButtons.forEach((btn) => {
            const requiresVideo = btn.dataset.requiresVideo === "true";
            const disabled = requiresVideo && !canSubmit;
            btn.disabled = disabled;
            btn.style.opacity = disabled ? "0.45" : "1";
            btn.style.cursor = disabled ? "not-allowed" : "pointer";
            btn.style.pointerEvents = disabled ? "none" : "auto";
        });
    }

    // ============================================================
    // 1. 链接嗅探逻辑
    // ============================================================

    // 方法A: 拦截 XHR 请求 (最常用的动态加载方式)
    const originalOpen = XMLHttpRequest.prototype.open;
    XMLHttpRequest.prototype.open = function (method, url) {
        // SJTU 视频通常是 .mp4 结尾，或者是 m3u8 流
        if (
            (url.includes(".mp4") || url.includes(".m3u8")) &&
            !url.includes("blob:")
        ) {
            // 排除一些无效的短链接或图标
            if (url.length > 20) {
                console.log("[AI助手] 网络嗅探捕获链接:", url);
                detectedUrls.add(url);
                updateButtonState();
            }
        }
        return originalOpen.apply(this, arguments);
    };

    // 方法B: 主动扫描 DOM 中的 Video 标签 (针对已经加载好的视频)
    function scanVideoTags() {
        let foundCount = 0;
        const videos = document.querySelectorAll("video");

        videos.forEach((v) => {
            if (v.src && (v.src.includes("http") || v.src.includes("blob"))) {
                if (!v.src.startsWith("blob:")) {
                    console.log("[AI助手 Pro] DOM 扫描发现链接:", v.src);
                    detectedUrls.add(v.src);
                    foundCount++;
                }
            }

            // 检查 source 标签
            const sources = v.querySelectorAll("source");
            sources.forEach((s) => {
                if (
                    s.src &&
                    s.src.includes("http") &&
                    !s.src.startsWith("blob:")
                ) {
                    console.log(
                        "[AI助手 Pro] DOM 扫描发现 source 链接:",
                        s.src
                    );
                    detectedUrls.add(s.src);
                    foundCount++;
                }
            });
        });

        if (foundCount > 0) {
            console.log(`[AI助手 Pro] 本次扫描发现 ${foundCount} 个视频链接`);
            updateButtonState();
        }

        return foundCount;
    }

    // ============================================================
    // 2. 元数据提取逻辑 (改进版)
    // ============================================================

    function getMetadata() {
        let courseName = "未知课程";
        let lessonTitle = document.title;

        try {
            // 1. 获取课程名 - 从左侧列表或页面标题
            const titleEl =
                document.querySelector(".list-title.courser-video") ||
                document.querySelector("h1") ||
                document.querySelector(".title");
            if (titleEl) {
                let text = titleEl.innerText.trim();
                // 移除括号里的老师名 (如 "课程名(教师...)")
                courseName = text.split("(")[0].trim();
            }

            // 2. 获取当前播放的课程信息
            const activeItem = document.querySelector(
                ".lti-list .list-item--active"
            );
            if (activeItem) {
                const paragraphs = activeItem.querySelectorAll("p");
                let fullText = "";

                paragraphs.forEach((p) => {
                    const text = p.innerText.trim();
                    if (text && text !== courseName) {
                        fullText += (fullText ? " " : "") + text;
                    }
                });

                lessonTitle = fullText || lessonTitle;

                // 如果 fullText 中包含课程名，提取课程名
                // 格式示例: "2025-10-17 08:55 程序语言与编译原理(曹钦翔)"
                const match = fullText.match(
                    /[\u4e00-\u9fa5]+\([^)]+\)|[\u4e00-\u9fa5]+/
                );
                if (match && courseName === "未知课程") {
                    courseName = match[0].split("(")[0].trim();
                }
            }
        } catch (e) {
            console.error("[AI助手] 元数据提取失败:", e);
        }

        return { courseName, lessonTitle };
    }

    // ============================================================
    // 3. UI 界面逻辑 (改为悬浮面板)
    // ============================================================

    // 注入自定义样式
    GM_addStyle(`
        @keyframes slideIn {
            from {
                transform: translateX(100%);
                opacity: 0;
            }
            to {
                transform: translateX(0);
                opacity: 1;
            }
        }
        
        @keyframes pulse {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.6; }
        }
        
        @keyframes shimmer {
            0% { background-position: -1000px 0; }
            100% { background-position: 1000px 0; }
        }
        
        .ai-helper-panel {
            animation: slideIn 0.3s ease-out;
        }
        
        .ai-helper-btn {
            position: relative;
            overflow: hidden;
        }
        
        .ai-helper-btn::before {
            content: '';
            position: absolute;
            top: 0;
            left: -100%;
            width: 100%;
            height: 100%;
            background: linear-gradient(90deg, transparent, rgba(255,255,255,0.3), transparent);
            transition: left 0.5s;
        }
        
        .ai-helper-btn:hover::before {
            left: 100%;
        }
        
        .task-item-enter {
            animation: slideIn 0.3s ease-out;
        }
        
        .task-processing {
            animation: pulse 1.5s ease-in-out infinite;
        }
        
        .custom-scrollbar::-webkit-scrollbar {
            width: 6px;
        }
        
        .custom-scrollbar::-webkit-scrollbar-track {
            background: #f1f1f1;
            border-radius: 3px;
        }
        
        .custom-scrollbar::-webkit-scrollbar-thumb {
            background: #888;
            border-radius: 3px;
        }
        
        .custom-scrollbar::-webkit-scrollbar-thumb:hover {
            background: #555;
        }
        
        .status-badge {
            display: inline-block;
            padding: 2px 8px;
            border-radius: 12px;
            font-size: 11px;
            font-weight: 600;
            animation: slideIn 0.3s ease-out;
        }
        
        .gradient-bg {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        }
        
        .glass-effect {
            background: rgba(255, 255, 255, 0.95);
            backdrop-filter: blur(10px);
            -webkit-backdrop-filter: blur(10px);
        }
    `);

    function createPanel(force = false) {
        if (!shouldOwnPanel()) {
            panelCreated = false;
            return null;
        }

        const activePanel = reconcilePanels();
        if (activePanel) {
            console.log("[AI助手 Pro] 面板已存在，复用当前面板");
            updateActionAvailability();
            return activePanel;
        }

        // 多重检查确保唯一性
        const existing = document.getElementById(PANEL_ID);
        if (existing) {
            console.log("[AI助手 Pro] 面板已存在，跳过创建");
            panelCreated = true;
            updateActionAvailability();
            return existing;
        }

        // 检查是否有同类面板（通过 class 名）
        const existingByClass = document.querySelector(".ai-helper-pro-panel");
        if (existingByClass) {
            console.log("[AI助手 Pro] 检测到同类面板，跳过创建");
            panelCreated = true; // 标记为已创建
            return;
        }

        if (!force && detectedUrls.size === 0) {
            console.log("[AI助手 Pro] 暂无视频，延迟创建面板");
            return;
        }

        if (panelCreated) {
            console.log("[AI助手 Pro] 面板创建标志已设置，跳过");
            return;
        }

        panelCreated = true;
        console.log("[AI助手 Pro] 开始创建面板...");

        const panel = document.createElement("div");
        panel.id = PANEL_ID;
        panel.className = "ai-helper-pro-panel glass-effect"; // 使用唯一类名
        panel.setAttribute("data-script", SCRIPT_ID); // 标记所属脚本
        panel.setAttribute("data-version", "3.1.1"); // 标记版本
        panel.style.cssText = `
            position: fixed;
            bottom: 30px;
            right: 30px;
            z-index: 99999;
            border-radius: 16px;
            box-shadow: 0 8px 32px rgba(0,0,0,0.12), 0 2px 8px rgba(0,0,0,0.08);
            padding: 0;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, "PingFang SC", "Microsoft YaHei", sans-serif;
            font-size: 13px;
            width: 280px;
            transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
            overflow: hidden;
        `;

        // 渐变标题栏
        const header = document.createElement("div");
        header.className = "gradient-bg";
        header.style.cssText = `
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 14px 16px;
            color: white;
        `;

        const headerTitle = document.createElement("div");
        headerTitle.style.cssText =
            "display: flex; align-items: center; gap: 8px;";
        headerTitle.innerHTML = `
            <span style="font-size: 20px;">🤖</span>
            <div>
                <div style="font-weight: 700; font-size: 15px; line-height: 1.2;">Notes Helper</div>
            </div>
        `;

        const minBtn = document.createElement("button");
        minBtn.innerHTML = "−";
        minBtn.style.cssText = `
            background: rgba(255,255,255,0.2);
            border: none;
            color: white;
            width: 28px;
            height: 28px;
            border-radius: 50%;
            cursor: pointer;
            font-size: 20px;
            line-height: 1;
            display: flex;
            align-items: center;
            justify-content: center;
            transition: all 0.2s;
        `;
        minBtn.onmouseover = () =>
            (minBtn.style.background = "rgba(255,255,255,0.3)");
        minBtn.onmouseout = () =>
            (minBtn.style.background = "rgba(255,255,255,0.2)");
        minBtn.onclick = () => {
            const content = document.getElementById("sjtu-ai-content");
            if (content.style.display === "none") {
                content.style.display = "block";
                minBtn.innerHTML = "−";
                panel.style.width = "280px";
            } else {
                content.style.display = "none";
                minBtn.innerHTML = "+";
                panel.style.width = "280px";
            }
        };

        header.appendChild(headerTitle);
        header.appendChild(minBtn);
        panel.appendChild(header);

        // 内容区域
        const content = document.createElement("div");
        content.id = "sjtu-ai-content";
        content.style.cssText = "padding: 16px;";

        // 状态显示（更精美）
        const status = document.createElement("div");
        status.id = "sjtu-ai-status";
        status.className = "status-badge";
        status.style.cssText = `
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            margin-bottom: 16px;
            text-align: center;
            padding: 8px 12px;
            border-radius: 8px;
            font-weight: 600;
            box-shadow: 0 2px 8px rgba(102, 126, 234, 0.3);
        `;
        status.innerHTML = "🔄 正在连接任务服务...";
        content.appendChild(status);

        // 按钮组（优化样式）
        const btnGroup = document.createElement("div");
        btnGroup.style.cssText =
            "display: flex; flex-direction: column; gap: 10px;";

        btnGroup.appendChild(
            createModernBtn(
                "🤖",
                "生成 AI 笔记",
                () => handleAction("note"),
                "linear-gradient(135deg, #667eea 0%, #764ba2 100%)",
                { requiresVideo: true }
            )
        );
        btnGroup.appendChild(
            createModernBtn(
                "🎵",
                "下载音频",
                () => handleAction("audio"),
                "linear-gradient(135deg, #f093fb 0%, #f5576c 100%)",
                { requiresVideo: true }
            )
        );
        btnGroup.appendChild(
            createModernBtn(
                "📝",
                "转录音频",
                () => handleTranscribeAction(),
                "linear-gradient(135deg, #4facfe 0%, #00f2fe 100%)",
                { requiresVideo: true }
            )
        );
        btnGroup.appendChild(
            createModernBtn(
                "🎬",
                "下载视频",
                () => handleAction("video"),
                "linear-gradient(135deg, #fa709a 0%, #fee140 100%)",
                { requiresVideo: true }
            )
        );

        // 工具按钮组
        const toolsGroup = document.createElement("div");
        toolsGroup.style.cssText =
            "display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin-top: 12px;";
        toolsGroup.appendChild(
            createSmallBtn("📋", "复制链接", () => copyVideoLink(), {
                requiresVideo: true,
            })
        );
        toolsGroup.appendChild(
            createSmallBtn("🗑️", "清空完成", () => clearFinishedTasks())
        );
        btnGroup.appendChild(toolsGroup);

        content.appendChild(btnGroup);

        // 任务列表（优化滚动）
        const taskList = document.createElement("div");
        taskList.id = "sjtu-task-list";
        taskList.className = "custom-scrollbar";
        taskList.style.cssText = `
            margin-top: 16px;
            padding-top: 16px;
            border-top: 2px solid #f0f0f0;
            max-height: 300px;
            overflow-y: auto;
        `;
        content.appendChild(taskList);

        panel.appendChild(content);
        document.body.appendChild(panel);
        console.log("[AI助手] 精美面板已创建");
        updateButtonState();
        return panel;
    }

    // 现代化主按钮
    function createModernBtn(icon, text, onClick, gradient, options = {}) {
        const btn = document.createElement("button");
        btn.className = "ai-helper-btn";
        btn.dataset.requiresVideo = options.requiresVideo ? "true" : "false";
        btn.style.cssText = `
            cursor: pointer;
            padding: 12px 16px;
            background: ${gradient};
            border: none;
            color: white;
            border-radius: 10px;
            text-align: left;
            font-size: 13px;
            font-weight: 600;
            transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
            width: 100%;
            box-shadow: 0 2px 8px rgba(0,0,0,0.1);
            display: flex;
            align-items: center;
            gap: 10px;
        `;
        btn.innerHTML = `
            <span style="font-size: 18px;">${icon}</span>
            <span style="flex: 1;">${text}</span>
            <span style="font-size: 16px; opacity: 0.8;">→</span>
        `;
        btn.onmouseover = () => {
            btn.style.transform = "translateY(-2px)";
            btn.style.boxShadow = "0 4px 16px rgba(0,0,0,0.2)";
        };
        btn.onmouseout = () => {
            btn.style.transform = "translateY(0)";
            btn.style.boxShadow = "0 2px 8px rgba(0,0,0,0.1)";
        };
        btn.onclick = onClick;
        actionButtons.push(btn);
        return btn;
    }

    // 小工具按钮
    function createSmallBtn(icon, text, onClick, options = {}) {
        const btn = document.createElement("button");
        btn.className = "ai-helper-btn";
        btn.dataset.requiresVideo = options.requiresVideo ? "true" : "false";
        btn.style.cssText = `
            cursor: pointer;
            padding: 8px 12px;
            background: white;
            border: 2px solid #e0e0e0;
            color: #666;
            border-radius: 8px;
            text-align: center;
            font-size: 12px;
            font-weight: 600;
            transition: all 0.2s;
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 6px;
        `;
        btn.innerHTML = `<span>${icon}</span><span>${text}</span>`;
        btn.onmouseover = () => {
            btn.style.borderColor = "#667eea";
            btn.style.color = "#667eea";
            btn.style.background = "#f8f9ff";
        };
        btn.onmouseout = () => {
            btn.style.borderColor = "#e0e0e0";
            btn.style.color = "#666";
            btn.style.background = "white";
        };
        btn.onclick = onClick;
        actionButtons.push(btn);
        return btn;
    }

    function updateButtonState() {
        if (!shouldOwnPanel()) {
            panelCreated = false;
            return;
        }

        const status = document.getElementById("sjtu-ai-status");
        updateActionAvailability();
        if (status) {
            if (!isTaskSubmissionPage()) {
                status.innerHTML =
                    "📋 当前页面仅显示任务状态；切回课程视频页可继续添加任务";
                status.style.background =
                    "linear-gradient(135deg, #94a3b8 0%, #64748b 100%)";
                status.style.color = "white";
            } else if (detectedUrls.size > 0) {
                status.innerHTML = `✨ 已检测 <strong>${detectedUrls.size}</strong> 个视频源`;
                status.style.background =
                    "linear-gradient(135deg, #667eea 0%, #764ba2 100%)";
                status.style.color = "white";

                if (!panelCreated) {
                    createPanel(true);
                }
            } else {
                status.innerHTML = "🔍 等待视频加载中...";
                status.style.background =
                    "linear-gradient(135deg, #fbc2eb 0%, #a6c1ee 100%)";
                status.style.color = "white";
            }
        }
    }

    function addTaskToUI(
        taskId,
        actionName,
        subtitle = "",
        initialStatus = "queued"
    ) {
        const taskList = document.getElementById("sjtu-task-list");
        if (!taskList) return;

        if (document.getElementById(`task-${taskId}`)) {
            return;
        }

        const taskItem = document.createElement("div");
        taskItem.id = `task-${taskId}`;
        taskItem.className = "task-item-enter";
        taskItem.style.cssText = `
            margin-bottom: 12px;
            padding: 12px;
            background: linear-gradient(135deg, #f5f7fa 0%, #c3cfe2 100%);
            border-radius: 12px;
            font-size: 12px;
            position: relative;
            border: 1px solid rgba(255,255,255,0.5);
            box-shadow: 0 2px 8px rgba(0,0,0,0.06);
            transition: all 0.3s;
        `;

        const subtitleHtml = subtitle
            ? `<div style="font-size: 10px; color: #666; margin-top: 4px; opacity: 0.8;">${subtitle}</div>`
            : "";

        taskItem.innerHTML = `
            <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 8px;">
                <div style="flex: 1;">
                    <div style="font-weight: 700; color: #333; font-size: 13px;">${actionName}</div>
                    ${subtitleHtml}
                </div>
                <button id="task-${taskId}-cancel" style="
                    background: linear-gradient(135deg, #f093fb 0%, #f5576c 100%);
                    color: white;
                    border: none;
                    border-radius: 6px;
                    padding: 4px 8px;
                    font-size: 12px;
                    cursor: pointer;
                    font-weight: 600;
                    transition: all 0.2s;
                    box-shadow: 0 2px 4px rgba(245, 87, 108, 0.3);
                ">✕</button>
            </div>
            <div id="task-${taskId}-status" style="
                color: #666;
                font-size: 11px;
                margin-bottom: 8px;
                font-weight: 500;
            ">⏳ 排队中...</div>
            <div style="background: rgba(255,255,255,0.6); height: 6px; border-radius: 3px; overflow: hidden; box-shadow: inset 0 1px 2px rgba(0,0,0,0.1);">
                <div id="task-${taskId}-progress" style="
                    background: linear-gradient(90deg, #667eea 0%, #764ba2 100%);
                    height: 100%;
                    width: 0%;
                    transition: width 0.5s cubic-bezier(0.4, 0, 0.2, 1);
                    border-radius: 3px;
                "></div>
            </div>
        `;

        taskList.appendChild(taskItem);

        const cancelBtn = document.getElementById(`task-${taskId}-cancel`);
        if (cancelBtn) {
            cancelBtn.onmouseover = () => {
                cancelBtn.style.transform = "scale(1.05)";
                cancelBtn.style.boxShadow = "0 4px 8px rgba(245, 87, 108, 0.4)";
            };
            cancelBtn.onmouseout = () => {
                cancelBtn.style.transform = "scale(1)";
                cancelBtn.style.boxShadow = "0 2px 4px rgba(245, 87, 108, 0.3)";
            };
            cancelBtn.onclick = () => cancelTask(taskId);
        }

        taskList.scrollTop = taskList.scrollHeight;
    }

    function updateTaskUI(taskId, status, progress, message) {
        const statusEl = document.getElementById(`task-${taskId}-status`);
        const progressEl = document.getElementById(`task-${taskId}-progress`);
        const cancelBtn = document.getElementById(`task-${taskId}-cancel`);
        const taskItem = document.getElementById(`task-${taskId}`);

        if (statusEl) {
            let icon = "⏳";
            let textColor = "#666";

            if (status === "completed") {
                icon = "✅";
                textColor = "#10b981";
            } else if (status === "error") {
                icon = "❌";
                textColor = "#ef4444";
            } else if (status === "cancelled") {
                icon = "🚫";
                textColor = "#9E9E9E";
            } else if (status === "processing" || status === "downloading") {
                icon = "⚡";
                textColor = "#667eea";
                taskItem.classList.add("task-processing");
            }

            statusEl.innerHTML = `${icon} ${message || status}`;
            statusEl.style.color = textColor;
        }

        if (progressEl) {
            progressEl.style.width = `${progress}%`;

            let gradient = "linear-gradient(90deg, #667eea 0%, #764ba2 100%)";
            if (status === "completed") {
                gradient = "linear-gradient(90deg, #10b981 0%, #059669 100%)";
            } else if (status === "error") {
                gradient = "linear-gradient(90deg, #ef4444 0%, #dc2626 100%)";
            } else if (status === "cancelled") {
                gradient = "linear-gradient(90deg, #9E9E9E 0%, #757575 100%)";
            }
            progressEl.style.background = gradient;
        }

        if (taskItem) {
            if (status === "completed") {
                taskItem.style.background =
                    "linear-gradient(135deg, #d4fc79 0%, #96e6a1 100%)";
                taskItem.classList.remove("task-processing");
            } else if (status === "error") {
                taskItem.style.background =
                    "linear-gradient(135deg, #ffeaa7 0%, #fdcb6e 100%)";
                taskItem.classList.remove("task-processing");
            } else if (status === "cancelled") {
                taskItem.style.background =
                    "linear-gradient(135deg, #dfe6e9 0%, #b2bec3 100%)";
                taskItem.classList.remove("task-processing");
            }
        }

        if (
            cancelBtn &&
            (status === "completed" ||
                status === "error" ||
                status === "cancelled")
        ) {
            cancelBtn.innerHTML = "🗑";
            cancelBtn.style.background =
                "linear-gradient(135deg, #a8a8a8 0%, #7f7f7f 100%)";
            cancelBtn.onclick = () => deleteTask(taskId);
        }
    }

    function pollTaskStatus(taskId) {
        if (activeTasks.has(taskId)) {
            return;
        }

        const interval = setInterval(() => {
            GM_xmlhttpRequest({
                method: "GET",
                url: `${SERVER_URL}/tasks/${taskId}`,
                onload: function (response) {
                    if (response.status === 200) {
                        const data = JSON.parse(response.responseText);
                        updateTaskUI(
                            taskId,
                            data.status,
                            data.progress,
                            data.message
                        );

                        // 任务完成或出错，停止轮询
                        if (
                            data.status === "completed" ||
                            data.status === "error" ||
                            data.status === "cancelled"
                        ) {
                            clearInterval(interval);
                            activeTasks.delete(taskId);

                            // 3秒后淡出任务项
                            if (data.status === "completed") {
                                setTimeout(() => {
                                    const taskItem = document.getElementById(
                                        `task-${taskId}`
                                    );
                                    if (taskItem) {
                                        taskItem.style.transition =
                                            "opacity 0.5s";
                                        taskItem.style.opacity = "0";
                                        setTimeout(
                                            () => taskItem.remove(),
                                            500
                                        );
                                    }
                                }, 3000);
                            }
                        }
                    }
                },
                onerror: function () {
                    clearInterval(interval);
                    activeTasks.delete(taskId);
                },
            });
        }, 1000); // 每秒轮询一次

        activeTasks.set(taskId, interval);
    }

    function copyVideoLink() {
        scanVideoTags();
        if (detectedUrls.size === 0) {
            showNotification("❌ 未检测到视频链接", "error");
            return;
        }

        const urlList = Array.from(detectedUrls);
        let targetUrl = urlList.find((u) => u.includes(".mp4")) || urlList[0];

        navigator.clipboard
            .writeText(targetUrl)
            .then(() => {
                showNotification("✅ 链接已复制到剪贴板", "success");
                console.log("[AI助手] 已复制链接:", targetUrl);
            })
            .catch((err) => {
                console.error("复制失败:", err);
                showNotification("❌ 复制失败", "error");
            });
    }

    function showNotification(message, type = "info") {
        const status = document.getElementById("sjtu-ai-status");
        if (!status) return;

        const originalHTML = status.innerHTML;
        const originalBg = status.style.background;

        let bgGradient = "linear-gradient(135deg, #667eea 0%, #764ba2 100%)";
        if (type === "success") {
            bgGradient = "linear-gradient(135deg, #10b981 0%, #059669 100%)";
        } else if (type === "error") {
            bgGradient = "linear-gradient(135deg, #ef4444 0%, #dc2626 100%)";
        }

        status.innerHTML = message;
        status.style.background = bgGradient;
        status.style.transform = "scale(1.05)";

        setTimeout(() => {
            status.style.transform = "scale(1)";
        }, 100);

        setTimeout(() => {
            status.innerHTML = originalHTML;
            status.style.background = originalBg;
        }, 2000);
    }

    function cancelTask(taskId) {
        if (!confirm("确定要取消这个任务吗？")) {
            return;
        }

        GM_xmlhttpRequest({
            method: "DELETE",
            url: `${SERVER_URL}/tasks/${taskId}`,
            onload: function (response) {
                if (response.status === 200) {
                    const data = JSON.parse(response.responseText);
                    console.log(`[AI助手] 任务 ${taskId} 已取消`);
                    // 更新UI会通过轮询自动完成
                } else {
                    alert("取消失败：" + response.responseText);
                }
            },
            onerror: function () {
                alert("无法连接到服务器");
            },
        });
    }

    function deleteTask(taskId) {
        GM_xmlhttpRequest({
            method: "DELETE",
            url: `${SERVER_URL}/tasks/${taskId}`,
            onload: function (response) {
                if (response.status === 200) {
                    // 从UI中移除任务项
                    const taskItem = document.getElementById(`task-${taskId}`);
                    if (taskItem) {
                        taskItem.style.transition = "opacity 0.3s";
                        taskItem.style.opacity = "0";
                        setTimeout(() => taskItem.remove(), 300);
                    }
                    // 停止轮询
                    if (activeTasks.has(taskId)) {
                        clearInterval(activeTasks.get(taskId));
                        activeTasks.delete(taskId);
                    }
                    console.log(`[AI助手] 任务 ${taskId} 已删除`);
                } else {
                    alert("删除失败：" + response.responseText);
                }
            },
            onerror: function () {
                alert("无法连接到服务器");
            },
        });
    }

    function clearFinishedTasks() {
        if (
            !confirm(
                "🗑️ 确定要清空所有已完成/已出错的任务吗？\n\n这不会影响正在进行的任务。"
            )
        ) {
            return;
        }

        GM_xmlhttpRequest({
            method: "POST",
            url: `${SERVER_URL}/tasks/clear`,
            headers: { "Content-Type": "application/json" },
            onload: function (response) {
                if (response.status === 200) {
                    const data = JSON.parse(response.responseText);
                    console.log(`[AI助手] 已清空 ${data.removed_count} 个任务`);
                    showNotification(
                        `✨ 已清理 ${data.removed_count} 个任务`,
                        "success"
                    );
                    restoreTasksFromServer(true);
                } else {
                    showNotification("❌ 清空失败", "error");
                }
            },
            onerror: function () {
                showNotification("❌ 无法连接到服务器", "error");
            },
        });
    }

    function restoreTasksFromServer(force = false) {
        if (!force && tasksRestored) {
            return; // 避免重复恢复
        }

        if (force) {
            tasksRestored = false;
            resetTaskPolling();
        }

        GM_xmlhttpRequest({
            method: "GET",
            url: `${SERVER_URL}/tasks`,
            onload: function (response) {
                if (response.status === 200) {
                    const allTasks = JSON.parse(response.responseText);
                    const taskIds = Object.keys(allTasks);

                    if (taskIds.length > 0) {
                        console.log(
                            `[AI助手] 从服务器恢复 ${taskIds.length} 个任务`
                        );

                        if (!panelCreated) {
                            createPanel(true);
                        }

                        const taskList =
                            document.getElementById("sjtu-task-list");
                        if (taskList && force) {
                            taskList.innerHTML = "";
                        }

                        taskIds.forEach((taskId) => {
                            const taskInfo = allTasks[taskId];
                            const actionName =
                                taskInfo.actionLabel ||
                                taskInfo.message ||
                                taskInfo.status ||
                                "未知任务";
                            const subtitle =
                                taskInfo.displayTitle ||
                                taskInfo.lessonTitle ||
                                "";

                            addTaskToUI(
                                taskId,
                                actionName,
                                subtitle,
                                taskInfo.status
                            );
                            updateTaskUI(
                                taskId,
                                taskInfo.status,
                                taskInfo.progress || 0,
                                taskInfo.message
                            );

                            if (
                                [
                                    "queued",
                                    "processing",
                                    "downloading",
                                ].includes(taskInfo.status)
                            ) {
                                pollTaskStatus(taskId);
                            }
                        });

                        const statusEl =
                            document.getElementById("sjtu-ai-status");
                        if (statusEl) {
                            statusEl.innerHTML = `📋 已恢复 <strong>${taskIds.length}</strong> 个任务`;
                            statusEl.style.background =
                                "linear-gradient(135deg, #4facfe 0%, #00f2fe 100%)";
                            statusEl.style.color = "white";
                        }
                    } else if (force) {
                        const taskList =
                            document.getElementById("sjtu-task-list");
                        if (taskList) {
                            taskList.innerHTML = "";
                        }
                    }

                    tasksRestored = true;
                }
            },
            onerror: function () {
                console.warn("[AI助手] 无法连接到服务器，跳过任务恢复");
            },
        });
    }

    // ============================================================
    // 4. 文件检查和智能流程控制
    // ============================================================

    async function checkFiles(courseName, lessonTitle) {
        return new Promise((resolve, reject) => {
            GM_xmlhttpRequest({
                method: "POST",
                url: `${SERVER_URL}/check-files`,
                headers: { "Content-Type": "application/json" },
                data: JSON.stringify({ courseName, lessonTitle }),
                onload: function (response) {
                    if (response.status === 200) {
                        resolve(JSON.parse(response.responseText));
                    } else {
                        reject(new Error("文件检查失败"));
                    }
                },
                onerror: function () {
                    reject(new Error("无法连接到服务器"));
                },
            });
        });
    }

    async function submitTask(endpoint, payload, actionName, subtitle) {
        return new Promise((resolve, reject) => {
            GM_xmlhttpRequest({
                method: "POST",
                url: `${SERVER_URL}${endpoint}`,
                headers: { "Content-Type": "application/json" },
                data: JSON.stringify(payload),
                onload: function (response) {
                    if (response.status === 200) {
                        const res = JSON.parse(response.responseText);
                        const taskId = res.task_id;

                        if (taskId) {
                            addTaskToUI(taskId, actionName, subtitle);
                            pollTaskStatus(taskId);
                            resolve(taskId);
                        } else {
                            alert(`✅ ${res.message}`);
                            resolve(null);
                        }
                    } else {
                        alert(`❌ 失败: ${response.responseText}`);
                        reject(new Error(response.responseText));
                    }
                },
                onerror: function () {
                    alert(
                        "无法连接到本地服务，请检查 auto_study_server.py 是否运行。"
                    );
                    reject(new Error("连接失败"));
                },
            });
        });
    }

    async function handleAction(type) {
        if (!isTaskSubmissionPage()) {
            alert("当前页面只能查看任务状态，请切回课程视频页后再添加新任务。");
            return;
        }

        // 再次扫描
        scanVideoTags();

        if (detectedUrls.size === 0 && type !== "note") {
            alert("未检测到视频链接！请尝试播放视频后再点击。");
            return;
        }

        const metadata = getMetadata();
        const urlList = Array.from(detectedUrls);

        try {
            // 先检查文件状态
            const fileCheck = await checkFiles(
                metadata.courseName,
                metadata.lessonTitle
            );

            if (type === "audio") {
                await handleDownloadAudio(metadata, urlList, fileCheck);
            } else if (type === "video") {
                await handleDownloadVideo(metadata, urlList, fileCheck);
            } else if (type === "note") {
                await handleGenerateNote(metadata, urlList, fileCheck);
            }
        } catch (error) {
            console.error("[AI助手] 操作失败:", error);
        }
    }

    async function handleDownloadAudio(metadata, urlList, fileCheck) {
        // 检查音频是否已存在
        if (fileCheck.audioExists && fileCheck.audioComplete) {
            const action = confirm(
                `音频已存在 (${(fileCheck.audioSize / 1024 / 1024).toFixed(
                    2
                )} MB)\n\n` +
                    `是否重新下载？\n` +
                    `- 点击"确定"重新下载\n` +
                    `- 点击"取消"进行转录`
            );

            if (!action) {
                // 用户选择不重新下载，直接转录
                if (!fileCheck.subtitleExists) {
                    await submitTask(
                        "/transcribe-only",
                        {
                            courseName: metadata.courseName,
                            lessonTitle: metadata.lessonTitle,
                            audioPath: fileCheck.paths.audio,
                            overwriteExisting: false,
                        },
                        "转录音频",
                        metadata.lessonTitle
                    );
                } else {
                    alert(
                        "✅ 音频和字幕都已存在！\n" +
                            `音频: ${fileCheck.paths.audio}\n` +
                            `字幕: ${
                                fileCheck.paths.srt || fileCheck.paths.txt
                            }`
                    );
                }
                return;
            }
        }

        // 下载音频
        if (
            !confirm(
                `确认下载音频吗？\n\n课程: ${metadata.courseName}\n标题: ${metadata.lessonTitle}`
            )
        ) {
            return;
        }

        const targetUrl = urlList.find((u) => u.includes(".mp4")) || urlList[0];
        await submitTask(
            "/download",
            {
                url: targetUrl,
                courseName: metadata.courseName,
                lessonTitle: metadata.lessonTitle,
                filename: metadata.lessonTitle,
                type: "audio",
                overwriteExisting: fileCheck.audioExists && fileCheck.audioComplete,
            },
            "下载音频",
            metadata.lessonTitle
        );
        
        // 已移除自动转录：用户需要手动点击"转录音频"按钮
    }

    async function handleDownloadVideo(metadata, urlList, fileCheck) {
        const videoExists = fileCheck.videoExists && fileCheck.videoComplete;
        if (videoExists) {
            if (!confirm(`视频已存在，是否重新下载？`)) {
                return;
            }
        }

        if (
            !confirm(
                `确认下载视频吗？\n\n课程: ${metadata.courseName}\n标题: ${metadata.lessonTitle}`
            )
        ) {
            return;
        }

        const targetUrl = urlList.find((u) => u.includes(".mp4")) || urlList[0];
        await submitTask(
            "/download",
            {
                url: targetUrl,
                courseName: metadata.courseName,
                lessonTitle: metadata.lessonTitle,
                filename: metadata.lessonTitle,
                type: "video",
                overwriteExisting: videoExists,
            },
            "下载视频",
            metadata.lessonTitle
        );
    }

    // 已移除 handleTranscribeOnly 和 waitForTaskCompletion 函数
    // 现在所有按钮都直接调用对应的递进式接口
    async function handleGenerateNote(metadata, urlList, fileCheck) {
        if (urlList.length === 0) {
            alert("未检测到视频链接，请先播放视频后重试。");
            return;
        }

        // 智能判断：需要下载 -> 转录 -> 生成笔记
        let needDownload = !fileCheck.audioExists || !fileCheck.audioComplete;
        // Gemini 需要 TXT 格式，不能只有 SRT
        let needTranscribe = !fileCheck.txtExists;
        
        // 标记是否需要强制重新生成（笔记已存在且用户确认重新生成）
        let forceRegenerate = false;

        if (fileCheck.noteExists) {
            const action = confirm(
                `笔记已存在！\n` +
                    `路径: ${fileCheck.paths.note}\n\n` +
                    `是否重新生成？`
            );
            if (!action) return;
            forceRegenerate = true;  // 用户确认要重新生成
        }

        let message = `确认生成 AI 笔记吗？\n\n课程: ${metadata.courseName}\n标题: ${metadata.lessonTitle}\n\n`;

        if (needDownload) {
            message += "⚠️ 需要先下载音频\n";
        }
        if (needTranscribe) {
            if (fileCheck.srtExists && !fileCheck.txtExists) {
                message += "⚠️ 需要 TXT 格式字幕（当前只有 SRT，需重新转录）\n";
            } else {
                message += "⚠️ 需要先转录音频\n";
            }
        }
        if (forceRegenerate) {
            message += "🔄 将重新生成笔记（覆盖已有文件）\n";
        }
        message += "\n将自动执行所有必需步骤";

        if (!confirm(message)) {
            return;
        }

        // 使用服务器的递进式流程（一个任务自动完成所有步骤）
        await submitTask(
            "/process",
            {
                urls: urlList,
                courseName: metadata.courseName,
                lessonTitle: metadata.lessonTitle,
                forceRegenerate: forceRegenerate,  // 传递强制重新生成标志
            },
            "生成 AI 笔记",
            metadata.lessonTitle
        );
    }

    // 已移除 submitGenerateNoteOnly 函数，现在直接使用 /process 接口

    async function handleTranscribeAction() {
        if (!isTaskSubmissionPage()) {
            alert("当前页面只能查看任务状态，请切回课程视频页后再添加新任务。");
            return;
        }

        const metadata = getMetadata();

        try {
            const fileCheck = await checkFiles(
                metadata.courseName,
                metadata.lessonTitle
            );

            if (fileCheck.subtitleExists) {
                const action = confirm(
                    `字幕已存在！\n` +
                        `SRT: ${fileCheck.srtExists ? "✅" : "❌"}\n` +
                        `TXT: ${fileCheck.txtExists ? "✅" : "❌"}\n\n` +
                        `是否重新转录？`
                );
                if (!action) return;
            }

            // 使用递进式转录接口（会自动下载音频如果不存在）
            scanVideoTags();
            const urlList = Array.from(detectedUrls);
            
            await submitTask(
                "/transcribe",
                {
                    urls: urlList,
                    courseName: metadata.courseName,
                    lessonTitle: metadata.lessonTitle,
                    overwriteExisting: fileCheck.subtitleExists,
                },
                "转录音频",
                metadata.lessonTitle
            );
        } catch (error) {
            console.error("[AI助手] 转录操作失败:", error);
        }
    }

    // 已移除 waitForTaskCompletion 函数（不再需要手动串联任务）

    // ============================================================
    // 5. 原有功能保持
    // ============================================================

    // 页面加载时立即尝试恢复任务
    setTimeout(() => {
        if (!shouldOwnPanel()) {
            console.log("[AI助手 Pro] 当前顶层页面仅承载课程 iframe，跳过自身面板创建");
            return;
        }

        createPanel(true);
        restoreTasksFromServer();
        updateButtonState();
    }, 1500); // 延迟 1.5 秒，避免与其他脚本冲突

    // 延迟启动，避免与 canvas_for_refer.js 冲突
    setTimeout(() => {
        if (!isTaskSubmissionPage()) {
            console.log("[AI助手 Pro] 当前页面只保持任务面板，不执行视频嗅探");
            updateButtonState();
            return;
        }

        console.log("[AI助手 Pro] 开始视频检测...");

        // 首次立即扫描
        const foundInitial = scanVideoTags();
        if (foundInitial > 0 && !panelCreated) {
            createPanel();
        }

        // 定时检测（不再需要 MutationObserver，避免重复触发）
        let initInterval = setInterval(() => {
            if (!panelCreated) {
                const found = scanVideoTags();
                if (found > 0 || detectedUrls.size > 0) {
                    createPanel();
                    clearInterval(initInterval);
                }
            } else {
                clearInterval(initInterval);
            }
        }, 3000); // 每 3 秒检测一次

        // 15秒后停止检测，避免一直运行
        setTimeout(() => {
            clearInterval(initInterval);
            if (detectedUrls.size > 0) {
                console.log(
                    `[AI助手 Pro] 初始化完成，共检测到 ${detectedUrls.size} 个视频源`
                );
            } else {
                console.log(
                    "[AI助手 Pro] 初始化完成，未检测到视频（可能需要播放视频）"
                );
            }
        }, 15000);
    }, 2000); // 延迟 2 秒启动，让 canvas_for_refer.js 先运行
})();
