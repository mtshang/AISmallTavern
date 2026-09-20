"""延迟测评：冷加载、热检索全程延迟与纯检索分解。

测量三层数据：
    1. cold_load_s：进程首次加载嵌入模型的时间（SentenceTransformer
       加载权重 + 懒初始化），对应"启动预加载"的一次性成本；
    2. warm_full_ms：热状态下调用生产入口 rag.search_worldview 的全程
       延迟（含缓存哈希检查、索引文件读取与反序列化、编码、检索、
       正文拼装），对应"每轮消息前预检索"的每轮成本；
    3. encode_ms / search_ms：把第 2 项中的纯编码与纯检索拆开计时，
       用于说明延迟的大头在哪。

只读缓存与索引，不修改任何程序文件。
运行：在项目根目录执行
    .venv\\Scripts\\python.exe eval\\eval_latency.py
"""

from __future__ import annotations

import datetime
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402  (先入 path 再取公共设施)
import dataset  # noqa: E402

import rag  # noqa: E402


def run() -> dict:
    """执行延迟测评，返回汇总字典（供 run_all 聚合）。"""
    common.setup_console()

    print("=" * 62)
    print("测评二：检索延迟基准")
    print("=" * 62)

    #/ ---- 1. 冷加载计时（本进程第一次加载模型）----
    #/ 先走与生产一致的缓存检查：缓存命中时它不会加载模型。
    t0 = time.perf_counter()
    rag.md_to_metadata_and_faiss_and_TtoC(
        common.MODEL_DIR, common.CHARACTER_DIR
    )
    cache_check_ms = (time.perf_counter() - t0) * 1000.0

    import json

    metadata = json.loads(
        (common.CHARACTER_DIR / "metadata.json").read_text(encoding="utf-8")
    )

    t0 = time.perf_counter()
    model = rag._load_worldview_embedding_model(
        metadata["encoding"]["model_dir"],
        metadata["encoding"]["model_version"],
    )
    cold_load_s = time.perf_counter() - t0

    print(
        f"[冷加载] 嵌入模型首次加载：{cold_load_s:.1f} s"
        f"（缓存检查另耗 {cache_check_ms:.1f} ms）"
    )

    #/ ---- 2. 热检索全程延迟（生产入口）----
    #/ warmup 让懒初始化（首次推理的算子编译等）不进入正式统计。
    for query in dataset.ALL_QUERIES[:3]:
        rag.search_worldview(
            common.MODEL_DIR, common.CHARACTER_DIR, query
        )

    full_ms: list[float] = []
    for query in dataset.ALL_QUERIES:
        t0 = time.perf_counter()
        rag.search_worldview(
            common.MODEL_DIR, common.CHARACTER_DIR, query
        )
        full_ms.append((time.perf_counter() - t0) * 1000.0)

    #/ ---- 3. 纯检索分解（编码 / FAISS 检索分开计时）----
    kb = common.load_knowledge_base()

    encode_ms: list[float] = []
    search_ms: list[float] = []
    for query in dataset.ALL_QUERIES:
        result = common.score_query(kb, query)
        encode_ms.append(result["encode_ms"])
        search_ms.append(result["search_ms"])

    #/ 全程延迟减去编码与检索，剩下的就是
    #/ 文件 IO / 哈希校验 / 反序列化 / 正文拼装等其他开销。
    other_ms = [
        f - e - s
        for f, e, s in zip(full_ms, encode_ms, search_ms)
    ]

    summary = {
        "ran_at": datetime.datetime.now().astimezone().isoformat(
            timespec="seconds"
        ),
        "sample_count": len(dataset.ALL_QUERIES),
        "cold_load_s": round(cold_load_s, 2),
        "warm_full_ms": common.stats_block(full_ms),
        "encode_ms": common.stats_block(encode_ms),
        "search_ms": common.stats_block(search_ms),
        "other_overhead_ms": common.stats_block(other_ms),
    }

    print()
    print(f"[样本] {len(dataset.ALL_QUERIES)} 条查询（热状态，warmup 3 次后计时）")
    print("[search_worldview 全程] ", summary["warm_full_ms"])
    print("[  其中 编码 encode ]   ", summary["encode_ms"])
    print("[  其中 FAISS 检索 ]   ", summary["search_ms"])
    print("[  其中 IO/哈希/拼装 ] ", summary["other_overhead_ms"])

    json_path = common.save_json("latency.json", summary)
    print()
    print(f"[输出] {json_path}")
    print()

    return summary


if __name__ == "__main__":
    run()
