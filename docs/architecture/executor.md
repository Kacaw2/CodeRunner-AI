# 2026-06-07 · CodeRunner-AI 架构 05｜代码执行沙箱

> 文档编号 05 ｜ 最后更新 2026-06-07 ｜ 范围: 不可信代码隔离执行、资源限制、输出归一化、状态码映射

代码沙箱是 CodeRunner 的核心引擎：把不可信的学生代码（C 或 Python）在隔离环境中编译、运行、与期望输出比对，并约束 CPU / 内存 / 时间 / 输出长度，防止恶意代码或意外死循环影响平台。

---

## 一、设计目标

| 目标 | 实现 |
|---|---|
| 时间隔离 | 子进程 wall-clock 超时（`subprocess.run(timeout=...)`）+ `RLIMIT_CPU` |
| 内存隔离 | `RLIMIT_AS`（默认 256 MB）|
| 文件系统隔离 | `tempfile.TemporaryDirectory` 每次评测一份临时目录，进程退出即销毁 |
| 输出截断 | stdout / stderr 截断（默认 10000 / 4000 字节）|
| 输出归一化 | 行尾空白、尾空行、转义序列（`\n` / `\t`）统一处理 |
| 部署灵活 | 三档 fallback：远程 HTTP 沙箱 → 本地 native 子进程 → 旧 Docker 兼容路径 |
| 状态可解析 | 标准 OJ 状态码：`AC / WA / CE / RE / TLE / SYSTEM_ERROR` |

---

## 二、整体架构

```
HTTP POST /api/v1/judge/run
   ↓
app/api/v1/judge.py: run_code()
   ↓ 校验 CodeRunInputSchema
   ↓
app/services/executor_service.py: ExecutorService.run_code()
   ↓
   ├──[1]── 若 EXECUTOR_REMOTE_URL 已设置
   │           → app/core/executor_client.py: run_code_remote()
   │           → POST 到远程沙箱（带 X-EXECUTOR-TOKEN 头）
   │           → 失败时记录日志并 fallback 到 [2]
   │
   └──[2]── app/core/executor.py: CodeExecutor.run_code()
              ├── 'python' / 'py' → run_python_code()
              ├── 'c'             → run_c_code()  (gcc 编译 → 二进制运行)
              └── 其他           → SYSTEM_ERROR: UNSUPPORTED
                  ↓
                  subprocess.run([...], timeout, preexec_fn=_set_resource_limits)
                  ↓
                  归一化 stdout → 与 expected_output 比对 → 派定状态
```

---

## 三、沙箱部署模式

### 模式 A：本地原生（默认）

应用容器**自己内置 gcc / python3**，沙箱直接 fork 子进程，由 Linux 内核的 `RLIMIT_*` 强制资源约束。

```
[Web Container (gunicorn)]
        │
        ├── subprocess.run(['python3', 'main.py'], timeout=2)
        │       ↓ preexec_fn 设置
        │       RLIMIT_CPU = 10s
        │       RLIMIT_AS  = 256 MB
        │       RLIMIT_FSIZE = 10 MB
        │
        └── subprocess.run(['./main'], timeout=2)  # C 二进制
```

优点：低延迟、单容器部署简单。
缺点：与应用进程同主机，进程隔离不如独立容器；macOS 开发时 `resource` 模块不可用（已 graceful 降级）。

### 模式 B：远程 HTTP 沙箱

设置 `EXECUTOR_REMOTE_URL` 后，`executor_service` 把代码 POST 到独立部署的沙箱服务（例如部署在 Render 上的隔离实例）。

```
[Web]                        [Executor Service]
  │                                │
  │── POST /run                    │
  │   X-EXECUTOR-TOKEN: ***        │
  │── { code, language, stdin,     │
  │     expected_output,           │
  │     time_limit_sec }           │
  │                          ────→ │ 在隔离实例运行
  │                                │ 同样的 resource limits
  │  ←──────────────────────────── │ JSON { status, passed, ... }
```

优点：物理隔离，恶意代码不影响主应用；可水平扩展 executor。
缺点：网络往返延迟（≥ 100 ms）。

`executor_service.run_code()` 在远程调用失败时会 fallback 到本地，保证可用性。

### 模式 C（已弃用但保留）：Docker-in-Docker

