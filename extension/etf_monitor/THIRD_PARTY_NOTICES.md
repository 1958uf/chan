# 第三方来源与许可

## 使用的依赖

- AKShare： https://github.com/akfamily/akshare ，作为独立环境的固定版本Python依赖，MIT许可。
- FastAPI、Pydantic、uvicorn、httpx、pandas、openpyxl、requests、APScheduler，以及前端React、Vite、ECharts等：许可随各自安装包保留，版本以依赖文件及锁文件为准。

## 功能参考

- national-team-position： https://github.com/Xiaoyuan-Liu/national-team-position ，MIT。参考宽基份额与指数走势并列展示的功能。本系统重新实现数据契约、分类、日期和统计，不把原系统沪市范围当作全市场。
- Resonance： https://github.com/OrangesHuang/Resonance ，截至调研未发现明确许可证。本系统只参考公开说明中的功能概念，**不复制源码、测试、前端资产、启动脚本和技能说明**，独立实现。

## AKShare MIT 许可原文

MIT License

Copyright (c) 2019-2026 Albert King

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

## 数据边界

数据来自公开市场接口，其使用条件、数据授权和限流约束独立于代码许可。本系统不绕过认证、不获取个人账户信息、不自动交易，不将启发式评分宣传为国家队身份概率。
