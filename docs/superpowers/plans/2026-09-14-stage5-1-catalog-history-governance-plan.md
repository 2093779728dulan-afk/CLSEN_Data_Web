# Stage 5.1 当前目录历史保护与必要修正实施计划 v1.1

> 最新交付状态（2026-09-14，候选10）：Stage5.1仍为`scope_closed / no_implementation_required`，无R1/R2新增代码项；候选09测试夹具已按既有`items/has_next`列表契约最小修正并冻结。获批准的候选10完整本地Collect在 canonical runner 启动即因 clean-SHA 保护拒绝223项 overlay，未执行 runner 门禁；随后独立 gate-run-10 同顺序预演完成 Windows smoke、Ubuntu-full、Frontend lint/typecheck/token/Vitest，并在浏览器首个失败处停止。`tests/e2e/product-detail.spec.ts:7` 的 `getByText("无报表")` strict-mode 同时匹配摘要文本与表格单元格，定向重跑复现；该问题不构成业务实现缺陷证据。Storybook、其余浏览器、生产构建、OpenAPI/产品基线、MySQL及正式验收未执行，候选10保持冻结；下一批需另行授权后仅修正测试选择器、定向验证并重新冻结，完整Collect仍须再次授权；V35历史证据不足、#9/#35既有确认及不提交/不部署边界均保持不变。

候选09清单：`D:/CLSEN_DeploymentPrep_20260914/evidence/candidate-overlay-manifest-09.json`；`candidate-source-09` 与 `gate-run-09` 按223项逐项复核无缺失、不匹配或删除项误存在。

候选10已完成最小测试夹具修正并冻结：`CatalogMaintenancePage.test.tsx` 与 `CatalogImportHistory.test.tsx` 定向测试2/2通过，目标 ESLint 通过。随后获批准的完整本地 Collect 在 canonical runner 的 clean-SHA 保护处停止，未执行 runner 门禁；独立 gate-run-10 同顺序预演在浏览器首个既有选择器失败处停止。清单：`D:/CLSEN_DeploymentPrep_20260914/evidence/candidate-overlay-manifest-10.json`，候选 source/gate 两副本按223项逐项无缺失、不匹配或删除项误存在。该测试夹具修正及选择器首因不属于R1/R2业务开发，Stage5.1保持`scope_closed / no_implementation_required`。

日期：2026-09-14。状态：`scope_closed / no_implementation_required`。发布范围与基线只读核对已完成，用户已确认当前无R1/R2新增代码项；部署准备中的候选05 mypy问题及候选06陈旧路由集合测试合同均已作为门禁缺口定向修正并冻结候选07。候选07/08/09完整本地Collect的历史结果按原记录保留；候选10完整本地Collect已获批准：canonical runner 因 clean-SHA 保护停止，未执行 runner 门禁；独立 gate-run-10 同顺序预演完成 Windows smoke 378项中376通过、2项平台允许跳过，Ubuntu-full的Ruff、399文件format、397源文件mypy及pytest执行范围通过，Frontend ESLint、TypeScript、设计 Token、Vitest 90文件/427项通过；浏览器在`tests/e2e/product-detail.spec.ts:7`的`getByText("无报表")` strict-mode 两元素冲突处停止，定向重跑复现。该首因不属于R1/R2业务缺陷。其余Frontend浏览器、Storybook、生产构建、OpenAPI/产品基线、MySQL及正式验收未执行；候选10失败后下一次完整Collect仍须单独授权。当前部署准备状态为`in_progress / candidate10_collect_failed / candidate10_runner_clean_sha_guard_blocked / windows_smoke_passed / ubuntu_full_passed / frontend_lint_passed / frontend_typecheck_passed / frontend_tokens_passed / frontend_unit_tests_passed / frontend_browser_failed / collect_stopped / collect_awaiting_new_authorization / targeted_experience_complete`。上述均不属于R1/R2业务开发。

