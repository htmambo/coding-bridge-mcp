# Task: 修复项目健康度问题（任务归档遗漏 + ruff 未纳入依赖）

**Status**: ✅ Completed (完成时间: 2026-07-02)
**Author**: Claude
**Scope**: 流程合规修复 + 开发工具链补全，不改变任何 Provider 运行时行为。

---

## 1. 背景与目标

### 背景

项目健康度检查发现两类问题：

- **问题 A（流程合规）**：`docs/Task/Active/FIX_EXTERNAL_REVIEW_RISKS_PLAN.md`
  正文「验收」段显示 T1/T2/T3/T5/T7 全部 ✅、T4/T6 显式豁免、测试 14 passed，
  即任务实质已完成，但**未按 CLAUDE.md 生命周期规范归档**——仍滞留 Active/，
  `docs/Task/README.md` 也仍将其列为 Active。
- **问题 B（工具链）**：项目记忆标注 `lint=ruff check`，DeepSeek/SenseNova 等历史
  计划也以 `uv run ruff check src tests` 作为验收标准，但 `ruff` 既不在 `dev`
  依赖组、CI 也只跑 pytest——lint 约束实际从未在 CI 中执行。基线扫描出 3 个 E402
  告警（`server.py` 中 `load_dotenv()` 后的 config 导入），属有意模式，需显式抑制。

### 目标

1. 归档已完成的 `FIX_EXTERNAL_REVIEW_RISKS_PLAN.md`，更新任务索引；
2. 将 `ruff` 纳入 dev 依赖与 CI，并修复现有 3 个 E402 告警，使 `uv run ruff check .` 全绿；
3. 不改变任何 Provider 运行时行为（E402 抑制采用配置/注释，不移动 `load_dotenv()`）。

### 关键设计决策

| 决策点 | 结论 | 依据 |
|---|---|---|
| 问题 A 归档目标目录 | `docs/Task/Archive/2026-06/` | 任务开始时间 2026-06-20，按开始月归档（与同月其他任务一致） |
| 问题 A 状态字段 | 保持原文 ✅，补完成时间 2026-07-02 | 正文显示实质已完成，仅补归档元数据 |
| ruff 版本约束 | `ruff>=0.6` (dev group) | 与 uv 生态兼容的稳定下限，不锁死上限以便获修复 |
| E402 抑制方式 | `[tool.ruff.lint.per-file-ignores]` 对 `src/coding_bridge_mcp/server.py` 忽略 E402 | `load_dotenv()` 必须先于 config 导入执行；文件级配置比逐行 `# noqa` 更显式、可文档化 |
| CI lint 步骤位置 | `uv sync` 之后、`pytest` 之前 | lint 失败应早于测试失败暴露 |
| 是否 lint tests 目录 | 是（`ruff check .` 全仓） | 历史验收标准即 `src tests`，保持一致 |

> **E402 不重构的理由**：`load_dotenv(override=False)` 必须在 `config.py` /
> `api_client.py` 模块被导入（从而读取环境变量）之前执行。把导入上移到
> `load_dotenv` 之前会破坏环境变量加载顺序，属功能性回归。故选择显式抑制告警。

---

## 2. 改动清单

| # | 文件 | 变更类型 | 概要 |
|---|---|---|---|
| 1 | `docs/Task/Active/FIX_EXTERNAL_REVIEW_RISKS_PLAN.md` → `docs/Task/Archive/2026-06/FIX_EXTERNAL_REVIEW_RISKS_PLAN.md` | 移动 | 归档已完成任务（git mv） |
| 2 | `docs/Task/Active/FIX_EXTERNAL_REVIEW_RISKS_PLAN.md`（归档前就地改） | 改 | 状态行补「完成时间 2026-07-02」、Status 改 ✅ Completed |
| 3 | `docs/Task/README.md` | 改 | Active 段移除该行；Completed 2026-06 段新增一行 |
| 4 | `pyproject.toml` | 改 | dev 组加 `ruff>=0.6`；新增 `[tool.ruff]` / `[tool.ruff.lint.per-file-ignores]` 配置 |
| 5 | `.github/workflows/ci.yml` | 改 | `pytest` 步骤前新增 `uv run ruff check .` 步骤 |
| 6 | `uv.lock` | 重新生成 | `uv lock` 自动更新 |

> 不修改 `src/` 任何 `.py`（E402 用 ruff 配置抑制，不动源码）；
> 不修改 `tests/`（基线无告警）。

---

## 3. 验收标准

