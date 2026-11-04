# 逐文件参考 · 说明

这一组文档覆盖 `src/novelvideo/` 下全部 **453 个 Python 文件**，以及前端、脚本、测试的结构。目标不是复述代码，而是让人在**改之前**知道：这个文件为什么存在、边界在哪、动它会影响谁。

## 1. 条目格式

每个文件一段，字段固定，方便跳读：

```text
#### `文件名.py` · 1,234 行 [核实]
作用   一句话说明它解决的问题（不是"工具函数"这类空话）
接口   核心类/函数，带关键签名或行为
I/O    读什么（表/文件/参数） → 写什么（返回值/表/目录）
依赖   上游调用者 → 本文件 → 下游依赖
注意   反直觉点、隐含契约、改动的坑
```

字段缺省规则：

- 没有外部 IO 的小文件，省略 I/O；
- 纯再导出的 `__init__.py` 只写一行；
- 条目里出现的表名、错误类名都可以 `grep` 到源码。

## 2. 状态标记

| 标记 | 含义 | 可信度 |
|---|---|---|
| `[核实]` | 读过源码（文档字符串 + 签名 + 关键函数体），接口名逐条比对 | 可直接依赖 |
| `[推断]` | 只依据签名、文档字符串与调用点推断，未读全部实现 | 判断用途可以，判断边界行为不行 |
| `[待补]` | 源码缺少说明，或行为依赖运行期配置 | 改动前必须读代码 |

本次重写中，绝大多数文件属于 `[核实]`（至少读了模块文档字符串与公开签名）；标注 `[推断]` 的多为纯数据/常量文件，或实现细节不影响契约的文件。

## 3. 分册与范围

| 文档 | 范围 | 文件数 |
|---|---|---:|
| [01-核心顶层模块](01-核心顶层模块.md) | `src/novelvideo/*.py` | 54 |
| [02-api层](02-api层.md) | `api/`（不含 `routes/`） | 16 |
| [03-api路由](03-api路由.md) | `api/routes/` | 27 |
| [04-agents与generators](04-agents与generators.md) | `agents/`、`generators/`、`generators/scene_voxel/` | 38 |
| [05-chat](05-chat.md) | `chat/` | 32 |
| [06-freezone](06-freezone.md) | `freezone/`、`freezone/agent_workflows/` | 59 |
| [07-运行时与端口](07-运行时与端口.md) | `ports/`、`ports/local/`、`task_backend/`、`runners/`、`shared/`、`security/`、`storage/` | 81 |
| [08-领域与集成](08-领域与集成.md) | `cognee/`、`director_world/`、`seedance2_i2v/`、`services/`、`workflows/`、`skills/`、`audio/`、`backup/`、`export/`、`render_plan/`、`ui/`、`prompts/`、`assets/` | 77 |
| [09-utils与verification](09-utils与verification.md) | `utils/`、`verification/`、`verification/cli/` | 69 |
| [10-前端文件](10-前端文件.md) | `frontend/src/` | 1,505 |
| [11-scripts与tests](11-scripts与tests.md) | `scripts/`（36）、`tests/`（468） | 504 |
| **后端合计** | 01–09 九册 | **453** |

## 4. 怎么快速找到某个文件

三种方式，按场景选：

```bash
# 1) 已知文件名，直接搜本目录
grep -rn "session_registry.py" docs/wiki/files/

# 2) 已知功能关键词（如"配额"）
grep -rn "配额" docs/wiki/files/

# 3) 已知目录，去对应分册看分组标题
grep -n "^### " docs/wiki/files/07-运行时与端口.md
```

## 5. 与功能篇的分工

| 你的问题 | 看哪里 |
|---|---|
| 「这套系统怎么跑起来的」 | `../02-架构与分层.md` |
| 「某个接口返回什么」 | `../06-HTTP-API参考.md` |
| 「这张表谁写的」 | `../04-数据模型与SQLite表.md` |
| 「这个文件干什么的、能不能删」 | 本目录 |
| 「改了会影响谁」 | 条目里的 `依赖` 字段 + 对应功能篇 |