**目标：** 用户能理解当前分析与历史快照的区别，并通过现有审核、批准和新目录版本完成必要纠错；历史记录、数据边界、权限和审计保持有效。

**技术路线：** 复用现有 FastAPI/Python、MySQL、React/TypeScript 和目录工作流。优先修改已有模块，不预建历史治理表、日期追溯解析器、结账状态机或新审批平台。

**执行方式：** 使用 writing-plans 组织完整使用路径和验证范围；按项目 AGENTS.md 内联实施，不继承通用技能的子代理、逐步审批、频繁提交或全量测试要求。

## 1. 与总主线和旧计划的关系

唯一顺序仍为：[发布范围与基线核对 → Stage 5.1必要修正 → Stage 5.2按实际规模收尾 → 部署准备 → Java/Python详细规划](2026-09-14-current-release-and-java-evolution-roadmap.md)。

- 发布范围与基线核对已完成；本计划直接复用其结果，不另开第二轮全项目盘点。
- 本文件原链接保留，正文升级为v1.1。旧A–D批次、D1–D8及拟新增模块完整保存在[原v1.0设计存档](2026-09-14-stage5-1-full-history-governance-v1-reference.md)，仅供延期需求追溯。
- 5.1不再等同于“完整历史治理系统”。下面的修正批次是缺口出现时的处理路径，不是默认新增功能清单；没有缺口可以不改代码。
- 计划优化不代表Stage5启动，也不改变Stage4、正式验收或整合状态。未来授权实施已选范围后，普通修正按路径连续完成，不逐步骤重复索要批准。

## 2. 基线与本轮已核实事实

业务位置：`D:/CLSEN_Data_Web/.worktrees/stage4-1-app-shell`，本轮读取分支为 `codex/stage4-1-app-shell`、HEAD为 `ec0a72e`。现有未提交成果必须保留；HEAD不能单独标识全部体验代码。主工作区文档为权威，本轮业务工作树根目录未发现独立AGENTS.md。

以下仅为代码/测试源码存在性核对，未运行测试，不能据此宣称当前行为全部通过：

| 已见能力 | 读取依据（路径相对业务工作树） | 对本计划的影响 |
|---|---|---|
| 两种事实口径及历史权限检查 | `backend/app/api/style_analytics.py` 的 `_fact_parameters`，接受 `current/catalog_snapshot`；快照要求目录版本，检查历史读取权限。 | 不新增同义查询参数，不改旧参数含义；需要时修复现有调用与显示。 |
| 快照结构与错误类型 | `backend/app/catalog/snapshots.py` 的 `FrozenCatalogExportPayload`、`CatalogSnapshotUnavailable`、`CatalogSnapshotError`。 | 优先沿用已有事实引用和错误，不用空结果掩盖不可重现。 |
| 现有批准与向前生成版本的恢复入口 | `backend/app/catalog/service.py` 的 `approve_import/restore_version`；`backend/tests/integration/test_catalog_approval.py` 包含对应测试。 | 不是从零建设版本恢复；已有恢复也不等同于按日期追溯的补偿引擎。 |
| 单商品修改、分类快照及幂等的目标测试 | 同一 `test_catalog_approval.py` 中 `test_single_style_change_is_isolated_idempotent_and_snapshots_category`。 | 优先复用既有草稿与批准能力，不再创建另一套商品编辑流程。 |
| 用户可见版本、风险与事实来源 | `CatalogVersionsPage.tsx`、`CatalogWorkflowActions.tsx`、`ProductDetailPage.tsx`（各在catalog/products功能目录）。 | 已有版本列表、风险预览和事实口径说明；只处理核实的问题，不重复设计页面。 |

