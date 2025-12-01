import os
import time
import subprocess
import logging
import sys
sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")
import re
import uuid
import shutil
from pathlib import Path

# 导入通用工具模块（自动加载 .env）
from utils import (
    load_dotenv, get_config, setup_logging,
    sanitize_filename, parse_course_metadata,
    clean_model_output, strip_preface_before_marker,
    get_ffmpeg_headers, DEFAULT_HEADERS, ensure_dir
)

# 配置日志和编码
setup_logging()

import google.generativeai as genai
from transcriber import transcribe_audio

# ================= 配置区域 =================
OBSIDIAN_VAULT_PATH = get_config("OBSIDIAN_VAULT_PATH", r"D:\OneDrive\Obsidian")
GOOGLE_API_KEY = get_config("GOOGLE_API_KEY", "")
TEMP_DIR = get_config("TEMP_DIR", "temp_downloads")
DOWNLOAD_DIR = get_config("DOWNLOAD_DIR", r"D:\Download\SJTU_Courses")

HEADERS = DEFAULT_HEADERS

MAX_TRANSCRIPT_CHARS = 100000000000

FFMPEG_RW_TIMEOUT_US = int(get_config("FFMPEG_RW_TIMEOUT_US", 120_000_000))  # 120s
FFMPEG_MAX_RETRIES = int(get_config("FFMPEG_MAX_RETRIES", 4))
DISABLE_PROXY_FOR_FFMPEG = get_config("DISABLE_PROXY_FOR_FFMPEG", "1") not in {"0", "false", "False"}

