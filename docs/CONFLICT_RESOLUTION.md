# 脚本冲突解决指南

## 🔍 问题描述

### 现象

-   出现**两个面板**
-   其中一个面板报错："未检测到视频链接"
-   另一个可以正常工作

### 原因

`sjtu_video_helper.js` (AI 助手 Pro) 和 `canvas_for_refer.js` (Canvas 视频播放器插件) 都在同一页面运行，导致冲突。

---

## ✅ 已实施的解决方案

### 1. 全局标识防重复初始化

```javascript
const SCRIPT_ID = "AI_HELPER_PRO_V3";
if (window[SCRIPT_ID]) {
    console.log("[AI助手 Pro] 脚本已运行，避免重复初始化");
    return;
}
window[SCRIPT_ID] = true;
```

**效果**: 防止脚本被多次执行

---

### 2. 唯一面板 ID 和 Class

```javascript
const panelId = "sjtu-ai-helper-pro-panel"; // 唯一 ID
panel.className = "ai-helper-pro-panel glass-effect"; // 唯一 class
panel.setAttribute("data-script", SCRIPT_ID); // 标记所属脚本
panel.setAttribute("data-version", "3.1.1"); // 标记版本
```

**效果**:

-   面板 ID 不会与其他脚本冲突
-   可以通过属性识别所属脚本

---

### 3. 多重唯一性检查

```javascript
// 检查 ID
const existing = document.getElementById(panelId);
if (existing) {
    console.log("[AI助手 Pro] 面板已存在，跳过创建");
    return;
}

// 检查 class
const existingByClass = document.querySelector(".ai-helper-pro-panel");
if (existingByClass) {
    console.log("[AI助手 Pro] 检测到同类面板，跳过创建");
    panelCreated = true;
    return;
}
```

**效果**: 即使 ID 被修改，也能通过 class 检测

---

### 4. 页面类型验证

```javascript
function isValidPage() {
    const url = window.location.href;
    // 排除登录页、主页等非视频页面
    if (
        url.includes("/login") ||
        url.includes("/dashboard") ||
        url === "https://oc.sjtu.edu.cn/"
    ) {
        return false;
    }
    // 必须是课程页面或视频页面
    return (
        url.includes("/courses/") ||
        url.includes("/lti/") ||
        url.includes("/v.sjtu.edu.cn/")
    );
}

if (!isValidPage()) {
    console.log("[AI助手 Pro] 非视频页面，脚本不运行");
    return;
}
```

**效果**: 只在相关页面运行，减少冲突

---

### 5. 延迟启动

```javascript
setTimeout(() => {
    console.log("[AI助手 Pro] 开始视频检测...");
    // ... 初始化逻辑
}, 2000); // 延迟 2 秒启动
```

**效果**:

-   让 `canvas_for_refer.js` 先运行
-   避免同时初始化导致的冲突

---

### 6. 优化视频检测

```javascript
function scanVideoTags() {
    let foundCount = 0;
    const videos = document.querySelectorAll("video");

    videos.forEach((v) => {
        // 检查 video.src
        if (v.src && v.src.includes("http") && !v.src.startsWith("blob:")) {
            detectedUrls.add(v.src);
            foundCount++;
        }

        // 检查 source 标签
        const sources = v.querySelectorAll("source");
        sources.forEach((s) => {
            if (s.src && s.src.includes("http") && !s.src.startsWith("blob:")) {
                detectedUrls.add(s.src);
                foundCount++;
            }
        });
    });

    return foundCount;
}
```

**效果**: 更全面的视频链接检测，减少"未检测到"错误

---

### 7. Userscript 元数据优化

```javascript
// @run-at       document-idle  // 在 DOM 完全加载后运行
// @priority     1               // 优先级（数字越大越优先，但不是所有管理器都支持）
```

**效果**: 控制脚本运行时机

---

## 🧪 测试验证

### 检查面板唯一性

1. 打开课程视频页面
2. 按 `F12` 打开控制台
3. 输入：

```javascript
document.querySelectorAll('[id*="ai-helper"]');
```

**预期结果**: 只有 1 个元素

```javascript
document.querySelectorAll(".ai-helper-pro-panel");
```

**预期结果**: 只有 1 个元素

---

### 检查脚本运行状态

在控制台输入：

```javascript
window.AI_HELPER_PRO_V3;
```

**预期结果**: `true`（表示脚本已运行）

---

### 检查面板属性

```javascript
const panel = document.getElementById("sjtu-ai-helper-pro-panel");
console.log({
    id: panel.id,
    class: panel.className,
    script: panel.getAttribute("data-script"),
    version: panel.getAttribute("data-version"),
});
```

**预期结果**:

```
{
    id: "sjtu-ai-helper-pro-panel",
    class: "ai-helper-pro-panel glass-effect",
    script: "AI_HELPER_PRO_V3",
    version: "3.1.1"
}
```

---

## 🔧 手动修复步骤

### 如果仍然出现两个面板

#### 方法 1: 刷新页面

1. 按 `Ctrl + Shift + R` 硬刷新页面
2. 清除浏览器缓存后再刷新

#### 方法 2: 检查脚本顺序