旧版本通过 Docker SDK 起 sibling container 运行用户代码（`USE_DOCKER=true`）。当前默认 `USE_DOCKER=false`，原因：DinD 要求挂载 `/var/run/docker.sock` 带来权限提升风险，且部署目标 Render 不支持。`run_c_in_docker / run_code_in_docker` 函数名保留，内部已切换到 native subprocess（向后兼容）。

---

## 四、Python 沙箱实现

`app/core/executor.py:CodeExecutor.run_python_code()`：

```python
with tempfile.TemporaryDirectory(dir=EXECUTOR_TMP_DIR) as tmpdir:
    (Path(tmpdir) / 'main.py').write_text(code, encoding='utf-8')
    result = subprocess.run(
        [PYTHON_VERSION, 'main.py'],
        cwd=tmpdir,
        input=normalized_stdin,
        capture_output=True,
        text=True,
        timeout=time_limit_sec,           # wall-clock
        preexec_fn=_set_resource_limits,  # CPU + 内存 + 文件大小
    )
```

关键设计：

1. **临时目录**：每次评测生成 `/tmp/executor/<random>/main.py`，进程退出 / 异常都会自动清理（`with` 语句保证）。
2. **stdin 用 `input=`**：直接传字符串给子进程的 stdin，不走临时文件。
3. **wall-clock vs CPU 时间**：`subprocess.run(timeout=...)` 是墙上时钟；`RLIMIT_CPU` 是实际 CPU 时间。两者都设，前者防止 sleep / IO 阻塞，后者防止 busy loop 占满 CPU。
4. **`preexec_fn` 在 fork 后 / exec 前执行**：在子进程上下文设置 rlimit，对父进程无影响。

---

## 五、C 沙箱实现

`run_c_code()` 多一步编译：

```python
# 1. 编译
subprocess.run(['gcc', '-std=c11', '-O2', '-pipe', '-Wall', '-o', 'main', 'main.c'],
               cwd=tmp_path, timeout=30)
# 2. 编译失败 → 返回 CE，附 compile_log
# 3. 编译成功 → 同 Python 路径运行 ./main
```

编译错误（CE）会把 gcc stderr 完整返回（截断到 4 KB）作为 `compile_log`，供学生定位错误。

`gcc` 失败模式：

| 异常 | 状态 | 说明 |
|---|---|---|
| `subprocess.TimeoutExpired` | CE | 编译本身超时（30 s）|
| `FileNotFoundError` | CE | 容器里没装 gcc（部署错误）|
| `returncode != 0` | CE | 用户代码语法错 / 链接错 |
| `OK` | 进入运行阶段 | 继续 |

---

## 六、Resource Limits

`_set_resource_limits()`（仅 Linux 有效，macOS 自动跳过）：

```python
resource.setrlimit(RLIMIT_CPU,   (10, 10))         # CPU 时间 10s
resource.setrlimit(RLIMIT_AS,    (256MB, 256MB))   # 虚拟内存 256MB
resource.setrlimit(RLIMIT_FSIZE, (10MB, 10MB))     # 单文件最大 10MB
```

**未设置 `RLIMIT_NPROC`** —— 早期版本设过，但与 Python multiprocessing 冲突导致 `fork: Resource temporarily unavailable`。当前依赖 wall-clock timeout 防 fork bomb（限 2-10 秒内能 fork 出的子进程数量有限）。

**未设置网络隔离** —— 当前沙箱不阻断网络。在远程 executor 模式下通过部署架构（隔离 VPC）解决。

---

## 七、输出归一化

OJ 题目最常见的"答错"误判来源是空白差异。沙箱在比对前对**预期输出和实际输出**都做归一化：

```python
def _normalize_input(text):
    # 处理用户在 JSON 里写 "1\\n2\\n3" 想表达三行
    return text.replace('\\n', '\n').replace('\\t', '\t')

def _normalize_output(text):
    lines = [line.rstrip() for line in text.splitlines()]   # 去每行尾空白
    while lines and lines[-1] == '':                        # 去尾空行
        lines.pop()
    return '\n'.join(lines)
```

注意 `_normalize_input` 用于**入参**（前端 JSON 里写转义的换行），`_normalize_output` 用于**比对**。两者方向相反：前者把字面 `\n` 转成真换行，后者裁掉额外空白。

---

## 八、状态码映射

