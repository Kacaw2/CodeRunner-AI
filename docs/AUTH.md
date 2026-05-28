# 认证与授权

> 最后更新: 2026-05-28

CodeRunner 同时服务于两类客户端——浏览器（Jinja2 渲染的 HTML 页面）和 REST API 客户端（前端 fetch / 移动端 / 自动化测试）。两类客户端的认证语义不同：网页期望未登录时跳转登录页，API 期望返回 JSON 401。本项目用**双轨装饰器 + 三源 token 解析**统一这两套需求。

---

## 一、设计目标

| 客户端 | 登录态来源 | 未认证响应 |
|---|---|---|
| 浏览器（Web 路由） | Flask-Login session **或** Cookie `auth_token`（JWT）**或** `Authorization: Bearer` | 302 redirect 到 `/auth/login?next=<原 URL>` |
| AJAX / API 客户端 | Flask-Login session **或** Cookie `auth_token` **或** `Authorization: Bearer` | JSON 401 / 403 |

两套装饰器（`app/auth/decorators.py` + `app/auth/web_decorators.py`）共享底层的 token 解析函数，但响应格式不同。

---

## 二、Token 三源解析

`app/auth/decorators.py:_try_get_user_from_sources()` 按优先级顺序解析当前请求的用户：

```
1. Flask session    -> session['user_id']                  (Flask-Login 写入)
2. Authorization    -> 'Bearer <jwt>'                      (API 客户端)
3. Cookie           -> request.cookies['auth_token']       (浏览器 / 网页表单登录)
```

任一来源命中即返回 `User` 对象并写入 `g.current_user`，便于同请求内复用。

`web_decorators.py` 用同一原理但顺序略调整（先 Flask-Login 再 Cookie 再 Header），并把 401 响应改成 redirect。

### 为什么 Cookie 用 JWT 而不是直接 session？

- Flask 默认 session 是 client-side（签名 cookie），改用 JWT 让 token 内容可被独立服务（例如未来分离的 executor 服务）验证。
- HttpOnly + SameSite=Lax 防御 XSS / CSRF 的同时，浏览器自动随请求携带，无需前端 JS 操作。
- JS 显式登录的客户端（fetch + localStorage）则放进 `Authorization: Bearer` 头，与同源限制脱钩。

---

## 三、JWT 设计

`app/auth/utils.py:generate_auth_token()`：

```python
payload = {
    'user_id': user.id,
    'username': user.username,
    'role': user.role.value,    # 'student' / 'teacher' / 'admin'
    'exp': now + timedelta(seconds=expires_in),  # 默认 3600s
    'iat': now,
}
jwt.encode(payload, SECRET_KEY, algorithm='HS256')
```

校验路径 `verify_auth_token(token)` 处理三类异常：

| 异常 | 行为 |
|---|---|
| `ExpiredSignatureError` | 返回 `None`，让上层走未登录分支 |
| `InvalidTokenError` | 返回 `None` |
| 任意其他 `Exception` | 返回 `None`（兜底，不让认证层向上抛错）|

登录成功后服务端**同时**：
1. 在响应体返回 `{ token, user }`（供 JS 客户端存储）
2. 设置 `Set-Cookie: auth_token=<jwt>; HttpOnly; SameSite=Lax; Path=/; Max-Age=604800`（7 天，供浏览器自动携带）

刷新流程：`POST /api/v1/auth/refresh` 带旧 token → 校验通过后签发新 token + 同步刷新 Cookie。

登出：`POST /api/v1/auth/logout` 把 Cookie `auth_token` 设为空值并 `expires=0`，客户端立即失效。

---

## 四、密码存储

`app/auth/utils.py`：使用 Werkzeug 的 `generate_password_hash` / `check_password_hash`（默认 PBKDF2-SHA256，自带 salt）。数据库字段 `users.password VARCHAR(200)` 存储完整 hash 串（包含算法标识 + salt + digest）。

明文密码永远不入库，也不在日志中输出。

---

## 五、RBAC 装饰器

### API 装饰器（`app/auth/decorators.py`）

```python
@require_auth                  # 登录即可
@require_role('teacher', 'admin')   # 通用：限定一个或多个角色
@require_teacher               # = require_role('teacher', 'admin')
@require_student               # = require_role('student', 'teacher', 'admin')   # 教师/管理员可看学生页面
@require_admin                 # = require_role('admin')
@optional_auth                 # 已登录就注入 g.current_user，不强制
```

未认证 → 401 `{"message": "Authentication required"}`
角色不符 → 403 `{"message": "Access denied: Insufficient permissions"}`

### Web 装饰器（`app/auth/web_decorators.py`）

```python
@web_login_required            # 登录即可，否则 302 → /auth/login?next=<url>
@web_student_required          # student / teacher / admin 可访问
@web_teacher_required          # teacher / admin 可访问
@web_admin_required            # 仅 admin
```

注意权限**层叠**设计：

- `student` 装饰器允许 teacher / admin 访问（教师可以查看学生侧界面用于演示或调试）
- `teacher` 装饰器允许 admin 访问
- `admin` 装饰器仅 admin

未认证 → redirect 登录页；已认证但角色不符 → 直接返回 403 字符串（避免登录后再次跳转造成循环）。

---

## 六、`g.current_user` 与请求上下文

所有装饰器认证通过后都会写入 `g.current_user`（Flask 请求级上下文）。下游业务代码统一从 `g.current_user` 取人，不需要重复解 token：

```python
@bp.get("/me")
@require_auth
def me():
    return AuthService.get_user_info(g.current_user)
```

这避免了"装饰器解 token、handler 又解一次"的重复，也保证同一请求内即使 user 被业务改动，认证信息仍然指向登录时的快照。

---

## 七、注册流程

`POST /api/v1/auth/register`：

1. `RegisterIn` schema 校验（username 1-64、password 6-128、email 可选、role ∈ {student, teacher}）
2. 唯一性校验：username 与 email 都不能与现有用户冲突
3. `hash_password(plain)` → 写库
4. **注册不自动登录**——返回 201 + 用户信息，前端再走 `/login`

> 安全性考虑：注册接口当前**允许直接传 `role: teacher`**——这是教学环境约定，生产场景应改为"申请-审批"或邀请码模式。

---

## 八、安全注意事项

| 当前实现 | 备注 |
|---|---|
| Cookie `secure=False` | 默认未启用 HTTPS-only。生产部署需改 `secure=True` 并跑在 HTTPS 后面 |
| `SECRET_KEY` 默认值 `'dev-secret-key-change-in-production'` | 启动前必须通过 env 注入正确值 |
| JWT 算法 HS256 | 对称密钥；分离服务时改 RS256 + 公钥分发 |
| 无登录失败计数 / 锁定机制 | 暴力破解防御依赖上游（如 Cloudflare、网关）|
| 注册接口允许选择 teacher 角色 | 见上节，按教学环境约定 |

---

## 九、相关文件速查

| 文件 | 职责 |
|---|---|
| `app/auth/utils.py` | 密码 hash + JWT 签发 / 校验 |
| `app/auth/decorators.py` | API 装饰器（JSON 响应）|
| `app/auth/web_decorators.py` | Web 装饰器（redirect）|
| `app/api/v1/auth.py` | `/register / /login / /me / /refresh / /logout` |
| `app/services/auth_service.py` | 业务层：注册、登录、token 刷新、用户信息封装 |
| `app/models/user.py` | `User` ORM + `UserRole` 枚举 |
| `app/schemas/user_schema.py` | `RegisterIn / LoginIn / LoginOut / UserOut / RefreshOut` |
