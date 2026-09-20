# eval/ 测评套件

本目录存放 AI 小酒馆的离线测评脚本与报告。所有脚本**只通过导入复用项目模块**
（`rag` / `ui` / `model_connect` / `assets_tools_calls` / `app_context`），
读取角色目录中与生产完全相同的索引缓存，不修改任何程序代码文件。

## 目录结构

```text
eval/
├── README.md                    # 本文件
├── 检索质量测评报告.md            # 检索类报告（表格总结 + 逐条明细）
├── 工具调用测评报告.md            # 工具类报告（契约 + 模拟循环 + 真实调用）
├── 端到端问答测评报告.md          # A/B 对比报告
├── retrieval/                   # 检索质量类（零成本）
│   ├── common.py                #   路径、知识库加载、评分检索（复刻生产检索内部流程）
│   ├── dataset.py               #   14 正 + 12 普通负 + 4 边界负样本（含预期命中标注）
│   ├── eval_retrieval.py        #   分数分布、命中率、阈值扫描、SCORE_GAP 扫描
│   ├── eval_latency.py          #   冷加载、热检索全程、编码/检索分解计时
│   ├── make_report.py           #   从 JSON 组装中文报告
│   ├── run_retrieval.py         #   一键入口（延迟必须最先跑，冷加载才准）
│   └── results/                 #   JSON 数据 + 原始明细
├── agent/                       # 工具调用类
│   ├── agent_common.py          #   路径、.env 加载、客户端构造（不打印凭证）
│   ├── agent_dataset.py         #   40 条工具意图样本（13 检索 + 7 掷骰 + 20 不该调）
│   ├── eval_tool_path.py        #   工具分发层契约（零成本）
│   ├── eval_agent_mock.py       #   步骤 A：模拟（Mock）工具循环（零成本）
│   ├── eval_agent_real.py       #   步骤 B：真实工具决策（花钱，单独运行）
│   ├── make_report.py           #   报告生成
│   ├── run_agent.py             #   一键入口（零成本部分）
│   └── results/
└── e2e/                         # 端到端类
    ├── e2e_dataset.py           #   16 道封闭式硬事实题（关键词自动判分）
    ├── eval_e2e_ab.py           #   A/B：无 RAG vs 有 RAG（花钱，单独运行）
    ├── make_report.py           #   报告生成
    ├── run_e2e.py               #   一键入口（含真实调用）
    └── results/
```

## 运行方式

在项目根目录执行（需要先完成依赖安装与模型下载）：

```powershell
# 检索质量（零成本，约 1 分钟，含模型加载）
.\.venv\Scripts\python.exe eval\retrieval\run_retrieval.py

# 工具调用 · 零成本部分（契约 + 模拟循环）
.\.venv\Scripts\python.exe eval\agent\run_agent.py

# 工具调用 · 真实调用部分（40 条 × 3 次采样，产生 API 费用）
.\.venv\Scripts\python.exe eval\agent\eval_agent_real.py --smoke   # 先冒烟 5 条
.\.venv\Scripts\python.exe eval\agent\eval_agent_real.py           # 再全量
.\.venv\Scripts\python.exe eval\agent\run_agent.py                 # 跑完合并进报告

# 端到端 A/B（16 题 × 2 组 × 2 次，产生 API 费用）
.\.venv\Scripts\python.exe eval\e2e\run_e2e.py
```

报告由各 `make_report.py` 从 `results/` 的 JSON 生成，可在不重跑测评的情况下
单独重新生成（例如换一种排版）。

## 三份报告分别证明什么

| 报告 | 证明的问题 | 方法要点 |
| --- | --- | --- |
| 检索质量 | 检索找得到正确章节，阈值 0.85 / SCORE_GAP 0.03 有数据依据 | 与生产同一份索引缓存；正负样本分数分布 + 参数扫描 |
| 工具调用 | 程序侧循环逻辑正确 + 模型侧决策质量高 | 步骤 A 用 ast 抽取 ui.py 真实源码在受控命名空间执行（零成本测生产代码）；步骤 B 真实采样 3 次看稳定性 |
| 端到端 | 注入的背景真的让模型答对了原本答不出的题 | 封闭式硬事实题 + 关键词自动判分；A/B 单变量对照 |

## 维护约定

- 新增世界观章节后，在 `retrieval/dataset.py` 补充正样本与预期命中标注；
- 更换嵌入模型、语料或聊天模型后，重跑对应测评并重新校准（`rag.py` 的
  `MIN_SCORE` 绑定「语料 + 嵌入模型」组合）；
- 真实调用类测评读取 `.env` 配置（编程式读取，不打印凭证内容）；
- 本目录不依赖任何测试框架，纯标准库 + 项目依赖即可运行。
