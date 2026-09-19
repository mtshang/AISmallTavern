# AI Small Tavern · AI 小酒馆

[![Python 3.12](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)](#快速开始)
[![TUI: prompt_toolkit](https://img.shields.io/badge/TUI-prompt__toolkit-4B8BBE)](#操作方式)
[![Status: In Development](https://img.shields.io/badge/Status-In%20Development-orange)](#当前范围与限制)
[![License: PolyForm Noncommercial 1.0.0](https://img.shields.io/badge/License-PolyForm%20Noncommercial%201.0.0-red)](LICENSE)

一款以 AI 角色扮演与沉浸式对话为外壳的 Python AI 应用项目。

AI 小酒馆在终端中提供固定输入区和流式聊天界面，通过兼容 OpenAI Chat Completions 的接口连接大语言模型；同时内置本地 RAG 长期记忆——角色的世界观设定按标题分块、向量化并持久化，对话时由程序侧预检索注入背景，模型也可通过工具自主追加查询。项目围绕异步流式调用、多轮上下文、工具调用、向量检索和本地会话持久化持续迭代。

当前采用终端文本界面（TUI），按源码方式运行。聊天模型走云端接口；RAG 检索使用本地嵌入模型（约 630 MB，CPU 推理即可，无需 GPU），通过项目内置脚本下载。聊天模型服务的调用费用由所使用的服务商决定。

## 已实现功能

- **异步流式对话**：逐段显示模型回复，生成期间可以继续编辑下一条输入草稿；同一时间只处理一条回复。
- **多轮上下文**：组织 `system / user / assistant` 消息，续聊时将当前会话的历史消息一并传入模型。
- **RAG 长期记忆**：本地嵌入模型（granite-embedding-311m-multilingual-r2，512 维）+ FAISS 余弦检索。世界观 Markdown 按标题分块、向量化并持久化，源文件变更后自动检测哈希并重建索引；检索阈值经正负样本校准（有答案查询 top1 分布 0.884~0.920，无答案 0.784~0.830，取交界 0.85），无关问题零注入。
- **工具调用**：以 OpenAI Function Calling 方式注册工具（掷骰、世界观检索），由模型自主决策是否调用；支持流式分片参数合并、错误重试上限与失败回滚。
- **混合式检索注入**：每轮用户消息先做一次程序侧预检索，将有效世界观背景随问题注入（XML 标签包裹）；同时保留工具供模型跨章节追问。
- **Markdown 角色设定**：角色以目录为单位（`人设.md` + 可选世界观文档），新会话保存角色提示词快照；知识库目录始终跟随会话角色，避免跨角色检索错配。
- **本地会话存档**：以 JSON 保存消息、角色和 UTC+8 时间戳，重启后恢复配置指定的会话。
- **用户数据集中管理**：配置、会话和自定义角色集中存放在 `user_data/`，便于备份和跨版本迁移；模型凭证 `.env` 单独保留在项目根目录。
- **逐轮保存与原子写入**：取得有效的完整回复后记录本轮消息；文件写入采用同目录临时文件加 `os.replace()`，降低产生半截文件的风险。
- **终端交互**：固定底部输入框、状态提示、历史文本显示、键盘翻页和输出自动跟随。
- **启动预加载与客户端复用**：进入界面前预加载嵌入模型，避免首次对话等待；AsyncOpenAI 客户端全局复用，连接池与 TLS 会话跨请求保持。

## 快速开始

### 1. 准备环境

以下命令适用于 Windows PowerShell。当前项目环境为 **Python 3.12.10**，建议使用 Python 3.12；其他版本和操作系统尚未完成运行验证。

下载或克隆仓库后，在包含 `main.py` 的项目根目录打开终端：

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

这些命令直接使用项目虚拟环境的解释器，不需要运行 `Activate.ps1`。已有 `.venv` 时，跳过创建环境这一步即可。

直接依赖为 `openai`、`prompt-toolkit`、`python-dotenv`，以及 RAG 长期记忆所需的 `faiss-cpu`、`numpy`、`sentence-transformers` 和 `huggingface-hub`。`pip` 会自动安装它们需要的间接依赖（含 `torch`，磁盘占用约 1 GB）。

### 2. 配置模型服务

首次使用时，复制配置示例。下面的命令会保留已有的 `.env`：

```powershell
if (-not (Test-Path -LiteralPath ".env")) {
    Copy-Item -LiteralPath ".env.example" -Destination ".env"
}
```

用文本编辑器打开项目根目录的 `.env`，填写三个必需值：

```dotenv
LLM_API_KEY=
LLM_BASE_URL=
LLM_MODEL=
```

| 配置项 | 内容 |
| --- | --- |
| `LLM_API_KEY` | 模型服务商提供的 API Key |
| `LLM_BASE_URL` | 服务商提供的兼容接口基础地址；是否包含 `/v1` 以服务商文档为准 |
| `LLM_MODEL` | 该接口支持的模型 ID，使用服务商要求的准确名称 |

基础地址不要填写成完整的 `/chat/completions` 请求地址。当前调用方式要求服务支持 Chat Completions 和流式文本输出，不保证所有第三方接口都兼容。

程序在启动时读取配置，修改后需要重启。进程中已有的同名环境变量优先于 `.env`；如果文件修改未生效，也请检查环境变量。

`.env.example` 可以提交到 GitHub，填写了真实凭证的 `.env` 不应提交。

### 3. 下载向量模型

本项目使用 granite-embedding-311m-multilingual-r2 作为本地嵌入模型，
仓库不包含模型文件（约 630 MB）。

一键下载（推荐，含国内镜像自动切换）：
- 双击项目根目录的「下载向量化模型.bat」
- 或在项目根目录的终端里运行：
  .venv\Scripts\python.exe download_embedding_model.py

需要先完成「1. 准备环境」中的虚拟环境创建与依赖安装；
若用系统 Python 直接运行本脚本，会提示缺少依赖 huggingface_hub。

模型会下载到项目根目录的 granite-embedding-r2/。
注意：官方仓库还包含 onnx / openvino 等冗余格式，合计约 4 GB，
本脚本只取运行时所需的约 630 MB。

### 4. 启动

```powershell
.\.venv\Scripts\python.exe main.py
```

请在支持交互输入的终端运行，例如 PowerShell 或 VS Code 的集成终端。程序使用整个终端内容区域绘制界面。

启动时会先在终端加载本地嵌入模型（打印加载进度），完成后进入全屏界面。首次启动会使用默认角色。在首轮成功取得非空回复后，程序才会创建新的会话文件。无需提前创建 `user_data/config.json` 或会话 JSON，但仓库中的 `assets/default/` 默认文件必须保留。

## 操作方式

| 操作 | 效果 |
| --- | --- |
| Enter | 提交输入框中的消息 |
| 生成期间继续输入 | 编辑下一条草稿；此时再次按 Enter 不会发起第二个请求 |
| PageUp / PageDown | 向上／向下翻阅输出 |
| Ctrl+Home / Ctrl+End | 跳到输出顶部／底部 |
| Ctrl+D | 退出程序 |
| 输入 `/=exit` 后按 Enter | 退出程序；大小写不敏感，命令前后不要加空格 |

向上翻阅时会暂停输出自动跟随，回到底部或提交新消息后恢复。

生成过程中退出会取消当前任务。本轮未完成的用户消息和部分回复不会作为完整对话写入存档；此前成功保存的对话仍然保留。

## 角色与会话

目前通过文件配置选择角色和会话，尚未提供界面内的选择菜单。请先退出程序，再修改 `user_data/config.json`，避免运行中的内存配置覆盖你的手动修改。

### 使用自定义角色

角色以**目录**为单位，每个角色一个文件夹：

1. 在 `user_data/characters/` 下创建角色目录，例如 `user_data/characters/my_character/`。
2. 在目录内创建 `人设.md`（必需）：写入角色身份、性格、说话方式等设定，内容不能全为空白。
3. 可选：在目录内添加世界观文档，**文件名包含「世界观」且扩展名为 `.md`**（如 `世界观.md`、`世界观-地理.md`）。这些文档会被分块、向量化并建立检索索引；文件名不含「世界观」的文件不会入库，可用于存放未来剧情、创作者备注等不想让模型检索到的内容。
4. 在 `user_data/config.json` 中把 `current_character_id` 设为目录名，并清空当前会话 ID：

```json
{
  "session_id": "",
  "current_character_id": "my_character"
}
```

如果还没有 `user_data/config.json`，可以先正常启动并退出一次，或将 `assets/default/default_config.json` 复制为 `user_data/config.json` 后编辑。

程序优先在 `user_data/characters/` 中寻找同名目录，再检查 `assets/default/`，找不到或人设为空时使用内置默认角色。目录结构示例见 `user_data/characters/示例角色/`。

已有会话使用创建时保存的 `system` 消息快照。修改角色文件或 `current_character_id` 不会自动替换旧会话中的设定；要让新设定用于新一轮会话，请同时把 `session_id` 设为 `""`。**知识库始终跟随会话的角色**：恢复旧会话时，即使配置已切换到别的角色，世界观检索仍使用该会话创建时的角色目录。

首次对话后，角色目录内会生成 `metadata.json`、`rag.faiss`、`title_to_content.json` 三个索引缓存文件（已被 Git 忽略）；世界观文档变更后，程序在下次检索时自动检测并重建索引，无需手动操作。

### 新建与恢复会话

- **新建会话**：退出后将 `session_id` 改成 `""`，重新启动。旧会话文件会保留。
- **继续上次会话**：保留配置即可，程序会尝试恢复该文件。
- **恢复指定会话**：将 `session_id` 设置为 `user_data/sessions/` 中的完整文件名，包含 `.json` 扩展名。

`session_id` 保存文件名，不保存绝对路径。会话文件无法加载时，程序会回退到未选择会话的状态。

### 会话数据结构

下面是示意数据，角色文本、消息和时间仅用于说明格式：

```json
{
  "title": "与my_character的对话",
  "character_id": "my_character",
  "created_at": "2026-09-08T20:30:00+08:00",
  "character_prompt": "你是一位友善的旅行向导。",
  "messages": [
    {
      "role": "system",
      "content": "你是一位友善的旅行向导。",
      "created_at": "2026-09-08T20:30:00+08:00"
    },
    {
      "role": "user",
      "content": "你好。",
      "created_at": "2026-09-08T20:30:00+08:00"
    },
    {
      "role": "assistant",
      "content": "你好，今天想去哪里？",
      "created_at": "2026-09-08T20:30:03+08:00"
    }
  ]
}
```

请求模型时只提取消息的 `role` 和 `content`，不会把 `created_at` 等本地元数据当作 API 消息字段发送。

“本地保存”指存档位置在本机。聊天时，角色设定、当前会话历史、预检索到的世界观背景和本轮消息会发送给 `LLM_BASE_URL` 指定的模型服务；世界观文档本身与向量索引不会离开本机。存档和 `.env` 均为明文文件。

## 更新版本与数据迁移

### 使用新目录结构的版本之间升级

**更新到新版本时，将旧版本的整个 `user_data` 文件夹复制到新版本项目根目录即可迁移用户配置、自定义角色和会话存档。** 复制后应保持 `新版本根目录/user_data/config.json` 这样的层级，不要多嵌套一层 `user_data/user_data/`。

1. 退出正在运行的程序，先备份旧版本的 `user_data/` 和根目录的 `.env`。
2. 将新版本下载或解压到一个新目录，保留旧版本作为备份。
3. 把旧版本的整个 `user_data/` 复制到新版本根目录，与发行包中的空用户数据目录合并；若新目录仅有默认生成的配置，可用旧配置替换它。
4. **单独复制旧版本根目录的 `.env` 到新版本根目录。** 它不在 `user_data/` 中，包含模型服务地址、模型名称和 API Key，请妥善保管。
5. 按新版本的启动说明运行，确认当前会话和自定义角色能够正常加载后，再自行处理旧版本备份。

如果新版本目录已经产生了需要保留的用户数据，请先备份两边的数据，再处理同名配置或存档，不要直接批量覆盖。

`assets/default/` 是随版本更新的默认资源，应保留新版本提供的内容，无需用旧版本的默认资源覆盖。虚拟环境 `.venv/` 不属于用户数据，也无需随 `user_data/` 一起复制；按源码方式运行时，依照新版本的 `requirements.txt` 准备依赖即可。

以上直接复制方式适用于用户数据格式兼容的版本；若未来版本调整存档结构并要求额外转换，请以对应发行说明为准。

### 从旧版目录结构迁移

如果你下载的是调整目录前的 v0.1，尚没有 `user_data/`，首次迁移时请先退出程序并备份，再按下表复制：

| 旧版本位置 | 新版本位置 |
| --- | --- |
| `data/config.json` | `user_data/config.json` |
| `data/sessions/` 中的会话文件 | `user_data/sessions/` |
| `user_characters/` 中的角色文件 | `user_data/characters/` |
| 根目录的 `.env` | 新版本根目录的 `.env` |

旧位置不存在时跳过对应项；复制时保留原文件名。无需迁移旧版 `data/default/`，使用新发行包中的 `assets/default/` 即可。完成这一次目录调整后，后续升级就可以按上一节直接复制整个 `user_data/`。

## 项目结构

```text
aismalltavern/
├── main.py                       # 入口：配置加载、角色解析、模型预加载、启动界面
├── ui.py                         # 终端界面：布局、按键、流式展示、预检索注入、工具调用循环
├── model_connect.py              # AsyncOpenAI 客户端管理与流式模型请求
├── app_context.py                # 共享上下文（dataclass）与角色目录解析
├── rag.py                        # RAG：分块、向量化、FAISS 索引、缓存与检索
├── assets_tools_calls.py         # 工具调用分发：按名称路由到具体实现
├── file_operate.py               # JSON 和文本文件的原子写入
├── download_embedding_model.py   # 嵌入模型一键下载（多镜像回退、体积校验）
├── 下载向量化模型.bat             # 下载脚本的双击入口
├── hooks/
│   └── hook-torch.py             # PyInstaller hook 覆盖：规避 torch 子模块枚举崩溃
├── requirements.txt
├── .env.example                  # 配置示例
├── .env模板.txt
├── .env                          # 本地模型配置，请勿提交或随发行包分发
├── .gitignore
├── README.md
├── LICENSE
├── NOTICE
├── assets/
│   ├── assets_tools.json         # 工具定义（名称、描述、参数 schema）
│   ├── tools/
│   │   └── roll_dice.py          # 掷骰工具实现
│   └── default/                  # 随版本提供的默认资源
│       ├── default_config.json
│       ├── default_session.json
│       └── 默认猫娘default_cat/   # 默认角色
│           ├── 人设.md
│           └── 世界观.md          # 首次检索后此处会生成索引缓存（已被忽略）
└── user_data/                    # 用户数据；升级时迁移整个文件夹
    ├── config.json               # 运行时生成的用户配置，请勿提交
    ├── characters/               # 本地自定义角色，请勿提交其内容
    │   └── 示例角色/             # 角色目录结构示例
    └── sessions/                 # 本地会话存档，请勿提交其内容
        └── .gitkeep

# granite-embedding-r2/           # 嵌入模型目录（约 630 MB，已被忽略，脚本下载）
```

`assets/default/` 保存程序随附的默认资源，`user_data/` 保存用户自己的数据。除根目录的 `.env` 外，用户配置、角色与会话均集中在 `user_data/` 中；发行包只保留空的用户角色和会话目录，不应包含真实用户数据或凭证。

| 模块 | 职责 |
| --- | --- |
| `main.py` | 加载配置、默认数据与角色，创建上下文，预加载嵌入模型并启动界面 |
| `ui.py` | 布局、按键、状态管理、流式展示、预检索注入与工具调用循环 |
| `model_connect.py` | 校验环境变量，以异步生成器提供模型增量回复 |
| `app_context.py` | 使用 `dataclass` 定义共享上下文，提供角色目录解析与状态更新 |
| `rag.py` | 世界观文档分块、向量化、FAISS 索引与缓存、相似度检索 |
| `assets_tools_calls.py` | 按工具名把模型请求路由到本地实现 |
| `file_operate.py` | JSON 和文本文件的原子写入 |

一次对话的处理顺序是：读取输入 → 预检索世界观背景 → 整理历史消息 → 异步请求模型 → 显示并收集回复（期间模型可能发起工具调用并循环）→ 提交完整消息 → 保存会话与配置。

文件写入采用同目录临时文件、`flush()`、`fsync()` 和 `os.replace()`，降低覆盖写入过程中产生半截文件的风险。会话与配置是两个独立文件，保存顺序为先会话、后配置，并非跨文件事务。

## 当前范围与限制

- 输入区为单行，输出为纯文本，暂不渲染 Markdown 富文本或展示模型思考内容。
- 使用键盘操作，未启用鼠标滚动；翻页按逻辑行移动，超长无换行段落可能无法细致浏览。
- 每轮发送当前会话的全部历史，尚未实现 token 预算、上下文裁剪或摘要。
- JSON 校验覆盖基础结构，尚未完整校验所有消息字段；暂不支持多个进程同时修改同一份存档。
- 分块器按字符位置硬切，尚未实现段落/句子级降级，超长小节可能被切断。
- 检索阈值（`SCORE_GAP` / `MIN_SCORE` / `MAX_CHUNKS`）为硬编码常量，更换语料或嵌入模型后需重新校准。
- 每轮消息前执行一次预检索，带来约 150~270 毫秒延迟；RAG 生成物与源文档同目录存放。
- 是否调用检索工具由模型自主决策，程序侧通过预检索兜底，尚未做工具调用率的系统性评测。

## 许可

本项目原创代码采用 [PolyForm Noncommercial License 1.0.0](LICENSE)。在该许可证允许的非商业用途范围内，可以免费使用、修改和分发；商业用途需要另行取得授权。许可证还明确允许特定教育、公益、公共研究及政府等组织的用途，具体边界以 [许可证原文](https://polyformproject.org/licenses/noncommercial/1.0.0) 为准。

免费获得软件授权不代表模型 API 免费，相关费用和使用条款由模型服务商决定。

本项目公开源码供学习和交流。由于存在商业用途限制，它不属于 [OSI 定义](https://opensource.org/osd) 下的开源软件。

第三方依赖及可选模型资源遵循各自的许可证，不因本项目的许可方式而改变。版权及第三方资源说明见 [NOTICE](NOTICE)。

作者：[时殇](https://github.com/mtshang)。
