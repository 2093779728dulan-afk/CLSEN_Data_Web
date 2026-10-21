# 项目计划与进度索引

> 共机部署资料（2026-09-14）：用户已确定Data_Web与Alpha共用Hostinger VPS，服务器规格、短时监测、Traefik/DNS及整机备份限制已写入[Hostinger共机部署参考](../operations/hostinger-shared-vps-deployment-reference.md)。来源为用户提供的核验结果，本任务未连接服务器；Data_Web域名、资源配额、独立MySQL备份及恢复方案待确定。仅资料准备完成，不代表服务器或应用发布验收通过，不改变下方候选状态。

> 最新候选状态（2026-09-15，候选20）：用户已批准并完成一次完整本地Collect预演。Ubuntu-full、Windows smoke、Frontend静态/单测、Playwright 14/14及Storybook静态构建通过；Storybook a11y为22通过、1失败，唯一失败是390px `narrow-and-long-chinese`节点的`Axe is already running`，按首因停止。定向诊断确认`@storybook/addon-a11y`自动`axe.run()`与外部`AxeBuilder.analyze()`存在偶发生命周期竞争，不是已发现的业务UI或可访问性违规。候选20保持冻结，未生成候选21，`release_validation = not_started`，#9/#35体验确认不重开。

> 当前部署准备以`candidate20_collect_failed / ubuntu_full_passed / windows_smoke_passed / frontend_unit_and_browser_passed / storybook_build_passed / storybook_a11y_failed / storybook_a11y_root_cause_confirmed / collect_stopped / fix_awaiting_new_authorization / canonical_clean_sha_prerequisite_unresolved / release_validation_not_started / targeted_experience_complete`为准。定向复现5/5通过；候选外生命周期探针10轮为5次通过、5次同型竞争失败，通过轮均为0项serious/critical。该诊断不等于修复或完整Collect通过。

> 候选20清单为 `D:/CLSEN_DeploymentPrep_20260914/evidence/candidate-overlay-manifest-20.json`；source/gate双副本按232项清单复核均无缺失、不匹配、删除项误存在、额外项或遗漏项，测试容器已清理。候选仍是 `ec0a72e` 加未提交overlay，不满足canonical runner的clean-SHA合同；若直接以相同表示方式启动canonical runner，仍会被相同保护阻断。本地预演不能记为正式门禁；#9/#35体验不重开，Stage5.1/5.2不重新开启。

## 当前统一状态（2026-09-14，覆盖下方旧状态）

“当前发布范围与基线核对”已完成，状态为 `complete`（只读代码、文档和既有证据核对及计划同步，不是业务开发、测试或发布验收）。Stage 4 仍为 `development_complete / user_verified`，仅限已确认版本、样例和路径；45组当前为44组已确认，#9分类管理最终UI及#35销售贡献/退货关注均已在候选02由用户确认通过。#40材料已纳入候选20且Storybook静态构建通过，但本轮a11y门禁因测试生命周期竞争停止，视觉及后续门禁未执行。`release_validation = not_started`，不得标记 `accepted`。

实际业务成果仍位于 `D:/CLSEN_Data_Web/.worktrees/stage4-1-app-shell`，分支 `codex/stage4-1-app-shell`、HEAD `ec0a72e` 加未提交修改；HEAD不能标识完整交付。与本轮遗留直接相关的分类维护、产品总表代码为已修改文件，`CatalogCategoryEditor.*`、`LedgerMetricHelp.stories.tsx`、`ProductTrendChart.stories.tsx` 和 `ProductTrendChart.reference.md` 为未跟踪文件。后续候选冻结必须显式纳入应交付文件，不能只按HEAD或已跟踪diff整合。

用户已确认Stage5.1无R1/R2新增代码项、Stage5.2不启动预设重构；两阶段均记为 `scope_closed / no_implementation_required`，未实施业务代码、未产生新的development_complete或user_verified。V35历史证据不足继续保留。部署准备当前为 `in_progress / candidate20_collect_failed / storybook_a11y_root_cause_confirmed / fix_awaiting_new_authorization / canonical_clean_sha_prerequisite_unresolved / targeted_experience_complete`。本次诊断未修改候选、业务代码、数据、依赖或体验环境；#9/#35既有用户确认继续保留，正式`release_validation`仍为`not_started`。

### 2026-09-14 当前发布范围与基线核对清单

### 2026-09-15 候选20 Storybook a11y首因定向诊断

- 在与Collect相同的Ubuntu 24.04.4、Node 24.18.1、pnpm 11.16.0及固定Playwright镜像中，只运行390px `design-system-selection-and-navigation--narrow-and-long-chinese`节点；原测试连续5次通过。该结果说明失败并非故事单独运行时稳定发生，也不能覆盖候选20完整Collect中的失败。
- 候选外生命周期探针仍只打开同一故事并执行同一WCAG标签扫描，10轮中5轮通过且serious/critical均为0，5轮在`AxeBuilder.analyze()`处复现同一`Axe is already running`。失败轮在扫描前观察到`window.axe`尚不存在，随后出现约十余毫秒的`_running=true -> false`转换，证明竞争发生在故事渲染完成与外部扫描启动之间。
- 只读实现证据显示项目`.storybook/preview.ts`设置`a11y.test = "todo"`，addon默认`globals.a11y.manual = false`；锁定的`@storybook/addon-a11y 10.6.0`在preview `afterEach`中调用自身队列包装的`axe.run()`，而`tests/storybook/a11y.spec.ts`另行调用`AxeBuilder.analyze()`。addon队列不包含外部扫描，因此两者可对同一iframe并发运行。
- 首因类别确定为Storybook a11y测试执行合同/生命周期竞争，不是候选20唯一后端夹具变化引入，也没有产生业务UI缺陷、serious/critical违规、数据异常或数据丢失证据。该问题仍阻塞候选20的a11y门禁及后续发布准备。
- 候选20保持冻结且未生成候选21。下一批需另行授权后，才可在测试/Storybook配置范围内消除自动扫描与外部扫描的双重运行，保持WCAG标签、serious/critical断言和故事覆盖不变；随后只运行原失败节点、目标静态检查并冻结下一候选。不得用重试、跳过、删除断言或降低标准掩盖竞争，也不得自动重跑完整Collect。
- 诊断日志及10份生命周期JSON位于`D:/CLSEN_DeploymentPrep_20260914/candidate20-a11y-diagnosis`。首次容器包装在测试前因PowerShell提前解释Bash命令替换且缺少一次性目录而退出，不计为候选失败；修正外部包装后仅执行上述目标。实际Skill：`systematic-debugging`用于复现和追踪双扫描生命周期，`verification-before-completion`用于限定结论范围。

### 2026-09-15 候选20完整本地Collect结果

- 用户明确授权候选20执行一次完整本地Collect。运行前`candidate-source-20`与`gate-run-20`按232项manifest复核均为`missing=0 / mismatch=0 / deleted_present=0 / extras=0 / omitted=0`；内容身份仍为`ec0a72e907cf7787536cf73964f7897485e28c97+overlay-sha256:0a292f4e6dcf1731f161f494d98a9bea595d7780569147d43b6237e2a8b6e6c2`，manifest SHA-256仍为`fa3db8fd56677c42ed6beb42c5c4e40c02c58732c1e19bcac6fbb88fe39d7bf9`。
- Ubuntu-full通过Ruff、399文件format、397源文件mypy及pytest执行范围（1242通过、2跳过、352排除）；Windows smoke为376通过、2跳过。Frontend通过496项供应链策略、ESLint、TypeScript、Token、Vitest 90文件/427项、Playwright 14/14和Storybook静态构建。
- Storybook a11y运行23项，22通过、1失败；唯一失败为390px `narrow-and-long-chinese`节点的`Axe is already running`，未输出serious/critical WCAG违规，失败附件中的页面结构正常。候选19/20的a11y测试、Storybook配置、package及lockfile哈希相同；候选20相对候选19唯一内容变化仍是后端`test_schema_compatibility.py`夹具，因此现有证据不支持候选20业务UI回归。
- 按首因停止，未执行Storybook visual 27项、`legacy_parser`/`p0_catalog`双生产构建、MySQL 8.0/8.4、generated-contract、性能、恢复、部署及其余release-only门禁。日志位于`D:/CLSEN_DeploymentPrep_20260914/candidate20-collect-logs`；本地同顺序预演不构成正式`release_validation`。
- 候选20保持冻结，未生成候选21，不自动修复或循环Collect；canonical clean-SHA前置仍未解决，形成clean SHA、整合/push、正式门禁及部署继续分别授权。

### 2026-09-15 候选20 schema newer测试夹具同步与冻结

- 授权范围内只修改`backend/tests/integration/test_schema_compatibility.py`一行：将`newer`参数的revision由`0024`改为`0029`，使其确实高于当前`CURRENT_SCHEMA_REVISION = "0028"`并继续满足四位ASCII数字合同；`REVISION_NEWER`期望、其他四个参数、生产分类函数、迁移、业务代码及依赖均未改变。
- 目标Ruff lint通过；首次format检查只发现补丁行换行符与原文件CRLF不一致，单文件机械格式化后diff仍为1增1删，最终lint及format检查均通过。
- 正确suite的正式MySQL开发入口使用随机可抛弃Oracle MySQL 8.0容器，将隔离库升级到0028后选择整个`test_mysql_revision_shape_refuses`参数化用例，结果5通过、5排除、耗时0.41秒，矩阵退出0；原`newer`节点及zero/multiple/older/unknown四个相邻合同均通过。首次误选`mysql-legacy`在容器启动前被allowlist拒绝，未执行测试或改变环境，不计为候选测试失败；两次日志保留于`D:/CLSEN_DeploymentPrep_20260914/candidate20-targeted`。
- 候选20仍基于`ec0a72e907cf7787536cf73964f7897485e28c97`，含146个修改、81个未跟踪、5个删除，共232项；内容身份为`ec0a72e907cf7787536cf73964f7897485e28c97+overlay-sha256:0a292f4e6dcf1731f161f494d98a9bea595d7780569147d43b6237e2a8b6e6c2`。清单`D:/CLSEN_DeploymentPrep_20260914/evidence/candidate-overlay-manifest-20.json`的SHA-256为`fa3db8fd56677c42ed6beb42c5c4e40c02c58732c1e19bcac6fbb88fe39d7bf9`。
- `candidate-source-20`与`gate-run-20`均为detached HEAD `ec0a72e`；按232项复核均为`missing=0 / mismatch=0 / deleted_present=0 / extras=0 / omitted=0`。候选19/20文件数组仅目标测试文件一项不同；候选19及其Collect日志保持不变，测试容器已清理。
- 下一步只在再次明确授权后启动候选20完整本地Collect，从头按既定顺序并首因停止。候选仍不满足canonical clean-SHA合同；不得把定向验证或本地预演记为正式`release_validation`，形成clean SHA、整合/push、正式门禁及部署继续分别授权。

### 2026-09-15 候选19完整本地Collect结果

- 用户明确授权候选19执行一次完整本地Collect。运行前`candidate-source-19`与`gate-run-19`按231项manifest复核均为`missing=0 / mismatch=0 / deleted_present=0 / extras=0 / omitted=0`，重算overlay SHA-256仍为`8b3fdeb92b48d495912282d5d766154f1b03ed46747b3f71495e0622fabe048d`，manifest SHA-256仍为`5045c7b71ce7ad088566ed162ead8ba2227919154769c830a201416eb78ded2c`，双副本HEAD均为`ec0a72e907cf7787536cf73964f7897485e28c97`。
- Ubuntu-full通过：Ruff lint、399文件format、397源文件mypy通过；pytest为1242通过、2项平台允许跳过、352项排除。Windows smoke为376通过、2项平台允许跳过。
- Frontend锁定环境为Ubuntu 24.04.4、Node 24.18.1、pnpm 11.16.0及固定Playwright镜像digest`sha256:dcc5531e97840b9b5e794f2814476b21571c5124a3fca2267d73041f56e7580e`。496项供应链策略、ESLint、TypeScript、Token、Vitest 90文件/427项、Playwright 14/14、Storybook构建、a11y 23/23、visual 27/27及`legacy_parser`/`p0_catalog`两种生产构建均通过。
- MySQL 8.0迁移组30/30通过、耗时2806.77秒。兼容性组257项中256通过、1失败、1条非阻塞pytest warning，耗时2279.84秒；唯一失败为`backend/tests/integration/test_schema_compatibility.py::test_mysql_revision_shape_refuses[newer]`。
- 失败测试仍写死`("0024", REVISION_NEWER, "0024")`，而`CURRENT_SCHEMA_REVISION`已为`0028`；生产分类函数对四位数字revision按数值比较，故`0024`实际返回`REVISION_OLDER`。该测试文件及`schema_revision.py`在候选18/19哈希分别一致，且失败测试不是候选19 overlay改动项。现有证据支持迁移头推进后测试夹具未同步，不支持业务实现缺陷、当前数据库损坏或数据丢失结论。
- 按首因停止，未运行MySQL 8.4、generated-contract、两版本性能、UI性能、admin worker E2E、备份恢复、部署验证及其余release-only门禁。可抛弃MySQL容器已清理；日志位于`D:/CLSEN_DeploymentPrep_20260914/candidate19-collect-logs`。候选19保持冻结，未生成候选20，未修改业务代码、数据、依赖或体验环境。
- 下一批最小范围须另行授权：只同步上述`newer`参数夹具，使其使用确实高于`0028`且保持四位数字revision合同的值；运行原失败MySQL 8.0节点、该参数化用例必要相邻节点及目标Ruff，通过后再冻结下一候选。不得自动重跑完整Collect；clean SHA、整合/push、正式门禁及部署继续分别授权。

### 2026-09-15 候选19 0025 downgrade密封约束恢复与冻结

- 授权范围承接候选18已确认首因，只修改`backend/alembic/versions/0025_catalog_categories_and_style_changes.py`的downgrade：为`product_catalog_versions`、`product_catalog_publication_events`及`catalog_exports`三条由0025改写、降级时须恢复0022密封状态的CHECK约束显式使用`_ascii`字符串字面量。允许值、upgrade、0022 seal、测试、依赖、业务代码及体验环境均未改变。
- TDD红态沿用候选18两个节点的独立复现。首次绿色运行只修正最早的product versions约束，测试已越过该表后在publication events同类seal不匹配处停止，证明同一根因覆盖0025改写的三条ASCII代码字段约束；随后在同一文件、同一downgrade中补齐其余两条，避免逐项试错或放宽保护。
- 最终新鲜验证：正式MySQL开发测试入口在随机可抛弃Oracle MySQL 8.0容器中只选择两个原失败节点，结果2/2通过、1项排除、耗时29.76秒，矩阵退出码0；目标文件Ruff lint与format检查退出码均为0。首次绿色失败日志与最终通过日志均保留于`D:/CLSEN_DeploymentPrep_20260914/candidate19-targeted`，不冒充完整Collect。
- 候选19仍基于`ec0a72e907cf7787536cf73964f7897485e28c97`，含145个修改、81个未跟踪、5个删除，共231项；内容身份为`ec0a72e907cf7787536cf73964f7897485e28c97+overlay-sha256:8b3fdeb92b48d495912282d5d766154f1b03ed46747b3f71495e0622fabe048d`。清单`D:/CLSEN_DeploymentPrep_20260914/evidence/candidate-overlay-manifest-19.json`的SHA-256为`5045c7b71ce7ad088566ed162ead8ba2227919154769c830a201416eb78ded2c`。
- 候选18/19清单逐项比较只有上述0025迁移文件内容变化。`candidate-source-19`与`gate-run-19`均为detached HEAD `ec0a72e`；按231项复核均为`missing=0 / mismatch=0 / deleted_present=0 / extras=0 / omitted=0`。候选18、其Collect日志及诊断证据保持不变。
- 下一步仅在再次明确授权后启动候选19完整本地Collect，并从头按既定顺序、首因停止。候选仍不满足canonical runner clean-SHA合同；形成clean SHA、整合/push、正式门禁及部署继续分别授权，本地预演不得记为正式`release_validation`。

### 2026-09-15 候选18 MySQL 8.0首因定向诊断

- 按用户授权，只选择`test_catalog_partial_migration_recreates_only_the_missing_suffix`与`test_catalog_partial_migration_rejects_a_mutated_sealed_table`两个节点，并为避免首项失败污染第二项而分别使用独立随机可抛弃Oracle MySQL 8.0容器。两次均为1项选中、2项排除，并稳定在`product_catalog_versions sealed signature`处失败；容器均由正式矩阵脚本清理。
- 候选外探针`D:/CLSEN_DeploymentPrep_20260914/candidate18-targeted-diagnosis/catalog_schema_probe.py`只监听`product_catalog_versions`的目标约束及seal DDL，按0022签名算法记录table comment、schema digest、约束与索引表示。原始0022稳定状态为comment/digest同为`bb5684fd6afc1d231ceebd1bfc948919b212fc691e424376851999bbd82e611c`，workbook约束表示含`_ascii'product_catalog_workbook_v1'`。
- 0025 upgrade把约束扩为v1/v2；0025 downgrade随后虽恢复同名、同业务表达式的v1约束，但MySQL记录为`_utf8mb4'product_catalog_workbook_v1'`。降级后列数量与原始0022一致、索引表示完全一致，约束表示不一致，当前schema digest变为`36d99eaa72425f15d136a4b71420e6007593b23db8f399418065889610591466`，而table comment仍保留原0022 digest，故0022部分恢复保护按设计拒绝。
- 首因类别已确定：`0025_catalog_categories_and_style_changes.py`的downgrade未精确恢复0022被seal的物理schema，是迁移downgrade实现缺口，不是两个测试的恢复合同缺口。该缺口阻塞当前发布门禁，必须在发布前处理；它只在降级/部分恢复路径中被证实，不证明正常forward upgrade失败、当前业务数据损坏或数据丢失，也不是候选18唯一新增`test_migrations.py`改动引入。
- 候选18内容与manifest保持不变；用户随后授权继续，该建议已按上方候选19记录实施。候选18本身及其证据未改写，候选19完整Collect仍须再次授权。

### 2026-09-15 候选18完整本地Collect结果

- 用户明确授权冻结候选18执行一次完整本地Collect。候选仍为`ec0a72e907cf7787536cf73964f7897485e28c97`加231项overlay，canonical clean-SHA前置未满足且未绕过；本轮在`gate-run-18`及Ubuntu 24.04锁定Frontend容器按既定顺序执行本地预演，日志根为`D:/CLSEN_DeploymentPrep_20260914/candidate18-collect-logs`，不能记为正式`release_validation`。
- Ubuntu-full通过：Ruff lint、399文件format、397源文件mypy通过；pytest 1242通过、2项平台允许跳过、352项排除。Windows smoke为376项通过、2项平台允许跳过。
- Frontend有效完整日志为`03c-frontend-full-ubuntu.log`：Ubuntu 24.04.4、Node 24.18.1、pnpm 11.16.0，固定镜像digest为`sha256:dcc5531e97840b9b5e794f2814476b21571c5124a3fca2267d73041f56e7580e`；496项供应链策略、ESLint、TypeScript、Token、Vitest 90文件/427项、Playwright 14/14、Storybook构建、a11y 23/23、visual 27/27及`legacy_parser`/`p0_catalog`两种生产构建均通过。前两份Frontend日志分别因外部包装未提供pnpm shim、以及误用不存在的`build-storybook`脚本并遗漏runner环境变量而停止；对照canonical runner语义修正外部包装后，完整Frontend段从头执行并通过，前两次不记为候选功能失败或正式门禁证据。
- MySQL 8.0迁移组30/30通过，耗时2810.33秒，候选17的旧head合同失败已解除。其余兼容性组收集257项，结果215通过、2失败、40错误，耗时1813.18秒并退出1。最早两项失败为`test_catalog_partial_migration_recreates_only_the_missing_suffix`和`test_catalog_partial_migration_rejects_a_mutated_sealed_table`；第一项从head降到0022、删除后缀表并把版本改回0021后，再升级0022时因`product_catalog_versions sealed signature`被拒，其finally恢复head也失败，之后第二项及40项fixture错误均遇到相同状态，故40项为级联而非40个独立缺陷。
- 只读代码证据显示：0022 seal把列、约束、索引签名写入table comment，并在部分恢复时要求comment等于当前签名；0025 upgrade/downgrade都会删除并重建`ck_product_catalog_versions_workbook`。现有证据因此把首因集中到0025 downgrade后的0022 seal一致性/恢复合同，但尚不足以区分迁移downgrade实现缺口与测试恢复合同缺口，不授权直接放宽0022 seal或断言。相关三个文件在候选14–18哈希一致，候选17/18唯一内容变化仍是`test_migrations.py`的head常量和历史序列，因此不支持把本次失败归因于候选18新增改动；测试使用随机可抛弃MySQL 8.0数据库，不构成业务数据丢失证据。
- 按首因停止，MySQL 8.4、generated-contract、MySQL 8.0/8.4性能、UI性能、admin worker E2E、备份恢复、部署验证及其余release-only门禁未执行。测试容器已清理；manifest SHA-256仍为`01abd0082ebbab155106ecac6ac4457ca2b2e3890dfe563cef534d8063af8208`，overlay SHA-256仍为`98c79ee657e685929bdbdc7ceba0af257839f7f33626826c4a9eef796b006878`，source/gate双副本HEAD均为`ec0a72e`且231项复核均为`missing=0 / mismatch=0 / deleted_present=0 / extras=0 / omitted=0`。候选18保持冻结，不生成候选19。
- 下一批须另行授权：只定向复现上述两个`test_catalog_schema.py`节点，并在随机可抛弃MySQL 8.0库采集0025 downgrade前后`product_catalog_versions`的table comment、schema digest及约束表示，确认责任属于迁移downgrade实现还是测试恢复合同；确认首因后再决定最小修正及定向验证。不得直接放宽seal、删除/跳过断言或自动循环完整Collect；形成clean SHA、整合/push、正式门禁及部署继续分别授权。

### 2026-09-15 候选18迁移测试合同同步与冻结

- 授权范围内仅修改`backend/tests/integration/test_migrations.py`：`_HEAD_REVISION`从`0027`更新为`0028`，并在`test_each_historical_revision_upgrades_in_order`的`0025`后显式补入`0026`、`0027`；未修改迁移实现、业务代码、依赖、体验环境或其他测试合同。
- 新鲜定向验证：用项目MySQL开发测试入口和随机可抛弃Oracle MySQL 8.0容器，只选择3个候选17原失败节点及历史序列节点，结果4/4通过、26项未选中，耗时672.74秒，脚本退出码0；目标文件Ruff lint和format检查通过。该结果解除已定位的测试合同阻塞，不代表候选18完整Collect或正式`release_validation`通过。
- 候选18基于`ec0a72e907cf7787536cf73964f7897485e28c97`，含145个修改、81个未跟踪、5个删除，共231项；内容身份为`ec0a72e907cf7787536cf73964f7897485e28c97+overlay-sha256:98c79ee657e685929bdbdc7ceba0af257839f7f33626826c4a9eef796b006878`。清单`D:/CLSEN_DeploymentPrep_20260914/evidence/candidate-overlay-manifest-18.json`的SHA-256为`01abd0082ebbab155106ecac6ac4457ca2b2e3890dfe563cef534d8063af8208`。
- 候选17/18清单逐项比较只有`backend/tests/integration/test_migrations.py`内容变化。`candidate-source-18`与`gate-run-18`均为detached HEAD `ec0a72e`；按231项复核均为`missing=0 / mismatch=0 / deleted_present=0 / extras=0 / omitted=0`，实际分类均为145个修改、81个未跟踪和5个删除。候选17及其Collect日志保持不变。
- 下一步仅在再次明确授权后启动候选18完整本地Collect，并从头按既定顺序、首因停止。候选仍不满足canonical runner的clean-SHA合同；形成干净提交SHA、整合/push、远端正式门禁及部署继续分别授权，本地预演不得记为正式`release_validation`。

### 2026-09-15 候选17完整本地Collect结果

- 用户明确授权冻结候选17执行一次完整本地Collect。候选仍为`ec0a72e907cf7787536cf73964f7897485e28c97`加231项overlay，canonical clean-SHA前置未满足且未绕过；本轮在`gate-run-17`和Ubuntu 24.04锁定Frontend容器按既定顺序执行本地预演，日志根为`D:/CLSEN_DeploymentPrep_20260914/candidate17-collect-logs`，不能记为正式`release_validation`。
- Ubuntu-full通过：Ruff lint、399文件format、397源文件mypy通过；pytest 1242通过、2项平台允许跳过、352项排除。Windows smoke为376项通过、2项平台允许跳过。
- Frontend锁定环境为官方Playwright镜像digest `sha256:dcc5531e97840b9b5e794f2814476b21571c5124a3fca2267d73041f56e7580e`，实测Ubuntu 24.04.4、Node 24.18.1、pnpm 11.16.0；496项供应链策略、ESLint、TypeScript、Token、Vitest 90文件/427项、Playwright 14项、Storybook静态构建、可访问性23项、视觉27项及`legacy_parser`/`p0_catalog`两种生产构建均通过。
- MySQL 8.0在可抛弃随机Oracle MySQL容器中运行迁移测试，27项通过、3项失败，耗时2802.30秒。三个失败分别为`test_empty_database_upgrades_to_head_idempotently`、`test_stage_four_downgrade_rejects_lossy_failed_attempt_before_ddl`和`test_stage_four_successful_attempt_type_roundtrips_through_baseline`；三处断言均为实际head `0028`、测试常量`_HEAD_REVISION = "0027"`。日志显示升级、降级及最终恢复实际到达0028，迁移文件又明确`revision = "0028" / down_revision = "0027"`。候选14–17的`test_migrations.py`及`0028_category_hierarchy.py`哈希分别一致；当前证据是既有迁移测试合同未同步，不构成0028迁移失败、业务功能缺陷或数据丢失证据。
- 同文件`test_each_historical_revision_upgrades_in_order`的显式序列目前列到0025后直接使用旧HEAD，未逐步覆盖0026/0027。按MySQL 8.0首因停止，MySQL 8.4及全部release-only门禁未执行；没有自动修正或重跑。
- 停止后候选17 manifest SHA-256仍为`a0856a0f53d9ef8874763ae2cc9dcc0edef79b5136418ef0abe229d95b2346fa`，overlay SHA-256仍为`765e94e7f1f4e3e5b9cd007c396ad8a9c40dd252789621eb1113abc2492a43bd`；`candidate-source-17`与`gate-run-17`按231项复核均为`missing=0 / mismatch=0 / deleted_present=0 / extras=0 / omitted=0`，两者HEAD均为`ec0a72e`，且无活动测试容器。候选17继续冻结，不生成候选18。
- 下一批最小范围须另行授权：仅在`backend/tests/integration/test_migrations.py`将`_HEAD_REVISION`同步为`0028`，并按“逐个历史版本升级”的原测试意图在序列中补入`0026`、`0027`；运行上述3个原失败节点、历史序列相邻节点及该文件目标Ruff，通过后冻结候选18。候选18完整Collect仍须再次授权；形成干净提交SHA、整合/push、远端正式门禁及部署继续分别授权。

