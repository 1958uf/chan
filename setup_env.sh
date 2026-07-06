#!/bin/bash
# ============================================================
# Chan 缠论框架 - 一键环境部署脚本
# 用法：bash setup_env.sh
# ============================================================

set -e

ENV_NAME="chan_py311"
PYTHON_VERSION="3.11"

echo "=== Chan 缠论框架环境部署 ==="
echo ""

# 检查 conda 是否可用
if ! command -v conda &> /dev/null; then
    echo "[错误] 未找到 conda，请先安装 Miniconda 或 Anaconda"
    echo "下载地址：https://docs.conda.io/en/latest/miniconda.html"
    exit 1
fi

# 检查环境是否已存在
if conda env list | grep -q "^${ENV_NAME} "; then
    echo "[提示] conda 环境 '${ENV_NAME}' 已存在，跳过创建"
else
    echo "[1/3] 创建 Python ${PYTHON_VERSION} conda 环境：${ENV_NAME}"
    conda create -n "${ENV_NAME}" python="${PYTHON_VERSION}" -y
    echo "      环境创建完成"
fi

echo ""
echo "[2/3] 安装核心依赖包..."
conda run -n "${ENV_NAME}" pip install -r requirements.txt
echo "      核心依赖安装完成"

echo ""
echo "[3/3] 验证安装..."
conda run -n "${ENV_NAME}" python -c "
import baostock, matplotlib, pandas, IPython, typing_extensions
print('  baostock        :', baostock.__version__)
print('  matplotlib      :', matplotlib.__version__)
print('  pandas          :', pandas.__version__)
print('  ipython         :', IPython.__version__)
print('  typing_extensions:', typing_extensions.__version__)
print('  所有核心依赖验证通过！')
"

echo ""
echo "=== 部署完成 ==="
echo ""
echo "激活环境："
echo "  conda activate ${ENV_NAME}"
echo ""
echo "运行项目："
echo "  python main.py"
echo ""
echo "如需安装可选依赖（GUI / 数字货币 / 机器学习）："
echo "  conda activate ${ENV_NAME}"
echo "  pip install -r requirements-optional.txt"