- `docs/Task/Active/` 不再包含 `FIX_EXTERNAL_REVIEW_RISKS_PLAN.md`；
  `docs/Task/Archive/2026-06/` 包含之；`README.md` 索引与之一致。
- `uv run ruff check .` 退出码 0（无告警）。
- `uv run pytest -q` 仍 114 passed, 3 deselected。
- `uv lock --locked` 通过（锁文件与 pyproject 一致）。
- CI yml 语法正确，lint 步骤在 test 之前。
- Provider 运行时行为零变化（未动 `src/*.py`）。

---

## 4. 风险评估与缓解

| 风险 | 等级 | 缓解 |
|---|---|---|
| E402 抑制过宽，掩盖未来真正的导入顺序问题 | 低 | 仅对 `server.py` 单文件抑制，并在配置中注释说明原因；其他文件仍执行 E402 |
| ruff 版本升级引入新规则致 CI 波动 | 低 | 不锁上限但 ruff 默认规则集稳定；必要时可后续固定 `ruff==` |
| 归档移动导致 git 历史断裂 | 极低 | 用 `git mv` 保留 rename 检测 |
| `uv lock` 重生成带入意外依赖变动 | 低 | 改动仅新增 dev 工具，`--locked` 验证可捕获漂移 |

---

## 5. 实施顺序

1. T1：就地更新待归档文档的状态字段 → `git mv` 到 Archive/2026-06/
2. T2：更新 `docs/Task/README.md` 索引
3. T3：`pyproject.toml` 加 ruff dev 依赖 + ruff 配置
4. T4：`uv lock` 重新生成锁文件
5. T5：`.github/workflows/ci.yml` 加 lint 步骤
6. T6：验证三件套（ruff / pytest / lock --locked）
7. 归档本任务文档 + 提交 Git commit

---

## 外部审核意见（Phase 0，requirement+plan 合并）

APPROVED (provider=coding-bridge, SessionId=166c73c4-3c37-4bd5-934c-811cf5130b11)

采纳的改进：
- 用 `uv add --dev "ruff>=0.6"` 替代手动编辑 + `uv lock`，避免依赖树整体升级。
- 归档前 `grep -r "FIX_EXTERNAL_REVIEW_RISKS_PLAN" docs/` 检查交叉引用。
- 提交前再跑全量 `uv run ruff check .`，确认纳入依赖后除 E402 外无新告警。

不采纳：
- lint 设为非阻塞（allow failure）——基线仅 3 个 E402 且为有意模式，抑制后即全绿，阻塞式才有约束力。
- 启动服务 smoke test——本次未动 src/*.py，无运行时变更面，单元测试已覆盖。

## 验收

- ✅ T1 归档：`FIX_EXTERNAL_REVIEW_RISKS_PLAN.md` 已 `git mv` 至 `Archive/2026-06/`，状态字段更新为 ✅ Completed (2026-07-02)。
- ✅ T2 索引：`docs/Task/README.md` Active 段移除旧条目，Completed 2026-06 段新增归档行。
- ✅ T3 ruff 依赖：`uv add --dev "ruff>=0.6"` → ruff 0.15.20 入 dev 组，依赖树无其他升级。
- ✅ T3 ruff 配置：`[tool.ruff]` + `per-file-ignores` 抑制 server.py 的 E402（有意模式）。
- ✅ T4 锁文件：`uv lock` 已重生成，`uv lock --locked` 无漂移。
- ✅ T5 CI：`.github/workflows/ci.yml` 在 `uv sync` 后、`pytest` 前新增 `uv run ruff check .` 步骤。
- ✅ 验证三件套：`ruff check .` All checks passed；`pytest -q` 114 passed 3 deselected；`uv lock --locked` 通过。
- ✅ 交叉引用：归档前 `grep` 确认仅 README 索引（已更新）+ 本计划自引用 + `.omc` 访问日志（历史快照，不动）。
- ✅ Provider 运行时行为零变化（未动 `src/*.py`）。

## 外部审核意见（Phase 4，code review）

APPROVED (provider=coding-bridge, SessionId=d4d35bde-aaf0-4536-a7a0-fad191519406)
无阻塞项。审查者建议的交叉引用检查已于归档前完成；扩展 ruff 规则集（isort/pyupgrade/bugbear）列为未来方向，本次不引入。

## 6. 备注

- 本次执行环境已挂载 `mcp__coding-bridge__*` 工具，按 CLAUDE.md 强制步骤执行
  外部审查（requirement + plan 合并为一次 review_plan，scope 小故合并）。
- 本任务自身完成后亦按规范归档至 `Archive/2026-07/`。