### 2026-09-15 候选17合并决定测试同步与冻结

- 仅将`MergeDecisionMatrix.test.tsx:41`的`expect(onStateChange.mock.calls.at(-1)?.[0].ready).toBe(true)`包入既有`waitFor`；`ready=true`期望、预填依据、操作人/行来源断言及本文件其余断言保持不变，未修改业务组件、API、样式、依赖、批准基线或体验环境。
- 新鲜定向验证：原失败Vitest节点1/1通过、同文件4项按节点过滤跳过；目标文件ESLint退出码0。未运行其余Vitest、Playwright、Storybook、生产构建、MySQL或完整Collect。
- 候选17仍基于`ec0a72e907cf7787536cf73964f7897485e28c97`，含145个修改、81个未跟踪、5个删除，共231项；内容身份为`ec0a72e907cf7787536cf73964f7897485e28c97+overlay-sha256:765e94e7f1f4e3e5b9cd007c396ad8a9c40dd252789621eb1113abc2492a43bd`。清单`D:/CLSEN_DeploymentPrep_20260914/evidence/candidate-overlay-manifest-17.json`的SHA-256为`a0856a0f53d9ef8874763ae2cc9dcc0edef79b5136418ef0abe229d95b2346fa`。
- 冻结时保留候选16已纳入的12项主工作区计划/流程材料；候选16/17清单文件项逐项比较只有`frontend/src/features/import-review/MergeDecisionMatrix.test.tsx`一项内容变化。`candidate-source-17`与`gate-run-17`均为独立detached worktree、HEAD `ec0a72e`；按231项清单核对均为`missing=0 / mismatch=0 / deleted_present=0 / extras=0 / omitted=0`，实际分类仍为145个修改、81个未跟踪和5个删除。候选16及其Collect日志保持不变。
- 下一步仅在再次明确授权后启动候选17完整本地Collect，并从头按既定顺序、首因停止。候选仍不满足canonical runner的clean-SHA合同；形成干净提交SHA、整合/push、远端正式门禁及部署继续分别授权，本地预演不得记为正式`release_validation`。

### 2026-09-15 候选16完整本地Collect结果

- 用户明确授权冻结候选16执行一次完整本地Collect。候选仍为`ec0a72e907cf7787536cf73964f7897485e28c97`加231项overlay，canonical clean-SHA前置未满足且未绕过；本轮在`gate-run-16`及锁定Frontend容器按既定顺序执行本地预演，日志根为`D:/CLSEN_DeploymentPrep_20260914/candidate16-collect-logs`，不能记为正式`release_validation`。
- Ubuntu-full范围通过：Ruff lint、399文件format、397源文件mypy通过；pytest 1242通过、2项平台允许跳过、352项排除。Windows smoke为376项通过、2项平台允许跳过。
- Frontend使用官方Playwright镜像digest `sha256:dcc5531e97840b9b5e794f2814476b21571c5124a3fca2267d73041f56e7580e`，实测Ubuntu 24.04.4、Node 24.18.1、pnpm 11.16.0；冻结依赖安装通过496项供应链策略，ESLint、TypeScript及Token通过。
- Vitest在89/90文件、426/427项通过后停止。首因是`MergeDecisionMatrix.test.tsx:41`在DOM已显示预填依据后立即读取`onStateChange.mock.calls.at(-1)`，期望`ready=true`、实际为`false`。组件在fetch完成后分步更新报告类型、冲突和草稿，`ready`由后续render计算并通过effect通知；等待DOM文本不保证通知effect已经执行。同一测试后半段已有对该回调使用`waitFor`的先例。候选15/16的`MergeDecisionMatrix.test.tsx`、`MergeDecisionMatrix.tsx`及`auditReason.ts`哈希分别一致，候选15完整Vitest曾427/427通过；停止后原失败节点定向重跑1/1通过、4项过滤跳过。现有证据指向既有Vitest异步同步缺口，不支持业务实现缺陷结论；定向重跑不覆盖完整轮失败。
- 按Vitest首因停止。Playwright、Storybook静态构建/可访问性/视觉、两种生产构建、MySQL 8.0/8.4及后续release-only门禁均未执行。首次Frontend容器挂载参数预检在任何候选门禁前退出，日志单独保留；修正外部包装并完成只读挂载预检后才开始上述唯一一次Frontend门禁，该包装失败不计为候选测试失败。
- 停止后manifest SHA-256仍为`e4220e0ddaaa6c84577eea819fffd6f09dc44a2f0b3e6e53c3e3c54af35a631c`，overlay SHA-256仍为`b1022898577c97bff8614cf121ddee4f40d240deac5f358ba7b2d41e8b3affe6`；`candidate-source-16`与`gate-run-16`按231项复核均为`missing=0 / mismatch=0 / deleted_present=0 / extras=0 / omitted=0`，两者HEAD均为`ec0a72e`，实际分类为145个修改、81个未跟踪和5个删除。候选16继续冻结，不生成候选17。
- 下一批最小范围须另行授权：仅将`MergeDecisionMatrix.test.tsx:41`现有`ready=true`断言包入`waitFor`，保持期望值和其余断言不变；运行原失败Vitest节点及目标ESLint，通过后再冻结候选17。候选17完整Collect仍须再次授权；形成干净提交SHA、整合/push、远端正式门禁及部署继续分别授权。

### 2026-09-15 候选16批量审核E2E同步与冻结

- 仅将`batch-review.spec.ts:156`的`expect(fixture.acceptedAdvanceRequests).toBe(6)`改为`await expect.poll(() => fixture.acceptedAdvanceRequests).toBe(6)`；期望值6、并发上限3、零发布写入及其余体验断言保持不变，未修改业务组件、API、样式、依赖、批准基线或体验环境。
- 新鲜定向验证：原失败Playwright节点1/1通过；目标文件ESLint退出码0。未运行其余Playwright、Vitest、Storybook、生产构建、MySQL或完整Collect。
- 候选16仍基于`ec0a72e907cf7787536cf73964f7897485e28c97`，含145个修改、81个未跟踪、5个删除，共231项；内容身份为`ec0a72e907cf7787536cf73964f7897485e28c97+overlay-sha256:b1022898577c97bff8614cf121ddee4f40d240deac5f358ba7b2d41e8b3affe6`。清单`D:/CLSEN_DeploymentPrep_20260914/evidence/candidate-overlay-manifest-16.json`的SHA-256为`e4220e0ddaaa6c84577eea819fffd6f09dc44a2f0b3e6e53c3e3c54af35a631c`。
- `candidate-source-16`与`gate-run-16`均为独立detached worktree、HEAD `ec0a72e`；按231项清单核对均为`missing=0 / mismatch=0 / deleted_present=0 / extras=0 / omitted=0`，实际分类为145个修改、81个未跟踪和5个删除，且无`data/`状态项。候选15及其Collect日志保持不变。
- 下一步仅在再次明确授权后启动候选16完整本地Collect，并从头按既定顺序、首因停止。候选仍不满足canonical runner的clean-SHA合同；形成干净提交SHA、整合/push、远端正式门禁及部署继续分别授权，本地预演不得记为正式`release_validation`。

### 2026-09-15 候选15完整本地Collect结果

- 用户明确授权冻结候选15执行一次完整本地Collect。候选仍为`ec0a72e907cf7787536cf73964f7897485e28c97`加230项overlay，canonical clean-SHA前置未满足且未绕过；本轮在`gate-run-15`及锁定Frontend容器按既定顺序执行本地预演，日志根为`D:/CLSEN_DeploymentPrep_20260914/candidate15-collect-logs`，不能记为正式`release_validation`。
- Ubuntu-full范围通过：Ruff lint、399文件format、397源文件mypy通过；pytest 1242通过、2项平台允许跳过、352项排除。Windows smoke为376项通过、2项平台允许跳过。
- Frontend使用官方Playwright镜像digest `sha256:dcc5531e97840b9b5e794f2814476b21571c5124a3fca2267d73041f56e7580e`，实测Ubuntu 24.04.4、Node 24.18.1、pnpm 11.16.0、Chromium 151.0.7922.34；冻结依赖安装通过496项供应链策略，ESLint、TypeScript、Token及Vitest 90文件/427项通过。
- Playwright为13项通过、1项失败。首因是`batch-review.spec.ts:156`在“重试”后立即断言`acceptedAdvanceRequests === 6`，实际读到5。trace显示初次5个选中项均已被夹具接受；暂停/刷新取消了浏览器侧第4、5项响应，但夹具完成处理。重试第4项的请求随后成功，失败文案消失；然而已有3项待发布使“查看全部待发布草稿”链接此前已可见，测试据此继续时，重试项尚未再次发出`advance`，所以计数仍为5。候选12–15的该E2E、执行器、页面/API及进度表文件SHA-256逐项一致；候选12曾通过，停止后在当前Node 24.18.1/Chromium环境定向重跑该节点1/1通过。现有证据确认测试缺少异步同步点，不支持候选15业务实现缺陷结论；该定向重跑不覆盖完整轮失败。
- 按Playwright首因停止。Storybook静态构建/可访问性/27项视觉、两种生产构建、MySQL 8.0/8.4及后续release-only门禁均未执行；不复用候选12历史结果冒充本轮通过。
- 下一批最小范围须另行授权：仅把`batch-review.spec.ts:156`现有计数断言改为等待第6次已接受推进请求（保持期望值6及其余断言不变），运行原失败Playwright节点及目标ESLint，若通过再冻结候选16。不得修改业务执行器、删除/降低断言或用固定等待掩盖时序；候选16完整Collect仍须再次授权。

### 2026-09-15 候选15目录入口测试夹具同步与冻结

- 仅在`App.test.tsx`现有共享fetch夹具中新增`/api/catalog/imports?`分支，返回既有空列表合同`{ items: [], has_next: false }`。未修改测试断言、`CatalogImportHistory`业务组件、API、样式、依赖、批准基线或体验环境。
- 新鲜定向验证：原失败的`catalog data manager can open the real maintenance controls`与4个参数化`catalog viewer cannot enter management deep link`相邻权限入口共5/5通过，同文件其余34项因节点过滤跳过；目标文件ESLint退出码0。未运行完整Vitest、Playwright、Storybook、生产构建、MySQL或完整Collect。
- 候选15仍基于`ec0a72e907cf7787536cf73964f7897485e28c97`，含144个修改、81个未跟踪、5个删除，共230项；内容身份为`ec0a72e907cf7787536cf73964f7897485e28c97+overlay-sha256:30b61ee33d35b8b0ee9386ccfb5490a5442c27c5302231eec7408da0655bb94d`。清单`D:/CLSEN_DeploymentPrep_20260914/evidence/candidate-overlay-manifest-15.json`的SHA-256为`e626dad8f1bb653be603b5fd5ad2381aa45d7299584f614c3a9502f1bfcd969a`。
- `candidate-source-15`与`gate-run-15`均为独立detached worktree、HEAD `ec0a72e`；按230项清单核对均为`missing=0 / mismatch=0 / deleted_present=0 / extras=0 / omitted=0`，实际分类为144个修改、81个未跟踪和5个删除，且无`data/`。
- 下一步仅在再次明确授权后启动候选15完整本地Collect，并从头按既定顺序、首因停止。候选仍不满足canonical runner的clean-SHA合同；形成干净提交SHA、整合/push、远端正式门禁及部署继续分别授权，本地预演不得记为正式`release_validation`。

### 2026-09-15 候选14完整本地Collect结果

- 用户明确授权冻结候选14执行一次完整本地Collect。候选仍为`ec0a72e907cf7787536cf73964f7897485e28c97`加230项overlay，canonical clean-SHA保护未绕过；本轮在`gate-run-14`及只读挂载候选的Ubuntu 24.04容器从头执行同顺序本地预演，日志根为`D:/CLSEN_DeploymentPrep_20260914/candidate14-collect-logs`，不能记为正式`release_validation`。
- Ubuntu-full通过：Ruff lint、399文件format、397源文件mypy通过；pytest 1242通过、2项Windows平台允许跳过、352项排除。Windows smoke通过：376项通过、2项平台允许跳过。
- Frontend固定官方Playwright镜像digest `sha256:dcc5531e97840b9b5e794f2814476b21571c5124a3fca2267d73041f56e7580e`，实测Ubuntu 24.04.4、Node 24.18.1、pnpm 11.16.0、Chromium 151.0.7922.34；候选只读挂载并复制至一次性容器工作区，冻结依赖安装通过496项供应链策略。ESLint、TypeScript及Token门禁通过。
- Vitest首因：89/90文件、426/427项通过，并有1项未处理错误。`App > catalog data manager can open the real maintenance controls`在`App.test.tsx:185`等待“目录工作簿”时，`CatalogImportHistory.tsx:22`因`result.items`未定义而抛错。该测试的共享fetch夹具未处理`/api/catalog/imports?page=1`，落入默认`{}`响应；组件独立测试及后端`GET /api/catalog/imports`均明确使用`items/has_next`列表合同。相同节点在同一Ubuntu环境定向重跑稳定复现为1项失败、38项过滤跳过及1项未处理错误。候选13/14的`App.test.tsx`与`CatalogImportHistory.tsx`逐文件哈希相同，候选13完整Vitest中该文件39项曾通过；现有证据指向既有测试夹具的竞态/合同缺口，不支持候选14业务实现缺陷结论。
- 前端正式命令前有两次容器包装预检退出：第一次因在只读根挂载下创建嵌套`node_modules`挂载点失败，第二次因镜像无`google-chrome`命令别名。两次均发生在依赖安装和候选门禁前；日志`03a-frontend-wrapper-preflight-failed.log`、`03b-frontend-browser-path-preflight-failed.log`保留。只读确认实际Chromium路径并改为候选只读源加一次性可写工作区后，才开始上述唯一一次Frontend门禁。
- 按Vitest首因停止。Playwright、Storybook静态构建/可访问性/27项视觉、两种生产构建、MySQL 8.0/8.4及release-only门禁均未执行。停止后候选14清单SHA-256仍为`4c3d5d32364abde9fc6c4496c4606dfcf06f6c0be634c1a43af8fd0d533c8f1b`；`candidate-source-14`与`gate-run-14`按230项复核均为`missing=0 / mismatch=0 / deleted_present=0 / extras=0 / omitted=0`，两者HEAD均为`ec0a72e`且无`data/`。
- 下一批最小范围须另行授权：仅在`App.test.tsx`现有fetch夹具中为`/api/catalog/imports`补齐既有空列表响应`{ items: [], has_next: false }`，运行原失败Vitest节点、该文件目标ESLint及必要的相邻入口断言，再冻结候选15。不得修改`CatalogImportHistory`业务容错来掩盖夹具错误；候选15完整Collect仍须再次授权。

### 2026-09-15 候选14测试隔离同步与冻结

- 仅把`ImportReviewFlow.test.tsx`已有`beforeEach/afterEach`从首个用例之后移动到`describe`开头，hook内容、两个用例、断言、mock及业务实现均未改变。该变化对应候选13已定位的测试隔离/时序首因，不将其记为业务缺陷修复。
- 新鲜定向验证：`inspects the explicit source instead of restoring an old draft`与`prefills the draft reason from the authenticated operator and source batch`共2/2通过（同文件17项因节点过滤跳过）；目标文件ESLint退出码0。未运行完整Vitest、Playwright、Storybook、生产构建、MySQL或完整Collect。
- 候选14仍基于`ec0a72e907cf7787536cf73964f7897485e28c97`，含144个修改、81个未跟踪、5个删除，共230项；内容身份为`ec0a72e907cf7787536cf73964f7897485e28c97+overlay-sha256:ddf2f5cb6340a68a706d1bab62d36eb32aed5a733c6968f3c7f2bc81033031af`。清单`D:/CLSEN_DeploymentPrep_20260914/evidence/candidate-overlay-manifest-14.json`的SHA-256为`4c3d5d32364abde9fc6c4496c4606dfcf06f6c0be634c1a43af8fd0d533c8f1b`。
- `candidate-source-14`与`gate-run-14`均为独立detached worktree、HEAD `ec0a72e`；按230项清单核对均为`missing=0 / mismatch=0 / deleted_present=0 / extras=0 / omitted=0`，实际分类为144个修改、81个未跟踪和5个删除，且无`data/`。
- 下一步仅在再次明确授权后启动候选14完整本地Collect，并从头按既定顺序、首因停止。候选仍不满足canonical runner的clean-SHA合同；形成干净提交SHA、整合/push、远端正式门禁及部署继续分别授权，本地预演不得记为正式`release_validation`。

### 2026-09-15 候选13完整本地Collect结果

- 用户明确授权冻结候选13执行一次完整本地Collect。候选仍为`ec0a72e907cf7787536cf73964f7897485e28c97`加230项overlay，canonical clean-SHA保护未绕过；本轮在`gate-run-13`及只读挂载候选的Ubuntu容器按既定顺序执行同顺序本地预演，日志根为`D:/CLSEN_DeploymentPrep_20260914/candidate13-collect-logs`。
- Ubuntu-full通过：Ruff lint、399文件format、397源文件mypy通过；pytest 1242通过、2项Windows平台允许跳过、352项排除。Windows smoke通过：376项通过、2项平台允许跳过。
- Frontend使用官方Playwright镜像digest `sha256:dcc5531e97840b9b5e794f2814476b21571c5124a3fca2267d73041f56e7580e`，实测Ubuntu 24.04.4、Node 24.18.1、pnpm 11.16.0、Chromium 151.0.7922.34；候选只读挂载，冻结依赖安装通过496项供应链策略。ESLint、TypeScript及Token门禁通过。
- Vitest首因：89/90文件、426/427项通过；`ImportReviewFlow > prefills the draft reason from the authenticated operator and source batch`在`ImportReviewFlow.test.tsx:194`找不到“CSV 文件”，DOM已恢复为批次#44的确认识别状态。只读追踪显示前一新增用例位于本文件`beforeEach/afterEach`声明之前，会异步持久化批次#44恢复状态却不受随后清理hook覆盖；下一用例可能恢复该状态。该文件在候选12/13哈希相同，且候选12两次完整Vitest中该节点通过，现有证据指向既有测试隔离/时序缺口，不支持候选13业务回归结论。
- 按首因停止且未修正、未重跑：本轮完整Playwright、Storybook构建/可访问性/27项视觉、两种生产构建、MySQL 8.0/8.4及release-only门禁均未执行。容器首次环境展示包装因镜像无`lsb_release`且Corepack shim未加入PATH而在任何Frontend门禁前退出；只读确认镜像实际环境后改用`/etc/os-release`和`corepack pnpm`，再开始上述唯一一次Frontend门禁，预检失败单独保留但不计为候选测试失败。
- 停止后候选13清单SHA-256仍为`7950ec48bb521c1f5cc5c0a52402b7a6a6e8bcb41289ccc1e9a0f25168294d9a`；`candidate-source-13`与`gate-run-13`按230项复核均为`missing=0 / mismatch=0 / deleted_present=0 / extras=0 / omitted=0`，两者HEAD均为`ec0a72e`且无`data/`。候选身份保持`ec0a72e+overlay-sha256:7aca3835c24cb1cde164b5247e3b20d028eb86ac02629e58f64a963dd6d88dcd`，不冻结候选14。
- 下一批最小范围：另行授权后，仅把该文件的`beforeEach/afterEach`移到首个用例之前，运行这两个相邻Vitest节点及目标ESLint；通过后冻结候选14。候选14完整Collect仍须再次授权，clean-SHA、整合/push、远端正式门禁和部署继续分别授权。

### 2026-09-15 候选13测试同步与冻结

- 候选12第二次完整本地Collect在`PublishedDetailLedgerPage.test.tsx:500`停止。根因是测试以第二次摘要API调用作为路由commit完成的同步点，但冲突处理同批调度路由替换与摘要reload，摘要查询键又不含展开日期；因此API调用可先于LocationProbe移除`report_date`发生。该节点上一轮曾通过，现有证据为测试时序缺口，不是业务功能缺陷。
- 仅将现有`not.toHaveTextContent("report_date")`断言包入`waitFor`，没有修改断言内容、业务组件、API、样式、依赖或体验环境。原失败Vitest节点新鲜运行1/1通过（同文件其余20项按节点过滤跳过），目标文件ESLint退出码0；未运行该文件其余测试、完整Frontend、Storybook、MySQL或完整Collect。
- 候选13基线仍为`ec0a72e907cf7787536cf73964f7897485e28c97`，清单新增该测试文件后为144个修改、81个未跟踪、5个删除，共230项。内容身份为`ec0a72e907cf7787536cf73964f7897485e28c97+overlay-sha256:7aca3835c24cb1cde164b5247e3b20d028eb86ac02629e58f64a963dd6d88dcd`；清单`D:/CLSEN_DeploymentPrep_20260914/evidence/candidate-overlay-manifest-13.json`的SHA-256为`7950ec48bb521c1f5cc5c0a52402b7a6a6e8bcb41289ccc1e9a0f25168294d9a`。
- `candidate-source-13`与`gate-run-13`均为独立detached worktree，HEAD为`ec0a72e`；按230项清单核对均为`missing=0 / mismatch=0 / deleted_present=0 / extras=0 / omitted=0`，且不含`data/`。候选12及其日志未改变。
- 下一步最小范围：候选13完整本地Collect仍需再次明确授权，并须从头按既定顺序、首因停止；正式clean-SHA候选、整合/push、远端门禁和部署继续分别授权。本地预演不得记为正式`release_validation`。

### 2026-09-15 候选12第二次完整本地Collect结果

- 用户明确授权冻结候选12重新执行一次完整本地Collect，并指定Frontend视觉门禁使用Ubuntu 24.04锁定环境。候选仍为`ec0a72e907cf7787536cf73964f7897485e28c97`加229项overlay；canonical clean-SHA保护未绕过，本轮在只读挂载候选的锁定容器及`gate-run-12`执行同顺序本地预演，日志根为`D:/CLSEN_DeploymentPrep_20260914/candidate12-collect-02-logs`。
- Ubuntu-full通过：Ruff lint、399文件format、397源文件mypy通过；pytest 1242通过、2项允许跳过、352项排除。Windows smoke通过：376项通过、2项平台允许跳过。
- Frontend锁定环境为官方`mcr.microsoft.com/playwright:v1.62.1-noble`（digest `sha256:dcc5531e97840b9b5e794f2814476b21571c5124a3fca2267d73041f56e7580e`）、Ubuntu 24.04.4、Node 24.18.1、pnpm 11.16.0、Playwright 1.62.1/Chromium 151.0.7922.34；候选只读挂载，冻结依赖安装通过496项供应链策略。ESLint、TypeScript和Token门禁通过。
- Vitest首因：89/90文件、426/427项通过；`PublishedDetailLedgerPage.test.tsx > drops an expanded scope conflict and reloads the summary exactly once`在第500行直接断言地址已移除`report_date`时失败。只读追踪确认冲突处理会同时调度路由替换与摘要reload，而摘要查询键不含展开日期，所以“摘要API已调用2次”可先于LocationProbe更新成立；同文件相邻路由断言使用`waitFor`。上一轮相同候选同一Vitest集合为90文件/427项通过。现有证据指向测试异步同步缺口，不足以认定业务功能缺陷；本轮未修改或重跑。
- 按首因停止：本轮Playwright、Storybook静态构建/可访问性/完整27项视觉、两种生产构建、MySQL 8.0/8.4及release-only门禁均未执行。上一轮和Ubuntu定向视觉证据不冒充本轮节点通过，本地预演也不记为正式`release_validation`。
- 停止后manifest SHA-256仍为`1d8b8d3179c54dd93fa720d65903e3cee38fe1b6ffe45a8c111e45f6b05c1d12`；`candidate-source-12`与`gate-run-12`逐项核对229项均为`missing=0 / mismatch=0 / deleted_present=0`，两者HEAD均为`ec0a72e`，tracked清单无意外项或遗漏。候选内容身份保持`ec0a72e+overlay-sha256:8cd7b744daa1b668ba2821e50ca387e627a7b5b0875fc52984566cc6751cfa39`，不冻结候选13。
- 下一批最小范围：另行授权后，只给该测试的`report_date`清除断言增加明确异步等待，运行该Vitest节点与目标ESLint，若通过再冻结候选13；候选13完整Collect仍须再次授权。形成干净提交SHA、整合/push、远端正式门禁和部署继续分别授权。

### 2026-09-15 候选12完整本地Collect结果

