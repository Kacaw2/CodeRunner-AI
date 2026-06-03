# Phase 0 — 安全加固执行方案 (Security Hardening Plan)

## Context（为什么做）

CodeRunner-AI 是面向学生/教师的编程教学平台，会执行学生提交的任意代码、并把 AI agent 的运行轨迹落库供教师查看。八维度审计发现三个**生产级安全风险**，且阅读真实源码后确认比审计描述更严重：

1. **沙箱形同虚设**：`app/core/executor.py` 文件头注释明确写 "Runs code directly in Render container **without Docker**"。`run_code_in_docker`（executor.py:520-534）名不副实，实际转发到 `_default_executor.run_code` 走 `subprocess.run` 裸执行。学生代码直接在 web 容器内以应用身份运行 gcc/python，无网络隔离、无文件系统隔离、无 PID 限制。`docker/docker-compose.yml:81` 的 `USE_DOCKER:"false"` 这个开关在代码里**从未被读取使用**（仅 `ExecutorConfig.USE_DOCKER` 定义于 executor.py:33 但无引用）。→ 真实 RCE / 数据外泄面。
2. **SECRET_KEY 弱默认值**：两处 —— `core/config.py:35-37`（agent/FastAPI 侧，用于 JWT 验签）与 `app/core/config.py:6`（Flask session）—— 默认 `"dev-secret-key-change-in-production"`。`core/config.py:77-79` 的 `get_settings()` 仅 `lru_cache` 无校验。生产若漏配 `SECRET_KEY` 环境变量 → 任何人可伪造 JWT / 篡改 session。
3. **Trace 写库不脱敏**：`core/observability/tracing.py` 的 `save()`（line 59）把 `input_message`(75)、`input_context`(67,76)、`output_response`(77)、每个 step 的 `tool_input`(96) 原样落库 `AgentRun/AgentRunStep`。学生粘贴的含密钥代码、对话中的凭证会明文入库，并经 `get_agent_trace` 工具回给教师。

预期结果：学生代码在隔离沙箱中执行；生产环境缺失强密钥时拒绝启动（fail-fast）；落库前自动抹除凭证类敏感串。

---

## 沙箱实现策略（已确认 = 方案 A）

采用**方案 A — 独立 executor 微服务**：复用项目已有的 `EXECUTOR_REMOTE_URL` + `app/core/executor_client.py` 通路（executor_service.py:49-73 已支持）。新建一个网络隔离、非 root、只读 rootfs 的 executor 容器，web 容器通过 HTTP 调它。**不挂 docker.sock**（避免等同宿主 root 的风险）。下文 0.3 即按此方案。

---

## 改动清单

### 0.1 Trace 写库脱敏 —— `core/observability/tracing.py`（零依赖，最先做）

**现状**：`save()` line 66-67 直接 `_make_json_safe`，line 75/76/77/96 原样落库。

**改动**：
1. 文件末尾（`_make_json_safe` 旁，约 line 117 前）新增凭证脱敏函数：
```python
import re as _re

_SECRET_PATTERNS = [
    _re.compile(r"sk-[A-Za-z0-9]{20,}"),                                  # OpenAI/DeepSeek keys
    _re.compile(r"Bearer\s+[A-Za-z0-9._\-]{8,}", _re.I),                  # bearer tokens
    _re.compile(r"(?i)(api[_-]?key|secret|token|password|passwd|pwd)\s*[=:]\s*\S+"),
    _re.compile(r"eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}"),  # JWT
]

def _redact_secrets(obj):
    if isinstance(obj, str):
        s = obj
        for pat in _SECRET_PATTERNS:
            s = pat.sub("[REDACTED]", s)
        return s
    if isinstance(obj, dict):
        return {k: _redact_secrets(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_redact_secrets(v) for v in obj]
    return obj
```
2. `save()` line 64-67 区域改为先脱敏：
```python
            total_ms = int((time.monotonic() - self.start_time) * 1000)

            # P0: redact credentials before persisting
            self.input_message = _redact_secrets(self.input_message)
            response = _redact_secrets(response)
            safe_steps = _redact_secrets(_make_json_safe(self.steps))
            safe_context = _redact_secrets(_make_json_safe(self.input_context))
```
下游 line 75/76/77/90-104 自动使用脱敏后的值（step 来自已脱敏的 `safe_steps`，line 96 的 `tool_input` 已覆盖）。

