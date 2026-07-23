# Task: 修复 test_volcengine_live.py 明文 API Key 泄漏

**Status**: ✅ Completed (completion time: 2026-06-30)
**Author**: Claude
**Scope**: 单文件安全 hotfix + 残留历史清理决策。

---

## 1. 事件事实

| 项 | 结论 |
|---|---|
| 明文 key 位置 | `tests/test_volcengine_live.py:86` |
| 泄漏值 | 一把火山方舟真实 Ark key（格式 `ark-<uuid>-<suffix>`，此处不复制明文） |
| 引入提交 | `0726c7a`（已推送 `origin/main`，GitHub 公开仓库，应视为已泄漏） |
| `.env` | 未被追踪，`.gitignore:37` 正确忽略，安全 |
| 其他硬编码 | grep 全仓扫描确认仅此一处 |

文件本身有 `_redact_secret()` 对 verbose 输出脱敏，但真正的明文 key 硬编码在源码——防住了日志泄露，没防住源码硬编码。

## 2. 修复目标

1. **移除源码中的明文 key**，改为从环境变量读取（`API_KEY` / `VOLCENGINE_API_KEY`）；
2. 无 key 时 `pytest.skip`，与该测试 opt-in 性质一致；
3. 加 `load_dotenv(override=False)` 兜底，使项目 `.env` 可用（与 `server.py` 行为一致，兑现 docstring 第 15-17 行的承诺）；
4. 不改测试的断言逻辑、verbose 脱敏逻辑、其他 provider。

## 3. 改动清单

| # | 文件 | 变更 |
|---|---|---|
| 1 | `tests/test_volcengine_live.py` | 加 `import os` + `from dotenv import load_dotenv`；`_build_volcsettings` 改为读环境变量 + skip |
| 2 | `docs/Task/Active/SECURITY_FIX_ARK_KEY_LEAK_PLAN.md` | 本文档（完成后归档） |
| 3 | `docs/Task/README.md` | 索引更新 |

> 不触碰 `providers.py` / `config.py` / `api_client.py` / `server.py`。

## 4. 残留风险（需用户决策）

1. **key 轮换（用户控制台操作，最紧急）**：删源码无法撤销已泄漏的历史，必须到火山方舟控制台吊销旧 key。
2. **git 历史重写（破坏性，需授权）**：`git filter-repo` 清理 `0726c7a` 起历史中的 key + force push。key 轮换后旧 key 已失效，此步主要价值是避免后续误用、保持仓库干净；是否做由用户定。

## 5. 验收

- 源码无明文 key（grep 该 key 前缀仅命中历史，不命中工作区文件）；
- `pytest -q` 默认套件全绿（live 测试被 deselect/skip，不产生费用）；
- `pytest -m volcengine_live` 在无环境 key 时 skip，有 key 时正常跑；
- `ruff check` 无新告警。

---

## 6. External Review Opinion（Code 审查，强制步骤）

- **review_id**：`60426a20-dcee-4031-81dc-b030b68f2dc2`
- **审查结论**：源码层面泄漏已修复；提 P0×2 / P1×2 / P2×3。

### 主助独立判断（含逐条核实）

| # | 审查意见 | 核实结果 | 处置 |
|---|---|---|---|
| P0#1 | .env 是否被 gitignore | ✅ `git check-ignore .env` 命中，第 37 行已忽略 | 无需处理 |
| P0#2 | _redact_secret 是否按值脱敏 | ✅ 按值脱敏（取传入 value 首4/尾4），非匹配固定串，动态 key 正确脱敏 | 无需处理 |
| P1#3 | grep 范围不足（仅 tests/src） | ✅ **命中真实问题**：本计划文档自身含明文 key（第14、45行） | **已修复**：移除两处明文，改为不复制明文 |
| P1#4 | load_dotenv 每次 fixture 调用 | live 测试单用例，无性能问题 | 不改（过度优化） |
| P2#5/6/7 | 命名 / pytest.skip 耦合 / 类型标注 | helper 仅此一处用，耦合可接受 | 不改 |

**结论**：审查 P0 两条经验证均不成立；P1#3 命中真实二次泄漏（系主助自身计划文档写入明文），已修复。其余 P2 为合理但不必要的优化。