- 用户明确授权候选12执行一次完整本地Collect。候选仍是`ec0a72e907cf7787536cf73964f7897485e28c97`加229项overlay；既有canonical runner clean-SHA合同未绕过，本轮在冻结`gate-run-12`按既定顺序执行本地同顺序预演，日志根为`D:/CLSEN_DeploymentPrep_20260914/candidate12-collect-logs`。
- Ubuntu-full：Ruff lint、399文件format、397源文件mypy通过；pytest收集1596项、排除352项、执行1244项，1242通过、2项允许跳过。Windows smoke：378项中376通过、2项平台允许跳过。
- Frontend：ESLint、TypeScript及设计Token通过；Vitest 90文件/427项、完整Playwright 14项通过。Storybook静态构建成功，可访问性门禁23/23通过。视觉门禁27项中23项通过，4项失败均为390×844移动端：`form-controls--field-states`、`selection-and-navigation--selection-states`、`feedback-and-data--toast-kinds`、`feedback-and-data--loading-empty-and-error`，报告差异比例为0.04/0.02/0.02/0.02，均超过0.01合同。
- 定向诊断：Windows下仅重跑这4个节点，结果稳定为相同差异比例，且两次实际截图SHA-256逐张完全一致，排除偶发动画或截图抖动。随后从批准基线首次提交`64176d4249f0d3232f01f08d542bf36b4855ca02`提取原始Frontend代码，在同一Windows Node 24.18.1、Playwright 1.62.1/Chromium 151.0.7922.34及Noto Sans SC 5.3.0环境只运行同4项；仍以完全相同像素数失败，4张实际图SHA-256也与候选12逐张一致。因此候选12代码变化不是差异来源。
- 环境证据：批准记录只固定Playwright 1.62.1和Noto Sans SC 5.3.0，没有记录OS；正式Frontend workflow明确使用`ubuntu-24.04`，而本地Collect运行于Windows 10.0.26200。现有WSL没有Node/Chromium，现有Frontend Docker镜像仅含Nginx静态产物，无法在不新增运行时/依赖的前提下完成Ubuntu对照。故首因收敛为跨平台视觉基线执行合同/证据缺口；是否在正式Ubuntu合同下通过仍待验证，不能把Windows差异认定为业务功能或候选样式缺陷。
- 用户随后授权Ubuntu 24.04四节点定向复核。使用官方`mcr.microsoft.com/playwright:v1.62.1-noble`（digest `sha256:dcc5531e97840b9b5e794f2814476b21571c5124a3fca2267d73041f56e7580e`），确认Ubuntu 24.04.4、Node 24.18.1、pnpm 11.16.0、Playwright 1.62.1/Chromium 151.0.7922.34及锁定依赖/字体；候选12以只读挂载进入一次性容器，4个390×844节点`4 passed (8.9s)`。这确认Windows失败为平台像素差异，不是候选12视觉回归；未生成或更新批准基线。
- 按首因停止；`legacy_parser`与`p0_catalog`生产构建、MySQL 8.0/8.4、OpenAPI/产品基线及后续Stage0门禁均未执行。停止后`candidate-source-12`与`gate-run-12`均再次核对为HEAD `ec0a72e`、`missing=0 / mismatch=0 / deleted_present=0 / extras=0 / omitted=0`；候选12身份保持`ec0a72e+overlay-sha256:8cd7b744daa1b668ba2821e50ca387e627a7b5b0875fc52984566cc6751cfa39`。
- 下一批最小范围：候选内容未变，不冻结候选13，也不修正业务样式或批准基线。若继续部署准备，须另行授权候选12下一次完整本地Collect，并明确Frontend视觉门禁使用正式Ubuntu 24.04锁定环境；仍按首因停止。正式形成干净提交SHA、整合/push、远端门禁及部署继续分别授权。

### 2026-09-14 候选12 E2E合同同步与冻结

- 仅修改`catalog-sensitive-reveal.spec.ts`、`catalog-workflow.spec.ts`、`date-workbench-structural-grid.spec.ts`、`import-review-publish.spec.ts`和`product-ledger.spec.ts`：同步当前可访问名称与维护页入口，补齐目录导出任务、批量审核历史及分类列表夹具，以具名表格/操作区代替CSS Modules字面类名，并按当前产品信息抽屉路径验证标准名称和详情入口。焦点可见性仍校验边框色与`--color-focus`语义Token相等，未删除或弱化断言。
- 诊断过程发现目录导出夹具缺当前权限/任务字段、工作台硬编码旧焦点色、导入页漏批量任务历史GET、产品表未按新的抽屉交互关闭模态后读取背景。现有快照和定向重跑均指向测试合同漂移，未得到业务功能缺陷证据。
- 最终目标ESLint退出码0；原失败的9个Chromium节点`9 passed (9.2s)`。日志位于`D:/CLSEN_DeploymentPrep_20260914/candidate12-targeted`。未运行候选12完整Collect、Storybook、生产构建、MySQL或后续门禁。
- 候选12基线仍为`ec0a72e907cf7787536cf73964f7897485e28c97`，清单含143个修改、81个未跟踪和5个删除项，共229项，内容身份以`D:/CLSEN_DeploymentPrep_20260914/evidence/candidate-overlay-manifest-12.json`为准；`candidate-source-12`与`gate-run-12`均为`missing=0 / mismatch=0 / deleted_present=0 / extras=0 / omitted=0`，且排除`data/`。候选12仍为overlay，canonical runner的clean-SHA前置未解决。
- 下一批最小范围：用户再次明确授权后，仅对已冻结候选12执行一次完整本地Collect并按首因停止。不自动循环，不将本地同顺序预演记为正式`release_validation`；形成干净提交SHA、整合/push、远端正式门禁和部署仍需分别授权。

### 2026-09-14 候选11浏览器测试修正与冻结

- 现有失败快照证明宽泛的 `getByText("无报表")` 同时命中图表每日读数摘要与趋势矩阵单元格；用例标题中的 `null gaps` 对应矩阵空点。修正为在具名“趋势每日点矩阵”区域内查找精确名称“无报表”的单元格，保留原 `toBeVisible()` 断言；未使用 `.first()`、未删断言、未跳过测试，也未修改业务实现、依赖或体验环境。
- 后续可见性失败经代码与现有组件测试核对：危险别名位于默认折叠的原生`details`中，现有`ProductDetailPage.test.tsx`也先点击“1 个来源别名”再断言安全占位。E2E缺少该展开动作；只补`click()`步骤，未修改业务代码、样式、依赖或体验环境。
- 定向验证：正确源工作树的目标ESLint `--max-warnings 0`通过；正确产品分析模式下唯一Chromium用例1/1通过（3.0秒）。早先主工作区误跑、`No tests found`及缺少产品分析模式的运行均不计为候选证据。未运行完整Collect、Storybook、其他浏览器、生产构建、MySQL或业务数据库检查。
- 候选11基线仍为`ec0a72e907cf7787536cf73964f7897485e28c97`；清单 `[candidate-overlay-manifest-11.json](D:/CLSEN_DeploymentPrep_20260914/evidence/candidate-overlay-manifest-11.json)` 共224项，source/gate双副本逐项核对，不含`data/`。候选10源/执行副本、清单与Collect日志均保留不变。
- clean-SHA只读结论：`run-ci-profile.ps1` 的 workspace-boundary 校验要求工作区HEAD等于指定SHA且 `git status --porcelain` 为空；候选11仍由基线加overlay表示，因此下一轮直接运行 canonical runner 仍会被同一保护阻断。正式准备必须先另行授权把完整候选（含应交付未跟踪材料和删除项）形成一个提交SHA，并在该SHA的干净检出上运行；远端正式 release gates 还要求另行授权整合/push到master，且workflow SHA、输入SHA、当前master SHA完全一致并有唯一成功的master push compatibility运行及`master-required`。本地同顺序预演只能提供当前overlay的开发/兼容性线索，不能形成不可变SHA绑定、远端来源或正式`release_validation`证据。

### 2026-09-14 候选11完整本地Collect结果

- 用户明确授权候选11执行一次完整本地Collect。canonical runner从`candidate-source-11`启动即因224项overlay不满足clean-SHA合同而退出，未执行runner门禁；保护未绕过，指定证据根`D:/CLSEN_DeploymentPrep_20260914/candidate11-collect-20260914`未产生门禁证据，也没有生成独立canonical日志文件，实际错误为`Baseline collection requires a clean candidate SHA outside the user-owned data directory.`。
- 随后只在独立`gate-run-11`执行副本按既定本地预演顺序运行，实际顺序为先Windows、后Ubuntu：Windows smoke收集378项，376通过、2项Windows平台允许跳过；Ubuntu-full的Ruff lint、399文件format、397源文件mypy通过，pytest收集1596项、排除352项、执行1244项，其中1242通过、2项允许跳过。
- Frontend为复用已有稳定依赖建立仅供执行环境使用的`node_modules` junction，未进入候选清单、未安装或修改依赖。该目录的`.modules.yaml`仍把`virtualStoreDir`绑定到`gate-run-08`；从`gate-run-11`调用pnpm包装器时，在第一项实际ESLint运行前触发`pnpm install`状态检查，因模块目录需要清理且当前无TTY，以`ERR_PNPM_ABORTED_REMOVE_MODULES_DIR_NO_TTY`退出。这是依赖执行前置阻塞，现有日志没有产生Frontend lint失败或业务功能失败证据。
- 按首因停止；Frontend ESLint、TypeScript、Token、Vitest、浏览器14项、Storybook静态构建/无障碍/视觉、两种生产构建，以及MySQL 8.0/8.4、OpenAPI、产品目录基线和后续Stage0门禁均未执行。未设置`CI=true`、未关闭pnpm确认保护、未清理/重装依赖，也未自动重跑完整Collect。
- 停止后按224项清单复核`candidate-source-11`与`gate-run-11`：两者HEAD均为`ec0a72e907cf7787536cf73964f7897485e28c97`，均为`missing=0 / mismatch=0 / deleted_present=0 / extras=0 / omitted=0`。下一批最小范围是另行授权后仅解决可复现、可审计的pnpm执行环境前置并做必要定向验证；候选内容无业务变更时不冻结新编号，完整Collect仍须再次授权。

### 2026-09-14 候选11 pnpm执行前置定向处理

- 当前执行主工作区为`D:/CLSEN_Data_Web`、分支`codex/development-throughput`、HEAD`7de0ee67734c5504b0a093cf05a18fa05e9097ae`；候选业务源仍为`stage4-1-app-shell / ec0a72e + overlay`，本批未在业务源修改文件。实际pnpm命令来自Codex bundled pnpm 11.19.0；runner只调用`pnpm lint`，不是脚本显式要求重新安装。
- 根因证据：`gate-run-11/frontend/node_modules`复用`gate-run-08`，其`.modules.yaml`将`virtualStoreDir`绝对绑定到`D:/CLSEN_DeploymentPrep_20260914/gate-run-08/frontend/node_modules/.pnpm`；从`gate-run-11`运行且未显式对齐该配置时，pnpm依赖状态检查判定模块目录需要清理，因无TTY而安全停止。
- 单变量处理仅在目标进程设置`pnpm_config_virtual_store_dir`为上述现有虚拟存储路径，不设置`CI=true`、不关闭`confirmModulesPurge`、不清理或安装依赖、不修改runner或候选文件。pnpm输出锁文件通过供应链策略、解析跳过、`Already up to date`，随后`eslint . --max-warnings 0`退出码0。
- 前后监控`package.json`、`pnpm-lock.yaml`、`.modules.yaml`和虚拟存储`lock.yaml`的SHA-256，变化数为0；再次按224项清单核对source/gate双副本均为`missing=0 / mismatch=0 / deleted_present=0 / extras=0 / omitted=0`。定向日志为`D:/CLSEN_DeploymentPrep_20260914/candidate11-pnpm-preflight/pnpm-lint-aligned-store.log`。
- 此处理只为候选11本地预演提供可审计的依赖路径参数，不改变canonical runner仍需干净提交SHA的合同，也不证明TypeScript、Token、Vitest、浏览器、Storybook、生产构建、MySQL或后续门禁。候选内容未变，因此不冻结候选12；再次完整Collect仍需用户明确授权。

### 2026-09-14 候选11第二次完整本地Collect结果

- 用户明确授权后，保留canonical clean-SHA保护的既有结论，不重复尝试绕过；在冻结`gate-run-11`按正式profile顺序新鲜运行本地预演。日志根为`D:/CLSEN_DeploymentPrep_20260914/candidate11-collect-02-logs`。
- Ubuntu-full：Ruff lint、399文件format、397源文件mypy通过；pytest收集1596项、排除352项、执行1244项，1242通过、2项Windows平台允许跳过。Windows smoke：378项中376通过、2项允许跳过。
- Frontend：pnpm进程级虚拟存储路径对齐有效；ESLint、TypeScript、设计Token通过，Vitest 90个文件/427项通过。Playwright 14项中5项通过、9项失败，失败分布为`catalog-sensitive-reveal.spec.ts`1项、`catalog-workflow.spec.ts`1项、`date-workbench-structural-grid.spec.ts`3项、`import-review-publish.spec.ts`1项、`product-ledger.spec.ts`3项。
- 只读诊断证据：当前目录入口已迁至`/catalog/maintenance`且按钮为“生成候选”，敏感标识按钮当前为“查看完整标识”，草稿校验按钮当前为“运行草稿校验”；对应E2E仍使用旧首页入口、“显式 reveal”和“运行完整校验”。工作台DOM已渲染表格，但E2E直接查找CSS Modules编译后不会保留的`.workbench-grid-wrap`/`.workbench-grid`字面类名。产品总表三个视口的夹具未返回新增的`/api/catalog/categories`合同，fallback `{}`使`categories`成为`undefined`并在`ProductLedgerPage`调用`.find`时触发页面错误。现有证据均指向测试入口、选择器或夹具未同步，不证明业务实现缺陷。
- 五个失败E2E文件在`candidate-source-10`、`candidate-source-11`及`gate-run-11`的SHA-256逐项相同，排除候选11最近浏览器修正引入这些失败。按浏览器门禁失败停止；Storybook静态构建/无障碍/视觉、两种生产构建、MySQL 8.0/8.4、OpenAPI、产品目录基线及后续Stage0门禁均未执行。
- 停止后source/gate双副本按224项清单再次核对，均为`missing=0 / mismatch=0 / deleted_present=0 / extras=0 / omitted=0`。下一批最小范围是另行授权后仅同步上述5个E2E合同，运行目标ESLint及9个受影响浏览器节点，随后如有内容变化冻结候选12；候选12完整Collect仍需再次授权。

### 2026-09-14 候选10测试夹具修正与冻结

- 用户授权后仅修正 `frontend/src/features/catalog/CatalogMaintenancePage.test.tsx` 的 fetch 夹具：按端点返回 `/api/catalog/imports` 所需 `items/has_next`，保留当前目录与最新导出响应形状。未修改业务组件、API、数据或体验环境。
- 定向验证：`CatalogMaintenancePage.test.tsx` 与 `CatalogImportHistory.test.tsx` 共 2 项通过；目标 ESLint 通过。未运行完整 TypeScript、浏览器、Storybook、生产构建、MySQL或其他完整门禁。
- 候选10基线为 `ec0a72e907cf7787536cf73964f7897485e28c97`；清单 `[candidate-overlay-manifest-10.json](D:/CLSEN_DeploymentPrep_20260914/evidence/candidate-overlay-manifest-10.json)` 的哈希与内容身份以清单文件为准；候选 source/gate 两副本均按223项逐项 missing=0、mismatch=0、deleted_present=0，不含 `data/`。
- 当前状态：`in_progress / candidate10_collect_failed / candidate10_runner_clean_sha_guard_blocked / windows_smoke_passed / ubuntu_full_passed / frontend_lint_passed / frontend_typecheck_passed / frontend_tokens_passed / frontend_unit_tests_passed / frontend_browser_failed / collect_stopped / targeted_experience_complete`。canonical runner 未绕过 clean-SHA 保护；同顺序本地预演的浏览器首因已定向重跑复现。#9/#35既有确认保留，Stage5.1/5.2不重新开启。

| 分类 | 事项 | 现有证据 | 缺口 | 发布影响 | 建议处置 | 所属阶段 |
|---|---|---|---|---|---|---|
| 已修复，完整Collect首项失败（历史候选08） | 候选07 Frontend lint中的2个测试文件（候选08修正）及候选08 Frontend typecheck首因 | 候选07 Frontend full稳定停止在`ImportReviewFlow.test.tsx`3项`no-base-to-string`及`DateWorkbenchPage.test.tsx`6项`require-await`/unsafe JSON类型错误；两文件在候选02–07逐份清单中的SHA-256始终相同，说明不是候选07业务回归。候选08仅修正这2个测试文件，定向ESLint通过，ImportReviewFlow 19项、DateWorkbenchPage 29项Vitest共48项通过。候选08完整Collect中Windows smoke 376/378通过、2项允许跳过；Ubuntu-full Ruff lint、399文件format、397源文件mypy及pytest执行范围1242项通过、2项允许跳过；Frontend ESLint通过，TypeScript首项在`MergeDecisionMatrix.test.tsx(170,114)`报TS18049。该文件自候选02至08哈希均为`3cc1526d...`。 | 候选08 TypeScript失败后，Frontend类型后续、单测、浏览器、Storybook、生产构建、MySQL 8.0/8.4及后续门禁未执行；候选08不是远端master干净SHA。现有证据只证明既有测试类型合同未满足，不证明业务实现失败。 | 曾阻塞候选08完整门禁和正式`release_validation`；不撤销#9/#35体验确认，也不把候选08失败归为Stage5.1/R1/R2业务缺陷。 | 候选09已对该测试合同做最小类型收窄，Front-end TypeScript 定向检查通过并完成冻结；候选09完整Collect仍需单独授权。保留Storybook材料，授权前不运行其门禁。 | 部署准备 |
| 候选09完整Collect首因（测试夹具，非业务缺陷） | 候选09全量 ESLint、TypeScript、设计 Token 通过；Vitest 90个测试文件中89个完成、426项通过，首个失败为`CatalogMaintenancePage.test.tsx`，并出现`CatalogImportHistory.tsx:22`读取`items.length`的未处理错误。后端`GET /api/catalog/imports`既有契约返回`items/has_next`，独立`CatalogImportHistory.test.tsx`通过；失败夹具却对非`/latest`请求统一返回`{catalog:null}`。pnpm 包装器因复用 gate-run-08 的虚拟存储路径报`ERR_PNPM_ABORTED_REMOVE_MODULES_DIR_NO_TTY`，本轮直接使用候选09既有`.bin`工具，锁文件和模块清单哈希未改变。 | 未执行剩余前端浏览器、Storybook静态构建/无障碍/视觉、两种生产构建、MySQL 8.0/8.4及后续门禁；没有业务行为或用户体验新证据。 | 阻塞候选09本地Collect继续及正式`release_validation`，但不撤销#9/#35确认、不启动Stage5.1/5.2，也不认定业务功能失败。 | 下一批仅修正该测试夹具返回契约并运行该测试及必要定向回归；修正未获本轮授权，完成后须重新冻结候选并再次授权完整Collect。保留 pnpm 环境阻塞为运行器缺口，不安装或清理依赖。 | 部署准备 |
| 候选10完整Collect首因（测试选择器，非业务缺陷；候选11已修正） | canonical runner 在 `candidate-source-10` 启动即因 clean-SHA 保护拒绝冻结副本的223项 overlay（退出码1，未执行门禁）；随后在独立 `gate-run-10` 执行副本按既定顺序完成 Windows smoke 376/378通过、2项平台允许跳过；Ubuntu-full Ruff、399文件format、397源文件mypy，pytest 1242通过/2项允许跳过；Frontend ESLint、TypeScript、Token及Vitest 90文件/427项通过。浏览器首个失败 `tests/e2e/product-detail.spec.ts:7`，`getByText("无报表")` strict-mode 匹配两个元素；同一用例定向重跑复现。 | 候选11已将null-gap断言收窄到趋势矩阵精确单元格；随后出现的危险别名hidden来自原生`details`默认折叠，补齐展开步骤后同一节点通过，不构成390px业务显示缺陷。canonical runner的clean-SHA合同仍未满足。浏览器其余用例、Storybook静态构建/无障碍/视觉、两种生产构建、OpenAPI/产品基线、MySQL 8.0/8.4及后续门禁仍未执行。 | 候选10该首因已解除并冻结候选11，但完整Collect和正式`release_validation`仍被未执行范围及clean-SHA前置阻塞；不影响已确认#9/#35体验，不启动Stage5.1/5.2。 | 保留候选10历史证据；后续如获授权，从候选11继续，但不得绕过clean-SHA保护或自动把本地预演记作正式验收。 | 部署准备 |
| 候选11第二次完整Collect首因（5个E2E合同文件，候选12已处理） | Ubuntu-full与Windows smoke通过；Frontend lint、typecheck、Token和Vitest 90文件/427项通过。Playwright 14项中5项通过、9项失败。页面快照、trace及当前源码将首因收敛到5个既有E2E合同漂移；5个文件在候选10/11哈希相同。候选12的目标ESLint及原9个Chromium节点已全部通过。 | 5个E2E合同同步缺口已关闭；Storybook、生产构建、MySQL 8.0/8.4、OpenAPI/产品基线及后续Stage0门禁仍未执行；canonical干净SHA前置仍未满足。 | 候选11的浏览器首因已解除，但候选12完整Collect与正式`release_validation`仍未开始；不撤销#9/#35确认，不启动Stage5.1/5.2。 | 保留候选11失败证据和候选12定向通过证据；只在再授权后对候选12执行一次完整本地Collect，不自动循环。 | 部署准备 |
| 候选12完整Collect首因（Windows平台Storybook像素差异，Ubuntu定向通过） | Ubuntu-full、Windows smoke、Frontend lint/typecheck/Token、Vitest 90文件/427项、Playwright 14项、Storybook静态构建和可访问性23项通过。Windows视觉门禁4项390×844截图稳定失败；原始批准基线提交在同一Windows工具链下产生与候选12逐张相同的实际图，排除候选代码变化。正式Ubuntu 24.04锁定环境下原4节点`4 passed (8.9s)`。 | 候选12完整Collect已停止，尚未在Ubuntu环境运行完整27项视觉门禁；两种生产构建、MySQL 8.0/8.4、OpenAPI/产品基线及后续门禁未执行，canonical干净SHA前置仍未满足。 | 对应候选视觉回归疑点已关闭，但完整本地Collect和正式`release_validation`仍未完成；不撤销#9/#35体验确认或启动Stage5.1/5.2。 | 保留Windows结果为平台差异，不更新基线或样式；再次获完整Collect授权时让Frontend视觉门禁使用正式Ubuntu锁定环境并重新按首因执行。 | 部署准备 |
| 已补体验 | 45组#9 分类管理左右布局、树目录、按钮与分支线 | 候选02隔离环境已准备`衬衫→长袖衬衫/短袖衬衫`两级虚构树；正确入口为“商品→查看商品卡→管理分类”（本次为`/catalog/styles/2`），不是批量维护页。用户按“搜索/展开→制造未保存修改并切换→取消修改→窄屏查看”路径体验后明确回复“通过”。 | 本项无剩余用户体验缺口；候选08仅修正两测试文件，相关业务语义未变，但完整Collect及正式发布门禁仍未完成。 | #9在候选02记为已确认并适用于相关业务语义未变的候选08，不扩大为正式发布验收通过。 | 保留本次确认；后续未受改动不重复安排。 | `user_verified`；发布候选体验已收口，不纳入Stage5.1代码项 |
| 已补体验 | 45组#35 销售贡献/退货关注组合 | 候选02隔离环境`/products`已有3款，2025-07-17销售额合计US$669.98；款号100为46件/US$569.98/3件退货。用户按“销售贡献→核对占比/平均单价→退货关注→核对同期退销比→切回”路径体验后明确回复“#35通过”。 | 本项无剩余用户体验缺口；候选08仅修正两测试文件，相关业务语义未变，但完整Collect及正式发布门禁仍未完成。 | #35在候选02记为已确认并适用于相关业务语义未变的候选08，不扩大为其他产品分析路径或正式发布验收通过。 | 保留本次确认；后续未受改动不重复安排。 | `user_verified`；发布候选体验已收口，不纳入Stage5.1代码项 |
| 仅文档/材料同步 | 45组#40 Storybook材料 | `LedgerMetricHelp.stories.tsx`、`ProductTrendChart.stories.tsx`及`ProductTrendChart.reference.md`均已进入候选12；候选12 Storybook静态构建成功、可访问性23/23通过。 | 视觉门禁4个移动端设计系统故事基线不匹配；失败不指向上述两个Patterns故事，但整体Storybook视觉门禁尚未通过。 | 旧20601业务体验不受影响；材料纳入与构建缺口已关闭，但不能声明Storybook整体验收通过。 | 保留材料，不重开业务体验；视觉差异按候选12首因单独定向核对。 | `candidate_included / build_passed / visual_gate_failed`；部署准备材料收口 |
| 证据不足 | V35批准前全量mapping/exclusion不变 | 明确记录的 `sku-closeout-summary.json` 证明8月1–6日逐日合计与既有汇总一致，并显示1202别名43→44、仅新增Light Blue XXL、无删除；`sku-closeout-readonly.json`包含current/V35单款式分析、daily、unmatched等响应，证明1202历史身份仍可读。 | 两份文件都没有V35批准前的全目录mapping/exclusion清单、计数加摘要或前后成对快照，不能证明无关款式/排除项均未变化。 | 不阻塞已确认的V36/current使用路径；阻塞“V35全目录历史不变已验证”的声明，也不能把V35当作已验证回滚基线。 | 保持未验证。部署准备时若发布/回滚依赖该历史事实，必须由用户明确授权一个批准前证据来源再核对；否则把它列为发布声明限制/残余风险。新快照只证明新操作。 | 部署准备证据与风险决定；不是Stage5.1修复 |
| 可复用，无当前修复项 | Stage5.1查询、批准与纠错保护 | 既有计划已定位 `current/catalog_snapshot`、安全错误、不可变快照、批准、单商品变更与向前恢复入口；现有交付记录没有相反的当前缺陷证据。 | 正式发布门禁未执行；目标合同存在不等于新候选已经验收。 | 当前无需为阶段编号新增功能；如未来出现明确错误再选择R1/R2。 | 用户已确认无新增实施项；A–D/D1–D8继续延期。 | Stage5.1 `scope_closed / no_implementation_required` |
| 可延期 | Stage5.2预设规模化改造及完整历史治理 | 当前加载反馈已有修复与相应确认/定向证据；没有记录证明当前分页、导出或维护规模仍不满足。 | 未做完整性能验收；未来ERP规模也未确定。 | 不应据此宣称性能全面通过，但不构成当前必须开发项。 | 用户已确认不启动候选子表化、游标分页、流式XLSX、通用治理平台或Java骨架；性能、恢复及完整门禁留部署准备。 | Stage5.2 `scope_closed / no_implementation_required`；未来需求延期 |

