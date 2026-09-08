"""
Chan 项目 - 监控侧模块

功能说明：
    - 提供命令行 K 线监控脚本，实时盯指数/个股与指定均线的接近程度
    - 与缠论主程序解耦：不依赖 chan.db，不修改既有代码
    - 数据来源为 akshare（零登录、支持指数与个股、盘中可用）

模块组成：
    - data_source.py : akshare 数据源封装（周线序列 + 实时现价）
    - indicators.py  : SMA 等指标计算与"接近均线"判定
    - alerts.py      : 终端彩色输出与蜂鸣提示
    - run.py         : CLI 入口，支持盘后(eod)/盘中(live)两种模式
"""
