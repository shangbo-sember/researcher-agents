#!/usr/bin/env python3
"""
研究协调器 - 通过 openclaw CLI 编排 searcher/writer/coordinator 三角色

流程：并行搜索 → 去重合并 → 生成大纲 → 审核大纲 → 撰写报告 → 审核报告

用法：python3 coordinator.py "中国新能源汽车行业"
"""

import asyncio
import json
import os
import re
import sys
import time
from datetime import datetime

MAX_REVISION_ROUNDS = 2
OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")
TIMEOUT = 600  # 单次 agent 调用超时（秒）

PASS_SCORE = 75  # 审核通过分数线

# ============================================================
# 审核评分标准
# ============================================================

OUTLINE_REVIEW_RUBRIC = """
## 大纲评分标准（满分 100 分）

请逐项打分，每项给出具体扣分理由。

### 1. 结构完整性（25 分）
必须包含以下 6 个标准章节，缺一项扣 5 分，缺两项以上直接判 0 分：
- 执行摘要
- 市场概况
- 竞争格局
- 机会与挑战
- 案例分析
- 结论与建议

### 2. 数据映射（25 分）
每个章节必须标注将引用的具体数据点（数字、来源名称）。
- 每个章节都有明确数据映射：25 分
- 超过 2 个章节缺少数据映射：扣至 10 分
- 超过 4 个章节无数据映射：0 分

### 3. 逻辑递进（25 分）
整体应遵循「现状描述 → 深度分析 → 风险研判 → 行动建议」的递进关系。
- 逻辑清晰、层层递进：25 分
- 章节顺序可调整但不影响理解：15-20 分
- 存在明显跳跃或重复：<15 分

### 4. 可行性验证（25 分）
对照研究材料，检查大纲中计划分析的内容是否有数据支撑。
- 所有计划内容均有对应材料：25 分
- 有 1-2 个小节缺少材料支撑：15-20 分
- 有章节完全无材料支撑（会导致写作时编造数据）：<10 分

### 硬性否决条件（触发任一条直接 REVISION_NEEDED）
- 缺少 2 个以上标准章节
- 超过一半章节无数据映射
- 存在计划分析但研究材料中完全无数据的整个章节
"""

REPORT_REVIEW_RUBRIC = """
## 报告评分标准（满分 100 分）

请逐项打分，并列出每项的具体问题清单。

### 1. 数据引用（30 分）
逐段检查，统计以下情况：
- 每个数字/百分比/排名是否标注了来源（来源名称或 URL）
- 无来源的数据断言数量：0 个=30 分，1-2 个=20 分，3-5 个=10 分，>5 个=0 分
- 【列出所有无来源断言的具体位置和内容】

### 2. 数据准确性（20 分）
将报告中的关键数据与研究材料原文逐条比对：
- 所有数据与材料一致：20 分
- 有 1-2 处数据偏差但不影响结论：15 分
- 有数据与材料矛盾或疑似编造：<10 分
- 【列出所有数据偏差和矛盾的具体内容】

### 3. 论证逻辑（20 分）
- 论点→论据→结论链条完整：20 分
- 有 1-2 处论证跳跃但整体通顺：15 分
- 结论缺乏充分数据支撑，或存在自相矛盾：<10 分
- 【列出逻辑问题的具体位置】

### 4. 结构合规（15 分）
对照已批准的大纲逐章检查：
- 完全符合大纲结构：15 分
- 有 1-2 处小节缺失或顺序调整：10 分
- 大幅偏离大纲：<5 分
- 【列出偏离大纲的具体章节】

### 5. 信息密度（15 分）
检查以下问题：
- 是否有套话开头（如"随着...的发展"）：每处扣 2 分
- 是否有无信息量的段落（纯定性描述无数据）：每处扣 3 分
- 是否有重复内容（不同章节说同一件事）：每处扣 3 分
- 【列出所有低密度段落的位置】

### 硬性否决条件（触发任一条直接 REVISION_NEEDED）
- 无来源数据断言超过 5 个
- 发现任何与研究材料矛盾的数据（疑似编造）
- 缺失大纲中的整个章节
"""

REVIEW_OUTPUT_FORMAT = """
## 输出格式要求

必须严格按以下格式输出，方便程序解析：

```
SCORE: <总分>/100

VERDICT: APPROVED 或 REVISION_NEEDED

### 各维度得分
<维度1>: <得分>/<满分> - <一句话理由>
<维度2>: <得分>/<满分> - <一句话理由>
...

### 问题清单
<如果 REVISION_NEEDED，列出具体的修改要求，按优先级排序>
1. 【必须修改】...
2. 【必须修改】...
3. 【建议修改】...
```

评判规则：
- 总分 ≥ 75 分：VERDICT: APPROVED
- 总分 < 75 分：VERDICT: REVISION_NEEDED
- 触发硬性否决条件：无论总分多少，VERDICT: REVISION_NEEDED
"""