**纵深（可选）**：`mcp_gateway/middleware/sanitizer.py` 出库时复用 `_redact_secrets`，兜底历史脏数据。

**回归风险**：误伤含 `key=value` 字面的正常代码（如 `password = input()` 会被打码）。trace 仅审计用、非回放，可接受。每次 save 多几次 regex，量小可忽略。

---

### 0.2 SECRET_KEY 启动门禁 —— `core/config.py` + `app/__init__.py`

**现状**：`core/config.py:35-37`、`app/core/config.py:6` 弱默认；无任何启动校验。

**改动**：
1. `core/config.py` —— Settings 加 `validate()`，`get_settings()` 调用（替换 line 77-79）：
```python
_DEFAULT_SECRET = "dev-secret-key-change-in-production"

class Settings:
    ...
    def validate(self) -> None:
        if not self.DEBUG:
            if not self.SECRET_KEY or self.SECRET_KEY == _DEFAULT_SECRET:
                raise RuntimeError(
                    "SECRET_KEY is unset or using the insecure default in non-DEBUG mode.")

@lru_cache()
def get_settings() -> Settings:
    s = Settings()
    s.validate()
    return s
```
2. `app/__init__.py` —— `create_app` 内 `app.config.from_object(...)`（line 13）之后插入门禁。注意需放行 `TESTING`（TestingConfig DEBUG 继承 False）：
```python
    # P0: SECRET_KEY gate — refuse to boot in production with insecure key
    if not app.config.get("DEBUG") and not app.config.get("TESTING"):
        sk = app.config.get("SECRET_KEY")
        if not sk or sk == "dev-secret-key-change-in-production":
            raise RuntimeError(
                "SECRET_KEY is unset or using the insecure default. "
                "Set the SECRET_KEY env var before starting in production.")
```

**回归风险**：本地以 production 配置但未设密钥会启动失败（符合预期）。Development(DEBUG=True)/Testing(TESTING=True) 不受影响。`run.py` 在 import 时即 `create_app()`，门禁即时生效。

---

### 0.3 强制沙箱执行（方案 A：独立 executor 微服务）

**现状**：`executor_service.run_code`（executor_service.py:32）→ 若有 `EXECUTOR_REMOTE_URL` 走远程（49-73），否则走 `run_code_in_docker`（76）→ 实为原生 subprocess。`run_c_in_docker`（114）的 `_fallback_run_c`（176-303）是另一条裸 subprocess 执行路径。

**改动**：
1. **新建 `docker/Dockerfile.executor`**（最小、非 root、nologin sandbox 用户）。
2. **新建 executor 服务进程**（轻量 HTTP，接收 `executor_client.run_code_remote` 的请求），内部对每次提交用严格资源限制 + 临时目录执行。容器层面提供隔离：`--network=none`、只读 rootfs、内存/PID 限制、非 root。
3. **`docker/docker-compose.yml`**：
   - 删除 web 服务的 `USE_DOCKER:"false"`（line 81）。
   - 新增 `executor` 服务（用 Dockerfile.executor 构建，独立内部网/network_mode、`read_only: true`、`mem_limit`、`pids_limit`、`cap_drop: [ALL]`、`security_opt: [no-new-privileges]`、`user: "4000:4000"`）。
   - web 服务新增 `EXECUTOR_REMOTE_URL: http://executor:PORT`，并 `depends_on: [executor]`。
