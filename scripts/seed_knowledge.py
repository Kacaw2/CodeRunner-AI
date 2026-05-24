"""Seed the knowledge base with common error patterns and core knowledge points.

Usage:
    # Via Flask CLI (recommended):
    flask seed-knowledge

    # Standalone:
    python scripts/seed_knowledge.py
"""

import logging
import sys
import os

logger = logging.getLogger(__name__)

# ── Error Patterns ───────────────────────────────────────────────
# Each entry: (error_type, description, explanation)
# Covers CE, RE, WA, TLE for both Python and C.

ERROR_PATTERNS = [
    # ── CE (Compilation Error) — Python ──────────────────────────
    (
        "CE",
        "[Python] SyntaxError: unexpected EOF while parsing",
        "通常由未闭合的括号、引号或缺少代码块引起。检查所有括号 ()[]{}、引号 ''\"\" 是否成对，"
        "以及 if/for/while/def 后是否有缩进的代码体。",
    ),
    (
        "CE",
        "[Python] IndentationError: unexpected indent / expected an indented block",
        "Python 使用缩进表示代码块。混合使用 Tab 和空格、或缩进层级不一致会导致此错误。"
        "建议统一使用 4 个空格缩进，在编辑器中开启'显示空白字符'。",
    ),
    (
        "CE",
        "[Python] NameError: name 'xxx' is not defined",
        "变量或函数在使用前未定义。常见原因：拼写错误、忘记导入模块、"
        "在函数内部引用了未传入的外部变量。检查变量名大小写和作用域。",
    ),
    (
        "CE",
        "[Python] TypeError: unsupported operand type(s)",
        "对不兼容的类型执行了运算，例如 str + int。"
        "使用 int()、str()、float() 进行显式类型转换，或检查 input() 的返回值（始终为字符串）。",
    ),

    # ── CE (Compilation Error) — C ───────────────────────────────
    (
        "CE",
        "[C] error: expected ';' before / missing semicolon",
        "C 语言每条语句必须以分号结尾。检查报错行的上一行是否遗漏了分号。"
        "常见场景：宏定义后误加分号、for 循环条件写错。",
    ),
    (
        "CE",
        "[C] error: implicit declaration of function / undeclared identifier",
        "使用了未声明的函数或变量。确保：1) 引入了正确的头文件 (#include)；"
        "2) 函数在调用前已声明或定义；3) 变量名拼写正确。",
    ),
    (
        "CE",
        "[C] error: incompatible types / type mismatch",
        "赋值或传参时类型不匹配。例如将 int* 赋给 int，或 printf 格式符与参数类型不一致。"
        "检查指针层级、使用正确的格式符 (%d, %f, %s, %c)。",
    ),
    (
        "CE",
        "[C] error: control reaches end of non-void function",
        "声明了返回值的函数在某些分支没有 return 语句。确保所有条件分支（包括 else）都有返回值，"
        "或在函数末尾添加默认 return。",
    ),

    # ── RE (Runtime Error) — Python ──────────────────────────────
    (
        "RE",
        "[Python] IndexError: list index out of range",
        "访问列表时下标超出范围。注意 Python 列表下标从 0 开始，长度为 n 的列表最大下标是 n-1。"
        "使用 len() 检查长度，或使用 try/except 处理边界情况。",
    ),
    (
        "RE",
        "[Python] RecursionError: maximum recursion depth exceeded",
        "递归没有正确的终止条件，或问题规模过大。检查递归基准情况(base case)是否正确，"
        "考虑使用记忆化(memoization)或改为迭代实现。Python 默认递归深度限制约 1000。",
    ),
    (
        "RE",
        "[Python] ZeroDivisionError: division by zero",
        "除数为零。在执行除法前检查除数是否为 0，或使用 try/except 捕获异常。"
        "注意整数除法 // 和浮点除法 / 都会触发此错误。",
    ),
    (
        "RE",
        "[Python] ValueError: invalid literal for int() with base 10",
        "尝试将非数字字符串转换为整数。常见于处理输入数据时。"
        "使用 str.strip() 清除空白字符，使用 str.isdigit() 验证，或用 try/except 包裹转换。",
    ),
    (
        "RE",
        "[Python] KeyError: 'xxx' — 访问字典中不存在的键",
        "使用 dict[key] 访问不存在的键会抛出 KeyError。"
        "使用 dict.get(key, default) 提供默认值，或先用 if key in dict 检查。",
    ),

    # ── RE (Runtime Error) — C ───────────────────────────────────
    (
        "RE",
        "[C] Segmentation fault (SIGSEGV) — 数组越界或空指针解引用",
        "访问了非法内存地址。常见原因：数组下标越界、解引用 NULL 指针、使用已释放的内存。"
        "使用 gdb 调试定位崩溃位置，检查数组大小和指针初始化。",
    ),
    (
        "RE",
        "[C] Stack overflow — 栈溢出",
        "递归过深或在栈上分配了过大的数组。将大数组改为 static 或用 malloc 在堆上分配，"
        "检查递归终止条件。OJ 环境栈大小通常为 8MB。",
    ),
    (
        "RE",
        "[C] Floating point exception — 除零或整数溢出",
        "整数除以零或取模零会触发此信号。在运算前检查除数是否为 0。"
        "注意 INT_MIN / -1 也会导致此异常（有符号整数溢出）。",
    ),

    # ── WA (Wrong Answer) ────────────────────────────────────────
    (
        "WA",
        "Off-by-one 错误 — 循环边界差一",
        "循环范围应该是 [0, n) 还是 [0, n]？常见场景：遍历数组用 < n，"
        "枚举区间用 <= n。画几个小例子验证边界条件，特别注意 n=0 和 n=1 的情况。",
    ),
    (
        "WA",
        "整数溢出 — 中间计算结果超出 int 范围",
        "32 位 int 最大约 2×10⁹，两个 int 相乘可能溢出。"
        "Python 自动处理大整数无此问题；C 中使用 long long（最大约 9×10¹⁸），"
        "注意在乘法前转换类型：(long long)a * b。",
    ),
    (
        "WA",
        "浮点精度问题 — 浮点数比较不精确",
        "浮点运算有精度误差，不要用 == 比较浮点数。"
        "使用 abs(a - b) < 1e-9 进行近似比较。如果题目允许，优先使用整数运算。"
        "Python 中 0.1 + 0.2 != 0.3。",
    ),
    (
        "WA",
        "输出格式错误 — 多余空格、换行、大小写不符",
        "OJ 严格匹配输出。检查：行末是否有多余空格、最后一行是否有多余换行、"
        "大小写是否与要求一致、数字格式（前导零、小数位数）是否正确。",
    ),
    (
        "WA",
        "排序不稳定导致答案不一致",
        "当排序关键字相同时，不稳定排序可能产生不同顺序。"
        "Python 的 sort() 是稳定排序；C 的 qsort() 不稳定。"
        "如需稳定排序，在比较函数中加入原始索引作为次要关键字。",
    ),
    (
        "WA",
        "未处理特殊输入 — 空输入、单元素、全相同元素",
        "算法在一般情况下正确但边界情况失败。检查：空数组/字符串、只有一个元素、"
        "所有元素相同、最大/最小值输入。先处理特殊情况再进入主逻辑。",
    ),

    # ── TLE (Time Limit Exceeded) ────────────────────────────────
    (
        "TLE",
        "O(n²) 算法用于大数据集 — 需要优化到 O(n log n) 或 O(n)",
        "当 n ≥ 10⁵ 时，O(n²) 算法通常会超时（约 10¹⁰ 次操作）。"
        "考虑：排序+双指针、哈希表、二分查找、前缀和等优化手段。"
        "1 秒通常可执行约 10⁸ 次简单操作。",
    ),
    (
        "TLE",
        "递归无记忆化 — 重复计算子问题",
        "朴素递归对相同参数重复计算。使用记忆化：Python 用 @functools.lru_cache 或手动字典缓存；"
        "C 用数组记录已计算结果。经典例子：斐波那契数列从 O(2ⁿ) 优化到 O(n)。",
    ),
    (
        "TLE",
        "[Python] 输入输出太慢 — 使用 sys.stdin 替代 input()",
        "Python 的 input() 较慢，大量输入时应使用 sys.stdin.readline()。"
        "输出使用 sys.stdout.write() 或将结果收集到列表后一次性 print('\\n'.join(results))。"
        "C 中使用 scanf/printf 替代 cin/cout。",
    ),
    (
        "TLE",
        "无效循环 — 循环内做了不必要的重复工作",
        "检查循环内是否有可以提到循环外的计算、是否有可以提前 break 的条件、"
        "是否在循环内重复创建数据结构。将不变的计算移到循环外，使用预计算和缓存。",
    ),
    (
        "TLE",
        "[C] 频繁内存分配 — malloc/free 在循环内反复调用",
        "在循环内反复 malloc/free 会严重影响性能。预分配足够大的数组，"
        "或使用内存池。对于字符串操作，预分配缓冲区而非每次拼接都分配新内存。",
    ),
]

