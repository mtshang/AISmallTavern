"""测评公共设施：路径解析、知识库加载、评分检索与统计工具。

设计原则：
    1. 只通过 import 复用项目模块（rag / assets_tools_calls），不修改任何程序代码文件；
    2. 分数等内部数据通过加载角色目录里与生产完全相同的缓存文件获得
       （metadata.json + rag.faiss），检索流程复刻 rag.search_worldview 的内部步骤；
    3. 模型对象直接使用 rag._load_worldview_embedding_model 的 lru_cache，
       保证与生产检索共享同一个已加载的模型。
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

#/ 项目根目录 = eval/retrieval/ 向上三级（main.py 所在目录）。
PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent.parent

#/ 把项目根目录加入模块搜索路径，
#/ 这样 "import rag" / "import assets_tools_calls" 都能找到项目模块。
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

#/ eval/ 根目录：三份中文测评报告统一输出到这里。
EVAL_ROOT: Path = Path(__file__).resolve().parent.parent

#/ 本大类（检索质量）脚本目录与结果输出目录。
EVAL_DIR: Path = Path(__file__).resolve().parent
RESULTS_DIR: Path = EVAL_DIR / "results"

#/ 默认角色目录与嵌入模型目录（与 main.py 源码运行时的解析结果一致）。
CHARACTER_DIR: Path = PROJECT_ROOT / "assets" / "default" / "默认猫娘default_cat"
MODEL_DIR: Path = PROJECT_ROOT / "granite-embedding-r2"

#/ 标题路径的公共前缀，报告展示时省略，避免表格过宽。
TITLE_PREFIX = "默认猫娘default_cat>世界观>"


def setup_console() -> None:
    """让 Windows 控制台/重定向输出稳定使用 UTF-8，中文表格不乱码。"""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


def short_title(title_path: str) -> str:
    """去掉标题路径的公共前缀，用于表格展示。"""
    if title_path.startswith(TITLE_PREFIX):
        return title_path[len(TITLE_PREFIX):]
    return title_path


def load_knowledge_base(
    model_dir: Path | None = None,
    character_dir: Path | None = None,
) -> dict:
    """加载角色知识库，返回检索所需的全部材料。

    流程与 rag.search_worldview 开头一致：先调用
    md_to_metadata_and_faiss_and_TtoC() 检查世界观是否变化
    （必要时重建索引），再读取 metadata.json 与 rag.faiss。

    返回值字典包含：
        metadata   —— 完整元数据；
        chunks     —— 分块列表（下标即 FAISS 编号）；
        encoding   —— 维度、模型目录等编码设置；
        index      —— 反序列化后的 FAISS 索引对象；
        model      —— 已加载的嵌入模型（来自 rag 的缓存）；
        rebuilt    —— 本次加载是否触发了索引重建（bool）。
    """
    import faiss
    import numpy as np

    import rag

    model_dir = Path(model_dir or MODEL_DIR)
    character_dir = Path(character_dir or CHARACTER_DIR)

    metadata_path = character_dir / "metadata.json"

    #/ 记录加载前的修改时间：之后 mtime 变化说明缓存未命中、发生了重建。
    before_mtime = metadata_path.stat().st_mtime if metadata_path.is_file() else None

    #/ 与生产路径完全一致：先检查世界观是否变化，必要时重建索引。
    rag.md_to_metadata_and_faiss_and_TtoC(model_dir, character_dir)

    metadata = json.loads(
        (character_dir / "metadata.json").read_text(encoding="utf-8")
    )

    after_mtime = metadata_path.stat().st_mtime

    index_bytes = (character_dir / "rag.faiss").read_bytes()
    index = faiss.deserialize_index(
        np.frombuffer(index_bytes, dtype=np.uint8)
    )

    #/ 模型目录与版本以元数据记录为准，与生产检索时加载的完全相同。
    model = rag._load_worldview_embedding_model(
        metadata["encoding"]["model_dir"],
        metadata["encoding"]["model_version"],
    )

    return {
        "metadata": metadata,
        "chunks": metadata["chunks"],
        "encoding": metadata["encoding"],
        "index": index,
        "model": model,
        "rebuilt": before_mtime != after_mtime,
    }


def score_query(kb: dict, query: str) -> dict:
    """对单条查询做编码 + 全量检索，返回全部块的相似度分数与计时。

    内部步骤复刻 rag.search_worldview：同一个模型缓存、同样的
    encode 参数、同样的归一化与全量 index.search。
    区别只在于把分数暴露出来，供测评统计。
    """
    import faiss
    import numpy as np

    dimension = kb["encoding"]["dimension"]
    model = kb["model"]
    index = kb["index"]

    #/ ---- 编码阶段 ----
    t0 = time.perf_counter()
    embeddings = model.encode(
        [query],
        convert_to_numpy=True,
        truncate_dim=dimension,
        normalize_embeddings=False,
        show_progress_bar=False,
    )
    embeddings = np.ascontiguousarray(embeddings, dtype=np.float32)
    faiss.normalize_L2(embeddings)
    t1 = time.perf_counter()

    #/ ---- 检索阶段（全量，与生产一致）----
    scores, indices = index.search(embeddings, index.ntotal)
    t2 = time.perf_counter()

    return {
        "scores": scores[0].tolist(),
        "indices": indices[0].tolist(),
        "encode_ms": (t1 - t0) * 1000.0,
        "search_ms": (t2 - t1) * 1000.0,
    }


def percentile(values: list[float], p: int) -> float:
    """简单百分位数（线性插值），p 取 0~100。"""
    data = sorted(values)
    if len(data) == 1:
        return data[0]
    pos = (len(data) - 1) * p / 100
    lower = int(pos)
    upper = min(lower + 1, len(data) - 1)
    frac = pos - lower
    return data[lower] * (1 - frac) + data[upper] * frac


def stats_block(values: list[float]) -> dict:
    """一组数值的常用统计量：最小 / 均值 / P50 / P90 / 最大。"""
    return {
        "count": len(values),
        "min": round(min(values), 4),
        "mean": round(sum(values) / len(values), 4),
        "p50": round(percentile(values, 50), 4),
        "p90": round(percentile(values, 90), 4),
        "max": round(max(values), 4),
    }


def save_json(name: str, data: dict) -> Path:
    """把测评结果 JSON 写入 eval/results/，返回文件路径。"""
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    path = RESULTS_DIR / name
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return path