def log(phase: str, msg: str):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] [{phase}] {msg}")


async def call_agent(
    agent_id: str,
    message: str,
    timeout: int = TIMEOUT,
    session_id: str | None = None,
) -> str:
    """调用 openclaw agent 并返回文本结果"""
    cmd = [
        "openclaw", "agent",
        "--agent", agent_id,
        "--message", message,
        "--json",
        "--timeout", str(timeout),
    ]
    if session_id:
        cmd.extend(["--session-id", session_id])

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await asyncio.wait_for(
        proc.communicate(), timeout=timeout + 30
    )

    # JSON 在 stderr 中（openclaw CLI 行为）
    raw = stderr.decode("utf-8", errors="replace")

    # 清洗控制字符（保留换行和 tab）
    raw = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", raw)

    # 找到最外层 JSON 对象（从第一个 { 到最后一个 }）
    start = raw.find("{")
    end = raw.rfind("}")
    if start < 0 or end < 0 or end <= start:
        raise RuntimeError(f"Agent {agent_id} 未返回 JSON:\n{raw[:500]}")

    data = json.loads(raw[start:end + 1])
    texts = [p["text"] for p in data.get("payloads", []) if p.get("text")]
    duration = data.get("meta", {}).get("durationMs", 0)
    result = "\n\n".join(texts)
    log(agent_id, f"完成 ({duration/1000:.1f}s, {len(result)} 字)")
    return result


def parse_review(review_text: str) -> tuple[bool, int]:
    """解析审核结果，返回 (是否通过, 分数)"""
    score_match = re.search(r"SCORE:\s*(\d+)\s*/\s*100", review_text)
    score = int(score_match.group(1)) if score_match else -1

    verdict_match = re.search(r"VERDICT:\s*(APPROVED|REVISION_NEEDED)", review_text)
    if verdict_match:
        verdict = verdict_match.group(1) == "APPROVED"
    else:
        # fallback: 在全文中搜索
        verdict = "APPROVED" in review_text.upper() and "REVISION_NEEDED" not in review_text.upper()

    # 双重检查：即使 LLM 判了 APPROVED，分数不够也要打回
    if score >= 0 and score < PASS_SCORE:
        verdict = False

    return verdict, score


def save(filename: str, content: str):
    """保存文件到 output 目录"""
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    path = os.path.join(OUTPUT_DIR, filename)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    log("save", f"已保存 {path}")


def load_search_cache(topic: str) -> str | None:
    """尝试从 output 目录加载已有的搜索结果"""
    labels = ["市场规模", "竞争玩家", "政策动向", "技术趋势"]
    parts = []
    for i, label in enumerate(labels):
        path = os.path.join(OUTPUT_DIR, f"search_{i+1}_{label}.md")
        if not os.path.exists(path):
            return None
        with open(path, "r", encoding="utf-8") as f:
            parts.append(f"[{label}]\n{f.read()}")
    return "\n\n---\n\n".join(parts)


