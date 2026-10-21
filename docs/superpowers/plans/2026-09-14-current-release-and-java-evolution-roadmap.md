# 当前版本交付与 Java/Python 演进主线 v1.0

日期：2026-09-14。依据：用户确定 Java 核心方向，并要求重新规划当前计划。本文替代旧计划的执行顺序与默认范围，保留历史设计、验收和体验记录；同日已完成第1项发布范围与基线只读核对，不启动功能实施。

**目标：** 先完成当前报表与商品主档系统的必要收尾和部署准备，再详细规划 Java ERP 核心与 Python 数据能力的逐步演进。

**执行方式：** 当前代理内联执行；使用 writing-plans 组织范围与依赖，按项目 AGENTS.md 覆盖通用技能中的子代理、逐步审批、自动提交和全量测试要求。

## 1. 当前所在位置

- Stage 4 开发和本轮真实数据体验收尾完成，`development_complete / user_verified` 仅覆盖已确认版本、样例与路径；45组当前为44组确认，#9分类管理最终UI及#35销售贡献/退货关注均已在候选02由用户确认通过；#40材料已纳入候选10但构建待门禁。
- `release_validation = not_started`；尚未正式 accepted、整合或部署。V35 批准前全量 mapping/exclusion 快照证据不足仍未验证，不是已发现丢失，也不能由新样例倒推证明。
- 本轮核对主工作区 `codex/development-throughput / 7de0ee6`，业务工作树 `.worktrees/stage4-1-app-shell` 为 `codex/stage4-1-app-shell / ec0a72e`。已交付业务成果包含未提交修改，HEAD 本身不是完整交付版本；下一任务须刷新目标路径与状态。
- 候选09历史状态（候选10已覆盖）：候选08首项 Frontend TypeScript 的可空`reason`测试合同已做最小类型收窄；候选09完整本地 Collect 按授权执行至 Frontend Vitest 首因，相关 Windows/Ubuntu/Frontend 已通过范围及`CatalogMaintenancePage.test.tsx`夹具错误详见下方历史记录。该夹具已在候选10按既有`items/has_next`列表契约最小修正；不构成业务实现缺陷证据。
- 候选09清单为 `D:/CLSEN_DeploymentPrep_20260914/evidence/candidate-overlay-manifest-09.json`；两个冻结副本均按223项逐项复核无缺失、不匹配或删除项误存在。
- 候选10最新状态：候选09测试夹具已按既有`items/has_next`列表契约最小修正并冻结。获批准的完整本地 Collect 在 canonical runner 启动即因 clean-SHA 保护拒绝223项 overlay，退出码1，未执行 runner 门禁；未绕过保护，随后在独立 gate-run-10 副本按同顺序预演。Windows smoke 378项中376通过、2项平台允许跳过；Ubuntu-full 的 Ruff、399文件 format、397源文件 mypy、pytest 1242项通过/2项允许跳过；Frontend ESLint、TypeScript、设计 Token、Vitest 90文件/427项通过。浏览器首个失败为 `tests/e2e/product-detail.spec.ts:7` 的 `getByText("无报表")` strict-mode 两元素冲突，定向重跑复现；该问题只证明既有测试选择器合同不够精确，不构成业务实现缺陷证据。Storybook、其余浏览器、生产构建、OpenAPI/产品基线、MySQL及后续门禁未执行；下一次完整 Collect 仍须再次授权。正式 `release_validation` 保持 `not_started`，#9/#35既有体验确认不重开。清单为 `D:/CLSEN_DeploymentPrep_20260914/evidence/candidate-overlay-manifest-10.json`，两个冻结副本223项逐项无缺失、不匹配或删除项误存在；Stage5.1/5.2不重新开启。
- 当前位于 **部署准备进行中**。第1项“当前发布范围与基线核对”已完成；用户已确认Stage5.1无R1/R2新增代码项、Stage5.2不启动预设重构，两阶段未实施业务代码并按范围收尾。候选07/08/09的历史门禁结果按原记录保留；候选10完整本地Collect获批准后 canonical runner 因 clean-SHA 保护停止，未执行 runner 门禁，独立 gate-run-10 同顺序预演完成 Windows smoke、Ubuntu-full、Frontend lint/typecheck/token/Vitest，并在 `tests/e2e/product-detail.spec.ts:7` 的 `getByText("无报表")` strict-mode 两元素冲突处停止，定向重跑复现。该首因是既有测试选择器合同问题，不支持业务实现缺陷判断。候选10清单为`D:/CLSEN_DeploymentPrep_20260914/evidence/candidate-overlay-manifest-10.json`，两个冻结副本223项逐项复核无缺失、不匹配或删除项误存在。Storybook、其余浏览器、生产构建、OpenAPI/产品基线、MySQL、远端正式门禁和实际上线仍未执行；下一批仅在另行授权后修正该测试选择器、定向验证并重新冻结候选，完整Collect仍需再次授权；#9/#35体验确认继续保留，不重开Stage5.1/5.2。