**当前任务（候选17覆盖）：** 部署准备，`in_progress / candidate17_collect_failed / ubuntu_full_passed / windows_smoke_passed / frontend_full_passed / mysql_8_0_failed / collect_stopped / collect_awaiting_targeted_fix_authorization / canonical_clean_sha_prerequisite_unresolved / targeted_experience_complete`。候选17完整本地Collect在MySQL 8.0旧迁移头测试合同首因处停止；MySQL 8.4及release-only未执行。不重开#9/#35，不启动Stage5.1/5.2，正式`release_validation`仍为`not_started`，不提交、整合、push、迁移或部署。

**当前候选（覆盖上段历史状态）：** 最新有效冻结身份为候选17，清单 `D:/CLSEN_DeploymentPrep_20260914/evidence/candidate-overlay-manifest-17.json`，含145个修改、81个未跟踪和5个删除项，共231项；source/gate双副本为`missing=0 / mismatch=0 / deleted_present=0 / extras=0 / omitted=0`。候选仍不是干净提交SHA，canonical runner的clean-SHA前置未满足。测试合同定向修正、下一候选完整Collect、形成提交SHA、整合/push、远端正式门禁及部署均需各自授权。

**候选09 Collect 结果覆盖：** Windows smoke 378项中376通过、2项平台允许跳过；Ubuntu-full 的 Ruff lint、399文件 format、397源文件 mypy及pytest执行范围沿用本次已通过结果（1596收集、352排除、1244执行、1242通过、2项允许跳过）。Frontend 直接调用冻结副本已有工具完成 ESLint、TypeScript、设计 Token；Vitest 90个测试文件中89个完成，426项通过，`CatalogMaintenancePage.test.tsx` 1项失败并伴随`CatalogImportHistory.tsx:22`未处理错误。根因是测试夹具对`/api/catalog/imports`返回`{catalog:null}`，而后端列表契约及独立历史组件测试要求`items/has_next`；这不是业务功能缺陷证据。因首因停止，浏览器、Storybook、生产构建、MySQL 8.0/8.4及后续门禁未执行；下一次完整Collect须重新授权，#9/#35体验不重开。

候选02体验环境：Run ID `0f54e6bb87424b7da68ec7f8ae007f9d`，前端 `http://127.0.0.1:59452`，API `http://127.0.0.1:47596`，一次性数据库`clsen_data_test_0f54e6bb87424b7d`，schema `0028`。完整登录名为`catalog-live-admin-0f54e6bb87424b7da68ec7f8ae007f9d`，密码仅存任务runtime的`experience-credentials.json`，不写仓库。为同时开放P0产品页，执行副本使用任务专用脚本副本放开Products体验模式；候选应用源码及正式脚本未因此改变。入口健康、两页200、分类树及产品账API数据已核实，随后#9/#35按本环境完成用户体验确认；确认仅适用于对应版本、样例和路径，不等于正式发布验收通过。

下方2026-09-11及更早的交付/环境记录全部保留；其中“当前、下一步、待体验、待修复、整体未完成”等旧状态已被本节与45组清单覆盖，仅解释当时版本。部署准备未访问业务原件、`data/`或业务数据库；只运行候选本地门禁预演、失败节点定向检查，并新建任务自有虚构体验环境。

本轮实际Skill：`systematic-debugging`用于沿runner→pnpm→模块元数据调用链确认绝对虚拟存储路径不一致的根因并做单变量处理；`verification-before-completion`用于核对完整ESLint退出码、四个受监控哈希、候选11双副本及未执行门禁范围。本批未修改业务代码，没有提交、整合或部署。

2026-09-14同项优化：[Stage5.1实施计划v1.1](../superpowers/plans/2026-09-14-stage5-1-catalog-history-governance-plan.md)已替换原链接正文；本次范围核对已将R1/R2收敛为当前不选入，原A–D/D1–D8继续保存在[延期存档](../superpowers/plans/2026-09-14-stage5-1-full-history-governance-v1-reference.md)。体验/验收及整合状态不变。



## 2026-09-11 Stage4体验功能重新盘点

按用户要求统计原定功能及中途优化，详见[45组功能与包含情况清单](stage4-experience-feature-inventory-2026-09-11.md)。按功能组合并连续修订：42组有对应功能/批次确认、3组保留部分确认（分类树连续UI、销售贡献/退货关注组合、Storybook）。不是45次独立测试或当前真实环境全覆盖确认。本轮比较开发工作树与20601的source：backend/app 177文件全同；frontend/src 257文件内业务实现全同，12个测试文件不同，指标说明Storybook故事文件仅开发工作树存在。业务功能已包含，开发展示材料同步缺口另记，未擅自同步或重跑测试。保留V35未验证及正式发布门禁边界，不重开已确认体验。本批无需Skill。

## 2026-09-11 七月及八月真实副本重新体验入口

用户明确要求体验七月整月及八月1–6日真实数据。使用原resume-review.ps1 -Experience -ExperienceOnly恢复b2f5960b07c74303ac2d26bf82d3be43，隐藏持久宿主PID24044，原数据库/存储不重建，API53904/前端20601，schema0028兼容。未重新导入、发布或迁移。新鲜API读取七月62条、八月1–6日12条日报记录，1202当前口径23件/USD807.78；浏览器七月总表已登录admin、显示31天完整发布与本月无需补齐。证据real-data-experience-restored.json位于july-baseline-20260910，原runtime新增私有真实数据体验账号.md供登录使用，不将密码写入仓库。

入口http://localhost:20601/?month=2026-07，产品分析按from/to限定七月或八月1–6日。当前数据及入口ready_for_user_review，既有user_verified保留，不把重新开放当新体验通过。56956独立虚构环境保留，两者不混用。V35历史证据缺口按用户同意保留；本轮不进入Stage5或发布验收。本批无需Skill，原恢复脚本与现有API/页面核实。



## 2026-09-11 用户确认保留V35证据缺口并完成本轮交付收尾

用户在明确了解“当前数据核对/已体验功能通过，不等于全部数据和功能完整验证；V35缺批准前全量快照是未验证而非已发现数据丢失”后回复“可以”，同意按保留项方式收尾。当前Stage4本轮交付收尾完成；既有development_complete及各项user_verified结论按原版本/样例范围保留。V35全量历史映射/排除前后不变继续标记未验证，用户同意保留仅解除本轮交付收尾阻塞，不等于证据补齐、风险消失或正式accepted。

适用边界：真实副本范围七月整月及八月1–6日；当前56956/c2704d51为独立虚构体验环境，不是七八月真实数据入口。沿用已有对账/体验证据，本轮不重新查询数据库或运行测试。未覆盖的全站导航、其他写操作和正式release_validation仍按原范围保留，不声称全量验证。成果仍未提交整合；不自动提交、合并、部署或进入Stage5。下一阶段须另行明确启动，本轮只完成记录收尾。本批无需Skill，仅用户确认和状态同步。本条覆盖此前“待用户决定保留V35缺口”的交接状态，历史核对记录保留。



## 2026-09-11 V35历史证据缺口核对结论

本轮仅读取已明确引用的sku-closeout-summary.json与sku-closeout-readonly.json，未读取原件、项目data/或业务数据库。summary记录8月1–6日六天daily_matches_previous均true，合计288件/USD13881.69/3416会话/118退货；1202历史别名43、当前44，仅增加1202-Light Blue-XXL、无删除。readonly文件包含current、v35_snapshot的单款式分析及daily/unmatched等响应，不含批准前V35全目录mapping/exclusion快照。上述是既有证据内容复核，不是新鲜数据库对账，也不声称已穷尽所有备份位置。

已拆分SKU修复计划D的混合复选项：V36批准及业务对账记完成，V35全量历史不变继续未验证。建议下一步由用户决定：是否允许将该历史证据缺口作为明确保留项，继续Stage4交付收尾；不把保留视作验证通过，不自动进入Stage5、accepted或发布。若要求补齐证据，则需明确可用的批准前备份/快照来源后再按范围核对，不能用当前状态重建批准前事实。现有已通过体验与定向权限/导航证据不撤销、不重复。本批无需Skill，仅证据文件范围审阅与计划纠偏。



## 2026-09-11 原隔离服务恢复与剩余定向检查

按用户授权恢复原c2704d51实例：数据库/存储/网页账号均保留，API14815、前端56956、Worker已启动。仅轮换容器内clsen_live_runtime连接密码，保留原权限及REQUIRE SSL，私有配置限原runtime；初次恢复误设p0_catalog，发现原Catalog里程碑使用legacy_parser后已纠正并重启三个自有进程，最终与原模式一致。恢复脚本位于独立父目录restore-original.py，进程记录restored-processes.json；未重新初始化或迁移。

写权限专项：viewer校验/提交/撤回均403 role_forbidden，viewer与data_manager创建账号均403，admin缺CSRF请求403 csrf_invalid。探针使用不存在的导入999999；首次撤回缺reason返回422，补合法reason后403，不将422当权限通过。证据stage4-closeout-write-denials.json。恢复后目录仍V3、导入3 approved、批量任务1待发布2/失败0。浏览器实核审核3→返回维护及维护历史找回批次3/revision6，目录版本入口显示V1/V2/V3；旧候选修订2相对当前3明确禁用开始审核。上轮3项导航组件通过结果沿用；此前用户角色与筛选体验user_verified保持。

本轮授权的恢复及上述写拒绝/目录返回路径检查完成，未发现新增产品缺陷；不扩大为全站所有路由、所有写操作或正式发布门禁通过。V35批准前完整快照证据仍缺失；Stage4不标记accepted，不进入Stage5。Skill沿用systematic-debugging处理原服务恢复及探针参数排错；无业务代码修改、真实数据操作、提交合并或完整测试。



## 2026-09-11 Stage4收尾定向核对

用户同意执行收尾核对。开发工作树codex/stage4-1-app-shell保留未提交成果。本轮检查catalog_common/imports：写操作有会话/CSRF上下文，校验和提交显式限制admin/data_manager；此前角色读接口与用户体验结果沿用。新鲜写权限拒绝探针在首次连接API14815即WinError10061，未发送写请求，不能记通过；独立数据库容器仍运行，不自行重建实例或重置数据。该项需恢复原API后补测viewer校验/提交拒绝、viewer/data_manager账号管理拒绝及实际响应，不将源码审查代替实测。

导航定向检查首次由run-dev-check调用pnpm时触发依赖状态检查并被非TTY阻止，未同意清理/重装依赖；改用现有runtime的node+vitest限定CatalogNavigation.test.tsx。发现第三项旧fixture只返回items且匹配不带查询串URL，缺少新baseline/range/impact，旧标题仍为待我处理；仅修正该测试文件并同步runtime，同文件3项通过。覆盖返回主档的搜索/排序/分页/视图与身份切换重置、viewer管理导航隐藏、待处理→审核→返回来源路径。产品代码未改，无需用户重复体验；这不是全部F-11导航或发布验收通过。

V35证据结论：既有记录支持1202历史身份仍可读，不能证明V35全量映射/排除在批准前后完全一致；缺批准前完整摘要，当前重算不能补回历史证据。Stage4关闭条件：完成原实例恢复后的写权限拒绝实测，限定并完成F-11剩余导航核对；V35缺口须找到可用批准前证据，或由用户明确接受作为未验证历史项保留。当前Stage4尚未关闭，不进入Stage5；正式全量发布验证仍在部署准备。Skill：systematic-debugging用于验证环境失败及过期测试fixture根因定位。无提交、合并、部署或真实数据改动。



## 2026-09-11 角色权限与返回筛选体验通过

2026-09-11 用户明确“体验通过下一步”：本专项更新为 development_complete / user_verified，适用独立实例c2704d51、目录V3。确认范围：商品主档搜索/排序/视图进入商品卡再返回保留，viewer/data_manager/admin的本轮入口权限体验及跨账号筛选重置；覆盖本节准备时待体验状态。依据为用户亲自确认及上轮role-review-preflight.json，不重跑未变更检查，不扩展到未交接的写接口或全部导航。

下一步进入Stage4收尾核对，暂不安排重复人工体验：①F-11剩余导航/写权限边界由代理按受影响路径定向核对，仅发现问题再修复并交接复体验；②V35全量历史映射/排除快照缺少批准前完整摘要，仍属证据缺口，不能通过当前快照或重做演练补称历史已验证；③整理剩余项后再明确Stage4关闭条件，正式发布验收仍留部署准备，不进入Stage5。此处是下一步安排，不声称上述核对已完成。本批无需Skill，仅用户确认、既有计划核对及记录更新。

用户批准下一专项。限定独立虚构实例c2704d51（56956/API14815）、目录V3，现有100/200两款数据已就绪。通过管理员API新增任务专用viewer与data_manager账号，保留现有admin；完整登录名与密码仅放该runtime的“角色体验账号与步骤.md”及role-review-credentials.json，不写仓库。只读接口核实：admin四项均200；viewer商品列表200、目录审核/批量审核/账号管理403；data_manager前三项200、账号管理403，详见role-review-preflight.json。浏览器已核实/catalog主档V3及搜索、排序、视图控件。

状态ready_for_user_review：用户先搜索100、切换商品名称排序和批量表格，进入商品后用站内返回，检查上下文保留；再逐一退出并用viewer/data_manager/admin登录，体验可见入口及管理页权限，最后恢复admin。跨账号预期筛选重置。当前仅2款，不安排跨页体验；写操作权限、完整导航/F-11及其他筛选链路未由本轮只读检查证明，不扩大覆盖范围。账号切换共用浏览器会话，应顺序操作。未代用户体验、未修改产品代码、未发布或重跑测试，正式验收不变。本批无需Skill（独立账号准备与入口核实）。




## 2026-09-11 批量审核失败重试体验通过

2026-09-11 用户在版本记录页明确“体验通过”，本项更新为 development_complete / user_verified，覆盖本节准备时的待体验状态。只读核实独立实例 c2704d51、任务1/revision4 已 completed、待发布2/失败0；原成功项目1的 dataset4/version4/validation1、attempt_count1 与 operation_token 均保持不变，失败项目2重试后生成 dataset5/version5/validation2、attempt_count2，失败原因已清空。确认范围为本虚构样例的失败提示、单项重试、结果刷新与版本记录找回，不扩展为真实数据库繁忙专项或正式发布验收。证据：该 runtime 的 batch-retry-user-verified.json。下一项建议为剩余角色权限及返回筛选上下文专项，V35全量历史快照证据待办仍保留；本轮未启动下一专项。本批无需 Skill，仅结果核对与体验记录更新，无代码修改或测试重跑。

用户同意准备下一项。独立虚构实例 c2704d51cd984250b06483e943226d11（前端56956/API14815）新增任务1，2099-10-01/02的SYNTHETIC文件为批次4/5。任务revision2、completed_with_exceptions：项目1待发布（dataset4/version4/validation1、attempt_count1），项目2失败（retryable_failure、attempt_count1、retry_allowed=true，尚无草稿）。使用一次性进程内BusyOnce注入DatasetTransactionBusy，由现有BatchReviewService记录真实失败状态；未直接写状态、未修改在线服务或真实七八月数据。注入进程已结束，页面重试走正常在线流程，不代表真实数据库繁忙故障专项已验证。

浏览器已核实管理员会话、待发布1/失败1、失败原因“服务暂时繁忙, 可稍后重试。”及第二行“重试”按钮。入口 http://127.0.0.1:56956/review/batch/1 。用户无需上传，点击第二行重试，预期待发布2/失败0，第一项version4与attempt_count1保持不变，再由版本记录找回两份草稿；本轮未代重试或发布。状态ready_for_user_review，重试结果待用户操作核实；此前暂停恢复与正式忽略恢复user_verified不重复。证据在该实例runtime的batch-retry-ready.json，准备脚本位于上级prepare-batch-retry.py。无产品代码改动或测试重跑，本批无需Skill（现有流程与独立虚构样例准备）；正式发布验收仍待部署准备。


## 2026-09-11 正式忽略确认与恢复入口修复

2026-09-11 用户明确“体验通过，下一步是”：正式忽略、恢复到草稿、重新映射、批准解除忽略完整路径记为development_complete/user_verified，适用新独立实例c2704d51、批次3/revision6、目录V3；覆盖本条此前恢复路径待确认状态，历史准备记录保留。沿用上一轮已核实的正式归属style2/sku12、ignored为空证据，不重新跑测试。下一项建议为独立虚构环境中的批量审核失败重试（此前暂停/恢复已通过，不重复）；该项尚未准备，不称入口就绪。之后保留多角色权限与返回筛选上下文专项、V35全量历史快照证据待办；不自动进入Stage5或正式发布验收。本批无需Skill，仅用户确认与计划更新。

2026-09-11 用户在56956/catalog/imports/3反馈“已完成”。本轮只读核实独立实例c2704d51的批次3为approved/revision6、生成目录V3；100-NAVY-L决定mapped，owners正式归属style2/sku12、ignored为空、drafts为空；商品卡确认款号100、NAVY/L、内部展示SKU SYNTHETIC-100-NAVY-L、seller_sku_count=1。正式忽略→恢复草稿→重新映射→批准解除忽略的操作闭环完成，记录用户操作完成及接口核实结果；不将“已完成”扩大为正式发布验收或其他环境体验通过。原正式忽略user_verified保留，恢复路径已完成操作、整体体验确认仍按用户明确反馈记录。本批无需Skill，只读核对及文档更新，无代码/业务数据写入或测试重跑。

2026-09-11 用户同意继续正式解除忽略体验。限定新独立实例c2704d51、草稿3：核对款号100/NAVY/L候选后，补内部展示SKU SYNTHETIC-100-NAVY-L并保存精确映射，执行目录业务校验。当前revision3/validated、validation_run3、issues为空、can_submit=true；owners显示草稿mapped，正式归属仍空，V2正式忽略及原因仍保留。交接用户刷新http://127.0.0.1:56956/catalog/imports/3，核对映射后提交审核、生成批准预览、填写原因并确认批准。尚未提交或批准，不预先标记解除忽略或user_verified。下一次核对以实际生成版本号为准。本批无需Skill，现有API准备虚构草稿与校验，无业务代码改动或全量测试。

2026-09-11 用户反馈“操作完成”。只读核实新独立实例 c2704d51 的批次 #3 已到 revision1/needs_attention，100-NAVY-L 的 identity_decision=null、target=null，恢复原因“恢复到待审核”；正式目录修订仍为2，owners仍保留V2的原忽略原因。记录恢复到草稿操作已完成、结果符合预期；未重新映射或批准新目录，正式解除忽略仍待后续体验。用户本次报告操作完成，不扩展为整个恢复闭环或正式发布验收通过。本批无需Skill，仅只读核对和状态记录，未改草稿或重跑测试。

用户在独立实例 `0dc6619a3118446ea42f5d4893baafe5` 的批次 #2 明确“体验通过”。只读核实批次已批准、目录 V2 生效，`100-NAVY-L` 仅存在正式忽略记录及原原因；该“正式忽略”路径记为 `user_verified`，不扩展为恢复路径通过。

继续生成 V2 后续草稿时发现正式忽略项只进入 candidate payload 的 exclusions，不进入 mappings；而“恢复到待审核”仅能从 mappings 行触发，造成正式忽略后没有恢复入口。修复 `build_catalog_candidates`：保留 exclusion 的同时生成无正式目标的 mapping candidate，使工作簿投影得到 `identity_decision=excluded` 的可审核行。目标测试先失败（StopIteration）后通过；`backend/tests/unit/catalog/test_candidates.py` 6 项通过，未执行全量回归。

为避免运行中旧实例热加载风险，使用修复后的同一 source 新建独立实例 `c2704d51cd984250b06483e943226d11`（前端 `http://127.0.0.1:56956`、API 14815、独立数据库）。仅用系统虚构 seed 自动复现用户已确认的 V2 正式忽略，生成恢复草稿 #3。新鲜接口核实草稿为 `validated`、可编辑，`100-NAVY-L` 显示正式忽略原因和 V2 归属证据，可执行恢复。状态：正式忽略 `user_verified`；恢复修复 `development_complete / ready_for_user_review`。Skill：`systematic-debugging` 用于根因追踪，`test-driven-development` 用于红绿目标测试，`verification-before-completion` 用于新鲜接口与测试证据。未改七八月实例、未提交/合并/部署或执行发布验收。

## 2026-09-11 独立正式忽略恢复演练准备

按用户“继续下一步”推进本项。新建独立实例ignore-recovery-20260911，Run ID 0dc6619a3118446ea42f5d4893baafe5，独立数据库clsen_data_test_0dc6619a3118446e和storage；复用当前source/依赖，不读取或复制七八月业务数据。仅运行原脚本ExperienceOnly的schema初始化与系统虚构seed，没有E2E/全量验收。真实localhost:20601不变。新入口http://127.0.0.1:34491/catalog/imports/2，API17238，完整管理员账号catalog-live-admin-0dc6619a3118446ea42f5d4893baafe5，凭据在新runtime的experience-credentials.json。

已核实目录V1、草稿2/revision1。虚构100-NAVY-L内部展示SKU已补为SYNTHETIC-100-NAVY-L，唯一阻断是映射决定未填写；尚未排除/提交/批准。用户先选排除、保存、校验、提交、预览批准，确认正式忽略后再准备新基线恢复草稿。恢复草稿不提前解除正式忽略。入口HTTP200、API权限和数据状态已核实；状态ready_for_user_review，正式忽略与恢复均未user_verified。步骤文件D:/CLSEN_Stage4_RealDataReview/ignore-recovery-20260911/体验步骤.md，初始及准备后响应保留在新runtime。首次启动参数Products不支持Experience、路径斜线未归一导致安全检查拒绝，修正专用脚本为Catalog及绝对归一D盘路径后初始化成功；未放宽安全检查。本批无需Skill，现有流程与虚构样例准备；无业务代码修改、提交合并、Stage5或发布验收。


## 2026-09-11 六月虚构演练污染默认查询修正

用户反馈默认待归属出现六月SYNNEW9501-Blue-S并授权优化。根因：演练仅按日期/标题区别，仍在真实体验实例内发布；默认范围还取历史数据集起点。此隔离方式不充分。后续虚构演练必须使用独立实例/数据库，不得继续向july-baseline-20260910真实体验基线发布样例；正式批准忽略恢复待独立环境准备，旧虚构样本历史保留，不扩展本轮清理范围。

本轮限定维护同Run ID b2f5960b07c74303ac2d26bf82d3be43、dataset81/version82/2026-06-01。校验容器所有权、数据库名、单行SYNTHETIC SKU、2件/USD119.98、无活动草稿后，在事务中移除精确当前发布指向并更新修订、写audit_events（synthetic_exercise_unpublished，operation c55531ee-5b9c-49b8-bd88-afdf678a5041）。没有删版本/原文件/事实行，没有替换成零值日报；全部其他发布指向前后相同。现有API没有撤回接口，本次为用户授权的隔离实例专项维护，非新增通用撤回功能。首次runtime锁权限不足、第二次用户名字段不符，均失败/回滚，修正后单次事务完成，未关闭触发器或修改权限。

业务工作树unmatched_repository.py仅调整默认开始日期：从当前快照有有效发布指向的成员取最早日期，没有则用覆盖结束日；显式日期范围不变。同步source并用原ExperienceOnly脚本重启。API定向验证默认2026-07-01至2026-09-11、待归属0；显式六月1日仍保留所选日期但无发布依据。八月1–6日daily-ledger与清理前完整响应一致，1202仍23件/USD807.78。其余七八月发布指向未变。证据在隔离根目录cleanup-synthetic-june.py、synthetic-june-unpublish-before.json、synthetic-june-cleanup-verification.json、synthetic-june-range-verification.json。

状态development_complete / user_verified。2026-09-11用户明确“体验通过”，确认本轮六月虚构样例退出当前发布结果及默认日期修正（july-baseline-20260910，目录V36，localhost:20601/catalog/unmatched，重启后的未提交修订）。历史版本82仍可追溯；本次确认不扩展为其他演练、全量历史快照核对或正式发布验收。此次仅同步体验状态，本批无需Skill，未重跑测试或修改业务数据。未做全量回归、提交、合并或发布验收。Skill：systematic-debugging，用于发布污染与默认日期来源排查。范围不扩展为其他演练已清理或Stage4已完成。


## 2026-09-11 SKU修复收尾只读核对（最新）

本轮用户授权收尾核对。原体验服务端口未监听，使用原 resume-review.ps1 -Experience -ExperienceOnly 恢复同一隔离实例，schema0028兼容，未重建或导入数据。当前目录V36下1202为23件/USD807.78，8月1–6日待归属0；与既有august-source-reconciliation.json逐日按Decimal比较，6日销量、金额、会话、退货全部一致，总计288件/USD13881.69/3416会话/118退货。证据：D:/CLSEN_Stage4_RealDataReview/july-baseline-20260910/sku-closeout-readonly.json与sku-closeout-summary.json。

