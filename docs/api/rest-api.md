# REST API 参考

> 最后更新: 2026-05-28

CodeRunner 暴露的 REST API 用 [flask-smorest](https://flask-smorest.readthedocs.io/) 构建，自动生成 OpenAPI 3.0.3 规范，运行时可在 **`/swagger-ui`** 访问交互式文档。

本文档列出所有 endpoint 的高层概览。详细字段以 schema 代码 (`app/schemas/`) 与 Swagger UI 为准。

---

## 一、约定

### URL 前缀

| 前缀 | 用途 |
|---|---|
| `/api/v1/*` | 受保护 API，需要认证 |
| `/api/public/*` | 公开 API，无需认证 |
| `/health` | 健康检查（公开）|
| `/swagger-ui` | OpenAPI 交互文档 |

### 认证

详见 [../architecture/auth.md](../architecture/auth.md)。任一项命中即可：

- `Cookie: auth_token=<JWT>`
- `Authorization: Bearer <JWT>`
- Flask session（同源浏览器登录后自动）

### 通用响应

```json
// 成功（具体字段按 endpoint 不同）
{ "id": 1, "title": "...", ... }

// 失败
{ "message": "Authentication required" }       // 401
{ "message": "Access denied: Insufficient permissions" }  // 403
{ "errors": { "field": ["Not a valid email."] } }  // 422 (Marshmallow 校验失败)
```

### 分页

需要分页的 endpoint 接受 `?page=1&per_page=20` 查询参数，返回：

```json
{
  "items": [...],
  "page": 1,
  "per_page": 20,
  "total": 137,
  "pages": 7
}
```

实现：`app/utils/pagination.py:paginate()`。

---

## 二、认证 API（`/api/v1/auth`）

| Method | Path | 权限 | 说明 |
|---|---|---|---|
| POST | `/register` | 公开 | 注册新用户。Body: `RegisterIn`。返回 `UserOut` |
| POST | `/login` | 公开 | 登录。Body: `LoginIn`。返回 `{token, user}`，同时设置 `auth_token` Cookie |
| GET | `/me` | 登录 | 当前用户信息 |
| POST | `/refresh` | 登录 | 刷新 JWT，更新 Cookie |
| POST | `/logout` | 公开 | 清除 Cookie |

详见 [../architecture/auth.md](../architecture/auth.md)。

---

## 三、班级 API（`/api/v1/classrooms`）

| Method | Path | 权限 | 说明 |
|---|---|---|---|
| GET | `/` | 登录 | 列出当前用户相关的班级（学生看已加入，教师看自己创建） |
| POST | `/` | 教师 | 创建班级，自动生成邀请码 |
| GET | `/<id>` | 登录 | 班级详情 |
| PATCH | `/<id>` | 教师（创建者）| 修改班级名称 / 描述 |
| DELETE | `/<id>` | 教师（创建者）| 删除班级（级联删除 enrollment / quiz_assignment）|
| POST | `/join` | 学生 | Body `{code}`，按邀请码加入班级 |
| GET | `/<id>/students` | 教师 | 班级学生名单 |
| DELETE | `/<id>/students/<student_id>` | 教师 | 把学生踢出班级 |

---

## 四、Problem API

`Problem` 是 dashboard、quiz 和 `/problem/<problem_id>` runner 暴露给用户的练习单元；`Question` 只作为内部可执行语言变体保留，用于 starter code、solution、executor language 和 submission 归属。

### 受保护（`/api/v1/problems`，按接口要求登录或教师权限）

| Method | Path | 权限 | 说明 |
|---|---|---|---|
| GET | `/problems` | 可选登录 | dashboard/list；一行一个 Problem，返回 `variants: [{language, question_id}]` |
| GET | `/problems/<id>?language=python` | 可选登录 | runner 详情；按语言选择变体，返回共享公开测试用例 |
| POST | `/problems/<id>/submit` | 学生 | 提交 `{language, code, time_limit_sec}`，记录选中变体的 `question_id` |
| POST | `/problems` | 教师 | 创建一个 Problem，可同时带 Python/C starter code、solution、explanation |
| PATCH | `/problems/<id>` | 教师（创建者）| 修改 Problem 元数据和语言变体代码 |
| DELETE | `/problems/<id>` | 教师（创建者）| 删除 Problem、语言变体和共享测试用例 |
| GET | `/teacher/problems` | 教师 | 教师题库列表，可按 `quiz_id` / `created_by_me` 过滤 |
| GET | `/problems/<id>/manage` | 教师（创建者）| 管理页详情，含隐藏测试用例和变体 solution |
| POST | `/problems/<id>/test-cases` | 教师（创建者）| 添加共享测试用例 |
| DELETE | `/test-cases/<tc_id>` | 教师（创建者）| 删除共享测试用例 |

旧 `/api/v1/questions` 端点仅作为兼容层保留，不作为当前用户界面入口；公开题库列表使用 `/api/v1/problems`。

---

## 五、Quiz API（`/api/v1/quizzes`）

| Method | Path | 权限 | 说明 |
|---|---|---|---|
| GET | `/` | 登录 | quiz 列表（教师看自己创建的，学生看分配到自己班级的）|
| POST | `/` | 教师 | 创建 quiz |
| GET | `/<id>` | 登录 | quiz 详情（含 `problems` 列表与 order）|
| PATCH | `/<id>` | 教师（创建者）| 修改 quiz |
| DELETE | `/<id>` | 教师（创建者）| 删除 quiz |
| GET | `/<id>/problems` | 教师（创建者）| 列出 quiz 内的 Problems |
| POST | `/<id>/problems` | 教师 | 添加 Problem 到 quiz：`{problem_id, order, points}` |
| PUT | `/<id>/problems/<problem_id>` | 教师 | 修改 quiz 内 Problem 的 order / points |
| DELETE | `/<id>/problems/<problem_id>` | 教师 | 从 quiz 移除 Problem |
| POST | `/<id>/assign` | 教师 | 把 quiz 分配到班级：`{classroom_id, due_date, allow_late_submission}` |
| GET | `/<id>/attempts` | 教师 / 学生（仅本人）| quiz 的所有 attempt |
| POST | `/<id>/start` | 学生 | 开始一次 attempt（写入 `quiz_attempts` 表）|
| POST | `/attempts/<attempt_id>/submit` | 学生 | 兼容提交接口；当前 runner 使用 `/api/v1/problems/<problem_id>/submit` |
| POST | `/attempts/<attempt_id>/finalize` | 学生 | 结束 attempt，计算总分 |

### 公开（`/api/public/quizzes`）

| Method | Path | 权限 | 说明 |
|---|---|---|---|
| GET | `/` | 公开 | 公开 quiz 列表（is_published=true 且无 classroom 限制）|

---

## 六、提交 API（`/api/v1/submissions`）

| Method | Path | 权限 | 说明 |
|---|---|---|---|
| POST | `/problems/<problem_id>/submit` | 学生 | 提交一份代码：`{language, code, time_limit_sec}`。同步评测，返回 `problem_id`、`question_id`、`Submission` + `TestResult[]` |
| POST | `/questions/<question_id>/submit` | 学生 | 兼容旧 question-id 提交路径 |
| GET | `/` | 登录 | 我的提交列表（教师可加 `?student_id` 看指定学生）|
| GET | `/<id>` | 提交者 / 教师 | 提交详情（含每个 test case 的 pass / actual_output）|

---

## 七、评测 API（`/api/v1/judge`）

| Method | Path | 权限 | 说明 |
|---|---|---|---|
| POST | `/run` | 公开 | **不入库**地运行一段代码（用于 IDE 内"试运行"按钮）|
| GET | `/health` | 公开 | 沙箱健康检查（gcc / python3 / docker 探测）|

详细输入输出与状态码：[../architecture/executor.md](../architecture/executor.md)。

---

## 八、成绩 API（`/api/v1/grades`）

| Method | Path | 权限 | 说明 |
|---|---|---|---|
| GET | `/students/summary` | 教师 | 教师视角：所有学生成绩概览（用于 grades dashboard）|
| GET | `/submissions` | 教师 | 提交流水，可按 `student_id / classroom_id / quiz_id` 过滤 |
| GET | `/submissions/export` | 教师 | 导出 CSV `grade_report_<YYYY-MM-DD>.csv` |
| GET | `/students/<student_id>` | 教师 / 学生（仅本人）| 单个学生的所有 attempt + score |

---

## 九、教师统计与学生 API

### `/api/v1/teacher/stats`

| Method | Path | 权限 | 说明 |
|---|---|---|---|
| GET | `/dashboard` | 教师 | 教师 dashboard 概览（班级数、学生数、活跃 quiz、待批数等）|
| GET | `/quiz/<quiz_id>` | 教师 | 单个 quiz 的统计（提交人数 / 平均分 / 题目通过率）|

### `/api/v1/teacher/students`

| Method | Path | 权限 | 说明 |
|---|---|---|---|
| GET | `/` | 教师 | 我教过的学生（去重所有班级 union）|
| GET | `/<student_id>/classrooms` | 教师 | 该学生在我教的哪些班 |

---

## 十、用户 Profile API（`/api/v1/profile` / `/api/v1/users`）

| Method | Path | 权限 | 说明 |
|---|---|---|---|
| GET | `/me/profile` | 登录 | 个人详细信息 |
| PATCH | `/me/profile` | 登录 | 修改 email |
| POST | `/me/password` | 登录 | 修改密码（需提供旧密码）|
| GET | `/users/<id>/profile` | 教师 | 看其他用户的 profile（仅教师 / 管理员）|

---

## 十一、健康检查与指标

| Method | Path | 权限 | 说明 |
|---|---|---|---|
| GET | `/health` | 公开 | `{status, service, checks: {database: 'ok'}}`，DB ping 失败返回 503 |
| GET | `/api/public/metrics` | 公开 | Prometheus 风格基础指标（如启用）|

---

## 十二、Swagger UI

应用启动后访问 [http://localhost:9900/swagger-ui](http://localhost:9900/swagger-ui)，可看到所有 endpoint 的：

- 请求 / 响应 schema（JSON Schema 自动从 Marshmallow 派生）
- "Try it out" 在线发请求
- 当前认证状态

OpenAPI 规范本身可通过 `/swagger.json`（`OPENAPI_URL_PREFIX` 控制）下载。
## Current Problem Variant API

CodeRunner-AI now exposes `Problem` as the public practice and quiz unit. `Question` remains the internal executable language variant selected by the runner and stored by submissions.

### Problem APIs (`/api/v1`)

| Method | Path | Access | Notes |
|---|---|---|---|
| GET | `/problems` | optional auth | Dashboard/list view; returns one row per Problem with available variants. |
| GET | `/problems/{problem_id}?language=python` | optional auth | Problem runner detail; selects a language variant and returns shared public test cases. |
| POST | `/problems/{problem_id}/submit` | student | Submit code by `{language, code, time_limit_sec}`; stores the selected variant `question_id`. |
| POST | `/problems` | teacher | Create one Problem with optional Python/C starter code, solution, and explanations. |
| PATCH | `/problems/{problem_id}` | teacher owner | Update problem metadata and variant code fields. |
| GET | `/teacher/problems` | teacher | Teacher problem workspace list, with optional `quiz_id` / `created_by_me`. |
| GET | `/problems/{problem_id}/manage` | teacher owner | Teacher management detail including hidden shared test cases and variant solutions. |
| POST | `/problems/{problem_id}/test-cases` | teacher owner | Add a shared test case for all variants. |
| DELETE | `/test-cases/{tc_id}` | teacher owner | Delete a shared test case. |

### Quiz Problem APIs (`/api/v1/quizzes`)

| Method | Path | Access | Notes |
|---|---|---|---|
| GET | `/{quiz_id}` | auth | Returns `problems` and problem-level progress. |
| GET | `/{quiz_id}/problems` | teacher owner | List problems in a quiz. |
| POST | `/{quiz_id}/problems` | teacher owner | Add `{problem_id, order, points}` to a quiz. |
| PUT | `/{quiz_id}/problems/{problem_id}` | teacher owner | Update quiz-specific order/points. |
| DELETE | `/{quiz_id}/problems/{problem_id}` | teacher owner | Remove a Problem from a quiz. |

Legacy question-id submission and quiz-question routes are kept only as compatibility shims. User-facing navigation should use `/problem/{problem_id}?language=python|c`, not `/question/{question_id}`.