## 2. 唯一执行顺序

| 顺序 | 阶段与状态 | 本阶段交付 | 进入下一阶段的条件 |
|---|---|---|---|
| 1 | 当前发布范围与基线核对：`complete`（只读核对） | 计划索引已列明实际业务工作树、未提交/未跟踪成果、3组部分确认、V35证据边界及发布影响。 | 已满足；未运行测试、未提交或整合。 |
| 2 | Stage 5.1 当前目录历史保护与必要修正：`scope_closed / no_implementation_required` | 用户确认当前无R1/R2新增代码项；V35保留为历史证据不足，不用代码或新测试倒推修复。 | 已按当前范围收尾；未来出现明确当前缺陷才另行选择R1/R2。 |
| 3 | Stage 5.2 当前规模适配与必要收尾：`scope_closed / no_implementation_required` | 用户确认不启动预设重构；当前无已确认加载、分页、导出或维护规模代码缺口。 | 已按当前范围收尾；完整性能门禁仍在部署准备。 |
| 4 | 部署准备：`in_progress / candidate10_collect_failed / candidate10_runner_clean_sha_guard_blocked / windows_smoke_passed / ubuntu_full_passed / frontend_lint_passed / frontend_typecheck_passed / frontend_tokens_passed / frontend_unit_tests_passed / frontend_browser_failed / collect_stopped / collect_awaiting_new_authorization / targeted_experience_complete` | 候选07/08/09历史分段结果保留；候选10 canonical runner 因 clean-SHA 保护未执行 runner 门禁，独立 gate-run-10 同顺序预演完成 Windows smoke 376/378通过、2项允许跳过，Ubuntu-full静态检查及pytest执行范围通过，Frontend ESLint、TypeScript、设计 Token、Vitest 90文件/427项通过，浏览器首个失败为`tests/e2e/product-detail.spec.ts:7`的`getByText("无报表")` strict-mode 两元素冲突。候选10双副本223项逐项0不一致；#9/#35体验确认继续保留。 | 该失败只证明既有测试选择器合同不够精确，不支持业务实现缺陷判断；canonical runner clean-SHA 合同未绕过。其余浏览器、Storybook、生产构建、OpenAPI/产品基线、MySQL、远端正式门禁和实际上线仍未执行。 | 阻塞候选10本地 Collect 继续和正式`release_validation`，但不撤销#9/#35体验确认，不启动Stage5.1/5.2，也不认定业务功能失败。 | 下一批需另行授权后仅修正该测试选择器、运行受影响浏览器节点并重新冻结候选；随后完整Collect仍需再次授权。提交/整合/push/迁移/部署继续单独授权。 | 部署准备 |
| 5 | Java/Python 演进详细规划：`deferred_until_deployment_preparation_complete` | 明确首个 ERP 闭环、领域与数据归属、Java 模块化单体方案、迁移顺序、切换/回退合同和未来拆分条件。 | 用户确定首批业务范围并授权后，才创建 Java 实施任务。详细规划不要求实际生产上线已经发生。 |

## 3. Stage 5.1 的新边界

当前合同优先复用：历史目录保持不可变；当前事实和历史快照不能混称；缺证据不能显示成完整结果或假零；目录批准和纠错保持权限、账号/站点隔离、版本冲突及审计。

