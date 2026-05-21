# AI Agents 设计文档

本文档描述 CodeRunner-AI 的 AI Agent 模块设计。该模块在现有评测平台基础上集成多 Agent 编排系统，为学生和教师提供智能辅导、代码审查、自动出题和学习分析能力。

---

## 一、架构概览

```
┌──────────────────────────────────────────────────────┐
│                Flask Web App                          │
│  /api/v1/ai/*  端点                                   │
└────────────────────┬─────────────────────────────────┘
                     │
         ┌───────────▼────────────┐
         │  AgentOrchestrator     │
         │  (LangGraph StateGraph)│
         │                       │
         │  route → agent → respond
         └──┬──────┬──────┬──────┘
            │      │      │
     ┌──────▼┐ ┌──▼───┐ ┌▼────────┐ ┌──────────┐
     │ Tutor │ │Review│ │Generator│ │Analytics │
     │ Agent │ │Agent │ │Agent    │ │Agent     │
     └──┬────┘ └──┬───┘ └──┬──────┘ └──┬───────┘
        │         │        │           │
     ┌──▼─────────▼────────▼───────────▼──┐
     │          Tool Layer                 │
     │ ExecutorTool · QuestionQueryTool    │
     │ SubmissionQueryTool · StatsQueryTool│
     └────────────────┬───────────────────┘
                      │
     ┌────────────────▼───────────────────┐
     │     现有 Service 层（不改动）         │
     │  executor_service · question_service│
     │  submission_service · teacher_stats │
     └────────────────────────────────────┘
```

### 关键设计原则

1. **Agent 不直接访问数据库**，一律通过现有 Service 层的 Tool 封装
2. **LangGraph 管理状态流转**，每个 Agent 是图中的一个节点
3. **对话历史持久化到 MySQL**，运行时状态缓存到 Redis
4. **SSE 流式输出**，兼容现有 Jinja2 前端
5. **Orchestrator 统一入口**，前端可指定 agent_type 或由 LLM 自动路由

---

## 二、技术选型

| 组件 | 技术 | 用途 |
|------|------|------|
| LLM | DeepSeek API (deepseek-chat)，兼容 OpenAI 协议 | Agent 推理引擎 |
| Agent 编排 | LangGraph | 状态图驱动的多 Agent 流转 |
| LLM 集成 | langchain-openai + langchain-core | Tool Calling 标准抽象（通过 OpenAI 兼容接口） |
| 状态缓存 | Redis 7 | 对话上下文缓存、rate limiting |
| 对话存储 | MySQL (现有) | 对话历史持久化 |
| 流式输出 | Flask SSE (stream_with_context) | 实时响应 |

### 新增依赖

```
langgraph>=0.4.0
langchain-openai>=0.3.0
langchain-core>=0.3.0
redis>=5.0.0
```

---

## 三、目录结构

```
app/agents/
├── __init__.py              # 暴露 AgentOrchestrator
├── orchestrator.py          # LangGraph 主编排器
├── state.py                 # AgentState TypedDict
├── config.py                # AI 相关配置读取
├── agents/
│   ├── __init__.py
│   ├── base.py              # BaseAgent 抽象基类
│   ├── tutor.py             # 智能辅导
│   ├── reviewer.py          # 代码审查
│   ├── generator.py         # 自动出题
│   └── analytics.py         # 学习分析
├── tools/
│   ├── __init__.py
│   ├── code_executor.py     # 包装 ExecutorService.run_code()
│   ├── question_query.py    # 查询题目 + 测试用例
│   ├── submission_query.py  # 查询提交历史 + 测试结果
│   └── stats_query.py       # 查询学习统计数据
└── prompts/
    ├── __init__.py
    ├── tutor.py
    ├── reviewer.py
    └── generator.py
```

---

## 四、共享状态

```python
# app/agents/state.py
class AgentState(TypedDict):
    messages: Annotated[list, add_messages]   # LangGraph 消息累加
    agent_type: Literal["tutor", "reviewer", "generator", "analytics"]
    user_id: int
    user_role: str                            # student / teacher
    context: dict                             # 请求上下文（见下表）
    tool_results: list
    final_response: str
```

### context 字段说明

