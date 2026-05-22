# 测试

CodeRunner 用 [Cypress](https://www.cypress.io/) 做端到端测试，覆盖完整用户流程：游客、学生、教师三种角色的核心功能与失败场景。当前共 **11 个 spec / 多份 fixture**，验证 UI ↔ API 的端到端路径。

---

## 一、目录布局

```
tests/cypress/
├── e2e/
│   ├── auth.cy.js                         # 登录 / 注册 / 退出
│   ├── public_home.cy.js                  # 游客首页
│   ├── student/
│   │   ├── profile.cy.js                  # 学生 profile
│   │   ├── question_runner.cy.js          # 代码编辑器 + 提交
│   │   └── quizzes.cy.js                  # quiz 列表 / 详情 / 答题
│   └── teacher/
│       ├── classrooms.cy.js               # 班级 CRUD
│       ├── grades.cy.js                   # 成绩 dashboard / 导出
│       ├── profile.cy.js                  # 教师 profile
│       ├── questions.cy.js                # 题目 CRUD + 测试用例
│       └── quizzes.cy.js                  # quiz CRUD + 分配
├── fixtures/                              # 各 endpoint 的模拟响应
│   ├── student/
│   └── teacher/
├── support/                               # 共享 commands / hooks
└── downloads/                             # 测试期间下载的 CSV 等
```

---

## 二、运行

### 前置条件

```bash
# 1. 后端跑在 http://localhost:9900
docker-compose -f docker/docker-compose.yml up -d
docker-compose exec web python -m app.core.init_db --drop --seed --force

# 2. 安装 Node 依赖
npm install
```

### 命令

```bash
npm run cy:open           # 交互模式（GUI，调试推荐）
npm run cy:run            # headless（CI 模式）
npm run cy:smoke          # 烟雾测试子集

# 跑单个 spec
npx cypress run --spec tests/cypress/e2e/teacher/profile.cy.js
```

`cypress.config.js` 已配置 `baseUrl: http://localhost:9900`，无需手动指定 host。

`cypress.env.json` 存放测试用账号（已 gitignore）。

---

## 三、覆盖范围

| 类别 | Spec | 关注点 |
|---|---|---|
| 公开页 | `public_home.cy.js`、`auth.cy.js` | 主页 hero、登录流程、localStorage token |
| 教师班级 | `teacher/classrooms.cy.js` | 创建 / 删除 / 学生列表 + 500 兜底、删除重试 |
| 教师题库 | `teacher/questions.cy.js` | 创建 / 删除 Problem、过滤器、modal 交互、API 失败 |
| 教师 quiz | `teacher/quizzes.cy.js` | quiz CRUD、Problem 添加、班级分配 |
| 教师成绩 | `teacher/grades.cy.js` | dashboard、CSV 导出（含失败场景）|
| 教师 profile | `teacher/profile.cy.js` | 邮箱修改成功 / 失败、用户名 / 密码校验、重复 email、未登录跳转 |
| 学生 profile | `student/profile.cy.js` | dashboard 数据、profile 字段 |
| 学生 quiz | `student/quizzes.cy.js` | quiz 列表 / 详情 / 提交流程 |
| 学生答题 | `student/question_runner.cy.js` | `/problem/<id>` runner、CodeMirror 编辑、提交、AC / WA / RE 反馈 |

---

## 四、负面场景

测试套件不只看 happy path，也覆盖关键失败：

- **表单校验**：缺字段、密码不一致、用户名过短，验证 `#username-error` / `#password-error` 提示
- **重复邮箱**：教师 profile 在新邮箱等于当前邮箱时阻止提交
- **API 失败**：用 `cy.intercept()` 把关键 endpoint 改成返回 500，验证 UI 兜底（错误提示 / 空状态 / 重试按钮）
- **认证守卫**：未带 token 访问 `/teacher/profile` → 应跳转 `/auth/login?next=/teacher/profile`
- **删除重试**：DELETE 失败后 UI 应允许再试一次
- **下载失败**：CSV 导出 API 失败时不应崩溃，提示用户

---

## 五、测试模式

### 数据准备

每个 spec 在 `beforeEach` 调用 `cy.seedDatabase()` + `cy.loginByApi()`，保证测试间状态隔离与可重放。

### Mock vs 真实 API

策略：**默认走真实 API**，只对要测试失败场景的 endpoint 做 mock。这样：

- 集成路径（前端 → API → DB）真实跑通
- 失败兜底（500 / 404 / 网络错误）通过 `cy.intercept()` 单独构造

```js
// 示例：模拟 GET /api/v1/grades/submissions 返回 500
cy.intercept('GET', '/api/v1/grades/submissions*', {
  statusCode: 500,
  body: { message: 'Internal Server Error' }
}).as('gradesError');
```

### 关于 input value 校验

输入框被浏览器自动填充时显示可能被截断。关键断言用 `.should('have.value', '...')` 而非 `.should('contain', '...')`，避免 flaky。

### 单 spec 调试

GUI 模式下运行单个测试时，**后端必须保持运行**——并非所有调用都被 mock，只有特定的失败场景被拦截。

---

## 六、CI 集成

烟雾测试用于快速反馈：

```bash
npm run cy:smoke
# = cypress run --spec tests/cypress/e2e/public_home.cy.ts,tests/cypress/e2e/auth.cy.ts
```

完整套件用 `npm run cy:run` 在 PR 验证。

下载产物（如 CSV 导出测试）落在 `tests/cypress/downloads/`，已 gitignore。

---

## 七、扩展指南

### 新增 spec

1. 在 `tests/cypress/e2e/<role>/` 下新建 `<feature>.cy.js`
2. 在 `support/commands.js` 复用 `cy.loginByApi()` / `cy.seedDatabase()`
3. 用 `cy.fixture('<role>/<file>.json')` 引用 fixture，避免硬编码 JSON 体
4. 标准结构：

```js
describe('<feature>', () => {
  beforeEach(() => {
    cy.seedDatabase();
    cy.loginByApi('teacher1', 'admin123');
    cy.visit('/teacher/<feature>');
  });

  it('happy path', () => { ... });
  it('handles API failure', () => {
    cy.intercept('GET', '/api/...', { statusCode: 500 }).as('fail');
    // ...
    cy.get('.error-banner').should('be.visible');
  });
});
```

### 新增 fixture

`tests/cypress/fixtures/<role>/<endpoint>.json` 命名约定与 endpoint 路径对应，便于追踪。
## Current Problem Variant Test Notes

Seed data is destructive and grouped by parent Problem:

```powershell
python -m app.core.init_db --drop --seed --force
```

The seed creates one `Problem` per prompt, Python/C `Question` variants where available, shared `TestCase.problem_id` rows, and `QuizProblem` associations. Cypress fixtures should mirror that shape: lists use `problem_id`, `variants: [{ language, question_id }]`, and `/problem/{problem_id}?language=python|c` links. Quiz progress assertions should count completed Problems, not language-specific rows.
