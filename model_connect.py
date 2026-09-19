from __future__ import annotations
from typing import TYPE_CHECKING


import asyncio
import os
from pathlib import Path
from typing import AsyncGenerator

from openai import AsyncOpenAI


from app_context import AppContext



def require_env(name: str) -> str:
    """
    【读取必需的环境变量。

    如果环境变量不存在或未设置，抛出RuntimeError。】
    """
    value = os.getenv(name)

    if not value or not value.strip():
        raise RuntimeError(f"缺少环境变量【{name}】，请在 .env 中写入真实的配置值！")

    placeholders = {"你的api key", "你的base url", "你的model", "your_api_key"}
    if value in placeholders:
        raise RuntimeError(
            f"环境变量【{name}】仍为模板占位符（'{value}'），请在 .env 中替换为真实的配置值！"
        )

    return value


async def chat_with_model(appcontext:AppContext,messages:list[dict],tools:list[dict]=[]) -> AsyncGenerator[tuple[str | None, list | None], None]:
    """
    异步请求模型，以流式方式接收回复。

    返回值：
        yield返回增量文本
    """

    model = appcontext.llm_model
    client = appcontext.llm_client
    if client is None:
        #/ 凭证缺失时客户端未创建；走到这里说明用户在配置错误的状态下发了消息。
        raise RuntimeError(
            "模型客户端不可用：请在 .env 中填写 LLM_API_KEY / LLM_BASE_URL / LLM_MODEL 后重启。"
        )
    request_messages=messages

    #/ 不再用 async with：客户端的生命周期由 tavern_loop 统一管理。
    #/ 异步客户端的 create() 必须使用 await。await 完成后，response 才是可以 async for 的异步流。
    response = await client.chat.completions.create(
        model=model,
        messages=request_messages,
        tools=tools,
        stream=True,
        #/ reasoning_effort 是 DeepSeek 扩展字段，并不是 OpenAI SDK 标准类型中一定存在的属性。
        #/reasoning_effort="high",

        #/ DeepSeek 的扩展参数。
        # extra_body={
        #     "thinking": {
        #         "type": "enabled",
        #     }
        # },
    )
    

    async with response:
        #/ 异步遍历服务器不断返回的数据块。
        async for chunk in response:
            #/ 某些结束数据块可能没有 choices。
            if not chunk.choices:
                continue

            delta = chunk.choices[0].delta

            #/ reasoning_content 是 DeepSeek 扩展字段，并不是 OpenAI SDK 标准类型中一定存在的属性。
            # reasoning_piece = getattr(
            #     delta,
            #     "reasoning_content",
            #     None,
            # )

            # / 当前数据块只要包含正文或工具调用增量，就交给调用者。
            if delta.content or delta.tool_calls:
                yield delta.content, delta.tool_calls






