# 面板冲突处理

## 历史问题

项目曾经出现过两个 `Notes Helper` 面板同时存在的情况：

- 顶层 Canvas/LTI 宿主页有一个浅层面板
- 深层实际播放页还有一个正确面板

浅层面板通常拿不到真实视频源，因此会出现“等待视频加载中”或“未检测到视频”的错误状态。

## 当前规则

现在只允许真正的播放页持有面板：

- `courses.sjtu.edu.cn/lti/app/lti/vodVideo/playPage...`
- `courses.sjtu.edu.cn/lti/app/lti/liveVideo/index.d2j...`
- `v.sjtu.edu.cn/jy-application-canvas-sjtu-ui/...`
- `vshare.sjtu.edu.cn/play/...`

以下页面会被视为浅层宿主，不允许持有面板：

- `oc.sjtu.edu.cn/courses/<id>`
- `oc.sjtu.edu.cn/courses/<id>/external_tools/<id>`
- 带有 Canvas/LTI 宿主页标记的顶层文档

## 兜底策略

如果当前页面不应该拥有面板，脚本会主动执行清理，而不是仅仅“跳过创建”。

这样可以覆盖：

- 旧实例残留
- SPA 跳转
- 页面先创建后切换上下文

## 调试方法

如果以后又出现双面板，优先检查这两个值：

```js
window.self === window.top
document.querySelectorAll(".ai-helper-pro-panel").length
```

如果需要更细的定位，再检查面板所属文档的 `ownerHref`、`topEqualsSelf` 和 DOM path。
