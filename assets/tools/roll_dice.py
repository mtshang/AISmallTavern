import random
def roll_dice(sides: int, count: int) -> str:
    """投掷指定面数的骰子，返回每次投掷的结果文本。"""

    #/ 类型注解不会自动检查实际参数，因此这里手动校验。
    #/ 使用 type(...) is int，也会排除 True、False。
    if type(sides) is str:
        sides=int(sides)
    if type(count) is str:
        count=int(count)
    
    if type(sides) is not int or type(count) is not int:
        raise TypeError("sides 和 count 必须是整数。")

    if sides < 1:
        raise ValueError("骰子面数必须至少为 1。")

    #/ 100 是本项目自行设定的次数上限，不是接口协议要求。
    if not 1 <= count <= 10000:
        raise ValueError("投掷次数必须在 1～10000 之间。")

    results: list[str] = []

    for i in range(1, count + 1):
        point = random.randint(1, sides)
        results.append(f"{sides}面骰第{i}次投掷，点数为：{point}。")
    return "\n".join(results)