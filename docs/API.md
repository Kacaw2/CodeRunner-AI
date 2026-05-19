# REST API 参考

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

详见 [AUTH.md](AUTH.md)。任一项命中即可：

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

详见 [AUTH.md](AUTH.md)。

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

## 四、题目 API

### 受保护（`/api/v1/questions`，需要登录）

| Method | Path | 权限 | 说明 |
|---|---|---|---|
| GET | `/` | 登录 | 题目列表（教师看全部 + 自己的，学生看公开+自己班级 quiz 涉及的）|
| POST | `/` | 教师 | 创建题目 |
| GET | `/<id>` | 登录 | 题目详情（学生不返回 `solution`）|
| PATCH | `/<id>` | 教师（创建者）| 修改题目 |
| DELETE | `/<id>` | 教师（创建者）| 删除题目 |
| GET | `/<id>/test-cases` | 教师 | 测试用例列表（含 `is_hidden`、`expected_output`）|
| POST | `/<id>/test-cases` | 教师 | 添加测试用例 |
| PATCH | `/<id>/test-cases/<tc_id>` | 教师 | 修改测试用例 |
| DELETE | `/<id>/test-cases/<tc_id>` | 教师 | 删除测试用例 |

### 公开（`/api/public/questions`）

| Method | Path | 权限 | 说明 |
|---|---|---|---|
| GET | `/` | 公开 | 公开题库浏览（仅返回非敏感字段）|
| GET | `/<id>` | 公开 | 单题预览（不含 solution / hidden test cases）|

---

## 五、Quiz API（`/api/v1/quizzes`）

| Method | Path | 权限 | 说明 |
|---|---|---|---|
| GET | `/` | 登录 | quiz 列表（教师看自己创建的，学生看分配到自己班级的）|
| POST | `/` | 教师 | 创建 quiz |
| GET | `/<id>` | 登录 | quiz 详情（含题目列表与 order）|
| PATCH | `/<id>` | 教师（创建者）| 修改 quiz |
| DELETE | `/<id>` | 教师（创建者）| 删除 quiz |
| POST | `/<id>/questions` | 教师 | 添加题目到 quiz：`{question_id, order, points}` |
| DELETE | `/<id>/questions/<qq_id>` | 教师 | 从 quiz 移除题目 |
| POST | `/<id>/assign` | 教师 | 把 quiz 分配到班级：`{classroom_id, due_date, allow_late_submission}` |
| GET | `/<id>/attempts` | 教师 / 学生（仅本人）| quiz 的所有 attempt |
| POST | `/<id>/start` | 学生 | 开始一次 attempt（写入 `quiz_attempts` 表）|
| POST | `/attempts/<attempt_id>/submit` | 学生 | 提交一道题：`{question_id, code}` |
| POST | `/attempts/<attempt_id>/finalize` | 学生 | 结束 attempt，计算总分 |

### 公开（`/api/public/quizzes`）

| Method | Path | 权限 | 说明 |
|---|---|---|---|
| GET | `/` | 公开 | 公开 quiz 列表（is_published=true 且无 classroom 限制）|

---

## 六、提交 API（`/api/v1/submissions`）

| Method | Path | 权限 | 说明 |
|---|---|---|---|
| POST | `/` | 学生 | 提交一份代码：`{question_id, code, language}`。同步评测，返回 `Submission` + `TestResult[]` |
| GET | `/` | 登录 | 我的提交列表（教师可加 `?student_id` 看指定学生）|
| GET | `/<id>` | 提交者 / 教师 | 提交详情（含每个 test case 的 pass / actual_output）|

---

## 七、评测 API（`/api/v1/judge`）

| Method | Path | 权限 | 说明 |
|---|---|---|---|
| POST | `/run` | 公开 | **不入库**地运行一段代码（用于 IDE 内"试运行"按钮）|
| GET | `/health` | 公开 | 沙箱健康检查（gcc / python3 / docker 探测）|

详细输入输出与状态码：[EXECUTOR.md](EXECUTOR.md)。

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