Stage4与真实数据试用确认范围继续以[计划索引](../../workflow/project-plan-index.md)为准：45组当前为44组确认，#9分类管理最终UI及#35销售贡献/退货关注均已在候选02由用户确认通过；#40材料继续纳入候选10，候选10同顺序预演在浏览器首因停止，尚未到达Storybook构建。V35批准前全量mapping/exclusion快照证据不足仍未验证，正式 `release_validation = not_started`。本轮未访问历史体验入口、真实数据或业务数据库。

## 3. 入选规则与范围台账

从发布范围核对中，只取与当前目录查询、批准、纠错和历史保护有关的条目。每项在现有索引/开发流程记录：业务触发、实际表现与期望、相关版本/证据、影响模块、处置及理由、开发/体验/验收状态。不另建审批系统或独立证据台账。

| 处置 | 判断依据 | 后续动作 |
|---|---|---|
| 复用已有能力 | 已有实现覆盖当前发布需要，且无新的相反证据。 | 引用适用的已有证据，不重做、不为状态消息重测。 |
| 纳入必要修正 | 存在当前业务路径的明确问题，例如历史/当前混称、拒绝后仍显示旧结果、目录批准覆盖无关内容。 | 先最小复现，再选下方R1或R2；这些例子是判断标准，不是本轮已发现缺陷。 |
| 证据不足待评估 | 无法确认历史状态或现有证据不覆盖目标版本。 | 说明“未知”，判断是否影响当前承诺；不虚构缺陷，不用新测试倒推历史。 |
| 延期 | 新业务语义、完整治理平台或未来规模需求，未证明是当前发布必需。 | 保留原因及后续阶段；不默认实施。 |

核对及确认结论：现有记录没有确认“查询表达与一致性”或“既有纠错与版本保护”的当前缺陷，用户已确认R1/R2均不选入本轮实施，Stage5.1按范围收尾。V35沿用原证据不足状态，不能用新测试倒推历史，也不属于R1/R2修复；分类树、销售贡献/退货关注的候选体验已在候选02确认并继续保留，Storybook材料已同步进入候选10但构建待门禁，均不塞入5.1。候选08的Frontend TypeScript首项已定位为`MergeDecisionMatrix.test.tsx`可空`reason`测试合同问题；候选09完整Collect的Vitest首因已按既有`items/has_next`列表契约最小修正；候选10完整Collect的浏览器首因进一步定位为`tests/e2e/product-detail.spec.ts:7`选择器同时命中摘要文本与表格单元格，现有证据不支持业务缺陷判断。上述不证明R1/R2或其他业务缺陷，也不改变本计划范围。

## 4. 必须保持的业务合同

1. **当前与历史分开解释。** 沿用现有事实口径、目录版本、日期及退货口径合同；当前结果随合法新发布/新目录变化，不冒充当时历史结果。历史快照不混入最新报告。未知参数、缺必要版本、越权和不支持组合保持明确错误。
2. **失败与零值分开。** 缺快照、范围不覆盖或完整性错误不能显示为“0件、无异常”。复用现有错误码及页面状态；若是否允许部分结果尚无合同，先明确受影响场景，不擅自改为部分成功。
3. **纠错沿用新版本。** 先选现有单商品修改或目录审核批准路径；保留旧事实和旧目录的业务内容。需要恢复时核实已有restore的实际影响范围，不能把整版本恢复伪装成单SKU撤销，也不能直接回写旧表恢复状态。
4. **同一基线才比较。** 对比须固定站点、账号/来源、日期、币种、事实成员和目录版本。仅归属变化时原始报表总计不变；映射/忽略变化要解释商品统计变化，不能称为原始销量变化。新报告发布造成的事实变化单独注明。
5. **服务端保护保留。** 沿用既有角色、风险等级、幂等、expected revision、预览有效性及审计；不把新旧审批策略混用，不默认新增禁止自批规则，也不弱化已有规则。拒绝或冲突不能留下半成品批准。
6. **日常纠错不承诺日期追溯。** 新目录对当前查询的影响按既有合同解释；本期不新增“从某日生效”输入，不将批准时刻当成业务生效日。