历史口径纠正：V35加current事实组合被接口拒绝（analytics_identity_fact_combination_invalid），合法catalog_snapshot返回该版本不含八月1–6日经营报告，不能声称历史页面可重现22件/USD771.79；该数字仅为批准前已留存的当前口径结果。V35仍可读取1202的30个变体/43个来源别名，V36为31个变体/44别名，差集仅新增1202-Light Blue-XXL，无删除别名。这证明本商品历史身份仍可查询，不代替V35全量映射/排除快照前后逐项或摘要比较；因缺少本轮可用的批准前完整摘要，该证据待办保留。

E演练最新：6月1日当前发布版本82，SYNNEW9501-Blue-S在source_ref_id=null且candidate=not_started时被发现，1项/2件/USD119.98，符合无需先导出发现的预期。覆盖此前“批次86尚未发布”的准备状态；用户此前“明白”不扩展为明确体验通过，E仍ready_for_user_review。真实归属/加载路径原user_verified有效。下一项为正式批准忽略及恢复，尚未生成该演练候选，不能称批准/恢复已就绪；不得把虚构SKU关联到真实商品。

本批无需Skill（现有API只读对账及计划更新），未改业务代码，未重跑测试或正式发布门禁。Stage4整体及release_validation未关闭，无提交/合并/部署。


2026-09-11 E演练日期修正及空状态缺陷：用户截图同日待归属0，API核实批次85已发布版本81，但目录快照coverage_end限定截至当前日期，未来2099-05-01被排除。此样例不能证明新SKU发现通过。用户授权解决后，CatalogUnmatchedPage在无范围发布依据且无待归属事实时不显示零指标/无未归属成功提示；未来范围明确日期限制，其他空范围提示核对报告日期与发布状态。目标测试2项、ESLint及diff检查通过，源码同步隔离实例；systematic-debugging用于根因及回归。已只读确认2026-06-01无既有经营版本，准备明确SYNTHETIC样本批次86（上传、识别完成，尚未发布），SKU SYNNEW9501-Blue-S，2件/USD119.98。文件位于隔离目录exercises/sku-discovery-2026-06-01/20260601-BusinessReport-SYNTHETIC-SKU-DISCOVERY.csv；首次相同文件字节上传被duplicate_import拒绝指向85，随后仅修改标题加入演练日期区别于未来样本，保留旧样本。新入口http://localhost:20601/review-advanced/2026-06-01?report_type=business_report&batch_id=86，发布后核对/catalog/unmatched?from=2026-06-01&to=2026-06-01&return_basis=event_date。状态development_complete/ready_for_user_review，E仍待体验；真实8月1–6日确认继续有效。

## 2026-09-11 新发布SKU发现与归属衔接修复（ready_for_user_review）

2026-09-11 用户在8月1–6日1202产品总表明确“体验通过，进行下一步”：记录本轮加载优化及批准后1202路径为 user_verified（july-baseline-20260910、目录V36）。本轮只读API核实导入6已approved、修订28；1202销量23件、销售额USD807.78，范围内unmatched=0。未将确认扩展为全Stage4或release_validation；历史V35/日报逐日完整对账仍保留证据待办。下一步E独立虚构演练已准备：2099-05-01，SKU SYNNEW9501-Blue-S，2件/USD119.98，文件位于隔离目录exercises/sku-discovery-2099-05-01；batch85已上传并解析1行（parse baseline87），尚未发布。入口http://localhost:20601/review-advanced/2099-05-01?report_type=business_report&batch_id=85（已核实显示批次85识别确认，可点确认并解析继续；普通日期页在草稿建立前显示未导入）；发布后从同日/catalog/unmatched查询，应直接发现新SKU，不先生成目录导出。等待用户体验发布和发现路径。本批无需Skill，复用既定计划与现有API，未修改业务代码、未运行回归。

2026-09-11 审核工作台加载反馈：导入6摘要与来源证据首屏API抽查均约0.05秒；前端此前等待五类数据及全部分页齐备才显示工作台。现先显示摘要/状态及五类加载进度，剩余分页并行读取；完整同修订数据返回前不展示编辑/工作流操作或虚假零待办。目标组件测试2项、两文件ESLint通过，源码同步至july-baseline-20260910/source，待用户复体验。Skill：systematic-debugging。此项为加载体验优化，未证明所有请求或冷启动均无性能问题；未执行全量验收。本轮最初核对为修订27等待批准；用户操作期间页面已显示当前目录V36，此次加载优化未执行任何提交或批准。此前V35与待办记录为历史快照。

用户反馈无日期 `/catalog/unmatched` 一直停在核对状态。实际API约0.54秒，页面却串行等待34款审核候选读取完才显示主结果。已将当前事实/影响/来源清单与“已有审核候选”拆开加载：主清单先显示，候选区局部加载或局部失败重试。模拟候选请求不返回的目标测试、两文件ESLint及浏览器无日期入口核对通过；运行源码已同步，页面可立即看到13项、16件、US$614.84及1202的1件/US$35.99。状态 `development_complete / ready_for_user_review`，不改变草稿6、V35或批准边界。Skill：`systematic-debugging`，用于区分API耗时与前端等待链。

按[完整实施计划 v1.0](../superpowers/plans/2026-09-11-published-sku-discovery-and-assignment-fix.md)完成A–C开发，并在授权8月1–6日隔离实例准备D的1202归属草稿。`/api/catalog/unmatched` 现直接从当前发布事实发现没有目录证据的新Seller SKU，支持日期/退货口径、准确总数、分页、目录与发布基线、分币种影响及候选状态；GET不建草稿、不写目录。产品总表/款式详情补齐覆盖提示和同口径入口，待归属页显示完整影响、翻页、候选状态及返回路径，继续复用现有在线审核/校验/批准流程。

实际 MySQL 与浏览器核实：目录V35、发布修订35，2026-08-01至08-06共有13个去重待归属身份，影响16件、US$614.84和1件退货；`1202-Light Blue-XXL` 来自8月4日当前版本66，影响1件/US$35.99、`source_ref_id=null`。隔离实例已完整重启，入口 `http://localhost:20601/catalog/unmatched?from=2026-08-01&to=2026-08-06&return_basis=event_date`。归属草稿为 `/catalog/imports/6`：已新增1202 Light Blue/XXL稳定变体并预填精确映射，仍有其余12个未知SKU的24个阻断项；没有提交或批准，V35和产品22件/US$771.79保持不变。D等待用户业务确认，E等待本路径体验及独立虚构再发布演练。

定向验证：Python编译/Ruff通过，后端5项、前端13项目标测试通过；完整typecheck仅剩既有 `MergeDecisionMatrix.test.tsx:170` 可空值错误。未运行完整回归、双MySQL、E2E或部署验收，未提交、push、merge、部署或进入Stage5。实际Skill：`executing-plans` 按计划实施；沿用 `systematic-debugging` 根因证据。

2026-09-11 计划最初按A发现API→B候选审核衔接→C提示与入口→D归属修订→E复体验组织；上述最新记录覆盖“各批待执行”的旧状态。限定范围仍为8月1–6日，1202批准及其余未知项仍须业务确认，Stage状态不变。

用户要求“修复这个bug，先找出原因再给出解决方案”。本轮按先诊断/方案执行，未修改代码或数据。证据：1202-Light Blue-XXL已在8/4发布事实中，但当前V35无mapping/exclusion、catalog_source_refs也无记录。catalog_queries.list_catalog_unmatched只从catalog_source_evidence查未映射，源证据由目录导出/候选冻结流程收集；产品分析BUSINESS_BUCKETS_SQL直接从当前发布事实分类mapped/unmatched，因此报表→目录候选缺口造成指标未纳入款式且待归属空。根因是两条查询来源/更新时点不一致；报表导入成功不等于新SKU已建档。

方案：1.未匹配发现以当前站点/账号范围的当前已发布有效事实为准，与已批准目录按完整SKU匹配，复用分析口径；未生成目录证据也返回安全摘要与可追溯报告引用，不用GET写库，不依赖用户先导出，排除历史被替换版本及已批准排除。2.待归属页和产品分析显示真实未归属数量/影响与入口；未关联时明确商品合计不完整，不用SKU前缀冒充正式映射。3.从发现项进入现有候选、校验、批准路径，创建新目录版本；补齐1202 Light Blue XXL并核对八月其他缺口，保留老目录。4.定向验证新SKU首次发布/重传/发布替换、已有映射与排除、站点隔离、待办清除及重复数量；隔离环境验证1202当前口径23件/807.78、历史目录V35保持旧映射、日报合计不变。订单指标独立，不混入本修复。正式全量验收仍留部署准备。Skill沿用systematic-debugging。

## 2026-09-11 1202缺失归属根因补充

继续只读核对当前隔离库：1202-Light Blue-XXL的catalog_source_refs为0，当前目录V35的product_catalog_mappings为0，product_catalog_exclusions为0。确认不是被排除，而是尚未进入目录来源候选/已批准映射。源码catalog_queries.py的/unmatched仅查catalog_source_evidence，不直接扫最新发布报表；目录证据由catalog_exports.py冻结来源快照并persist_building后采集，因此最新报表已有SKU、产品分析无映射，待归属页却为空。根因是报表新增来源到目录候选更新/提示链路缺口，不能归因于销量字段或自行推测空格/XXL解析失败。待补齐来源候选并批准正确归属，同时修复新来源发现提示；本轮仅回答原因，无写入。

## 2026-09-11 1202销量23而页面22的定位

用户指出8月1–6日1202销量23、订单商品总数22，但产品页销量22。逐SKU对照授权经营CSV（8/2用纠错副本）和当前style26卡片：1202-Light Blue-XXL在8/4含表头记录5，销量1、订单商品数1、销售额35.99，未出现在当前style26别名/变体汇总中；其余9个源SKU销量均一致。关键1202-Cappuccino-M源销量2、订单商品数1，API销量2，排除销量字段错取订单数的解释。1202按源SKU前缀合计销量23、销售额807.78；当前页面22/771.79，差额1/35.99。

进一步/api/catalog/unmatched返回空列表，不能据此宣称待归属页已就绪；仍需核对新发布来源进入目录候选及归属链路，作为八月商品归属补齐的明确缺口。未修改身份、目录或发布数字。本轮完成差异定位，归属修复待继续，不能标已修复。证据august-z-20260911/1202-source-comparison.json、1202-card-check.json、unmatched-check.json。Skill：systematic-debugging，字段与逐SKU来源排错。

## 2026-09-11 八月数据查看体验确认及销量/订单口径说明

用户反馈“体验通过”，确认8月1–6日报/产品分析查看及覆盖说明（localhost:20601，report_date口径）为user_verified；未映射16件/614.84美元/1件退货仍待补齐，不扩展为全部归属完成。随后询问销量和订单定义与展示位置。源码核实销量units=SUM(units_ordered)，原字段“已订购商品数量”，产品总表/款式详情称销量，发布总表称订购数；total_order_items来自“订单商品总数”，已解析保留在源表/审核字段中，当前产品聚合没有订单指标，也没有从经营报告计算去重订单笔数。命名易混问题已记录为建议：统一销量（件），订单项与独立订单数明确区分；本轮只解释，未授权实施新订单指标。状态更新及源码核对，无数据/代码修改或测试。本批无需Skill。

## 2026-09-11 发布按钮确认与八月数据核对交接

用户确认发布按钮提亮体验通过，development_complete/user_verified，仅样式与可操作状态，不推断发布。按“下一步”准备8月1–6日真实数据核对：只读比较12份授权D盘CSV（8月2日经营使用CORRECTED派生副本）与当前daily-ledger，每日销量/销售额/会话/退货量全部相符，合计288件、13881.69美元、3416会话、118件退货。8月2日当前发布版本77，56件/2579.95美元/792会话/27退货，状态complete。

产品分析当前目录V35、report_date口径34款：已映射272件/13266.85美元/117退货/3386会话，未映射16件/614.84美元/1退货/30会话；API覆盖说明经营15条、退货1条来源未匹配，汇总与源合计可对账。产品页尚不能称全部商品数据就绪，应核对覆盖说明后安排归属补齐，不改身份或自动批准。本轮ready_for_user_review，纯只读核对，无数据写入、代码修改或测试。证据august-z-20260911/august-source-reconciliation.json及两个API快照。入口/products?from=2026-08-01&to=2026-08-06&sort=units&direction=desc&page=1&page_size=50&return_basis=report_date&fact_basis=current；仅1–6日非整月。Skill：Spreadsheets只读CSV与接口合计比较（Decimal精确加总）。其他待体验：批量失败重试、正式批准忽略恢复、F-11完整导航/权限；八月归属缺口需补齐。

## 2026-09-11 单文件重复体验确认及发布入口提亮

用户明确体验通过：2099-04-01虚构单文件重复行排除与校验（批次84/草稿80）记development_complete/user_verified，截图校验销售额169.97且进入待发布。此确认不代表实际发布。

新增UI反馈：“打开发布确认”偏暗，可点击时应亮起来。按用户截图及源代码内联核对，publish-gate泛化span样式将半透明说明色和上边距误施加到Button内部文字；改为仅容器直属说明文字。发布区可用按钮采用现有success-border浅绿背景、深色文字及细光圈，hover更浅，focus轮廓可辨；仅:not(:disabled)应用提亮，原权限/审核/发布条件不改。主工作树及七月source已同步热更新，Vite样式请求200、定向样式检查；纯CSS未运行测试或构建。状态development_complete/ready_for_user_review。Skill：product-design:index与product-design:audit，限于截图所示发布入口的可操作性与对比度内联检查，不扩展整页重设计。

## 2026-09-11 批量恢复通过与单文件重复演练

用户确认“体验通过，进行下一步”。任务3批量暂停恢复记development_complete/user_verified；当前API实核completed、待发布2、失败0。确认不覆盖实际发布或失败重试。下一项已准备2099-04-01的纯虚构SYNTHETIC经营文件：3行，第1和第3数据行完全相同，批次84/基线86/草稿版本80，未校验、未排除、未发布。状态ready_for_user_review。入口http://localhost:20601/review-advanced/2099-04-01?report_type=business_report&version_id=80 ，已实核页面；默认“仅看差异”开启导致无显示行，体验先关闭它，再排除第3行并运行草稿校验。预期有效2行、units_ordered=3、ordered_product_sales=169.97美元；原始3行留存。该场景手动排除源文件内重复，不冒充跨文件合并默认策略或自动识别/删除已实现。用户无需重传文件。

证据及样例：july-baseline-20260910/exercises/internal-duplicate-2099/preparation.json、workspace.json与CSV。只写独立演练草稿，真实七八月不变。本批无需Skill（现有接口准备虚构体验）；未改代码或运行测试。

## 2026-09-11 批量暂停恢复继续体验交接

按用户“继续”核实任务#3：API返回paused、revision2，两项批次68/69均queued，attempt_count0，无dataset/version，allowed_actions仅resume。使用2099-03-01/02明确SYNTHETIC虚构文件，与七八月真实数据隔离。已提供http://localhost:20601/review/batch/3：用户点击“恢复批量处理”，预期两项推进至待发布，然后从版本记录找回；不点击发布。只核实并交接，未代点击恢复、未重新导入或创建重复任务。状态ready_for_user_review，失败重试仍单独待体验；证据exercises/batch-pause-resume-2099/current-review-check.json。本批无需Skill（现有演练状态核对），无测试/代码改动。

## 2026-09-11 审核恢复体验确认与后续清单

用户反馈“体验完成，后续的体验还有哪些”。确认本轮指定文件重新审核入口与完全相同重复行默认保留目标行体验完成（development_complete / user_verified），范围为localhost:20601、批次83恢复路径及局部合并决定；不推断用户已经实际合并或发布，不扩大为八月总表数字已核对通过。

最新待体验清单：①批量暂停/恢复与失败重试（任务3此前已准备，继续前复核当前状态）；②同一文件内部重复（真实七月样本未覆盖，须独立标记虚构样例）；③正式批准忽略及其恢复（草稿排除恢复已通过，不重复）；④全部导航遗漏F-11及viewer/data_manager/admin的权限、返回路径与筛选上下文；⑤八月新增数据在总表/产品分析的最终业务核对，含8月2日状态及纠错数字。来源精确版本直达/物理CSV行定位仍属增强待办，不冒充已具备的待体验功能。F-01同操作重放、批量任务2至待发布、XLSX往返、分类、趋势等已有确认不重复安排。建议下一项先批量暂停/恢复。本轮仅核对主计划与更新状态，无测试或数据操作；本批无需Skill。Stage4整体尚未关闭，正式发布验收留部署准备。

## 2026-09-11 完全相同重复行默认保留目标行

用户提出两侧完全相同时默认保留一行。MergeDecisionMatrix 在完整预览返回后，对全部字段严格相等且非空字段集的记录（包含所有分页）默认 keep_target，自动填写“系统默认：两侧全部字段完全相同”及版本/行来源依据；任意字段差异仍待人工选择。可改选或编辑原因；改选会替换自动依据，手填依据保留。仅预填合并命令，仍需确认生成草稿，不自动发布。

状态 development_complete / user_verified，适用 stage4-1-app-shell 未提交代码和 july-baseline-20260910/source（localhost:20601）。重复矩阵及导入流程24项目标测试通过，覆盖跨分页默认、非展示字段差异、人工覆盖及原合并/重建路径；局部ESLint通过。已同步前端热更新，服务健康200；无真实数据合并或发布操作，无完整回归。本批无需Skill（现有合并表单局部默认值优化）。


用户于2026-09-11回复“可以”，确认本项局部优化体验；仅覆盖完全相同重复项默认保留目标行及可修改的默认依据，不扩展为其他恢复流程、Stage4整体或正式发布验收通过。

## 2026-09-11 错误文件重新上传后的审核恢复

用户反馈上传错误表格后，重传原文件仍回到旧信息。定位日期工作台的冲突/重复结果仅链接日期当前工作区，未携带来源批次；高级审核同时默认恢复旧活动草稿，已发布重复文件也只有查看入口。现增加 batch_id 指定原文件恢复路径，优先于旧草稿/浏览器队列；上传结果明确“文件已保存但尚未替换”，提供“核对文件并继续审核”；已发布重复文件可显式“用此原始文件重新审核”。保留去重，替换/管理员重建仍经目标预览、确认、校验与人工发布，历史不删除。

适用：stage4-1-app-shell 未提交成果及 july-baseline-20260910/source，localhost:20601。development_complete / user_verified；用户本轮确认恢复路径体验完成。3个受影响前端目标共87项通过，路由现场发现初始化丢失batch_id后修正并复测目标；TypeScript和三文件ESLint通过。正式开发脚本被pnpm依赖自动安装检查阻止，未安装/清理依赖，改为直接运行已有vitest等效目标。未运行完整回归、未提交或进入Stage5。

现场：修正批次83恢复链接保持batch_id=83，显示人工识别及/api/imports/83/raw-file；旧标签仍显示失败批次82队列，刷新/清空队列不删除服务器历史。本轮只打开识别预览，未重新解析、替换或发布真实数据。前端已同步并热更新，服务健康200。入口：http://localhost:20601/review-advanced/2026-08-02?report_type=business_report&batch_id=83 。Skill：systematic-debugging，用于来源选择与恢复路径定位。


## 2026-09-11 八月2日总表历史失败误阻断修复

实际重启后接口已核实：2026-08-02 status=green，两类报告已发布，draft_report_types=[]、reasons=[]。状态为 development_complete / ready_for_user_review。

原因：旧失败批次71及82仍计入日历阻断，修正版83已发布；82在发布后重试使失败更新时间晚于发布。现按同站点/日期/报告类型的当前发布版本实际version_input_batches来源判断：采用创建时间更新的批次后，旧失败不再阻断；新批次失败仍阻断，历史记录及完整性错误保留。新增实际SQL测试覆盖恢复、更新失败与站点/类型/日期隔离；与已有日历测试共7项通过。同步七月运行副本并重启，待实际接口验证及用户复体验；未全量回归或进入Stage5。Skill：systematic-debugging。


## 2026-09-11 八月2日尾行修订与发布

用户明确授权删除错误792尾行及空行。仅修改D盘派生副本20260802-BusinessReport-CORRECTED.csv，删除含表头记录42/43，逐字段确认前40条记录保持一致；原文件与初始副本保留。新增批次83、解析40行、草稿/发布版本76，经源副本行数、销量、金额核对及业务校验发布成功；当前API返回published。销售额2579.95美元、销量56件、会话792次；这里792来自保留商品记录汇总，已删除的尾行未计入。证据august-z-20260911/aug02-correction.json及publication-results.json。入口http://localhost:20601/?month=2026-08；本项ready_for_user_review，不自动记体验通过。未改代码或运行完整回归，不进入Stage5。本批无需Skill，沿用已定位的尾行问题进行授权副本修订与正常审核发布。


## 2026-09-11 八月总表与8月2日解析原因

用户要求在总表看到八月数据。当前接口核实8月1日、3–6日经营及退货均已发布，8月2日退货已通过副本行数/数量核对、校验与重新审核确认发布（version71）；8月2日经营仍未导入成功。只读检查D盘经营副本：含表头记录42为22列全空，记录43仅“会话数 - 总计”为792，其余为空；前40条为商品记录。这两条尾部记录触发必填整数invalid_integer。尚未确认792用途，不删除或填零；需业务确认后仅修订副本。原文件与七月数据保留，未进入Stage5。发布证据位于august-z-20260911/publication-results.json；本批沿用systematic-debugging定位解析与发布状态。


## 2026-09-11 八月1–6日追加导入

用户授权读取 Downloads/z 并确认八月文件已脱敏、同一美国站账号。12份CSV已原样复制到 D:/CLSEN_Stage4_RealDataReview/july-baseline-20260910/august-z-20260911，保存哈希与逐文件结果。退货6份共118行新增批次76–81、草稿70–75，未发布。经营6份命中已有文件：批次70（8月1日）已发布，72–75（8月3–6日）待发布，保留原状态；批次71（8月2日）此前处理失败，本次通过正常识别/解析重试返回 invalid_integer（尝试82、修订2），尚无草稿，不能标记导入成功。未修改原始数值，待定位不合法整数字段后修订副本。导入记录见上述目录 import-results.json。当前为部分就绪，待用户审核；不扩展为体验通过。七月发布数据保留，未进入Stage5。本批无需Skill（原样副本及既有导入接口操作）。


## 2026-09-11 完整体验第一项：批量暂停与恢复

使用仓库虚构经营报告创建 2099-03-01/02 两份明确标记的隔离演练文件，导入批次 #68/#69 已解析；批量任务 #3 在任何项目推进前由服务端从 `running` 暂停为 `paused`，当前两项均为 `queued`，未生成草稿或发布。入口 `http://localhost:20601/review/batch/3` 已实核显示“已暂停”、两项排队中及“恢复批量处理”。本项为 `development_complete / ready_for_user_review`；用户点击恢复后应自动推进两项至待发布，仍不会自动发布。证据位于七月任务目录 `exercises/batch-pause-resume-2099/preparation.json`。七月真实数据和既有草稿未改，Stage 4 整体仍未关闭，不进入 Stage 5。

Skill：systematic-debugging，用于核对任务状态转换、队列停点与恢复后的非发布边界；未运行完整回归。

## 2026-09-11 F-01 体验确认与完整功能体验安排

用户明确“体验通过”，F-01 解析同操作重放由 `ready_for_user_review` 更新为 `development_complete / user_verified`：批次 #65 两次相同令牌调用返回同一解析尝试 #65、基线 #65、修订 1，未生成草稿或发布。当前用户要求继续体验完整功能。已只读核对七月任务目录中的 62 份授权副本，未发现文件内部完全相同的重复行，因此自然文件内重复记为“真实样本未覆盖”，不得伪称通过；后续使用明确标记的虚构重复样例独立体验。其余待准备：批量暂停/恢复与失败重试、正式批准忽略与恢复、完整导航及 viewer/data_manager 权限与返回筛选上下文。Stage 4 整体仍未关闭，不进入 Stage 5。

本批沿用 systematic-debugging 的 F-01 证据口径；状态更新与样本只读核对未运行完整回归。

## 2026-09-11 F-01 解析同操作重放体验准备

使用仓库虚构经营报告在七月隔离测试库创建 2099-02-01 批次 #65，第一次解析生成尝试 #65 / 基线 #65 / 修订 1 / 2 行；使用完全相同的操作令牌和请求再次调用后，返回完全相同的尝试、基线和修订，无权限错误或重复基线。机器证据位于 `D:/CLSEN_Stage4_RealDataReview/july-baseline-20260910/exercises/parse-replay-2099/replay-evidence.json`。本批只停在解析基线，未生成草稿或发布；2099-02-01 页面应继续显示无业务数据。F-01 为 `development_complete / ready_for_user_review`，等待用户确认幂等重放结果与停点；不以普通页面点击伪造网络响应丢失。七月日报与现有草稿未改，未进入 Stage 5。

Skill：systematic-debugging，用于确认只追加记录的共享锁根因、隔离重放条件与同结果证据。

## 2026-09-11 来源证据补齐体验确认与剩余体验

用户明确反馈“体验通过”。来源证据新增的来源文件名、含表头的原表记录序号、原始退货时间和导入来源时区，按七月隔离环境 Run ID `b2f5960b07c74303ac2d26bf82d3be43` 记为 `development_complete / user_verified`。该确认替代下方本项 `ready_for_user_review`，但不扩展为物理 CSV 文本行定位或精确版本自动展开已经完成。

当前不再安排已确认的商品身份与分类、日报与历史版本、产品总表及款式趋势、XLSX 往返、同文件去重、人工跨文件冲突、批量任务 #2、草稿排除恢复及本次来源证据展示。后续仍需逐项准备并体验：F-01 解析失败同操作重试；自然/文件内重复；批量暂停恢复与失败重试；正式批准忽略及恢复；完整导航遗漏（含 viewer/data_manager 权限、返回路径和筛选上下文）。物理 CSV 行定位和精确版本直达作为来源追溯增强待办，不阻塞本次展示确认。Stage 4 真实数据试用整体尚未关闭，不进入 Stage 5；正式发布验证仍留部署准备。

