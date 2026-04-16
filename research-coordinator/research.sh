#!/bin/bash
# research - 启动多智能体研究流水线
#
# 用法:
#   research "中国新能源汽车行业"
#   research "中国低空经济行业" --skip-search
#
# 流程: searcher并行搜索 → coordinator去重合并 → writer出大纲 → coordinator审核
#       → writer写报告 → coordinator审核 → 输出到 output/

set -euo pipefail

SCRIPT_DIR="/home/admin/.openclaw/workspace/research-coordinator"

if [ $# -lt 1 ]; then
    echo "用法: research <研究主题> [--skip-search]"
    echo ""
    echo "示例:"
    echo '  research "中国新能源汽车行业"'
    echo '  research "中国低空经济行业" --skip-search'
    echo ""
    echo "产出目录: ${SCRIPT_DIR}/output/"
    exit 1
fi

echo "🔬 启动研究流水线..."
echo "   主题: $1"
echo "   预计耗时: 10-15 分钟"
echo ""

cd "$SCRIPT_DIR"
python3 coordinator.py "$@"