以上是目标约束，不代表本轮已验证全部合同。

## 5. 批次安排

### 入口：复用发布范围核对结果

输入：主线第1项产出的实际代码基线、发布功能范围、对应确认及待办。

- [x] 只核对相关模块与证据，把条目按第3节分类；已有结果直接引用。
- [x] R1/R2当前均无可由现有证据确认的修正项；未证实问题不预设文件、迁移或测试。
- [x] 未发现当前发布必须新增的业务语义；旧D1–D8继续延期。
- [x] 结果已写回现有计划索引和开发流程，说明可复用能力、体验/材料项、证据不足及延期理由。

退出：5.1实际范围明确。核对无必要代码改动时可直接提交范围收尾结论，用户确认后记录无需新增实施；不编造 `development_complete` 或新的 `user_verified` 证据。此入口不运行完整测试、不改业务数据。

当前退出状态：用户已确认“无R1/R2新增代码项”，上述退出条件已满足；记录为 `scope_closed / no_implementation_required`，不是 `development_complete`。未来明确缺陷需作为新授权事项重新进入R1或R2。

### R1：查询口径与结果解释修正（仅有缺口时）

**使用路径：** 商品分析/详情 → 查看事实口径与目录 → 通过已有入口查看支持的历史范围 → 返回原上下文；不可重现时看到明确原因。

**优先修改位置：** 后端 `api/style_analytics.py`、`analytics/style_service.py` 及实际定位的查询模块；前端 `features/products/ProductLedgerPage.tsx`、`ProductDetailPage.tsx`，必要时 `features/catalog/CatalogVersionsPage.tsx`。以上不是必须全部修改的文件清单。

- [ ] 用一个问题场景固定预期，例如缺快照时显示明确错误而非零，或返回后保留原口径；先确认问题确实存在。
- [ ] 修复对应解析、查询、错误映射或页面状态，保持旧API合同。已有版本/覆盖信息足够时只修展示，不为“完整溯源字段”扩充整套响应。
- [ ] 若改动跨表格、趋势、详情或分页，确保受影响页面使用同一响应基线；不新增全局版本锁系统。
- [ ] 集中完成一轮目标检查，交付受影响路径。无新UI的纯后端保护按相关调用路径说明验证方式，不专门建演示页。

**体验步骤（将来交付时填写已核实入口及账号）：**

1. 查看指定虚构日期范围的商品分析，能识别当前口径及目录。
2. 通过已有功能打开支持的历史视图，核对显示版本与范围。
3. 用预置的缺证据或越权样例查看明确拒绝；不显示成完整零结果。
4. 返回原页面，日期、口径及已有筛选按原产品合同保留。

仅本批改动触及的步骤需要重新体验；既有已确认路径不全量重开。仅修错误提示时不扩成新增历史切换入口。

### R2：既有纠错与目录版本保护修正（仅有缺口时）

**使用路径：** 当前商品/待处理 → 现有修改或审核 → 风险预览与批准 → 新目录回执 → 查看当前结果及旧版本记录。

**优先修改位置：** `backend/app/catalog/service.py`、`import_repository.py`、`snapshots.py` 或定位到的单商品变更模块；前端 `CatalogStylePage.tsx`、`CatalogWorkflowActions.tsx`、`CatalogVersionsPage.tsx`。仅沿实际调用链修改，不预建 `history_*` 或 `period_close` 模块。

- [ ] 明确影响范围：单商品纠错、批量目录修改或已有整版本恢复。先沿既有路径处理，不将一个缺陷升级为通用追溯治理。
- [ ] 如修改批准/快照写入，保留原目录mapping/exclusion及相关快照业务内容、无关商品和其他账号数据；沿用原事务、审计及冲突检查。
- [ ] 如修改预览/回执，基线过期或批准冲突后提示重新预览；成功后刷新版本和当前结果；结果未知沿用已有回执查询/幂等重放，不盲目生成第二版本。
- [ ] 只有写入范围受到改动时，才用本轮隔离样例在操作前保存完整的受测目录mapping/exclusion业务内容摘要，并在操作后对比。此证据只证明新操作，不能证明V35原历史状态。