# ── Knowledge Points ─────────────────────────────────────────────
# Each entry: (topic, content, category)

KNOWLEDGE_POINTS = [
    # ── 数据结构 ─────────────────────────────────────────────────
    (
        "数组 (Array)",
        "数组是连续内存存储的同类型元素集合。支持 O(1) 随机访问（按下标），"
        "但插入/删除需要 O(n) 移动元素。Python 中 list 是动态数组，C 中需声明固定大小。"
        "适用场景：需要频繁按下标访问、数据量已知且变化不大。"
        "常见陷阱：越界访问、忘记数组从 0 开始索引。",
        "data_structure",
    ),
    (
        "链表 (Linked List)",
        "链表由节点组成，每个节点包含数据和指向下一个节点的指针。"
        "插入/删除 O(1)（已知位置时），查找 O(n)。分为单链表、双链表、循环链表。"
        "适用场景：频繁插入删除、不需要随机访问。"
        "常见陷阱：忘记处理空链表、操作指针顺序错误导致断链、忘记释放内存(C)。",
        "data_structure",
    ),
    (
        "栈 (Stack)",
        "后进先出(LIFO)数据结构。核心操作：push(入栈)、pop(出栈)、peek(查看栈顶)，均为 O(1)。"
        "Python 用 list 的 append/pop 实现；C 用数组+栈顶指针实现。"
        "典型应用：括号匹配、表达式求值、DFS、函数调用栈、单调栈。",
        "data_structure",
    ),
    (
        "队列 (Queue)",
        "先进先出(FIFO)数据结构。核心操作：enqueue(入队)、dequeue(出队)，均为 O(1)。"
        "Python 用 collections.deque；C 用循环数组实现。"
        "变体：双端队列(deque)、优先队列(heap)。典型应用：BFS、任务调度、滑动窗口。",
        "data_structure",
    ),
    (
        "树 (Tree)",
        "层级结构，由节点和边组成。二叉树每个节点最多两个子节点。"
        "二叉搜索树(BST)：左子树值 < 根 < 右子树值，查找/插入/删除平均 O(log n)。"
        "遍历方式：前序(根左右)、中序(左根右)、后序(左右根)、层序(BFS)。"
        "常见陷阱：递归遍历忘记 base case、BST 退化成链表时性能下降。",
        "data_structure",
    ),
    (
        "图 (Graph)",
        "由顶点和边组成的数据结构。存储方式：邻接矩阵 O(V²) 空间、邻接表 O(V+E) 空间。"
        "核心算法：BFS(最短路径-无权图)、DFS(连通性/拓扑排序)、"
        "Dijkstra(最短路径-正权图)、Floyd(全源最短路径)。"
        "常见陷阱：忘记标记已访问节点导致死循环、有向图vs无向图处理不同。",
        "data_structure",
    ),
    (
        "哈希表 (Hash Table)",
        "通过哈希函数将键映射到数组下标，实现 O(1) 平均查找/插入/删除。"
        "Python 的 dict 和 set 基于哈希表；C 需手动实现（链地址法或开放寻址法）。"
        "冲突处理：链地址法(最常用)、开放寻址法。"
        "常见陷阱：自定义对象作为键时需实现 __hash__ 和 __eq__(Python)、哈希冲突退化为 O(n)。",
        "data_structure",
    ),
    (
        "堆 (Heap / Priority Queue)",
        "完全二叉树，满足堆性质：最小堆中父节点 ≤ 子节点。"
        "插入和删除最值 O(log n)，查看最值 O(1)。"
        "Python 用 heapq 模块（最小堆），最大堆取负值实现。"
        "典型应用：Top-K 问题、合并 K 个有序列表、Dijkstra 算法。",
        "data_structure",
    ),

    # ── 算法 ─────────────────────────────────────────────────────
    (
        "排序算法",
        "常用排序：冒泡 O(n²)、选择 O(n²)、插入 O(n²)、归并 O(n log n) 稳定、"
        "快排 O(n log n) 平均不稳定、堆排 O(n log n)。"
        "Python 内置 sorted()/list.sort() 使用 Timsort（稳定，O(n log n)）。"
        "C 的 qsort() 不稳定。选择排序算法时考虑：稳定性需求、数据规模、是否基本有序。",
        "algorithm",
    ),
    (
        "二分查找 (Binary Search)",
        "在有序数组中查找目标，每次排除一半，O(log n)。"
        "关键点：循环条件 left <= right 还是 left < right、中间值 mid = left + (right-left)//2 防溢出、"
        "边界更新 left = mid+1 或 right = mid-1。"
        "变体：查找第一个/最后一个满足条件的位置、查找插入位置。"
        "常见陷阱：死循环（边界更新不正确）、整数溢出(C 中 (left+right)/2)。",
        "algorithm",
    ),
    (
        "递归 (Recursion)",
        "函数调用自身解决问题。三要素：1)基准情况(base case)终止递归；"
        "2)递推关系将问题拆分为更小的子问题；3)确保每次递归都向基准情况靠近。"
        "常见应用：树遍历、分治算法、回溯搜索。"
        "常见陷阱：忘记 base case 导致无限递归、递归深度过大导致栈溢出。"
        "优化：尾递归、记忆化、改为迭代。",
        "algorithm",
    ),
    (
        "动态规划 (Dynamic Programming)",
        "通过记录子问题的解避免重复计算。适用条件：最优子结构 + 重叠子问题。"
        "解题步骤：1)定义状态(dp 数组含义)；2)找状态转移方程；3)确定初始条件；4)确定遍历顺序。"
        "实现方式：自顶向下(记忆化递归)或自底向上(迭代填表)。"
        "经典问题：背包问题、最长公共子序列(LCS)、最长递增子序列(LIS)、编辑距离。"
        "常见陷阱：状态定义不正确、遍历顺序错误、初始值设置错误。",
        "algorithm",
    ),
    (
        "贪心算法 (Greedy)",
        "每一步都做局部最优选择，期望达到全局最优。不一定总能得到最优解，需要证明贪心策略的正确性。"
        "适用场景：区间调度(按结束时间排序)、霍夫曼编码、最小生成树(Kruskal/Prim)。"
        "与动态规划的区别：贪心做选择后不回头，DP 考虑所有子问题。"
        "常见陷阱：贪心策略看似正确但不是最优（需反例验证）。",
        "algorithm",
    ),
    (
        "回溯 (Backtracking)",
        "系统地搜索所有可能的解，通过剪枝减少搜索空间。本质是带剪枝的 DFS。"
        "模板：做选择 → 递归 → 撤销选择。"
        "经典问题：N 皇后、全排列、组合、子集、数独。"
        "优化：排序后剪枝、使用 visited 数组或位运算标记状态。"
        "常见陷阱：忘记撤销选择、剪枝条件不正确、重复解。",
        "algorithm",
    ),
    (
        "BFS 与 DFS",
        "BFS(广度优先)：使用队列，逐层遍历，适合最短路径(无权图)、层序遍历。时间 O(V+E)。"
        "DFS(深度优先)：使用栈或递归，深入到底再回溯，适合连通性、拓扑排序、路径搜索。时间 O(V+E)。"
        "选择依据：求最短路径用 BFS，求所有路径/判断连通性用 DFS。"
        "常见陷阱：BFS 忘记在入队时标记已访问（而非出队时）、DFS 忘记回溯标记。",
        "algorithm",
    ),

    # ── 编程基础 ─────────────────────────────────────────────────
    (
        "循环 (Loops)",
        "for 循环：已知迭代次数时使用。Python: for i in range(n)；C: for(int i=0; i<n; i++)。"
        "while 循环：条件驱动，适合不确定次数的迭代。"
        "关键概念：break(提前退出)、continue(跳过本次)、嵌套循环的时间复杂度。"
        "常见陷阱：无限循环(条件永真)、off-by-one(循环次数差一)、修改循环变量。",
        "programming_basics",
    ),
    (
        "条件语句 (Conditionals)",
        "if-elif-else(Python) / if-else if-else(C) 实现分支逻辑。"
        "注意事项：条件顺序（先判断更具体的条件）、"
        "短路求值(and/or, &&/||)、Python 中 None/0/空字符串/空列表为 falsy。"
        "C 中注意 = 与 == 的区别（赋值 vs 比较）。",
        "programming_basics",
    ),
    (
        "函数 (Functions)",
        "将代码组织为可重用的模块。参数传递：Python 按引用传对象，C 按值传递（指针模拟引用）。"
        "返回值：Python 可返回多值(tuple)，C 只能返回一个值（用指针参数输出多值）。"
        "作用域：局部变量 vs 全局变量。Python 用 global/nonlocal 声明；C 变量默认局部。"
        "常见陷阱：Python 可变默认参数(def f(a=[]))、C 中返回局部数组指针(悬空指针)。",
        "programming_basics",
    ),
    (
        "指针 (Pointers) — C 语言",
        "指针存储内存地址。声明：int *p; 取地址：&x; 解引用：*p。"
        "指针运算：p+1 移动 sizeof(int) 字节。数组名是指向首元素的指针。"
        "动态内存：malloc 分配、free 释放，务必成对使用。"
        "常见陷阱：野指针(未初始化)、悬空指针(指向已释放内存)、内存泄漏(忘记 free)、"
        "double free、指针类型不匹配。",
        "programming_basics",
    ),
    (
        "字符串处理 (String)",
        "Python 字符串不可变，拼接用 join() 而非 += (避免 O(n²))。"
        "C 字符串以 '\\0' 结尾，使用 strlen/strcpy/strcmp 等函数操作。"
        "常用操作：分割(split)、查找(find/index)、替换(replace)、格式化(f-string/printf)。"
        "常见陷阱：C 中缓冲区溢出(目标数组太小)、Python 中字符串与字节串混淆(encode/decode)。",
        "programming_basics",
    ),
    (
        "输入输出 (I/O)",
        "Python：input() 读一行(返回字符串)，print() 输出。"
        "多值读取：map(int, input().split())。快速 IO：sys.stdin.readline()。"
        "C：scanf/printf(格式化)，getchar/putchar(字符级)。"
        "常见陷阱：Python input() 返回字符串忘记转换类型、C scanf 忘记取地址符 &、"
        "C 中 scanf 后残留换行符影响后续读取。",
        "programming_basics",
    ),
]