第1项核对已读取业务工作树对应模块与已有记录，未为状态查询重跑测试。结果未发现现有证据能够确认的R1/R2业务缺陷；既有正常目录候选、审核、批准及增量维护路径继续使用，不建立第二套治理状态机。V35证据不足不作为代码缺陷处理。

| 原5.1设计 | 新安排 | 纳入条件 |
|---|---|---|
| A 生效日期与影响预览 | 完整日期追溯模型延期；现有批准路径必要的影响说明可纳入5.1。 | 当前用户场景确需补充，明确影响基线与边界后按最小范围实施。 |
| B 审批与结账冻结 | 保留现有权限、冲突、审计的必要修复；新结账/重开/跨入口冻结延期到Java阶段重新设计。 | 不在Python提前建设财务账期或通用审批平台。 |
| C 三种查询口径 | 保持现有 `current/catalog_snapshot` 合同；新增 `corrected` 和治理版本暂不实施。 | 如当前显示混淆或结果不一致则修复；新增口径需明确业务需要后另行决定。 |
| D 前向撤销 | 保留旧目录不可变和现有纠错安全；新增治理补偿引擎延期。 | 当前纠错缺陷单独处理，不用整库回滚覆盖其他修改。 |

[Stage 5.1实施计划v1.1](2026-09-14-stage5-1-catalog-history-governance-plan.md)已按本节边界重写：复用发布范围核对结果，仅按实际缺口选择R1查询口径修正、R2既有纠错保护，无缺口不新增代码。[原完整治理设计存档](2026-09-14-stage5-1-full-history-governance-v1-reference.md)只作延期参考；D1–D8不再是全部上线前置问题。只有选入当前范围的变更实际依赖某项语义时才决定，未来Java设计需重新验证旧方案，不能直接视为已批准需求。

## 4. Stage 5.2 的新边界

- 先确定本次发布支持的数据量、并发角色/任务量与XLSX大小范围，再判断现有实现是否满足；不能凭未来ERP规模直接宣称现有系统有瓶颈或已经足够。
- 候选子表化、游标分页、流式XLSX、组件/Repository拆分由“默认全部实施”改为“有当前问题证据才选择”。已有有效测量优先复用；开发期只做必要的局部测量，完整性能验收仍在部署准备。
- 限制可以作为明确产品边界，但必须告知用户并获得范围确认，不能静默截断数据、漏页、少导出或降低原有一致性合同。
- 不预装Spring、Redis、消息队列、注册中心、Kubernetes或对象存储。若当前版本有独立且必要的基础设施需求，说明证据与成本后单独定范围。

## 5. 现在固定的架构约束

这是后续方向及今后改动的约束，不代表当前代码已完成解耦，也不要求为它启动全仓重构。

| 领域 | 目标责任与边界 |
|---|---|
| Java/Spring | 后续ERP核心：库存、采购、销售、财务、业务权限和工作流；优先模块化单体，具体Spring组件及版本在部署准备后选择。 |
| Python | 报表、分析、AI、清洗、脚本、自动化与外部连接适配；涉及库存/财务等核心状态变更，未来通过核心领域接口提交，不能绕过业务规则直写。 |
| React/TypeScript | 继续复用当前UI体系，按稳定业务API对接后端；不因Java迁移重写前端。 |
| 数据与身份 | 领域逐项指定唯一写入责任方。迁移前现有Python模块继续负责；切换后Java负责，Python通过API、事件或受控只读投影消费。禁止两端无约束双写业务表。 |
| 权限与契约 | 当前权限检查继续有效；未来统一身份、领域授权及服务间身份需明确方案，不以先建设通用权限平台为当前发布前置。保持业务ID、账号/站点隔离、金额精度、版本与审计语义清晰。 |
| 微服务 | 在业务边界稳定、独立发布/扩容或团队分工产生实际需求后评估拆分；微服务不是支持复杂数据的先决条件。 |

部署准备后，先选一个有业务价值的ERP闭环，再设计Java/Python接口、数据迁移核对、幂等和切换回退；需要可靠异步通信时再选择事件投递/重试方案。当前不预定服务数量、不建空服务、不提前锁定数据库拆分。