本批无需 Skill；仅根据用户明确反馈更新体验状态，未修改代码、数据或运行环境。

## 2026-09-10 来源证据文件与原始时间补齐

用户授权继续后，已沿版本行的original_parsed_source_row_id读取不可变解析快照，仅向页面返回文件名、原表记录序号、原始return-date和导入时来源时区。关联限定当前站点；无原始关联时明确缺失，不用系统记录ID推算行号，不返回订单等其他原始字段。原表记录序号含表头，源解析器不保存多行CSV的物理文本行号，本轮不伪称物理行定位；精确版本自动展开与物理文本行定位仍保留后续项，现有版本入口按日期/类型筛选。

development_complete / ready_for_user_review，七月原Run ID b2f5960b07c74303ac2d26bf82d3be43重启READY。入口 http://localhost:20601/catalog/styles/11 → 展开Seller SKU → 查看来源明细。实际API与浏览器核实2112-Black-L：文件亚马逊物流买家退货-20260707-80710020642.csv，记录5（含表头），原始时间2026-07-08T00:45:40+00:00，导入来源时区America/Los_Angeles，报告归属7月7日；历史日期口径未改、原件与业务数字未改。

验证：新增时间提取/缺失安全降级6项目标检查、已有商品卡3项组件检查、局部ESLint通过。前端正式快检入口受pnpm依赖状态检查阻断（尝试要求重装），未安装或清理依赖，改用已有node_modules的vitest执行同一目标成功。Ruff新增部分已修正；queries.py原有分类查询第183行E501仍属无关存量问题。未运行完整回归或发布门禁；保留数据与草稿、不进入Stage5。Skill：systematic-debugging，用于来源链路与记录序号口径核对。体验状态待本次用户确认，不沿用首批来源说明的历史确认。


## 历史收尾记录（2026-09-10；旧状态已被顶部2026-09-14记录覆盖）

- **草稿排除与恢复：user_verified。** 用户明确“体验通过，可以继续下一步”。七月环境 `/catalog/imports/5` 实核修订4，2112-Black-L恢复为未决定，已批准归属仍为STYLE #11 / SKU #2。保留演练草稿，不提交或批准；本次确认不覆盖正式批准忽略及其恢复。
- **已确认项目不重复安排：** 七月产品身份展示、指标说明弹窗、表头排序、颜色/尺码明细、分类代码修改、标题分类与主/细分类筛选、XLSX上传至预览及反馈修复、来源证据首批展示/日期说明、批量任务#2推进至待发布及找回、草稿排除恢复。此前折线图及Storybook、日报/历史版本查看、同文件去重和人工跨文件冲突按原版本与交付范围保留确认，不扩展为七月所有异常场景通过。
- **本轮导航定向审查：** 当前管理员会话实走草稿#5→返回批量维护，已有审核批次可找回#5/修订4；版本记录→任务#2正常打开已完成任务（待发布2、失败0），提供返回版本记录和查看全部待发布草稿。上述入口没有发现遗漏；未覆盖全部角色、页面和筛选上下文，不关闭整体导航排查F-11。
- **下一项优先：来源证据精确追溯补齐。** 尚缺实际文件名、物理CSV行号、原始时间及原始时区；当前版本链接只按报告日期/类型筛选，不能直接定位确切来源版本与原表行。实现后只复体验受影响来源路径。
- **仍保留专项待办：** F-01解析失败同操作重试的真实场景；自然/文件内重复；批量暂停恢复与失败重试；正式批准忽略及恢复；其余导航/角色/返回筛选上下文。未准备样例的项目不标记就绪。中途优化继续纳入既有记录，销售贡献/退货关注快捷视图及分类树历次UI修订的独立确认范围仍须核对，不凭相邻确认自动升级。
- **环境与阶段：** localhost:20601，七月持续导入隔离环境，Run ID b2f5960b07c74303ac2d26bf82d3be43。开发成果仍在codex/stage4-1-app-shell未提交工作树；Stage 4真实数据试用整体尚未关闭，release_validation留部署准备，不进入Stage 5。保留原文件、数据和演练现场。

本批使用 product-design:audit，内联审查草稿及批量任务找回路径。只读浏览器检查与文档状态更新；无代码修改、数据写入、重启或回归测试。下方日期记录保留为历史，旧环境地址和旧“待体验”不代表当前状态。


2026-09-10 忽略/恢复演练准备：实核当前目录V35、旧export4基于V34，已新建export5并生成独立在线审核草稿#5（基于V35、修订0、34款222SKU）。本轮限定既有映射在草稿中排除与恢复，非新增真实来源，也不覆盖正式忽略批准场景；不批准即可保持现有商品关联。目标2112-Black-L，入口/catalog/imports/5→SKU映射→取消仅看待处理→搜索SKU→排除并写演练原因/保存→归属冲突与恢复→恢复审核。草稿已就绪，浏览器筛选操作遇到CDP超时，尚未核实目标行最终展示，不声称全路径就绪或体验通过。不得批准此演练草稿，保留现场。本批无需Skill，未改代码或运行完整回归。

2026-09-10 批量审核任务#2获用户明确“好的，体验通过”，user_verified：两份LOCAL-TEST报告完成预检/批量审核进入待发布，查看待发布草稿及从版本记录找回任务按本轮交付范围确认。截图显示待发布2、失败0、人工处理0。确认不包含实际发布、暂停/恢复或失败重试；不推断额外数据操作。测试日期2099-01-01/02，与真实七月分开，现场保留。此前本项ready_for_user_review由本记录更新，不重复安排。整体Stage4试用与正式发布验收仍未整体完成。本批无需Skill，仅更新确认记录。

2026-09-10 来源证据首批展示/日期说明获用户体验通过，user_verified；原文件精确定位和时区完整展示仍待补齐。后续批量审核已准备：七月独立库使用明确LOCAL-TEST文件，取7月1/2经营副本，仅首条标题添加测试标记，字段比较确认其他单元格未变；测试归属2099-01-01/02，不代表真实日期。上传批次63/64完成识别，批量任务#2预检2项可执行、目标为空，/review/batch/2已实核，ready_for_user_review。未确认运行、生成草稿或发布；旧预检#1因识别前创建为人工处理，保留但不用。原七月发布数据不改。准备证据在任务exercises/batch-review-2099。批量执行仅至待发布，不自动发布。本批无需新Skill，沿用CSV结构保留核对约定。

2026-09-10 来源证据可追溯性优化首批：用户反馈2112-Black-L无法在实际退货表找到。已明确报告归属日与记录事件日期，系统版本/记录编号折叠并注明非文件行号；提供按报告日/类型跳转版本页及安全完整SKU复制，标题安全标记补说明。接口未提供原文件名/原始行号/原始时间和时区，明确显示不可定位及不换算，不伪造原表行号。3项组件检查和ESLint通过，七月source热更新，入口/catalog/styles/11展开来源明细，ready_for_user_review。原文件直达/精确行定位和时间字段补齐保留待办，整体方案未全部完成；无数据改动/重启或Stage5。本批沿用systematic-debugging核对日期与内部编号。

2026-09-10 XLSX往返体验完成：用户在导入#4反馈“体验完成”，本轮上传→重新校验→提交审核→生成预览按已交付范围记user_verified，包含上传兼容与提交入口修复。范围止于预览，不推断已批准、新目录版本或额外数据变化；此前待复体验记录由此更新。下一项为有实际数据的批量审核，尚需准备任务，不因本次确认自动创建/运行任务。整体Stage4试用与发布验收状态不变。本批无需Skill，仅记录确认，未重跑检查或操作数据。

2026-09-10 XLSX提交入口修复：导入#4解析后status=validated但validation_run_id为空，页面提前允许提交，与仓库提交前置不一致。详情API现在仅正式校验记录存在时开放提交，工作流提示先重新校验。草稿修订2保留，未代提交/批准。目标详情检查1项、Ruff、TS通过，七月原RunID重启READY；待用户重新校验→提交→预览。development_complete / ready_for_user_review；沿用systematic-debugging排查，无完整回归或Stage5。

2026-09-10 XLSX兼容修订复体验：用户反馈修改后成功，上传兼容修复按该范围记user_verified。浏览器只读核实导入#4校验通过、修订2、待处理0，34款/222SKU/222映射、解析异常0；当前可提交审核，尚未生成批准预览或批准。XLSX往返的上传/校验已成功，变更范围预览仍待核对，不能据此声明仅名称变化或整体通过。本批无需Skill，未代提交、批准或重跑检查。

2026-09-10 XLSX上传兼容修订：用户要求优化上传失败。已允许白名单内空目录及受限标量自定义属性（WPS保存元信息），继续拒绝路径穿越、目录载荷、外链和公式。实际下载文件OOXML 22条目已通过；进一步发现款式主档C16款号1210被保存为数字，保持文本字段限制并新增中文错误提示，不自动改身份值。17项OOXML目标检查、Ruff和受影响前端ESLint通过；七月原RunID重启READY。development_complete / ready_for_user_review，需将编辑副本C16恢复文本并仅修改D16后复体验。原文件未改，无自动上传/批准、全量回归或Stage5。Skill：systematic-debugging。

2026-09-10 主/细分类联动筛选：development_complete / user_verified，用户明确确认“体验通过，进行下一步”。范围为七月localhost:20601、目录V34的主/细分类筛选；此前核对裤子8款、休闲长裤7款、西裤1款（1210）。下一项准备当前目录的兼容XLSX往返，先止于单名称修改的校验与预览。整体试用/发布状态不变，未重跑测试。本批无需Skill。

## 功能优化记录约定（2026-09-10 用户要求）

后续用户中途提出的功能优化、UI/交互调整、新增功能及缺陷反馈均纳入本索引，详细交付沿用开发流程记录。每项按“提出日期 / 需求与模块 / 实施状态 / 体验状态 / 版本或环境 / 剩余问题及记录链接”维护；同项反馈连续更新，体验通过后同步相关体验清单。继续下一步前先查最新确认，避免重复安排。此次落地后续记录规则，不表示此前所有优化已完成逐项回填或全部体验通过。

本批无需 Skill；仅更新记录规则，无代码、数据或运行环境改动。

2026-09-10 状态纠正：用户指出同文件重复上传已经体验通过，并要求更新计划。本项按本次用户确认记为 user_verified，不再安排重复体验；下方上一轮“下一项同文件重复导入”交接已被本记录替代。本次仅更新状态，不推断实际上传时间、批次ID或新日报版本，不扩大到更正、合并冲突等其他场景。后续先核对剩余事项与已有体验确认再安排，整体Stage4试用、导航遗漏排查及正式发布验收仍未整体完成。本批无需Skill，未重跑测试或操作试用数据。

2026-09-10 商品标题分类已获用户明确体验通过（user_verified）：七月隔离目录现为V34，34款均已分类；保留原2款分类，32款经单商品预览批准完成归类。探索用批次#2已撤回。此前“不自动归类”为当时授权边界，后续用户已明确授权本次按标题分类。整体Stage4七月试用与发布验收未完成。下一项按完整体验清单进入7月7日同文件重复导入审核，入口已核实，日报仍为v1/22行；先验证重复文件不重复计入，不发布人工更正金额。后续仍需全导航遗漏排查。本批无需Skill，未重跑测试、重启或进入Stage5。

2026-09-10 已按用户截图导入七月隔离环境分类字典：26个唯一分类（15主分类、11细分类），保留原有5个分类ID；Dress/Skirt/Pants等细分关系、英文别名及重复Sweater/Cardigan合并已写入。未修改已批准商品归属或历史目录，证据见D:/CLSEN_Stage4_RealDataReview/july-baseline-20260910/category-import-20260910.json。分类目录可在管理员商品卡→管理分类查看，后续仅按用户明确选择给商品建立草稿，不自动归类，不进入Stage5。

2026-09-10 分类管理UI布局 development_complete / ready_for_user_review：可搜索分类目录+单项编辑、未保存保护、窄屏上下布局；3项目标组件检查/ESLint及1592/680px浏览器核对通过，七月已热更新并保留待新建内容。待体验，未进入Stage5。

2026-09-10 两级分类/中文校验/产品总表分类筛选 development_complete / ready_for_user_review。schema0028仅升级七月隔离库，旧目录快照指纹一致；独立MySQL8.0两文件5项、相关前后端及类型检查通过，原环境重启READY。主/细分类维护→商品预览批准→七月总表筛选路径待用户体验，未自动分类或进入Stage5。

2026-09-10 分类代码直接编辑 development_complete / user_verified（用户明确反馈“体验通过”）：管理员商品卡→管理分类可修改代码；稳定category_id保持关联，历史快照不重写。后端7项、前端1项及单MySQL8.0目录批准3项目标检查通过，七月原环境已重启READY。此前分类缺项为历史状态，用户已新增DRESS/T-SHIRT。本轮体验已确认，整体七月体验及正式发布验收状态不变，未进入Stage5。

2026-09-10 产品总表表头排序及款式详情颜色/尺码经营明细均获用户确认，development_complete / user_verified。下一项七月单商品名称维护，catalog/styles/31已实核可用，ready_for_user_review，先止于变更预览；分类仅BLAZER/SHIRT，2301所需分类待补，保持待分类。未代建草稿或批准，未进入Stage5。

2026-09-10 产品总表8项指标说明弹窗统一优化已获用户体验通过（user_verified）；已按约定录入 Storybook Patterns/Product Ledger Metric Help，使用虚构数据。整体七月试用及正式发布状态不变。

2026-09-10 产品总表销售贡献/退货关注已更新七月隔离环境并重启，development_complete / ready_for_user_review；含筛选全量销售占比、平均单价及同期退销比。前端6项、后端10项和真实分页/搜索分母定向核对通过，待用户体验，不代表正式验收。

2026-09-10 产品总表身份展示优化已获用户明确体验通过（user_verified）：默认款号、悬浮名称、右侧商品信息抽屉及显示名称开关。七月环境保留，完整试用其他项目及发布验收状态不变。

2026-09-10 入口故障修复：七月新环境曾因 PowerShell 7 localhost 健康检查超时而自动关闭；已改为内部 IPv4 检查，原数据库恢复，runner READY 且持续运行、浏览器登录页及双角色数据读取核对通过。入口仍为 http://localhost:20601/?month=2026-07，完整体验待用户确认；未重建、重导入或进入 Stage 5。

核对日期：2026-09-08。R、A 与 B1 均为 `development_complete / user_verified`；B2（统一冲突、忽略/恢复与增量保护）为 `development_complete / user_verified`。目标工作树 `codex/stage4-1-app-shell`、基线 `ec0a72e`，新增 0027 排除草稿预占和增量来源引用修复；成果仍未提交、合并或部署。C 已完成开发与人工体验，D 已完成开发与人工体验。Stage 3 保持 `accepted / merged_to_stage2_branch`。

## 历史安排：Stage 4 真实数据试用与反馈修订

本节保留当时交付过程；其中待体验、待修复和环境状态均非当前执行安排，以顶部最终状态为准。

2026-09-10 七月全量基线已恢复，http://localhost:20601/?month=2026-07；62份日报及目录V1(34款/222SKU)就绪，双角色API读取和XLSX下载核对通过。完整体验入口在july-baseline-20260910/完整体验入口.md，逐项待用户确认；异常恢复等未覆盖项保留，旧现场不动，不进入Stage5。

2026-09-10 用户扩展授权：将7月整月作为额外持续导入基线，原review-01现场保留。新任务D:/CLSEN_Stage4_RealDataReview/july-baseline-20260910，Run ID b2f5960b07c74303ac2d26bf82d3be43；62份原始脱敏日报已逐日导入/校验/测试发布（经营944行/1364件/US$58733.20，退货449行/449件）。商品候选尚未批准。新入口拟localhost:20601，与旧127.0.0.1区分登录Cookie；切换入口后恢复命令被自动审批拒绝，仅返回blocked by policy，当前新实例已停止，不能标记入口ready。不得重建/重复导入；恢复说明见新任务基线说明.md。原实例未改动，不进入Stage5或部署。

2026-09-10 用户确认导航修订review-28/29体验通过(user_verified)，F-11本次主要路径与四处修订闭环。未覆盖场景继续见任务收尾清单；整体Stage4待收尾范围确认，保留现场，不自动进入Stage5。

2026-09-10 review-29：批量审核任务列表补齐，原实例已重启；4项目标检查通过，实际空列表及v2/v3保留。F-11主要路径源码审查完成、四处入口已补，等待导航体验确认；真实任务恢复未覆盖，不自动记整体完成或进入Stage5。

2026-09-10 review-28：试用收尾清单已整理；F-11首批补已有目录批次列表、日报到版本记录、版本到活动草稿三处入口。3项目标检查及实际入口通过，已重启，ready_for_user_review。完整导航范围仍有待查项，整体未关闭，不进入Stage5。

2026-09-10 用户确认本轮人工跨文件重复记录处理体验通过(user_verified，按交付范围止于草稿校验)。保留现场，不推断发布或具体草稿版本；待收尾列明未覆盖项及整体体验后导航遗漏排查F-11，整体不自动完成，不进入Stage5。

2026-09-10 用户确认review-27历史明细体验通过(user_verified)。下一项为人工跨文件重复冲突：merge-conflict-trial完整22行、21同值+1异值样本已备，选择合并/保留目标v2，预期22行/1338.69，止于草稿校验；入口ready_for_user_review。整体未完成，F-11保留，不进入Stage5。

2026-09-10 review-27：版本记录新增固定发布版本只读明细，5项目标检查与实际v1/v2的83.98/93.98核实通过，原实例已重启并保留v1展开入口。ready_for_user_review；总体试用及F-11未完成，未进入Stage5。

2026-09-10 review-26：F-01解析重试改共享锁读取，正式独立MySQL8.0权限目标节点2项通过，development_complete；原Run ID及API30250/前端46638/Storybook6006已恢复，同账号API登录和V2商品21/2个变体只读核实。浏览器重启后需重新登录。整体仍待导入路径复体验，F-11保留，未完整回归或进入Stage 5。

2026-09-09 review-25（F-23）：重复上传按真实阶段显示，已发布项只查看原日报、不重新识别；结果说明和成功后文件框清理已同步。4个目标节点及局部ESLint通过，原页批次#7实读确认新UI。ready_for_user_review，F-01/F-11保留。

2026-09-09 最新确认：本次商品主档体验user_verified；下一项为7月7日经营报告同文件重复上传，http://127.0.0.1:46638/review/2026-07-07 已核实两类报告published v1和上传入口，ready_for_user_review。只使用任务samples/1中既有7月7日副本，未代用户上传。自然行级冲突未覆盖、重试权限F-01及整体体验后导航F-11保留；整体试用未完成、不进入Stage 5。

2026-09-09 最新交接：review-24 Storybook已获用户确认（user_verified）；款式详情折线图review-23已确认。下一项为单商品名称/主分类修改，入口 http://127.0.0.1:46638/catalog/styles/21 已核实有1101/2个变体及分类选项（ready_for_user_review），未代用户生成草稿或批准。整体试用未完成，F-01及体验结束后的导航排查F-11保留，不进入Stage 5。下方条目为历次记录，当前状态以本条及计划末尾最新交接为准。

2026-09-09 review-21（F-22）：对比选择按实际选项总数显示，全选4颜色不再显示4/8；标题随维度变化。2项目标测试/局部ESLint及实际文案核实通过，ready_for_user_review，F-01/F-11保留。

2026-09-09 review-20（F-21）：稳定系列颜色/线型、tooltip实际尺寸视口避让与超长滚动已同步原入口；10项目标测试及实际配色/500px高度提示检查通过，ready_for_user_review，F-01/F-11保留。

2026-09-09 review-19（F-20复修）：独立点只显示自身，同日期同值重合点才列多条；8项目标测试及实际单点/三重合点验证通过，ready_for_user_review。覆盖review-18全天系列tooltip行为，F-01/F-11保留。

2026-09-09 review-18（F-20）：悬停改按日期列出全部已选系列，修复重合点遗漏和日期切换旧提示，8项目标测试、局部ESLint及实际五尺码读数检查通过，ready_for_user_review；F-01/F-11保留。

2026-09-09 review-17（F-19）：数据点新增就近日期/系列/精确数值提示，7项目标测试、局部ESLint及真实悬停显示核实通过，原入口已同步ready_for_user_review；F-01/F-11及整体试用待办保留。

2026-09-09 review-16（F-18）：修复筛选请求卸载整页造成的闪动，同商品同权限下保留带原口径的旧结果并标注更新中，新响应整体替换；4项目标测试及局部ESLint/实际切换检查通过，ready_for_user_review，F-01/F-11和整体试用待办保留。

2026-09-09 review-15（F-17）：指标标签、维度/退货口径分段单选及颜色标签已同步原体验页，3项目标测试/局部ESLint和1048/390实际检查通过，development_complete / ready_for_user_review。未改数据和业务计算；F-01/F-11及整体体验待办保留。

2026-09-09 review-14（F-16）：修复尺码颜色空下拉，按同目录版本读取颜色并说明限定范围；工具栏更新，聚焦时显示恢复全部曲线。9项目标测试、局部ESLint和1048/390实际检查通过，原入口已同步ready_for_user_review，F-01/F-11保留。

2026-09-09 review-13（F-15）：趋势图650ms生长/重播、空心节点及聚焦/游标/显隐过渡已同步原入口，减少动态效果时关闭。6项目标测试、局部ESLint、实际展开与390显示检查通过；development_complete / ready_for_user_review，未改业务数据/计算，F-01/F-11与整体体验待办保留。

2026-09-09 review-12（F-14）：产品每日趋势增加日期读数/键盘逐日查看、图例单系列突出、数据点开关，改善8色线条和响应式轴标签。图表5项及详情页2项目标测试、局部ESLint、390/1592显示检查通过；原试用入口已同步，development_complete / ready_for_user_review。未修改数据或计算口径，整体体验未完成，F-01/F-11保留。

2026-09-09 review-11（F-13）：修复商品主档旧标签页刷新缺口，加入切回自动读取、手动刷新和失败重试。原标签页已核实 V1/27款及刷新按钮可见；3项目标组件测试与局部 ESLint 通过。development_complete / ready_for_user_review，尚待用户复体验；未改数据库或重建现场，F-01/F-11及Stage 4剩余体验继续保留。

2026-09-09 后续入口已核实（review-10 / V1 / review01-data-manager）：商品主档27款；1101商品卡 /catalog/styles/21 有2个变体及名称/分类修改入口；产品分析 /products?from=2026-07-01&to=2026-07-07 有27款，2301详情有15个变体和指标。上述查看路径 ready_for_user_review；未执行分类写入、未独立复核分析数字或替代用户确认。仍停留 Stage 4，F-01/F-11 保留。

2026-09-09 review-10：用户操作后首个目录批次 #1 已批准为 V1（实际页面只读确认）；覆盖下文历史“首个目录未批准”状态。优化批准结果区与后续导航按钮，3 项定向测试及 1048/390 显示检查通过，新增结果 UI ready_for_user_review。商品主档/分类/产品分析后续体验待核实与确认，F-01/F-11 保留，仍为 Stage 4，未完整回归或部署。

2026-09-09 用户明确确认“目前的体验通过”：当前 review-09 商品建档审核界面及本轮 UI/交互反馈修订标记 `user_verified`，覆盖此前 review-03 至 review-09 的待复体验界面；日报既有 `user_verified` 保留。这不表示目录业务内容已确认或批准、产品分析已体验、整体真实数据试用或发布验收已完成。用户要求整体体验完成后集中排查所有导航遗漏（F-11）：覆盖本次试用全部功能的菜单入口、已有批次继续处理、返回/跨页路径及角色可见性；已知首次建档批次未纳入待处理入口，需修复并定向复体验。当前记录待办，不启动完整回归或 Stage 5，不提交/整合/部署。

2026-09-09 review-09：优化 SKU 信息层级、映射卡片及就近归属入口、来源证据列表，保留 reveal 权限边界。8 项定向测试与实际宽窄屏检查通过，同步原试用入口，ready_for_user_review；原数据保留，未进入 Stage 5。

2026-09-09 review-08：紧凑审核顶部、SKU 标准化响应式卡片，修复账号文字与退出按钮重叠。相关 8 项定向测试及 1592/1048/390 宽度显示检查已完成（详见开发记录）；同步原试用入口，ready_for_user_review，数据现场保留，未进入 Stage 5。

2026-09-09 review-07：优化“校验与批准”步骤、主次按钮、输入与高级基准调整展开区；原权限/批准规则不变。3 项工作流目标测试及宽窄屏显示检查通过，同步原入口，ready_for_user_review，试用数据保留；未进入 Stage 5。

2026-09-09 review-06：保留用户认可的卡片分隔，压缩卡片留白；桌面改两行网格、名称框随内容增高。已同步原入口，1592/1048/390 宽度显示检查通过，待用户复体验；数据现场保留，未完整回归或进入 Stage 5。

2026-09-09 review-05：按用户标注优化款式审核布局与组件，使用面板宽度断点排列来源/款号、名称、状态/保存和独立修改说明。8 项定向测试通过，实际 1592/1048/720/390 宽度已检查，最窄无页面横向溢出或文本框裁切。已同步原试用入口，ready_for_user_review；原数据和日报 user_verified 保留，未完整回归或进入 Stage 5。

2026-09-09 review-04：字段增加 × 清空按钮；标准商品名称列加宽、编辑框自动增高，候选模式显示完整名称。已同步原试用入口，组件 6 项定向测试与相关 ESLint 通过，实际页面显示已核对；待用户复体验。数据现场和日报 user_verified 保留，未进入 Stage 5。

