# AI Small Tavern · AI 小酒馆

[![Python 3.12](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)](#快速开始)
[![TUI: prompt_toolkit](https://img.shields.io/badge/TUI-prompt__toolkit-4B8BBE)](#操作方式)
[![Status: In Development](https://img.shields.io/badge/Status-In%20Development-orange)](#当前范围与限制)
[![License: PolyForm Noncommercial 1.0.0](https://img.shields.io/badge/License-PolyForm%20Noncommercial%201.0.0-red)](LICENSE)

一款以 AI 角色扮演与沉浸式对话为外壳的 Python AI 应用项目。

AI 小酒馆在终端中提供固定输入区和流式聊天界面，通过兼容 OpenAI Chat Completions 的接口连接大语言模型。项目围绕异步调用、多轮上下文、角色设定和本地会话持久化持续迭代。

当前采用终端文本界面（TUI），按源码方式运行。无需下载本地模型，也无需 GPU；模型服务的调用费用由所使用的服务商决定。

## 已实现功能

- **异步流式对话**：逐段显示模型回复，生成期间可以继续编辑下一条输入草稿；同一时间只处理一条回复。
- **多轮上下文**：组织 `system / user / assistant` 消息，续聊时将当前会话的历史消息一并传入模型。
- **Markdown 角色设定**：从 UTF-8 `.md` 文件读取人设，新会话保存角色提示词快照。
- **本地会话存档**：以 JSON 保存消息、角色和 UTC+8 时间戳，重启后恢复配置指定的会话。
- **逐轮保存**：取得有效的完整回复后记录本轮消息，依次保存会话和配置；正常退出时再次保存。
- **终端交互**：固定底部输入框、状态提示、历史文本显示、键盘翻页和输出自动跟随。
- **配置与异常处理**：读取 `.env`；对缺失配置、部分无效 JSON 结构和缺失角色提供提示或默认值回退。

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

直接依赖只有 `openai`、`prompt-toolkit` 和 `python-dotenv`。`pip` 会自动安装它们需要的间接依赖；当前聊天功能不需要 `torch`、`transformers` 或 `sentence-transformers`。

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

### 3. 启动

```powershell
.\.venv\Scripts\python.exe main.py
```

请在支持交互输入的终端运行，例如 PowerShell 或 VS Code 的集成终端。程序使用整个终端内容区域绘制界面。

首次启动会使用默认角色。在首轮成功取得非空回复后，程序才会创建新的会话文件。无需提前创建 `data/config.json` 或会话 JSON，但仓库中的 `data/default/` 默认文件必须保留。

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

目前通过文件配置选择角色和会话，尚未提供界面内的选择菜单。请先退出程序，再修改 `data/config.json`，避免运行中的内存配置覆盖你的手动修改。

### 使用自定义角色

1. 在 `user_characters/` 下创建 UTF-8 Markdown 文件，例如 `my_character.md`。
2. 写入角色身份、性格、说话方式等设定，文件内容不能全为空白。
3. 在 `data/config.json` 中设置角色文件名，并清空当前会话 ID：

```json
{
  "session_id": "",
  "current_character_id": "my_character.md"
}
```

如果还没有 `data/config.json`，可以先正常启动并退出一次，或复制 `data/default/default_config.json` 后编辑。

程序优先在 `user_characters/` 中寻找同名文件，再检查 `data/default/`，找不到或内容为空时使用内置默认角色。

已有会话使用创建时保存的 `system` 消息。修改角色文件或 `current_character_id` 不会自动替换旧会话中的设定；要让新设定用于新一轮会话，请同时把 `session_id` 设为 `""`。

### 新建与恢复会话

- **新建会话**：退出后将 `session_id` 改成 `""`，重新启动。旧会话文件会保留。
- **继续上次会话**：保留配置即可，程序会尝试恢复该文件。
- **恢复指定会话**：将 `session_id` 设置为 `data/sessions/` 中的完整文件名，包含 `.json` 扩展名。

`session_id` 保存文件名，不保存绝对路径。会话文件无法加载时，程序会回退到未选择会话的状态。

### 会话数据结构

下面是示意数据，角色文本、消息和时间仅用于说明格式：

```json
{
  "title": "与my_character的对话",
  "character_id": "my_character.md",
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

“本地保存”指存档位置在本机。聊天时，角色设定、当前会话历史和本轮消息仍会发送给 `LLM_BASE_URL` 指定的模型服务。存档和 `.env` 均为明文文件。

## 项目结构

```text
aismalltavern/
├── main.py
├── ui.py
├── model_connect.py
├── app_context.py
├── file_operate.py
├── requirements.txt
├── .env.example
├── .gitignore
├── README.md
├── LICENSE
├── NOTICE
├── data/
│   ├── default/
│   │   ├── default_config.json
│   │   ├── default_session.json
│   │   └── 默认猫娘default_cat.md
│   ├── config.json               # 运行时生成，不提交
│   └── sessions/                 # 本地会话，不提交其内容
│       └── .gitkeep
└── user_characters/              # 本地自定义角色，不提交其内容
    └── .gitkeep
```

| 模块 | 职责 |
| --- | --- |
| `main.py` | 加载配置、默认数据与角色，创建上下文，启动界面并处理退出保存 |
| `ui.py` | 布局、按键、状态管理、流式展示和每轮会话更新 |
| `model_connect.py` | 校验环境变量，以异步生成器提供模型增量回复 |
| `app_context.py` | 使用 `dataclass` 定义共享上下文，提供状态更新与时间格式化方法 |
| `file_operate.py` | JSON 和文本文件的原子写入 |

一次对话的处理顺序是：读取输入 → 整理历史消息 → 异步请求模型 → 显示并收集回复 → 提交完整消息 → 保存会话与配置。

文件写入采用同目录临时文件、`flush()`、`fsync()` 和 `os.replace()`，降低覆盖写入过程中产生半截文件的风险。会话与配置是两个独立文件，保存顺序为先会话、后配置，并非跨文件事务。

## 当前范围与限制

- 输入区为单行，输出为纯文本，暂不渲染 Markdown 富文本或展示模型思考内容。
- 使用键盘操作，未启用鼠标滚动；翻页按逻辑行移动，超长无换行段落可能无法细致浏览。
- 每轮发送当前会话的全部历史，尚未实现 token 预算、上下文裁剪或摘要。
- JSON 校验覆盖基础结构，尚未完整校验所有消息字段；暂不支持多个进程同时修改同一份存档。
- 当前未接入 RAG、向量检索、本地嵌入模型、工具调用或 Web 服务。
- 若本地保留 `granite-embedding-r2/`，它属于未接入的实验资源，当前程序不加载它，Git 忽略规则也已排除该目录。

## 许可

本项目原创代码采用 [PolyForm Noncommercial License 1.0.0](LICENSE)。在该许可证允许的非商业用途范围内，可以免费使用、修改和分发；商业用途需要另行取得授权。许可证还明确允许特定教育、公益、公共研究及政府等组织的用途，具体边界以 [许可证原文](https://polyformproject.org/licenses/noncommercial/1.0.0) 为准。

免费获得软件授权不代表模型 API 免费，相关费用和使用条款由模型服务商决定。

本项目公开源码供学习和交流。由于存在商业用途限制，它不属于 [OSI 定义](https://opensource.org/osd) 下的开源软件。

第三方依赖及可选模型资源遵循各自的许可证，不因本项目的许可方式而改变。版权及第三方资源说明见 [NOTICE](NOTICE)。

作者：[时殇](https://github.com/mtshang)。