| 状态 | 全称 | 触发条件 |
|---|---|---|
| `AC` | Accepted | 进程正常退出 (return 0) + 输出与 expected 完全匹配（归一化后）|
| `WA` | Wrong Answer | 进程正常退出但输出不匹配 |
| `CE` | Compilation Error | 仅 C：gcc 失败 / 超时 / 缺失 |
| `RE` | Runtime Error | 进程非 0 退出（段错误、未捕获异常等）|
| `TLE` | Time Limit Exceeded | `subprocess.TimeoutExpired` |
| `SYSTEM_ERROR` | System Error | 平台异常（写文件失败 / 不支持的语言等）|

`expected_output=None` 时不做比对，状态留 `AC` 或 `RE` / `TLE`，`passed` 字段为 `null`。

---

## 九、API 输入输出

### Request（`POST /api/v1/judge/run`）

```json
{
  "code": "print(int(input()) * 2)",
  "language": "python",
  "input": "21",
  "expected_output": "42",
  "time_limit_sec": 2.0
}
```

`code` 必填且非空；`language` 默认 `c`，支持 `c / python / py / python3`；`input / expected_output` 可选；`time_limit_sec` 默认 2.0，硬上限由 `EXECUTOR_DEFAULT_TIMEOUT` 环境变量控制。

### Response（200）

```json
{
  "status": "AC",
  "passed": true,
  "compiled": true,
  "stdout": "42",
  "stderr": "",
  "time_ms": 38,
  "compile_log": "",
  "expected": "42",
  "expected_match": true,
  "error_message": "",
  "executor": "local"           // 或 "remote"
}
```

`executor` 字段标记本次评测走的是哪条路径，便于线上 debug。

---

## 十、健康检查

`GET /api/v1/judge/health`：

```json
{
  "status": "healthy",          // healthy | degraded | unhealthy
  "message": "Judge service is running",
  "docker_available": true,
  "docker_version": "Docker version 24.0.7"
}
```

`docker_available=false` 时降级为 `degraded` 而非 `unhealthy`——因为当前默认走 native 模式，没有 Docker 也能跑。仅在子进程能力本身故障时返回 `503 unhealthy`。

---

## 十一、性能约束

| 项 | 当前默认 | 可调环境变量 |
|---|---|---|
| 单次评测 wall-clock | 2.0 s | `EXECUTOR_DEFAULT_TIMEOUT` |
| 单次评测 CPU 时间 | 10 s | `EXECUTOR_MAX_CPU_TIME` |
| 单次评测内存 | 256 MB | `EXECUTOR_MAX_MEMORY_MB` |
| 编译超时 | 30 s（硬编码）| - |
| stdout 截断 | 10 KB | `EXECUTOR_MAX_STDOUT` |
| stderr 截断 | 4 KB | `EXECUTOR_MAX_STDERR` |
| 临时文件单文件上限 | 10 MB（`RLIMIT_FSIZE`）| - |

并发：gunicorn 4 workers，单 worker 同时一份代码评测（subprocess 阻塞）。同时跑的最大并发数 = workers 数量。如需更高吞吐，应启用远程 executor 模式并独立扩容。

---

## 十二、当前已知限制

1. **沙箱不隔离网络** —— 用户代码可发起出站请求；生产场景应在远程 executor 容器层 drop network。
2. **不限制系统调用** —— 没有用 seccomp / AppArmor 过滤危险 syscall（fork bomb 仅靠 wall-clock 兜底）。
3. **不支持多文件项目** —— 一次评测一份单文件源码，无 `Makefile` / 多 `.py` 模块。
4. **语言扩展需改代码** —— 添加新语言（如 Java / C++）需在 `CodeExecutor.run_code()` 加分支；架构本身可扩展但当前未做。
5. **macOS 开发降级** —— `resource` 模块不存在，仅靠 wall-clock；不影响 Linux 部署。

改进方向见 README 的 "Future Enhancements" 章节。

---

## 十三、相关文件

| 文件 | 职责 |
|---|---|
| `app/api/v1/judge.py` | HTTP endpoint：`/run / /health` |
| `app/services/executor_service.py` | 调度层：远程优先，失败 fallback 本地 |
| `app/core/executor.py` | 本地沙箱实现（Python + C）|
| `app/core/executor_client.py` | 远程沙箱 HTTP 客户端 |
| `app/schemas/judge_schema.py` | 输入校验 schema |