**体验步骤（将来交付时准备任务自有虚构数据）：**

1. 打开虚构商品甲，进入现有纠错路径，看到当前目录基线。
2. 提交允许的变更，查看范围和风险；默认沿用现有预览内容，不承诺新增金额影响计算器。
3. 用实际具备权限的账号批准，看到新的目录版本与回执。
4. 核对当前结果符合变更、旧目录业务内容未改、无关商品乙保留。
5. 仅若改动涉及冲突/权限，体验预置的失效预览或越权场景，确认被明确拦截且无额外版本。

R1与R2没有强制依赖，也不要求为了凑批次分别实现。若同一缺陷横跨查询和批准，合为一条完整路径，集中验证一次；没有对应缺陷的批次不启动。

## 6. 定向验证选择表

下列均为本轮确认存在的源码入口，**不是必跑清单或已通过结果**。实施时先选择对应风险的节点，再按需扩到受影响文件；不为了计划完整性新增一套测试目录。

| 改动风险 | 优先复用的既有目标（相对业务工作树） |
|---|---|
| 参数解析、历史权限及安全错误映射 | `backend/tests/unit/test_style_analytics_api.py`：`test_invalid_ledger_parameters_use_stable_analytics_errors`、`test_viewer_catalog_snapshot_is_forbidden_before_repository_access`、`test_repository_errors_have_safe_stable_http_mapping`，只选相关节点。 |
| 快照冻结/持久化被改动 | `backend/tests/integration/test_catalog_snapshot_consistency.py::test_rr_payload_cannot_mix_pointer_changes_and_write_persists_exact_payload`，另补真实缺陷未覆盖的最小断言。 |
| 批准保护或单商品变更被改动 | `backend/tests/integration/test_catalog_approval.py` 中 `test_projection_expiry_and_high_risk_require_admin` 或 `test_single_style_change_is_isolated_idempotent_and_snapshots_category`。已有整版本restore受影响时才选同文件 `test_restore_creates_forward_version_with_target_ready_fact_tuple`。 |
| 目录发布竞争被改动 | `backend/tests/integration/test_catalog_concurrency.py::test_two_approvals_with_same_catalog_counter_have_one_cas_winner`。 |
| 页面交互、错误清理及刷新 | 对应的 `ProductLedgerPage.test.tsx`、`ProductDetailPage.test.tsx`、`CatalogWorkflowActions.test.tsx`、`CatalogVersionsPage.test.tsx` 或 `CatalogStylePage.test.tsx`，只选受影响组件；纯文案/样式通常仅定向diff及必要显示检查。 |

运行规则：

- 使用目标业务工作树内的 `scripts/run-dev-check.ps1 -Kind Backend/Frontend -Targets`；脚本以自身位置确定仓库根目录，不能拿主工作区脚本验证另一工作树并误报结果。
- 该快检的后端入口只接unit/contracts；MySQL集成用目标工作树 `scripts/test-mysql-matrix.ps1 -DevelopmentTests` 指定实际节点。实施前核对该工作树脚本参数、目标文件及已有运行时，避免旧脚本合同与主工作区不同。
- 普通检查约3分钟、单MySQL约10分钟；必要的权限/并发验证超预算时说明理由，不跳过，也不自动扩大到双版本矩阵。
- 仅复现已确认缺陷、关键合同缺口或实质风险时补有价值的测试；不能把“已有测试文件”当成本轮验证通过。
- 完整回归、双MySQL、E2E、性能、无障碍/视觉、备份恢复及部署演练等正式门禁全部留部署准备，本期目标检查不替代它们。