1. 打开 Tampermonkey 管理面板
2. 检查脚本列表
3. 确保 `SJTU AI 学习助手 Pro` 在列表中
4. 如果有多个相似脚本，禁用旧版本

#### 方法 3: 重新安装脚本

1. 在 Tampermonkey 中删除旧的 `sjtu_video_helper.js`
2. 重新安装新版本（v3.1.1）
3. 刷新页面

#### 方法 4: 手动删除重复面板

在控制台执行：

```javascript
// 查找所有可能的面板
const panels = document.querySelectorAll('[id*="helper"], [class*="helper"]');
console.log(`找到 ${panels.length} 个面板:`);
panels.forEach((p, i) => {
    console.log(`${i + 1}. ID: ${p.id}, Class: ${p.className}`);
});

// 删除非 Pro 版本的面板
document
    .querySelectorAll('[id*="helper"]:not([data-script="AI_HELPER_PRO_V3"])')
    .forEach((p) => {
        console.log("删除旧面板:", p.id);
        p.remove();
    });
```

---

## 🛡️ 与 canvas_for_refer.js 的兼容性

### 功能分工

| 脚本                   | 功能           | 冲突点 |
| ---------------------- | -------------- | ------ |
| `canvas_for_refer.js`  | 视频播放器增强 | ❌ 无  |
| `sjtu_video_helper.js` | AI 笔记生成    | ❌ 无  |

**结论**: 两个脚本功能不重叠，理论上可以共存

---

### 为什么会冲突？

#### 1. 视频检测冲突

-   两个脚本都在检测视频元素
-   可能同时触发初始化

**解决方案**:

-   AI 助手延迟 2 秒启动
-   添加页面类型验证

#### 2. DOM 操作冲突

-   两个脚本都在操作 DOM
-   可能互相干扰

**解决方案**:

-   使用唯一 ID 和 class
-   添加属性标记

#### 3. 全局变量冲突

-   可能使用相同的变量名

**解决方案**:

-   使用 IIFE 封装
-   添加全局标识

---

## 📋 推荐配置

### Tampermonkey 脚本顺序

建议按以下顺序排列（从上到下）：

1. `canvas_for_refer.js` (播放器增强)
2. `sjtu_video_helper.js` (AI 助手 Pro)

**原因**: 让播放器增强先运行，AI 助手后运行

---

### 脚本设置

#### canvas_for_refer.js

```
状态: ✅ 启用
执行时机: document-start
```

#### sjtu_video_helper.js

```
状态: ✅ 启用
执行时机: document-idle (新增)
```

---

## ⚠️ 常见问题

### Q1: 为什么还是出现两个面板？

**可能原因**:

1. 浏览器缓存了旧版本脚本
2. 有多个版本的脚本同时运行

**解决方案**:

1. 硬刷新页面 (`Ctrl + Shift + R`)
2. 检查 Tampermonkey，禁用/删除旧版本
3. 清除浏览器缓存

---

### Q2: 面板显示"未检测到视频链接"？

**可能原因**:

1. 视频还未加载
2. 视频使用了特殊加载方式

**解决方案**:

1. **播放视频** - 视频开始播放后会触发网络请求
2. 等待 3-5 秒让脚本检测
3. 刷新页面重试

---

### Q3: 如何确认脚本正常运行？

在控制台查看日志：

```
[AI助手 Pro] 初始化中...
[AI助手 Pro] 开始视频检测...
[AI助手 Pro] DOM 扫描发现链接: https://...
[AI助手 Pro] 本次扫描发现 1 个视频链接
[AI助手 Pro] 开始创建面板...
[AI助手 Pro] 精美面板已创建
[AI助手 Pro] 初始化完成，共检测到 1 个视频源
```

---

### Q4: 面板位置和其他元素重叠？

**解决方案 1**: 调整 z-index

```javascript
// 在控制台执行
document.getElementById("sjtu-ai-helper-pro-panel").style.zIndex = "999999";
```

**解决方案 2**: 调整面板位置

```javascript
const panel = document.getElementById("sjtu-ai-helper-pro-panel");
panel.style.bottom = "50px";
panel.style.right = "50px";
```

---

## 🎯 最佳实践

### 1. 脚本管理

-   ✅ 只保留最新版本
-   ✅ 定期检查更新
-   ✅ 清理不用的脚本

### 2. 调试技巧

-   ✅ 使用控制台查看日志
-   ✅ 检查元素面板查看 DOM
-   ✅ 使用网络面板查看请求

### 3. 问题报告

如果问题仍然存在，请提供：

-   浏览器版本
-   Tampermonkey 版本
-   脚本版本
-   控制台日志
-   页面 URL

---

## 📝 版本历史

### v3.1.1 (2024-11-24) - 冲突修复版

-   ✅ 添加全局标识防重复初始化
-   ✅ 使用唯一 ID 和 class
-   ✅ 添加多重唯一性检查
-   ✅ 添加页面类型验证
-   ✅ 延迟启动避免冲突
-   ✅ 优化视频检测逻辑
-   ✅ 添加面板属性标记

### v3.1 (2024-11-24) - UI 升级版

-   全新渐变设计
-   流畅动画效果
-   智能通知系统

---

**更新时间**: 2024-11-24  
**状态**: ✅ 已修复冲突问题

---

_"一个页面，一个助手，专注学习"_ 🎓
