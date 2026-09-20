"""工具意图测评样本集（Step B 真实调用用）。

设计目标：
    40 条查询 ≈ 5 成"该调工具"（与用户预期一致）：
        13 条设定问答  → 该调 search_worldview
         7 条掷骰请求  → 该调 roll_dice
        20 条闲聊/世界观外 → 不该调任何工具（10 闲聊 + 10 域外）

每条标注：
    expected_tool：期望调用的工具名（None = 不该调用）；
    category：意图分层（统计各层正确率用）；
    expected_args：掷骰用例的期望参数（sides/count），
                   用于验证模型是否把参数填对；
    note：出题意图（报告中展示，解释为什么这条该/不该调）。

边界说明：
    "帮我查一下明天北京的天气"是刻意的陷阱题——应用里没有天气
    工具，正确行为是不调用（或如实说明无法查询），调用
    search_worldview 属于工具误用。单独标注 tricky=True。
"""

from __future__ import annotations

SAMPLES: list[dict] = [
    #/ ---- 该调 search_worldview（13 条）----
    {
        "query": "小咪的斗篷下摆缝着几枚月牙银扣？",
        "expected_tool": "search_worldview",
        "category": "设定问答",
        "note": "硬设定细节，人设里没有，必须查世界观",
    },
    {
        "query": "九命庭当年是被谁焚毁的？",
        "expected_tool": "search_worldview",
        "category": "设定问答",
        "note": "历史事件设定",
    },
    {
        "query": "圣锤骑士团镇守的是哪座关隘？",
        "expected_tool": "search_worldview",
        "category": "设定问答",
        "note": "势力与地理交叉设定",
    },
    {
        "query": "月之女神缇雅和灵猫族是什么关系？",
        "expected_tool": "search_worldview",
        "category": "设定问答",
        "note": "神话背景设定",
    },
    {
        "query": "艾瑟兰大陆分为哪五大区域？",
        "expected_tool": "search_worldview",
        "category": "设定问答",
        "note": "地理总览",
    },
    {
        "query": "老刀是个什么样的角色？",
        "expected_tool": "search_worldview",
        "category": "设定问答",
        "note": "配角人物设定",
    },
    {
        "query": "影裔是一种什么样的存在？",
        "expected_tool": "search_worldview",
        "category": "设定问答",
        "note": "种族设定，注意'影'字可能诱导编造",
    },
    {
        "query": "猫族成年时的掉耳礼是什么习俗？",
        "expected_tool": "search_worldview",
        "category": "设定问答",
        "note": "文化习俗设定",
    },
    {
        "query": "小咪的月牙短刃叫什么名字？",
        "expected_tool": "search_worldview",
        "category": "设定问答",
        "note": "装备命名设定",
    },
    {
        "query": "银爪商会表面上做什么生意？",
        "expected_tool": "search_worldview",
        "category": "设定问答",
        "note": "组织设定",
    },
    {
        "query": "星辉术施法需要付出什么代价？",
        "expected_tool": "search_worldview",
        "category": "设定问答",
        "note": "魔法体系设定",
    },
    {
        "query": "世界树伊露维在哪个区域？",
        "expected_tool": "search_worldview",
        "category": "设定问答",
        "note": "地理设定",
    },
    {
        "query": "沉星秘社想要达成什么目的？",
        "expected_tool": "search_worldview",
        "category": "设定问答",
        "note": "反派组织设定",
    },

    #/ ---- 该调 roll_dice（7 条）----
    {
        "query": "帮我掷一个20面的骰子。",
        "expected_tool": "roll_dice",
        "expected_args": {"sides": 20, "count": 1},
        "category": "掷骰请求",
        "note": "最直白的掷骰",
    },
    {
        "query": "扔3次6面骰看看我今天的运气。",
        "expected_tool": "roll_dice",
        "expected_args": {"sides": 6, "count": 3},
        "category": "掷骰请求",
        "note": "面数和次数都明确",
    },
    {
        "query": "来一把100面骰，掷1次。",
        "expected_tool": "roll_dice",
        "expected_args": {"sides": 100, "count": 1},
        "category": "掷骰请求",
        "note": "大面数骰",
    },
    {
        "query": "掷骰子决定谁先出手，用4面骰就行。",
        "expected_tool": "roll_dice",
        "expected_args": {"sides": 4, "count": 1},
        "category": "掷骰请求",
        "note": "目的性表达，次数省略（期望默认 1 次）",
    },
    {
        "query": "我要测试一下手气，扔个12面骰。",
        "expected_tool": "roll_dice",
        "expected_args": {"sides": 12, "count": 1},
        "category": "掷骰请求",
        "note": "口语化表达",
    },
    {
        "query": "掷两次骰子，20面的。",
        "expected_tool": "roll_dice",
        "expected_args": {"sides": 20, "count": 2},
        "category": "掷骰请求",
        "note": "后置修饰语",
    },
    {
        "query": "帮roll一个10面骰。",
        "expected_tool": "roll_dice",
        "expected_args": {"sides": 10, "count": 1},
        "category": "掷骰请求",
        "note": "中英混搭表达",
    },

    #/ ---- 不该调工具：闲聊（10 条）----
    {
        "query": "你好呀，今天过得怎么样？",
        "expected_tool": None,
        "category": "日常闲聊",
        "note": "寒暄，工具描述里明确说不要调",
    },
    {
        "query": "聊聊你最近的心情吧。",
        "expected_tool": None,
        "category": "日常闲聊",
        "note": "情感交流",
    },
    {
        "query": "你觉得自由重要吗？",
        "expected_tool": None,
        "category": "日常闲聊",
        "note": "观点类，正好与世界观母题相近——看模型会不会过度联想",
    },
    {
        "query": "讲个笑话听听。",
        "expected_tool": None,
        "category": "日常闲聊",
        "note": "创作类请求",
    },
    {
        "query": "我今天有点累，想听你说说话。",
        "expected_tool": None,
        "category": "日常闲聊",
        "note": "陪伴类对话",
    },
    {
        "query": "晚上吃鱼还是吃牛肉好呢？",
        "expected_tool": None,
        "category": "日常闲聊",
        "note": "陷阱：猫娘爱鱼是天性，但这是闲聊不是设定查询",
    },
    {
        "query": "谢谢你陪我聊天。",
        "expected_tool": None,
        "category": "日常闲聊",
        "note": "道谢",
    },
    {
        "query": "晚安，我要去睡了。",
        "expected_tool": None,
        "category": "日常闲聊",
        "note": "道别",
    },
    {
        "query": "陪我玩个文字接龙怎么样？",
        "expected_tool": None,
        "category": "日常闲聊",
        "note": "游戏请求（掷骰的反例：说'玩'不等于要骰子）",
    },
    {
        "query": "你现在的心情像什么天气？",
        "expected_tool": None,
        "category": "日常闲聊",
        "note": "比喻类闲聊，含'天气'字样（与陷阱题对照）",
    },

    #/ ---- 不该调工具：世界观外问题（10 条）----
    {
        "query": "Python 的列表推导式怎么写？",
        "expected_tool": None,
        "category": "世界观外",
        "note": "编程问题，与角色世界无关",
    },
    {
        "query": "帮我写一首关于秋天的短诗。",
        "expected_tool": None,
        "category": "世界观外",
        "note": "创作请求，不需要设定依据",
    },
    {
        "query": "光速大概是每秒多少公里？",
        "expected_tool": None,
        "category": "世界观外",
        "note": "现实常识",
    },
    {
        "query": "怎么提高英语听力水平？",
        "expected_tool": None,
        "category": "世界观外",
        "note": "学习方法",
    },
    {
        "query": "红烧肉应该怎么做？",
        "expected_tool": None,
        "category": "世界观外",
        "note": "烹饪问题（检索测评的负样本同款）",
    },
    {
        "query": "1加到100等于多少？",
        "expected_tool": None,
        "category": "世界观外",
        "note": "数学心算",
    },
    {
        "query": "推荐几本计算机科学的入门书。",
        "expected_tool": None,
        "category": "世界观外",
        "note": "求推荐",
    },
    {
        "query": "人类第一次登月是哪一年？",
        "expected_tool": None,
        "category": "世界观外",
        "note": "历史常识（世界观里也有'历史'章节，看会不会误调）",
    },
    {
        "query": "北京的冬天一般有多冷？",
        "expected_tool": None,
        "category": "世界观外",
        "note": "现实地理气候（世界观里也有地理章节）",
    },
    {
        "query": "帮我查一下明天北京的天气。",
        "expected_tool": None,
        "category": "世界观外",
        "tricky": True,
        "note": "陷阱题：'查一下'诱导调用，但不存在天气工具；调用 search_worldview 属于工具误用",
    },
]