async def run_research(topic: str, skip_search: bool = False):
    start_time = time.time()
    log("main", f"开始研究：{topic}")

    # ========== Phase 1: 并行搜索 ==========
    all_search = None
    if skip_search:
        all_search = load_search_cache(topic)
        if all_search:
            log("Phase 1", "使用已缓存的搜索结果，跳过搜索")
        else:
            log("Phase 1", "未找到缓存，执行搜索")

    if all_search is None:
        log("Phase 1", "启动 4 个并行搜索任务")
        search_prompts = [
            f"搜索{topic}的市场规模数据，包括近3年的销量、增长率、市场规模。输出结构化结果，注明数据来源和日期。",
            f"搜索{topic}的主要竞争玩家，包括市场份额排名、各家核心优势。输出结构化结果，注明数据来源。",
            f"搜索{topic}的最新政策动向，包括补贴、税收、行业标准。输出结构化结果，注明政策文件来源。",
            f"搜索{topic}的技术发展趋势，包括核心技术路线、最新突破、未来方向。输出结构化结果，注明来源。",
        ]
        search_tasks = [
            call_agent("research-searcher", p, session_id=f"search-{i}")
            for i, p in enumerate(search_prompts)
        ]
        search_results = await asyncio.gather(*search_tasks, return_exceptions=True)

        valid_results = []
        labels = ["市场规模", "竞争玩家", "政策动向", "技术趋势"]
        for i, (label, result) in enumerate(zip(labels, search_results)):
            if isinstance(result, Exception):
                log("Phase 1", f"搜索「{label}」失败: {result}")
                valid_results.append(f"[{label}] 搜索失败")
            else:
                valid_results.append(f"[{label}]\n{result}")
                save(f"search_{i+1}_{label}.md", result)

        all_search = "\n\n---\n\n".join(valid_results)
        log("Phase 1", f"搜索完成，{len(valid_results)} 组结果")

    # ========== Phase 2: 去重合并 ==========
    log("Phase 2", "去重合并搜索结果")
    merge_prompt = (
        f"你是研究协调员。以下是关于「{topic}」的 4 组搜索结果，请进行：\n"
        "1. 按来源 URL 去重\n"
        "2. 合并相同来源的不同数据点\n"
        "3. 标记矛盾数据（同一指标不同来源给出不同数字）\n"
        "4. 按可靠性排序（政府报告 > 研究机构 > 行业媒体）\n"
        "输出合并后的结构化材料，保留所有来源标注。\n\n"
        f"搜索结果：\n{all_search}"
    )
    merged = await call_agent("research-coordinator", merge_prompt)
    save("merged_results.md", merged)

    # ========== Phase 3: 生成报告大纲 ==========
    log("Phase 3", "生成报告大纲")
    outline_prompt = (
        f"你是专业报告撰写专家。根据以下研究材料，为「{topic}」研究报告生成大纲。\n"
        "要求：\n"
        "- 只输出大纲结构和各章节要点，不要写正文\n"
        "- 每个章节必须标注将引用的具体数据点（数字+来源名称）\n"
        "- 必须包含以下 6 个标准章节：执行摘要、市场概况、竞争格局、机会与挑战、案例分析、结论与建议\n"
        "- 只规划研究材料中有数据支撑的内容，不要规划无法用数据论证的章节\n\n"
        f"研究材料：\n{merged}"
    )
    outline = await call_agent("research-writor", outline_prompt)
    save("outline_draft.md", outline)

    # ========== Phase 4: 审核大纲（带评分标准） ==========
    log("Phase 4", "审核大纲")
    review_prompt = (
        f"你是研究协调员。按照以下评分标准审核「{topic}」报告大纲。\n\n"
        f"{OUTLINE_REVIEW_RUBRIC}\n\n"
        f"{REVIEW_OUTPUT_FORMAT}\n\n"
        f"---\n\n待审核大纲：\n{outline}\n\n---\n\n研究材料（用于验证数据映射和可行性）：\n{merged}"
    )
    outline_review = await call_agent("research-coordinator", review_prompt)
    save("outline_review.md", outline_review)

    passed, score = parse_review(outline_review)
    log("Phase 4", f"大纲得分：{score}/100，{'通过' if passed else '未通过'}")

    for i in range(MAX_REVISION_ROUNDS):
        if passed:
            log("Phase 4", "大纲审核通过")
            break
        log("Phase 4", f"大纲需修订（第 {i+1}/{MAX_REVISION_ROUNDS} 轮，得分 {score}）")
        revise_prompt = (
            f"你是专业报告撰写专家。根据以下审核意见修改「{topic}」报告大纲。\n"
            "重点关注标记为【必须修改】的问题。\n\n"
            f"当前大纲：\n{outline}\n\n审核意见：\n{outline_review}\n\n研究材料：\n{merged}"
        )
        outline = await call_agent("research-writor", revise_prompt)
        save(f"outline_revision_{i+1}.md", outline)
        review_prompt2 = (
            f"你是研究协调员。按照以下评分标准再次审核修改后的「{topic}」报告大纲。\n\n"
            f"{OUTLINE_REVIEW_RUBRIC}\n\n"
            f"{REVIEW_OUTPUT_FORMAT}\n\n"
            f"---\n\n待审核大纲：\n{outline}\n\n---\n\n研究材料：\n{merged}"
        )
        outline_review = await call_agent("research-coordinator", review_prompt2)
        save(f"outline_review_{i+1}.md", outline_review)
        passed, score = parse_review(outline_review)
        log("Phase 4", f"修订后得分：{score}/100，{'通过' if passed else '未通过'}")
    else:
        if not passed:
            log("Phase 4", f"大纲修订 {MAX_REVISION_ROUNDS} 轮仍未通过（{score}分），使用最新版本继续")

    save("outline_approved.md", outline)

    # ========== Phase 5: 撰写完整报告 ==========
    log("Phase 5", "撰写完整报告")
    write_prompt = (
        f"你是专业报告撰写专家。根据确认的大纲和所有研究材料，撰写「{topic}」完整研究报告。\n"
        "写作硬性要求（违反将被审核打回）：\n"
        "1. 每个数字、百分比、排名必须标注来源（来源名称或 URL）\n"
        "2. 只使用研究材料中提供的数据，严禁编造数据\n"
        "3. 禁止套话开头（如\"随着...的发展\"），每段必须有信息增量\n"
        "4. 严格按照大纲结构撰写，不得遗漏或大幅调整章节\n"
        "5. 专业术语首次出现时附简要解释\n"
        "6. 图表用 Mermaid 语法描述\n\n"
        f"大纲：\n{outline}\n\n研究材料：\n{merged}"
    )
    report = await call_agent("research-writor", write_prompt, timeout=600)
    save("report_draft.md", report)

    # ========== Phase 6: 审核报告（带评分标准） ==========
    log("Phase 6", "审核报告")
    report_review_prompt = (
        f"你是研究协调员。按照以下评分标准审核「{topic}」研究报告。\n\n"
        f"{REPORT_REVIEW_RUBRIC}\n\n"
        f"{REVIEW_OUTPUT_FORMAT}\n\n"
        f"---\n\n待审核报告：\n{report}\n\n---\n\n已批准大纲（用于检查结构合规）：\n{outline}\n\n---\n\n研究材料（用于核实数据准确性）：\n{merged}"
    )
    report_review = await call_agent("research-coordinator", report_review_prompt)
    save("report_review.md", report_review)

    passed, score = parse_review(report_review)
    log("Phase 6", f"报告得分：{score}/100，{'通过' if passed else '未通过'}")

    for i in range(MAX_REVISION_ROUNDS):
        if passed:
            log("Phase 6", "报告审核通过")
            break
        log("Phase 6", f"报告需修订（第 {i+1}/{MAX_REVISION_ROUNDS} 轮，得分 {score}）")
        fix_prompt = (
            f"你是专业报告撰写专家。根据以下审核意见修改「{topic}」研究报告。\n"
            "重点关注标记为【必须修改】的问题，这些不修复会再次被打回。\n\n"
            f"当前报告：\n{report}\n\n审核意见：\n{report_review}\n\n大纲：\n{outline}\n\n研究材料：\n{merged}"
        )
        report = await call_agent("research-writor", fix_prompt, timeout=600)
        save(f"report_revision_{i+1}.md", report)
        review2_prompt = (
            f"你是研究协调员。按照以下评分标准再次审核修改后的「{topic}」研究报告。\n\n"
            f"{REPORT_REVIEW_RUBRIC}\n\n"
            f"{REVIEW_OUTPUT_FORMAT}\n\n"
            f"---\n\n待审核报告：\n{report}\n\n---\n\n已批准大纲：\n{outline}\n\n---\n\n研究材料：\n{merged}"
        )
        report_review = await call_agent("research-coordinator", review2_prompt)
        save(f"report_review_{i+1}.md", report_review)
        passed, score = parse_review(report_review)
        log("Phase 6", f"修订后得分：{score}/100，{'通过' if passed else '未通过'}")
    else:
        if not passed:
            log("Phase 6", f"报告修订 {MAX_REVISION_ROUNDS} 轮仍未通过（{score}分），使用最新版本")

    # ========== 保存最终报告 ==========
    date_str = datetime.now().strftime("%Y%m%d")
    final_name = f"{topic}_研究报告_{date_str}.md"
    save(final_name, report)
    save("review_final.md", report_review)

    elapsed = time.time() - start_time
    log("main", f"全部完成！耗时 {elapsed/60:.1f} 分钟")
    log("main", f"最终报告：{os.path.join(OUTPUT_DIR, final_name)}")
    log("main", f"最终评分：{score}/100（通过线 {PASS_SCORE} 分）")

    return report


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python3 coordinator.py <研究主题> [--skip-search]")
        print('示例: python3 coordinator.py "中国新能源汽车行业"')
        print('      python3 coordinator.py "中国新能源汽车行业" --skip-search')
        sys.exit(1)

    topic = sys.argv[1]
    skip = "--skip-search" in sys.argv
    asyncio.run(run_research(topic, skip_search=skip))
