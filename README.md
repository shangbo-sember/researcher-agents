# Researcher Agents - 多智能体研究系统

基于 OpenClaw 框架的多智能体协作研究系统，自动化完成行业研究、市场分析、报告撰写等任务。

## 🎯 核心功能

- **并行搜索**：4 个 searcher agent 同时搜索不同维度（市场规模、竞争玩家、政策动向、技术趋势）
- **智能去重**：coordinator 对搜索结果去重、合并、标记矛盾数据
- **大纲生成**：writer 根据材料生成结构化报告大纲
- **审核循环**：coordinator 审核大纲和报告，支持最多 2 轮修订
- **报告输出**：生成完整的 Markdown 格式研究报告

## 🏗️ 系统架构

```
┌─────────────────────────────────────────────────────────┐
│                    用户 (终端)                           │
│              python3 coordinator.py "研究主题"           │
└────────────────────┬────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────┐
│              coordinator.py (调度器)                      │
│  • asyncio 并发控制                                      │
│  • subprocess 调用 openclaw CLI                          │
│  • 字符串拼接传递数据                                     │
│  • 字符串匹配控制审核循环                                 │
└─────────┬───────────────────────────────────────────────┘
          │
    ┌─────┴─────┬─────────────┬──────────────┐
    ▼           ▼             ▼              ▼
┌────────┐ ┌────────┐  ┌──────────┐  ┌──────────┐
│searcher│ │searcher│  │coordinator│ │  writer  │
│ 搜索 1  │ │ 搜索 2  │  │ 审核/合并  │ │  写作    │
└────────┘ └────────┘  └──────────┘  └──────────┘
```

## 📁 项目结构

```
.
├── README.md                    # 本文件
├── research-coordinator/        # 协调器 agent
│   ├── coordinator.py          # 主调度脚本（入口）
│   ├── research.sh             # CLI 快捷命令
│   └── output/                 # 输出目录
├── research-searcher/           # 搜索 agent
└── research-writor/            # 写作 agent
```

## 🚀 快速开始

### 前置条件

1. 安装 [OpenClaw](https://github.com/openclaw/openclaw)
2. 配置好 searcher/coordinator/writor 三个 agent

### 使用方式

#### 方式 1：直接使用 CLI 命令（推荐）

```bash
# 完整流水线（搜索 + 分析 + 大纲 + 写作 + 审核）
research "中国低空经济行业"

# 跳过搜索（复用已有搜索结果）
research "中国新能源汽车行业" --skip-search
```

#### 方式 2：直接运行 Python 脚本

```bash
cd research-coordinator

# 完整流程
python3 coordinator.py "中国低空经济行业"

# 跳过搜索
python3 coordinator.py "中国新能源汽车行业" --skip-search
```

### 输出文件

所有产出在 `research-coordinator/output/` 目录：

```
output/
├── search_1_市场规模.md          # searcher 搜索结果
├── search_2_竞争玩家.md
├── search_3_政策动向.md
├── search_4_技术趋势.md
├── merged_results.md             # coordinator 去重合并
├── outline_draft.md              # writer 初稿大纲
├── outline_approved.md           # 审核通过的大纲
├── report_draft.md               # writer 初稿报告
├── review_report.md              # coordinator 审核意见
└── {主题}_研究报告_{日期}.md      # 最终报告
```

## 🔄 工作流程

### Phase 1: 并行搜索
同时启动 4 个 searcher agent，搜索：
- 市场规模数据（近 3 年销量、增长率）
- 主要竞争玩家（市场份额、核心优势）
- 最新政策动向（补贴、税收、行业标准）
- 技术发展趋势（核心技术路线、最新突破）

### Phase 2: 去重合并
coordinator 对 4 组搜索结果进行：
- 按来源 URL 去重
- 合并相同来源的不同数据点
- 标记矛盾数据
- 按可靠性排序（政府报告 > 研究机构 > 行业媒体）

### Phase 3: 生成大纲
writer 根据合并后的材料生成报告大纲，包含：
- 执行摘要
- 市场概况
- 竞争格局
- 机会与挑战
- 案例分析
- 结论与建议

### Phase 4: 审核大纲（最多 2 轮修订）
coordinator 审核大纲：
- 结构是否完整
- 数据支撑是否充分
- 逻辑顺序是否合理

### Phase 5: 撰写报告
writer 根据确认的大纲撰写完整报告：
- 每个观点有数据支撑
- 注明来源
- 图表用 Mermaid 语法
- 专业术语配合解释

### Phase 6: 审核报告（最多 2 轮修订）
coordinator 审核报告：
- 数据引用是否准确
- 论证逻辑是否通顺
- 是否有未注明来源的断言
- 结构是否符合大纲

## ⚙️ 技术细节

### 核心设计决策

1. **为什么用 subprocess 调 CLI？**
   - OpenClaw 没有 Python SDK
   - 唯一通信方式是 `openclaw agent` CLI 命令

2. **Agent 之间怎么传递数据？**
   - 没有共享内存，全靠 Python 变量 + prompt 拼接
   - 数据流：agent 回复 → Python 变量 → 拼入下一个 prompt → 下一个 agent

3. **并行怎么实现？**
   - Phase 1 用 `asyncio.gather` 并发 4 个搜索任务
   - 后续步骤串行（依赖上一步输出）

4. **审核回路怎么工作？**
   - coordinator 回复包含 `APPROVED` 或 `REVISION_NEEDED`
   - Python 脚本字符串匹配决定是否继续循环

## 📋 配置说明

### coordinator.py 参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `MAX_REVISION_ROUNDS` | 2 | 最大修订轮数 |
| `TIMEOUT` | 600 | 单次 agent 调用超时（秒） |
| `OUTPUT_DIR` | `./output/` | 输出目录 |

### Agent 配置

每个 agent 目录下有独立的配置文件：
- `AGENTS.md` - Agent 行为规范
- `SOUL.md` - Agent 人格设定
- `TOOLS.md` - 工具配置

## 🛠️ 开发指南

### 添加新的搜索维度

编辑 `coordinator.py` 的 Phase 1 部分：

```python
search_prompts = [
    # 添加新的搜索任务
    f"搜索{topic}的...",
]
```

### 修改审核标准

编辑 Phase 4 和 Phase 6 的 `review_prompt`，调整审核维度。

### 自定义报告结构

修改 Phase 3 的 `outline_prompt`，指定不同的大纲模板。

## 📄 许可证

MIT License

## 🙏 致谢

- [OpenClaw](https://github.com/openclaw/openclaw) - 多智能体协作框架