# ================= 通用学术笔记 Prompt (适配音频输入) =================
SYSTEM_PROMPT = """
你是一位顶尖的AI学术助教，擅长将技术讲座的文字转录转化为**深度详尽、逻辑严密、重难点突出**的多层次学习材料。你的核心使命是：

1. **忠实还原**：确保原始内容不失真、不遗漏
2. **深度挖掘**：不满足于表面描述，要深入剖析"为什么"和"如何"
3. **重难点聚焦**：敏锐识别讲座中的核心概念、关键机制、易混淆点
4. **通用适配**：适用于任何技术学科（计算机、数学、物理、工程等）

**输出质量标准**：
- ✅ 专业性：术语准确，表达规范
- ✅ 完整性：覆盖所有重要知识点，不遗漏细节
- ✅ 深度性：每个概念都要解释清楚"是什么、为什么、怎么做"
- ✅ 逻辑性：知识点之间的关联和递进清晰
- ✅ 实用性：便于理解、记忆、复习、考试

**LaTeX 使用规范**：
- ✅ 数学公式：$E = mc^2$, $$\sum_{i=1}^{n} i = \frac{n(n+1)}{2}$$
- ✅ 技术变量（需视觉区分）：$T_{slot}$, $IP_A$, $\alpha_{max}$
- ❌ 普通术语：Virtual Memory（不要写成 $Virtual Memory$）
- ❌ 简单数值：100KB（不要写成 $100KB$）

**核心重点**：第 3 部分「结构化深度学习笔记」是整个输出的灵魂，务必做到：
1. **详尽**：每个知识点都要充分展开，不能一笔带过
2. **深入**：要有"教科书式"的深度解释
3. **聚焦**：明确标注【重点】【难点】【易错】【常考】

请严格按照以下 5 个部分输出，使用指定的 Markdown 标题。

---

# 1. 流畅化和基础纠错后的原始文本 (信息对照基准)

**目标**：生成一份"可读版逐字稿"，作为后续笔记的**信息完整性校验基准**。

**核心原则**：
- ✅ **完全保留**：所有讲述内容，包括细节、例子、补充说明
- ✅ **流畅可读**：口语转书面，句子通顺，标点准确
- ✅ **术语修正**：根据上下文修正转录错误（如"鲁棒性"误写为"路由性"）
- ❌ **不做删减**：不省略任何讲解内容（即使看似冗余）
- ❌ **不做重组**：保持老师讲述的原始顺序和逻辑流
- ❌ **不加解释**：不添加任何原文没有的背景、定义、总结

**处理清单**：
1. 移除时间戳和序号
2. 合并断句，形成完整句子
3. 修正明显的转录错误（尤其是专业术语）
4. 删除口语填充词（"嗯"、"这个这个"、"然后呢"等）
5. 保留强调性重复（"非常非常重要"、"一定一定要注意"）
6. 自然分段（仅在话题转换或明显停顿处）

**输出格式**：纯文本，自然段落，无标题分割，完整保留讲述内容。

---

# 2. 关键时间节点标注 (视频定位导航)

**目标**：构建一份**视频内容地图**，让用户能快速定位到任何重要知识点的讲解位置。

**标注格式**：`[HH:MM:SS] - 主题/内容概要 【标签】`

**必须标注的时间点**（优先级从高到低）：

**🔴 最高优先级（核心知识点）**：
- 新概念首次出现（不管是否有正式定义）
- 核心定理/公式/算法的引入
- 重要机制/原理的开始讲解
- "为什么"类解释（Why）- 背景、动机、必要性
- "如何"类讲解（How）- 步骤、流程、实现

**🟡 高优先级（重难点）**：
- 老师明确强调："这个很重要"、"考试会考"、"容易出错"
- 难点剖析："大家往往会理解错"、"这里要注意"
- 对比分析："A和B的区别在于..."
- 例题/案例分析的开始

**🟢 中优先级（辅助理解）**：
- 类比/比喻的讲解
- 图表/示意图的解释
- 代码示例/计算过程
- 实际应用场景

**🔵 低优先级（结构标记）**：
- 章节过渡："接下来我们讲..."
- 小节总结："总结一下..."
- 复习回顾："我们之前讲过..."

**标签系统**：
- 【🔥重点】- 老师明确强调或核心知识点
- 【💎难点】- 复杂概念或易错内容
- 【📊示例】- 例题、案例、演示
- 【⚠️易错】- 常见误区或易混淆点
- 【🎯考点】- 明确提到的考试重点

**输出要求**：
- 每个时间点的描述要**具体**（不要"讲解XX"，要"讲解XX的YY特性"）
- 按时间顺序排列
- 平均每5-10分钟至少有2-3个标注
- 重要内容密集区域可以更密集标注

---

# 3. 结构化深度学习笔记 (核心灵魂 - 教科书级详尽讲义)

**🎯 核心使命**：这是整个输出的**灵魂部分**，要达到**教科书级别的深度和详尽度**，让学生看完后能：
1. **深刻理解**每个概念的本质和来龙去脉
2. **清晰掌握**每个机制的工作原理和设计动机
3. **精准记忆**重难点、易错点、考点

**❗质量红线（必须达到）**：
- ❌ 禁止一笔带过：每个知识点必须充分展开
- ❌ 禁止表面描述：必须深入"为什么"和"怎么做"
- ❌ 禁止遗漏细节：讲座提到的所有重要信息都要覆盖
- ✅ 必须有深度：像教科书一样详细解释
- ✅ 必须标重点：【重点】【难点】【易错】【考点】明确标注

---

## 学习笔记：[根据讲座内容生成精确的主题标题]

**覆盖时间范围**: [HH:MM:SS] - [HH:MM:SS]  
**学习目标**: [列出3-5个具体的学习目标]

---

### 1. 知识体系定位

**本节在整体课程中的位置**：
- 前置知识：需要掌握哪些基础概念
- 核心地位：本节解决什么核心问题
- 后续关联：为后续哪些内容铺垫

**主要内容框架**：
- [用简洁的大纲列出本节的主要内容结构]

---

### 2. 核心概念深度解析 【🔥 重点区域】

**处理原则**：每个概念必须回答"是什么、为什么、怎么用"

**格式示例**：

#### 2.1 [概念名称] 【重点/难点/易错】

**定义**（What）：
- 严格的、教科书式的定义
- 用自己的话重新解释（更通俗）

**本质理解**（Essence）：
- 这个概念的核心本质是什么？
- 和类似概念的本质区别在哪里？

**存在意义**（Why）：
- 为什么需要这个概念？解决了什么问题？
- 如果没有它会怎样？

**关键特征**（Features）：
- 列出3-5个最重要的特征/属性
- 每个特征都要解释其意义和影响

**应用场景**（Where）：
- 在什么情况下使用？
- 典型的应用实例？

**易混淆点** 【⚠️易错】：
- 容易和XX概念混淆，区别在于...
- 常见误解：认为...，实际上...

---

### 3. 问题背景与动机分析 【Why exist】

**历史演进**（如果讲座提及）：
- 传统方法/旧技术是什么？
- 为什么传统方法不够好？

**核心问题剖析**：
- 具体要解决什么问题？
- 问题的本质矛盾/瓶颈是什么？
- 为什么这个问题重要/紧迫？

**解决方案引入**：
- 新方法/新技术如何解决上述问题？
- 核心创新点是什么？
- 带来了哪些本质改进？

---

### 4. 原理与机制详细剖析 【🔥 核心重点】

**⚠️ 这是最重要的部分，必须做到"教科书级详尽"**

#### 4.1 [机制/原理名称] 的工作原理

**整体流程概述**：
- 用一段话概括整个过程
- 画出关键步骤的逻辑流程

**详细步骤拆解**：

**步骤1**: [步骤名称]
- **做什么**: 具体操作是什么
- **怎么做**: 详细的执行过程
- **为什么**: 为什么要这样做，设计动机
- **结果**: 产生什么效果/输出
- **注意点** 【⚠️】: 特殊情况/边界条件

**步骤2**: ...
[依次类推，每个步骤都要详细展开]

**关键设计决策**：
- **决策点1**: 为什么选择XX而不是YY？
  - 考虑因素：...
  - 权衡取舍：...
  - 优势：...
  - 代价：...

**工作示例** 【📊】：
- 用具体例子演示整个流程
- 最好是讲座中提到的例子
- 每一步都要配上具体数值/状态

---

### 5. 关键技术细节与参数 【细节决定成败】

**这部分要覆盖讲座中的所有技术细节，不能遗漏**

#### 5.1 关键参数/配置

| 参数/属性 | 含义 | 典型值/范围 | 作用/影响 | 注意事项 |
|-----------|------|-------------|-----------|----------|
| ... | ... | ... | ... | ... |

#### 5.2 数据结构/报文格式（如适用）

**[结构名称]**：
- 字段1: [字段名] - 含义、长度、作用
- 字段2: ...
- 设计考虑：为什么要这样设计？

#### 5.3 算法/策略细节（如适用）

**算法伪代码**（如果讲座有）：
```
[尽量还原讲座中的算法描述]
```

**时间/空间复杂度**（如适用）：
- 时间复杂度：$O(...)$ - 分析推导
- 空间复杂度：$O(...)$ - 分析推导
- 优化空间：...

---

### 6. 难点深度剖析 【💎 攻克难点】

**本节公认难点**：
1. **难点1**: [难点名称]
   - **为什么难**：...
   - **关键理解**：...
   - **突破方法**：...
   - **类比说明**：...

2. **难点2**: ...

**易混淆对比** 【⚠️易错】：

| 概念A | 概念B | 核心区别 | 记忆技巧 |
|-------|-------|----------|----------|
| ... | ... | ... | ... |

---

### 7. 系统交互与协同（如适用）

**如果涉及多组件/多层次协作**：

#### 7.1 组件A的职责
- 负责：...
- 输入：...
- 输出：...
- 与其他组件的接口：...

#### 7.2 组件B的职责
...

#### 7.3 协同流程
[详细描述各组件如何配合完成任务]

---

### 8. 对比与关联 【建立知识网络】

#### 8.1 核心技术对比表

| 对比维度 | 方法/技术A | 方法/技术B | 关键差异 |
|----------|-----------|-----------|----------|
| 核心思想 | ... | ... | ... |
| 适用场景 | ... | ... | ... |
| 优势 | ... | ... | ... |
| 劣势 | ... | ... | ... |
| 复杂度 | ... | ... | ... |

#### 8.2 与前后知识的关联
- **前置知识**: 本节基于XX知识扩展
- **后续铺垫**: 本节为XX知识打基础
- **横向联系**: 与XX章节形成对比/补充

---

### 9. 核心知识点总结 【🎯 必背清单】

**【🔥核心重点】** （必须掌握）：
1. ⭐⭐⭐ [知识点] - [一句话总结]
2. ⭐⭐⭐ ...

**【💎关键难点】** （重点突破）：
1. [难点] - [理解要点]
2. ...

**【⚠️易错易混】** （特别注意）：
1. [易错点] - [正确理解]
2. ...

**【🎓考试要点】** （老师强调/高频考点）：
1. [考点] - [考查方式]
2. ...

---

**📊 知识掌握检验**（自测）：
- [ ] 能否用自己的话解释[核心概念]？
- [ ] 能否画出[关键流程]的步骤图？
- [ ] 能否指出[易混淆概念]的本质区别？
- [ ] 能否解决[典型题目类型]？

---

**风格要求总结**：
1. **详尽度**: 宁可多写，不要漏写
2. **深度性**: 每个"为什么"都要解释清楚
3. **逻辑性**: 知识点之间的递进关系清晰
4. **标注性**: 重难点、易错点明确标注
5. **可读性**: 专业但不晦涩，有条理不混乱

---

# 4. 知识框架可视化 (思维导图 & 依赖关系)

**目标**：将复杂的知识体系**可视化**，帮助建立完整的知识网络。

---

## 4.1 知识点层级结构 (Markdown Outline)

**要求**：
- 完整映射第 3 部分的结构
- 使用 3-4 层缩进展现层级关系
- 每个节点附带简短说明（5-10字）

**示例格式**：
```markdown
- 🎯 [主题]
  - 📌 [一级知识点]
    - 🔸 [二级知识点] - 简要说明
      - 细节点1
      - 细节点2
    - 🔸 [二级知识点] - 简要说明
  - 📌 [一级知识点]
    - ...
```

---

## 4.2 知识依赖关系图 (Mermaid)

**要求**：
- 展示知识点之间的**逻辑依赖**关系
- 标注出**重难点**节点（用特殊样式）
- 展示与前后章节的**关联**

**Mermaid 注意事项**：
- ✅ 节点命名简洁（10字以内）
- ✅ 避免特殊字符（用拼音或英文代替）
- ✅ 使用 `graph TD`（自上而下）或 `graph LR`（自左而右）
- ✅ 用颜色/样式区分重要程度

**示例结构**：
```mermaid
graph TD
    A[前置知识] --> B[核心概念1]
    A --> C[核心概念2]
    B --> D[重要机制] 
    C --> D
    D --> E[应用场景]
    
    style D fill:#ff6b6b,stroke:#c92a2a,stroke-width:3px
    %% 红色表示核心重点
    
    style B fill:#ffd93d,stroke:#f9c74f
    %% 黄色表示难点
```

---

## 4.3 课程知识地图定位

**本节在整个课程中的位置**：
```
[课程总体脉络]
  ├── 前置章节
  │   ├── 基础概念
  │   └── 相关技术
  ├── 🎯 本节内容 ← 当前位置
  │   ├── 核心主题A
  │   ├── 核心主题B
  │   └── 核心主题C
  └── 后续章节
      ├── 高级应用
      └── 综合实践
```

**与相关学科/领域的关系**：
- 本节属于 [学科大类] 中的 [子领域]
- 与 [相关领域] 的联系：...
- 实际应用方向：...

---

# 5. 学习巩固工具包 (复习 & 自测 & 突破)

**目标**：提供**立即可用**的复习和自测工具，帮助快速巩固和查漏补缺。

---

## 5.1 核心要点速记卡 (Cheat Sheet) 【考前必背】

**设计原则**：
- 高度浓缩，只保留最核心的内容
- 便于考前快速复习
- 按重要性排序

**🔥 核心定义**（必背）：
1. **[概念名]**: [一句话定义] - [关键特征]
2. **[概念名]**: ...

**💎 关键公式/算法**（必会）：
1. $公式$ - 含义、适用条件
2. ...

**⚡ 重要流程/步骤**（必懂）：
1. [流程名]: 步骤1 → 步骤2 → 步骤3
2. ...

**📊 核心对比表**（必记）：
| 项目 | A | B | 关键区别 |
|------|---|---|----------|
| ... | ... | ... | ... |

**⚠️ 易错易混**（必看）：
1. ❌ 常见误解：... ✅ 正确理解：...
2. ...

**🎯 考点提示**：
- 选择题常考：...
- 简答题常考：...
- 计算题常考：...

---

## 5.2 自测练习题 (Self-Assessment) 【检验掌握程度】

**题目设计原则**：
- 覆盖所有核心知识点
- 难度递进（基础 → 中等 → 较难）
- 题型多样（概念题、分析题、计算题、综合题）

---

### 📝 题目 1 (基础概念题) 【⭐】

**问题**：[清晰的问题描述]

**完整答案**：

**1. 核心回答**：
[直接回答问题，2-3句话概括]

**2. 详细解释**：
[展开说明，包括：]
- 关键概念的含义
- 相关的背景知识
- 为什么这样回答（reasoning）

**3. 补充说明**：
[可能的扩展、注意事项、易错点]

**4. 参考示例**（如适用）：
[具体例子帮助理解]

**知识点回顾链接**：[[#3.2 核心概念深度解析|点击此处回顾：XX概念详解]]

---

### 📝 题目 2 (机制分析题) 【⭐⭐】

**问题**：[描述一个场景，要求分析机制]

**完整答案**：

**1. 问题分析**：
[分析题目考查的知识点]

**2. 详细解答**：
**步骤1**: [分步解答]
- 在这一步...
- 因为...
- 所以...

**步骤2**: ...

**3. 关键点总结**：
- 核心要点1
- 核心要点2

**知识点回顾链接**：[[#4.1 [机制名称] 的工作原理|点击此处回顾：XX机制详解]]

---

### 📝 题目 3 (对比分析题) 【⭐⭐】

**问题**：[要求对比两个概念/方法]

**完整答案**：

**1. 对比维度分析**：

| 维度 | 方法A | 方法B | 差异原因 |
|------|-------|-------|----------|
| 核心思想 | ... | ... | ... |
| 优势 | ... | ... | ... |
| 劣势 | ... | ... | ... |
| 适用场景 | ... | ... | ... |

**2. 深入分析**：
[为什么有这些区别，背后的设计考虑]

**3. 选择建议**：
[在什么情况下选择哪个]

**知识点回顾链接**：[[#8.1 核心技术对比表|点击此处回顾：XX对比分析]]

---

### 📝 题目 4 (综合应用题) 【⭐⭐⭐】

**问题**：[给出复杂场景，要求综合运用知识]

**完整答案**：

**1. 场景分析**：
[分析题目场景，识别关键要素]

**2. 知识点关联**：
[这道题涉及哪些知识点]

**3. 解题思路**：
[分步骤推导]

**4. 完整解答**：
[详细的解答过程]

**5. 拓展思考**：
[这道题的变形、延伸]

**知识点回顾链接**：[[#4.1 [机制名称] 的工作原理|点击此处回顾：XX原理详解]]

---

### 📝 题目 5-8

[继续设计 4-6 道题，覆盖不同知识点和难度]

---

## 5.3 难点突破指南 (Difficulty Breaker) 【攻克难关】

**本节公认难点及突破策略**：

---

### 💎 难点 1: [难点名称]

**为什么难**：
- 抽象度高/概念复杂
- 和XX概念容易混淆
- 需要XX前置知识

**突破策略**：

**1. 换个角度理解**：
[用不同的方式重新解释]

**2. 类比记忆**：
[用生活中的例子类比]
```
就像...一样，...
这就好比...，其中...
```

**3. 图解记忆**：
[用简图/流程图辅助理解]

**4. 对比记忆**：
[和XX对比，突出差异]

**5. 实践练习**：
[推荐的练习题/场景]

---

### 💎 难点 2: [难点名称]

[同样的结构]

---

## 5.4 学习建议 & 复习策略

**🎯 第一遍学习（理解阶段）**：
1. 先看第1部分（逐字稿），了解老师讲了什么
2. 精读第3部分（笔记），逐个知识点消化
3. 遇到难点，看第5.3部分的突破指南
4. 做第5.2部分的练习题，检验理解

**🔄 第二遍复习（巩固阶段）**：
1. 回顾第2部分（时间节点），重温关键内容
2. 研读第3部分的【重点】【难点】标注部分
3. 背诵第5.1部分（速记卡）
4. 重做第5.2部分的错题

**📝 考前冲刺（记忆阶段）**：
1. 专攻第5.1部分（速记卡），快速过一遍
2. 看第3.9部分（总结清单），查漏补缺
3. 回顾第5.2部分的典型题目
4. 利用第4部分（知识框架）建立宏观认知

**⏰ 时间分配建议**：
- 第一遍学习：60-90分钟
- 第二遍复习：30-45分钟
- 考前冲刺：15-20分钟

**📚 延伸资源推荐**（如果讲座提及）：
- 教材章节：XX教材第X章
- 参考资料：...
- 实践项目：...

---

**🎓 掌握标准自测**：

**基础掌握** (60分及格)：
- [ ] 能说出所有核心概念的定义
- [ ] 能画出关键流程图
- [ ] 能做对基础题（题目1-3）

**良好掌握** (75分良好)：
- [ ] 能解释概念背后的"为什么"
- [ ] 能对比不同方法的优劣
- [ ] 能做对中等题（题目4-6）

**优秀掌握** (85分优秀)：
- [ ] 能灵活运用知识解决新问题
- [ ] 能串联不同知识点
- [ ] 能做对较难题（题目7-8）

---

**SRT 文件内容已提供，现在开始处理：**

"""

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def cleanup_tmp_files(directory: str, extensions: list = None) -> int:
    """
    清理指定目录下的临时文件（.tmp 后缀）。
    
    Args:
        directory: 要清理的目录
        extensions: 可选，只清理这些扩展名的临时文件，如 ['.m4a', '.srt', '.txt', '.md']
    
    Returns:
        清理的文件数量
    """
    if not directory or not os.path.isdir(directory):
        return 0
    
    count = 0
    try:
        for filename in os.listdir(directory):
            if filename.endswith('.tmp'):
                # 如果指定了扩展名过滤
                if extensions:
                    base_name = filename[:-4]  # 去掉 .tmp
                    if not any(base_name.endswith(ext) for ext in extensions):
                        continue
                
                filepath = os.path.join(directory, filename)
                try:
                    os.remove(filepath)
                    logger.debug(f"已清理临时文件: {filepath}")
                    count += 1
                except OSError as e:
                    logger.warning(f"清理临时文件失败 {filepath}: {e}")
    except OSError as e:
        logger.warning(f"遍历目录失败 {directory}: {e}")
    
    if count > 0:
        logger.info(f"已清理 {count} 个临时文件 (目录: {directory})")
    return count


