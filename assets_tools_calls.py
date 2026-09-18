from rag import search_worldview
from assets.tools.roll_dice import roll_dice
from pathlib import Path
from app_context import AppContext

def tool_calls(appcontext,name:str,**args):
    """根据工具名，调用对应的本地函数。"""
    if name =="roll_dice":
        return roll_dice(**args)
    if name =="search_worldview":
        if appcontext.session_character_dir is None:
            return "知识库目录未找到，无法检索世界观设定。"
        rag_character_dir:Path=appcontext.session_character_dir
        model_dir:Path=appcontext.embedding_model_dir
        result = search_worldview(model_dir, rag_character_dir, **args)
        #/ 接口可能不接受空的 tool 消息；
        #/ 同时这句提示也让模型知道"是没查到"，而不是"工具没返回"。
        if not result:
            return "未在知识库中找到与该问题相关的设定。"
        return result
    raise ValueError(f"未知工具：{name}")