def seed_error_patterns(kb):
    """Seed error_patterns collection if empty."""
    if kb.error_patterns.count() > 0:
        return 0

    count = 0
    for error_type, description, explanation in ERROR_PATTERNS:
        kb.add_error_pattern(error_type, description, explanation)
        count += 1
    return count


def seed_knowledge_points(kb):
    """Seed knowledge_points collection if empty."""
    if kb.knowledge.count() > 0:
        return 0

    count = 0
    for topic, content, category in KNOWLEDGE_POINTS:
        kb.add_knowledge_point(topic, content, category)
        count += 1
    return count


def seed_all(kb=None):
    """Seed all knowledge base collections. Returns (error_count, knowledge_count)."""
    if kb is None:
        from app.agents.knowledge_base import get_knowledge_base
        kb = get_knowledge_base()

    err_count = seed_error_patterns(kb)
    kp_count = seed_knowledge_points(kb)
    return err_count, kp_count


def register_cli(app):
    """Register the seed-knowledge Flask CLI command."""
    import click

    @app.cli.command("seed-knowledge")
    @click.option("--force", is_flag=True, help="Re-seed even if collections are not empty.")
    def seed_knowledge_cmd(force):
        """Seed the knowledge base with error patterns and knowledge points."""
        from app.agents.knowledge_base import get_knowledge_base

        try:
            kb = get_knowledge_base()
        except Exception as e:
            click.echo(f"Failed to initialize knowledge base: {e}", err=True)
            raise SystemExit(1)

        if force:
            ep_count = kb.error_patterns.count()
            kp_count_existing = kb.knowledge.count()
            if ep_count + kp_count_existing > 0:
                if not click.confirm(
                    f"This will delete {ep_count} error patterns and "
                    f"{kp_count_existing} knowledge points. Continue?"
                ):
                    click.echo("Aborted.")
                    return
            all_ep_ids = kb.error_patterns.get()["ids"]
            if all_ep_ids:
                kb.error_patterns.delete(ids=all_ep_ids)
            all_kp_ids = kb.knowledge.get()["ids"]
            if all_kp_ids:
                kb.knowledge.delete(ids=all_kp_ids)
            click.echo("Cleared existing collections.")

        err_count = seed_error_patterns(kb)
        kp_count = seed_knowledge_points(kb)

        if err_count:
            click.echo(f"Seeded {err_count} error patterns.")
        else:
            click.echo("Error patterns already populated — skipped.")

        if kp_count:
            click.echo(f"Seeded {kp_count} knowledge points.")
        else:
            click.echo("Knowledge points already populated — skipped.")

        click.echo("Done.")


if __name__ == "__main__":
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    from app import create_app

    app = create_app()
    with app.app_context():
        err, kp = seed_all()
        print(f"Seeded {err} error patterns, {kp} knowledge points.")