2026-09-09 review-03 修复 F-04：商品建档选择“手动输入其他值…”保留当前候选文字，编辑期间不因内容等于候选或清空而跳回下拉框。已同步原试用实例；组件定向 6 项通过，Vite 更新模块 HTTP 200；待用户复体验，日报既有 user_verified 保留。原 Run ID、端口和数据不变，无完整回归、提交、整合、部署或 Stage 5。详情见开发流程 review-03 记录。

2026-09-08 用户已授权本地脱敏报告及独立测试库导入、编辑、校验、批准目录、测试日报发布，并确认同一美国站账号。按[真实数据试用计划 v1.0](../superpowers/plans/2026-09-08-stage4-real-data-review-and-feedback-plan.md)完成 review-01 环境准备，日报查看已获用户明确确认：`daily_report_review = user_verified`；商品建档、产品分析及写入体验仍待完成，`real_data_review` 整体未完成。独立代码快照为 ec0a72e + stage4-1-app-shell 未提交成果；任务目录 `D:/CLSEN_Stage4_RealDataReview/review-01-20260908`，入口卡 `体验入口.md`。前端 `http://127.0.0.1:46638`，Run ID `c8064cc8c42c4fe7823cd1c1f336697e`；2026-07-01 至 07-07 的 14 份完整报告、260 行已导入校验并测试发布。原件及副本哈希一致，停止后恢复保留现场。首个目录尚待标准名/内部 SKU/身份确认；解析同操作重试存在运行权限问题（F-01），未修复，首次批次仅用任务初始化身份经解析服务恢复，不能宣称重试权限通过。未完整回归、提交、整合、部署或进入 Stage 5。详见开发流程本次记录。

2026-09-09 继续初次商品建档：恢复同一 Run ID/端口和既有现场；草稿 #1 已补齐 27 款名称建议、107 原 Seller SKU 内部编码及一对一映射（241 项），分类保留待分类。应用校验无 issue，workflow_revision=3，已提交待批准，预览普通风险、134 行。多标题 6 款的候选差异见任务目录 `商品建档建议.md`。本轮仅草稿建议 `ready_for_user_review`，没有批准首个目录；已发布商品主档与产品分析仍未就绪。日报 user_verified 保持，F-01 未修复。不改代码、不重跑日报或完整回归。

2026-09-09 建档代码更新为 review-02，沿用原 Run ID、端口和现场。修复 F-03：相同草稿/审核人使用新请求重新生成批准预览时，摘要重复导致唯一键冲突；摘要加入预览 operation token，新请求有独立生命周期，同 token 继续幂等重放，内容 diff 摘要不变，无迁移。只改 backend/app/catalog/import_repository.py 与已有 test_catalog_import_workflow.py。正式脚本 MySQL 8.0、DevelopmentTests 指定该文件和 test_catalog_approval.py，共 6 项通过；实际页面取消“仅看待处理”后显示 27 行建议，预览 HTTP 200、普通风险/134 行、确认批准按钮可见，无 pageerror。用户尚未批准目录，商品主档/产品分析仍未就绪；建档建议 ready_for_user_review。日报 review-01 user_verified 保留，不重跑无关检查；F-01 仍未修复，未完整回归、提交、整合、部署或进入 Stage 5。

顺序：明确授权副本/业务范围 → 独立本地测试环境 → 只读体验 → 少量写入体验 → 集中修订 → 定向复体验 → 用户确认后进入 Stage 5。建议先 1 个站点/账号/Marketplace、7–14 天、3–6 份格式完整的报告和 10–20 个代表款式，按真实文件范围调整，不强制截断报告。

执行前一次性提供：data/ 外的授权脱敏副本路径和文件范围、业务日期/站点范围、首轮体验重点、隔离测试库允许操作。未指定路径不搜索原件或读取 data/；未授权测试写入只做只读。临时库中的日报发布和目录批准不代表生产发布或应用部署。

Stage 4 已完成的开发/合成样例体验结论保持，真实数据试用单独记录。反馈按阻塞/错误结果、交互体验、源数据、范围新增处理；集中修订后只复体验受影响路径。Stage 5 暂缓启动，完整回归留部署准备；本轮不提交、合并或部署。后面的旧“继续剩余 4.3”描述只用于历史追溯，当前执行顺序以本节为准。

## 历史阶段记录：Stage 4.3 已完成开发与人工体验

用户于 2026-09-08 明确确认 P0 产品总表与款式详情“体验通过”。对应 18615 入口、`ec0a72e + 未提交改动`，本批状态更新为 `development_complete / user_verified`。随后用户授权“继续下一步”，日期表格与单日审核交接已交付，用户随后明确确认“体验通过”；本批为 `development_complete / user_verified`。用户随后授权“是，继续”；审核内部控件/局部样式、发布确认对话框及批量审核迁移已开发交付，用户现明确确认“体验通过”，状态 `development_complete / user_verified`。随后用户授权“继续”；审核外层、备注/来源组件局部迁移与隔离修复已交付，用户现明确确认“体验通过，继续进行下一步”，状态 `development_complete / user_verified`。

用户此前明确确认“可以，体验通过进入下一阶段”：发布数据查看首批及入口、退货状态、月内趋势/导航优化统一记为 `development_complete / user_verified`，对应 Run ID `d9f9e41881224205af5255261df23e88`。本轮继续 Stage 4.3 的 P0 产品总表与款式详情，不进入 Stage 5；以下历史待体验记录由本确认更新，正式发布验收仍待部署准备。

最新 Stage 4.3 收尾批次为产品趋势坐标与技术适用性，用户已明确确认“体验通过”，状态 `development_complete / user_verified`。页面登记核对确认 `/versions`、`/admin` 已属 Stage 3 验收范围，月内趋势已有完整坐标；本批只修正 P0 多系列 SVG 在窄屏的实际字号、纵横轴和文字图例。现有精确 SVG 与表格后备更符合当前合同，因此不新增 Motion/ECharts。后续 UI 与动画优化另行安排；仍有调用者的全局兼容规则继续保留，不为清零 CSS 文件机械删除。

用户随后授权“进行下一步”。空日期的新建导入入口、任务栏、五步证据链、导入说明与 CSV 选择区已迁移到 ImportEntry.module.css；用户实走解析、生成草稿与校验后明确确认“体验通过”，状态 `development_complete / user_verified`。按用户反馈，“生成草稿原因”现从登录会话自动带入显示名、账号、用户 ID，并结合报告日、报表类型、导入批次和原始文件生成说明，既有人工说明保留为补充说明；审核确认、草稿移动/废弃、发布说明、字段修改/恢复、新增/排除行及重复记录决定沿用同一来源规则。后端仍以登录会话用户 ID 为权威审计操作人。

用户要求继续后，导入队列、人工识别确认、日期差异和解析基线局部样式已迁移，并从 `styles.css` 精确删除这些唯一调用者规则；与工作台、发布回执共享的选择器已拆开保留。用户现明确确认“体验通过”，状态 `development_complete / user_verified`。

下一批选择生成草稿和草稿改期共用的目标日期冲突处理路径：冲突选择卡、目标版本摘要和逐行重复记录矩阵已迁入 ReviewDecision.module.css，两处调用统一使用模块类，旧全局规则已删除。首次体验发现 24 对冲突全部展开导致页面超过 22,000px；现已改为每页 4 组、显示完成进度、支持当前页未处理项统一选择，并把长字段摘要限制为 3 行，完整字段仍可展开。第二次反馈进一步修正“相同数据为何冲突”和左右失衡：页面现在明确说明经营报告按“子 ASIN + SKU”、退货报告按完整退货业务键识别重复记录；字段完全相同标记为重复副本，不再重复展示“相同值 → 相同值”。解析摘要改为紧凑页头，原因和决策区域使用整行宽度，宽屏 4 组记录按 2×2 排列。第三次反馈发现长审计说明撑出卡片，现已允许决策列和控件收缩，长内容在未聚焦时省略显示、聚焦后仍可完整查看和编辑。第四次反馈修正草稿页整页横向溢出和审核步骤过长：宽表只在表格内部滚动，工具栏按实际可用宽度堆叠；版本备注改为紧凑整行，草稿校验与确认并排，并同步精简操作文字。右侧批次备注在窄栏中也改为正常横排。第五次反馈继续收紧整段审核工作区：导入队列和草稿页头减少空白，数据标题与新增操作同排，搜索/字段/行状态归为一行，差异开关与导航归为一行；草稿页头样式同时从旧全局兼容层迁入局部模块。每条决定继续保留独立操作人、目标版本和目标/来源行号。用户已确认第五次修正版体验通过，状态 `development_complete / user_verified`。

最后一批已完成草稿改期、重新解析/废弃、校验发布状态、发布闸门和发布回执的局部样式迁移；移动原因改为可完整查看的多行输入，“调整草稿日期”与“重新解析或废弃草稿”同一时间只展开一项。用户已明确确认体验通过，状态 `development_complete / user_verified`。至此 Stage 4.3 页面登记内的开发批次和人工体验全部完成；正式发布验收仍待部署准备，Stage 5 尚未启动。

2026-09-08 已按用户授权继续剩余 Stage 4.3，交付“发布数据查看”首批，状态 `development_complete / user_verified`。当前入口为 `http://127.0.0.1:18614/?month=2025-07`，Run ID `d9f9e41881224205af5255261df23e88`；已核实真实隔离 API 与合成样例可用。下方 R/A/B/C/D 地址仅为历史记录，不作为本轮入口。代码仍未提交、合并或部署，正式发布验收待部署准备。

最新用户确认：D Run ID `d97a3b79951e45b7bcbcde54bb5db159` 已获用户明确确认“明白了，体验通过”，状态为 `user_verified`；本次不自动启动剩余 4.3 页面，正式发布验收留部署准备。