| 场景 | context 包含 |
|------|-------------|
| Tutor 辅导 | `question_id`, `submission_id`, `code`, `error_status` |
| Code Review | `question_id`, `code` |
| 自动出题 | `topic`, `difficulty`, `language`, `quiz_id`(可选) |
| 学习分析 | `target_student_id`, `question_id`(可选) |

---

## 五、Orchestrator 编排流程

```
            ┌───────┐
            │ route │  意图识别 / 直接使用前端指定的 agent_type
            └───┬───┘
      ┌─────┬───┴───┬──────┐
      ▼     ▼       ▼      ▼
   tutor reviewer generator analytics
      │     │       │      │
      └─────┴───┬───┴──────┘
                ▼
           ┌─────────┐
           │ respond  │  统一格式化 + 安全过滤
           └────┬────┘
                ▼
               END
```

### 路由规则

1. 前端在请求中指定 `agent_type` → 直接路由
2. 未指定时 → `route` 节点用 Claude 做 few-shot 意图分类：
   - 包含"帮我看看""哪里错了""怎么改" → tutor
   - 包含"审查""review""代码质量" → reviewer
   - 包含"出题""生成""创建题目" → generator
   - 包含"分析""报告""薄弱" → analytics

---

## 六、四个 Agent 详细设计

### 6.1 Tutor Agent（智能辅导）

| 属性 | 说明 |
|------|------|
| 面向角色 | Student |
| 触发方式 | 提交代码后遇到 WA/RE/TLE，点击 "Ask AI" |
| 可用工具 | ExecutorTool, QuestionQueryTool, SubmissionQueryTool |

**核心策略**：苏格拉底式教学，分级提示，绝不直接给代码。

```
错误分类 → 分级提示
├── CE (编译错误): 指出错误位置附近，提示语法规则
├── RE (运行时错误): 分析可能原因（空指针/越界/除零）
├── WA (答案错误): 对比期望输出，引导逻辑分析
└── TLE (超时): 提示算法复杂度，引导优化方向
```

**提示级别**：
- Level 1：抽象方向提示（"循环条件可能有问题"）
- Level 2：具体线索（"当输入为空时你的代码会怎样？"）
- Level 3：伪代码级引导（"试试在循环前加一个判断"）

### 6.2 Review Agent（代码审查）

| 属性 | 说明 |
|------|------|
| 面向角色 | Student（提交后可选）、Teacher（查看学生代码时） |
| 触发方式 | 点击 "AI Review" 或教师主动调用 |
| 可用工具 | ExecutorTool, QuestionQueryTool |

**审查维度**（按优先级）：
1. 正确性 — 逻辑错误、边界条件
2. 可读性 — 命名、结构
3. 效率 — 时间/空间复杂度
4. 安全性 — 缓冲区溢出、未初始化变量（C）
5. 最佳实践 — 语言惯用法

**输出格式**：结构化 JSON

```json
{
  "overall_score": "B",
  "summary": "逻辑正确但有边界条件遗漏",
  "issues": [
    {
      "severity": "warning",
      "line": 12,
      "message": "未处理空数组情况",
      "suggestion": "在循环前添加长度检查"
    }
  ],
  "strengths": ["变量命名清晰", "整体结构合理"]
}
```

### 6.3 Generator Agent（自动出题）

| 属性 | 说明 |
|------|------|
| 面向角色 | Teacher |
| 触发方式 | 教师在出题页面点击 "AI 生成" |
| 可用工具 | ExecutorTool |

**自验证流程**（关键设计）：

```
LLM 生成题目 + 测试用例 + 参考答案
            │
            ▼
  ExecutorTool 运行参考答案 × 所有测试用例
            │
       全部 AC? ─── No ──→ LLM 修正（最多 3 轮）
            │
           Yes
            │
            ▼
    返回验证通过的完整题目数据
```

生成的数据结构直接对齐 `Question` + `TestCase` 模型，教师确认后可一键入库。

### 6.4 Analytics Agent（学习分析）

| 属性 | 说明 |
|------|------|
| 面向角色 | Teacher、Student |
| 触发方式 | 查看学习报告页面 |
| 可用工具 | SubmissionQueryTool, StatsQueryTool, QuestionQueryTool |

