**状态**: ✅ Completed (完成时间: 2026-07-02; 开始时间: 2026-06-20)
> 对应 fullauto 状态：.omc/fullauto/fix-external-review-risks/state.json
> 归档说明：任务实质于 2026-06 完成（见下方验收段），2026-07-02 补办归档。

## 任务目标
按 coding-bridge 外部审查 (REJECTED) 优先级修复当前未提交改动中的 7 项风险。

## 问题分析
外部审查 SessionId=5bc3f62b-a184-4167-a5d0-3f2ffd61d138 返回 7 项风险：
- #1 Blocker: WS auth_url 泄露
- #2 High: SPARK_MODE 错误信息
- #3 High: DEFAULT_WS_URLS 硬编码 / SPARK 注释残留
- #4 Medium: configure_logging 幂等过窄
- #5 Medium: URL query 泄露
- #6 Low: LogRecord reserved 硬编码
- #7 Info: README 缺 LOG_LEVEL 文档

## 子任务列表
详见 .omc/fullauto/fix-external-review-risks/spec.md

## 每个子任务的改动内容
见 spec.md

## 预期效果和验收标准
- 全部 7 项风险修复或显式记录豁免理由
- pytest 全绿
- ruff check 无新增问题

## 风险评估和缓解措施
见 spec.md

## 实施顺序和依赖关系
T1 → T2 → T3 → T4 → T5 → T6 → T7

## 阶段 0 输出（spec）
- 路径：.omc/fullauto/fix-external-review-risks/spec.md

## 外部审核意见（Phase 0）
跳过（外部审查已对原始 diff 给出 REJECTED，spec 来自该审查）

## 实施计划
- 路径：.omc/plans/fullauto-fix-external-review-risks-impl.md

## Runtime Decisions
见 .omc/plans/fullauto-fix-external-review-risks-impl.md 的 ## Runtime Decisions 段

## 验收
- ✅ T1 (Blk) WS auth_url 防泄露：_safe_url() + 仅记录 exc_type
- ✅ T2 (High) SPARK_MODE 错误信息：改为 Unsupported API mode
- ✅ T3 (High) WS 注释清理：改为 "via api_url (provider profile)"
- ✅ T5 (Med) configure_logging 幂等改进：清除非 JSONFormatter handler
- ✅ T7 (Info) README 补充 LOG_LEVEL 文档
- ⏭️ T4 (.env.example)：经核查无 SPARK section 残留，豁免
- ⏭️ T6 (Low reserved 集合)：按 spec.md 决定记为 deferred

## 外部审核复审结果
- api_client.py → APPROVED (SessionId=5bc3f62b)
- logging_config.py → APPROVED (SessionId=5bc3f62b)
- README.md → self-checked（文档豁免）
- 测试: 14 passed in 0.49s