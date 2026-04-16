# openclaw-agents/coordinator.py
"""
研究协调器 - 三角色架构：coordinator（编排/分析/审核）、searcher（搜索）、writer（撰写）

流程：并行搜索 → 去重合并 → 生成大纲 → 审核大纲 → 撰写报告 → 审核报告
"""

import asyncio
from openclaw import AgentPool, SharedMemory

MAX_REVISION_ROUNDS = 2


async def run_research(topic: str) -> dict:
    """
    执行完整的研究流程

    Args:
        topic: 研究主题

    Returns:
        审核后的最终报告
    """
    memory = SharedMemory("research_project")
    pool = AgentPool()

    # ========== Phase 1: 并行搜索 ==========
    print(f"[Coordinator] Phase 1/6: 并行搜索 - {topic}")

    search_tasks = [
        pool.run("searcher", f"搜索{topic}的市场规模数据"),
        pool.run("searcher", f"搜索{topic}的主要竞争玩家"),
        pool.run("searcher", f"搜索{topic}的最新政策动向"),
        pool.run("searcher", f"搜索{topic}的技术发展趋势"),
    ]
    search_results = await asyncio.gather(*search_tasks)
    memory.set("search_results", search_results)
    print(f"[Coordinator] Phase 1 完成，共 {len(search_results)} 组结果")

    # ========== Phase 2: 去重合并（coordinator 自行处理） ==========
    print("[Coordinator] Phase 2/6: 去重合并搜索结果")

    merged = await pool.run(
        "coordinator",
        "对以下搜索结果进行去重合并：\n"
        "1. 按来源URL去重\n"
        "2. 合并相同来源的不同数据点\n"
        "3. 标记矛盾数据（同一指标不同来源给出不同数字）\n"
        "4. 按可靠性排序（政府报告 > 研究机构 > 行业媒体）\n"
        "输出合并后的结构化材料",
        context={"search_results": search_results},
    )
    memory.set("merged_results", merged)

    # ========== Phase 3: 生成报告大纲 ==========
    print("[Coordinator] Phase 3/6: 生成报告大纲")

    outline = await pool.run(
        "writer",
        f"根据以下材料，为「{topic}」研究报告生成大纲。\n"
        "要求：只输出大纲结构和各章节要点，不要写正文。",
        context={"topic": topic, "research": merged},
    )
    memory.set("outline_draft", outline)

    # ========== Phase 4: 审核大纲（coordinator 审核，带反馈回路） ==========
    print("[Coordinator] Phase 4/6: 审核大纲")

    outline_review = await pool.run(
        "coordinator",
        "审核以下报告大纲：\n"
        "1. 结构是否完整覆盖主题\n"
        "2. 各章节是否有足够的数据支撑\n"
        "3. 逻辑顺序是否合理\n"
        "如果通过，输出 APPROVED。\n"
        "如果需要修改，输出 REVISION_NEEDED 并给出具体修改意见。",
        context={"outline": outline, "research": merged},
    )

    for i in range(MAX_REVISION_ROUNDS):
        if "APPROVED" in str(outline_review).upper():
            break
        print(f"[Coordinator] 大纲需修订（第 {i + 1}/{MAX_REVISION_ROUNDS} 轮）")
        outline = await pool.run(
            "writer",
            "根据以下审核意见修改报告大纲",
            context={
                "outline": outline,
                "feedback": outline_review,
                "research": merged,
            },
        )
        outline_review = await pool.run(
            "coordinator",
            "再次审核修改后的大纲，通过输出 APPROVED，否则输出 REVISION_NEEDED 及意见",
            context={"outline": outline, "research": merged},
        )

    memory.set("approved_outline", outline)
    print("[Coordinator] Phase 4 完成，大纲已确认")

    # ========== Phase 5: 撰写完整报告 ==========
    print("[Coordinator] Phase 5/6: 撰写完整报告")

    report = await pool.run(
        "writer",
        f"根据确认的大纲和所有研究材料，撰写「{topic}」完整研究报告。\n"
        "要求：每个观点必须有数据支撑，注明来源。",
        context={
            "topic": topic,
            "outline": outline,
            "research": merged,
        },
    )
    memory.set("report_draft", report)

    # ========== Phase 6: 审核报告（coordinator 审核，带反馈回路） ==========
    print("[Coordinator] Phase 6/6: 审核报告")

    report_review = await pool.run(
        "coordinator",
        "审核以下研究报告：\n"
        "1. 数据是否准确引用、来源是否标注\n"
        "2. 论证逻辑是否通顺\n"
        "3. 是否有未注明来源的断言\n"
        "4. 报告结构是否符合大纲\n"
        "如果通过，输出 APPROVED。\n"
        "如果需要修改，输出 REVISION_NEEDED 并给出具体修改意见。",
        context={"report": report, "outline": outline, "research": merged},
    )

    for i in range(MAX_REVISION_ROUNDS):
        if "APPROVED" in str(report_review).upper():
            break
        print(f"[Coordinator] 报告需修订（第 {i + 1}/{MAX_REVISION_ROUNDS} 轮）")
        report = await pool.run(
            "writer",
            "根据以下审核意见修改研究报告",
            context={
                "report": report,
                "feedback": report_review,
                "outline": outline,
                "research": merged,
            },
        )
        report_review = await pool.run(
            "coordinator",
            "再次审核修改后的报告，通过输出 APPROVED，否则输出 REVISION_NEEDED 及意见",
            context={"report": report, "outline": outline, "research": merged},
        )

    memory.set("final_report", report)
    print("[Coordinator] 研究流程完成！")
    return report


async def main():
    """主入口"""
    topic = input("请输入研究主题: ")
    result = await run_research(topic)
    print("\n" + "=" * 50)
    print("最终报告:")
    print("=" * 50)
    print(result)


if __name__ == "__main__":
    asyncio.run(main())