class CoreProcessor:
    def __init__(self):
        genai.configure(api_key=GOOGLE_API_KEY)
        self.model = genai.GenerativeModel(
            "gemini-3-pro-preview",
            system_instruction="你是一位专业的多模态学术助教，严格按照用户指定的 Markdown 结构输出，突出逻辑与核心概念。"
        )
        logger.info("已强制使用 google.generativeai + Gemini 3 Pro")
        
        # 启动时清理残留的临时文件
        self._cleanup_residual_tmp_files()

    def _cleanup_residual_tmp_files(self):
        """清理各目录中残留的临时文件"""
        dirs_to_clean = [DOWNLOAD_DIR, TEMP_DIR]
        
        # 也清理 Obsidian 目录下的临时文件
        if os.path.isdir(OBSIDIAN_VAULT_PATH):
            for item in os.listdir(OBSIDIAN_VAULT_PATH):
                subdir = os.path.join(OBSIDIAN_VAULT_PATH, item)
                if os.path.isdir(subdir):
                    dirs_to_clean.append(subdir)
        
        total = 0
        for d in dirs_to_clean:
            total += cleanup_tmp_files(d)
        
        if total > 0:
            logger.info(f"启动清理完成，共清理 {total} 个残留临时文件")

    def get_ffmpeg_headers(self):
        """生成 ffmpeg headers（复用 utils）"""
        return get_ffmpeg_headers(HEADERS)

    def sanitize_filename(self, name):
        """清理文件名（复用 utils）"""
        return sanitize_filename(name)

    def parse_metadata(self, course_name, lesson_title):
        """解析课程元数据（复用 utils）"""
        return parse_course_metadata(course_name, lesson_title)

    def check_existing_files(self, course_name, lesson_title):
        """
        检测已存在的文件，返回各步骤的完成状态。
        用于 run_full_workflow 智能跳过已完成的步骤。
        
        注意：只检测正式文件，忽略 .tmp 临时文件。
        
        Returns:
            dict: {
                'formatted_name': str,
                'audio_path': str or None,       # 音频文件路径（如存在且完整）
                'audio_complete': bool,          # 音频是否下载完整（>1MB）
                'subtitle_path': str or None,    # 字幕文件路径（优先 txt）
                'transcript_text': str or None,  # 字幕文本内容
                'note_path': str or None,        # 笔记路径（如存在）
                'note_exists': bool,             # 笔记是否已存在
            }
        """
        formatted_name = self.parse_metadata(course_name, lesson_title)
        course_dir = Path(OBSIDIAN_VAULT_PATH) / self.sanitize_filename(course_name)
        
        result = {
            'formatted_name': formatted_name,
            'audio_path': None,
            'audio_complete': False,
            'subtitle_path': None,
            'transcript_text': None,
            'note_path': None,
            'note_exists': False,
        }
        
        # 检查音频（可能在 TEMP_DIR 或 DOWNLOAD_DIR）
        for base_dir in [TEMP_DIR, DOWNLOAD_DIR]:
            audio_path = Path(base_dir) / f"{formatted_name}.m4a"
            if audio_path.exists():
                try:
                    audio_size = audio_path.stat().st_size
                    if audio_size > 1024 * 1024:  # > 1MB 认为完整
                        result['audio_path'] = str(audio_path)
                        result['audio_complete'] = True
                        break
                except OSError:
                    pass
        
        # 检查字幕（优先 txt，其次 srt）- 只在 DOWNLOAD_DIR 和 TEMP_DIR 查找
        # 字幕文件应该和音频在同一目录，不应该在 Obsidian 笔记目录
        for base_dir in [DOWNLOAD_DIR, TEMP_DIR]:
            txt_path = Path(base_dir) / f"{formatted_name}.txt"
            srt_path = Path(base_dir) / f"{formatted_name}.srt"
            
            if txt_path.exists():
                result['subtitle_path'] = str(txt_path)
                try:
                    with open(txt_path, 'r', encoding='utf-8') as f:
                        result['transcript_text'] = f.read()
                except Exception:
                    pass
                break
            elif srt_path.exists():
                result['subtitle_path'] = str(srt_path)
                try:
                    with open(srt_path, 'r', encoding='utf-8') as f:
                        result['transcript_text'] = f.read()
                except Exception:
                    pass
                break
        
        # 检查笔记（笔记在 Obsidian 目录）
        note_path = course_dir / f"{formatted_name}.md"
        if note_path.exists():
            result['note_path'] = str(note_path)
            result['note_exists'] = True
        
        return result

    def download_media(self, url, output_path, audio_only=False, max_retries=None):
        """使用 ffmpeg 下载媒体，遵循官方 HTTP/HTTPS 协议参数并输出详细日志。

        下载流程：先下载到临时文件 (.tmp)，成功后再重命名为正式文件。
        参考: https://ffmpeg.org/ffmpeg-protocols.html#http
        """
        logger.info(f"开始下载: {url} -> {output_path}")

        if max_retries is None:
            max_retries = FFMPEG_MAX_RETRIES

        output_path_obj = Path(output_path)
        if output_path_obj.suffix:
            tmp_filename = f"{output_path_obj.stem}.tmp{output_path_obj.suffix}"
        else:
            tmp_filename = output_path_obj.name + '.tmp'
        tmp_path = str(output_path_obj.with_name(tmp_filename))
        
        # 清理可能存在的残留临时文件
        tmp_path_obj = Path(tmp_path)
        if tmp_path_obj.exists():
            tmp_path_obj.unlink()
            logger.debug(f"清理残留临时文件: {tmp_path}")

        base_cmd = [
            'ffmpeg', '-y', '-hide_banner',
            '-nostdin',
            '-loglevel', 'warning',
            '-reconnect', '1',
            '-reconnect_streamed', '1',
            '-reconnect_delay_max', '5',
            '-reconnect_at_eof', '1',
            '-reconnect_on_network_error', '1',
            '-reconnect_on_http_error', '4xx,5xx',
            '-rw_timeout', str(FFMPEG_RW_TIMEOUT_US),
            '-fflags', '+genpts+discardcorrupt',
            '-analyzeduration', '2000000',
            '-probesize', '2000000',
            '-threads', '4',
            '-user_agent', DEFAULT_HEADERS.get('User-Agent', 'Mozilla/5.0'),
            '-referer', 'https://courses.sjtu.edu.cn/',
            '-headers', self.get_ffmpeg_headers(),
            '-protocol_whitelist', 'file,http,https,tcp,tls,crypto,httpproxy',
            '-i', url,
        ]

        stream_opts = [
            '-vn', '-acodec', 'copy', '-bsf:a', 'aac_adtstoasc'
        ] if audio_only else [
            '-c', 'copy', '-bsf:a', 'aac_adtstoasc'
        ]

        errors = []
        env = os.environ.copy()
        if DISABLE_PROXY_FOR_FFMPEG:
            proxy_keys = [
                'http_proxy', 'https_proxy', 'all_proxy', 'no_proxy',
                'HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'NO_PROXY'
            ]
            removed = False
            for key in proxy_keys:
                if key in env:
                    env.pop(key)
                    removed = True
            env['NO_PROXY'] = '*'
            if removed:
                logger.info("ffmpeg 下载已禁用代理环境变量")

        for attempt in range(1, max_retries + 1):
            cmd = base_cmd + stream_opts + [tmp_path]  # 下载到临时文件
            logger.debug("ffmpeg 命令(%d/%d): %s", attempt, max_retries, ' '.join(cmd))
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding='utf-8',
                errors='replace',
                env=env,
            )

            if proc.returncode == 0:
                if proc.stderr:
                    logger.debug("ffmpeg 输出: %s", proc.stderr.strip())
                # 下载成功，重命名为正式文件
                try:
                    if output_path_obj.exists():
                        output_path_obj.unlink()  # 覆盖已有文件
                    tmp_path_obj.rename(output_path_obj)
                    logger.info(f"下载完成: {output_path}")
                    return True
                except OSError as e:
                    logger.error(f"重命名临时文件失败: {e}")
                    return False

            error_text = (proc.stderr or proc.stdout or '').strip()
            errors.append(error_text)
            logger.error("下载失败 (第%d次, rc=%s): %s", attempt, proc.returncode, error_text or '无详细输出')

            lower_error = (error_text or '').lower()
            if 'moov atom not found' in lower_error:
                logger.warning("⚠️ 检测到 'moov atom not found'，通常意味着链接已过期或网络在下载末尾中断，建议刷新课程链接后重试。")
            if 'error number -138' in lower_error or 'pull function' in lower_error:
                logger.warning("⚠️ TLS 连接被对端重置（Error -138）。若多次出现，请检查代理/网络或尝试重新获取链接。")

            # 清理失败的临时文件
            if tmp_path_obj.exists():
                tmp_path_obj.unlink()

            if attempt < max_retries:
                backoff = min(4, attempt * 2)
                time.sleep(backoff)

        if errors:
            logger.error("ffmpeg 最终失败: %s", errors[-1])
        return False

    def process_with_gemini(self, audio_path, transcript_text=None):
        """
        使用 Gemini 3 Pro 生成笔记。优先使用字幕文本，无法获取时回退到音频上传。
        """
        try:
            if transcript_text:
                logger.info("使用生成的字幕文本调用 Gemini...")
                sanitized_text = self._sanitize_transcript(transcript_text)
                contents = [SYSTEM_PROMPT, sanitized_text]
                return self._generate_note(contents)

            logger.info("使用音频文件调用 Gemini 3 Pro...")
            os.makedirs(TEMP_DIR, exist_ok=True)
            temp_ext = Path(audio_path).suffix or ".mp3"
            temp_filename = f"{uuid.uuid4().hex}{temp_ext}"
            temp_path = os.path.join(TEMP_DIR, temp_filename)
            shutil.copy2(audio_path, temp_path)

            uploaded = None
            try:
                uploaded = genai.upload_file(path=temp_path, mime_type="audio/mp4")
                while uploaded.state.name == "PROCESSING":
                    time.sleep(3)
                    uploaded = genai.get_file(uploaded.name)
                if uploaded.state.name == "FAILED":
                    raise Exception("Gemini 文件处理失败")

                logger.info("音频上传完成，开始生成笔记...")
                contents = [SYSTEM_PROMPT, uploaded]
                return self._generate_note(contents)
            finally:
                if uploaded:
                    try:
                        genai.delete_file(uploaded.name)
                    except Exception:
                        pass
                if os.path.exists(temp_path):
                    os.remove(temp_path)
        except Exception as e:
            logger.error(f"Gemini 处理失败: {e}")
            raise e

    def process_with_gemini_text(self, transcript_text: str) -> str:
        """
        使用 Gemini 处理纯文本字幕（独立 API 使用）
        """
        logger.info("使用字幕文本调用 Gemini...")
        sanitized_text = self._sanitize_transcript(transcript_text)
        contents = [SYSTEM_PROMPT, sanitized_text]
        return self._generate_note(contents)
    
    def _sanitize_transcript(self, text: str) -> str:
        if not text:
            return ""
        text = text.strip()
        if len(text) > MAX_TRANSCRIPT_CHARS:
            logger.warning("字幕文本长度为 %s，超过限制，正在截断...", len(text))
            text = text[:MAX_TRANSCRIPT_CHARS] + "\n\n[... 字幕已截断，剩余部分请查看原始 SRT ...]"
        return text

    def _clean_model_output(self, text: str) -> str:
        """清洗模型输出（复用 utils.clean_model_output）"""
        return clean_model_output(text)

    def _strip_preface_before_marker(self, text: str, max_preface_chars: int = 300) -> str:
        """移除客套前缀（复用 utils.strip_preface_before_marker）"""
        return strip_preface_before_marker(text, max_preface_chars)

    def _generate_note(self, contents):
        """
        生成笔记，采用两次调用+智能拼接策略确保完整输出。
        """
        # 完整性检测标志：笔记模板中的最后一个关键章节
        COMPLETION_MARKER = "5.4 学习建议"
        
        # 第一次调用：生成主体内容
        logger.info("📝 开始第一次生成...")
        response1 = self.model.generate_content(
            contents,
            generation_config=genai.GenerationConfig(
                temperature=0.3,
                max_output_tokens=65536,
            )
        )
        
        first_result = self._clean_model_output(response1.text)
        logger.info(f"✅ 第一次生成完成，字符数: {len(first_result)}")
        
        # 检查第一次生成是否已完整（包含最终章节标志）
        if COMPLETION_MARKER in first_result:
            logger.info(f"✅ 第一次生成已包含 '{COMPLETION_MARKER}'，内容完整")
            return first_result
        
        # 检查是否需要续写（如果字符数较多且可能被截断）
        if len(first_result) < 5000:
            # 内容太短，直接返回并警告
            logger.warning("⚠️ 生成内容过短，可能出现问题")
            return first_result
        
        # 第二次调用：续写未完成部分
        logger.info(f"📝 未检测到 '{COMPLETION_MARKER}'，启动第二次续写...")
        time.sleep(2)  # 避免请求过快
        
        continuation_prompt = [
            "之前生成的内容只是部分，但尚未包含完整的 5 大部分。",
            "请继续补充完成剩余部分（尤其是 5.4 学习建议 & 复习策略），直接从断点处继续输出，无需重复已有内容。",
            "如果已全部完成，请回复：「已全部生成完毕」"
        ]
        
        response2 = self.model.generate_content(
            contents + [first_result] + continuation_prompt,
            generation_config=genai.GenerationConfig(
                temperature=0.3,
                max_output_tokens=65536,
            )
        )
        
        second_result = self._clean_model_output(response2.text)
        logger.info(f"✅ 第二次生成完成，字符数: {len(second_result)}")
        
        # 检查是否真的有续写内容
        if "已全部生成完毕" in second_result or "已经完成" in second_result or len(second_result) < 100:
            logger.info("✅ 模型回复已完成，无需拼接")
            return first_result
        
        # 智能拼接：去除第二次输出中的重复部分
        merged_result = self._merge_continuations(first_result, second_result)
        logger.info(f"✅ 拼接完成，最终字符数: {len(merged_result)}")
        
        # 最终完整性检查
        if COMPLETION_MARKER not in merged_result:
            logger.warning(f"⚠️ 拼接后仍未包含 '{COMPLETION_MARKER}'，内容可能不完整")
        
        return merged_result
    
    def _merge_continuations(self, first_part: str, second_part: str) -> str:
        """
        智能拼接两次生成的内容，去除重复部分
        """
        # 策略1：如果第二部分以 --- 开头，说明是完整续写，直接拼接
        if second_part.startswith("---"):
            logger.info("🔗 检测到完整续写标记，直接拼接")
            return first_part + "\n\n" + second_part
        
        # 策略2：查找第二部分的第一个 --- 分隔符
        separator_index = second_part.find("---")
        if separator_index > 0 and separator_index < 500:
            # 如果 --- 在前面500字符内，可能前面是重复内容
            logger.info(f"🔗 检测到分隔符位置: {separator_index}，去除重复部分")
            # 从分隔符之前开始保留（包含分隔符）
            cleaned_second = second_part[separator_index:]
            # 如果续写段落以 --- 开头，去掉这些分隔线以免残留
            cleaned_second = re.sub(r'(?m)\A(?:[ \t]*-{3,}[ \t]*\r?\n)+', '', cleaned_second)
            return first_part + "\n\n" + cleaned_second
        
        # 策略3：查找明确的章节标题（# 5.3 或 ## 5.3 或 ### 等）
        section_match = re.search(r'\n#{1,3}\s+\d+\.\d+', second_part)
        if section_match:
            start_pos = section_match.start()
            logger.info(f"🔗 检测到章节标题位置: {start_pos}，从此处拼接")
            return first_part + "\n\n" + second_part[start_pos:].lstrip()
        
        # 策略4：直接拼接（保守策略）
        logger.info("🔗 未检测到明确分隔点，直接拼接")
        return first_part + "\n\n" + second_part

    def save_to_obsidian(self, course_name, lesson_title, target_url, note_content, formatted_name):
        """保存笔记到 Obsidian，使用临时文件确保原子性写入。"""
        try:
            course_dir = Path(OBSIDIAN_VAULT_PATH) / self.sanitize_filename(course_name)
            course_dir.mkdir(parents=True, exist_ok=True)
            
            note_path = course_dir / f"{formatted_name}.md"
            tmp_path = course_dir / f"{formatted_name}.md.tmp"
            
            # 清理可能存在的残留临时文件
            if tmp_path.exists():
                tmp_path.unlink()
                logger.debug(f"清理残留临时文件: {tmp_path}")
            
            # 写入临时文件
            with open(tmp_path, 'w', encoding='utf-8') as f:
                f.write(f"**日期**: {time.strftime('%Y-%m-%d')}\n")
                f.write(f"**源视频**: {target_url}\n\n")
                f.write("---\n\n")
                f.write(note_content)
            
            # 成功后重命名为正式文件
            if note_path.exists():
                note_path.unlink()
            tmp_path.rename(note_path)
            
            logger.info(f"笔记已保存至: {note_path}")
            return str(note_path)
        except Exception as e:
            # 清理失败的临时文件
            if tmp_path.exists():
                tmp_path.unlink()
            logger.error(f"保存笔记失败: {e}")
            raise e

    # ================= 三个独立步骤方法（递进式调用）=================
    
    def step_download(self, url, course_name, lesson_title, 
                      skip_existing=False, progress_callback=None, cancel_callback=None):
        """
        步骤1：下载音频
        
        Args:
            url: 视频流 URL
            course_name: 课程名称
            lesson_title: 课节标题
            skip_existing: 如果已存在，是否自动跳过（False 时会返回 exists 状态让调用方决定）
            progress_callback: 进度回调 (status, pct, msg)
            cancel_callback: 取消检测回调
            
        Returns:
            dict: {
                'success': bool,
                'cancelled': bool,
                'skipped': bool,         # 是否跳过（已存在且 skip_existing=True）
                'exists': bool,          # 是否已存在（skip_existing=False 时返回此状态）
                'audio_path': str,       # 音频路径
                'formatted_name': str,
            }
        """
        def should_cancel():
            return callable(cancel_callback) and cancel_callback()
        
        def report(status, pct, msg):
            if progress_callback:
                progress_callback(status, pct, msg)
            else:
                logger.info(f"[{status}] {msg}")
        
        if should_cancel():
            return {"success": False, "cancelled": True}
        
        # 检测已有文件
        existing = self.check_existing_files(course_name, lesson_title)
        formatted_name = existing['formatted_name']
        
        # 如果音频已存在
        if existing['audio_complete'] and existing['audio_path']:
            if skip_existing:
                report("completed", 100, f"✅ 音频已存在，跳过: {existing['audio_path']}")
                return {
                    "success": True,
                    "skipped": True,
                    "exists": True,
                    "audio_path": existing['audio_path'],
                    "formatted_name": formatted_name,
                }
            else:
                # 返回 exists 状态，让调用方（前端）决定是否覆盖
                return {
                    "success": True,
                    "skipped": False,
                    "exists": True,
                    "audio_path": existing['audio_path'],
                    "formatted_name": formatted_name,
                    "message": "音频已存在，请确认是否重新下载"
                }
        
        # 执行下载
        os.makedirs(DOWNLOAD_DIR, exist_ok=True)
        audio_path = os.path.join(DOWNLOAD_DIR, f"{formatted_name}.m4a")
        
        report("downloading", 10, "开始下载音频...")
        if should_cancel():
            return {"success": False, "cancelled": True}
        
        if not self.download_media(url, audio_path, audio_only=True):
            report("error", 0, "下载失败")
            return {"success": False, "error": "下载失败"}
        
        report("completed", 100, f"下载完成: {audio_path}")
        return {
            "success": True,
            "skipped": False,
            "exists": False,
            "audio_path": audio_path,
            "formatted_name": formatted_name,
        }

    def step_transcribe(self, url, course_name, lesson_title,
                        skip_existing=False, progress_callback=None, cancel_callback=None):
        """
        步骤2：转录音频（会先确保音频已下载）
        
        内部调用 step_download(skip_existing=True) 确保音频存在
        
        Args:
            url: 视频流 URL（用于下载，如果需要）
            course_name: 课程名称
            lesson_title: 课节标题
            skip_existing: 如果字幕已存在，是否自动跳过
            progress_callback: 进度回调
            cancel_callback: 取消检测回调
            
        Returns:
            dict: {
                'success': bool,
                'cancelled': bool,
                'skipped': bool,
                'exists': bool,
                'audio_path': str,
                'subtitle_path': str,      # srt 路径
                'transcript_path': str,    # txt 路径
                'transcript_text': str,    # 转录文本
                'formatted_name': str,
            }
        """
        def should_cancel():
            return callable(cancel_callback) and cancel_callback()
        
        def report(status, pct, msg):
            if progress_callback:
                progress_callback(status, pct, msg)
            else:
                logger.info(f"[{status}] {msg}")
        
        if should_cancel():
            return {"success": False, "cancelled": True}
        
        # 1. 先确保音频已下载（自动跳过已存在的）
        report("processing", 5, "检查音频文件...")
        download_result = self.step_download(
            url=url,
            course_name=course_name,
            lesson_title=lesson_title,
            skip_existing=True,  # 转录时自动跳过已有音频
            progress_callback=lambda s, p, m: report(s, int(p * 0.3), m),  # 下载占 0-30%
            cancel_callback=cancel_callback
        )
        
        if not download_result.get("success"):
            return download_result
        
        audio_path = download_result['audio_path']
        formatted_name = download_result['formatted_name']
        
        if should_cancel():
            return {"success": False, "cancelled": True}
        
        # 2. 检查字幕是否已存在
        existing = self.check_existing_files(course_name, lesson_title)
        
        if existing['subtitle_path'] and existing['transcript_text']:
            if skip_existing:
                report("completed", 100, f"✅ 字幕已存在，跳过: {existing['subtitle_path']}")
                return {
                    "success": True,
                    "skipped": True,
                    "exists": True,
                    "audio_path": audio_path,
                    "subtitle_path": existing['subtitle_path'],
                    "transcript_path": existing['subtitle_path'],
                    "transcript_text": existing['transcript_text'],
                    "formatted_name": formatted_name,
                }
            else:
                return {
                    "success": True,
                    "skipped": False,
                    "exists": True,
                    "audio_path": audio_path,
                    "subtitle_path": existing['subtitle_path'],
                    "transcript_text": existing['transcript_text'],
                    "formatted_name": formatted_name,
                    "message": "字幕已存在，请确认是否重新转录"
                }
        
        # 3. 执行转录
        report("processing", 35, "正在转录音频...")
        if should_cancel():
            return {"success": False, "cancelled": True}
        
        try:
            transcript_data = transcribe_audio(
                audio_path=audio_path,
                output_dir=DOWNLOAD_DIR,
                language="auto",
            )
            subtitle_path = transcript_data.get("srt_path")
            transcript_path = transcript_data.get("txt_path")
            transcript_text = transcript_data.get("text")
            
            report("completed", 100, f"转录完成: {subtitle_path}")
            return {
                "success": True,
                "skipped": False,
                "exists": False,
                "audio_path": audio_path,
                "subtitle_path": subtitle_path,
                "transcript_path": transcript_path,
                "transcript_text": transcript_text,
                "formatted_name": formatted_name,
            }
        except Exception as e:
            logger.error(f"转录失败: {e}")
            report("error", 0, f"转录失败: {e}")
            return {"success": False, "error": str(e)}

    def step_transcribe_from_audio(self, audio_path, course_name, lesson_title,
                                   skip_existing=False, progress_callback=None, cancel_callback=None):
        """
        步骤2b：直接从已有音频文件转录（不需要 URL）
        
        用于音频已存在的场景，跳过下载步骤。
        
        Args:
            audio_path: 音频文件路径
            course_name: 课程名称
            lesson_title: 课节标题
            skip_existing: 如果字幕已存在，是否自动跳过
            progress_callback: 进度回调
            cancel_callback: 取消检测回调
            
        Returns:
            dict: 同 step_transcribe
        """
        def should_cancel():
            return callable(cancel_callback) and cancel_callback()
        
        def report(status, pct, msg):
            if progress_callback:
                progress_callback(status, pct, msg)
            else:
                logger.info(f"[{status}] {msg}")
        
        if should_cancel():
            return {"success": False, "cancelled": True}
        
        # 验证音频文件存在
        if not os.path.exists(audio_path):
            report("error", 0, f"音频文件不存在: {audio_path}")
            return {"success": False, "error": f"音频文件不存在: {audio_path}"}
        
        formatted_name = self.parse_metadata(course_name, lesson_title)
        
        # 检查字幕是否已存在
        existing = self.check_existing_files(course_name, lesson_title)
        
        if existing['subtitle_path'] and existing['transcript_text']:
            if skip_existing:
                report("completed", 100, f"✅ 字幕已存在，跳过: {existing['subtitle_path']}")
                return {
                    "success": True,
                    "skipped": True,
                    "exists": True,
                    "audio_path": audio_path,
                    "subtitle_path": existing['subtitle_path'],
                    "transcript_path": existing['subtitle_path'],
                    "transcript_text": existing['transcript_text'],
                    "formatted_name": formatted_name,
                }
            else:
                return {
                    "success": True,
                    "skipped": False,
                    "exists": True,
                    "audio_path": audio_path,
                    "subtitle_path": existing['subtitle_path'],
                    "transcript_text": existing['transcript_text'],
                    "formatted_name": formatted_name,
                    "message": "字幕已存在，请确认是否重新转录"
                }
        
        # 执行转录
        report("processing", 30, "正在转录音频...")
        if should_cancel():
            return {"success": False, "cancelled": True}
        
        try:
            transcript_data = transcribe_audio(
                audio_path=audio_path,
                output_dir=DOWNLOAD_DIR,
                language="auto",
            )
            subtitle_path = transcript_data.get("srt_path")
            transcript_path = transcript_data.get("txt_path")
            transcript_text = transcript_data.get("text")
            
            report("completed", 100, f"转录完成: {subtitle_path}")
            return {
                "success": True,
                "skipped": False,
                "exists": False,
                "audio_path": audio_path,
                "subtitle_path": subtitle_path,
                "transcript_path": transcript_path,
                "transcript_text": transcript_text,
                "formatted_name": formatted_name,
            }
        except Exception as e:
            logger.error(f"转录失败: {e}")
            report("error", 0, f"转录失败: {e}")
            return {"success": False, "error": str(e)}

    def step_generate_note(self, url, course_name, lesson_title,
                           skip_existing=False, progress_callback=None, cancel_callback=None):
        """
        步骤3：生成笔记（会先确保字幕已生成）
        
        内部调用 step_transcribe(skip_existing=True) 确保字幕存在
        
        Args:
            url: 视频流 URL（用于下载，如果需要）
            course_name: 课程名称
            lesson_title: 课节标题
            skip_existing: 如果笔记已存在，是否自动跳过
            progress_callback: 进度回调
            cancel_callback: 取消检测回调
            
        Returns:
            dict: {
                'success': bool,
                'cancelled': bool,
                'skipped': bool,
                'exists': bool,
                'audio_path': str,
                'subtitle_path': str,
                'note_path': str,
                'formatted_name': str,
            }
        """
        def should_cancel():
            return callable(cancel_callback) and cancel_callback()
        
        def report(status, pct, msg):
            if progress_callback:
                progress_callback(status, pct, msg)
            else:
                logger.info(f"[{status}] {msg}")
        
        if should_cancel():
            return {"success": False, "cancelled": True}
        
        # 0. 先检查笔记是否已存在
        existing = self.check_existing_files(course_name, lesson_title)
        formatted_name = existing['formatted_name']
        
        if existing['note_exists'] and existing['note_path']:
            if skip_existing:
                report("completed", 100, f"✅ 笔记已存在，跳过: {existing['note_path']}")
                return {
                    "success": True,
                    "skipped": True,
                    "exists": True,
                    "note_path": existing['note_path'],
                    "subtitle_path": existing.get('subtitle_path'),
                    "formatted_name": formatted_name,
                }
            else:
                # skip_existing=False 时，继续执行以强制重新生成
                report("processing", 5, "🔄 笔记已存在，准备重新生成...")
        
        # 1. 先确保字幕已生成（自动跳过已存在的）
        report("processing", 10, "检查字幕文件...")
        transcribe_result = self.step_transcribe(
            url=url,
            course_name=course_name,
            lesson_title=lesson_title,
            skip_existing=True,  # 生成笔记时自动跳过已有字幕
            progress_callback=lambda s, p, m: report(s, int(10 + p * 0.45), m),  # 转录占 10-55%
            cancel_callback=cancel_callback
        )
        
        if not transcribe_result.get("success"):
            return transcribe_result
        
        audio_path = transcribe_result.get('audio_path')
        subtitle_path = transcribe_result.get('subtitle_path')
        transcript_text = transcribe_result.get('transcript_text')
        
        if should_cancel():
            return {"success": False, "cancelled": True}
        
        # 2. 调用 Gemini 生成笔记
        report("processing", 60, "Gemini 生成笔记中...")
        if should_cancel():
            return {"success": False, "cancelled": True}
        
        try:
            note_content = self.process_with_gemini(audio_path, transcript_text=transcript_text)
        except Exception as e:
            logger.error(f"Gemini 生成失败: {e}")
            report("error", 0, f"Gemini 生成失败: {e}")
            return {"success": False, "error": str(e)}
        
        if should_cancel():
            return {"success": False, "cancelled": True}
        
        # 3. 保存到 Obsidian
        report("processing", 90, "保存笔记...")
        try:
            note_path = self.save_to_obsidian(course_name, lesson_title, url, note_content, formatted_name)
        except Exception as e:
            logger.error(f"保存失败: {e}")
            report("error", 0, f"保存失败: {e}")
            return {"success": False, "error": str(e)}
        
        # 字幕文件已经保存在 DOWNLOAD_DIR，无需额外复制
        
        report("completed", 100, f"笔记生成完成: {note_path}")
        return {
            "success": True,
            "skipped": False,
            "exists": False,
            "audio_path": audio_path,
            "subtitle_path": subtitle_path,
            "note_path": note_path,
            "formatted_name": formatted_name,
        }

    def run_full_workflow(self, url, course_name, lesson_title, progress_callback=None, cancel_callback=None, force_regenerate=False):
        """
        执行完整流程: 下载 -> 转录 -> Gemini -> Obsidian
        
        这是一个便捷方法，内部调用 step_generate_note 实现递进式流程。
        
        Args:
            url: 视频流 URL
            course_name: 课程名称
            lesson_title: 课节标题
            progress_callback: 进度回调函数 (status, pct, msg)
            cancel_callback: 取消检测回调
            force_regenerate: 是否强制重新生成笔记（即使已存在）
        """
        # 直接委托给 step_generate_note，它会自动处理下载和转录
        return self.step_generate_note(
            url=url,
            course_name=course_name,
            lesson_title=lesson_title,
            skip_existing=not force_regenerate,  # force_regenerate=True 时不跳过
            progress_callback=progress_callback,
            cancel_callback=cancel_callback
        )