**分析能力**：
- 错误模式识别：统计 WA/RE/TLE 分布，找出高频错误类型
- 学习曲线：分数随时间的变化趋势
- 薄弱环节：按题目类型/知识点分析正确率
- 个性化推荐：基于薄弱点推荐练习题

---

## 七、Tool 层设计

每个 Tool 使用 `@tool` 装饰器，包装现有 Service 方法。

| Tool | 包装的 Service | Agent 使用 |
|------|---------------|-----------|
| `execute_code` | `ExecutorService.run_code()` | Tutor, Review, Generator |
| `get_question_detail` | `Question.query` + `TestCase.query` | Tutor, Review, Generator, Analytics |
| `get_student_submissions` | `SubmissionService.get_student_submissions()` | Tutor, Analytics |
| `get_submission_detail` | `SubmissionService.get_submission_detail()` | Tutor, Review |
| `get_student_stats` | `TeacherStatsService` 相关方法 | Analytics |

### 安全约束

- Tool 输出截断：stdout ≤ 2000 字符，stderr ≤ 1000 字符，防止 token 爆炸
- 权限继承：Tool 内部复用调用者的 user_id 和 role 做权限检查
- 只读原则：除 Generator 生成题目入库外，所有 Tool 均为只读操作

---

## 八、数据模型扩展

新增两张表用于对话持久化：

### ai_conversations

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INT PK | |
| user_id | INT FK→users | 发起对话的用户 |
| agent_type | VARCHAR(20) | tutor / reviewer / generator / analytics |
| context_type | VARCHAR(20) | question / submission / quiz |
| context_id | INT | 关联的业务实体 ID |
| title | VARCHAR(200) | 对话标题（自动生成） |
| created_at | DATETIME | |
| updated_at | DATETIME | |

### ai_messages

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INT PK | |
| conversation_id | INT FK→ai_conversations | |
| role | VARCHAR(10) | user / assistant / system |
| content | TEXT | 消息内容 |
| tool_calls | JSON | Agent 工具调用记录（可选） |
| tokens_used | INT | 本次消息消耗的 token 数 |
| created_at | DATETIME | |

---

## 九、配置项

在 `app/core/config.py` 的 `Config` 类中新增：

| 环境变量 | 默认值 | 说明 |
|---------|--------|------|
| `DEEPSEEK_API_KEY` | (必填) | DeepSeek API 密钥 |
| `AI_MODEL` | `deepseek-chat` | 使用的模型 |
| `AI_MAX_TOKENS` | `4096` | 单次响应最大 token |
| `AI_TEMPERATURE` | `0.7` | 生成温度 |
| `AI_RATE_LIMIT` | `20` | 每用户每分钟最大请求数 |
| `REDIS_URL` | `redis://localhost:6379/0` | Redis 连接 |

---

## 十、基础设施变更

### Docker Compose 新增 Redis

```yaml
redis:
  image: redis:7-alpine
  container_name: educode_redis
  restart: unless-stopped
  ports:
    - "6379:6379"
  volumes:
    - redis_data:/data
  networks:
    - educode_network
```

### Flask App 变更

- `app/__init__.py`：注册 `ai_bp` 蓝图
- `app/core/extensions.py`：初始化 Redis 连接
- `app/core/config.py`：新增 AI 相关配置项

---

## 十一、开发阶段

| 阶段 | 内容 | 产出 |
|------|------|------|
| Phase 1 | 骨架搭建：agents 包结构、State 定义、Config、数据库迁移、Redis 容器 | 可运行的空 Agent 框架 |
| Phase 2 | Tutor Agent 完整实现 + `/api/v1/ai/chat` + SSE 流式 + 前端聊天面板 | 学生可用的 AI 辅导功能 |
| Phase 3 | Review Agent + Generator Agent（含自验证循环） | 代码审查 + AI 出题 |
| Phase 4 | Analytics Agent + 对话历史 + 完整前端集成 | 学习分析报告 |
| Phase 5 | Prompt 调优、错误处理、Rate Limiting、测试 | 生产就绪 |

---

## 十二、相关文档

- AI API 端点参考：[AI_API.md](AI_API.md)
- 系统架构总览：[ARCHITECTURE.md](ARCHITECTURE.md)
- 现有 REST API：[API.md](API.md)
- 代码沙箱：[EXECUTOR.md](EXECUTOR.md)