async def test_model_response(
    appcontext: AppContext,
    user_text: str,
    messages: list[dict],
    tools: list[dict],
    *,
    stream: bool = False,
) -> dict | list[dict]:
    """
    单独请求一次模型，打印并返回 SDK 收到的完整响应数据，便于观察工具调用。

    参数：
        appcontext：提供 API Key、接口地址和模型名称。
        user_text：本次测试的用户输入；函数会把它追加到请求消息列表。
        messages：已有上下文，不要重复放入本轮 user_text。
        tools：提供给模型的工具定义列表；这里只描述工具，不执行工具。
        stream：只能用关键字传入。False 接收完整响应，True 接收流式数据块。

    返回值：
        stream=False：完整响应转换得到的字典。
        stream=True：各个流式数据块转换得到的字典列表。
                     这个列表没有合并成一条完整消息，工具参数可能分散在多个块中。

    注意：
        本函数不是异步生成器，没有 yield，调用时需要 await。
        不修改传入的消息列表，不保存会话，不执行工具，也不进行第二轮模型请求。
        接口报错时异常会继续抛出，方便测试时查看具体原因。
    """
    #/ 新增函数需要的导入放在函数内部，保持原文件顶部的导入部分不变。
    import json
    from typing import cast

    from openai.types.chat import (
        ChatCompletionMessageParam,
        ChatCompletionToolParam,
    )

    api_key = appcontext.llm_api_key
    base_url = appcontext.llm_base_url
    model = appcontext.llm_model

    #/ 配置不完整时直接报错，不让测试继续发起网络请求。
    if not isinstance(api_key, str) or not api_key.strip():
        raise ValueError("测试失败：LLM_API_KEY 未配置。")
    if not isinstance(base_url, str) or not base_url.strip():
        raise ValueError("测试失败：LLM_BASE_URL 未配置。")
    if not isinstance(model, str) or not model.strip():
        raise ValueError("测试失败：LLM_MODEL 未配置。")

    #/ 创建新的列表，避免把本轮用户消息追加到调用者的原列表中。
    #/ cast(目标类型, 对象) 只告诉类型检查器如何看待对象，不转换或校验运行时数据。
    request_messages = cast(
        list[ChatCompletionMessageParam],
        [*messages, {"role": "user", "content": user_text}],
    )
    request_tools = cast(list[ChatCompletionToolParam], tools)

    #/ max_retries=0：测试请求失败后不由 SDK 自动重试。
    #/ timeout=60.0：设置 SDK 网络请求超时时间，单位为秒，并非整个函数的总时限。
    async with AsyncOpenAI(
        api_key=api_key,
        base_url=base_url,
        max_retries=0,
        timeout=60.0,
    ) as client:
        if not stream:
            response = await client.chat.completions.create(
                model=model,
                messages=request_messages,
                tools=request_tools,
                #/ auto：模型可以直接回复，也可以提出工具调用；不保证一定调用。
                tool_choice="auto",
                stream=False,
            )

            #/ response 是 SDK 响应对象，不是普通字典。
            #/ model_dump(mode="json") 将其转换为可以 JSON 序列化的完整字典。
            #/ 不只提取 content，也保留 tool_calls、finish_reason、usage 等字段。
            response_data = response.model_dump(mode="json")

            #/ json.dumps 返回 JSON 文本；ensure_ascii=False 显示中文，indent=2 格式化缩进。
            #/ 打印不会改变返回值：函数返回的仍是字典，而不是 JSON 字符串。
            print(json.dumps(response_data, ensure_ascii=False, indent=2))
            return response_data

        response_stream = await client.chat.completions.create(
            model=model,
            messages=request_messages,
            tools=request_tools,
            tool_choice="auto",
            stream=True,
        )

        chunks: list[dict] = []
        async with response_stream:
            async for chunk in response_stream:
                #/ 不跳过 choices 为空的数据块；如果服务端返回用量等信息，也会保留。
                chunk_data = chunk.model_dump(mode="json")
                chunks.append(chunk_data)

                print(f"\n[流式数据块 {len(chunks)}]")
                print(json.dumps(chunk_data, ensure_ascii=False, indent=2))

        return chunks


if __name__ == "__main__":
    from dotenv import load_dotenv

    #/ 只在直接运行本文件时加载测试配置，导入模块不会执行下面的测试。
    BASE_DIR = Path(__file__).resolve().parent
    load_dotenv(dotenv_path=BASE_DIR / ".env")

    try:
        LLM_API_KEY = require_env("LLM_API_KEY")
        LLM_BASE_URL = require_env("LLM_BASE_URL")
        LLM_MODEL = require_env("LLM_MODEL")
    except RuntimeError as error:
        print(f"测试配置出错：{error}")
        #/ 结束测试进程；退出码 1 表示失败，不再用空配置请求接口。
        raise SystemExit(1) from None

    appcontext = AppContext(
        base_dir=BASE_DIR,
        llm_api_key=LLM_API_KEY,
        llm_base_url=LLM_BASE_URL,
        llm_model=LLM_MODEL,
        config={},
        config_env_error=None,
        session=None,
        session_path=None,
        #/ 本测试不读取人设文件，路径只用于满足 AppContext 的字段要求。
        character_path=BASE_DIR / "assets" / "default" / "默认猫娘default_cat"/ "人设.md",
        character_prompt="",
    )

    api_messages = [
        {
            "role": "system",
            "content": "你是一个助理。",
        },
    ]
    #/ 明确面数和次数，避免模型因为参数不清楚而先追问用户。
    user_text = "请调用 roll_dice，帮我投掷一次六面骰子。"

    tools = [
        {
            "type": "function",
            "function": {
                "name": "roll_dice",
                "description": "投掷指定面数的骰子，重复指定次数。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "sides": {
                            "type": "integer",
                            "description": "骰子的面数（如 6 代表标准 6 面骰，20 代表 20 面骰）。",
                        },
                        "count": {
                            "type": "integer",
                            "description": "投掷骰子的次数（如投掷 1 次）。",
                        },
                    },
                    #/ 必填参数名称必须与 properties 中定义的名称一致。
                    "required": ["sides", "count"],
                    "additionalProperties": False,
                },
                "strict": True,
            },
        },
    ]

    #/ 默认接收完整的非流式响应字典；改成 True 可以逐块查看流式响应。
    #/ asyncio.run 驱动测试协程，返回值交给 response_data，函数内部已经打印它。
    response_data = asyncio.run(
        test_model_response(
            appcontext=appcontext,
            user_text=user_text,
            messages=api_messages,
            tools=tools,
            stream=False,
        )
    )