生产/供应链、11A、11B、图片资产/PIM、独立订单指标、净利润等原暂停或未授权方向继续保留；进入Java规划不等于这些模块自动全部启动。

## 6. 验证与剩余事项

- 普通开发集中完成一个使用路径后做一轮最小充分验证，保留受影响权限、并发、数据一致性和关键接口检查；数据库仅任务自有可抛弃MySQL。用户体验只复查受改动影响的路径。
- 完整回归、双版本MySQL、完整E2E、无障碍/视觉、性能、备份恢复与部署演练等约定门禁仍在部署准备执行，不能因未来迁移Java而省略。
- 部署准备开始时冻结实际候选及环境；当前未提交成果需先按用户授权形成可识别的整合候选。旧SHA证据按现有合同使用，不能冒充新候选正式验收。
- V35缺失的历史证据继续列明。新建前后快照只能证明新的操作；若发布场景依赖无法重现的历史事实，必须明确限制或补足可信证据，不能以“用户允许本轮收尾”替代发布风险结论。
- 45组清单中的3组部分确认、Storybook材料同步及专项未覆盖项在发布范围核对中逐项处置。保留已有确认，不全部重开，也不自动豁免确实影响本次发布的事项。
- 数据授权范围不扩展；不读取/枚举 `data/`，不连接业务数据库、不改变真实体验环境。提交、push、merge、迁移和部署均不由本次规划触发。

## 7. 下一任务执行口令

> Stage5.1无R1/R2新增代码项、Stage5.2不启动预设重构已由用户确认并按范围收尾。部署准备当前为`in_progress / candidate10_collect_failed / candidate10_runner_clean_sha_guard_blocked / windows_smoke_passed / ubuntu_full_passed / frontend_lint_passed / frontend_typecheck_passed / frontend_tokens_passed / frontend_unit_tests_passed / frontend_browser_failed / collect_stopped / collect_awaiting_new_authorization / targeted_experience_complete`：候选07/08/09历史结果按原记录保留；候选10 canonical runner 未绕过 clean-SHA 保护，独立 gate-run-10 同顺序预演完成 Windows smoke 376/378通过、2项允许跳过，Ubuntu-full静态检查及pytest执行范围通过，Frontend ESLint、TypeScript、设计 Token、Vitest 90文件/427项通过；浏览器在`tests/e2e/product-detail.spec.ts:7`因`getByText("无报表")` strict-mode 两元素冲突首个失败，定向重跑复现。该问题是既有测试选择器合同问题，不构成业务实现缺陷；候选10清单为`D:/CLSEN_DeploymentPrep_20260914/evidence/candidate-overlay-manifest-10.json`，双副本223项逐项复核无缺失、不匹配或删除项误存在。其余浏览器、Storybook、生产构建、OpenAPI/产品基线、MySQL及后续门禁仍需分别授权；下一批仅修正该测试选择器并运行受影响浏览器节点后重新冻结候选，完整Collect仍需再次授权。#9/#35体验确认继续保留，V35继续作为证据不足的发布声明限制/残余风险；不得重开44组未受影响的已确认体验，也不得把本地候选冒充需要远端master来源身份的正式门禁。

> 候选10已覆盖上述候选09阶段状态：定向测试/ESLint通过并冻结；本次完整本地 Collect 获批准后 canonical runner 因 clean-SHA 保护停止，独立同顺序预演在浏览器首个选择器失败处停止。当前状态为`candidate10_collect_failed / candidate10_runner_clean_sha_guard_blocked / frontend_browser_failed / collect_stopped`；不绕过保护，不认定业务缺陷。下一批仅在另行授权后修正该选择器、运行受影响浏览器节点并重新冻结候选，之后完整 Collect、Storybook、MySQL及其余门禁仍需分别授权；#9/#35不重开，Stage5.1/5.2不重新开启。

本次范围核对实际使用 `verification-before-completion`，用于交付前核实文档状态、范围清单、链接、格式及工作树边界；此前writing-plans用于主线重排和旧计划范围映射。只读核对完成不等于Stage 5开发、候选冻结或部署准备已启动。
