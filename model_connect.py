from __future__ import annotations
from typing import TYPE_CHECKING

import asyncio
import os
from pathlib import Path
from typing import AsyncGenerator

from openai import AsyncOpenAI

from app_context import AppContext


def require_env(name: str) -> str:
    value = os.getenv(name)

    if not value or not value.strip():
        raise RuntimeError(f"缺少环境变量【{name}】，请在 .env 中写入真实的配置值！")

    placeholders = {"你的api key", "你的base url", "你的model", "your_api_key"}
    if value in placeholders:
        raise RuntimeError(
            f"环境变量【{name}】仍为模板占位符（'{value}'），请在 .env 中替换为真实的配置值！"
        )

    return value


async def chat_with_model(appcontext: AppContext, user_text: str, messages: list[dict]) -> AsyncGenerator[str, None]:
    api_key = appcontext.llm_api_key
    base_url = appcontext.llm_base_url
    model = appcontext.llm_model

    async with AsyncOpenAI(
        api_key=api_key,
        base_url=base_url,
    ) as client:
        request_messages: list = [*messages, {"role": "user", "content": user_text}]
        response = await client.chat.completions.create(
            model=model,
            messages=request_messages,
            stream=True,
        )

        async with response:
            async for chunk in response:
                if not chunk.choices:
                    continue

                delta = chunk.choices[0].delta

                if delta.content:
                    yield delta.content


if __name__ == "__main__":
    import random
    hex_ran_num = hex(random.randint(0, 268436455))
    print(hex_ran_num)