## 7. 延期需求与 Java 边界

| 旧方案 | 本期处置 | 后续位置 |
|---|---|---|
| D1–D3：完整修正范围、生效区间、跨期退货适用日 | 保持既有归属/日期合同；不新增日期追溯模型。 | Java阶段按实际追溯需求重评。 |
| D4：第三种“修正后结果”、治理版本 | 保持现有两种事实口径；只修已定位的不一致。 | 部署准备后的详细规划。 |
| D5–D6：结账、重开、跨入口冻结、下期调整 | 不在Python建设财务账期平台。 | Java核心业务规划。 |
| D7：新的提案/批准分工 | 当前继续执行现有权限和风险策略；只修缺陷，不自行扩大角色职责。 | 新治理业务启动时再定；当前必要权限修复不延期。 |
| D8：按日期区间补偿、重叠修正引擎 | 复用既有新目录版本及已有恢复能力，不将恢复包装成精确单项撤销。 | Java治理需求确定后设计。 |

延期不等于废弃，更不代表已批准未来实施。原方案细节保留在存档；本期不安装Spring相关依赖、不拆微服务、不引入Java/Python双写或为未来迁移全仓重构。

## 8. 交付、数据边界与收尾

- 仅在相关批次明确启动后改业务代码；默认使用隔离虚构样例。真实数据范围和操作授权不外推，禁止读取/枚举 `data/`、擅自迁移或连接业务库；本计划不改变现有体验环境。
- 开发完成记录 `development_complete`；实核入口、版本、完整登录名获取方式、数据和权限前置齐备后才记 `ready_for_user_review`；只有用户明确确认该版本才记 `user_verified`。不在计划中写死历史端口或捏造测试账号。
- 用户反馈更新同一事项，修正后只复查受影响路径；已有完整确认不失效，除非新改动确实影响它。开发和体验状态分开记录于[计划索引](../../workflow/project-plan-index.md)及[开发流程](../../operations/development-workflow.md)。
- V35保留证据不足；若发布需要依赖无法重现的历史结果，应在发布范围/验收中明确限制与处理，不把用户允许本轮收尾解释为正式发布接受风险。
- 5.1收尾需：已选必要项完成或明确处置、适用体验获得确认、延期项与剩余发布门禁列明。无需新增项时提供依据让用户确认范围收尾；不假称新功能已验收。随后按主线指令进入5.2，不自动整合、push、merge、迁移或部署。

## 9. 下一任务口令

候选10已冻结并完成测试夹具定向修正；Stage5.1不重新开启，下一次完整 Collect 仍需再次授权。

> Stage5.1当前无R1/R2新增代码项已由用户确认，范围已收尾；V35保持历史证据不足，A–D/D1–D8继续延期。候选07/08/09完整本地Collect历史结果按原记录保留，不证明或新增R1/R2业务缺陷，不重新开启Stage5.1。候选10完整Collect获授权后，canonical runner因clean-SHA保护停止，独立同顺序预演完成Windows smoke、Ubuntu-full、Frontend ESLint/TypeScript/Token/Vitest，并在`tests/e2e/product-detail.spec.ts:7`的`getByText("无报表")` strict-mode两元素冲突处停止，定向重跑复现；该问题是既有测试选择器合同问题，不构成业务缺陷证据。Storybook及其他后续门禁未执行；下一批仅在另行授权后修正该测试选择器、运行受影响浏览器节点并重新冻结候选，之后完整Collect仍须再次授权；#9/#35两条候选体验确认继续保留。若未来出现明确当前缺陷，再按新授权选择R1或R2。

本次范围核对实际使用 `verification-before-completion`，用于交付前核实文档状态、范围清单、链接、格式及工作树边界；此前writing-plans用于收敛实施范围及交付边界。Stage5.1为`scope_closed / no_implementation_required`，不是`development_complete`，也不因部署准备材料修正而重新开启。