- Stage 4.1：`development_complete / user_verified`；基线 `ec0a72e`，工作分支 `codex/stage4-1-app-shell`，代码尚未提交或整合，正式发布验收待部署准备。
- Stage 4.2①：`development_complete / user_verified`；用户体验后明确要求继续下一批，隔离体验实例已干净停止。
- Stage 4.2② 与 R：`development_complete / user_verified`；用户于 2026-09-07 明确确认修正版本“目前体验通过，可以进入下一阶段”。
- A（4.2③-A）：`development_complete / user_verified`；新增 `0025` 分类与单商品修改迁移，详情页可修改标准名称/主分类、预览并批准为完整新目录版本，管理员可创建、改名、维护别名和停用分类；空别名数组反馈已修正并完成复体验。
- A 修正版复体验入口：`http://127.0.0.1:50512/catalog`，Run ID `2f86edc18ad04ea4b52e99b309060c36`；`SHORTS / 短裤 / aliases: []` 返回 HTTP 201，用户随后明确确认体验通过。
- B1（4.2③-B）：`development_complete / user_verified`；用户明确确认该版本体验通过并授权进入 B2。
- B1 复体验入口：`http://127.0.0.1:23840/catalog`，Run ID `1df31eba47974b94b9d2071af162af13`；款式编号 `100` 的摘要为“新增变体 1 / Seller SKU 1 / 100-NAVY-L”，进入导入 2 后稳定显示款式 `2/2`、SKU `10/12`、映射 `11/12`。凭据文件位于该运行目录，未实际保存候选或批准。
- Stage 3 历史状态保持如下，不因后续开发重开：
- 验收版本：`28684cfe6367ad81a1dfef256bdb643c6d36a39f`（`28684cf`），[PR #9](https://github.com/dulanjy/CLSEN_Data_Web/pull/9)。本轮已核对本地候选 SHA；CI 结果已通过 GitHub 只读查询复核，人工体验依据用户明确确认记录。
- 开发：`development_complete`；人工体验：`user_verified`；阶段状态：`accepted / merged_to_stage2_branch`。
- 当前 PR 验收：Ubuntu、Windows、Frontend、MySQL 8.0、`pr-required` 全部通过。MySQL 8.4 按 PR 策略正常跳过，不记为通过。
- 合并前 PR 状态已核对为 `CLEAN`；合并后已核对为 `MERGED`。用户确认 Stage 3 候选工作树干净。主工作区仍有流程文档未提交改动，不能将两者混为一谈。
- 验收范围为原 Stage 3 UI 基础体系，包含统一 Token、共享组件、CSS Modules、Lucide 和管理员 Worker 页接入；商品主档业务、Stage 4 全页面迁移及其他业务计划不因此视为完成。
- `release_validation`：当前 PR 约定检查通过；正式部署完整测试仍留到部署准备。本次仅执行用户确认的 PR #9 合并并更新文档，不重复启动测试；未执行 master 整合、部署或真实数据库迁移。

Stage 4.1、4.2①、4.2②/R、A 与 B1 已完成开发与人工体验；B2 已完成开发与人工体验，C 已完成开发与人工体验，D 已完成开发与人工体验。正式发布验收仍留部署准备，整合按用户指令执行。

- B2 体验入口：`http://127.0.0.1:31138/catalog`，Run ID `ef353bd36763453aa13ca6aedea39eec`，schema `0027`。已实走导入 2 中 `100-NAVY-L` 的排除保存、占用查询、带原因恢复及商品卡待办重新出现，正式目录保持版本 1。用户明确确认“体验通过”，当前 `development_complete / user_verified`。

- C（Stage 4.3-A 商品主档）：`development_complete / user_verified`。四入口为商品、待处理、目录版本、批量维护；旧导入深链保留，列表搜索/排序/页码/视图在当前会话内保留，身份/角色/站点配置边界变化清空。待处理复用 B 的授权摘要；批量页承接原工作簿控件。
- C 体验入口：`http://127.0.0.1:19264/catalog`，Run ID `173d1aa238c445d6b5cf1df7f868b743`，版本为 `ec0a72e + 未提交 C`、schema `0027`。定向前端 17 项、后端路由契约 1 项、TypeScript/目标 ESLint/Ruff 通过；隔离 MySQL 中未匹配接口修复后正常，导航返回、原深链、390px 窄屏及键盘进入已实走。正式目录 V1 未批准变更。旧 B2 入口不用于本轮体验。

- D（Stage 4.3-B 商品主档）：`development_complete / user_verified`。完善初始化指引、旧候选提醒、在线/XLSX 路径、服务端行级问题定位、批准版本反馈与只读边界；修正旧修订请求在校验后覆盖页面状态的问题。schema 仍为 0027，无新增迁移。
- D 体验入口：`http://127.0.0.1:59874/catalog/imports/5`（两处待处理问题）；批量入口 `http://127.0.0.1:59874/catalog/maintenance`。Run ID `d97a3b79951e45b7bcbcde54bb5db159`，`ec0a72e + 未提交 D`。前端定向 16 项、工作簿 5 项及后端详情 1 项通过；TypeScript/目标 ESLint/Ruff 通过。已实走任务恢复、真实 XLSX 下载上传、问题行保存、校验、提交与预览；测试草稿 3/4 已撤回，导入 5 在交付时留供体验；后续用户已确认该 Run ID 体验通过，但未提供最终批准或目录版本变化证据，不推断已生成 V2。

## Stage 4.3 剩余页面首批：发布数据查看（2026-09-08）

基于 Stage 0 `scripts/project-optimization-baseline-manifest.json` 路由登记逐项核对本批相邻页面；不修改冻结清单。版本为 `ec0a72e + 未提交 Stage 4.3 发布数据查看改动`，工作树 `D:/CLSEN_Data_Web/.worktrees/stage4-1-app-shell`。

| 登记入口 | 本轮核对的实际差距与处理 | 当前状态 |
| --- | --- | --- |
| `/`，含 legacy 产品总表和商品弹窗 | 业务表、角色导航和 URL 筛选已存在；迁移 CSS Modules/Token 和共享反馈，修正月份/筛选切换显示旧值及迟到响应，进入明细账携带月份 | development_complete / user_verified |
| `/ledger/published-details`，含日期摘要与只读原始表 | 快照 token、冲突重读、行列设置、权限和 CSV 已存在；迁移局部样式与共享控件/分页/状态，保留这些业务合同，修正窄屏搜索按钮换行 | development_complete / user_verified |
| `/published-details/:reportDate` | 原页面依赖全局样式，空结果一直加载、换日期未隔离请求；改为共享页头/反馈、局部样式、可重试与日期请求隔离，增加当日原始明细链接 | development_complete / user_verified |
| `/published/:reportDate` | 日期工作台已迁移局部样式/共享控件，补齐分页、重试、原日期版本审核交接与返回；单日摘要沿用已确认版本 | 本批 development_complete / user_verified |
| `/products`、`/products/:style_id` | 已迁移 CSS Modules、共享控件/反馈/分页，保留原指标合同；详情切换指标后返回保留筛选与焦点 | development_complete / user_verified |
| `/review/:reportDate`、`/review/batch/:runId`、`/review-advanced/:reportDate` | 交接、审核表/阶段/确认、批量页、外层备注/来源、新建导入入口及识别/解析/队列均已体验通过；目标日期重复记录决定、分页和五轮排版反馈已完成体验；草稿改期/处置、校验发布状态与发布回执已迁入局部样式，维护入口改为单开折叠组 | development_complete / user_verified |

开发证据：5 个明确前端目标文件共 41 项通过；TypeScript、8 个目标 TS/TSX 的 ESLint、定向 diff 检查通过。真实隔离 API 中已核对 2025-07 两个发布日期、展开与全部明细、列设置和 CSV HTTP 200；1280/390px 定向浏览器查看，无页面脚本错误，390px 明细账与单日摘要无整页横向溢出。证据目录 `D:/CLSEN_Data_Web-tmp/stage43-view`，不是正式 release evidence。未运行后端测试、完整构建、全量 E2E、双版本 MySQL 或发布 Collect。

体验：打开上述总表入口，用运行目录的 `experience-credentials.json` 中的临时账号登录；选择 2025-07，进入“发布明细”，展开 07-17，切换“全部明细”；单日入口 `http://127.0.0.1:18614/published-details/2025-07-17`。具体前置条件、步骤与关闭方式见[开发流程交付记录](../operations/development-workflow.md#stage-43-发布数据查看首批2026-09-08)。本批已获用户明确体验确认，当前为 `user_verified`。

入口反馈已修正：日期摘要操作区新增“查看单日摘要”，全部明细中的报告日期可点击；单日页可返回原筛选/分页/查看方式。沿用当前 Run ID，33 项相关组件测试和实际进入/返回路径通过，已随本批获得用户体验确认。

用户已批准并完成单日摘要月内趋势与共享导航优化：现有接口取月初至所选日，展示 5 类可切换趋势、相邻日比较、累计/覆盖天数及逐日数据表；缺报断线、零基数和实际 28 位转化率已定向覆盖。共享 LinkButton 已用于本页顶部。19 项相关目标测试、TypeScript/目标 ESLint 通过，实际隔离样例及 1048/390px 显示已核对，沿用 18614 入口和当前 Run ID。状态仍为 `development_complete / user_verified`，已得到本版本人工体验确认。图表不等于全站图表体系迁移完成。

Stage 4.3 页面迁移、反馈修正和人工体验已全部完成。余项只有部署准备阶段的正式门禁及尚未授权的整合；Stage 5 尚未启动。

## 最新专项计划：商品主档与目录工作簿优化 v1.0

正式入口为[商品主档与目录工作簿优化实施计划](../superpowers/plans/2026-09-07-product-catalog-workbook-optimization-implementation.md)。R、A、B1 已完成体验；B2 已完成体验，C 已完成开发与人工体验，D 已完成开发与人工体验。

采用“商品卡日常维护 + 批量维护中心”。单商品草稿经校验批准形成新目录版本，保留其他商品，不放宽旧整批草稿的阻断规则；分类独立于稳定身份，网页改名与 XLSX 模板升级分开处理。

| 执行顺序 | 所属 Stage | 本批交付 | 当前安排 |
| --- | --- | --- | --- |
| R | 4.2② 反馈修正 | 款式编号、身份层级、工作簿步骤与状态；保留现有后端和模板 | `development_complete / user_verified` |
| A | 4.2③-A | 独立单商品草稿/批准、分类与名称编辑、分类治理、模板兼容 | `development_complete / user_verified` |
| B | 4.2③-B | 变体/别名候选、临时预占与统一冲突、忽略/恢复、增量保护 | B1 `user_verified`；B2 `development_complete / user_verified` |
| C | 4.3-A 商品主档部分 | 商品/待处理/目录版本/批量维护导航，保留上下文和深链 | `development_complete / user_verified` |
| D | 4.3-B 商品主档部分 | 在线/XLSX 批量维护和空目录初始化 | `development_complete / user_verified` |

D 结束仍需完成原 4.3 的看板、工作台和审核等页面，再按总计划推进 Stage 5 与部署准备；不从本专项直接跳到部署。完整测试留部署准备，日常批次保留权限、并发、版本一致性及工作簿安全的受影响目标检查。

## 已确定的唯一主线：Stage 4 → 发布范围核对 → Stage 5必要收尾 → 部署准备 → Java/Python详细规划

2026-09-07确定商品主档融入Stage；2026-09-14按用户Java核心方向重新收敛，执行范围以[新主线](../superpowers/plans/2026-09-14-current-release-and-java-evolution-roadmap.md)为准。Stage 0–4保留既有开发、体验和验收边界，不重复实施。旧完整历史治理与预设规模化改造不再自动启动。

| 顺序 | 本批可用功能与范围 | 开发交付及体验退出条件 |
| --- | --- | --- |
| **4.1 应用外壳与公共页面**（已完成体验） | 沿用 Stage 3 组件，迁移应用外壳、登录、导航、全局错误与权限状态；核对管理员和版本页，仅补未迁移部分。 | `development_complete / user_verified`；基线 `ec0a72e`，分支 `codex/stage4-1-app-shell`，代码尚未提交或整合；正式发布验收待部署准备。 |
| **4.2 商品主档日常闭环**（已完成开发与体验） | ①候选任务恢复；②/R 商品卡、N:1 别名与来源；③A 分类与单商品修改、B1/B2 候选预占、统一冲突、忽略/恢复及增量保护均已交付。 | `development_complete / user_verified`；正式发布验收待部署准备，不重做已交付批次。 |
| **4.3 其余业务页面迁移**（开发与体验已完成） | C 商品主档导航、D 批量维护与初始化，以及看板、商品分析、发布日期/明细账、工作台、单项/批量审核和高级发布的主要使用路径均已完成开发；重复记录、草稿工作区五轮反馈及草稿维护/发布回执收尾均已完成体验。 | `development_complete / user_verified`。Stage 4.3 全部开发批次与人工体验已完成；正式发布验收仍待部署准备，Stage 5 尚未启动。 |
| **Stage 4 真实数据试用与修订** | 开发和本轮真实数据体验收尾完成，商品建档/产品分析及F-01对应确认范围已闭环。 | `development_complete / user_verified`，限已确认版本、样例及路径；45组中44组确认，#9/#35已在候选02确认，#40材料已纳入候选12且Storybook构建/可访问性通过，视觉门禁仍有4项移动端基线差异。V35批准前全量mapping/exclusion快照证据仍不足。`release_validation = not_started`，不标记accepted；成果仍在stage4-1-app-shell未提交，未整合或部署。 |
| **发布范围与基线核对** | 已核对实际业务工作树、相关未提交成果、3组部分确认、Storybook材料及V35证据边界，形成5.1/5.2最小范围。 | `complete`（只读核对）；未测试、提交或整合，详见顶部同名清单。 |
| **5.1 当前目录历史保护与必要修正** | 按[实施计划v1.1](../superpowers/plans/2026-09-14-stage5-1-catalog-history-governance-plan.md)复用历史不可变、当前/历史口径与既有审批纠错；R1/R2仅处理未来明确缺口。完整追溯、结账及新治理补偿设计已另存延期参考。 | `scope_closed / no_implementation_required`；用户已确认当前无R1/R2新增代码项，未实施代码。 |
| **5.2 当前规模适配与必要收尾** | 按本次支持规模和已证实瓶颈选择加载、分页、XLSX及内部收尾；子表化、游标、流式导出和模块拆分均非默认必做。 | `scope_closed / no_implementation_required`；用户已确认不启动预设重构，完整性能验收仍留部署准备。 |
| **部署准备** | 候选17完整本地Collect的Ubuntu-full、Windows smoke与Frontend完整段通过；MySQL 8.0在旧迁移头测试合同处停止。#9/#35确认因业务语义未变而保留。 | `in_progress / candidate17_collect_failed / ubuntu_full_passed / windows_smoke_passed / frontend_full_passed / mysql_8_0_failed / collect_stopped / collect_awaiting_targeted_fix_authorization / canonical_clean_sha_prerequisite_unresolved / targeted_experience_complete`；MySQL 8.4及release-only未执行。全部适用证据通过后才能给出正式accepted/可发布结论，实际上线仍另需授权。 |
| **Java/Python演进详细规划** | Java/Spring ERP核心、Python数据与AI能力、React复用；优先模块化单体，确定首个业务闭环和逐域迁移，再按实际需要拆微服务。 | `deferred_until_deployment_preparation_complete`；部署准备完成后开始详细规划，不要求实际上线已发生，也不自动授权Java实施或解冻暂停模块。 |

### 执行边界与不遗漏规则

- Stage 4保留历史交付；5.1/5.2按2026-09-14新主线收敛。重大业务改造不混入样式或纯重构，原验收合同不因排程变化缩减。
- 旧商品卡设计的历史治理和规模化需求保留来源，按新主线第3/4节逐项判定当前必要或延期，不再默认全部属于发布前必做。现有窄查询、摘要修复及审核筛选复用，不重新实施。
- Stage 4、Stage 5 每批只做受影响的定向检查并交用户体验；权限、并发、数据一致性和关键接口检查保留。完整测试集中部署准备，未执行的正式门禁记待办，不写成 accepted。
- Stage 4开发及本轮真实数据体验收尾按顶部状态保留；发布范围核对及5.1/5.2最小范围确认已完成。部署准备需另行授权，不重开试用、不扩展数据授权、不自动整合或启动后续开发。
- 进入 4.2、5.1 的数据模型工作时再细化该批事务、迁移与回退方案；新的重大业务决定当时确认，不提前铺开全阶段详细任务。所有验证使用授权的隔离或合成样例，不读取 `data/`，不因旧方案“7 月真实数据验证”自动访问真实数据。
- CI 分层待办纳入部署准备；如用户先要求缩小远端 CI，则提前作为明确的流程批次处理。当前 PR CI 范围没有因本路线自动缩小。
- 生产/供应链、Agent 11A、自动发布 11B、图片资产/PIM/ERP 等继续暂停。Stage 4/5 交付和部署准备完成后，再规划新的业务方向；既有普通 Compose 部署不依赖 11B。

### 已交付批次：Stage 4.2① 商品候选任务恢复

本批只处理“生成候选”任务，不扩入商品卡双视图、Seller SKU 归属、冲突审核或历史修正。现有目录导入解析已经具备租约、fencing 和恢复入口；`catalog_jobs` 已有任务身份、状态、租约和失败字段，原候选导出 Worker 曾直接扫描 `catalog_exports.building`，缺少尝试次数、退避、最大重试和人工恢复闭环。

当前交付状态为 `development_complete / user_verified`：以下五项均已实现并完成相应定向检查，用户体验后要求继续下一批；完整发布验收仍留到部署准备。

1. 让 `catalog_jobs` 成为候选导出调度权威，保持 `catalog_exports` 为不可变快照及产物状态；以新迁移补足尝试次数、下次尝试时间和可解释阶段，不修改历史迁移。
2. Worker 原子领取单个到期任务，续租并用 fencing 完成；可恢复失败按有限指数退避重排，达到最大次数后进入人工恢复状态，迟到 Worker 不能覆盖新结果。
3. 增加受角色、CSRF、幂等键和期望 revision 保护的人工恢复 API；只允许恢复服务端判定可恢复且没有活动租约的失败任务，并写审计事件。
4. 商品主档页面展示真实阶段、尝试次数、下一次重试、最后失败码和 Worker 可用性；仅在允许时显示“恢复生成”，轮询失败不得伪造任务完成。
5. 使用现有 Worker/API/组件目标测试及一个可抛弃 MySQL 8.0 定向场景验证领取、退避、上限、人工恢复和 ABA fencing；准备隔离合成任务的体验入口后交用户确认。本批到 `development_complete / ready_for_user_review` 即停止，不自动进入 4.2②。

预计目标文件为 `backend/alembic/versions/0024_*`、`backend/app/worker/catalog_exports.py`、`backend/app/api/catalog_exports.py`、必要的 catalog service/repository、`frontend/src/features/catalog/catalogApi.ts`、`catalogState.ts`、`CatalogExportPanel.tsx` 及对应目标测试。实际实现先按现有事务边界确认最小文件集，不拆散无关 Repository。

### 已交付批次：Stage 4.2② 商品卡与来源只读闭环

本批复用 `0022` 已批准目录中的款式、稳定变体及多个映射指向同一 `sku_id` 的能力，不增加迁移或新的写入状态。商品主档提供卡片/批量表格切换；商品卡汇总实际变体、Seller SKU、来源报告和观察记录，变体按需加载关联 Seller SKU 和分页安全来源明细。查看者可读取安全摘要，原值 reveal 权限保持原合同。

该批与 R 修正后已为 `development_complete / user_verified`。以下保留首次交付证据：定向证据包括后端路由契约、前端 7 项组件/API 测试、TypeScript、目标 ESLint/Ruff，以及可抛弃 MySQL 8.0 中两条 Seller SKU 映射到同一稳定 SKU并返回来源明细的单节点验证。隔离体验数据通过正式审批服务生成，当时入口预置 3 张商品卡、11 个实际变体和一个含 2 个 Seller SKU 的稳定变体。未执行完整回归、MySQL 8.4 或发布门禁；归属唯一性、草稿预占、统一冲突、永久忽略和恢复审核由后续 A/B1/B2 完成，不再列为未开始。

## 如何理解当前进度

以下保留各计划名称用于追溯。当前状态以上方 Stage 4.3-B D 交付记录为准；后续排程以上方唯一主线为准，主线外计划保持暂停。

- **平台优化 Stage 0–5**：保留原运行基线、schema 保护、监控、UI、页面迁移和重构范围；Stage 3 已验收并合入 Stage 2 分支，Stage 4.1、4.2①、4.2②/R、A 与 B1 已完成人工体验，Stage 4.2③-B2 也已完成人工体验，C 已完成开发与人工体验，D 已完成开发与人工体验。
- **商品主档 P0 里程碑 A/B/C**：目录初始化 → 稳定款式分析 → 受控切换与候选验收，已有实现与历史验收记录。
- **商品卡维护 A/B/C**：原设计分组，现统一映射到 Stage 4.2、5.1、5.2，不单独开线。
- **原平台阶段 11A/11B**：只读 Agent 分析与可切换应用发布，目前没有对应完整实现。
- **供应链 A/B/E0/C/D/E**：生产订单、完工入库、Amazon 标识、出货海运、FBA 实收与全链分析，不能与商品主档的 A/B/C 混用。

以下状态区分“代码已存在”“历史记录通过”“人工体验已确认”“当前发布可用”。代码存在不代表本次已运行或验收；未发现实现不等于用户取消了需求。

## 核对范围与限制

本次盘点主工作区 `docs/superpowers/specs` 的 15 份 Markdown 设计稿、`docs/superpowers/plans` 的 15 份 Markdown 计划/路线图，并对照已登记工作树的同名文档及额外的 Stage 2 计划、相关模块、路由和 Git 提交归属。查看关键状态和依赖，不把文档中全部测试步骤当作本轮任务。

未读取 `data/`、业务数据库、凭据或备份，未运行测试、启动服务、触发 CI 或验收。远端 PR、正式部署和所有历史原始验收产物未逐一刷新。表内历史验收结论引用现有项目记录，不能视为新 SHA 的发布证据；分支及入口状态在后续任务中需按需刷新。

## 当前代码位置

下表 Stage 4 行为最新交付位置；其他旧分支条目为前序盘点快照，本轮没有刷新全部分支或远端。

| 位置 | 核对时版本 | 说明 |
| --- | --- | --- |
| 本地主分支 `master` | `4402206` | 已包含 P0、第一次 CI 用量优化、商品候选与审核体验修复、Stage 1 代码和 Stage 0 冻结记录；不包含 Stage 2 最终候选或 Stage 3 首批代码。 |
| 主工作区 `D:/CLSEN_Data_Web`，`codex/development-throughput` | `7de0ee6`，另有本轮未提交流程文档 | 有 Stage 2 收尾记录，但记录存在不代表其业务代码已整合。 |
| `.worktrees/stage2-worker-observability`，`codex/stage3-ui-foundation` | `28684cf` | Stage 3 已验收、PR #9 已合入 Stage 2 分支；包含 Stage 2 候选 `c924e4a` 与后续 UI 基础体系。目录名保留 Stage 2，实际分支为 Stage 3。 |
| `.worktrees/stage4-1-app-shell`，`codex/stage4-1-app-shell` | `ec0a72e` + 未提交 Stage 4 成果 | 当前业务开发位置；4.1、4.2①、②/R、A、B1/B2、C、D 已完成开发与体验，交付 schema 为 0027；不将基线 SHA 当作全部未提交成果的验收 SHA。 |
| `.worktrees/stage2-responsive-width` | `55a5b29` | 历史自适应样式体验版本；其差异已纳入 Stage 2 组合验收，不作为新的独立功能线。 |
| `D:/CLSEN_Data_Web-worktrees/project-optimization-stage1` | `8981656` | 历史工作树；后续 schema 保护相关修复已进入主分支，不能只看该旧 HEAD 判断当前功能。 |
| `D:/CLSEN_Data_Web-worktrees/read-only-agent-analysis-implementation` | `a4bdeb9` | 最近提交仍是设计和计划；分支名含 implementation 不代表 Agent 已实现。 |
| `D:/CLSEN_Data_Web-worktrees/ui-quick-prototype` | `fadc768` | 另有运营总览 UI 原型和本地代理配置；独立保留，不能算入 Stage 3 正式交付。采用其中内容前按实际 diff 选择。 |

前序盘点通过提交祖先关系确认（以下为历史核对，非本次重新检查）：`47f401c`（P0 基础）、`e2325b5`（CI 优化）、`76b6209`（证据 JSON 限界）、`9cd0431`（审核体验）均在 master、主工作区和 Stage 3 分支中；`c924e4a`、`ca9aaac` 仅在上述 Stage 3 分支中。未执行 merge、push 或清理工作树。

## 所有计划线

以下保留各来源的待办和恢复条件，Stage 3 状态已按最新确认更新。表中“下一步”只有已映射到上方唯一主线的内容进入排程，其余保持暂停。历史完成项保留合同和证据，不为补勾选框重新测试。

| 计划线与来源 | 核对结论 | 剩余事项 / 下一步 |
| --- | --- | --- |
| 日报审核与可视化 MVP：[设计](../superpowers/specs/2026-08-06-daily-data-review-platform-design.md)、[实施](../superpowers/plans/2026-08-06-daily-data-review-platform-implementation.md) | 已有导入、解析、审核、发布、看板、权限、备份和容器部署代码；实施文档记录本地 MVP 与 10B 容器验证已完成。设计开头的数据库版本和阶段状态是旧快照。 | 正式服务器域名/证书、生产迁移、真实机器恢复等仍需部署任务核实，不把本地容器验收当作正式上线。 |
| 可编辑日期工作台：[设计](../superpowers/specs/2026-08-14-editable-date-data-workbench-design.md)、[实施](../superpowers/plans/2026-08-14-editable-date-data-workbench-implementation.md) | 状态段记载 Tasks 1–10 已实施及 Task 11 验证；`backend/app/workbench` 与前端 workbench 已存在。正文未勾选项不能推翻后来的实现状态。 | 按实际使用反馈维护；本次未重新确认全部人工体验记录。 |
| 日期表格结构增强：[设计](../superpowers/specs/2026-08-14-date-workbench-structural-table-enhancement-design.md)、[实施](../superpowers/plans/2026-08-14-date-workbench-structural-table-enhancement-implementation.md) | 共享列展示、列偏好、表头和设置组件已存在于 `frontend/src/components/data-table`；缺少统一收尾状态。 | 标为“实现已存在、交付结论待核实”，不要按未勾选步骤从头重建；只在相关体验任务核对余项。 |
| 总表首页与审核优化：[设计](../superpowers/specs/2026-08-14-ledger-home-and-workflow-optimization-design.md)、[UI 契约](../superpowers/specs/2026-08-14-ledger-home-ui-contract.md)、[实施](../superpowers/plans/2026-08-14-ledger-home-and-workflow-optimization-implementation.md) | 首页与产品视图已有代码；其旧 Seller SKU parser / modal 路径和 P0 新产品分析是两种身份来源，不是两份可随意混合的实现。 | 旧入口后续受 P0 整套选择器和回滚合同约束；不恢复已由 P0 取代的身份模型，不把遗留页面自动认定为缺失功能。 |
| 跨日期发布明细：[设计](../superpowers/specs/2026-08-14-cross-date-published-detail-ledger-design.md)、[实施](../superpowers/plans/2026-08-14-cross-date-published-detail-ledger-implementation.md) | `published_details` 后端、`PublishedDetailLedgerPage` 和 `/ledger/published-details` 路由已落地；文档缺少统一收尾结论。 | 汇报为实现已存在，历史正式验收/人工确认待核实；不从头执行原九项任务。 |
| 蓝白视觉系统：[设计](../superpowers/specs/2026-08-14-blue-white-visual-system-design.md)、[实施](../superpowers/plans/2026-08-14-blue-white-visual-system-implementation.md) | 已有 Token、样式和共享组件基础；平台 Stage 3/4 又覆盖相同的视觉统一与页面迁移。 | 后续 UI 工作以平台 Stage 3/4 排程，旧设计作为视觉约束和差距参考，不作为并行重做计划；尚未核实“全站完成”。 |
| 批量审核：[设计](../superpowers/specs/2026-08-17-batch-review-workflow-design.md)、[实施](../superpowers/plans/2026-08-17-batch-review-workflow-implementation.md) | `batch_review`、`BatchReviewPage`、`/review/batch/:runId` 已存在，并有 `8e2fb34` 等后续修复。 | 第一版明确由浏览器执行且排除 Worker。若要改成真正后台批处理，是需单独安排的行为变更，不能用 Stage 2 四队列监控宣称已经覆盖。 |
| 商品主档 P0 与款式分析：[设计](../superpowers/specs/2026-08-19-product-style-variant-analytics-foundation-design.md)、[实施](../superpowers/plans/2026-08-20-product-style-variant-analytics-foundation-implementation.md) | 代码已进入本地主分支；实施状态记载 Tasks 0–20、A/B 真实链路及历史候选门禁通过。设计开头仍停在 successor 待批准。 | 不再报“P0 尚未编码”。历史候选通过不代表当前 SHA 部署通过；新业务优化按下一行安排。 |
| 商品卡与增量维护：[设计](../superpowers/specs/2026-09-02-product-catalog-card-maintenance-design.md)、[实施 v1.0](../superpowers/plans/2026-09-07-product-catalog-workbook-optimization-implementation.md) | 4.2①、②/R、A、B1/B2、C、D 均已完成开发与人工体验；成果仍在 stage4-1-app-shell 未提交改动中。 | 本专项不重做；接续剩余 4.3 页面。历史治理和规模化归 Stage 5，正式发布验收待部署准备。 |
| 生产订单与完工入库：[设计](../superpowers/specs/2026-08-18-finished-goods-production-receipt-design.md)、[实施](../superpowers/plans/2026-08-18-finished-goods-production-receipt-implementation.md) | 计划明确暂停，未发现对应 production 后端领域或前端业务模块。P0 历史 Milestone A 已通过，但不自动解除 successor 再次批准及目标目录 V1 条件。 | 恢复前重编 successor，并解决旧计划 `0023/0024` 与 Worker `0023` 占号冲突；不改写已应用迁移、不迁移真实库。 |
| 全链 SKU 供应链：[路线图](../superpowers/plans/2026-08-18-end-to-end-sku-supply-chain-roadmap.md) | A/B 承接上一行；E0（Amazon 标识）、C（出货/海运）、D（FBA）、E（全链分析）仍是待决策的路线图，未发现独立详细计划或对应业务实现。 | 按第 7 节补齐模板、操作角色、实际离厂事实、FBA 实收与短溢收等业务决定后再拆任务。现有 P0 映射和销售趋势不能冒充 E0/E 全链交付。 |
| 只读 Agent 分析 11A：[设计](../superpowers/specs/2026-08-12-read-only-agent-analysis-design.md)、[实施](../superpowers/plans/2026-08-12-read-only-agent-analysis-implementation.md) | 有计划和单独工作树，但 HEAD 仍在文档提交。主代码只有 `agent_tools` 工具边界，未发现 `/agent` 对话页或完整独立 Runtime。 | 保留未开工/待恢复；需对当前模型、数据快照、备份分类、迁移 head 和原安全合同重新核对，不将工具接口当作可用 Agent 产品。 |
| 可切换应用发布 11B：[设计](../superpowers/specs/2026-08-12-switchable-application-release-management-design.md)、[实施](../superpowers/plans/2026-08-12-switchable-application-release-management-implementation.md) | 设计与计划存在，完整签名发布目录和持久发布控制器未见实现。原计划明确依赖 11A 全部任务。 | 保留待规划；普通 Compose 部署能力不等于 11B。若只需部署现有应用，沿用既有部署手册，不把可选新控制器当作现有产品上线的默认前置。调整 11A/11B 依赖须明确决定。 |
| CI 用量优化：[设计](../superpowers/specs/2026-08-26-ci-actions-usage-optimization-design.md)、[实施](../superpowers/plans/2026-08-26-ci-actions-usage-optimization-implementation.md) | 旧计划写未实施，但 `e2325b5`、suite manifest、profile runner 和新的 workflow 已存在。第一次 CI 优化已有实现；历史耗时、取消运行等外部验收本次未刷新。 | 与新要求分开：下一轮是“PR 定向检查、部署前完整门禁”，仍未迁移。不能把旧 CI 计划重跑一遍当作落实新要求。 |
| 平台优化：[路线图](../superpowers/specs/2026-08-27-project-optimization-roadmap-design.md)、[Stage 0](../superpowers/plans/2026-08-27-project-optimization-stage-0-implementation.md)、[Stage 1](../superpowers/plans/2026-09-01-project-optimization-stage-1-schema-fail-fast-implementation.md)、[Stage 2 工作树计划](../../.worktrees/stage2-worker-observability/docs/superpowers/plans/2026-09-04-project-optimization-stage-2-worker-observability-implementation.md) | Stage 0 有冻结批准记录；Stage 1 保护代码已入主分支；Stage 2 accepted；Stage 3 `28684cf` accepted / merged_to_stage2_branch；Stage 4.1、4.2① development_complete / user_verified。 | 4.2②/R、A、B1/B2、C、D 均 development_complete / user_verified；下一项为剩余 4.3 页面，master 整合待指令，正式部署完整测试留至部署准备。 |

## 已确认的遗漏与冲突

### 1. Worker 监控与商品任务恢复范围（恢复缺口已由 4.2① 交付）

[Stage 2 计划](../../.worktrees/stage2-worker-observability/docs/superpowers/plans/2026-09-04-project-optimization-stage-2-worker-observability-implementation.md) 明确不修改四类队列原状态机、租约、fencing、重试和恢复，也不新增强制重试控件。平台路线图还明确 `catalog_export` 无 claim/lease、无计划重试。

因此“有心跳、状态和失败提示”不等于商品卡方案中的退避、最大重试、人工恢复和真实进度已完成。该缺口已由 Stage 4.2① 完成开发与人工体验；其关闭依据是该批交付记录，而非 Stage 2/3 的验收。正式发布验证仍按部署准备安排。

### 2. 生产迁移编号已经冲突

生产旧计划将订单/完工入库排为 `0023/0024`，Stage 2 已创建 [0023_worker_observability.py](../../.worktrees/stage2-worker-observability/backend/alembic/versions/0023_worker_observability.py)。早期盘点时主工作区为 `0022`、Stage 3 工作树为 `0023`；最新 Stage 4 商品主档交付记录已到 `0027`。这些是代码/隔离体验版本，不能推断真实数据库版本。

后续生产、11A、11B 的迁移必须基于选定整合候选的实际 Alembic head 分配下一个空闲编号；本次不预留新编号、不修改历史迁移，也不修改已批准计划的哈希基线。生产恢复仍需 successor 确认。

### 3. 状态与旧文档不一致

| 旧表述 | 当前可核对事实 | 使用规则 |
| --- | --- | --- |
| CI 实施计划第 13 行“未实施” | 优化提交和脚本已在主分支 | 将其视为执行前快照，不重新开工；外部验收单独核实。 |
| P0 设计开头 successor 待批准 | 实施计划记录批准及 Tasks 0–20 完成，代码已集成 | 需求继续引用版本化设计，进度引用后续执行记录和实际代码。 |
| 原 MVP 设计仍引用早期阶段/数据库版本 | 后续实施记录已经覆盖本地 MVP/10B | 不引用早期环境快照回答当前部署状态。 |
| 工作台等计划仍有大量未勾选框 | 同一文件状态段及代码显示已实现 | 不按勾选比例报告进度或触发重跑；人工与发布结论缺失则明说。 |
| 平台路线图开头仍待书面复核 | 后续 Stage 0 已有冻结批准、Stage 2 已收尾 | 后续事实证明具体工作已发生，不据此推断全部未来阶段均获授权。 |
| 主目录写 Stage 2 accepted | 主目录不含其业务提交，工作树才有 | 同时标记功能结论与代码集成位置。 |

本索引是当前状态补充；原设计、批准基线、历史运行失败和受限复用合同保持原样。没有新证据时保留待核实，不能仅为让表格全绿而写 accepted。

### 4. 重叠计划需要合并排程

- 蓝白视觉、UI 原型、平台 Stage 3/4 是同一界面体系的不同来源；按页面差距收敛，不安排三轮全站重写。
- 商品卡 UI 复用 Stage 3 已稳定的基础组件；业务归属、冲突、来源和历史修正仍由商品主档计划负责，不能只做换皮就关闭该计划。
- 发布流程分清三件事：已有 Compose 运维、新 CI 分层、尚未实现的 11B 自动发布控制器。它们不是同一个“部署完成”状态。
- 日报“发布版本”和应用“发布版本”必须注明对象；P0 产品分析切换也不等于整套应用发布控制器。

## 下一轮入口

[新主线第1项：当前发布范围与基线核对](../superpowers/plans/2026-09-14-current-release-and-java-evolution-roadmap.md)已完成，Stage5.1/5.2范围也已由用户确认收尾。部署准备当前为`in_progress / candidate17_collect_failed / ubuntu_full_passed / windows_smoke_passed / frontend_full_passed / mysql_8_0_failed / collect_stopped / collect_awaiting_targeted_fix_authorization / canonical_clean_sha_prerequisite_unresolved / targeted_experience_complete`：候选17本地Collect在MySQL 8.0旧迁移头测试合同首因处停止；下一批仅在另行授权后同步`test_migrations.py`的0028 head及历史序列，定向验证并冻结候选18，候选18完整Collect仍需再次授权。#9/#35确认因业务语义未变而保留，V35仍为历史证据不足；clean-SHA前置不因本地预演解除。原5.1四批及D1–D8不作为当前执行入口，不重新安排已确认Stage 4体验。Java详细规划仍在部署准备完成后进行。

### 历史交付与体验摘要（保留证据，不是当前执行口令）

商品主档 R/A/B1/B2/C/D 与发布数据查看（含单日摘要月内趋势）为 `development_complete / user_verified`。当前 P0 产品总表 → 款式详情为 `development_complete / user_verified`，入口 http://127.0.0.1:18615/products?from=2025-07-01&to=2025-07-18 ，复用 Run ID `d9f9e41881224205af5255261df23e88` 的隔离 API/合成数据。原 18614 入口保留。

本批完成共享控件/反馈/分页、局部样式、趋势配色与无障碍标识，以及详情更新 URL 后返回原筛选和焦点。7 个受影响组件文件累计 13 项测试通过（失败修复后仅重跑受影响文件），TypeScript 与目标 ESLint 通过；真实浏览器走通切换指标及返回，1280/390px 无页面溢出或脚本错误。后续产品趋势坐标可读性与 ECharts/Motion 适用性已在开发流程的独立收尾批次处理。

日期表格 → 单日审核 → 返回路径现为 `development_complete / user_verified`。体验入口 http://127.0.0.1:18615/published/2025-07-18?report_type=business_report ，同一隔离 Run ID；已准备修订 v2（version_id=4），标题快检编辑已撤销，发布仍为 v1。本批 66 项目标组件测试、TypeScript/目标 ESLint 及桌面/390px 路径检查通过。审核控件、发布确认与批量审核现为 `development_complete / user_verified`。单日入口 http://127.0.0.1:18615/review-advanced/2025-07-18?report_type=business_report&version_id=4 ，批量预检入口 http://127.0.0.1:18615/review/batch/1 。44 项受影响测试、TypeScript/目标 ESLint 通过；真实隔离预检有 2 项需人工核对、0 项可执行，未启动批量处理或发布。本轮审核外层、批次备注与来源预览组件已完成局部样式/共享控件迁移，状态 `development_complete / user_verified`，沿用单日审核入口。67 项受影响组件测试、TypeScript/目标 ESLint 通过；真实隔离样例完成备注展开/临时输入清空、日期切换与 390px 检查。目标日期重复记录决定、五轮草稿工作区排版反馈及最后一批草稿维护/发布回执均已获用户体验确认。Stage 4.3 当前为 `development_complete / user_verified`，全部开发批次与人工体验已完成；不重做已交付商品主档，不自动进入 Stage 5。

成果仍在 stage4-1-app-shell 工作树，基线 `ec0a72e` 加未提交改动，未合入 master、未部署。后续恢复体验时重新核实当前入口，不根据本记录推断服务持续运行；正式发布验收留部署准备。

## 如何维护这份索引

- 整体进度查询先读当前执行决定，再刷新相关分支、任务和状态来源；报告当前 Stage/批次、开发与体验状态、正式验收待办及整合状态；主线外计划标明暂停。
- 新计划或可体验批次只更新所属行的版本、状态、余项和下一步。已存在的验收证据仍放原位置，不建立第二套证据系统。
- 普通功能任务只读所属行和相关上下文，无需每次重新遍历全部计划。
- 总体汇报至少区分：业务功能、平台优化、暂停/待决定、集成/部署。不按文件数、测试数或 checkbox 数给出虚假的完成百分比。
- 开发状态、用户体验、正式验收继续遵循 [开发流程](../operations/development-workflow.md)；本次索引只接受文档审阅，不额外构建 UI。

2026-09-09 review-22：图表指标与单位提示已同步隔离入口，development_complete / ready_for_user_review；11项定向测试通过，保留原试用边界与F-01/F-11，详见真实数据试用计划。

2026-09-09 review-23：修复原生SVG提示与数据点tooltip重叠，10项图表目标测试通过，同步隔离体验入口，ready_for_user_review；其余试用边界不变。

2026-09-09 review-24：款式详情折线图review-23已获用户确认（user_verified），指定为后续参考；新增9个Storybook场景已在http://127.0.0.1:6006/就绪（ready_for_user_review），详见真实数据试用计划。整体试用未完成、未进入Stage 5。

2026-09-10 当前体验交接：7月7日完整修正版测试副本已准备(correction-trial)，仅一行销售额+US$10，预期22行/1338.69/31销量/666会话；管理角色和上传入口实核可用。更正发布路径ready_for_user_review，未导入或发布，详见真实试用计划末尾。代码review-26无需重启，整体未完成，F-11保留。