4. **`app/core/executor.py`**：把 `run_code_in_docker`（520）与 `run_c_in_docker`（506）的"原生回退"语义改为 **fail-closed**：当无 `EXECUTOR_REMOTE_URL` 且非显式允许原生时，返回 `EXECUTOR_UNAVAILABLE` 错误而非裸跑。保留 `CodeExecutor` 类供 executor 服务进程内部使用。
5. **`app/services/executor_service.py`**：删除 `_fallback_run_c`（176-303）裸执行；`run_c_in_docker` 的 `except ImportError`（157-161）改为返回 `EXECUTOR_UNAVAILABLE`。`run_code`（32）主体不变 —— 现在 `EXECUTOR_REMOTE_URL` 成为主路径。

**fail-closed 错误结构**（保持与现有返回字段兼容，新增 status）：
```python
{"status": "EXECUTOR_UNAVAILABLE", "compiled": False, "passed": False,
 "stdout": "", "stderr": "Sandbox executor unavailable", "time_ms": 0,
 "expected": expected_output, "expected_match": None,
 "error_message": "Sandbox executor unavailable"}
```

**回归风险**：判题/AI 跑代码的所有调用方依赖 `run_code` 返回结构 —— 新增 status `EXECUTOR_UNAVAILABLE` 需确认前端/判题逻辑遇未知 status 不崩（非 `AC` 即视为未通过即可）。`tools/code/executor.py` 调 `ExecutorService.run_code`，透传新 status 不会崩。

---

## 执行顺序

```
0.1 (零风险，先行) → 0.2 (启动门禁) → 0.3 (沙箱微服务)
```
0.1 / 0.2 / 0.3 之间无代码耦合，可并行开发；0.3 合并前必须完成沙箱回归。

## 待修改/新建文件

- `core/observability/tracing.py`（改）
- `mcp_gateway/middleware/sanitizer.py`（改，纵深，可选）
- `core/config.py`（改）
- `app/__init__.py`（改）
- `app/core/config.py`（参考，确认 TESTING/DEBUG 语义）
- `app/core/executor.py`（改）
- `app/services/executor_service.py`（改，删 fallback）
- `docker/Dockerfile.executor`（新建）
- `docker/docker-compose.yml`（改）
- executor 服务进程入口（新建，方案 A）

## 复用的现有设施

- `app/core/executor_client.py` 的 `run_code_remote` + `EXECUTOR_REMOTE_URL` 通路（executor_service.py:49-73）—— 方案 A 直接复用，无需新协议。
- `core/observability/tracing.py:_make_json_safe`（118）—— 脱敏在其之上叠加。
- `app/core/config.py` 的 `DevelopmentConfig/ProductionConfig/TestingConfig`（63-91）—— 门禁复用 DEBUG/TESTING 标志。

## 验证方式（端到端）

**0.1 脱敏**：构造 input_message/code 含 `sk-xxxxxxxx...`、`Bearer abc...`、`API_KEY=secret`、JWT → 触发一次 agent run → 查 `agent_runs` / `agent_run_steps` 表，相关字段应为 `[REDACTED]`；正常代码仍可读。
**0.2 门禁**：(a) `FLASK_ENV=production` + 不设 SECRET_KEY → `create_app()` 抛 RuntimeError；(b) 设强密钥 → 正常启动；(c) `FLASK_ENV=development`（DEBUG=True）→ 不报错；(d) pytest（TESTING=True）→ 不报错。
**0.3 沙箱（方案 A）**：(a) 构建 executor 镜像 + 起 compose；(b) 提交 `import socket; socket.create_connection(...)` 联网代码 → 失败（network=none）；(c) fork bomb / 大内存 → 受 pids/mem 限制，不拖垮 web；(d) `open("/etc/passwd","w")` → 只读失败；(e) 停掉 executor 服务 → web 返回 `EXECUTOR_UNAVAILABLE` 而非裸跑；(f) 正常 AC 用例回归通过。
**测试套件**：`pytest`（关注 executor / auth / trace 相关用例），确认门禁不误伤测试。
