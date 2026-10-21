# 功能交付优先的开发流程

## 2026-09-14 Hostinger共机部署资料归档

用户要求将服务器配置写入项目，为Data_Web与Alpha共机部署准备。已新增[Hostinger共机部署参考](hostinger-shared-vps-deployment-reference.md)，区分历史快照、用户提供的5分钟监测、已报告配置及未确认建议；保留磁盘容量口径差异、Traefik实际版本/Swap未知、无独立MySQL一致性备份、Alpha部分服务无日志轮转等缺口。

状态：文档资料准备完成；服务器核验、DNS/代理配置、MySQL部署、备份恢复和应用验收未由本任务执行。适用对象为用户选定的Hostinger共享VPS及记录中的Alpha v0.5.0，不改候选11或其开发/体验/验收状态。仅文档格式与链接检查，不读取业务数据、不连接服务器、不修改Alpha或现有环境、不提交部署。本批无需Skill。

> 最新状态（2026-09-15，候选20）：用户批准的完整本地Collect已执行并在Storybook a11y首因处停止。Ubuntu-full、Windows smoke、Frontend静态/单测、Playwright 14/14及Storybook构建通过；a11y为22通过、1失败，唯一错误是390px故事的`Axe is already running`。定向生命周期诊断确认addon自动`axe.run()`与外部`AxeBuilder.analyze()`偶发竞争，不是已发现的业务UI或可访问性违规。候选20保持冻结，未生成候选21；#9/#35体验确认不重开，V35仍为历史证据不足，不提交、整合、push、迁移或部署。

## 当前统一状态（2026-09-14，覆盖下方旧状态）

“当前发布范围与基线核对”已完成。用户已确认Stage5.1无R1/R2新增代码项、Stage5.2不启动预设重构，两阶段均记为 `scope_closed / no_implementation_required`，未实施业务代码。Stage 4当前为44组已确认；#9/#35均已在候选02确认，#40材料已纳入候选20且Storybook静态构建通过。本轮a11y因测试生命周期竞争停止，视觉及后续门禁未执行；`release_validation = not_started`，业务成果仍在 `stage4-1-app-shell / ec0a72e` 加未提交修改，未整合或部署。

部署准备当前为 `in_progress / candidate20_collect_failed / ubuntu_full_passed / windows_smoke_passed / frontend_unit_and_browser_passed / storybook_build_passed / storybook_a11y_failed / storybook_a11y_root_cause_confirmed / collect_stopped / fix_awaiting_new_authorization / canonical_clean_sha_prerequisite_unresolved / targeted_experience_complete`。候选20保持冻结；#9/#35体验继续保留，正式`release_validation`未开始。测试合同修正、下一候选Collect、形成提交SHA、整合、push、远端正式门禁与实际部署继续分别授权。

**候选09结果覆盖：** 当前状态为 `in_progress / candidate09_collect_failed / windows_smoke_passed / ubuntu_full_passed / frontend_lint_passed / frontend_typecheck_passed / frontend_tokens_passed / frontend_unit_tests_failed / collect_awaiting_new_authorization / targeted_experience_complete`。候选09的Windows/Ubuntu结果见本次授权Collect；Frontend直接工具的ESLint、TypeScript和Token通过，Vitest在`CatalogMaintenancePage.test.tsx`测试夹具契约错误处停止（426项通过、1项失败，并有1项未处理错误）。夹具对`/api/catalog/imports`返回`{catalog:null}`，而后端列表契约及`CatalogImportHistory.test.tsx`要求`items/has_next`，因此现有证据不支持业务实现缺陷。浏览器、Storybook、生产构建、MySQL及后续门禁未执行；下一批仅建议修正该测试夹具并定向验证，未获本轮授权，不重开#9/#35体验。

**候选11结果覆盖：** 第二次本地Collect新鲜执行Ubuntu-full与Windows smoke通过；Frontend lint、typecheck、Token及Vitest 90文件/427项通过，Playwright 5通过/9失败后停止。失败来自5个既有E2E合同文件未同步当前实现，文件在候选10/11哈希相同；现有证据不支持候选11业务回归。其余门禁未执行，#9/#35体验确认、Stage5.1/5.2范围及不提交/不部署边界保持不变。

**候选13结果覆盖：** 候选12第二次Collect的异步URL断言已按相邻测试模式最小同步并冻结候选13；候选13完整本地Collect的Ubuntu-full、Windows smoke及Frontend lint/typecheck/Token通过，Vitest在`ImportReviewFlow.test.tsx:194`的既有测试隔离首因处停止。候选12历史证据按原节保留，正式`release_validation`仍未开始。

**候选14结果覆盖：** 候选13的测试隔离首因已按既有hook合同机械同步并冻结候选14；随后候选14完整本地Collect的Ubuntu-full、Windows smoke及Frontend lint/typecheck/Token通过，Vitest在`App.test.tsx:185`的既有列表夹具合同首因处停止。候选13历史证据按原节保留，正式`release_validation`仍未开始。

**候选15结果覆盖：** 候选14的目录入口测试夹具首因已按后端及组件既有`items/has_next`合同最小同步，原失败节点、4个相邻权限入口及目标ESLint通过并冻结候选15。该结果只解除已定位的测试夹具阻塞，不代表候选15完整Collect或正式发布验收通过；候选14完整Collect结果保留为历史记录。

**候选15完整Collect结果覆盖：** Ubuntu-full、Windows smoke及Frontend静态/单测通过；Playwright在`batch-review.spec.ts:156`的异步计数同步缺口处以13通过、1失败停止。Storybook、生产构建、MySQL及后续门禁未执行，正式`release_validation`仍未开始。

**候选17结果覆盖：** 候选16完整Collect的`MergeDecisionMatrix.test.tsx:41`异步通知首因已定向修正并冻结候选17；随后候选17完整本地Collect的Ubuntu-full、Windows smoke及Frontend完整段通过，MySQL 8.0在`test_migrations.py`旧head常量处以27通过、3失败停止。MySQL 8.4及release-only未执行，正式`release_validation`仍未开始。

**候选20结果覆盖：** 候选19的旧`0024` newer夹具已同步并冻结候选20；随后完整本地Collect在Storybook a11y双扫描竞争处以22通过、1失败停止。定向生命周期探针确认首因属于addon自动扫描与外部扫描并发，不是已证实的业务UI或WCAG违规。候选20保持冻结，修正及下一候选均待另行授权，正式发布验收未开始。

下方旧记录保留为当时证据；旧“下一步核对、待体验、待修复”等状态由本节及[计划索引核对清单](../workflow/project-plan-index.md#2026-09-14-当前发布范围与基线核对清单)覆盖。本批只在候选外一次性Ubuntu容器中定向复现一个Storybook a11y节点并采集生命周期，未访问业务原件、`data/`或业务数据库，未修改候选或体验环境。

本批实际Skill：`systematic-debugging`用于只围绕390px Story追踪addon/axe生命周期竞争；`verification-before-completion`用于复核定向运行、候选身份和停止边界。未修改候选、业务代码、依赖或体验环境，未提交、整合或部署。

### 2026-09-15 部署准备：候选20 Storybook a11y首因定向诊断

- 同一锁定Ubuntu环境只运行原390px `narrow-and-long-chinese`节点，连续5次通过；这说明原失败不是故事单独运行时稳定发生，也不能据此覆盖完整Collect失败。
- 候选外探针仍只打开同一故事并使用相同WCAG标签扫描。10轮结果为5次通过、5次`Axe is already running`；通过轮serious/critical均为0。失败轮在手工扫描前`window.axe`尚不存在，随后采样到约十余毫秒的`_running=true -> false`，错误栈仍落在外部`AxeBuilder.runPartialRecursive`。
- 只读代码确认`.storybook/preview.ts`启用`a11y.test = "todo"`，addon默认`globals.a11y.manual = false`；`@storybook/addon-a11y 10.6.0`的preview `afterEach`调用自身队列内的`axe.run()`，而项目`a11y.spec.ts`并行调用外部`AxeBuilder.analyze()`。addon内部队列不会串行化外部扫描，构成同一iframe的双扫描竞争。
- 首因属于测试/Storybook执行合同，不是候选20唯一后端夹具变化引入，也没有业务UI缺陷、WCAG违规、数据异常或数据丢失证据。当前a11y门禁仍失败并阻塞后续发布准备；候选20保持冻结，未生成候选21。
- 下一批最小范围需另行授权：只在测试/Storybook配置范围消除自动扫描与外部扫描的并发，保持故事覆盖、WCAG标签和serious/critical断言不变；运行原失败节点与目标静态检查，通过后冻结下一候选。不得增加重试、跳过测试、删除断言或降低标准，也不得自动启动完整Collect。
- 证据目录为`D:/CLSEN_DeploymentPrep_20260914/candidate20-a11y-diagnosis`。首次外部容器包装在任何测试前因PowerShell/Bash转义及一次性目录问题退出，仅保留为调用预检，不计候选失败。
- 本批实际Skill：`systematic-debugging`用于复现和确定双扫描首因；`verification-before-completion`用于限定证据与状态声明。

### 2026-09-15 部署准备：候选20完整本地Collect结果

- 运行前`candidate-source-20`与`gate-run-20`按232项manifest复核五类差异均为0；HEAD、overlay SHA-256 `0a292f4e6dcf1731f161f494d98a9bea595d7780569147d43b6237e2a8b6e6c2`及manifest SHA-256 `fa3db8fd56677c42ed6beb42c5c4e40c02c58732c1e19bcac6fbb88fe39d7bf9`均与冻结记录一致。
- Ubuntu-full通过Ruff、399文件format、397源文件mypy及pytest执行范围（1242通过、2跳过、352排除）；Windows smoke为376通过、2跳过。Frontend通过496项供应链策略、ESLint、TypeScript、Token、Vitest 90文件/427项、Playwright 14/14及Storybook静态构建。
- Storybook a11y为22通过、1失败；唯一失败是390px `narrow-and-long-chinese`节点的`Axe is already running`，没有输出serious/critical违规。候选19/20相关a11y测试、Storybook配置、package和lockfile哈希相同，候选20唯一内容变化仍是后端revision夹具，现有证据不支持业务UI回归。
- 按首因停止，Storybook visual 27项、两种生产构建、MySQL 8.0/8.4、generated-contract、性能、恢复、部署及其他release-only门禁未运行。日志位于`D:/CLSEN_DeploymentPrep_20260914/candidate20-collect-logs`；本地预演不记为正式`release_validation`。
- 候选20保持冻结，未生成候选21，不自动修复或循环Collect；canonical clean-SHA前置仍未解决，形成clean SHA、整合/push、正式门禁及部署继续分别授权。

### 2026-09-15 部署准备：候选20 schema newer测试夹具同步与冻结

- 仅将`backend/tests/integration/test_schema_compatibility.py`参数表中的`("0024", REVISION_NEWER, "0024")`改为`("0029", REVISION_NEWER, "0029")`，确保样例高于当前`0028`；生产revision分类、迁移与其他测试断言不变。最终diff为1行替换。
- 单文件Ruff lint与format检查通过。MySQL开发矩阵以正确`mysql-schema-startup` suite和文件allowlist启动随机可抛弃8.0容器，隔离库升级到0028后用`-k test_mysql_revision_shape_refuses`选择5个参数，结果5通过、5排除、0.41秒，脚本退出0。首次误用`mysql-legacy`在第74行allowlist检查处、启动容器前退出，仅属调用配置错误，不计为候选测试失败。
- 候选20清单含146个修改、81个未跟踪、5个删除，共232项；内容身份`ec0a72e907cf7787536cf73964f7897485e28c97+overlay-sha256:0a292f4e6dcf1731f161f494d98a9bea595d7780569147d43b6237e2a8b6e6c2`，manifest SHA-256为`fa3db8fd56677c42ed6beb42c5c4e40c02c58732c1e19bcac6fbb88fe39d7bf9`。source/gate双副本按232项核验五类差异均为0，HEAD均为`ec0a72e`；候选19/20文件数组只有目标测试一项变化。
- 候选20完整本地Collect仍需再次明确授权；canonical clean-SHA前置未解决，形成提交、整合/push、正式门禁及部署继续分别授权。本批不自动Collect、不修改业务代码、数据、依赖或体验环境。
- 本批实际Skill：`systematic-debugging`用于沿候选19已确认首因保持单点夹具修正；`verification-before-completion`用于Ruff、MySQL参数节点、容器清理、manifest及双副本核验。

### 2026-09-15 部署准备：候选19完整本地Collect结果

- 运行前按manifest逐项复核`candidate-source-19`与`gate-run-19`的231项，双副本均为`missing=0 / mismatch=0 / deleted_present=0 / extras=0 / omitted=0`；HEAD、overlay hash和manifest hash均与冻结记录一致。候选仍是`ec0a72e+overlay`，canonical clean-SHA前置未满足且未绕过，本轮证据只属于本地同顺序预演。
- Ubuntu-full通过Ruff、399文件format、397源文件mypy；pytest为1242通过、2跳过、352排除。Windows smoke为376通过、2跳过。Frontend在既定Ubuntu锁定镜像中通过496项供应链策略、ESLint、TypeScript、Token、Vitest 90文件/427项、Playwright 14/14、Storybook构建、a11y 23/23、visual 27/27及两种来源生产构建。
- MySQL 8.0迁移组30/30通过、2806.77秒；兼容性组256通过、1失败、1 warning、2279.84秒。唯一失败节点`test_mysql_revision_shape_refuses[newer]`保留旧参数`0024 -> REVISION_NEWER`，而当前revision源为`0028`，运行时按既有数值比较返回`REVISION_OLDER`。候选18/19的该测试文件和revision实现哈希一致，失败测试不是候选19变化项；证据支持测试夹具未同步，不证明业务逻辑、数据库状态或历史数据异常。
- 按首因停止，MySQL 8.4及release-only门禁未运行；矩阵容器已清理。候选19保持冻结、没有候选20，日志根为`D:/CLSEN_DeploymentPrep_20260914/candidate19-collect-logs`。下一批仅建议在另行授权后同步这一参数夹具并做原节点、必要相邻参数和目标Ruff验证，之后才可冻结下一候选；不自动再次Collect。
- 本批实际Skill：`systematic-debugging`用于只读核对唯一失败的预期值、当前revision和分类函数；`verification-before-completion`用于新鲜读取各段完整摘要、容器清理及候选身份。未修改业务代码、数据、依赖或体验环境，未提交、整合、push、迁移或部署。

### 2026-09-15 部署准备：候选19 0025 downgrade密封约束恢复与冻结

- 只修改`backend/alembic/versions/0025_catalog_categories_and_style_changes.py`的downgrade，为`product_catalog_versions`、`product_catalog_publication_events`和`catalog_exports`三条由0025改写的CHECK约束显式恢复ASCII字符串字面量。业务允许值、upgrade、0022 seal、测试合同、依赖和体验环境均未改变。
- 首次绿色运行仅修最早product versions约束后，原测试已越过该表并在publication events同类seal处停止；源码核对显示0025共改写三条0022密封表的ASCII代码字段约束，因此在同一根因、同一文件内补齐三条，而未放宽seal或删除断言。首次日志`D:/CLSEN_DeploymentPrep_20260914/candidate19-targeted/mysql-8.0-two-catalog-schema-nodes.log`保留。
- 最终定向MySQL 8.0使用正式开发测试入口和随机可抛弃Oracle容器，只选择两个原失败节点，结果2通过、1排除、耗时29.76秒，脚本退出0；目标文件Ruff lint及format检查均退出0。最终日志为`D:/CLSEN_DeploymentPrep_20260914/candidate19-targeted/mysql-8.0-two-catalog-schema-nodes-02.log`，未运行其他MySQL节点或完整Collect。
- 候选19清单`D:/CLSEN_DeploymentPrep_20260914/evidence/candidate-overlay-manifest-19.json`含145个修改、81个未跟踪、5个删除，共231项；内容身份为`ec0a72e907cf7787536cf73964f7897485e28c97+overlay-sha256:8b3fdeb92b48d495912282d5d766154f1b03ed46747b3f71495e0622fabe048d`，清单SHA-256为`5045c7b71ce7ad088566ed162ead8ba2227919154769c830a201416eb78ded2c`。
- 候选18/19只有目标迁移文件内容变化。`candidate-source-19`和`gate-run-19`均为detached HEAD `ec0a72e`，231项复核均为`missing=0 / mismatch=0 / deleted_present=0 / extras=0 / omitted=0`；候选18及其日志、诊断证据保持不变。
- 下一步只在再次明确授权后启动候选19完整本地Collect，从头按既定顺序并首因停止。候选仍不满足canonical clean-SHA合同；形成clean SHA、整合/push、正式门禁和部署继续分别授权。

### 2026-09-15 部署准备：候选18 MySQL 8.0首因定向诊断

- 只运行`test_catalog_schema.py`中两个授权节点，每个节点使用独立随机可抛弃Oracle MySQL 8.0容器，结果均为1失败、2排除并复现`product_catalog_versions sealed signature`；这样排除了候选18完整Collect中首项finally失败对第二项的数据库污染影响。
- 候选外诊断目录为`D:/CLSEN_DeploymentPrep_20260914/candidate18-targeted-diagnosis`。探针复用0022 `_schema_signature`的查询与序列化规则，在0022 seal、0025 upgrade及0025 downgrade目标DDL前后记录comment、digest、workbook约束及索引。原始0022稳定digest为`bb5684fd6afc1d231ceebd1bfc948919b212fc691e424376851999bbd82e611c`且comment匹配；workbook约束表示为`_ascii'product_catalog_workbook_v1'`。
- 0025 upgrade把该约束扩为v1/v2；0025 downgrade重建v1约束后，其表示变为`_utf8mb4'product_catalog_workbook_v1'`。原始与降级后的列数量一致、索引表示完全一致，约束表示不一致；降级后digest为`36d99eaa72425f15d136a4b71420e6007593b23db8f399418065889610591466`，原comment仍记录`bb5684fd…`，所以0022部分恢复的sealed signature检查正确拒绝该状态。
- 结论为0025 downgrade迁移实现没有恢复0022 seal要求的精确物理约束表示；测试合同和0022保护均按既有意图工作。该缺口必须在发布前修复，但当前证据只覆盖降级/部分恢复路径，不证明forward upgrade、当前业务数据或候选18新增测试合同存在问题。
- 候选18 manifest SHA-256仍为`01abd0082ebbab155106ecac6ac4457ca2b2e3890dfe563cef534d8063af8208`。用户随后授权继续，最小修正及候选19冻结已按上方记录完成；候选18、其日志和诊断证据保持不变。

### 2026-09-15 部署准备：候选18完整本地Collect结果

- 用户授权冻结候选18执行一次完整本地Collect。候选仍是`ec0a72e`加231项overlay，未满足canonical runner clean-SHA合同且未绕过；本轮在`gate-run-18`和Ubuntu 24.04锁定Frontend容器按既定顺序执行本地预演，日志位于`D:/CLSEN_DeploymentPrep_20260914/candidate18-collect-logs`，不计为正式`release_validation`。
- Ubuntu-full中Ruff、399文件format、397源文件mypy通过，pytest为1242通过、2跳过、352排除；Windows smoke为376通过、2跳过。Frontend有效完整日志`03c-frontend-full-ubuntu.log`记录496项供应链策略、ESLint、TypeScript、Token、Vitest 90文件/427项、Playwright 14/14、Storybook构建、a11y 23/23、visual 27/27及两种生产构建均通过。锁定环境为Ubuntu 24.04.4、Node 24.18.1、pnpm 11.16.0及镜像digest `sha256:dcc5531e97840b9b5e794f2814476b21571c5124a3fca2267d73041f56e7580e`。
- `03-frontend-full-ubuntu.log`因外部包装未`corepack enable`导致Playwright webServer找不到pnpm；`03b-frontend-full-ubuntu.log`修正shim后又因外部包装误用不存在的`build-storybook`脚本并遗漏`PLAYWRIGHT_CUTOVER_RUN=1`停止。对照`run-ci-profile.ps1`后以runner语义从头完整执行形成`03c`；前两次包装失败不记为候选功能失败，也不冒充正式门禁结果。
- MySQL 8.0迁移组30/30通过、耗时2810.33秒。随后兼容性组257项为215通过、2失败、40错误、耗时1813.18秒。最早失败的两个节点均在`test_catalog_schema.py`：从head降到0022后，0022部分恢复因`product_catalog_versions sealed signature`被拒；首项finally无法恢复head，造成随后相同fixture错误级联。0022的seal签名包含列/约束/索引并存于table comment，0025 upgrade/downgrade会重建同名workbook约束；当前只读证据将首因集中在0025 downgrade后的0022 seal一致性/恢复合同，尚不能判定应修迁移downgrade还是测试恢复合同。
- 相关`test_catalog_schema.py`、0022迁移和0025迁移在候选14–18哈希一致；候选17/18唯一变化是`test_migrations.py`同步head与历史序列。失败发生在随机可抛弃测试库，现有证据不支持候选18新增回归或业务数据丢失结论。
- 按首因停止，MySQL 8.4、generated-contract、两版本性能、UI性能、admin worker E2E、备份恢复、部署验证及其余release-only门禁未执行。容器已清理；候选18 manifest/overlay哈希不变，source/gate均为HEAD `ec0a72e`，按231项复核均为`missing=0 / mismatch=0 / deleted_present=0 / extras=0 / omitted=0`。候选18保持冻结，不生成候选19。
- 下一批需另行授权：仅定向复现两个失败节点，在可抛弃MySQL 8.0库记录0025 downgrade前后`product_catalog_versions`的comment、schema digest和约束表示，确认首因类别后再批准最小修正与定向验证。不得放宽seal、删除/跳过断言或自动再次完整Collect；clean SHA、整合/push、正式门禁及部署继续分别授权。

### 2026-09-15 部署准备：候选18迁移测试合同同步与冻结

- 授权范围内只修改`backend/tests/integration/test_migrations.py`：`_HEAD_REVISION`由`0027`改为`0028`，历史逐级升级序列在`0025`后补入`0026`、`0027`。迁移实现、业务代码、依赖、真实体验环境及其他测试合同均未修改。
- 新鲜定向验证使用项目MySQL开发测试入口、随机可抛弃Oracle MySQL 8.0容器及节点过滤；3个候选17原失败节点和`test_each_historical_revision_upgrades_in_order`共4/4通过、26项未选中，耗时672.74秒，兼容性脚本退出码0。目标Ruff lint和format检查通过。没有运行其他MySQL节点或完整Collect。
- 候选18清单`D:/CLSEN_DeploymentPrep_20260914/evidence/candidate-overlay-manifest-18.json`包含145个修改、81个未跟踪、5个删除，共231项；内容身份为`ec0a72e907cf7787536cf73964f7897485e28c97+overlay-sha256:98c79ee657e685929bdbdc7ceba0af257839f7f33626826c4a9eef796b006878`，清单SHA-256为`01abd0082ebbab155106ecac6ac4457ca2b2e3890dfe563cef534d8063af8208`。
- 候选17/18清单只有目标测试文件内容变化。`candidate-source-18`和`gate-run-18`均为detached HEAD `ec0a72e`，231项复核均为`missing=0 / mismatch=0 / deleted_present=0 / extras=0 / omitted=0`，状态分类与清单一致；候选17及其Collect日志保持不变。
- 下一步只在用户再次明确授权后运行候选18完整本地Collect，并从头按既定顺序、首因停止。候选仍是未提交overlay，canonical clean-SHA前置未解决；不得把定向验证或后续本地预演记为正式`release_validation`。

### 2026-09-15 部署准备：候选17完整本地Collect结果

- 授权范围为冻结候选17的一次完整本地Collect；候选仍为`ec0a72e+overlay`，canonical clean-SHA前置未满足且未绕过。本轮在`gate-run-17`和Ubuntu 24.04锁定Frontend容器按既定顺序执行本地预演，日志位于`D:/CLSEN_DeploymentPrep_20260914/candidate17-collect-logs`，不能记为正式`release_validation`。
- Ubuntu-full为Ruff、399文件format、397源文件mypy通过，pytest 1242通过、2项平台允许跳过、352项排除；Windows smoke为376通过、2项平台允许跳过。
- Frontend固定官方Playwright镜像digest `sha256:dcc5531e97840b9b5e794f2814476b21571c5124a3fca2267d73041f56e7580e`，实测Ubuntu 24.04.4、Node 24.18.1、pnpm 11.16.0；496项供应链策略、ESLint、TypeScript、Token、Vitest 90文件/427项、Playwright 14项、Storybook构建、可访问性23项、视觉27项及两种生产构建均通过。
- MySQL 8.0在随机可抛弃Oracle MySQL容器执行迁移测试，结果27通过、3失败，耗时2802.30秒。三个失败都只在比较实际Alembic head `0028`与`test_migrations.py:24`的旧常量`_HEAD_REVISION = "0027"`时失败；日志记录0028升级/降级链执行，`0028_category_hierarchy.py`明确从0027升级到0028。候选14–17的迁移测试与0028迁移文件哈希一致。现有证据是测试迁移头合同未同步，不构成迁移执行失败、业务缺陷或数据丢失证据。
- `test_each_historical_revision_upgrades_in_order`当前显式序列只列到0025再使用旧HEAD，未逐步覆盖0026/0027。按首因停止，MySQL 8.4及release-only门禁未执行；测试容器已清理，没有自动修正或重跑。
- 停止后manifest SHA-256仍为`a0856a0f53d9ef8874763ae2cc9dcc0edef79b5136418ef0abe229d95b2346fa`，overlay SHA-256仍为`765e94e7f1f4e3e5b9cd007c396ad8a9c40dd252789621eb1113abc2492a43bd`；source/gate双副本231项复核均为`missing=0 / mismatch=0 / deleted_present=0 / extras=0 / omitted=0`。候选17继续冻结，没有候选18。
- 下一批须另行授权：仅在`backend/tests/integration/test_migrations.py`把`_HEAD_REVISION`更新为`0028`，并为原“逐个历史版本升级”序列补入`0026`、`0027`；运行3个原失败节点、该历史序列节点和目标Ruff，通过后冻结候选18。候选18完整Collect、形成干净提交SHA、整合/push、远端门禁和部署继续分别授权，不自动循环。

### 2026-09-15 部署准备：候选17合并决定测试同步与冻结

- 授权范围仅为`MergeDecisionMatrix.test.tsx:41`的`ready=true`断言、原失败Vitest节点、目标ESLint及候选17冻结。实际只把原断言包入本文件已导入并在同一用例后续使用的`waitFor`；期望值、预填依据、操作人/行来源及其余断言均未改变，未修改业务组件、API、样式、依赖、批准基线或体验环境。
- 新鲜定向结果：原失败Vitest节点1/1通过，同文件4项按节点过滤跳过；目标文件ESLint退出码0。未运行其余Vitest、Playwright、Storybook、生产构建、MySQL或完整Collect。
- 候选17清单为`D:/CLSEN_DeploymentPrep_20260914/evidence/candidate-overlay-manifest-17.json`，含145个修改、81个未跟踪、5个删除，共231项；内容身份`ec0a72e907cf7787536cf73964f7897485e28c97+overlay-sha256:765e94e7f1f4e3e5b9cd007c396ad8a9c40dd252789621eb1113abc2492a43bd`，清单SHA-256为`a0856a0f53d9ef8874763ae2cc9dcc0edef79b5136418ef0abe229d95b2346fa`。
- 候选17从冻结候选16保留12项主工作区计划/流程材料，并仅从业务工作树取得授权修改的目标测试文件；候选16/17清单文件项比较只有该文件一项变化。`candidate-source-17`与`gate-run-17`均为detached HEAD `ec0a72e`，231项复核均为`missing=0 / mismatch=0 / deleted_present=0 / extras=0 / omitted=0`，状态分类仍为145个修改、81个未跟踪、5个删除。候选16及其Collect日志保持不变，canonical clean-SHA前置仍未满足。
- 下一步只在再次明确授权后启动候选17完整本地Collect，从头按既定顺序并首因停止；不自动循环，不把本地预演计为正式`release_validation`。形成干净提交SHA、整合/push、远端正式门禁及部署继续分别授权。

### 2026-09-15 部署准备：候选16完整本地Collect结果

- 授权范围为冻结候选16的一次完整本地Collect；候选仍为`ec0a72e+overlay`，canonical clean-SHA前置未满足且未绕过。本轮在`gate-run-16`和Ubuntu 24.04锁定Frontend容器按既定顺序执行本地预演，日志位于`D:/CLSEN_DeploymentPrep_20260914/candidate16-collect-logs`，不能记为正式`release_validation`。
- Ubuntu-full范围通过：Ruff、399文件format、397源文件mypy通过，pytest 1242通过、2项平台允许跳过、352项排除。Windows smoke为376项通过、2项平台允许跳过。
- Frontend固定官方Playwright镜像digest `sha256:dcc5531e97840b9b5e794f2814476b21571c5124a3fca2267d73041f56e7580e`，实测Ubuntu 24.04.4、Node 24.18.1、pnpm 11.16.0；冻结依赖安装通过496项供应链策略，ESLint、TypeScript和Token通过。
- Vitest为89/90文件、426/427项通过。首因节点`MergeDecisionMatrix > prefills each selected conflict decision with operator and row provenance`在`MergeDecisionMatrix.test.tsx:41`期望最后一次`onStateChange`的`ready`为`true`，实际为`false`。DOM文本出现只证明预填内容已渲染；组件的`ready`由后续render计算并经effect通知，测试没有等待该通知完成。同一测试后续已经用`waitFor`等待相同回调。候选15/16的测试、组件和`auditReason.ts`哈希逐项一致，候选15完整Vitest曾427/427通过；停止后相同节点定向重跑1/1通过、4项过滤跳过。当前证据指向既有测试异步同步缺口，不构成业务实现缺陷证据；定向通过不覆盖本次完整轮失败。
- 按Vitest首因停止。Playwright、Storybook静态构建/可访问性/视觉、两种生产构建、MySQL 8.0/8.4及后续release-only门禁未执行。首次Frontend挂载包装预检在任何候选门禁前退出，修正外部挂载参数并完成只读预检后才开始唯一一次Frontend门禁；该包装记录不计为候选测试失败。
- 停止后候选16 manifest SHA-256仍为`e4220e0ddaaa6c84577eea819fffd6f09dc44a2f0b3e6e53c3e3c54af35a631c`，overlay SHA-256仍为`b1022898577c97bff8614cf121ddee4f40d240deac5f358ba7b2d41e8b3affe6`。`candidate-source-16`与`gate-run-16`HEAD均为`ec0a72e`，按231项复核均为`missing=0 / mismatch=0 / deleted_present=0 / extras=0 / omitted=0`，分类仍为145个修改、81个未跟踪和5个删除。候选16继续冻结，没有候选17。
- 下一批须另行授权：仅把`MergeDecisionMatrix.test.tsx:41`现有`ready=true`断言包入`waitFor`，保持期望值及其余断言不变；运行原失败Vitest节点和目标ESLint，通过后冻结候选17。候选17完整Collect、形成干净提交SHA、整合/push、远端门禁和部署继续分别授权，不自动循环。

### 2026-09-15 部署准备：候选16批量审核E2E同步与冻结

- 授权范围仅为`batch-review.spec.ts:156`的计数断言、原失败Playwright节点、目标ESLint及候选16冻结。实际只用`expect.poll`等待`acceptedAdvanceRequests`达到原期望值6；并发上限3、零发布写入和其他断言均未改变，未修改任何业务实现、依赖、批准基线或体验环境。
- 新鲜定向结果：原失败Playwright节点1/1通过；目标文件ESLint退出码0。未运行其余浏览器节点、Vitest、Storybook、生产构建、MySQL或完整Collect。
- 候选16清单为`D:/CLSEN_DeploymentPrep_20260914/evidence/candidate-overlay-manifest-16.json`，含145个修改、81个未跟踪、5个删除，共231项；内容身份`ec0a72e907cf7787536cf73964f7897485e28c97+overlay-sha256:b1022898577c97bff8614cf121ddee4f40d240deac5f358ba7b2d41e8b3affe6`，清单SHA-256为`e4220e0ddaaa6c84577eea819fffd6f09dc44a2f0b3e6e53c3e3c54af35a631c`。
- `candidate-source-16`与`gate-run-16`均为独立detached worktree、HEAD `ec0a72e`；231项逐项核对均为`missing=0 / mismatch=0 / deleted_present=0 / extras=0 / omitted=0`，实际状态计数与清单一致且无`data/`状态项。候选15及其日志保持不变；canonical clean-SHA前置仍未满足。
- 下一步只在再次明确授权后启动候选16完整本地Collect，从头按既定顺序并首因停止；不自动循环，不把本地预演计为正式`release_validation`。形成干净提交SHA、整合/push、远端正式门禁及部署继续分别授权。

### 2026-09-15 部署准备：候选15完整本地Collect结果

- 授权范围为冻结候选15的一次完整本地Collect；候选仍为`ec0a72e+overlay`，canonical clean-SHA前置未满足且未绕过。本轮在`gate-run-15`及Ubuntu 24.04锁定Frontend容器按既定顺序执行本地预演，日志位于`D:/CLSEN_DeploymentPrep_20260914/candidate15-collect-logs`，不能记为正式`release_validation`。
- Ubuntu-full范围：Ruff、399文件format、397源文件mypy通过，pytest 1242通过、2项平台允许跳过、352项排除。Windows smoke：376项通过、2项平台允许跳过。
- Frontend固定官方Playwright镜像digest `sha256:dcc5531e97840b9b5e794f2814476b21571c5124a3fca2267d73041f56e7580e`，实测Ubuntu 24.04.4、Node 24.18.1、pnpm 11.16.0、Chromium 151.0.7922.34；冻结依赖安装通过496项供应链策略。ESLint、TypeScript、Token和Vitest 90文件/427项通过。
- Playwright为13通过、1失败。`batch-review.spec.ts:156`期望夹具收到6次被接受的`advance`，实际即时读取为5。trace确认初次5个选中项均进入夹具；暂停/刷新时第4、5项浏览器响应被取消，但服务端夹具完成处理。第4项重试请求成功后，测试只等待失败文案消失，又等待一个此前已有3项待发布时就已可见的链接，随后在重试项再次发出`advance`前读取计数。候选12–15的测试、执行器、页面、API和进度表文件哈希一致；候选12曾通过，停止后当前Node 24.18.1/Chromium环境单节点定向重跑1/1通过。证据指向测试异步同步缺口，不构成业务实现缺陷证据；单节点通过不覆盖完整轮失败。
- 按首因停止，Storybook构建/可访问性/27项视觉、两种生产构建、MySQL 8.0/8.4及后续release-only门禁未执行。候选15继续冻结，不自动循环Collect。
- 下一批须另行授权：仅将第156行计数断言改为异步等待`acceptedAdvanceRequests`达到6，保持期望值、并发上限、零发布写入及其余体验断言不变；运行原失败Playwright节点和目标ESLint，通过后冻结候选16。不得用固定等待、删除断言或修改业务执行器掩盖问题；候选16完整Collect仍须再次授权。

### 2026-09-15 部署准备：候选15目录入口测试夹具同步与冻结

- 授权范围仅为`App.test.tsx`的`/api/catalog/imports`测试夹具、原失败节点、必要相邻入口断言、目标ESLint及候选15冻结。实际只新增返回`{ items: [], has_next: false }`的fetch分支，未修改断言、业务组件、API、样式、依赖、批准基线或体验环境。
- 新鲜定向结果：原失败的目录数据管理员入口与4个viewer管理深链参数化用例共5/5通过，同文件34项因节点过滤跳过；目标文件ESLint退出码0。未运行完整Vitest、Playwright、Storybook、生产构建、MySQL或完整Collect。
- 候选15清单为`D:/CLSEN_DeploymentPrep_20260914/evidence/candidate-overlay-manifest-15.json`，含144个修改、81个未跟踪、5个删除，共230项；内容身份`ec0a72e907cf7787536cf73964f7897485e28c97+overlay-sha256:30b61ee33d35b8b0ee9386ccfb5490a5442c27c5302231eec7408da0655bb94d`，清单SHA-256为`e626dad8f1bb653be603b5fd5ad2381aa45d7299584f614c3a9502f1bfcd969a`。
- `candidate-source-15`与`gate-run-15`均为独立detached worktree、HEAD `ec0a72e`；230项逐项核对均为`missing=0 / mismatch=0 / deleted_present=0 / extras=0 / omitted=0`，实际状态计数与清单一致且无`data/`。候选14及其日志保持不变；canonical clean-SHA前置仍未满足。
- 下一步只在再次明确授权后启动候选15完整本地Collect，从头按既定顺序并首因停止；不自动循环，不把本地预演计为正式`release_validation`。形成干净提交SHA、整合/push、远端正式门禁及部署继续分别授权。

### 2026-09-15 部署准备：候选14完整本地Collect结果

- 授权范围为冻结候选14的一次完整本地Collect；candidate仍为`ec0a72e+overlay`，canonical clean-SHA保护未绕过。本轮在`gate-run-14`及Ubuntu 24.04锁定容器从头执行同顺序本地预演，不能记为正式`release_validation`。日志位于`D:/CLSEN_DeploymentPrep_20260914/candidate14-collect-logs`。
- Ubuntu-full：Ruff、399文件format、397源文件mypy通过，pytest 1242通过、2项平台允许跳过、352项排除。Windows smoke：376通过、2项平台允许跳过。
- Frontend使用官方Playwright镜像digest `sha256:dcc5531e97840b9b5e794f2814476b21571c5124a3fca2267d73041f56e7580e`，实测Ubuntu 24.04.4、Node 24.18.1、pnpm 11.16.0、Chromium 151.0.7922.34；候选以只读源挂载并复制到一次性容器工作区，冻结依赖安装通过496项供应链策略。ESLint、TypeScript和Token通过。
- Vitest为89/90文件、426/427项通过，并有1项未处理错误。失败节点`App > catalog data manager can open the real maintenance controls`在第185行等待“目录工作簿”时，`CatalogImportHistory.tsx:22`读取未定义的`result.items.length`。`App.test.tsx`共享fetch夹具没有处理`/api/catalog/imports?page=1`，请求落入默认`{}`；组件独立测试和后端GET路由均明确返回`items/has_next`。同一Ubuntu环境定向重跑该节点稳定复现为1项失败、38项过滤跳过和1项未处理错误。候选13/14相关测试与组件文件哈希相同，而候选13完整Vitest中`App.test.tsx`39项曾通过，说明先前通过依赖异步时序；现有证据是既有测试夹具合同缺口，不构成候选14业务缺陷证据。
- 前端门禁前两次容器包装预检分别因只读根下缺少嵌套挂载点、镜像无`google-chrome`别名退出；两次均早于依赖安装和任何Frontend命令，日志单独保留。只读定位实际Chromium路径并采用只读候选源加一次性可写工作区后，才开始本轮唯一一次Frontend门禁；未绕过或降低任何候选检查。
- 按Vitest首因停止。Playwright、Storybook静态构建/可访问性/27项视觉、两种生产构建、MySQL 8.0/8.4及release-only门禁均未执行。候选14双副本仍为HEAD `ec0a72e`，230项清单复核均为`missing=0 / mismatch=0 / deleted_present=0 / extras=0 / omitted=0`且无`data/`；清单SHA-256仍为`4c3d5d32364abde9fc6c4496c4606dfcf06f6c0be634c1a43af8fd0d533c8f1b`。
- 下一步仅在另行授权后修正`App.test.tsx`共享fetch夹具，为`/api/catalog/imports`返回既有空列表合同`{ items: [], has_next: false }`，运行原失败节点、目标ESLint及必要相邻入口断言，再冻结候选15。候选15完整Collect、clean-SHA、整合/push、远端门禁和部署继续分别授权。

### 2026-09-15 部署准备：候选14测试隔离同步与冻结

- 授权范围仅为`ImportReviewFlow.test.tsx`的hook顺序、两个相邻Vitest节点、目标ESLint及候选14冻结。实际只将已有`beforeEach/afterEach`移动到首个用例之前，未改变hook内容、测试断言、mock、业务组件、API、样式、依赖、批准基线或体验环境。
- 新鲜定向结果：`inspects the explicit source instead of restoring an old draft`与`prefills the draft reason from the authenticated operator and source batch`为2/2通过，同文件17项因节点过滤跳过；目标文件ESLint退出码0。未运行完整Vitest、Playwright、Storybook、生产构建、MySQL或完整Collect。
- 候选14清单为`D:/CLSEN_DeploymentPrep_20260914/evidence/candidate-overlay-manifest-14.json`，含144个修改、81个未跟踪、5个删除，共230项；内容身份`ec0a72e907cf7787536cf73964f7897485e28c97+overlay-sha256:ddf2f5cb6340a68a706d1bab62d36eb32aed5a733c6968f3c7f2bc81033031af`，清单SHA-256为`4c3d5d32364abde9fc6c4496c4606dfcf06f6c0be634c1a43af8fd0d533c8f1b`。
- `candidate-source-14`与`gate-run-14`均为独立detached worktree、HEAD `ec0a72e`；230项逐项核对均为`missing=0 / mismatch=0 / deleted_present=0 / extras=0 / omitted=0`，实际状态计数与清单一致且无`data/`。候选13及其日志保持不变；canonical clean-SHA前置仍未满足。
- 下一步只在再次明确授权后启动候选14完整本地Collect，从头按既定顺序并首因停止；不自动循环，不把本地预演计为正式`release_validation`。形成干净提交SHA、整合/push、远端正式门禁及部署继续分别授权。

### 2026-09-15 部署准备：候选13完整本地Collect结果

- 授权范围为冻结候选13的一次完整本地Collect；candidate仍为`ec0a72e+overlay`，canonical clean-SHA保护未绕过。本轮在`gate-run-13`及Ubuntu 24.04锁定容器从头执行同顺序本地预演，不能记为正式`release_validation`。日志位于`D:/CLSEN_DeploymentPrep_20260914/candidate13-collect-logs`。
- Ubuntu-full：Ruff、399文件format、397源文件mypy通过，pytest 1242通过、2项允许跳过、352项排除。Windows smoke：376通过、2项允许跳过。
- Frontend容器固定官方Playwright镜像digest `sha256:dcc5531e97840b9b5e794f2814476b21571c5124a3fca2267d73041f56e7580e`，实测Ubuntu 24.04.4、Node 24.18.1、pnpm 11.16.0、Chromium 151.0.7922.34；候选只读挂载，依赖仅装于一次性容器，496项供应链策略通过。ESLint、TypeScript和Token通过。
- Vitest为89/90文件、426/427项通过。失败节点`ImportReviewFlow > prefills the draft reason from the authenticated operator and source batch`在第194行立即查询上传控件时，DOM已经处于上一用例批次#44的确认识别状态。`ImportReviewFlow.test.tsx`把新增的显式source用例放在本文件`beforeEach/afterEach`之前；该用例可异步保存恢复状态，却不受后置清理hook覆盖。下一用例因此可能恢复批次#44而不显示“CSV 文件”。候选12/13该文件SHA-256同为`ee8e82dfdeee297b4c1334cfa4dfc6b6c2677ef41de540fe63069eeb8b416f16`，候选12相同节点已有通过记录；现有证据是测试隔离/时序缺口，不构成候选13业务缺陷证据。
- 初次容器包装在任何Frontend门禁前因环境展示命令和Corepack PATH假设错误退出；诊断确认镜像本身及锁定工具存在后，仅修正外部包装为读取`/etc/os-release`并调用`corepack pnpm`，随后开始唯一一次Frontend门禁。预检日志`03a-frontend-wrapper-preflight-failed.log`保留以区分执行器前置与候选首因。
- 按首因停止且未修改、未重跑。Playwright、Storybook静态构建/可访问性/27项视觉、两种生产构建、MySQL 8.0/8.4及release-only门禁均未执行。候选13双副本仍为HEAD `ec0a72e`，230项清单均为`missing=0 / mismatch=0 / deleted_present=0 / extras=0 / omitted=0`且无`data/`；清单SHA-256仍为`7950ec48bb521c1f5cc5c0a52402b7a6a6e8bcb41289ccc1e9a0f25168294d9a`。
- 下一步仅在另行授权后移动该测试文件的两个hook到首个用例之前，运行首个与原失败两个相邻节点及目标ESLint，再冻结候选14。候选14完整Collect、clean-SHA、整合/push、远端门禁和部署继续分别授权。

### 2026-09-15 部署准备：候选13测试同步与冻结

- 授权范围仅为`PublishedDetailLedgerPage.test.tsx`的异步URL断言、原失败Vitest节点、目标ESLint及候选13冻结；没有修改业务组件、API、样式、依赖、批准基线或体验环境。
- 将第500行已有`report_date`清除断言包入`waitFor`。原失败节点新鲜运行1/1通过（20项因节点过滤跳过），目标文件ESLint退出码0；未运行完整Vitest、Playwright、Storybook、生产构建、MySQL或其他门禁。
- 候选13清单为`D:/CLSEN_DeploymentPrep_20260914/evidence/candidate-overlay-manifest-13.json`，含144个修改、81个未跟踪、5个删除，共230项；内容身份`ec0a72e907cf7787536cf73964f7897485e28c97+overlay-sha256:7aca3835c24cb1cde164b5247e3b20d028eb86ac02629e58f64a963dd6d88dcd`，清单SHA-256为`7950ec48bb521c1f5cc5c0a52402b7a6a6e8bcb41289ccc1e9a0f25168294d9a`。
- `candidate-source-13`与`gate-run-13`均为独立detached worktree、HEAD `ec0a72e`，230项逐项核对均为`missing=0 / mismatch=0 / deleted_present=0 / extras=0 / omitted=0`且无`data/`目录。候选12及历史证据保持不变；canonical clean-SHA前置仍未满足。
- 下一步只在再次明确授权后启动候选13完整本地Collect，从头按既定顺序并首因停止；不自动循环，不把本地预演计为正式`release_validation`。形成干净提交SHA、整合/push、远端正式门禁及部署继续分别授权。

### 2026-09-15 部署准备：候选12第二次完整本地Collect结果

- 用户授权冻结候选12重新执行一次完整本地Collect，并明确Frontend视觉门禁使用Ubuntu 24.04锁定环境。候选仍以`ec0a72e+overlay`表示，canonical clean-SHA保护未绕过；本轮为同顺序本地预演，日志根`D:/CLSEN_DeploymentPrep_20260914/candidate12-collect-02-logs`，不能记为正式`release_validation`。
- Ubuntu-full通过：Ruff lint、399文件format、397源文件mypy及pytest执行范围通过（1242通过、2项允许跳过、352项排除）。Windows smoke通过：376项通过、2项平台允许跳过。
- Frontend运行于官方Playwright noble镜像digest `sha256:dcc5531e97840b9b5e794f2814476b21571c5124a3fca2267d73041f56e7580e`，实测Ubuntu 24.04.4、Node 24.18.1、pnpm 11.16.0、Playwright 1.62.1/Chromium 151.0.7922.34；候选只读挂载，冻结依赖安装通过496项供应链策略。ESLint、TypeScript与Token通过。
- Vitest为89/90文件、426/427项通过，首个失败为`PublishedDetailLedgerPage.test.tsx:500`：展开明细发生`publication_scope_changed`后，测试在第二次摘要API调用出现后立即断言LocationProbe已移除`report_date`。代码只读追踪表明冲突处理同批调度`setSearchParams(..., { replace: true })`与`setSummaryReload`；摘要键不含展开日期，故API第二次调用不能作为路由commit完成的同步点。同文件相邻用例对路由更新使用`waitFor`，上一轮相同候选的完整Vitest为427/427通过。当前证据指向测试同步缺口，不构成业务实现缺陷证据；本轮未修正或重跑。
- 按首因停止，本轮未执行完整Playwright、Storybook构建/可访问性/27项视觉、两种生产构建、MySQL 8.0/8.4及release-only门禁。此前的Storybook及Ubuntu四节点证据保留为历史开发证据，但不冒充本轮完整门禁通过。
- 停止后manifest SHA-256为`1d8b8d3179c54dd93fa720d65903e3cee38fe1b6ffe45a8c111e45f6b05c1d12`；source/gate双副本HEAD均为`ec0a72e`，229项显式清单均为`missing=0 / mismatch=0 / deleted_present=0`，tracked清单无意外项或遗漏。候选内容身份仍为`ec0a72e+overlay-sha256:8cd7b744daa1b668ba2821e50ca387e627a7b5b0875fc52984566cc6751cfa39`，未冻结候选13。
- 下一批最小范围：另行授权后，只将第500行地址断言改为等待`report_date`消失，运行该Vitest节点与目标ESLint；通过后冻结候选13。候选13完整Collect、干净候选SHA、整合/push、远端正式门禁与部署仍分别授权。

### 2026-09-15 部署准备：候选12完整本地Collect结果

- 授权边界为冻结候选12的一次完整本地Collect；canonical clean-SHA保护未绕过。因候选仍以`ec0a72e+overlay`表示，本轮只在`gate-run-12`执行同顺序本地预演，不能记为正式`release_validation`。日志为`D:/CLSEN_DeploymentPrep_20260914/candidate12-collect-logs/01-ubuntu-full.log`、`02-windows-smoke.log`和`03-frontend-full.log`。
- Ubuntu-full通过：Ruff lint、399文件format、397源文件mypy无问题；pytest 1242通过、2项允许跳过、352项排除。Windows smoke通过：376项通过、2项平台允许跳过。
- Frontend在复用既有依赖时仅对进程设置已核对的`pnpm_config_virtual_store_dir`；锁文件策略通过且`Already up to date`，未安装、清理或修改依赖。ESLint、TypeScript、Token、Vitest 90文件/427项和完整Playwright 14项通过；Storybook静态构建成功，可访问性23/23通过。
- Storybook视觉门禁27项中23项通过、4项失败，均限390×844移动端：Form controls/Field states差异0.04，Selection and navigation/Selection states、Feedback and data/Toast kinds及Loading empty and error各0.02；合同上限为0.01。预期/实测尺寸相同，差异集中在文字和控件像素；桌面、平板及其余5个移动故事通过。当前证据不足以在不重跑、不改变环境的前提下区分平台渲染差异与需批准的基线/样式变化，因此仅记`storybook_visual_failed`，不认定业务功能缺陷、不更新批准基线、不降低阈值。
- 获得定向诊断授权后，仅在Windows重跑4个失败节点；差异数与比例完全复现，两轮实际图SHA-256逐张相同。再从视觉基线首次提交`64176d4249f0d3232f01f08d542bf36b4855ca02`提取原始Frontend代码，以相同Windows Node 24.18.1、Playwright 1.62.1/Chromium 151.0.7922.34和Noto Sans SC 5.3.0只运行4项；结果、像素差异及实际图SHA-256仍与候选12完全相同。这一单变量对照排除候选12代码变化为首因。
- 正式Frontend workflow使用`ubuntu-24.04`；基线批准记录只写Playwright与字体版本，未写OS。本机WSL没有Node/Chromium，已有Frontend容器镜像是Nginx静态产物，没有可复用的Playwright测试运行时。本轮未下载、安装或构造新Linux依赖环境。因此当前首因定为跨平台视觉基线执行合同/证据缺口，Ubuntu 24.04下是否通过仍是必要缺口，不把Windows像素差异判为业务缺陷或批准基线应更新。
- 用户授权Ubuntu四节点定向复核后，获取官方`mcr.microsoft.com/playwright:v1.62.1-noble`，digest为`sha256:dcc5531e97840b9b5e794f2814476b21571c5124a3fca2267d73041f56e7580e`。容器实测Ubuntu 24.04.4、Node 24.18.1、pnpm 11.16.0、Chromium 151.0.7922.34；候选12只读挂载，`pnpm install --frozen-lockfile`通过496项供应链策略并安装锁定400包，未改变候选。原4个390×844节点`4 passed (8.9s)`，日志为`D:/CLSEN_DeploymentPrep_20260914/candidate12-visual-diagnostic/ubuntu-24.04/ubuntu-four-mobile-03.log`。
- Ubuntu结果关闭候选12视觉回归疑点：Windows失败仅作为平台像素差异保留，不修改业务样式、批准截图、阈值或候选身份。该4节点结果不是完整27项视觉门禁，也不补跑Collect后续节点或构成正式`release_validation`。
- 按首因停止，未执行两种生产构建、MySQL 8.0/8.4、OpenAPI/产品基线或后续Stage0门禁。依赖`.modules.yaml`与虚拟存储`lock.yaml`哈希仍为`5c12be46...`和`56e89b49...`。停止后候选source/gate均为HEAD `ec0a72e`，229项清单复核均为`missing=0 / mismatch=0 / deleted_present=0 / extras=0 / omitted=0`；候选内容身份仍为`ec0a72e+overlay-sha256:8cd7b744daa1b668ba2821e50ca387e627a7b5b0875fc52984566cc6751cfa39`。
- 下一批最小范围：候选12内容未变，不冻结候选13。若继续部署准备，须另行授权候选12下一次完整本地Collect，并明确Frontend视觉门禁使用上述Ubuntu锁定环境；不得自动改图、改样式、降阈值或从中断点继续冒充一轮完整Collect。

### 2026-09-14 部署准备：候选12 E2E合同同步与冻结

- 授权边界仅包含5个E2E合同文件、目标ESLint、原失败9个Chromium节点及候选12冻结；未修改业务代码、依赖、体验环境或数据。
- `catalog-sensitive-reveal.spec.ts`同步“查看完整标识”；`catalog-workflow.spec.ts`从目录首页进入批量维护，使用当前导出任务字段/权限并验证“下载兼容 XLSX”与“开始在线审核”；`date-workbench-structural-grid.spec.ts`使用具名表格与操作区，焦点边框与`--color-focus`语义Token比较；`import-review-publish.spec.ts`补空的批量审核历史列表；`product-ledger.spec.ts`按当前款号按钮→商品信息抽屉→详情入口路径验证，关闭模态后再核对背景对账表。
- 最终定向证据：5文件ESLint退出码0；原失败Chromium节点`9 passed (9.2s)`。过程中对新失败仅重跑受影响节点，最后以全部原9节点一次新鲜通过作为完成证据。日志根：`D:/CLSEN_DeploymentPrep_20260914/candidate12-targeted`。
- 候选12基线仍为`ec0a72e907cf7787536cf73964f7897485e28c97`，清单含143个修改、81个未跟踪和5个删除项，共229项，内容身份以`D:/CLSEN_DeploymentPrep_20260914/evidence/candidate-overlay-manifest-12.json`为准；source/gate双副本均为`missing=0 / mismatch=0 / deleted_present=0 / extras=0 / omitted=0`且不含`data/`。canonical runner的clean-SHA保护仍会拒绝这种overlay表示。
- 未执行候选12完整Collect、Storybook、生产构建、MySQL、OpenAPI/产品基线或后续门禁。下一步仅为再授权后对冻结候选12执行一次完整本地Collect；不自动循环，不作正式`release_validation`声明。
- 本批实际Skill：`systematic-debugging`用于根据快照、trace和当前组件合同追踪根因；`test-driven-development`用于保留原失败节点作为红色复现并最小同步测试；`verification-before-completion`用于新鲜运行目标ESLint、9节点与候选双副本核对。

### 2026-09-14 部署准备：候选11浏览器首因修正与冻结

- `product-detail.spec.ts:7` 原 `getByText("无报表")` 同时匹配图表每日读数摘要和趋势矩阵单元格。保持 `toBeVisible()` 不变，将目标明确为具名“趋势每日点矩阵”区域内精确名称“无报表”的单元格；未使用 `.first()`、未删断言、未跳过测试或修改业务代码。
- 定向检查：现有组件测试与业务组件代码证明危险别名位于默认折叠的原生`details`中；E2E缺少展开步骤，不是390px业务显示缺陷。只在安全占位断言前点击“1 个来源别名”，未修改业务代码或样式。
- 正确源工作树的目标ESLint `--max-warnings 0`通过；正确产品分析模式下唯一Chromium用例1/1通过（3.0秒）。主工作区误跑、错误文件过滤和缺少产品分析模式的运行均不计为候选证据。证据目录为 `D:/CLSEN_DeploymentPrep_20260914/candidate11-targeted`。
- 候选11基线仍为`ec0a72e907cf7787536cf73964f7897485e28c97`，清单`D:/CLSEN_DeploymentPrep_20260914/evidence/candidate-overlay-manifest-11.json`共224项；source/gate双副本按清单逐项核对并排除`data/`。候选10源/执行副本、清单与Collect日志均保留不变。
- canonical runner的workspace-boundary在验证模式要求HEAD等于指定SHA且`git status --porcelain`为空，在正式执行模式也检查提交边界；候选11仍为基线加overlay，因此不改变表示方式就再次运行会被同一clean-SHA保护阻断。正式准备需要另行授权将完整候选（含应交付未跟踪材料和删除项）形成单一提交SHA，并从该SHA干净检出；远端正式门禁还要求另行授权整合/push到master，使workflow/input/current master为同一SHA，并先取得唯一成功的master push compatibility及`master-required`。本地同顺序预演不具备不可变SHA和远端来源绑定，只能作为开发期线索，不得记为正式验收通过。
- 未启动完整Collect、Storybook、其余浏览器、生产构建、OpenAPI/产品基线、MySQL或其他门禁；下一次完整验证仍需再次授权，完成本批后停止。

### 2026-09-14 部署准备：候选11完整本地Collect结果

- canonical runner从`candidate-source-11`启动即因224项overlay不满足clean-SHA合同而退出，未执行runner门禁且未绕过保护；指定证据根`D:/CLSEN_DeploymentPrep_20260914/candidate11-collect-20260914`未产生门禁证据，也没有生成独立canonical日志文件。Windows、Ubuntu和Frontend本地预演日志位于`D:/CLSEN_DeploymentPrep_20260914/candidate11-collect-logs`。
- 独立`gate-run-11`按既定本地预演顺序运行，实际先Windows、后Ubuntu：Windows smoke收集378项，376通过、2项Windows平台允许跳过；Ubuntu-full的Ruff lint、399文件format、397源文件mypy通过，pytest收集1596项、排除352项、执行1244项，其中1242通过、2项允许跳过。
- 为执行副本复用已有稳定前端依赖建立`node_modules` junction，未安装或修改依赖；其中`.modules.yaml`的`virtualStoreDir`仍指向`gate-run-08`。Frontend runner从`gate-run-11`调用pnpm包装器时，在实际ESLint前触发`pnpm install`状态检查，pnpm发现模块目录需要清理但当前无TTY，以`ERR_PNPM_ABORTED_REMOVE_MODULES_DIR_NO_TTY`退出。该日志只证明依赖执行前置未满足，不证明Frontend lint或业务实现失败。
- 按首因停止：Frontend实际检查、浏览器14项、Storybook三项、两种生产构建、MySQL 8.0/8.4、OpenAPI、产品目录基线及后续Stage0门禁均未执行。未设置`CI=true`、未关闭确认机制、未清理/重装依赖，也未自动重跑完整Collect。
- 停止后复核两个冻结副本：HEAD均为`ec0a72e907cf7787536cf73964f7897485e28c97`，224项清单均为`missing=0 / mismatch=0 / deleted_present=0 / extras=0 / omitted=0`。候选11身份不变，没有候选12。下一步须另行授权后仅处理pnpm执行环境前置；再次完整Collect仍单独授权，正式`release_validation`保持`not_started`。

### 2026-09-14 部署准备：候选11 pnpm执行前置定向处理

- 核对实际执行上下文：主工作区为`codex/development-throughput / 7de0ee6`，候选业务源仍为`stage4-1-app-shell / ec0a72e + overlay`。runner的Frontend分支只依次调用pnpm脚本；实际pnpm为Codex bundled 11.19.0。
- `gate-run-11/frontend/node_modules`复用`gate-run-08`，`.modules.yaml`内绝对`virtualStoreDir`仍指向`gate-run-08/frontend/node_modules/.pnpm`。未对齐配置时，从`gate-run-11`调用pnpm会在脚本运行前把目录判为需重建并因无TTY停止；这解释了上一轮为何实际ESLint没有启动。
- 单变量验证只在进程环境设置`pnpm_config_virtual_store_dir`指向该现有虚拟存储，不设置`CI=true`、不关闭清理确认、不清理/安装依赖、不改runner。pnpm报告锁文件通过策略、解析跳过、依赖已是最新，随后完整`eslint . --max-warnings 0`退出码0。
- 验证前后`package.json`、`pnpm-lock.yaml`、`.modules.yaml`及虚拟存储`lock.yaml`哈希变化数为0；source/gate双副本224项清单再次核对均为`missing=0 / mismatch=0 / deleted_present=0 / extras=0 / omitted=0`。日志：`D:/CLSEN_DeploymentPrep_20260914/candidate11-pnpm-preflight/pnpm-lint-aligned-store.log`。
- 本批只解除本地预演的pnpm执行前置并验证第一项Frontend lint，不代表其余Frontend或完整门禁通过；canonical clean-SHA合同仍未满足。候选内容未变，不冻结候选12；再次完整Collect须另行授权。

### 2026-09-14 部署准备：候选11第二次完整本地Collect结果

- 用户授权后在`gate-run-11`按正式profile顺序重新运行；复用已确认的canonical clean-SHA阻塞结论，不绕过保护。日志位于`D:/CLSEN_DeploymentPrep_20260914/candidate11-collect-02-logs`。
- Ubuntu-full：Ruff、399文件format、397源文件mypy通过；pytest 1242通过、2项允许跳过。Windows smoke：376通过、2项允许跳过。Frontend：ESLint、TypeScript、Token通过，Vitest 90文件/427项通过。
- Playwright 14项中5项通过、9项失败：目录敏感标识1项、目录工作流1项、工作台3项、导入发布1项、产品总表3项。浏览器失败后整个Collect停止，Storybook、两种生产构建、MySQL 8.0/8.4、OpenAPI、产品基线及后续Stage0门禁均未执行。
- 只读诊断确认：三个测试仍使用旧入口/按钮名称；工作台三个节点使用CSS Modules不会保留的字面类名；产品总表三个视口夹具遗漏`/api/catalog/categories`响应，fallback `{}`导致`categories.find`页面错误。五个文件在候选10/11哈希逐项一致，现有证据指向E2E材料合同未同步，不证明业务实现失败。
- 停止后source/gate双副本224项清单均为`missing=0 / mismatch=0 / deleted_present=0 / extras=0 / omitted=0`。候选11不变、未冻结候选12。下一批仅建议同步5个E2E合同、运行目标ESLint及9个受影响节点，再冻结候选12；所有修改与完整Collect均需新授权。

### 2026-09-14 部署准备：候选10完整本地Collect结果

- 用户授权候选10执行一次完整本地Collect。冻结候选基于 `ec0a72e907cf7787536cf73964f7897485e28c97` 加223项 overlay；canonical runner 启动即被 clean-SHA 保护拒绝，退出码1，证据根 `D:/CLSEN_DeploymentPrep_20260914/candidate10-collect-20260914` 未执行 runner 门禁，未绕过保护。
- 在独立 `gate-run-10` 执行副本按既定顺序进行同顺序本地预演：Windows smoke 378项中376通过、2项平台允许跳过；Ubuntu-full 的 Ruff、399文件 format、397源文件 mypy、pytest 1242项通过/2项允许跳过；Frontend ESLint、TypeScript、设计 Token、Vitest 90个文件/427项通过。
- 浏览器首个失败为 `tests/e2e/product-detail.spec.ts:7`：`getByText("无报表")` strict-mode 同时匹配摘要文本与表格单元格；同一用例定向重跑复现。该证据仅支持既有测试选择器合同不够精确，不支持产品详情业务实现缺陷判断。
- 按首因停止，未执行浏览器其余用例、Storybook静态构建/无障碍/视觉、生产构建、OpenAPI/产品基线、MySQL 8.0/8.4及后续材料门禁。候选10日志保留于 `D:/CLSEN_DeploymentPrep_20260914/candidate10-collect-logs`；未修改业务代码、`data/`、数据库或体验环境。
- 候选10清单为 `D:/CLSEN_DeploymentPrep_20260914/evidence/candidate-overlay-manifest-10.json`；`candidate-source-10` 与 `gate-run-10` 按223项逐项复核无缺失、不匹配或删除项误存在。下一步如继续，仅修正该测试选择器并运行受影响浏览器节点后重新冻结候选；完整Collect仍需再次授权，不启动Stage5.1/5.2，不重开#9/#35体验。

### 2026-09-14 部署准备：候选01门禁失败与最小材料修正

- 授权边界：冻结可识别候选、纳入应交付未跟踪材料、只准备#9/#35体验并执行约定门禁；不含提交、push、merge、迁移、实际部署或生产变更。正式`release-gates`只接受远端master干净SHA及成功`master-required`，当前本地内容候选不能冒充正式来源。
- 候选01：`ec0a72e907cf7787536cf73964f7897485e28c97+overlay-sha256:fd764907d9ee0f2488c2aae6154a12ffce90e5069c596af950dcf5c071769c8c`；显式覆盖129个已修改文件、81个未跟踪文件、5个删除项，排除`data/`。清单位于`D:/CLSEN_DeploymentPrep_20260914/evidence/candidate-overlay-manifest.json`；分类编辑器、LedgerMetricHelp故事、ProductTrendChart故事与参考文件均已纳入。
- 首项Windows smoke预演结果：378项中368通过、8失败、2个Windows平台允许跳过，随后停止整套门禁。失败均为迁移0028、维护路由、两个既有读路由及未匹配查询参数已进入实现，但相关迁移计数/列表、路由基线、权限契约、schema新旧样例和生成API摘要未同步；现有权限依赖检查在失败前已逐路由通过，未发现#9/#35业务缺陷。
- 最小修正仅涉及测试/生成材料：补0028线性迁移记录及114表计数；把`0029`作为“比当前0028更新”的测试样例；补`/catalog/maintenance`路由基线、批量审核列表与版本行读取权限契约、产品账`category_id`参数；重新生成API客户端。未修改业务逻辑，Stage5.1/5.2范围不变。
- 定向复核：首次仅重跑8个失败节点，13个参数化用例中12通过、1项因批量审核列表条目只补到总操作清单而未补到角色清单仍失败；修正角色清单后仅重跑该节点，1项通过。按“不自动循环Collect”规则尚未重启完整门禁，下一步先重新冻结候选并准备两条体验。

### 2026-09-14 部署准备：候选02与两条定向体验

- 候选02内容身份：`ec0a72e907cf7787536cf73964f7897485e28c97+overlay-sha256:a7ce55e1a1eee26d3ad11cafd080f2abc435bf3e1af960a892915415e330ca4c`；133个已修改、81个未跟踪、5个删除项，共219项显式覆盖，排除`data/`。清单为`D:/CLSEN_DeploymentPrep_20260914/evidence/candidate-overlay-manifest-02.json`，SHA-256 `631514bf1d2f52b1e412d1958de765c1487eb109f8230cf41cb487040f150dc7`。
- Storybook材料：`LedgerMetricHelp.stories.tsx`、`ProductTrendChart.stories.tsx`和`ProductTrendChart.reference.md`均已纳入候选02并逐文件哈希确认；三项在候选03保持相同内容。候选02本地Collect仍在frontend门禁前停止，因此Storybook构建待完整Collect，不把“已纳入”写成“构建通过”。
- 体验环境：Run ID `0f54e6bb87424b7da68ec7f8ae007f9d`，前端`http://127.0.0.1:59452`、API`http://127.0.0.1:47596`，任务自有一次性MySQL `clsen_data_test_0f54e6bb87424b7d`，schema `0028`。完整登录名`catalog-live-admin-0f54e6bb87424b7da68ec7f8ae007f9d`，密码只保存在runtime的`experience-credentials.json`。未访问业务原件、`data/`或业务数据库。
- 官方体验脚本仅允许Catalog模式。为同时提供P0产品页，本次只在`experience-run-02`执行副本创建任务专用脚本副本并移除Products体验限制；候选应用源码、冻结清单和仓库正式脚本均未因此改变。第一次TTY运行在服务启动后因子进程作业对象“拒绝访问”失败，已确认容器和端口清理；无TTY重试成功并持续健康。这是环境准备问题，不是#9/#35功能失败。
- #9数据、入口与确认：虚构分类为`衬衫→长袖衬衫/短袖衬衫`及`西装外套`。首次交接误指向批量维护页，已纠正为“商品→查看商品卡→管理分类”（本次`/catalog/styles/2`）；用户按搜索/展开、未保存切换保护、取消修改及窄屏布局路径体验后明确回复“通过”。状态`user_verified`，不扩大为正式发布验收通过。
- #35数据、入口与确认：`/products?from=2025-07-17&to=2025-07-17&return_basis=report_date`返回200，产品账3款、销售额合计US$669.98；款号100为46件/US$569.98/3件退货。用户按销售贡献的占比/平均单价、退货关注的同期退销比及切回路径体验后明确回复“#35通过”。状态`user_verified`，不扩大为其他产品分析路径或正式发布验收通过。
- V35仍为批准前全量mapping/exclusion证据不足。本次新候选清单、虚构分类和产品账只能证明当前候选与新环境，不能倒推V35历史状态；继续作为发布声明限制/残余风险，不认定数据丢失。
- 后续边界：#9/#35两条定向体验均已确认，不再重复安排。候选02完整本地Collect已经用户授权启动并在首项失败处停止；后续状态见下一节。正式`release-gates`还需另行授权提交/整合/push并形成远端master干净SHA与成功`master-required`，实际部署仍单独授权。

### 2026-09-14 部署准备：候选02 Collect失败与候选03定向修正

- 候选02本地Collect按既定顺序启动，但因其为`ec0a72e`加未提交overlay，不满足正式canonical Collect的干净SHA合同，本次只能记为同顺序本地预演。首项`windows-smoke`收集378项，375通过、1失败、2项Windows允许跳过；失败后其余门禁停止，没有自动重跑完整Collect。
- 唯一失败节点为`backend/tests/contracts/test_project_optimization_baseline_runner.py::test_runner_disallows_retry_based_success`。保留最内层stderr后确认`validate-pytest-outcomes`报`routes must contain 18 unique identities`：候选02的基线manifest已有19条路由并包含`/catalog/maintenance`，校验器的路由类型、角色、摘要和数量提示仍为18路由旧合同。候选01同节点通过、runner/校验器/测试三文件在候选01与02之间均未变化，排除业务功能失败和随机环境波动。
- 最小修正只更新`tools/project_optimization_baseline.py`中的`/catalog/maintenance`路由类型、两角色合同、19路由摘要及数量提示，不改业务逻辑。进程内单变量验证先使相同报告由退出码2变为0；随后新候选03的原失败节点定向结果为`1 passed in 2.23s`。
- 候选03内容身份为`ec0a72e907cf7787536cf73964f7897485e28c97+overlay-sha256:c70ceee7d0e1706f46e8545bdd4a3f73d718786270237ad8e41daf95d8f97dd4`；134个已修改、81个未跟踪、5个删除项，共220项，排除`data/`。清单为`D:/CLSEN_DeploymentPrep_20260914/evidence/candidate-overlay-manifest-03.json`，SHA-256 `31b1f3ebece02edf3de5f9af04cffb4ff3f41c787071aaec380ce44fd133303a`；`candidate-source-03`与`gate-run-03`逐项校验均为220项、0不一致。
- 候选03相对候选02没有业务代码变化；除门禁校验器外，仅同步主工作区的AGENTS/计划/流程状态文档。因此保留#9/#35在候选02的用户确认，不重复体验；Storybook材料内容未变但构建仍待门禁。候选03完整本地Collect未启动，不能据定向节点通过写成门禁、release validation或可发布通过。
- 本批实际Skill：`systematic-debugging`，用于保留内层错误、比较候选差异、单变量验证根因并只修正已确认的门禁合同。

### 2026-09-14 部署准备：候选03完整本地Collect结果

- 用户明确授权候选03启动一次完整本地Collect；仍按overlay候选本地同顺序预演记录，不冒充远端master干净SHA的canonical/release validation。
- Windows smoke完成：378项收集，376通过、2项Windows平台允许跳过、0失败，耗时37.78秒；此前失败的baseline runner契约组在本轮通过。
- Ubuntu-full在Ruff阶段失败，pytest尚未开始。共36项：5项`I001`导入排序、31项`E501`超长行，分布于`style_sql.py`、`approval.py`、`change_service.py`、`queries.py`及4个对应测试文件。定向Ruff对同8文件再次得到相同36项，退出码1。
- 候选01/02/03清单中这8个文件的SHA-256逐项相同，因此失败不是候选03新增门禁修正造成；Windows通过也不能覆盖Ubuntu Ruff失败。当前证据没有证明业务逻辑错误，只证明候选内容不满足现行Ruff门禁。
- Collect按首个失败停止；Frontend full、MySQL 8.0、MySQL 8.4、Storybook构建和不涉及业务原件的后续发布材料检查均未执行。未访问业务原件、`data/`或业务数据库。
- 最小后续范围是仅整理这8个文件的导入和长行，不改语义；完成后只跑这8文件的Ruff，再冻结新候选。新候选的完整Collect不得因本次失败自动启动，需另行明确。
- 本批实际Skill：`executing-plans`用于按授权门禁顺序执行，`systematic-debugging`用于失败首因与候选来源核对。

### 2026-09-14 部署准备：候选04最小Ruff整理与冻结

- 用户确认执行既定最小后续范围。仅在`style_sql.py`、`approval.py`、`change_service.py`、`queries.py`及4个对应测试文件中处理5项`I001`、31项`E501`，并执行同8文件的Ruff机械格式化；未改变业务分支、权限、数据口径或测试断言。
- 业务工作树同8文件的`ruff check`与`ruff format --check`均通过；冻结后在`candidate-source-04`再次得到相同结果。没有运行pytest、Frontend、MySQL、Storybook构建或完整Collect。
- 候选04内容身份为`ec0a72e907cf7787536cf73964f7897485e28c97+overlay-sha256:bd0bac0b24140304c9c0f2fd620e6b4b8e01fd91e62b6acd9f3401d0f146bd0c`；134个已修改、81个未跟踪、5个删除项，共220项，排除`data/`。清单为`D:/CLSEN_DeploymentPrep_20260914/evidence/candidate-overlay-manifest-04.json`，SHA-256为`48b2927780218d575c7a9ef37b460a5099aeb44c5a862c655a3af3f314fe8d93`。
- `candidate-source-04`与`gate-run-04`均基于`ec0a72e907cf7787536cf73964f7897485e28c97`，按清单逐项检查均为220项、0不一致。相对候选03只有8个Ruff文件和5份冻结前同步的权威计划/流程文档内容变化；#9/#35业务语义未变，既有用户确认继续保留；#40材料继续纳入但构建待门禁。
- 当前停止在候选04已冻结、定向Ruff通过。候选04完整本地Collect必须由用户再次明确授权，不因定向结果自动启动；提交、整合、push、远端`master-required`、正式release gates和实际部署仍分别授权。V35历史证据不足边界不变。
- 本批实际Skill：`executing-plans`用于按既定最小范围执行，`verification-before-completion`用于候选身份、逐项哈希和定向Ruff核验。

### 2026-09-14 部署准备：候选04完整本地Collect结果

- 用户明确授权候选04启动一次完整本地Collect；仍按overlay候选本地同顺序预演记录，不冒充远端master干净SHA的canonical/release validation。
- Windows smoke完成：378项收集，376通过、2项Windows平台允许跳过、0失败，耗时38.90秒。
- Ubuntu-full的Ruff lint通过；随后全后端`ruff format --check`发现29个文件未格式化并以退出码1停止，pytest尚未开始。再次以相同只读format检查提取到准确29文件清单；这些文件在候选03与候选04逐文件SHA-256均相同，因此不是候选04已完成的8文件整理引入。候选03此前在lint阶段停止，未执行到本项。
- 29文件精确范围：`backend/app/analytics/style_repository.py`、`backend/app/api/catalog_exports.py`、`backend/app/api/catalog_imports.py`、`backend/app/api/catalog_queries.py`、`backend/app/api/data_calendar.py`、`backend/app/catalog/candidates.py`、`backend/app/catalog/category_service.py`、`backend/app/catalog/commands.py`、`backend/app/catalog/identity_conflicts.py`、`backend/app/catalog/import_repository.py`、`backend/app/catalog/import_service.py`、`backend/app/catalog/ooxml.py`、`backend/app/catalog/snapshots.py`、`backend/app/catalog/workbook.py`、`backend/app/main.py`、`backend/app/maintenance/backup.py`、`backend/app/worker/catalog_exports.py`、`backend/tests/contracts/test_database_bootstrap_script.py`、`backend/tests/contracts/test_maintenance_scripts.py`、`backend/tests/contracts/test_migration_contract.py`、`backend/tests/integration/test_catalog_repository.py`、`backend/tests/integration/test_database_constraints.py`、`backend/tests/integration/test_migrations.py`、`backend/tests/unit/catalog/test_candidates.py`、`backend/tests/unit/catalog/test_incremental_source_identity.py`、`backend/tests/unit/catalog/test_workbook.py`、`backend/tests/unit/maintenance/test_schema_compatibility.py`、`backend/tests/unit/test_catalog_api.py`、`backend/tests/unit/test_openapi_contract.py`。
- Collect按首个失败停止；Ubuntu pytest、Frontend full、MySQL 8.0、MySQL 8.4、Storybook构建及后续发布材料检查均未执行。未访问业务原件、`data/`或业务数据库。
- 最小后续范围是仅对已明确的29文件执行Ruff机械格式化，并运行这29文件的定向lint与format检查，再冻结新候选。新候选完整Collect不得因本次失败自动启动，需另行明确；现有证据不构成业务逻辑缺陷。
- 本批实际Skill：`executing-plans`用于按授权顺序运行门禁，`systematic-debugging`用于提取失败范围及核对候选来源，`verification-before-completion`用于最终状态与证据边界核验。

### 2026-09-14 部署准备：候选05机械格式化与冻结

- 用户明确授权仅机械格式化候选04 format门禁列出的29个文件，运行同范围定向lint/format检查并冻结候选05；授权不含pytest、完整Collect、提交、整合、push、迁移或部署。
- 格式化前29文件在业务工作树与候选04逐文件SHA-256一致；随后仅以Ruff formatter处理这29文件。业务工作树与冻结后的`candidate-source-05`均通过同29文件`ruff check`和`ruff format --check`，没有运行其他测试。
- 候选05内容身份为`ec0a72e907cf7787536cf73964f7897485e28c97+overlay-sha256:4ff3199b7d3343ba35b3896786615926c066d9f22415d96002deff90fd50f109`；134个已修改、81个未跟踪、5个删除项，共220项，排除`data/`。清单为`D:/CLSEN_DeploymentPrep_20260914/evidence/candidate-overlay-manifest-05.json`，SHA-256为`7d7cc6fb9f764903cd42ee5198f43f63be545bffbff15a2bbff173a8f21a9e04`。
- `candidate-source-05`与`gate-run-05`均基于`ec0a72e907cf7787536cf73964f7897485e28c97`，按清单逐项检查均为220项、0不一致。相对候选04仅29个格式化文件和5份冻结前同步的权威计划/流程文档变化；#9/#35业务语义未变，既有用户确认继续保留；#40材料继续纳入但构建待门禁。
- 当前停止在候选05已冻结、定向lint/format通过。候选05完整本地Collect必须由用户再次明确授权，不因定向结果自动启动；后续提交、整合、push、远端`master-required`、正式release gates和实际部署仍分别授权。V35历史证据不足边界不变。
- 本批实际Skill：`executing-plans`用于按既定最小范围执行，`verification-before-completion`用于定向Ruff、候选身份及逐项哈希核验。

### 2026-09-14 部署准备：候选05完整本地Collect结果

- 用户明确授权候选05启动一次完整本地Collect；候选仍为`ec0a72e`加未提交overlay，本轮继续按相同顺序本地预演，不冒充要求远端master干净SHA的canonical/release validation。
- Windows smoke完成：378项收集，376通过、2项Windows平台允许跳过、0失败，耗时36.07秒。
- Ubuntu-full的Ruff lint通过，`ruff format --check`确认399文件已格式化；随后mypy发现73项类型错误、涉及19个文件并以退出码1停止，pytest尚未开始。涉及：`backend/app/catalog/workbook.py`、`backend/tests/performance/project_optimization_baseline.py`、`backend/app/catalog/queries.py`、`backend/app/catalog/import_repository.py`、`backend/app/catalog/category_service.py`、`backend/app/worker/catalog_exports.py`、`backend/app/catalog/approval.py`、`backend/tests/unit/test_category_rename.py`、`backend/tests/unit/catalog/test_evidence_locator.py`、`backend/tests/unit/worker/test_catalog_exports.py`、`backend/app/catalog/change_service.py`、`backend/tests/unit/catalog/test_incremental_source_identity.py`、`backend/tests/unit/test_version_rows.py`、`backend/tests/unit/test_calendar_recovered_import.py`、`backend/tests/unit/test_style_analytics_api.py`、`backend/tests/unit/test_catalog_import_history.py`、`backend/tests/unit/test_batch_review_history.py`、`backend/tests/unit/test_catalog_api.py`、`backend/tests/integration/test_catalog_approval.py`。
- Collect按首个失败停止；Ubuntu pytest、Frontend full、MySQL 8.0、MySQL 8.4、Storybook构建及后续发布材料检查均未执行。现有输出只证明mypy门禁不满足；未逐项诊断前不得把73项静态类型错误写成73个业务缺陷，也不得据此推断用户体验失败。
- 运行后重新按候选05清单检查`gate-run-05`，220项、0不一致，HEAD仍为`ec0a72e907cf7787536cf73964f7897485e28c97`，无活动门禁进程。未访问业务原件、`data/`或业务数据库，未修改体验环境。
- 最小后续范围是另行授权后只诊断并修正上述19文件的mypy问题，运行对应定向mypy并冻结新候选；新候选完整Collect不得自动启动。提交、整合、push、正式release gates和实际部署继续分别授权。
- 本批实际Skill：`executing-plans`用于按授权顺序运行门禁，`verification-before-completion`用于核实首因、未执行范围和候选未漂移。

### 2026-09-14 部署准备：候选06 mypy定向修正与冻结

- 用户明确授权只诊断并修正候选05记录的19文件mypy问题，运行定向mypy后冻结候选06；候选06完整Collect须再次授权。本批不新增功能、不启动Stage5.1 R1/R2或Stage5.2预设重构，也不含提交、整合、push、迁移或部署。
- 稳定复现为73项/19文件。根因集中在SQL `RowMapping`与宽泛`object`字典缺少精确类型、同函数变量名复用导致错误继承旧类型、测试替身与具体接口类型不一致、测试函数缺少注解，以及Windows平台静态折叠和指数表达式类型推断；没有证据支持将其表述为73个业务功能缺陷。
- 最小修正后，17个文件相对候选05发生内容变化；`backend/app/catalog/approval.py`与`backend/tests/unit/worker/test_catalog_exports.py`无需直接修改，其错误由依赖类型修正关闭。未修改业务分支、权限、数据口径或用户体验环境。
- 业务工作树定向结果：mypy为`Success: no issues found in 19 source files`，Ruff lint为`All checks passed!`，Ruff format为`19 files already formatted`，受影响离线单元测试为`59 passed in 1.34s`。冻结后在`candidate-source-06`再次运行同19文件mypy，结果仍为0项问题；未运行MySQL、Frontend、Storybook或完整Collect。
- 候选06内容身份为`ec0a72e907cf7787536cf73964f7897485e28c97+overlay-sha256:ec8e77e00be09f4eb1469c0f7f59bdd422f069799ddcd55c68a11ec1f4be3f84`；136个已修改、81个未跟踪、5个删除项，共222项，排除`data/`。清单为`D:/CLSEN_DeploymentPrep_20260914/evidence/candidate-overlay-manifest-06.json`，SHA-256为`a4aa17ba518a3e616dd64bb7f68a26c6b4035a26e39ed008eb835bab6cd254f0`。
- `candidate-source-06`与`gate-run-06`均基于`ec0a72e907cf7787536cf73964f7897485e28c97`，按清单逐项检查均为222项、0缺失、0额外、0哈希不一致，清单overlay hash可独立重算。相对候选05实际变化为17个后端/测试文件和冻结前同步的5份权威计划/流程文档；#9/#35业务语义未变，既有用户确认继续保留；#40材料继续纳入但构建待门禁。
- 当前停止在候选06已冻结、定向mypy/Ruff及受影响离线单元测试通过。候选06完整本地Collect必须由用户再次明确授权，不因定向结果自动启动；正式`release_validation`仍未开始，提交、整合、push、远端`master-required`、正式release gates和实际部署继续分别授权。V35历史证据不足边界不变。
- 本批实际Skill：`systematic-debugging`用于从稳定错误输出归类根因并约束最小类型修正；`verification-before-completion`用于定向mypy/Ruff/受影响测试及候选身份、逐项哈希核验。

### 2026-09-14 部署准备：候选06完整本地Collect结果

- 用户再次明确授权候选06启动一次完整本地Collect。候选仍为`ec0a72e`加未提交overlay，本轮继续按候选02–05相同的本地同顺序预演执行，不冒充要求远端master干净SHA的canonical或正式`release_validation`。
- 运行前`gate-run-06`按清单核验222项、0不一致，HEAD为`ec0a72e907cf7787536cf73964f7897485e28c97`；Python 3.14、Node、pnpm和Docker前置均可用。Windows smoke收集378项，376通过、2项Windows平台允许跳过、0失败，耗时36.31秒。
- Ubuntu-full的Ruff lint通过，`ruff format --check`确认399文件已格式化，mypy确认397个源文件无问题。离线后端测试收集1596项，352项按既定marker排除，执行1244项：1241通过、2项Windows平台允许跳过、1项失败，耗时89.21秒。
- 唯一失败节点为`backend/tests/unit/test_batch_reviews_api.py::test_batch_review_router_exposes_all_seven_operations`。实际路由集合比期望多`GET /api/imports/batch-reviews`；同候选的`test_batch_review_history.py`已验证列表查询，`test_openapi_contract.py`与生成客户端均包含该GET入口。失败节点定向重跑仍以相同额外路由失败，1项失败、耗时0.46秒。
- `backend/app/api/batch_reviews.py`与失败测试在候选05和候选06逐文件SHA-256相同，排除候选06 mypy修正引入该失败；测试文件仍保持基线的“seven operations”名称和7项精确集合，未随既有列表入口更新。现有证据支持“测试合同未同步”，不支持将列表入口认定为功能缺陷，也不撤销#9/#35既有用户确认。
- Collect按首个失败停止；Frontend full、MySQL 8.0、MySQL 8.4、Storybook构建、OpenAPI漂移复核及其后本地材料门禁均未执行。未访问业务原件、`data/`或业务数据库，未修改体验环境。
- 最小后续范围是另行授权后只更新该路由合同测试的名称和期望集合为8项，保留新增GET入口；运行该失败节点及直接相关的历史列表/OpenAPI目标检查，再冻结新候选。新候选完整Collect不得自动启动，仍须再次授权；提交、整合、push、正式release gates和实际部署继续分别授权。
- 本批实际Skill：`executing-plans`用于按授权门禁顺序执行；`systematic-debugging`用于保留完整失败、比较候选内容并定位陈旧测试合同；`verification-before-completion`用于核实结果、未执行范围和候选未漂移。

### 2026-09-14 部署准备：候选07路由合同修正与冻结

- 用户确认执行候选06失败后的最小范围：只更新`backend/tests/unit/test_batch_reviews_api.py`的路由合同测试，运行失败节点及直接相关历史列表/OpenAPI检查并冻结候选07；候选07完整Collect仍需再次授权。本批不修改业务实现，不含提交、整合、push、迁移或部署。
- 修正仅有两项语义：测试名由`test_batch_review_router_exposes_all_seven_operations`改为`test_batch_review_router_exposes_all_eight_operations`，期望集合加入既有`GET /api/imports/batch-reviews`。首次目标测试7项通过；Ruff lint通过，format检查要求统一该文件格式后执行单文件机械格式化。
- 格式化后在业务工作树重新运行相同范围：失败路由合同文件、`test_batch_review_history.py`、OpenAPI会话认证、服务端权限依赖和生成类型一致性共7项通过，耗时1.60秒；单文件Ruff lint通过、format确认已格式化。冻结后在`candidate-source-07`再次得到7项通过（2.18秒）及相同Ruff结果。
- 候选07内容身份为`ec0a72e907cf7787536cf73964f7897485e28c97+overlay-sha256:6762f052afab6366aa219743f08b4e27556a1c868799d1e36ecb2102a075a4ea`；137个已修改、81个未跟踪、5个删除项，共223项，排除`data/`。清单为`D:/CLSEN_DeploymentPrep_20260914/evidence/candidate-overlay-manifest-07.json`，SHA-256为`bb636196b51278c6971bf3d008364094e44f3bcbbbc3b2fee73ef9c82c460577`。
- `candidate-source-07`与`gate-run-07`均基于`ec0a72e907cf7787536cf73964f7897485e28c97`，按清单逐项检查均为223项、0缺失、0额外、0哈希不一致，overlay hash可独立重算。相对候选06新增内容项仅为上述测试文件；另同步冻结前5份权威计划/流程文档。#9/#35业务语义未变，既有用户确认继续保留；#40材料内容不变但构建待门禁。
- 当前停止在候选07已冻结、7项目标检查及单文件Ruff通过。候选07完整本地Collect必须由用户再次明确授权，不因定向结果自动启动；正式`release_validation`仍未开始，提交、整合、push、远端`master-required`、正式release gates和实际部署继续分别授权。V35历史证据不足边界不变。
- 本批实际Skill：`systematic-debugging`用于按已确认根因执行单点测试合同修正；`verification-before-completion`用于目标测试、Ruff及候选身份、逐项哈希核验。

### 2026-09-14 部署准备：候选07完整本地Collect结果

- 用户明确授权候选07启动一次完整本地Collect；候选仍为`ec0a72e`加未提交overlay，本轮按候选02–06相同的本地同顺序预演执行，不冒充要求远端master干净SHA的canonical或正式`release_validation`。
- 运行前候选07按223项清单核验无不一致。Windows smoke收集378项，376通过、2项Windows平台允许跳过、0失败，耗时35.90秒。
- Ubuntu-full的Ruff lint通过，`ruff format --check`确认399文件已格式化，mypy确认397个源文件无问题；离线后端收集1596项，352项按`not mysql`排除，执行1244项，1242通过、2项Windows平台允许跳过、0失败，耗时90.28秒。
- Frontend full在首项ESLint失败并停止：`ImportReviewFlow.test.tsx`有3项`no-base-to-string`，`DateWorkbenchPage.test.tsx`有1项`require-await`及5项unsafe/unnecessary类型错误，共9项。定向ESLint稳定复现相同结果；类型检查、Token、单元测试、浏览器测试、Storybook静态构建/无障碍/视觉、两种来源生产构建均未执行，MySQL 8.0/8.4及后续门禁也未启动。
- 两个失败文件在候选02、03、04、05、06、07清单中的SHA-256各自完全一致，排除候选07后端路由测试合同修正引入。源码对比显示错误来自新增测试写法：对`string | URL | Request`直接`String()`，以及无实际`await`的async回调和无类型JSON解析；同文件/相邻测试已有类型安全URL分支及LocationProbe断言模式可复用。现有证据只证明测试代码不满足当前lint合同，不证明业务功能缺陷。
- 失败后`candidate-source-07`与`gate-run-07`再次按223项清单逐项检查，均为0缺失、0哈希不一致、0个删除项意外存在；无活动门禁进程。未访问业务原件、`data/`或业务数据库，未修改体验环境。
- 最小后续范围须另行授权：只修正上述2个测试文件的类型安全写法，运行定向ESLint和对应受影响测试并冻结新候选；新候选完整Collect不得自动启动，提交、整合、push、正式release gates和实际部署继续分别授权。#9/#35既有体验确认与V35历史证据不足边界均不变。
- 本批实际Skill：`systematic-debugging`用于复现失败、比较候选哈希并定位lint根因；`verification-before-completion`用于读取本轮门禁输出、未执行范围及复核候选未漂移。

### 2026-09-14 Stage5.1/5.2范围收尾确认

- 用户明确确认Stage5.1无R1/R2新增代码项，记录为 `scope_closed / no_implementation_required`；这不是业务开发完成或新体验通过。V35继续作为历史证据不足保留，A–D/D1–D8继续延期。
- 用户明确确认Stage5.2不启动预设重构，记录为 `scope_closed / no_implementation_required`；候选子表化、游标分页、流式XLSX、组件/Repository拆分及未来ERP预构建均未实施。完整性能验收仍属部署准备。
- 下一任务为部署准备，`not_started / awaiting_authorization`。本次确认不授权冻结候选、纳入未跟踪材料、准备#9/#35体验、运行发布门禁、提交、整合、迁移或部署。
- 适用基线仍为主工作区 `codex/development-throughput / 7de0ee6` 与业务工作树 `codex/stage4-1-app-shell / ec0a72e` 加既有未提交成果；本轮仅更新主工作区状态文档，不触碰业务工作树。
- 本轮实际Skill：`verification-before-completion`，用于确认状态写回、边界和链接；未运行测试或构建。

### 2026-09-14 当前发布范围与基线核对

- 需求与模块：核对45组中3组部分确认、Storybook材料同步、V35批准前全量mapping/exclusion证据缺口，并确定Stage5.1/5.2最小范围；详细逐项分类见计划索引同名清单。
- 基线：主工作区 `codex/development-throughput / 7de0ee6` 为文档权威；业务工作树 `codex/stage4-1-app-shell / ec0a72e` 加既有未提交成果为实际功能来源，HEAD不是完整交付。定向状态确认分类维护/产品总表有已修改内容，分类编辑器和三份Storybook/参考文件仍未跟踪；本轮没有改变这些成果。
- 3组部分确认：分类树最终连续UI和销售贡献/退货关注组合没有现成缺陷证据，分别保留为“需要补体验”；已有分类业务、排序、详情和指标弹窗确认不撤销。Storybook属于“仅材料同步”：20601缺指标说明故事但业务组件相同，12个差异是测试文件，不要求同步到旧运行副本；候选冻结时纳入未跟踪故事/参考文件。
- V35证据：仅复核已记录的 `sku-closeout-summary.json` 与 `sku-closeout-readonly.json`。它们支持8月1–6日既有合计一致、1202历史身份可读、43→44仅增加一个别名；不含批准前V35全目录mapping/exclusion成对清单或摘要，不能证明全目录前后不变，也不表示发现数据丢失。当前V36/current确认路径不因此失效；V35不能作为已验证历史或回滚基线。
- 阶段处置：Stage5.1没有确认的R1/R2修复项，A–D/D1–D8继续延期；Stage5.2没有确认的当前规模代码缺口，不启动候选子表化、游标分页、流式XLSX或未来ERP预构建。两项定向补体验和Storybook材料收口放到发布候选收口，完整性能/恢复/发布门禁放到部署准备。
- 同项后续：用户已确认Stage5.1无当前R1/R2代码项、Stage5.2不启动预设重构；两阶段范围已收尾。部署准备仍需另行授权，当前不冻结候选、不纳入材料、不准备#9/#35体验。

### 2026-09-14 主线重新规划交付

- 需求与模块：用户确定Java负责后续ERP核心、Python负责报表/AI/清洗/自动化/外部适配，要求当前计划重新规划；影响计划索引、AGENTS、Skill路由及原5.1设计定位。
- 实施状态：规划文档已更新；Stage5.1/5.2开发未启动。同项后续发布范围核对已完成，当前分别收敛为“无已确认R1/R2代码项”和“无已确认规模代码项”，完整结账治理与预设规模化重构不再默认必做。
- 同项连续优化：用户要求优化原Stage5.1计划，现已将原链接更新为[实施计划v1.1](../superpowers/plans/2026-09-14-stage5-1-catalog-history-governance-plan.md)，旧完整设计另存[延期参考](../superpowers/plans/2026-09-14-stage5-1-full-history-governance-v1-reference.md)。正文增加已有代码依据、范围入选规则、按需R1/R2路径、已有目标测试选择和3–5步体验；后续只读范围核对未发现实际缺陷，R1/R2当前不选入。该结论不代表测试通过或Stage5实施完成。
- 审阅方式：阅读新主线及旧→新范围映射；本轮无独立UI，不新增体验确认，也不改Stage4既有确认。实际Java详细规划在部署准备完成后，实施另按届时范围启动。
- 适用版本：主工作区 `codex/development-throughput / 7de0ee6` 文档修订；业务工作树 `codex/stage4-1-app-shell / ec0a72e` 加既有未提交成果，未整合、未部署。HEAD不代表全部交付代码。
- 剩余项：V35历史证据不足、45组中3组部分确认和Storybook同步保留；在发布范围核对中逐项处置，不冒充通过，不重开全部体验。正式发布门禁仍完整保留，权限、并发和数据一致性开发检查不延期。



## 2026-09-11 Stage4体验功能重新盘点

按用户要求统计原定功能及中途优化，详见[45组功能与包含情况清单](../workflow/stage4-experience-feature-inventory-2026-09-11.md)。初次核对时42组有对应功能/批次确认、3组保留部分确认（分类树连续UI、销售贡献/退货关注组合、Storybook）；候选02的#9分类树最终UI及#35销售贡献/退货关注组合现均已获用户确认，当前为44组确认、#40材料构建待门禁。不是45次独立测试或当前真实环境全覆盖确认。本轮比较开发工作树与20601的source：backend/app 177文件全同；frontend/src 257文件内业务实现全同，12个测试文件不同，指标说明Storybook故事文件仅开发工作树存在。业务功能已包含，开发展示材料同步缺口另记，未擅自同步或重跑测试。保留V35未验证及正式发布门禁边界，不重开已确认体验。本批无需Skill。

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


## 2026-09-11 新发布SKU发现与归属衔接修复（development_complete / ready_for_user_review）

用户现场反馈 `/catalog/unmatched` 无日期入口长期停在“正在核对”。定向计时表明主API约0.54秒，阻塞来自前端在设置主结果前按每批4款遍历34款审核候选。`CatalogUnmatchedPage` 现先完成 `listCatalogUnmatched` 并渲染13项来源，再单独读取当前目录和逐款候选；候选加载和失败都限制在“已有审核候选”区域。重试仍清理旧状态，切换范围/页码会清理旧主结果，避免显示错范围数据。

验证：修改现有组件测试，让待归属API返回、候选请求永久不完成，断言1202、US$35.99、处理入口和候选局部加载提示均可见；Vitest 1 passed，两文件ESLint和diff检查通过。标准 `run-dev-check.ps1` 被既有pnpm无TTY模块目录确认拦截，未安装/清理依赖，改用工作树现有Vitest/ESLint直接执行同一目标。两文件同步到隔离source，浏览器实际无日期入口已显示13项主清单和独立候选加载状态。状态 `development_complete / ready_for_user_review`，无数据库写入、批准、完整回归或阶段推进。Skill：`systematic-debugging`，用于定位API与页面加载链差异。

按[新发布SKU发现与商品归属衔接修复 v1.0](../superpowers/plans/2026-09-11-published-sku-discovery-and-assignment-fix.md)完成A–C。新增当前发布事实未归属仓库，扩展 `/api/catalog/unmatched` 的范围、准确总数/分页、事实与目录基线、影响和候选状态；只读GET不再依赖目录导出已采集证据。继续复用原目录导出和在线审核，没有新增审批系统。产品分析覆盖提示、待归属详情、候选入口、返回筛选和失败重试已接通。

实际环境为 `july-baseline-20260910` / Run ID `b2f5960b07c74303ac2d26bf82d3be43`，源码同步后以 `resume-review.ps1 -Experience -ExperienceOnly` 完整重启并保持 `http://localhost:20601`。MySQL核实8月1–6日目录V35下有13个去重待归属身份，影响16件、US$614.84和1件退货；1202-Light Blue-XXL为8月4日版本66中的1件/US$35.99，目录证据引用为空但稳定发现身份可用。浏览器已从产品总表进入待归属页并看到同一结果。

D只准备可审阅草稿：export 6 / import 6，修订1。草稿新增1202 Light Blue/XXL稳定变体并把精确Seller SKU预填为纳入目录；其余12个未知SKU仍保留24个阻断项。未提交、未生成批准预览、未批准，当前V35、1202产品22件/US$771.79、日报和历史版本均未改变。用户可在 `/catalog/imports/6` 取消“仅看待处理”并搜索该SKU审阅；批准前必须确认归属，批准后才核对23件/US$807.78。

验证：Python `py_compile` 与本轮文件Ruff通过；`backend/tests/unit/test_catalog_api.py` 5 passed；四个受影响前端组件目标共13 passed。完整typecheck只剩既有 `MergeDecisionMatrix.test.tsx(170,114)` 的 `reason` 可空错误；未扩大到完整回归、双MySQL、E2E、性能、恢复或发布门禁。业务代码仍在 `codex/stage4-1-app-shell` 的 `ec0a72e` 加未提交差异，未提交、push、merge或部署。实际Skill：`executing-plans` 用于按既定计划实施；沿用 `systematic-debugging` 的根因证据。

2026-09-11 计划最初按A发现API、B候选审核、C页面路径、D现有归属修订、E复体验串行交接；上述最新记录覆盖“A–E均待执行”的旧状态。八月授权仍仅为1–6日，业务批准、虚构再发布演练与用户体验确认仍待完成。

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


## 2026-09-11 Stage 4 完整体验：批量暂停/恢复已就绪

隔离任务新增虚构批量任务 #3，来源为仓库 synthetic fixture 的两份单字段标记副本，归属 2099-03-01/02。批次 #68/#69 已解析，确认批量任务后立即通过正式 pause API 停在 `paused`，两项保持 `queued`；浏览器实核入口显示恢复按钮，未生成草稿或发布。用户恢复后只应推进至两项待发布。本项 `development_complete / ready_for_user_review`；失败项重试、正式忽略恢复、文件内重复和剩余角色导航继续独立准备，不以本项代替。Skill：systematic-debugging；只做隔离 API 状态与页面入口核对。

### 2026-09-11 F-01 用户确认与完整体验续接

用户确认 F-01 体验通过，状态更新为 `development_complete / user_verified`。七月授权副本 62 份经只读逐文件全行比较，文件内部完全相同行为 0 组，因此自然重复样本未覆盖；后续只能用明确标记的虚构重复样例体验，不把该结果写成真实数据重复验证。继续准备批量暂停/恢复与失败重试、正式批准忽略恢复和完整导航/角色上下文。未运行完整回归或进入 Stage 5。

### 2026-09-11 F-01 解析同操作重放体验准备

在现有七月隔离库使用仓库自带虚构经营报告，创建测试日期 2099-02-01、批次 #65。相同请求和相同操作令牌连续调用两次，均返回解析尝试 #65、解析基线 #65、确认修订 1、2 行，证明运行账号可读取既有只追加终态且不会重复解析。只到解析基线，未物化草稿或发布。证据与体验说明存放在任务目录 `exercises/parse-replay-2099`；状态 `development_complete / ready_for_user_review`。Skill：systematic-debugging。未运行完整回归、提交、合并、部署或进入 Stage 5。

### 2026-09-11 来源证据体验确认

七月隔离环境中的来源文件名、含表头记录序号、原始退货时间和导入来源时区获用户明确体验通过，状态更新为 `development_complete / user_verified`。仍未覆盖物理 CSV 文本行定位和精确版本自动展开。后续真实数据体验只安排 F-01 真实重试、自然/文件内重复、批量暂停恢复及失败重试、正式批准忽略恢复和完整导航遗漏，不重复已有确认路径。无代码、数据或运行环境改动；本批无需 Skill。

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


本流程按用户要求替代旧计划中的默认组织方式，适用于后续开发。保留已批准的数据边界和明确的阶段前置条件，不把阶段验收工作逐项复制到每个功能任务。

完整测试默认集中到部署准备阶段，在正式上线前完成；另行明确要求的专项验收按指定范围执行。开发交付、提交、合并准备、计划收尾和用户体验不自动触发完整门禁。

项目整体状态与计划归属统一见 [项目计划与进度索引](../workflow/project-plan-index.md)。截至 2026-09-08，4.1、4.2①、4.2②/R、A、B1/B2、C、D 均为 `development_complete / user_verified`。成果仍在 `codex/stage4-1-app-shell` 基于 `ec0a72e` 的未提交改动中，未合并或部署；正式发布验收待部署准备。Stage 3 保持 `accepted / merged_to_stage2_branch`，主线外业务继续暂停。

Stage 3 验收限于原 UI 基础范围；Stage 4/5 的商品业务扩展按索引独立批次实施，页面样式迁移与纯重构继续保持业务语义。日常执行受影响组件及必要局部检查，完整测试留到部署准备。开发完成、用户体验和验收分开记录，不能把状态更新或后续规划讨论作为重新 Collect 的触发器；既有正式证据合同保持有效。

商品主档[优化实施计划 v1.0](../superpowers/plans/2026-09-07-product-catalog-workbook-optimization-implementation.md)已完成开发和人工体验。原“继续剩余Stage 4.3页面”和“审阅完整Stage5.1历史治理”安排均被顶部2026-09-14重规划覆盖；发布范围与基线核对现为 `complete`，Stage5.1/5.2为 `scope_closed / no_implementation_required`。部署准备已于2026-09-14完成候选08冻结，当前为 `in_progress / candidate08_collect_failed / windows_smoke_passed / ubuntu_full_passed / frontend_lint_passed / frontend_typecheck_failed / collect_awaiting_authorization / targeted_experience_complete`；候选07完整本地Collect的Windows smoke及Ubuntu-full通过，Frontend在首项lint因2个既有测试文件共9项错误停止；候选08仅修正这2个测试文件，定向ESLint及48项受影响Vitest通过。候选08完整Collect已获授权，Windows smoke与Ubuntu-full通过，Frontend ESLint通过后在TypeScript首项`MergeDecisionMatrix.test.tsx(170,114)`报TS18049停止；其余Frontend、MySQL、Storybook及后续门禁未执行。候选08清单与身份见上方最新交付记录。`MergeDecisionMatrix.test.tsx`自候选02至08哈希未变，现有证据只证明既有测试类型合同不满足，不证明业务功能失败；#9/#35两条定向体验均保留确认。候选08失败后下一次完整Collect须再次授权，当前不含提交、push、merge、迁移、实际部署或生产变更。正式`release-gates`要求远端master干净SHA及成功`master-required`，本地候选预演不得记作正式发布门禁通过。历史交付记录中的等待体验或不进入下一批只表示当时范围；历史体验地址未在本次复核，不视为仍在线。

### 2026-09-14 候选08定向Lint与受影响测试交付

用户授权仅修正候选07 Frontend full首项暴露的两个既有测试文件共9项lint问题：`frontend/src/features/import-review/ImportReviewFlow.test.tsx` 3项与 `frontend/src/features/workbench/DateWorkbenchPage.test.tsx` 6项。修正仅涉及测试代码的安全路径解析、异步等待和局部JSON结构类型；未修改业务实现、数据、权限或体验环境，也未重开#9/#35已通过体验。

验证在业务工作树 `codex/stage4-1-app-shell`（基线 `ec0a72e` 加未提交成果）使用现有依赖直接CLI完成：目标ESLint通过；ImportReviewFlow 19项、DateWorkbenchPage 29项受影响Vitest共48项通过。该段记录的是完整Collect前的定向修正，随后候选08完整Collect按另行授权执行；Storybook构建/无障碍/视觉门禁、其余Frontend后续门禁、MySQL 8.0/8.4、生产构建或部署演练仍未到达。

已冻结候选08：清单 `[candidate-overlay-manifest-08.json](D:/CLSEN_DeploymentPrep_20260914/evidence/candidate-overlay-manifest-08.json)`，内容身份 `ec0a72e907cf7787536cf73964f7897485e28c97+overlay-sha256:9e8a68250de62fbe816c184e6443f021978e01053ae138e1906d5e218a9f1c23`，清单SHA-256 `44d368d8fa66dd540554424a02d87e89f126a927fc67810a33a23a69a9035807`。`candidate-source-08` 与 `gate-run-08` 均按223项清单逐项核验，missing/mismatch/deleted_present/extras均为0。随后用户授权候选08完整Collect：Windows smoke 378项中376通过、2项Windows平台允许跳过；Ubuntu-full的Ruff lint、399文件format及397源文件mypy通过，pytest收集1596项、排除352项、执行1244项，其中1242通过、2项允许跳过；Frontend ESLint通过，但TypeScript首项在`MergeDecisionMatrix.test.tsx(170,114)`报`TS18049: 'd.reason' is possibly 'null' or 'undefined'`后停止。状态更新为 `in_progress / candidate08_collect_failed / windows_smoke_passed / ubuntu_full_passed / frontend_lint_passed / frontend_typecheck_failed / collect_awaiting_authorization / targeted_experience_complete`；其余Frontend、Storybook、MySQL及后续门禁未执行，下一次完整Collect需再次授权，不提交、push、merge、迁移或部署。本批使用 `systematic-debugging` 定位既有lint/类型合同首因，`verification-before-completion` 复核完整Collect分段输出与候选未漂移。

### 2026-09-14 候选09 Frontend TypeScript 定向修正与冻结

- 用户授权仅修正 `frontend/src/features/import-review/MergeDecisionMatrix.test.tsx` 的可空 `reason` 类型合同问题，运行 Frontend TypeScript 定向检查并冻结候选09；不含完整 Collect、Storybook、MySQL、其余门禁、提交、整合、push、迁移或部署。
- 修正仅在断言中增加 `typeof d.reason === "string"` 守卫，再调用 `includes`；未修改业务实现、权限、数据口径或体验环境。业务工作树现有依赖直接执行 `tsc -b --pretty false` 通过（退出码0）。
- 候选09由基线 `ec0a72e` 加既有overlay形成，清单为 `D:/CLSEN_DeploymentPrep_20260914/evidence/candidate-overlay-manifest-09.json`；`candidate-source-09`/`gate-run-09` 已按223项逐项核验无缺失、不匹配或删除项误存在。候选09完整 Collect 仍须另行授权。候选08完整Collect的Windows/Ubuntu分段结果保留为历史，不外推为候选09新门禁证据；#9/#35确认继续保留，V35仍为证据不足。

### 2026-09-14 候选09完整本地Collect结果

- 用户授权候选09启动一次完整本地Collect；候选仍为 `ec0a72e` 加未提交overlay，本轮按既定顺序执行，不冒充远端master干净SHA的canonical或正式 `release_validation`。候选09保持冻结，未修改业务代码、数据、权限或体验环境。
- pnpm 包装器在依赖状态检查阶段稳定报 `ERR_PNPM_ABORTED_REMOVE_MODULES_DIR_NO_TTY`：候选09的 `node_modules` junction 指向候选08，`.modules.yaml` 的 `virtualStoreDir`仍指向`gate-run-08`。复现前后模块清单与锁文件SHA均未改变，未安装或清理依赖；按现有环境改用冻结副本已有 `.bin` 工具继续，不记为ESLint或业务缺陷。
- Windows smoke完成：378项中376通过、2项Windows平台允许跳过、0失败。Ubuntu-full沿用本次已完成结果：Ruff lint、399文件format、397源文件mypy通过；pytest收集1596项、排除352项、执行1244项，其中1242通过、2项允许跳过。
- Frontend直接工具完成：ESLint通过、TypeScript通过、设计Token检查通过（14个CSS Modules、0项例外）。Vitest在90个测试文件中完成89个，426项通过；首个失败为新增`CatalogMaintenancePage.test.tsx`，并伴随`CatalogImportHistory.tsx:22`读取`items.length`的未处理错误。根因已通过后端`GET /api/catalog/imports`契约及独立`CatalogImportHistory.test.tsx`核对：生产接口和组件测试返回`items/has_next`，该页面测试夹具却对非`/latest`请求统一返回`{catalog:null}`。这是测试夹具契约错误，不是业务实现缺陷证据。
- 按首因停止：Frontend浏览器、Storybook构建/无障碍/视觉、两种生产构建、MySQL 8.0/8.4及后续发布材料门禁未执行。下一批最小范围是另行授权后仅修正该测试夹具、运行该测试及必要定向检查，再冻结新候选；不得自动重跑完整Collect。#9/#35既有体验确认不重开，V35证据不足边界不变。
- 本批使用 `systematic-debugging` 诊断pnpm环境与Vitest首因，使用 `verification-before-completion` 核对输出、失败计数、双副本及未执行范围；没有提交、整合、push、迁移或部署。

### 历史安排：真实数据试用与反馈修订（2026-09-08）

以下为当时安排，旧状态已被顶部2026-09-14最终记录覆盖，保留以解释授权和交付过程。

Stage 4.3 已完成开发与人工体验。Stage 5 前按[真实数据试用计划](../superpowers/plans/2026-09-08-stage4-real-data-review-and-feedback-plan.md)进行一次有限试用，当前 not_started / awaiting_data_scope。本次只编制计划；旧“继续剩余 4.3”的执行提示由此安排替代。

先确认 data/ 外授权脱敏副本、日期/站点范围、体验重点和测试写入范围；隔离环境就绪后先只读、后少量写入，反馈集中修订，复体验只覆盖变化路径。严重数据/权限问题阻塞受影响写入，独立路径可继续；新业务语义先明确决定。原 Stage 4 user_verified 保留，真实数据结果单独记录，不升级为正式 accepted。试用收尾后再与用户确认 Stage 5 入口。

## Agent 如何开始和推进

1. 读取当前工作区的 `AGENTS.md`，确认本轮目标、分支和相关已有改动；只读取相关模块与必要上下文，遵守不访问 `data/` 的边界。
2. 用一句话说明交付内容，选定最小验证目标。小任务直接做，普通功能列几个简短步骤；只有缺失重大决定时才提问，不重新索取已有授权。
3. 按 [Skill 搭配表](../workflow/skill-stack.md) 选择必要指导，也可以不使用 Skill。引用的下游 Skill 同样服从项目边界，不自动启用子代理或额外设计、审批、提交和评审流程。
4. 沿完整使用路径集中修改，复用现有实现、依赖与测试。定向验证通过后交付体验入口；等待反馈期间继续没有依赖的已授权工作。

前端反馈按问题分流：简单字段、文案和局部样式直接修正；整页、多区域信息层级调整或同页反复布局反馈使用 `frontend-design`；步骤过多、入口难找、保存与批准含义不清时使用 `product-design:audit`，基于授权页面证据内联审查一条使用路径。实际报错或行为缺陷进入 `systematic-debugging`，复杂问题才升级到 `diagnosing-bugs` 并沿用已有复现与证据。不为同一反馈默认串联多套 Skill，外部界面参考只在确有帮助时补充。

`AGENTS.md` 管边界，本文件管执行和待办，[验证策略](development-verification-policy.md) 管检查范围与命令，Skill 搭配表管工具选择和覆盖关系。历史计划用于查需求与既有合同，不要求每轮重新阅读，也不作为重复全量验收的触发器。

## 一轮开发如何完成

| 环节 | 必须产出 | 退出条件 |
| --- | --- | --- |
| 确定范围 | 一句话说明用户本轮能使用什么 | 没有影响实施的实质歧义 |
| 实现 | 可运行的完整使用路径 | 本轮功能实现完成 |
| 定向验证 | 最小有效检查及结果 | 受影响范围通过，无关键阻塞 |
| 开发交付 | 改动说明、验证结果、必要待办 | 标记 development_complete |
| 准备人工体验 | 可用入口、对应版本、必要前置条件、3–5 步体验说明 | 入口就绪后标记 ready_for_user_review |
| 用户亲自体验 | 用户对该版本的明确反馈 | 有问题先修复并复体验；明确通过才标记 user_verified |
| 部署准备或明确指定的专项验收 | 约定的正式证据 | 人工体验已确认且满足合同才标记 accepted；正式上线前完成完整测试，发布仍须相应授权 |

普通功能不要求单独设计文档、逐步审批、每一步红绿测试、反复全量评审或证据归档。已有约定足够明确就直接实施。一个需求拆为少数可用功能，避免拆成大量各自触发测试的微任务。

## 用户人工体验

每个可体验功能在必要快检后尽早交给用户本人体验，无需先等待整轮发布验收。体验默认使用可抛弃或明确隔离的测试环境及合成数据；本次真实数据试用可使用用户明确授权、位于 data/ 外的脱敏副本并按专项范围执行，继续遵守不访问 `data/`、不迁移真实数据库等边界；不能为了演示改动活动验收候选。

交付体验时一次性给出以下简短信息，不增加审批文档：

- 体验什么：本轮新增或变化的功能，以及对应提交/版本。
- 从哪里进入：已检查可用的地址或本地启动入口；必要账号通过安全方式获取，文档中不记录密码。
- 怎么体验：3–5 个普通用户可执行的步骤，每步说明预期结果，覆盖主要使用路径。
- 重点反馈：是否符合需要、哪里不好操作、是否遇到错误；列出已知限制，避免用户误以为尚未实现的部分已经完成。

先准备好入口再邀请体验。若环境尚不可用，记录“体验准备中”和具体缺项，不虚构链接、不要求用户先体验一个打不开的功能。纯文档/内部工具没有独立 UI 时提供文档审阅或实际命令使用方式，不额外开发体验页面。

用户明确确认该版本“体验通过”后，记录版本和确认结果为 `user_verified`。用户未回复、只批准开发、代理点击页面或测试通过，都不能替代人工体验结论。等待期间可以推进不依赖反馈的已授权任务，不循环轮询或反复催促用户。

收到问题后记录复现步骤，优先修正本轮使用问题，做受影响范围的快检，再提供同一路径供用户复体验。改变了已经确认的体验行为时，对受影响部分重新确认；不要求用户反复体验无关功能，也不自动重跑全量测试。

人工体验与机器验收分别记录：前者确认实际使用是否符合需求，后者确认规定的技术证据。自动门禁成功只能更新机器验收结果；人工体验仍待确认时不得宣布整体 accepted。

## 工作安排

开发过程中，验证的计划时间通常不超过开发工作时间的约 20%，作为排期信号而非质量豁免；极小改动和权限、并发、迁移等高风险工作不套用比例。普通定向检查默认约 3 分钟，数据库定向检查约 10 分钟。超过时先缩小范围或说明必要性，不自动升级为全量。

达到预算但仍存在关键问题时，明确标记该功能尚未完成并解决问题；可同时推进没有依赖的已授权工作。不要把未验证功能称为通过，也不要以验证预算为由取消必要的数据与权限检查。

一次修改批次只安排一轮必要检查。失败后定位首因、修复、只重跑受影响节点；若第二次仍失败，先重新判断根因和测试环境，停止机械重复命令。检查通过后不为了更有把握再跑一次。

## 开发入口

在已包含这些脚本参数的工作树执行。其他或历史工作树是否支持参数需读取对应脚本确认；如有活动验收，不修改其工作树来安装开发入口。

```powershell
# 后端：必须是 unit/contracts 的显式文件或节点，fail-fast
./scripts/run-dev-check.ps1 -Kind Backend -Targets backend/tests/unit/worker/test_runner.py

# 前端：必须是显式组件测试文件，fail-fast
./scripts/run-dev-check.ps1 -Kind Frontend -Targets frontend/src/features/admin/AdminConsole.test.tsx

# MySQL：沿用现有安全容器逻辑，默认只跑 8.0 和所选节点
./scripts/test-mysql-matrix.ps1 -Suites mysql-p0 `
  -PythonExecutable D:\CLSEN_Data_Web\.venv\Scripts\python.exe `
  -DevelopmentTests tests/integration/test_catalog_schema.py::test_catalog_partial_migration_recreates_only_the_missing_suffix
```

后端/前端加 `-ListOnly`，MySQL 加 `-ListDevelopmentTests`，可预览选择而不启动测试或 Docker。开发入口拒绝目录、非允许测试路径及正式验收环境；MySQL 开发模式拒绝双版本与性能模式。所有开发输出明确不代表完整验收通过。未传开发参数时，原有正式矩阵范围保持不变。

后端临时路径为工作区下唯一 `.tmp/dev-check-*`，MySQL 开发临时目录也在 `.tmp`，容器/临时目录沿用原 runner 清理规则。无需为了普通开发重装依赖。选择阶段不创建数据库；已有记录只证明开发参数的选择与拒绝逻辑，真实 MySQL 开发路径仍按下表待办安排，不据此宣称容器联调已通过。

## 验收安排与失败处理

- 完整门禁默认在部署准备阶段集中安排；用户另行明确要求的专项验收按指定范围执行。普通开发、提交、合并准备、计划收尾和体验反馈不得自动切入完整验收。
- 验收独立冻结候选，开发使用其他分支。与验收无关的文档、UI 或下一项功能可以继续，不修改活动候选的代码、依赖和环境。
- 完整验收失败，保留首因、耗时与原始证据，先集中完成定向修复。一次失败不自动触发又一整轮 Collect。
- 开发证据可说明旧版本已验证的未变化行为，但不能冒充新 SHA 的验收证据。正式验收仍按其合同执行，既有版本限定例外不推广到新候选。
- 发布、数据库实际迁移、push 和 merge 仍按已有授权边界执行。

### Stage 2 历史增量合同（已收尾）

以下保留 2026-09-05 已批准的合同与结论，供追溯历史组合证据；不表示这些候选当前正在执行，也不授权新的跨版本复用或要求后续开发重跑 Stage 2。

- 2026-09-05 项目负责人明确批准一次仅限 Stage 2 的版本化例外：提交 `55a5b29` 相对正式候选 `5d888d0` 的差异只能包含 `frontend/src/features/admin/AdminConsole.css` 中移除 `1440px` 上限并增加 `width: 100%` 的自适应修改。未变化代码可复用 `5d888d0` 的 Collect/Validate 证据；该 CSS 差异以精确 diff、`git diff --check`、1920px 视觉快检及版本 `55a5b29` 的 `user_verified` 作为增量证据。差异文件或内容扩大时本例外立即失效，其他提交仍执行同 SHA 门禁。
- 2026-09-05 项目负责人进一步批准 Stage 2 test-only 增量续跑合同：整合候选 `8283995` 相对 `5d888d0` 只能增加上述 CSS 差异，以及 `backend/tests/integration/test_schema_compatibility.py` 中把过期的 newer 样例 `0023` 更正为 `0024`。复用 `5d888d0` 已通过的 Ubuntu、Windows、Frontend、30 个迁移测试和 252 个 MySQL 8.0 集成测试证据；在 `8283995` 上只补跑修正节点，并继续此前未运行的 MySQL 8.4、性能、UI、备份恢复和部署门禁。不得从头重跑完整 Collect，不得把组合证据描述为单一同 SHA Collect；差异扩大时本批准失效。
- 2026-09-05 项目负责人随后批准把部署门禁中发现的 Worker secret 挂载、入口加载和迁移往返测试前置状态修复纳入同一次增量续跑。最终组合候选为 `c924e4a86fe55a1d15bbfd477ed61c5257c44091`；相对 `5d888d0c9d7cfa6d867df21715136c3074929c69` 严格限定为 `backend/app/deployment/entrypoint.py`、`backend/tests/integration/test_migrations.py`、`backend/tests/integration/test_schema_compatibility.py`、`backend/tests/unit/deployment/test_entrypoint.py`、`frontend/src/features/admin/AdminConsole.css`、`ops/docker-compose.yml` 六个文件。原候选未变化部分继续复用已批准证据，新增差异只运行受影响节点和此前尚未完成的门禁；此结论是透明组合验收，不是单一同 SHA Collect。

### Stage 2 收尾记录（2026-09-05）

- 开发与人工体验：Worker 可观测性使用路径已完成；管理页面自适应版本已由用户明确确认 `user_verified`。
- 复用证据：原候选 `5d888d0` 的 Ubuntu、Windows、Frontend、30 个迁移测试和 252 个 MySQL 8.0 集成测试。
- 增量证据：MySQL 8.0 schema 修正节点、MySQL 8.4 完整兼容门禁、generated-contract、MySQL 8.0/8.4 性能各 25 项、管理员页性能、admin-worker E2E、MySQL 8.0/8.4 备份恢复、Worker 入口 10 项及迁移往返修复节点均通过。
- 部署门禁：前三次分别暴露缺少工作树 secret 链接、Worker 未挂载 session secret、入口未加载 session secret；第四次确认 secret 修复有效后暴露迁移测试初始 revision 假设。上述失败均保留，不作为通过证据。候选 `c924e4a` 的第五次部署验证以 `EXIT_CODE=0` 完成，包含 30 项迁移、部署集成检查、备份与隔离恢复，并清理任务专用容器、卷和网络；日志位于 `D:\CLSEN_Stage2_Evidence\resume-c924e4a86fe55a1d15bbfd477ed61c5257c44091\deployment-attempt5.log`。
- 验收结论：`development_complete`、`user_verified`、`release_validation` 均满足，Stage 2 标记为 `accepted`。该结论不授权发布、真实数据库迁移、push 或 merge。

### Stage 3 收尾记录（2026-09-07）

- 验收版本：`28684cfe6367ad81a1dfef256bdb643c6d36a39f`，分支 `codex/stage3-ui-foundation`，[PR #9](https://github.com/dulanjy/CLSEN_Data_Web/pull/9)。本轮已核对本地候选 SHA；CI 结果已通过 GitHub 只读查询复核，人工体验依据用户明确确认记录；未重复运行测试。
- 开发状态：`development_complete`；用户人工体验：`user_verified`；阶段状态：`accepted / merged_to_stage2_branch`。
- 当前 PR 验收：Ubuntu、Windows、Frontend、MySQL 8.0、`pr-required` 全部通过；MySQL 8.4 按 PR 策略正常跳过，不记为通过。
- PR #9 于 2026-09-07 13:09（北京时间）合入 `codex/stage2-worker-observability`，合并提交 `ec0a72e907cf7787536cf73964f7897485e28c97`，已查询确认 `MERGED`。合并前 `CLEAN`，用户确认候选工作树干净；该描述指 Stage 3 候选工作树，主工作区仍有流程文档未提交改动。
- `release_validation`：当前 PR 约定检查通过；正式部署完整测试仍留到部署准备。本次用户确认已用于 PR #9 合并，不扩大为 master 整合、部署或真实数据库迁移授权，后续 Stage 按已确定的主线和用户开发指令推进。

### Stage 4.1 收尾记录（2026-09-07）

- 开发基线：`ec0a72e907cf7787536cf73964f7897485e28c97`；工作分支 `codex/stage4-1-app-shell`。应用外壳、登录、站点载入/错误、退出失败状态接入 Stage 3 共享组件和 CSS Module，并增加窄屏导航、Escape 关闭与焦点恢复；管理员和版本页保留既有业务行为。
- 开发状态：`development_complete`；用户人工体验：`user_verified`（用户于 2026-09-07 明确确认“通过”）；`release_validation` 留到部署准备。
- 定向证据：App 组件测试 31 项通过，目标 TypeScript、ESLint 和 Token 规则通过；桌面与 390px 登录页真实浏览器快检通过，前端及同源 CSRF 入口返回 HTTP 200。未执行全前端、完整 E2E、正式构建或发布门禁。
- 整合状态：代码仍为未提交工作树改动；未 push、未 merge、未部署、未迁移数据库。下一批进入 Stage 4.2①，不重开 Stage 3、不提前扩入 4.2②/③。

### Stage 4.2① 交付记录（2026-09-07）

- 开发状态：`development_complete / user_verified`。用户完成体验后要求“继续下一个”。`catalog_jobs` 已成为候选导出调度权威；新增 `0024` 迁移、原子领取/续租、有限指数退避、三次上限、人工恢复、审计和 fencing 完成保护。商品主档展示真实阶段、尝试次数、下次重试、失败码、Worker 可用性，并从最新任务恢复页面状态。
- 定向证据：后端相关单元/迁移合同 56 项通过；前端目标组件/API/state 6 项、TypeScript 和目标 ESLint 通过；可抛弃 MySQL 8.0 中候选导出 4 个场景通过，覆盖 active lease 拒绝、revision、幂等、退避上限、恢复审计及 ABA fencing。未执行完整回归、MySQL 8.4 或发布门禁。
- 体验环境：隔离合成库、API、Worker 和前端已在体验结束后通过 runner stop 清理，退出码 0；未迁移或读取现有本地数据库。
- 整合状态：Stage 4.1 与 4.2① 改动均保持未提交；未 push、未 merge、未部署。

### Stage 4.2② 交付记录（2026-09-07）

- 首次交付状态为 `development_complete / ready_for_user_review`；后续 R 修正版本已获用户确认，当前为 `development_complete / user_verified`。复用 `0022` 的已批准 N:1 映射，不新增迁移；商品主档支持商品卡/批量表格双视图，商品卡展示实际变体和来源摘要，稳定变体按需读取多个 Seller SKU 与分页来源明细。
- 定向证据：后端路由契约 3 项和 live harness 相关单元 13 项通过；前端目标组件/API 7 项、TypeScript、目标 ESLint/Ruff 通过；可抛弃 MySQL 8.0 单节点验证两条 Seller SKU 指向同一稳定 SKU并返回来源明细。未执行完整回归、MySQL 8.4 或发布门禁。
- 体验环境：隔离合成库通过正式审批服务预置 3 张商品卡、11 个实际变体，其中一个稳定变体关联 2 个 Seller SKU 和 3 条来源明细；API 登录与查询链路通过，前端返回 HTTP 200。
- 整合状态：Stage 4.1、4.2①、4.2② 改动均保持未提交；未 push、未 merge、未部署。当时等待体验；后续 R、A、B1/B2 均已完成体验，不再作为待体验入口。

### Stage 4.2②-R 反馈修正交付记录（2026-09-07）

- 开发状态：`development_complete / user_verified`。统一“款式编号/内部展示 SKU”网页用语，列表与详情明确款式、实际变体、Seller SKU、来源层级；启用状态改用绿色中文徽标并保留非颜色图标提示；目录工作簿按生成候选、审核方式、校验批准组织，下载、在线审核和恢复操作由真实服务端任务状态决定。用户于 2026-09-07 明确确认该修正版本体验通过。
- 定向证据：受影响四个组件测试文件 7 项通过，目标 ESLint 与 TypeScript 通过；隔离合成实例实际核对商品卡、9 个真实变体、Seller SKU 与来源展开，以及失败任务的可执行动作。未执行完整回归、完整 E2E、MySQL 8.4 或发布门禁。
- 复体验环境：Run ID `11ca24be3ef74a5d932a12a3d8f0c26a`，入口 `http://127.0.0.1:46792/catalog`；使用 runner 自有临时 MySQL 8.0 和临时存储，不读取或迁移现有数据库。用户已明确确认该 R 版本体验通过；此处保留历史环境信息。
- 整合状态：本批与此前 Stage 4 未提交成果均保留在 `codex/stage4-1-app-shell`；未提交、push、merge 或部署。

### Stage 4.2③-A 分类与单商品普通修改交付记录（2026-09-07）

- 首次交付状态为 `development_complete / ready_for_user_review`；空别名数组修正版已获用户确认，当前为 `development_complete / user_verified`，对应 Run ID 见下方状态同步。详情页提供标准名称/主分类独立草稿、前后差异预览和幂等批准；批准形成完整新目录版本并保留其他目录成员。分类字典为站点作用域，支持管理员创建、显示名/别名/启停治理，并保存目录版本分类快照。
- 工作簿：保留 v1 精确结构并按“保持分类”解释；新增 v2 精确结构、款式编号文案及保持/清空/选择分类语义。未知结构继续 fail-closed。
- 定向验证：后端单元 8 项、前端目标 5 项、TypeScript 与目标 Ruff 通过；可抛弃 MySQL 8.0 中 0025 往返迁移及单商品隔离/重复批准/字典改名快照用例通过。发布构建仅停在既有 `VITE_PRODUCT_ANALYTICS_SOURCE` 发布配置要求，TypeScript 已独立通过；未运行完整回归、MySQL 8.4 或发布门禁。
- 整合状态：A 与此前 Stage 4 成果仍为未提交工作树改动；未 push、merge、部署或迁移真实数据库。当时等待体验；后续修正版已确认，B1/B2 也已交付，不再作为执行阻塞。
- 体验环境：Run ID `bbb8b6ccf06047acb521d385ca379c0b`，入口 `http://127.0.0.1:42011/catalog`；临时管理员实走名称/SHIRT 分类预览批准及分类治理页面成功。

### 商品主档专项状态同步（2026-09-08）

R/A/B1/B2/C/D 最新开发与人工体验结论以[专项交付记录](../superpowers/plans/2026-09-07-product-catalog-workbook-optimization-implementation.md#每批执行记录)为依据。A 修正版用户确认对应 Run ID `2f86edc18ad04ea4b52e99b309060c36`；D 最终体验确认对应 `d97a3b79951e45b7bcbcde54bb5db159`。以下状态同步不新增验证证据，不推断 D 已执行最终批准或空目录浏览器全链；这些正式证据待部署准备。前述 A 初版、R 及其他早期记录保留用于追溯，不是当前待体验任务。

### Stage 4.3 发布数据查看首批（2026-09-08）

- 状态：`development_complete / ready_for_user_review`；用户尚未体验确认，`release_validation` 留部署准备。代码在 `codex/stage4-1-app-shell`、`ec0a72e + 未提交改动`；保留原 R/A/B1/B2/C/D 成果。
- 路径：发布总表 → 跨日期发布明细 → 展开/全部原始明细；单日摘要 → 当日原始明细。完成局部样式迁移、共享反馈与分页、月份交接及单日空/失败/日期竞态修正。外层日期工作台及 P0 商品分析未完成迁移。
- 定向验证：`scripts/run-dev-check.ps1 -Kind Frontend -Targets` 显式选择 PublishedDashboard、PublishedDetailLedgerPage、PublishedDateSummaries、ReadonlyPublishedDataGrid、PublishedDayPage 的测试文件，合计 41 项通过；TypeScript 与 8 个相关 TS/TSX 的目标 ESLint 通过。初次 pnpm 在测试执行前尝试自动重装，已用本次进程环境 `pnpm_config_verify_deps_before_run=false` 复用现有依赖；未安装依赖。修复共享 Button 嵌套文本导致的 tab 断言和 ref 类型边界后，仅重跑受影响文件及被 fail-fast 中断的目标。
- 体验运行：`scripts/run-product-catalog-live-e2e.ps1 -Experience -ExperienceOnly`，仅启动已有 MySQL 8.0 镜像、正式隔离账户/TLS/触发器配置与合成样例，不执行完整 E2E。Run ID `d9f9e41881224205af5255261df23e88`，schema 0027，无本轮新增迁移。运行目录 `D:/CLSEN_Data_Web-tmp/stage43-view/clsen-catalog-live-d9f9e41881224205af5255261df23e88`。
- 入口：`http://127.0.0.1:18614/?month=2025-07`；临时账号从运行目录 `experience-credentials.json` 读取，仅用于本轮合成体验。启动器提供 admin 账号；viewer 导出限制由现有组件目标测试覆盖，不宣称本次实走三角色完整验收。
- 体验步骤：① 登录后选择 2025-07，07-17 为完整发布、07-18 为部分发布；② 点击“发布明细”，范围应保持 07-01 至 07-31；③ 展开 07-17 再切换“全部明细”，应能查看原始行、列设置并按授权导出；④ 打开 `/published-details/2025-07-17`，查看指标并通过“查看当日原始明细”进入精确当日范围；⑤ 缩窄窗口，筛选与操作应可用，明细表在表内横向滚动。
- 实际快检：上述真实 API 查询与 CSV HTTP 200，1280/390px 页面截图已检查；390px 明细账/单日摘要无整页水平溢出，无页面脚本错误。定向浏览器脚本和截图存 `D:/CLSEN_Data_Web-tmp/stage43-view`，不作为正式部署门禁。
- 关闭：在目标工作树设置 `$env:TEMP='D:/CLSEN_Data_Web-tmp/stage43-view'`、`$env:TMP=$env:TEMP` 后运行 `scripts/stop-product-catalog-experience.ps1 -RunId d9f9e41881224205af5255261df23e88`，由原脚本清理其所有资源；本轮交付时保持入口运行。
- 余项：人工体验确认；P0 商品分析、工作台/审核、图表/Motion/ECharts 适用项与 CSS 收尾；完整测试和正式发布验收待部署准备，不自动提交、整合或部署。

### Stage 4.3 单日摘要入口反馈修正（2026-09-08）

用户反馈找不到独立单日摘要入口。本次在日期摘要的“读取操作”增加“查看单日摘要”，将全部明细/展开明细的报告日期改为可访问链接并增加提示；单日页显示“返回发布明细”，通过限定为本地明细账路由的 return_to 保留原查询、分页和查看方式。原工作台和版本记录入口保留。

沿用 Run ID `d9f9e41881224205af5255261df23e88`、18614 端口与未提交工作树。33 项受影响组件测试通过；目标 ESLint、TypeScript 通过；真实隔离实例实走两种入口、键盘 Enter 进入及带 search/mode 的原范围返回，无页面脚本错误。状态仍为 `ready_for_user_review`；用户“明白了”不作为本批体验通过。未重新运行完整门禁。

### Stage 4.3 单日摘要展示反馈（2026-09-08）

已修正：退货数 null 不再用横线，未发布报告显示“报告未发布”，已发布但缺少值显示“暂无数据”，真实 0 保留 0。单日组件 7 项目标测试及目标 ESLint 通过；沿用 18614 隔离体验实例，状态仍待用户复体验。

待后续优化：用户建议下方增加月内趋势、顶部统一操作组件。建议历史页默认月初至所选报告日（如 2025-07-01 至 07-18）；当前月可到站点今天。以可切换指标的每日趋势、选中日与前一日比较、月内累计与有效发布日期覆盖说明组织；缺失日期断线、不补零，无可比前日不计算涨跌。顶部采用共享链接按钮和主次操作层级，保留链接语义及原范围返回。图表及统一导航组件尚未实施，不记为本次已完成。

### Stage 4.3 单日摘要月内趋势与共享导航（2026-09-08）

用户已批准前述方案，本次完成开发，状态 `development_complete / ready_for_user_review`。沿用 `ec0a72e + 未提交改动`、Run ID `d9f9e41881224205af5255261df23e88`，没有提交、合并或部署。

- 独立单日摘要页按“当月 1 日至所选报告日”读取现有 daily-ledger 接口；嵌入工作台的摘要仍只取单日。月内趋势按需加载，可切换销售额/订购数/会话数/转化率/退货数；提供日对日变化、月内累计与逐日数据表，按有效值说明各指标覆盖天数。
- 缺报不补零，不跨缺报日期连接或比较；零基数不除零，转化率按百分点比较。使用 BigInt 定点计算，覆盖实际 API 28 位转化率响应与超出 JS 安全整数的大额金额；累计不通过 Number 求和。
- 新增共享 LinkButton 复用现有 Button 样式与 Token，顶部采用带图标的返回/次要总表/主操作链接，保留原筛选返回和链接语义。图表采用局部 SVG，随容器宽度自适应；不新增运行依赖、不改其他业务页面或后端。
- 定向证据：monthlyMetrics 7 项、PublishedMonthTrend 2 项、PublishedDayPage 7 项、LinkButton 1 项及既有 Button 2 项，共 19 项通过；TypeScript、8 个相关 TS/TSX 的目标 ESLint 和定向 diff 通过。首次实际检查发现 28 位转化率被短精度解析拒绝，已修复并新增该实际响应回归；后续仅重跑受影响目标。
- 真实隔离样例：7 月 18 日累计销售额 US$999.94（2/18 天）、订购数 71（2/18 天）、退货数 3（1/18 天）；销售额较 17 日减少 US$660.00、−79.52%，转化率增加 9.77 个百分点。已实走指标切换、逐日表、返回原明细范围；1048/390px 截图已检查，390px 无整页横向溢出且所选点完整可见，无页面脚本错误。证据在 `D:/CLSEN_Data_Web-tmp/stage43-view/month-*`，不是正式发布门禁。
- 复体验入口：`http://127.0.0.1:18614/published-details/2025-07-18?return_to=%2Fledger%2Fpublished-details%3Ffrom%3D2025-07-01%26to%3D2025-07-31%26mode%3Drows`，账号和关闭方式沿用本批记录。操作：查看默认销售额 → 切换转化率/退货数 → 展开逐日表 → 返回发布明细；用户未明确确认前保持待体验。

这关闭了本页月内图表与导航反馈项；P0 商品分析、工作台/审核、全站图表体系（含 ECharts/Motion 适用项）和其余 CSS 收尾仍属后续 Stage 4.3，正式门禁留部署准备。

### 发布数据查看批次人工确认（2026-09-08）

用户明确表示“可以，体验通过进入下一阶段”。Run ID `d9f9e41881224205af5255261df23e88` 的发布数据查看、入口反馈、退货状态、月内趋势和共享导航均记为 `development_complete / user_verified`。不重复验证已确认部分；本次授权继续下一独立 Stage 4.3 批次 P0 产品总表/款式详情，不授权提交、合并或部署。

### Stage 4.3 P0 产品总表与款式详情（2026-09-08）

- 状态：`development_complete / user_verified`。版本 `codex/stage4-1-app-shell`、`ec0a72e + 未提交改动`。仅前端迁移与导航修复，未改后端、未新增迁移。
- 改动：7 个组件改用 CSS Modules、共享按钮/选择器/勾选/反馈/分页和 Token；补齐排序语义、日期下界、窄屏布局。详情规范化 URL、切换指标/维度及失效选择修复均保留总表来源；返回保留筛选和键盘焦点。保留原精确数值、缺失断点、零值、1–8 系列及来源安全合同。
- 验证：7 文件累计 13 项组件测试通过；最初返回焦点测试失败后修正，仅重跑受影响文件；新增详情指标切换测试的金额模拟数据修正后通过。TypeScript 和目标 ESLint 通过。隔离浏览器实走总表 → Standard 100 → 销售额 → 返回，焦点及日期保留；1280/390px 显示检查无整页溢出、无 pageerror。证据 `D:/CLSEN_Data_Web-tmp/stage43-view/product-path.cjs` 及 products/product-detail 截图。未运行完整构建、全量 E2E、MySQL 矩阵或 Collect。
- 入口：http://127.0.0.1:18615/products?from=2025-07-01&to=2025-07-18 。单独 Vite 进程启用 `VITE_PRODUCT_ANALYTICS_SOURCE=p0_catalog`，代理同一隔离 API `http://127.0.0.1:52635`。原 18614 保留 legacy_parser。两者不能视为生产切换。
- 前置条件：原 Run ID `d9f9e41881224205af5255261df23e88` 保持运行；同一主机已有登录 cookie 可复用。若需登录，使用 `D:/CLSEN_Data_Web-tmp/stage43-view/clsen-catalog-live-d9f9e41881224205af5255261df23e88/experience-credentials.json` 临时账号，不在文档写密码。实例包含此前人工体验成果，未重置数据。
- 人工体验：①打开入口查看 7 月 1–18 日产品总表；②点击 Standard 100 查看周期指标、趋势与实际变体；③切换销售额及颜色/尺码等比较维度，确认图表与逐日矩阵对应、缺报与零值区分；④点击“产品总表”，确认原日期/筛选保留并定位原产品。机器检查不替代本次体验确认。
- 环境生命周期：附加 Vite PID 11008，记录 `D:/CLSEN_Data_Web-tmp/stage43-view/products-vite.pid`。后续关闭前核实该 PID 命令行，另行停止本前端；原 runner 清理不会拥有此附加进程，原 API 停止后本前端不可用。本轮保持体验环境运行。
- 人工确认：用户于 2026-09-08 明确表示“体验通过”；对应 18615 入口与上述未提交版本。本次仅同步文档，沿用已有开发证据，不重跑测试。
- 余项：工作台/审核/高级发布及其余 CSS，图表坐标可读性、全站 ECharts/Motion 适用项。正式发布验证待部署准备，未提交、合并、部署或进入 Stage 5。

### Stage 4.3 日期表格与单日审核交接（2026-09-08）

- 授权：用户“继续下一步”。状态 `development_complete / user_verified`；代码位于 `codex/stage4-1-app-shell`、`ec0a72e + 未提交改动`，未新增后端或迁移，保留所有前批成果。
- 实际差距与改动：日期工作台/编辑表迁移 CSS Modules 与 Token；按钮、筛选、反馈、加载和分页复用共享组件。新增上一页/下一页，切换“只看修改”回第一页，搜索展示跟随 URL，初次读取失败可按原条件重试。固定操作栏改为工作台内 sticky，跟随实际内容宽度；保存中/待保存不再显示已同步，不允许带未保存或失败单元格跳往审核发布。
- 审核交接：原“运行检查/确认发布”仅滚动 `.advanced-review`，在已发布页实际滚向摘要。现打开 `/review-advanced/:reportDate`，携带报告类型与当前 version_id，并提供“返回日期表格”保留原路径/查询。按钮改为“前往发布”，实际校验、人工确认和发布继续由原审核界面执行；viewer 深链重定向只读页面。
- 日期缺陷：StrictMode 下重复站点配置请求迟到后把历史日期审核重置成今天；增加请求序号，仅最新站点上下文请求可更新状态，已通过历史日期双报告草稿与准确版本回归。
- 验证：DateWorkbenchPage 25、EditableDataGrid 3、App 38，累计 66 项目标测试通过；TypeScript、5 个受影响 TSX 的目标 ESLint 和定向 diff 检查通过。最初文案/测试选择器及类型问题修复后只重跑受影响目标。没有完整构建、全仓测试、完整 E2E、数据库矩阵或发布 Collect。
- 人工入口：http://127.0.0.1:18615/published/2025-07-18?report_type=business_report 。沿用 P0 入口的隔离 API、Run ID `d9f9e41881224205af5255261df23e88` 和临时账号；凭据获取位置、环境关闭方式见上批。当前运行已实时核实。
- 真实隔离路径：由 7 月 18 日经营报告发布 v1 创建修订 v2（version_id=4），编辑标题自动保存后撤销，当前标题恢复原值；进入审核精确定位 v2/7 月 18 日，再返回原表格。未执行日报发布，现有发布 v1 保留；修订 v2 留供体验。1280/390px 检查无整页横向溢出及 pageerror。证据 `D:/CLSEN_Data_Web-tmp/stage43-view/workbench-path.cjs`、`workbench-wide.png`、`workbench-narrow.png`、`review-draft-wide.png`。
- 体验步骤：①打开入口查看工作草稿 v2；②修改一处标题、移出单元格观察保存，再点“撤销上次修改”确认恢复；③使用列设置/搜索、切换报告类型；④回经营报告点“运行检查”，应进入 7 月 18 日经营草稿 v2 的审核页；⑤点“返回日期表格”，原筛选保留。已有审核页中的校验/人工确认/发布是独立操作，此次代理未替用户发布。
- 人工确认：用户明确表示“体验通过”，对应上述 18615 入口和未提交版本。本次仅记录人工确认，沿用已有定向开发证据，不推断用户执行了日报发布；正式发布验收仍待部署准备。
- 余项：单日审核内部表格、发布面板及批量审核的完整组件/样式迁移尚未完成，不能把本次交接修复视为所有审核页面完成。全站图表/CSS 收尾及正式发布门禁仍按原排程；未提交、合并、部署或进入 Stage 5。

### Stage 4.3 审核控件、发布确认与批量审核（2026-09-08）

- 用户授权“是，继续”。状态 `development_complete / user_verified`，版本 `codex/stage4-1-app-shell`、`ec0a72e + 未提交改动`，保留前批成果，无后端或迁移变化。
- 改动：ImportReviewFlow、ReviewDataTable、DraftReviewGate 复用 Button/Input/Select；保留表格单元格、排序与引用焦点所需原生控件。审核表、审核阶段、字段抽屉、问题卡与发布确认内容样式迁移到 ReviewWorkspace.module.css，颜色使用 Token；其他共用样式用明确 global 引用。最终发布确认改为共享 Dialog，包含焦点管理、Escape/关闭与返回；发布中拒绝关闭，发布说明和原版本/校验/权限合同保持。
- 批量审核：页面及四个展示子组件迁移 CSS Modules/Token；共享加载/失败反馈和返回版本记录入口。按 runId 建立独立组件生命周期，切任务清空旧结果、选择和已核对状态，旧任务迟到响应不覆盖新任务。恢复执行器、三项并发与人工确认合同未改。
- 验证：6 个受影响目标测试文件累计 44 项通过（ReviewDataTable 6、DraftReviewGate 8、ImportReviewFlow 16、BatchReviewPage 4、Recovery 5、Entry 5）；局部样式迁移后仅重跑审核表/闸门的 14 项。TypeScript、目标 ESLint、定向 diff 通过。测试覆盖精确字段/备注写入、草稿与跨日发布合同、退货快照重试、批量恢复与新任务隔离；这不是生产发布或完整验收。
- 实例：复用 Run ID `d9f9e41881224205af5255261df23e88` 与 18615 前端/52635 API；临时账号和关闭方式沿用前批。单日入口 http://127.0.0.1:18615/review-advanced/2025-07-18?report_type=business_report&version_id=4 。已实走搜索和打开字段源值/基础值/当前值抽屉，没有提交字段修改或发布。
- 批量体验：http://127.0.0.1:18615/review/batch/1 。使用同一隔离实例已知批次 1、3 创建预检 #1；服务端真实返回 2 项 recognition_uncertain，0 项可执行，预检停留 preview。选择/开始保持禁用是正确阻断，未伪造可执行结果；真实批量推进/恢复未在本轮执行，其局部合同由既有定向测试覆盖。
- 体验步骤：①打开单日入口，搜索 Existing；②点击 title 当前值，核对源值/基础值/当前值，关闭抽屉；③查看自动校验/人工确认区域，最终发布仍需独立确认；④打开批量 #1，核对两份文件的需人工处理原因、禁用选择和开始按钮；⑤点击后续处理链接进入对应报告。前端控件体验不要求用户实际发布。
- 显示证据：D:/CLSEN_Data_Web-tmp/stage43-view/review-batch-check.cjs、review-controls-wide.png、batch-review-wide.png、batch-review-narrow.png；批量 1280/390px 无整页溢出、无 pageerror。单日表格/字段抽屉桌面可用；最终发布对话框由组件测试验证，本轮未将真实草稿标为待发布来演示。
- 人工确认：用户明确表示“体验通过”，对应上述 18615 单日审核与批量预检入口、ec0a72e 加未提交改动。本次仅同步状态，沿用已有开发证据；不据此推断实际执行了批量推进或日报发布，正式发布验收仍待部署准备。
- 余项：审核外层、备注/来源等共用组件及旧全局 CSS 规则仍需定向收尾，图表/Motion/ECharts 适用项仍在 Stage 4.3；本批不能标记 Stage 4 整体完成。未运行完整构建、全量回归/矩阵/Collect，未提交、push、merge、部署或进入 Stage 5。

### Stage 4.3 审核外层与备注/来源组件（2026-09-08）

- 授权：用户“继续”；交付后用户明确确认“体验通过，继续进行下一步”。状态 `development_complete / user_verified`；工作树 `codex/stage4-1-app-shell`、`ec0a72e + 未提交改动`，保留已体验通过的所有前批成果。
- 迁移：审核日期轨、页头、日期状态、报告切换、审核/证据布局、批次备注与来源预览使用 ReviewSurfaces.module.css 和 Token；备注编辑、来源搜索/翻页按钮复用共享控件。源文件和不可变备注 API 合同未修改。
- 修复：SourceFilePreview 按 batchId/encoding 隔离缓存与请求结果，调用方无需自行提供 key；搜索后保留原数据行序号，避免筛选结果重新编号误指证据。BatchNotePanel 按 batchId 隔离加载结果、备注列表、编辑草稿与操作键。
- 目标证据：App 38、DraftReviewGate 8、ImportReviewFlow 16、BatchNotePanel 3、SourceFilePreview 2，累计 67 项通过；TypeScript、受影响 TSX 目标 ESLint、定向 diff 通过。新增原行号与跨批次隔离检查；没有完整构建、全量回归、MySQL 矩阵或发布 Collect。
- 入口：http://127.0.0.1:18615/review-advanced/2025-07-18?report_type=business_report&version_id=4 。沿用 Run ID `d9f9e41881224205af5255261df23e88`、已有临时账号与原隔离 API，环境关闭方式见前批。源表预览仍位于导入识别阶段，不能把草稿页面字段对照当作完整源表预览。
- 实际检查：历史草稿 v2 的批次 #3 备注展开、临时输入/清空（未提交），日期轨切换 7 月 17 日正确；桌面与 390px 无整页横向溢出、无 pageerror。证据 `D:/CLSEN_Data_Web-tmp/stage43-view/review-surfaces-check.cjs`、review-surfaces-wide.png、review-surfaces-narrow.png。来源切换/筛选与备注追加修订由目标组件测试覆盖，本轮没有新增导入或写入备注。
- 人工体验：①打开入口，查看日期轨/经营与退货状态；②下滚到“原始批次”，点击“管理批次备注”；③输入临时文本并清空，确认展开/收起与禁用状态；④切换日期轨 7 月 17/18 日，检查对应日期和报告状态。来源预览可在下一次正常导入识别时体验；未提供新上传样例或声称真实导入链已重跑。
- 余项：本批体验；按页面登记核对尚有调用者的全局样式与旧规则清理、图表/Motion/ECharts 适用项。抽出的旧全局规则暂保留以兼容其他调用者，不能宣称全站 CSS 清理已完成。正式发布验证仍待部署准备；未提交、push、merge、部署或进入 Stage 5。

### Stage 4.3 产品趋势坐标与技术适用性收尾（2026-09-08）

- 授权：用户在审核外层体验通过后要求继续；交付后明确确认“体验通过”，并要求 UI 与动画后续再优化。状态 `development_complete / user_verified`；基线仍为 `ec0a72e + 未提交改动`。
- 页面登记核对：`/versions` 与 `/admin` 已由 Stage 3 蓝白视觉批次覆盖并获验收，不重复迁移；月内趋势已有精确纵轴、首/中/末日期刻度和逐日表格。实际缺口位于 P0 款式详情的多系列 SVG：固定 viewBox 在窄屏缩小了坐标文字，且缺少纵轴数值、横轴日期和独立文字图例。
- 实现：产品趋势新增三档精确纵轴、首/中/末日期刻度、网格线和颜色/线型/文字图例；ResizeObserver 让 viewBox 跟随容器宽度，390px 下保持 11px 刻度字号。跨系列按日期索引对齐，缺报仍断线，decimal 继续先转 BigInt，坐标和标签不从浮点值反推业务数据。
- 技术选择：本批不引入 Motion 或 ECharts。当前交互只需 CSS 状态反馈；两张业务趋势图已有 SVG、精确 BigInt/decimal 路径、文字摘要和表格后备，引入 ECharts 会增加 bundle、Number 精度与无障碍适配成本，没有形成更好的当前使用路径。
- CSS 调用者核对：`styles.css` 中 `main-content`、`form-error`、`section-kicker`、`workspace-loading`、`quiet-action` 等仍被 App/ImportReviewFlow 调用；SafeSourceRef 与 DataTable 各自仍有共享调用者，VersionHistory、AdminConsole 和 Catalog 样式分别属于已验收或暂停重复迁移的页面。因而只保留有调用者的兼容规则，本批不为清零文件数机械删除。
- 定向验证：ProductTrendChart 3、TrendPointMatrix 1、ProductDetailPage 2，共 6 项通过；TypeScript、目标 ESLint、`git diff --check` 通过。真实 390px 隔离页中图表渲染宽度与 viewBox 同为 348px，刻度字号 11px，显示 0/13/27 与 07-01/07-09/07-18；无整页横向溢出、无浏览器 error。
- 人工入口：http://127.0.0.1:18615/products/2?from=2025-07-01&to=2025-07-18&metric=units&dimension=color&return_basis=event_date&fact_basis=current 。①查看每日趋势纵轴、日期刻度与 RED/BLUE/GREEN 图例；②切换销售额和转化率，确认刻度格式；③切换比较维度，确认图例与曲线对应；④对照下方逐日矩阵，确认 7 月 17/18 日数值和缺报断线。机器检查不能替代本次体验确认。
- 人工确认：用户已在销售额、转化率与颜色比较等入口完成体验并明确表示通过。本批不再等待体验；后续 UI 与动画优化单独排期，不反向重开本批。
- 余项：其余仍有调用者的全局兼容样式按下一条完整使用路径处理。正式发布验证待部署准备；未提交、push、merge、部署或进入 Stage 5。

### Stage 4.3 新建导入入口与证据链（2026-09-08）

- 授权：用户在产品趋势体验通过后要求“进行下一步”，并在实走五步证据链、生成草稿和校验后明确确认“体验通过”。状态 `development_complete / user_verified`；基线为 `ec0a72e + 未提交改动`。
- 实际差距：空日期进入审核后，“上传原表”任务栏、五步证据链、新建导入说明和 CSV 选择区仍依赖 `styles.css` 的页面级规则。这些类只有 ImportReviewFlow 调用，适合从兼容层独立迁出。
- 实现：新增 ImportEntry.module.css，使用设计 Token；迁移 import-workflow、review-taskbar、custody-chain、intake-panel 和 file-drop。证据链当前阶段增加 `aria-current="step"`，空入口指向“原始文件”，发布完成指向“发布版本”。从 `styles.css` 删除对应唯一调用者规则，保留仍被其他审核组件调用的字段、错误、按钮和后续识别/解析样式。
- 定向验证：ImportReviewFlow 16 项、App 38 项通过；迁移后 TypeScript、目标 ESLint、Token policy 4 项和 `git diff --check` 通过。旧类名断言改为当前步骤语义断言；没有新增业务测试、完整构建、全前端测试、E2E 或数据库检查。
- 实际检查：390px 隔离页表单宽 358px，无整页横向溢出、无浏览器 error；五步证据链在自身区域横向滚动。未选择文件，保存按钮保持禁用；没有上传、导入或写入数据。
- 人工入口：http://127.0.0.1:18615/review-advanced/2025-07-16?report_type=business_report 。①查看“上传原表”任务栏和五步证据链；②横向滚动证据链查看五步；③核对归属日为 2025-07-16；④聚焦 CSV 选择区，确认未选文件时保存按钮禁用。无需选择真实文件或提交表单。
- 体验反馈修正：用户走到解析基线后要求必填原因不再为空，并自动携带当前操作用户且有可信来源。前端现从已认证 Principal 生成“操作人、操作、来源”三段式默认说明；生成草稿包含报告日、报表类型、导入批次和原始文件，旧人工说明作为补充说明保留。审核确认、草稿移动/废弃、发布说明、字段修改/恢复、新增/排除行及逐项重复记录决定复用同一规则。页面明确标注身份来自当前登录会话；后端既有命令仍从 Principal 绑定 `actor_user_id`，不接受前端自报用户作为权威身份。定向验证为 ImportReviewFlow 17、DraftReviewGate 9、ReviewDataTable 7、MergeDecisionMatrix 3，共 36 项通过；TypeScript、目标 ESLint 与相关 diff 检查通过。实际 18615 页面核对 Catalog Live Admin、用户 #1、批次 #4、原始文件及旧人工补充说明同时显示；用户随后生成草稿、运行当前草稿校验并核对汇总指标，阻断项和警告均为 0。
- 反馈复体验入口：http://127.0.0.1:18615/review/2026-07-01 。确认“生成草稿原因”已有当前操作人、报告/批次/文件来源及原补充说明；用户可直接使用或补充修改，再自行决定是否生成审核草稿。
- 余项：正式发布验证待部署准备；未提交、push、merge、部署或进入 Stage 5。

### Stage 4.3 识别确认、解析基线与导入队列（2026-09-08）

- 授权：用户确认新建导入入口与默认审计说明体验通过后要求继续，交付后明确确认“体验通过继续下一步”。状态 `development_complete / user_verified`；基线为 `ec0a72e + 未提交改动`。
- 实际差距：`ImportReviewFlow` 的批量导入队列、人工识别确认、日期差异、解析基线和发布完成回执仍使用页面级全局类；这些类只有该流程调用，但部分规则与 `DraftReviewGate` 的工作台标题和发布回执共用选择器，不能整段删除。
- 实现：队列、识别确认、日期差异和解析基线迁入既有 `ImportEntry.module.css`，动态队列状态改为模块类组合，队列末端主操作增加局部定位类；旧全局规则已精确删除，共享选择器拆分后保留工作台、发布回执及其他调用者。业务逻辑、接口、草稿和默认审计说明均未改变。
- 定向验证：ImportReviewFlow 17 项、TypeScript、目标 ESLint、设计 Token 策略和相关 `git diff --check` 通过。未运行完整前端测试、完整构建、E2E、MySQL 矩阵、Collect 或正式发布验收。
- 实际检查：18615 隔离实例仍可读取 2026-07-01 日期页，页面恢复为已发布经营报告与未导入入口，五步证据链和 CSV 选择区正常呈现，未自动上传、导入或创建业务记录。
- 人工入口：http://127.0.0.1:18615/review/2026-07-01 。①在页面下方查看“上传原表”与五步证据链；②如需完整体验，可选择一份 CSV，核对批量队列和“人工确认识别结果”；③检查报表类型、所属报告日、编码与识别规则；④确认解析后核对绿色“不可变解析基线”区域，并在生成新草稿前停止。上传会新建导入批次，应使用可接受的体验文件并由用户本人决定是否执行。
- 余项：正式发布验证待部署准备；未提交、push、merge、部署或进入 Stage 5。

### Stage 4.3 目标日期冲突与逐行重复记录决定（2026-09-08）

- 授权：用户确认识别/解析/队列体验通过后要求继续；完成五轮排版反馈后又明确表示“体验通过，进行下一步”。状态 `development_complete / user_verified`；基线为 `ec0a72e + 未提交改动`。
- 实际差距：生成草稿时的目标日期冲突和草稿改期冲突共用 `target-conflict` / `target-choice` 全局规则；两条路径都可进一步进入 `MergeDecisionMatrix`，其目标/来源逐行对照仍依赖 `styles.css`。这是同一个业务决定路径，适合一并迁移。
- 实现：新增 `ReviewDecision.module.css`，集中承载冲突选择卡、目标版本摘要、选中/禁用状态、窄屏操作按钮和逐行重复记录矩阵；`ImportReviewFlow`、`DraftReviewGate` 与 `MergeDecisionMatrix` 统一使用局部模块类。旧全局规则已删除；合并/替换/取消合同、默认审计说明和后端命令均未改变。
- 体验反馈修正：真实 24 对冲突原先全部展开，页面超过 22,000px，长商品标题在窄列中进一步拉高页面。矩阵现固定每页 4 对，顶部显示总数与已完成数；可为当前页选择统一处理方式并只应用到未完成项，翻页时保留已有决定。每条记录仍生成独立默认审计原因，包含当前操作人、目标版本、目标行号和来源行号。摘要中的长字段最多显示 3 行，完整内容仍通过“查看两行的全部字段”展开。
- 第二次体验反馈修正：后端实际以业务键交集生成完整目标行 × 来源行矩阵；经营报告业务键为 `child_asin + sku`，退货报告业务键为 `return_date + order_id + sku + asin + fnsku + quantity + license_plate_number`。因此两行所有字段完全一致时仍是合并时需要明确去重的重复副本，并非数值异常。界面已将“冲突”改称“重复记录”，直接展示当前报告的判定规则；相同字段只显示一次并标记“两侧相同”，差异记录显示不同字段数量。
- 布局修正：解析基线改为紧凑的图标、摘要和改期操作页头，草稿原因与决策区使用整行宽度；宽屏每页 4 组按 2×2 卡片排列，较窄视口回到单列。每张卡的处理方式和决定依据并排，继续使用既有 Token、控件和审计合同。
- 第三次体验反馈修正：决定依据输入框原先受网格最小列宽和长默认审计说明影响，越过并排卡片右边界。现将第二列改为可收缩轨道，并为标签、输入框和选择框设置可收缩宽度；长说明未聚焦时省略显示，聚焦后仍可完整查看和编辑，没有截断提交值。
- 第四次体验反馈修正：草稿数据表外层现在限制为工作区宽度，横向滚动只发生在表格区域；工具栏在 1200px 以下改为上下排列，分页允许换行。审核步骤去掉 330px 强制高度，版本备注占整行，草稿校验与确认校验结果并排，相关标题、说明和改期/处置入口文字同步精简。证据侧栏中的批次备注在 310px 宽栏内改为两列摘要和整行按钮，避免标题与按钮逐字竖排。
- 第五次体验反馈修正：把导入队列、草稿页头和数据工具栏作为连续工作区收紧。队列缩小内边距、间距和标题；草稿页头迁入 ReviewWorkspace.module.css，状态标记与标题层级集中呈现；数据标题和新增操作同排，搜索/字段/行状态占第一行，差异开关与导航占第二行。旧 `draft-workbench`、`workbench-heading` 和 `state-stamp` 全局规则已删除，并一并修复该旧段缺少闭合花括号造成的 CSS 解析边界问题。
- 定向验证：ImportReviewFlow 17、MergeDecisionMatrix 4，共 21 项通过；TypeScript、3 个目标 TS/TSX 的 ESLint、CSS 尾随空白/结尾换行和相关 `git diff --check` 通过。第三次修正仅涉及局部 CSS，按项目规则做真实页面显示与差异检查，未重复运行组件测试。未运行完整前端测试、完整构建、E2E、MySQL 矩阵、Collect 或正式发布验收。
- 第四次反馈定向验证：DraftReviewGate 9、ReviewDataTable 7，共 16 项通过；TypeScript、4 个目标 TS/TSX 的 ESLint 和相关 `git diff --check` 通过。浏览器只读测量中视口 1592px、页面客户区和滚动宽度均为 1577px；草稿数据区宽 956px，表格内容宽 3796px 但滚动容器仍为 956px，整页不再横向溢出。未点击校验、确认、改期或处置按钮。
- 第五次反馈定向验证：DraftReviewGate 9、ReviewDataTable 7，共 16 项通过；TypeScript、2 个目标 TSX 的 ESLint 和相关 `git diff --check` 通过。1048×912 只读浏览器测量中页面客户区和滚动宽度均为 1033px；数据工具栏由 304px 收紧至 242px，导入队列由 181px 收紧至 155px。未触发业务写操作。
- 实际检查：18615 的 2026-07-01 草稿 v2 页面显示紧凑的版本备注、校验草稿和确认校验结果；宽表滚动条保留在表格内部，右侧批次备注恢复正常横排。页面继续保留 24 组重复记录的分页、业务键说明、字段相同状态和完整审计值。检查期间未发送最终决策或其他写命令。
- 人工入口：http://127.0.0.1:18615/review/2026-07-01 。①刷新当前页，确认浏览器底部不再出现整页横向滚动条；②在草稿表内横向滚动，确认只移动表格；③查看“版本备注—校验草稿—确认校验结果”的紧凑布局和右侧批次备注；④如需复核重复记录，返回对应冲突区翻页查看，不要点击最终生成、校验、确认、改期或处置按钮。
- 人工确认：用户已确认第五次草稿工作区排版修正版体验通过；重复记录决定、分页、业务键解释、宽表内部滚动和紧凑审核步骤均记为 `user_verified`。不重复验证已确认部分。
- 当时余项为草稿工作台改期/处置和发布回执等仍有调用者的全局兼容规则；该余项已由下一批收尾。正式发布验证仍待部署准备；未提交、push、merge、部署或进入 Stage 5。

### Stage 4.3 草稿维护与发布回执收尾（2026-09-08）

- 授权：用户确认上一批体验通过并要求进行下一步；交付后又明确表示“体验通过”。状态 `development_complete / user_verified`；基线为 `ec0a72e + 未提交改动`，保留此前所有未提交成果。
- 实际差距与实现：`DraftReviewGate` 的改期、重新解析/废弃、校验状态、发布闸门与发布回执仍使用页面级全局规则。现已迁入 `ReviewWorkspace.module.css`，状态与计数颜色使用局部模块类；冲突决定最终操作改用共享 Button。移动原因改为三行文本框，可完整查看自动带入的当前用户与草稿来源。
- 入口收紧：“调整草稿日期”和“重新解析或废弃草稿”使用同名 details 折叠组，同一时间只展开一项，减少长页面占用；原权限、确认、审计说明及服务端写入合同未变。
- 定向验证：DraftReviewGate 9 项、TypeScript、目标 ESLint 与相关 `git diff --check` 通过。409×758 真实浏览器只读检查中，页面客户宽度/滚动宽度为 394/394px；展开重新解析/废弃后，调整日期自动收起。检查期间未执行校验、确认、改期、废弃或发布。
- 人工入口：http://127.0.0.1:18615/review/2026-07-01 。①下滚到“确认校验结果”；②展开“调整草稿日期”，确认移动原因完整可见；③展开“重新解析或废弃草稿”，确认前一项自动收起；④核对处置原因中的当前操作人和草稿来源，不勾选确认或执行任何提交按钮。
- 人工确认：用户已明确确认本批体验通过。至此 Stage 4.3 页面登记内的开发批次与人工体验全部完成，当前阶段状态为 `development_complete / user_verified`。正式发布验收仍留部署准备；未提交、push、merge、部署，Stage 5 尚未启动。

## 交付与验证待办

| 项目 | 状态 | 只阻塞什么 | 下一步 |
| --- | --- | --- | --- |
| Stage 4 真实数据试用与反馈修订 | 日报查看 user_verified；商品建档/产品分析待体验，整体未完成 | 本次真实业务结论及 Stage 5；首个目录待业务确认，F-01 重试权限未修复 | 按本次入口卡体验并反馈，不扩大验收 |
| Stage 4.3 页面迁移全部批次，ec0a72e + 未提交改动 | development_complete / user_verified | 正式发布验收及尚未授权的整合 | Stage 4.3 开发与人工体验已全部完成；Stage 5 尚未启动 |
| Stage 4.3 目标日期冲突与逐行重复记录决定，ec0a72e + 未提交改动 | development_complete / user_verified | 正式发布结论与整合 | 五轮排版反馈已确认；保留现有成果 |
| Stage 4.3 识别确认、解析基线与导入队列，ec0a72e + 未提交改动 | development_complete / user_verified | 正式发布结论与整合 | 用户已确认体验通过 |
| Stage 4.3 新建导入入口与证据链，ec0a72e + 未提交改动 | development_complete / user_verified | 正式发布结论与整合 | 用户已生成草稿、运行校验并确认体验通过 |
| Stage 4.3 产品趋势坐标与技术适用性收尾，ec0a72e + 未提交改动 | development_complete / user_verified | 正式发布验收与整合 | UI/动画后续单独优化；继续剩余全局兼容样式调用路径 |
| Stage 4.3 审核外层与备注/来源组件，ec0a72e + 未提交改动 | development_complete / user_verified | 正式发布验收与整合 | 后续 CSS/图表适用项 |
| Stage 4.3 审核控件/发布确认与批量审核，ec0a72e + 未提交改动 | development_complete / user_verified | 正式发布验收与整合 | 后续外层/共用样式及图表适用项收尾 |
| Stage 4.3 日期表格与单日审核交接，ec0a72e + 未提交改动 | development_complete / user_verified | 正式发布验收与整合 | 后续审核内部表格/发布面板与批量审核迁移 |
| Stage 4.3 发布数据查看首批及反馈修正，ec0a72e + 未提交改动 | development_complete / user_verified | 正式发布验收与整合；不阻塞独立页面开发 | 已确认；保留现有成果 |
| Stage 4.3 P0 产品总表与款式详情，ec0a72e + 未提交改动 | development_complete / user_verified | 正式发布验收与整合 | 下一批工作台/审核；不重复本批 |
| 商品主档专项 R/A/B1/B2/C/D，基线 ec0a72e + 未提交改动 | development_complete / user_verified；D 于 2026-09-08 明确确认体验通过，详见专项交付记录 | 正式发布验收及尚未授权的整合/部署；不阻塞独立页面开发 | 下一次开发核对剩余 Stage 4.3 页面，不重做专项 |
| Stage 4.2② 商品卡与来源只读闭环及 R 反馈修正，基线 ec0a72e | development_complete / user_verified | 正式发布结论；代码尚未提交或整合 | 保留现有成果，不重复验收 |
| Stage 4.2① 商品候选任务恢复，基线 ec0a72e | development_complete / user_verified；定向检查与人工体验完成 | 正式发布结论；代码尚未提交或整合 | 保留现有未提交改动，不重复验收 |
| Stage 4.1 应用外壳与公共页面，基线 ec0a72e | development_complete / user_verified；定向检查与人工体验通过 | 正式发布结论仍待部署准备；代码尚未提交或整合 | 保留现有未提交改动，不重复验收 |
| Stage 3 UI 基础体系，28684cf，PR #9 | accepted / merged_to_stage2_branch；development_complete、user_verified；当前 PR 检查通过，MySQL 8.4 按策略跳过 | master 整合与发布仍待相应授权；正式部署完整测试待部署准备 | PR #9 已合入 Stage 2 分支（ec0a72e）；商品主档专项已完成开发与体验，后续接续剩余 4.3 |
| Stage 2 Worker 可观测性，组合候选 c924e4a | accepted；六文件增量合同、复用证据、增量门禁与最终部署验证均已核对 | 仅阻塞尚未授权的发布、真实数据库迁移、push 和 merge | 保留分支与透明组合证据；后续 Stage 3 已合入 Stage 2 分支，master 整合仍待指令 |
| Stage 2 Worker 管理页面人工体验，版本 55a5b29（已整合至 c924e4a） | user_verified；已纳入 Stage 2 accepted 结论 | 无 | 后续 UI 改动若改变已确认体验，再仅对受影响部分邀请复体验 |
| 开发验证脚本的真实 MySQL 路径 | 待下一次相关数据库任务验证 | 宣称新开发模式已经完成容器联调 | 仅用可抛弃 MySQL 8.0 定向联调一次，不为此追加完整矩阵 |
| GitHub CI 与部署门禁分层 | 尚未迁移；PR 仍跑 Ubuntu full、Windows smoke、Frontend full、MySQL 8.0，master push 还跑 MySQL 8.4 | 宣称远端 CI 已按改动范围快检；不阻塞本地独立功能开发 | 在调整远端 CI 的任务中统一修改 compatibility.yml、必需检查聚合、release-gates.yml 和 verify-release-source.ps1，保留上线前完整覆盖和可信来源校验 |

后续待办沿用四项记录：事项、风险/阻塞范围、最小验证命令、安排时点。无需为常规验证待办生成新审批单。

CI 迁移须在下一次希望缩小 PR 检查范围前安排，或纳入部署准备任务。本地策略不能改变 GitHub 自动触发行为；目前发布来源校验要求指定 master SHA 的成功 push 兼容运行及 `master-required`，不能只删任务或把跳过写成成功。迁移时先定位现有来源校验测试节点并验证成功、失败和伪造来源的拒绝路径，再安排工作流联调；本次文档优化不启动远端运行，也不改变分支保护配置。

## 对外报告

每轮只报告：本轮交付的功能、实际做过的必要检查、人工体验入口与步骤（就绪时）、仍影响使用或发布的限制。明确区分“待你体验”“你已确认通过”和机器验收结果。状态查询不启动测试。用户说“继续”时推进已授权工作，避免把对话全部用于等待和汇报测试。

每批交付另用一行说明实际使用的 Skill 及用途，或写“本批无需 Skill”。仅记录实际读取并应用的指导；Vitest、浏览器和截图等工具使用不能代替 Skill 使用记录。不推测补记历史，不另建台账。


## Stage 4 真实数据试用准备 review-01（2026-09-08）

用户已明确授权 data/ 外的本地脱敏副本及独立测试库写入，确认同一美国站账号。用户现已确认 review-01 日报查看正确、体验通过，日报查看记为 `user_verified`；商品建档与产品分析仍待体验，真实数据试用整体未完成，正式 `release_validation` 待部署准备。旧 Stage 4 合成体验结论保留，Stage 5、生产/供应链、11A/11B 不推进。

- 工作树复核：`codex/stage4-1-app-shell`，HEAD `ec0a72e907cf7787536cf73964f7897485e28c97`，107 个已跟踪变更状态项及明确代码目录下的未跟踪成果均保留。独立代码快照和哈希在 D 盘任务目录；业务代码未修改，未提交或整合。
- 环境：`D:/CLSEN_Stage4_RealDataReview/review-01-20260908`，Run ID `c8064cc8c42c4fe7823cd1c1f336697e`；前端 `http://127.0.0.1:46638`，API `http://127.0.0.1:30250`，独立 MySQL 8.0.46/schema 0027、Worker、D 盘存储/临时目录/缓存。运行器仅初始化账号，不载入合成业务样例。停止/恢复已核对保留同一库、14 份发布和目录草稿；不是备份恢复演练。
- 样本：7 月 1–7 日、14 份完整日报、260 行；经营 175 行/257 件，退货 85 行/85 件。按洛杉矶时区核对归日，不截取商品行。原件与副本 SHA-256 复核一致；用户已确认脱敏，未外传数据、读取项目根 data/ 或连接业务数据库。
- 检查：14 份解析、应用内校验和测试发布；逐日行数、销售件数/金额、退货数量与独立 CSV 汇总一致。viewer 日报读取成功，上传和用户管理返回 403；管理账号 4 个入口可用、无页面脚本错误。未完整回归、全量 E2E、双版本矩阵或发布验收。
- 限制：目录候选 27 款/107 SKU 与映射，标准名、内部 SKU、身份决定待业务确认，尚无批准目录，P0 按款式分析暂不能体验。自然行级重复冲突样本未覆盖；同文件重复上传已拦截。
- F-01：解析同操作重试在 `parse_operation_tokens SELECT FOR UPDATE` 被运行权限拒绝。首份因快照资源遗漏失败的批次用任务初始化身份经既有解析服务恢复，其余 13 份正常 API 导入；运行账号权限未放宽，缺陷未修复，不能把恢复记作重试权限通过。安排真实试用反馈修订，修复时只做该分支及不可变性相关目标检查。
- F-02：初次建档 241 条必填提示导致页面较长，已记录待用户反馈，未改 UI。最初漏带的后端 Unicode 标准资源已补入快照哈希，不涉及项目根 data/。

入口卡、3–5 步操作、临时账号获取方式及保留现场的停止方式见任务目录 `体验入口.md`；凭据仅保存在受限任务目录，不进入仓库。用户已确认本版本日报查看通过；此确认不扩展到商品建档、产品分析、写入流程或整轮真实数据试用。

### review-01 日报查看人工确认（2026-09-08）

用户明确反馈“目前日报可查看是正确的，体验通过”，日报查看记为 user_verified，范围为上述 Run ID、2026-07-01 至 07-07 授权样本。商品建档、产品分析、导入审核/重复处理及写入流程不据此判定通过；F-01 继续保留。用户要求后续避免“入口打开却无数据”的交付情况，已写入 AGENTS.md：逐功能交付数据、角色、前置条件和可体验状态。此次仅更新文档和入口卡，不改运行环境、不重跑测试、不进入 Stage 5。

## review-01 初次商品建档建议（2026-09-09）

2026-09-09 继续初次商品建档：恢复同一 Run ID/端口和既有现场；草稿 #1 已补齐 27 款名称建议、107 原 Seller SKU 内部编码及一对一映射（241 项），分类保留待分类。应用校验无 issue，workflow_revision=3，已提交待批准，预览普通风险、134 行。多标题 6 款的候选差异见任务目录 `商品建档建议.md`。本轮仅草稿建议 `ready_for_user_review`，没有批准首个目录；已发布商品主档与产品分析仍未就绪。日报 user_verified 保持，F-01 未修复。不改代码、不重跑日报或完整回归。

依据：授权副本逐条核对，107 Seller SKU 与候选款号/颜色/尺码完全相符，每个在所选报告中仅对应一个子 ASIN。名称优先经营报告高频标题，无经营来源则用退货；只移除 US 变体尾注，候选差异保留供业务审阅，不推断正式分类。草稿写入前复核 revision=0，无用户修改；原建议为空。通过应用决策/校验/提交/预览接口，不直接写业务表。入口 `http://127.0.0.1:46638/catalog/imports/1`，完整账号 `review01-data-manager`；用户可审阅、修改、重新校验并最终批准，审批前不把商品列表或产品分析记就绪。

### review-02 批准预览最小修复与建档交付（2026-09-09）

2026-09-09 建档代码更新为 review-02，沿用原 Run ID、端口和现场。修复 F-03：相同草稿/审核人使用新请求重新生成批准预览时，摘要重复导致唯一键冲突；摘要加入预览 operation token，新请求有独立生命周期，同 token 继续幂等重放，内容 diff 摘要不变，无迁移。只改 backend/app/catalog/import_repository.py 与已有 test_catalog_import_workflow.py。正式脚本 MySQL 8.0、DevelopmentTests 指定该文件和 test_catalog_approval.py，共 6 项通过；实际页面取消“仅看待处理”后显示 27 行建议，预览 HTTP 200、普通风险/134 行、确认批准按钮可见，无 pageerror。用户尚未批准目录，商品主档/产品分析仍未就绪；建档建议 ready_for_user_review。日报 review-01 user_verified 保留，不重跑无关检查；F-01 仍未修复，未完整回归、提交、整合、部署或进入 Stage 5。

证据：任务目录 preview-fix-check.log、catalog-proposal-ui-check.json、source-manifest.json；草稿建议及完整操作见 商品建档建议.md。首次商品建档仍待用户业务确认，预览不等于批准，不把“27/27 已填”写成 user_verified。

### 2026-09-09 review-03：候选值转手动编辑（F-04）
用户反馈：选择“手动输入其他值…”希望基于当前候选文字编辑。已取消切换时清空值，以及根据输入值自动切换模式的 effect；手动输入保留原值，清空/输入匹配候选值时保持输入框，仍需“保存此行”才写入。修改位于 stage4-1-app-shell 的 CatalogImportSectionTable.tsx，并同步原试用实例 source，版本 review-03；保留数据库、Run ID 与端口。入口 http://127.0.0.1:46638/catalog/imports/1，使用 review01-data-manager。
定向验证：正式 run-dev-check 指定组件文件被 pnpm 依赖检查阻断；未重装依赖，使用现有 node node_modules/vitest/vitest.mjs run src/features/catalog/CatalogImportSectionTable.test.tsx --bail=1，同一目标 6 项通过；git diff --check 通过，原入口 Vite 返回更新模块 HTTP 200。development_complete / ready_for_user_review，待用户复体验；日报既有 user_verified 保留。未完整回归、提交、合并、部署或进入 Stage 5。

### 2026-09-09 review-04：字段清空与完整名称显示（F-05）
已按用户反馈添加字段 × 清空按钮，清空仅修改行内草稿，仍需保存此行；标准商品名称采用自动增高 textarea，名称列加宽，候选模式下方完整换行显示所选名称。保留 review-03 的候选转手动保值行为。代码/样式同步原试用实例，数据库与端口不变。组件 6 项定向测试、相关 TSX ESLint 通过；实际 1266px 页面截图确认完整名称、× 与相邻列无重叠；未保存任何试验性编辑。沿用现有 Vitest 直接运行目标，避免已知 pnpm 依赖重装检查。development_complete / ready_for_user_review，未完整回归、提交、整合、部署或进入 Stage 5。

### 2026-09-09 review-05：审核区响应式布局（F-06）
用户标注反馈六列缩窄挤压、款号/状态/保存文字裁切。按 Product Design 现有产品与标注范围指导，沿用现有 tokens 和 Button，将款式审核行改为分区网格：来源/款号、名称、状态/保存、独立修改说明。按审核面板可用宽度的 container query 切换上下布局，避免只按窗口断点判断；输入/选择/清空控件统一尺寸，修改说明自动增高，保留手动编辑、清空、保存行为。没有重建应用或调用外部服务传输数据。
已同步同一 Run ID、端口、数据库的 review-05。现有 CatalogImportSectionTable/CatalogImportPage 共 8 项定向测试通过，组件 ESLint 与定向 diff 检查通过。实际浏览器 1592/1048/720/390 宽度检查，390 下 54 个 textarea 均未裁切、页面无横向溢出；检查后恢复默认浏览器尺寸，未写入测试性修改。development_complete / ready_for_user_review，等待用户复体验；日报 user_verified 保留。未完整回归、提交、整合、部署或进入 Stage 5。

### 2026-09-09 review-06：压缩审核卡片留白（F-07）
用户认可卡片分隔，但反馈留白过多。保留卡片与响应式断点；桌面三行网格改两行，将款号/说明/保存对齐，减小卡片间隔/内边距，textarea 初始一行并按实际文字增高。同步原试用实例 review-06，数据/端口不变。实际 1592/1048/390 宽度检查，宽屏首卡约 193px；390 下 textarea 无裁切、页面无横向溢出，恢复默认尺寸。定向 diff 检查通过，纯显示调整未重跑业务测试；review-05 的 8 项行为检查作为既有证据引用，不声明本版重新执行。ready_for_user_review，未写入数据、完整回归、提交、整合、部署或进入 Stage 5。

### 2026-09-09 review-07：校验与批准操作区（F-08）
按用户 Product Design 标注优化工作流布局，采用现有 Button，突出预览/确认主操作，步骤紧凑编号展示，撤回等为次操作；rebase 收入“高级操作 · 调整目录基准”原生展开区，输入与按钮统一。保留服务器权限、修订与预览失效、批准条件。CatalogWorkflowActions 现有 3 项目标测试、相关 ESLint、定向 diff 检查通过；实际 1592/390 宽度及高级区展开检查，窄屏无横向溢出。未触发预览/批准/撤回/rebase，原数据和端口保留，同步原试用实例 review-07，ready_for_user_review。未完整回归、提交、整合、部署或进入 Stage 5。

### 2026-09-09 review-08：顶部、SKU 标准化与侧栏账号（F-09）
按用户三处标注压缩审核顶部标题/返回导航/进度留白，SKU 标准化采用紧凑分区卡片，完整展示内部 SKU，颜色/尺码候选直接显示值，说明独占宽行。账号区 flex 剩余宽度、文字省略、头像/退出不压缩，修复退出与角色文字重叠。原 API/权限/保存流程不变。
CatalogImportPage/SectionTable 8 项定向测试与相关 ESLint 通过（之后仅调整候选展示文字及 CSS）；定向 diff 检查通过。实际 1592/1048/390 宽度检查，1048 账号/退出边界无重叠，390 页面和表格无横向溢出、textarea 无裁切。已同步原现场 review-08，恢复浏览器默认尺寸；未执行保存/退出/批准或其他数据写入。ready_for_user_review，保留日报 user_verified，未完整回归、提交、整合、部署或进入 Stage 5。

### 2026-09-09 review-09：SKU 层级、映射与证据（F-10）
用户继续反馈 SKU 排版并要求映射/来源证据统一优化。SKU 卡片顶部显示已有内部 SKU 与可读来源颜色/尺码，编辑字段统一对齐，移除重复预览；映射卡片突出来源/目标/决定，归属冲突展开区就近移至对应卡片；证据为编号、安全预览/摘要和查看完整标识按钮的紧凑列表，仍使用原 reveal 权限服务与安全渲染，明确当前仅加载最多50条。不改变导入/保存/批准规则。
SectionTable/EvidencePanel/IdentityOwners 8 项目标测试通过，相关 ESLint 与定向 diff 检查通过。实际宽屏核对三个页签，390 下映射/证据无横向溢出，未点击 reveal、保存或批准。同步原试用实例 review-09，恢复浏览器尺寸；ready_for_user_review，数据现场保留，未完整回归、提交、整合、部署或进入 Stage 5。

### 2026-09-09 用户确认与导航排查待办（F-11）
用户明确表示“目前的体验通过，注意后续体验完成需要对所有的导航遗漏进行排查”。当前 review-09 商品建档审核界面及本轮 UI/交互修订标记 user_verified，覆盖 review-03 至 review-09 对应界面待复体验状态；日报既有确认保留。不据此推断目录业务内容确认/批准、产品分析体验或整体试用完成。
整体体验完成后，集中排查本次试用所有功能的导航遗漏：菜单/列表入口、已有审核批次继续处理、返回与跨页路径、不同角色的入口可见性。已知缺陷：首次建档草稿没有清晰的继续审核入口，待处理只枚举已生效商品候选。需补齐真实导航路径，不能仅靠固定链接；修复后定向复体验。本轮仅记录状态与待办，不运行测试、不进入 Stage 5、不自动提交/合并/部署，保留原试用现场。

### 2026-09-09 review-10：批准结果区（F-12）
用户标注显示批次 #1 已批准生成 V1；本轮只读实际页面确认已批准/V1，代理未执行批准。按反馈将批准结果改为成功图标、版本标记、清晰状态文案与主次导航按钮，使用现有 LinkButton。WorkflowActions 3 项定向测试通过（批准结果链接目标断言补入已有测试）、相关 ESLint 与定向 diff 通过，实际 1048/390 宽度检查。原试用实例更新 review-10，ready_for_user_review，数据现场保留。首个目录已批准，但商品主档/分类/产品分析的后续体验仍待核实与用户确认；此前审核界面 user_verified 不扩大为新增结果区已确认。F-01 及整体体验完成后的导航排查 F-11 保留。未完整回归、提交、整合、部署或进入 Stage 5。

### 2026-09-09 review-10 后续体验入口核实
继续 Stage 4：以 review01-data-manager 只读核实 V1 商品主档显示27款，款号1101详情 /catalog/styles/21 显示2个实际变体、2个 Seller SKU、待分类；“修改名称 / 分类”可打开，分类可选衬衫/西装外套，未生成修改草稿。产品总表 /products?from=2026-07-01&to=2026-07-07 显示目录版本1、27款；2301详情可进入且有15个实际变体与指标。仅验证入口与数据展示可用，未独立重算分析数字，不标记业务核对通过。商品主档浏览、分类操作入口、产品分析查看 ready_for_user_review，等待用户本轮确认；分类保存/批准尚未执行。没有重跑测试或修改数据，F-01、体验结束后F-11导航排查继续保留。

### 2026-09-09 review-11：商品主档旧标签页刷新（F-13）
用户反馈批准后商品页显示尚未初始化。检查用户原标签页时已显示 V1、27款，未现场重现截图瞬间，不能据此认定数据库丢失；代码确认商品页原先仅挂载时读取，其他标签页批准后存在旧状态不更新的缺口。现加入切回可见页面/窗口聚焦时重新读取、刷新商品主档按钮，以及请求失败重试入口，保留错误与未初始化状态区分和异步卸载保护。
CatalogHomePage 3项目标测试（含空目录后聚焦读回V1）及两文件 ESLint、定向 diff 检查通过；沿用现有 Node 直接运行目标，未重装依赖。已同步原试用 source 与 manifest 为 review-11，备份 review-10 对应文件；实际原商品标签页确认刷新按钮、V1、27款可见。development_complete / ready_for_user_review，待用户复体验。数据库、账号、Run ID及端口保留，无业务写入；F-01和体验结束后的全导航排查F-11继续保留，未完整回归、提交、整合、部署或进入Stage 5。
### 2026-09-09 review-12：产品趋势交互与线条（F-14）
用户标注2301每日趋势，希望增加功能并优化线条。按 Product Design 现有产品标注范围及简短设计梳理实施；Remotion 路由确认其为视频/时间轴用途，本图继续使用现有SVG与轻量CSS高亮，不引入视频依赖或外部服务。8条系列改为8色与疏朗实/虚线，圆角线端/拐角、数据点开关、图例单系列突出/取消、悬停日期游标和精确读数面板、键盘/滑杆逐日查看；全日期在宽屏显示，窄屏保留关键日期，修正末日标签裁切。缺失点继续断线，无报表/分母为0/零值区分，读取同一响应，不变更API、业务值、指标计算或矩阵。
验证：ProductTrendChart 5项及ProductDetailPage 2项定向测试通过，图例重复文本的既有断言改为按钮角色后仅重跑图表文件；相关 ESLint 和定向diff通过。其后仅末日轴标签锚点调整，实际390/1592宽度检查无页面横向溢出；浏览器验证图例突出7条其他系列变淡、方向键日期切换及数据点开关。浏览器尺寸恢复、代理临时标签页关闭，用户原标签页保留。工作树和原试用source已同步review-12并备份对应review-11文件/manifest；未写入数据库、完整回归、提交、整合、部署或进入Stage 5。development_complete / ready_for_user_review，等待用户本版体验确认；F-01及整体体验结束后所有导航遗漏排查F-11继续保留。
### 2026-09-09 review-13：趋势生长与交互动画（F-15）
用户批准前述动态建议，并要求增加生长动画、改善线条。现有SVG加入650ms从左向右遮罩展开和“重播生长动画”，只在数据/指标变化、挂载或主动重播时触发；悬停/日期选择/图例聚焦不重新生长。圆角折线优化线宽、空心节点及选中点大小，聚焦线宽、游标、节点显隐过渡；单独观测点在关闭数据点时仍保留。数字直接更新、原坐标与缺失段不变。减少动态效果媒体查询关闭全部本轮动画与过渡。
Skill：Product Design（既有标注范围/视觉层级），Remotion router/markup（确认时间轴动画用途，参考缓动节奏；当前交互图表沿用SVG/CSS，未引入Remotion依赖）。图表6项定向测试、局部ESLint及diff检查通过；实际浏览器重播时遮罩从28.2791%余量到0%，截图确认展开中与完成态，390宽度无页面横向溢出。减少动态效果为代码规则检查，未声称系统偏好切换已实测。已同步原source/manifest review-13并备份review-12对应文件，用户试用数据、端口和标签页保留，代理临时页已关闭/视口恢复。development_complete / ready_for_user_review；未数据库写入、完整回归、提交、合并、部署或进入Stage 5，F-01/F-11继续保留。
### 2026-09-09 review-14：趋势工具栏与尺码颜色选择（F-16）
尺码available_series仅含尺码，前端从中找颜色导致空下拉；现通过已有只读card接口按当前响应catalog_version读取颜色选项，取消过时请求，支持直达链接、读取中/失败重试；切换颜色清空旧系列。限定颜色说明明确为同色内尺码比较。工具栏分为当前状态/说明与操作，取消突出改为仅聚焦时显示恢复全部曲线。
详情页3项及图表6项目标测试、4文件ESLint通过；新增直达尺码链接读取同版本颜色与切换回归。实际页面核实White/Blue/Black/Hot Pink选项，White切Blue后曲线和矩阵更新，1048/390布局及恢复操作通过，390无横向溢出。原source/manifest同步review-14并备份review-13；数据库、原用户标签页保留，临时页关闭、视口恢复。development_complete / ready_for_user_review；未完整回归、数据库写入、提交、整合、部署或进入Stage 5。F-01/F-11及整体体验待办保留。Skill沿用Product Design标注范围和既有组件。
### 2026-09-09 review-15：分析筛选层级改造（F-17）
用户认可公开参考方向并授权实施。指标改直接选择的下划线式标签，比较维度/退货口径分段单选，尺码模式限定颜色改为色点与名称标签；原生radio及fieldset保留键盘/分组语义，未知颜色不猜色点，选中底色/边框与文字共同识别。沿用现有蓝白tokens、原API和URL状态，颜色切换仍清空旧系列，不改计算、数据和图表动画。Skill：frontend-design（同页反复布局反馈，集中调整筛选层级与响应式）。
现有ProductDetailPage 3项目标测试与两文件ESLint通过，断言改为radio操作，保留同版本颜色读取、系列清空、指标更新及返回条件验证。实际隔离入口White切Blue、销售额切销量可用；1048并排/390堆叠与颜色换行检查通过，无横向溢出。同步原source/manifest review-15并备份review-14对应文件；保留数据库与用户标签页、恢复视口、关闭代理临时页。development_complete / ready_for_user_review，等待用户本版体验确认；F-01及整体体验后全导航排查F-11保留，未完整回归、写库、提交、整合、部署或进入Stage 5。
### 2026-09-09 review-16：筛选切换闪动（F-18）
根因：每次请求setLoaded(undefined)且按请求key隐藏整个详情，导致卸载/骨架占位/页面收缩及重挂载。现仅首次读取显示骨架，同商品同权限generation内保留旧响应与其原view，图表/矩阵沿用原metric格式；更新期间固定状态提示、旧趋势区inert，成功后整体替换。跨商品或权限变化不保留响应，错误时隐藏旧数据；保留AbortController及sequence防旧请求覆盖。颜色选项按商品/权限/目录版本复用，避免切换时标签区短暂清空。
ProductDetailPage 4项目标测试通过（包含未完成请求期间图表DOM保持、旧结果标识、新数据完成后仍同一图表DOM），局部ESLint及定向diff通过；实际商品6退货切销售额后选中状态/图表正常、无骨架/横向溢出。网络等待全过程的稳定性证据为延迟Promise组件测试，不将浏览器完成态冒充逐帧测试。同步原source/manifest review-16、备份review-15，数据与原用户标签页保留。development_complete / ready_for_user_review；未完整回归、写库、提交、整合、部署或进入Stage 5。F-01/F-11保留。Skill：systematic-debugging（定位卸载与请求状态），无新增外部调用或依赖。
### 2026-09-09 review-17：数据点就近提示（F-19）
用户反馈悬停点旁不显示数据。原行为只更新图下读数，无tooltip。现按屏幕距离命中最近有效观测点，显示日期、系列、指标及精确值/部分数据提示；图例聚焦后只命中对应系列，离开图表或Escape关闭，右侧自动避让，新series/metric不显示旧提示。缺失值不生成点，不改计算/数据；原逐日面板保留。
图表7项目标测试、两文件ESLint通过；包含精确小数提示、右侧定位和移出关闭。实际隔离商品6悬停显示2026-07-01/Sand/销售额223.96，截图已核实。后续移出实测时临时标签页已不在会话，未重复操作用户页面；移出关闭以组件测试为证。同步source/manifest review-17并备份review-16，development_complete / ready_for_user_review；未写库、完整回归、提交、整合、部署或Stage 5。F-01/F-11继续保留。Skill：systematic-debugging（定位悬停只更新外部面板的缺口）。
### 2026-09-09 review-18：重合点与悬停一致性（F-20）
原最近点排序仅取首项，重合/相邻点遗漏。改为图内按日期显示当日全部已选系列，聚焦不隐藏其他系列读数，最近系列仅作强调；保留精确值、零/无报表/分母为零/部分数据区分。日期滑杆及重播清除旧提示，ResizeObserver清除旧定位，series/metric变化仍禁止旧提示。8项目标测试及局部ESLint通过，新增重合零点、聚焦仍显示全部、缺失报告、相邻值、日期切换与新响应清理断言。
实际商品6/Sand尺码模式核实7月1日L167.97、XL55.99、M/S/XXL均0.00同时出现在tooltip，和下方读数一致。同步source/manifest review-18并备份review-17，临时页已关闭。development_complete / ready_for_user_review；未写库、完整回归、提交、整合、部署或Stage 5，F-01/F-11继续保留。Skill：systematic-debugging（最近点选择和相关提示状态检查）。
### 2026-09-09 review-19：独立点与重合点区分（F-20复修）
用户纠正review-18不应对独立点显示全天全部系列。现恢复22px最近点命中，仅将同日期且精确缩放数值相同的系列作为重合组；独立点单条，重合点注明数量，附近不同值/缺失值不加入，空白处不显示提示。图下完整读数保留。8项目标测试、局部ESLint和diff通过；实际商品6验证独立L167.97仅一条、同日M/S/XXL零值三条同时显示。同步原source/manifest review-19并备份review-18，临时页关闭。development_complete / ready_for_user_review；数据、端口、原用户页保留，未写库、完整回归、提交、整合、部署或进入Stage 5，F-01/F-11保留。本批无需新Skill，沿用本反馈已定位的命中逻辑。
### 2026-09-09 review-20：稳定配色与提示框边缘（F-21）
按用户同意优先项修复：以完整available_series身份集合排序确定颜色/线型，不再以当前选中顺序决定；线条、节点、图例、提示和读数共用映射。tooltip布局阶段测量实际尺寸，按视口上下左右8px边距调整，最大高度限制并允许框内滚动；移入tooltip不立即关闭，页面滚动/resize清除旧定位。业务数据/计算/权限保持原样。
10项图表目标测试、局部ESLint及diff通过；新增取消/重排配色不变及实际高度定位测试。实际商品26取消White后Blue/Black/Hot Pink颜色保持，1048x500窗口重合提示top365/bottom492，完整处于屏幕内。恢复视口、关闭代理临时页，原source/manifest同步review-20并备份review-19。development_complete / ready_for_user_review，未写库、完整回归、提交、整合、部署或进入Stage 5；F-01/F-11继续保留。Skill：systematic-debugging（核实索引配色和未测量提示高度）。
### 2026-09-09 review-21：选择数量说明（F-22）
比较系列改为随实际维度变化的选择要对比的颜色/尺码/SKU；已选数对照available实际总数，全选显示全部N项已选，部分显示已选N/总数。仅实际选项超过8时说明同时上限，不改变至少1项/最多8项约束。2项既有目标测试补充实际总数/上限断言通过，局部ESLint通过；实际商品26显示选择要对比的颜色/全部4种颜色已选，无8项误导。同步source/manifest review-21并备份review-20，临时页关闭、原数据保留。development_complete / ready_for_user_review；无完整回归、写库、提交、整合、部署或Stage 5，F-01/F-11保留。本批无需Skill（局部文案与数量呈现修正）。
### 2026-09-09 review-22：当前指标与单位提示
图表顶部、SVG可访问名称、悬停提示、每日读数和矩阵标题统一标明当前指标/单位：销量与退货为件、会话为次、销售额为报告原币、转化率为比率。金额币种由源报告决定，不在缺少币种字段时硬编码美元；转化率保留六位小数并说明0.05=5%，计算和数据不变。11项图表/矩阵目标测试、局部ESLint与定向diff通过；当前隔离页面已实读到销售额（报告原币）及每日明细标题，热更新生效。source/manifest同步review-22，备份review-21对应文件；development_complete / ready_for_user_review。保留现场，未写库、全量回归、提交、整合、部署或进入Stage 5，F-01/F-11保留。本批无需Skill（局部指标文案）。

### 2026-09-09 review-23：重复悬停提示
用户截图中原生浅黄色提示与SVG根title文字一致，与自定义数据点tooltip叠加。根SVG改用aria-label及aria-describedby，移除根title，保留可访问名称/说明和原有精确坐标刻度提示。10项图表目标测试及两文件ESLint通过，补充无根title/保留无障碍描述/单个tooltip断言；同步source/manifest review-23并备份review-22。development_complete / ready_for_user_review，待用户复体验。保留数据和现场，无全量回归、写库、提交、整合、部署或Stage 5。Skill：systematic-debugging（截图文字与SVG提示来源定位）。

### 2026-09-09 review-24：折线图参考与Storybook
用户确认现有款式详情折线图基本达到本轮要求，并指定为后续折线图创作参考；仅折线图review-23标为user_verified，整体真实数据试用仍未完成。新增Patterns/Product Trend Chart九个故事，直接复用现有图表/选择器/矩阵，以虚构数据展示多系列、合计、重合、缺失/零/部分数据、转化率、选择上限、390宽度、空态和单日。Controls支持五种指标和宽度；不接API/数据库，不改现有图表实现。参考约定记录于工作树frontend/src/features/products/ProductTrendChart.reference.md，主AGENTS加入后续复用规则。
定向TypeScript（仅故事与其依赖）、故事ESLint通过；本地Storybook索引可读且列出9个故事，实际页面指标切换至conversion、精确比率与提示同步可用，390容器故事截图检查通过。既有review-23图表10项测试证据沿用，未为此重跑。Storybook本地进程入口http://127.0.0.1:6006/?path=/story/patterns-product-trend-chart--reference，无需登录；已打开用户体验标签页并保留。进程PID/log保留在review任务目录，禁用遥测、只绑定127.0.0.1；source/manifest为review-24，业务试用页面组件仍review-23。Storybook新增示例development_complete / ready_for_user_review。无完整构建/回归、写库、提交、整合、部署或Stage 5；F-01/F-11保留。本批无需Skill（复用既有组件和故事约定）。


### 2026-09-09 Storybook确认与单商品修改体验交接
用户明确表示“体验通过，进行下一步”，review-24 Storybook九场景记为user_verified；review-23款式详情折线图既有user_verified保留。下一项按真实数据试用计划第二轮第1步，交付单商品名称/主分类修改路径，不进入Stage 5。
实际只读页面核实/catalog/styles/21：款号1101、已批准商品、待分类、2个实际变体和2个Seller SKU；已展开修改表单，当前会话可读取衬衫（SHIRT）及西装外套（BLAZER）选项，生成变更预览按钮可用。没有替用户填写、生成草稿或批准。用review01-data-manager体验，建议仅选衬衫并保持名称不变→生成变更预览→核对仅主分类变化→填写原因并批准生成新目录版本→核对分类、目录版本及两个变体不变。数据及入口就绪，实际写入待用户操作/确认，不能按代理展开表单标为业务通过。
本轮仅文档状态与页面只读核对，无新代码或测试，无写库、全量回归、提交/整合/部署。原任务与Storybook现场保留。整体试用仍未完成：导入审核/重复处理实际体验、解析同操作重试权限F-01、整体体验后导航遗漏F-11继续保留。本批无需Skill。


### 2026-09-09 商品主档确认与重复文件上传体验交接
用户明确“好的，体验通过，进行下一步”，本次商品主档体验标记user_verified；不推断未观察到的具体目录版本号或其他未执行操作。按既定第二轮继续导入审核，先交接同文件重复上传。实际页面/review/2026-07-07核实经营/退货均published v1，经营22行，CSV选择及保存并检查文件入口可见，日期为2026-07-07；已将新体验页定位到上传区域。输入仅使用既有授权副本samples/1/20260707-BusinessReport-09-7-26.csv，已核实文件存在，不读取原件或扩展日期。
使用review01-data-manager选择该副本并保存检查，预期识别已有文件并返回已有批次，不产生第二份日报。本轮未代用户上传、解析、创建草稿或发布，仅入口ready_for_user_review；同文件去重既有准备证据可引用，不冒充本次用户通过。自然行级冲突样本缺失仍单列，解析同操作重试权限F-01未关闭，不能以文件去重通过代替。整体体验结束后的导航遗漏F-11继续保留。
只读页面核对及文档更新，无代码变更、新测试、全量回归、写库、提交、整合、部署或Stage 5；保留原试用数据与Storybook现场。本批无需Skill。

### 2026-09-09 review-25：重复上传结果与后续操作（F-23）
按用户授权修复：重复文件根据服务端stage显示真实状态；published标文件已导入并发布，提供查看已发布日报链接到原日期/报告类型工作台，禁止从此项重新inspect。未完成仍继续审核。队列标题改上传结果，每个已存在文件明确本次未新增该文件批次/未改变已发布日报（依据duplicate_import返回及ImportService.created=false合同，不冒充本轮数据库计数核验）。全部保存/识别成功或重复时清空File[]及原生文件框，有失败项保留选择供恢复；上传中禁止更改文件选择。既有持久化队列的旧状态文案同样即时修正。
4个相关目标节点通过（多文件、混合识别失败、未完成重复、已发布重复）；新增已发布重复链接、无inspect、输入清空/提交禁用断言。首次测试过度约束全部fetch次数而忽略既有HEAD探测，改为只断言上传请求与无inspect；最终局部ESLint/diff通过。实际原用户页核实批次#7显示新状态/结果/链接，文件框为空、提交禁用；未代用户再次上传/发布。同步原source/manifest review-25，备份review-24文件及清单，development_complete / ready_for_user_review。F-01/F-11及整体体验边界保留；未全量回归、写库、提交、整合、部署或Stage 5。Skill：systematic-debugging（区分stage、识别动作与上传结果）。

### 2026-09-10 review-26：解析重试权限F-01与原环境重启
用户授权继续优化并要求重启。按未完成项先修F-01：parse_operation_tokens和parse_attempts/parse_baselines均为只追加记录，原重试注册/终态读取FOR UPDATE要求不应授予运行账号的UPDATE权限；改FOR SHARE，保留当前读与锁，原import_batches排他锁/令牌唯一约束/摘要验证不变，不扩大权限、不改schema。
在已有test_runtime_account_can_register_but_not_mutate_operation_tokens的parse参数补同令牌认领重放、带锁终态读取、不同摘要拒绝，沿用UPDATE/DELETE拒绝断言。正式test-mysql-matrix -Versions 8.0 -Suites mysql-legacy -DevelopmentTests指定test_database_constraints.py，PYTEST_ADDOPTS只选该节点并fail-fast：2 passed / 68 deselected；只在新可抛弃测试容器按正式TLS/账号/触发器初始化，未在试用库迁移。Ruff与定向diff通过。此证据覆盖运行账号权限及令牌恢复读取，不外推完整并发/HTTP端到端验收；未重跑全量门禁。F-01 development_complete，后续实际导入路径仍待复体验。
原端口初查均未监听，发现旧恢复运行器后发原stop-review标记并核实进程退出，再同步source/manifest review-26，备份review-25对应源码/测试/清单。隐藏窗口执行原resume-review -Experience -ExperienceOnly，Run ID c8064cc8c42c4fe7823cd1c1f336697e不变；API30250/前端46638恢复，API和Worker schema0027兼容。既有账号从受限文件进行本地API登录成功，只读商品21确认目录V2、1101和2个变体保留；未复建空库、未重新导入或批准业务数据。重启后浏览器需要重新登录，已保留入口。Storybook6006同样已启动，禁用遥测/仅本机。
日志：任务目录resume-20260910.log、resume-20260910-error.log、storybook-20260910.log。体验账号仍review01-data-manager，原凭据文件不变。review-25反馈未获得本版独立确认，继续ready_for_user_review；F-11及自然行级冲突未覆盖保留，整体试用未完成，不进入Stage 5、提交、整合或部署。Skill：systematic-debugging（最小权限下解析重试锁读取）。

### 2026-09-10 完整修正版日报体验准备
用户同意继续体验错误日报更正。仅在任务目录 correction-trial 创建人工构造的 20260707-BusinessReport-TEST-CORRECTION.csv，来源为已授权 samples/1 的7月7日完整经营报告；不代表发现真实业务错误。只改2301-Blue-M的已订购商品销售额(S2)，US$83.98→US$93.98。字节保留式修改及逐单元格比较确认仅此一处变化；22行、销量31、会话666保持，销售额1328.69→1338.69。源副本哈希未变，verification.json记录来源/输出哈希与核对值，退货文件未修改。
实际浏览器/review/2026-07-07确认Review 01 data_manager、当前经营v1、22行、原行83.98及CSV上传可用。入口ready_for_user_review；未代用户上传、创建草稿、校验或发布。操作：上传TEST-CORRECTION文件→核对日期2026-07-07和经营报告并完成识别解析→选择替换当前发布版本(不是合并)，形成新草稿→核对22行/1338.69/31/666后校验发布→核对新版本及旧v1仍可查看。若已有活动草稿或出现意外差异，先保留现场处理，不强制重建。可填原因：隔离试用：人工构造金额更正，2301-Blue-M销售额增加US$10.00。
样本构造核对通过不等于导入/更正发布链路体验通过；同文件去重F-23未另行提升状态，F-01实际路径与整体试用后的导航排查F-11保留。代码仍review-26，本轮仅样本和文档，无需重启；不完整回归、提交、合并、部署或Stage5。Skill：Spreadsheets（结构保留与核对）；为保持原始CSV格式采用字节级局部修改，没有转换为工作簿。

### 2026-09-10 review-27：补齐历史版本只读明细
用户发现版本记录仅有元信息，授权补齐。VersionHistory的published版本加入查看此版本数据，新增VersionRows按选中version_id读取、只读表格/行状态/分页/错误重试；切换版本以key卸载旧请求结果，校验响应version_id，避免显示当前指针数据。新增GET /api/versions/{version_id}/rows，仅published可用，沿用版本可见角色；复用工作台列/行读取，writable=false及editable=false，所有角色按viewer安全字段过滤，不暴露退货敏感字段或扩展列。不写库、不改发布指针或授权；本入口暂不提供汇总/导出，保留原始精度，已删除行按既有工作台规则不返回。
验证：后端2项目标测试覆盖非发布拒绝/固定版本及只读参数；前端2项覆盖固定URL/零值/只读/版本不一致拒绝，已有VersionHistory查询与viewer可见性目标1项通过；Ruff/局部ESLint通过。原Run ID恢复并重启，代码同步review-27，备份source-manifest.review-26-before-version-rows.json及受影响源文件。实际浏览器v1(#7)与v2(#15)各自首行2301-Blue-M销售额83.980000/93.980000，切换清空旧表格，v1展开保留；1048视口页面宽1033，表格554容器内横向滚动4309，不撑宽页面。API/Worker schema0027兼容，原数据保留。
development_complete / ready_for_user_review，用户尚未确认更正发布完整体验。F-11总体导航审查仍待整体体验结束；无完整回归、提交、合并、部署或Stage5。Skill：product-design:audit，按项目规则只内联核对版本选择→只读明细路径；显示核实为DOM与尺寸检查，未做截图或全量视觉审计。

### 2026-09-10 review-27体验确认与跨文件重复记录体验准备
用户明确“体验通过，下一步”，历史版本只读明细review-27标记user_verified；更正日报v2已实际存在且v1/v2差异可查看，不扩展为完整发布验收或F-01同令牌恢复通过。
下一项聚焦最初优先的重复记录处理：在任务merge-conflict-trial创建人工样本20260707-BusinessReport-TEST-MERGE-CONFLICT.csv，以correction-trial完整22行副本为基准，仅2301-Blue-M的销售额93.98→103.98，保持日期/身份/列/其他行，逐字段核实仅一处不同并记录哈希verification.json。源表合计1348.69，目标当前v2为1338.69，预期21组同值和1组异值业务键冲突。不是自然业务重复，也不是同一文件判重或文件内重复验收。
实际/review/2026-07-07显示经营published v2、退货published v1及CSV上传入口。体验步骤：上传此人工文件→确认7月7日经营报告并解析→合并到现有数据→逐页统一保留目标行(目标=v2，来源=新文件)，核对2301-Blue-M的93.98/103.98差异→生成草稿并校验，预期22行/1338.69/销量31/会话666；本轮止于草稿校验，保留现场，不再发布相同数字的日报。代理未上传/解析/生成草稿或写库。
样本和入口ready_for_user_review，不因准备完成标记冲突体验通过；F-11整体体验结束后导航审查保留，不进入Stage5。本批无需新Skill，沿用先前Spreadsheets的CSV结构保留与逐字段核对约定；无代码变动，无需重启或重跑测试。

### 2026-09-10 重复记录处理体验确认
用户明确“明白，体验通过”，本轮人工跨文件重复记录处理按交付范围标记user_verified：完整22行样本，21组同值/1组金额异值，合并时保留目标v2，止于草稿校验。此状态依据用户反馈，未再次读取数据库，不推断用户执行了发布、草稿版本号或额外操作。原试用现场保留。
本次确认不等于自然重复样本、同令牌解析失败恢复或正式发布验收通过；整体真实数据试用不自动标记完成。后续收尾须列清未覆盖项，并按用户此前要求在整体体验结束后排查全部导航遗漏F-11。未进入Stage5、未提交/合并/部署，无新代码/测试/数据库操作。本批无需Skill（状态记录）。

### 2026-09-10 review-28：试用收尾盘点与F-11导航首批补齐
用户授权继续优化，整理任务目录《试用收尾与导航排查.md》，列清已确认与未覆盖（XLSX往返、自然/文件内重复、同令牌失败恢复、候选忽略恢复等），不扩大用户确认。
补GET /api/catalog/imports只读分页列表，require_catalog_manager且site_id限定，仅返回批次身份/状态/修订；批量维护新增已有审核批次，管理角色可继续或查看批准结果，并重设返回来源为批量维护。日期工作台新增携带report_date/report_type的版本链接；版本详情新增返回日期工作台，活动草稿显示继续审核草稿。未改业务数据、权限或发布指针。
前端列表目标1项/后端viewer拒绝与站点分页2项通过，局部ESLint/Ruff通过；原实例review-28已重启，API/Worker schema0027兼容。实际页面列出目录#1已批准/#2待补全，#2可达且返回来源正确；日期7月7日→版本页保留类型，v2当前发布/v3(#16)活动草稿，继续审核指向同日工作台。没有编辑旧候选或草稿。其余主要返回路径完成源码核对，批量审核入口/完整角色及前进后退组合仍待查；不声称F-11全部关闭或全量浏览器回归通过。
development_complete / ready_for_user_review，本批只需导航体验，不保存/批准/发布。详细列表见任务收尾文档；整体不自动完成、无Stage5/提交/合并/部署。Skill：沿用product-design:audit进行内联导航检查。

### 2026-09-10 review-29：批量任务找回及导航收尾
继续F-11，确认批量任务从上传队列创建后没有列表找回。新增GET /api/imports/batch-reviews（既有_ManagerRead权限、既有站点解析、每页20条），仅返回身份/状态/修订/时间；版本页仅管理角色显示已有批量审核任务，可分页刷新并进入原任务。列表本身只读；原BatchReviewPage对running状态会继续执行，paused须手动恢复，已在入口明确说明，代理未进入/恢复运行任务。
目标检查4项通过：后端站点与分页；前端暂停任务链接只读；已有viewer可见性及版本筛选浏览器历史节点。Ruff/局部ESLint通过。review-29同步原source和manifest，备份review-28对应文件；原Run ID重启成功，schema0027兼容。实际页面显示暂无批量审核任务、v2当前发布/v3活动草稿，原数据保留。无任务数据时不虚构已验证恢复，不创建试用任务。
F-11本次主要路径源码核对完成：角色路由守卫、批量入口/异常转人工/待发布到版本/返回任务、商品与分析返回、日期与版本往返；发现的4处入口已实现（review-28三处+本批任务列表）。定向显示/测试覆盖按记录，未做所有角色全页面浏览器回归。开发审查完成，待用户导航确认；review-28未因“继续下一步”自动记user_verified。XLSX往返、自然重复与F-01真实失败恢复等保持未覆盖。无Stage5、提交、合并、部署或全量测试。Skill：沿用product-design:audit内联路径审查。

### 2026-09-10 导航修订体验确认
用户在review-29版本记录页明确“体验通过”，本轮review-28/29导航入口修订按交付范围标记user_verified；F-11本次试用主要导航检查及四处修订闭环。确认仅涵盖已交付的导航体验，不代表有数据的批量任务恢复、全角色全页面回归或发布验收完成。
当前现场保留，不新增或恢复任务，不修改草稿/发布指针，不重新读取数据库。标准XLSX往返、自然/文件内重复、F-01真实失败后的同令牌恢复、候选忽略恢复等仍按收尾清单列为未覆盖。整体Stage4待收尾范围确认，不自动进入Stage5、提交、合并或部署。本批无需Skill（用户确认状态记录），无新代码或测试。

### 2026-09-10 七月全量Stage4完整体验准备
用户授权按七月独立持续基线准备全部既有功能。新入口http://localhost:20601/?month=2026-07已恢复；新管理/查看账号通过localhost登录与只读API核对，62份原始日报保留。恢复故障为Docker重启映射端口变化，任务脚本核对容器Run ID后更新私有连接端口、等待SELECT 1，再过schema0027检查，未重建数据库。
目录34款/222SKU经正常API校验/预览/批准为V1；27款名称复用旧确认，7款来源标题作试用建议，1101继承SHIRT分类，其余待分类。身份逐项验证精确SellerSKU=款号颜色尺码且单ASIN；没有越权直接SQL写目录。两角色商品/分析/日报读取通过，XLSX当前模板已生成下载，Storybook原6006可用。人工练习副本仅复制到exercises未导入；新基线各日v1，旧测试v1/v2/v3留在旧环境。
完整入口/逐项前置/测试金额与原始口径/恢复方式见新任务《完整体验入口.md》。整体ready_for_user_review，不等于全部场景已体验；受控异常恢复、自然重复仍明确未覆盖，不人为故障注入或自动跑完整回归。旧环境保持，无Stage5/提交/合并/部署。Skill：systematic-debugging；沿用表格核对约定。

### 2026-09-10 七月入口连接拒绝修复

用户反馈 localhost:20601 连接被拒绝。复现：PowerShell 7 的 localhost 健康请求超过 2 秒超时，而同端口 127.0.0.1 返回 200；启动检查因此误判失败并关闭任务服务。已将本任务 resume-review.ps1 的前端启动及持续健康检查改用明确 IPv4 回环地址，浏览器入口保持 http://localhost:20601/?month=2026-07，以保留与旧环境的 Cookie 隔离。

使用原 Run ID 和原数据库恢复，未重建或重新导入。resume-stable.log 已出现 Catalog experience READY；运行超过一分钟后进程与入口仍在线，浏览器正常显示登录页。check_recovery_readonly.py 定向确认 data_manager/viewer 登录、34款/222SKU目录、七月分析及发布汇总均通过，证据 recovery-read-check.json。七月整月体验仍为 ready_for_user_review，待用户确认；不代表发布验收。此次使用 systematic-debugging，未运行完整回归。

### 2026-09-10 产品总表商品身份展示优化

按用户确认方案：默认款号、悬停/聚焦完整名称、点击右侧商品信息抽屉、可选显示两行名称；来源标题计数移入抽屉，保留携带筛选上下文的款式详情入口。工作树成果同步到七月基线 source 并热更新，未重启数据库或重新导入。状态 development_complete / ready_for_user_review，待用户体验。

验证：ProductLedgerPage.test.tsx 3项通过，相关3个TSX文件 ESLint通过。正式快检脚本受pnpm依赖自动检查阻塞，使用现有node_modules/vitest/vitest.mjs执行同一目标，未安装依赖。浏览器确认抽屉宽440px/视口1280px，关闭恢复款号焦点且scrollY保持77。使用frontend-design；未完整回归、未提交/整合、未进入Stage5。

### 2026-09-10 产品总表身份展示体验确认

用户明确反馈“体验通过，确实不错，感觉良好”。本次确认覆盖七月环境的产品总表款号展示、悬浮名称、商品信息抽屉及显示名称开关，状态 development_complete / user_verified。当前环境继续保留；整体七月完整试用及正式发布验收不据此判定完成，不进入 Stage 5。纯体验状态记录，本批无需 Skill，未重跑测试。
### 2026-09-10 产品总表销售贡献与退货关注

用户授权实施三项建议。已完成：总表销售额/平均单价标注US$、转化率百分比、本期退货日期口径说明；销售额下方显示当前筛选全部款式占比；原最近发布位置改为平均销售单价（最近发布在商品抽屉保留）；销售贡献/退货关注快捷排序，退货视图附同期退销比及非订单退货率说明。零分母和缺失显示破折号，部分数据保留提示。未推断利润或退款损失。

占比分母由原有同一快照SQL在搜索筛选后、分页前通过窗口求和提供filtered_sales_total；生成客户端已同步。七月隔离环境原RunID恢复成功，未迁移数据库或重导入；运行日志resume-insights.log显示READY。定向验证：前端6项、后端SQL/模型10项通过，受影响前端ESLint通过；真实隔离数据两页25+9条分母均58733.20，搜索2301分母25634.21，退货排序通过，证据july-baseline-20260910/ledger-insights-check.json。当前状态development_complete / ready_for_user_review，待用户确认。本轮沿用frontend-design；未完整回归、未自动提交/合并或进入Stage5。
### 2026-09-10 修复产品总表切换快捷视图闪屏

根因：排序变化清空loaded，并将整表替换为骨架屏，页面高度收缩。已按同筛选范围及权限generation保留上次结果，显示更新提示，收到当前请求结果后更新；请求序列/abort保护保留。排序等待时表格aria-busy/inert，日期、搜索、分页或权限变化不复用旧结果，失败隐藏旧表。七月source已热更新，无数据库重启或数据写入。ProductLedgerPage定向5项通过（新增排序保留同一表节点及失败清除旧结果），相关ESLint通过。状态development_complete / ready_for_user_review，等待用户复体验。使用systematic-debugging；未完整回归、提交、整合或进入Stage5。

### 2026-09-10 产品总表表头指标说明

已按用户授权新增8个独立表头说明按钮，点击弹窗展示来源、公式、当前日期/目录/事实口径和缺失规则。销售占比及同期退销比随对应表头解释；实际变体明确为目录成员数量。按钮不触发排序，关闭恢复焦点。七月环境source已热更新，未重启数据库或修改业务数据。ProductLedgerPage 6项定向测试通过，相关静态检查通过；状态development_complete / ready_for_user_review，待用户确认。本批无需Skill，复用现有Dialog；未完整回归或进入Stage5。

### 2026-09-10 全部指标说明弹窗统一优化

用户要求统一改善刚加入的所有表头说明弹窗，并在本次体验完成后再录入Storybook。已统一8项：标题层级、正文内边距、公式强调框、日期/目录/事实信息条、短段落规则、细分隔线、180ms入场/120ms退场及减少动态效果适配。通过Dialog可选contentClassName仅作用于这组说明弹窗，其他业务弹窗不受样式影响。七月source热更新；定向6项通过，相关ESLint通过。浏览器832x912视口核对销售和退货说明，宽680px，正文内边距24px 28px 26px，长文均在视口内显示。状态development_complete / ready_for_user_review；Storybook明确待本次用户确认后补入，未提前更新。使用Product Design index/audit内联审查、frontend-design布局指导；已读取Remotion路由，本次使用网页CSS动效，不引入视频运行时。未全量回归、提交/整合或进入Stage5。
### 2026-09-10 指标说明弹窗体验通过并录入Storybook

用户明确确认“体验通过”，覆盖上一批统一优化的8个指标说明弹窗，状态development_complete / user_verified。本次依照预先授权补入Patterns/Product Ledger Metric Help，包含全部八项、销售额、两种退货口径/目录快照及窄屏预览场景。故事使用虚构2026年1月/目录V3参数，无业务数据读取或API请求。新故事ESLint通过，在线6006/index.json确认5个故事入口均已注册；沿用上一批6项功能测试，不重复全量验证。七月整体体验/发布状态不据此标记完成。本批无需Skill，未提交、合并或进入Stage5。

### 2026-09-10 产品总表直接点击表头排序优化

按用户偏好不添加排序箭头，扩大文字按钮区域，统一表头说明入口对齐；当前排序列使用浅底/细线，工具栏一处显示字段及方向。款式表头改款号，对应style_code排序；当前列及快捷视图选中状态以已返回结果为准，避免等待期间高亮和行顺序不一致。保留之前无闪屏切换。后端同值现为style_id ASC，本轮未改变；未新增平均单价和同期退销比排序。7项目标测试及相关ESLint通过，七月source已热更新。状态development_complete / ready_for_user_review。本批无需新增Skill，沿用已有局部交互实现；未完整回归、提交/整合或进入Stage5。

### 2026-09-10 排序体验确认与变体经营明细

用户确认上一批产品总表表头点击排序/无箭头高亮体验通过，标记user_verified。随后授权继续下一步，已复用详情页现有全部实际变体响应，补齐销售贡献/退货关注降序、颜色和尺码本地筛选、款内销售占比、平均单价和同期退销比；分母始终取整款汇总，筛选不改变，空组合不虚构SKU，缺失/零分母沿用精确计算规则。来源安全别名可展开，未绕过SafeSourceRefView。上方既有折线图保持原实现。

新批次development_complete / ready_for_user_review。七月source热更新，款号2301入口products/31（2026-07-01至07-31）；浏览器已核对16SKU及White退货降序45/37/29/27，款内占比不随筛选变化。变体/详情定向5项通过，相关ESLint通过，返回列表上下文既有测试通过。本批无需新增Skill，复用已有组件和样式；未完整回归、数据库写入、提交/合并或进入Stage5。
### 2026-09-10 变体经营明细体验确认与下一项

用户明确反馈“应该无异常，体验通过请你继续下一步”，本轮款式详情颜色/尺码经营明细标记 development_complete / user_verified。沿用上一批5项目标测试及局部ESLint证据，本轮未修改代码、未重跑测试。

下一项为七月完整体验清单第3项单商品维护。浏览器实核目录V1、批次#1已批准；当前管理角色可访问 http://localhost:20601/catalog/styles/31 ，款号2301、16个变体，名称CLSEN Women Linen Mini Dress，待分类。已打开“修改名称 / 分类”表单，未生成草稿或批准。先体验修改标准名称→生成变更预览→核对仅当前商品名称变化，止于预览；主分类保持待分类。当前可选分类仅BLAZER/SHIRT，缺少该款连衣裙分类，记录为后续分类配置待补，不能称分类全量就绪。名称维护入口 ready_for_user_review。

七月原始日报及目录V1保持原状，整体体验、导航遗漏排查和正式发布验收未完成；未进入Stage5、提交、合并或部署。本批无需Skill。

### 2026-09-10 分类代码直接修改

用户授权直接修改分类代码，同时保留商品关联及历史代码。管理员分类管理表已将代码改为可编辑字段，PUT请求可选code以兼容旧客户端；服务保持category_id，规范化代码并检查其他分类别名冲突，数据库唯一约束阻止重码，审计记录previous_code/code。只更新分类字典，不修改已批准目录成员快照或商品关联；已批准商品卡继续展示批准时的代码。未替用户修改七月分类值。

验证：后端目标7项（含权限路由及改码/冲突检查）、前端编辑目标1项、相关ESLint通过；正式脚本单MySQL8.0独立测试库test_catalog_approval.py共3项通过，覆盖分类改码后相同category_id及原SHIRT历史快照。非全量门禁。七月source明确5文件同步、原RunID重启READY，浏览器管理员分类管理已看到可编辑代码字段，用户新建DRESS/T-SHIRT保留。状态development_complete / ready_for_user_review，入口http://localhost:20601/catalog/styles/25 → 管理分类 → 修改代码 → 保存。整体试用及发布状态不变，未进入Stage5、未提交/合并。Skill：test-driven-development用于定向行为与数据一致性测试，验证范围遵循项目规则。

### 2026-09-10 分类代码编辑体验确认

用户明确反馈“体验通过”，本次分类代码直接修改标记 development_complete / user_verified。确认范围为上一批分类代码编辑功能，不推断用户具体修改值或新增目录版本。沿用上一批前后端定向与独立MySQL快检证据，本轮仅记录确认，未修改代码、重跑测试或重启环境。七月现场保留；整体试用、后续导航遗漏排查和正式发布验收状态不变，未进入Stage5、提交、合并或部署。本批无需Skill。

### 2026-09-10 两级分类与中文校验

用户批准主分类+可选细分类方案。新增schema0028：分类父ID（同站点外键）及目录成员category_parent_snapshot；保留分类ID，两级校验防止自身/三级/有子节点主分类下移及停用父节点选择。管理员创建/编辑可选上级，代码格式中文提示与本地拦截；单商品维护主/细联动，预览及商品卡显示批准路径。产品总表新增主/细筛选，SQL按所选目录成员及父快照筛选，不重复计数，分页与销售分母同范围。单商品/批量批准保存父快照，keep/前向恢复复制历史分类字段，不重写历史。未自动导入整张分类表或猜测商品归属。

验证：分类/权限/分析API及服务SQL与schema定向单元检查通过；前端分类、商品卡、总表与URL定向检查通过，TS类型检查与相关ESLint通过。独立MySQL8.0仅目录批准及产品分析两文件5项通过，包含父/子筛选同商品同分母、父子代码改名后历史快照不变。七月任务仅升级所属隔离库0027→0028，category-hierarchy-upgrade.json记录升级前后旧目录成员指纹一致；source明确20文件同步，resume-hierarchy.log记录原RunID READY，双角色只读快检34款222SKU、分析及汇总200。未完整回归、未进入Stage5、未提交/合并/部署。

状态development_complete / ready_for_user_review。入口http://localhost:20601/catalog/styles/25 → 管理分类，已预填DRESS_MINI/短款连衣裙/上级DRESS，未提交；用户新建后可到实际连衣裙商品修改主/细分类、预览批准，再在七月产品总表筛选验证。类别字典修改本身不会自动更新已批准商品归属。保留现场。Skill：brainstorming梳理已批准方案，frontend-design检查表单布局，沿用定向测试约定。

### 2026-09-10 分类管理布局与组件优化

按用户截图反馈，分类管理由全行编辑表改为左侧可搜索的主/细分类目录、右侧单项编辑；顶部集中新建/关闭，名称代码、上级状态、别名分组，复用Button/Input/Select，说明靠近相关字段。选中、停用、未保存、保存反馈明确，切换或关闭时若有未保存修改先提示保存/取消；取消恢复当前已保存值。主分类已有子项时上级控件禁用。避免保存时刷新其他未保存行的问题，保存响应更新当前项。未改后端及历史快照规则。

3项目标组件测试及ESLint通过，包含代码保存、格式中文反馈、未保存切换保护和取消。七月source仅同步组件与新CSS模块，热更新无需数据库重启。浏览器1592px与680px实核，无页面横向溢出，窄屏上下布局，检查后恢复视口。恢复之前预填DRESS_MINI/短款连衣裙/上级DRESS，未提交分类或商品变更。状态development_complete / ready_for_user_review，入口http://localhost:20601/catalog/styles/25 → 管理分类。未完整回归、未进入Stage5、未提交/合并/部署。

Skill：Product Design index/audit基于用户截图内联审查一条分类维护路径；frontend-design用于层级、布局及响应式组件。本轮等待用户体验，未新增Storybook故事。

### 2026-09-10 商品分类体验确认与重复导入交接

2026-09-10 批量审核体验确认：用户在/versions?batch_review_run_id=2明确“好的，体验通过”。此前截图任务#2已完成，2项待发布、0失败、0人工处理。确认范围为预检、运行进度、推进待发布、查看草稿和任务找回；暂停恢复/失败重试/发布不在本次确认范围。状态user_verified，保留2099-01-01/02测试草稿及七月现场，未代发布、重启或重跑检查；主索引和完整体验入口同步。本批无需Skill。

2026-09-10 XLSX往返确认：用户在/catalog/imports/4反馈“体验完成”，按本轮交付的上传、重新校验、提交审核与预览范围标记user_verified；包括WPS文件结构兼容及正式校验前置的提交入口修复。未读取数据库或推断用户批准、新目录版本、具体预览差异；本次确认止于预览。主索引与七月清单同步更新，原现场保留。下一项有数据批量审核仍待准备，不自动启动。本批无需Skill，无代码/测试/重启或阶段推进。

2026-09-10 XLSX复体验确认：用户称修改后成功，上传兼容修复user_verified。只读页面核对导入4校验通过、workflow修订2、待处理0、34款222SKU222映射、解析异常0；当前显示提交审核按钮，未见批准预览。未代执行写入，后续预览差异仍待用户核对。本批无需Skill，无新测试或重启。

2026-09-10 XLSX兼容反馈：正常目录条目误触zip_member_path_invalid。ooxml.py仅允许已知包部件的空父目录，仍检查路径/重复/本地头/CRC；受限支持docProps/custom.xml标量属性及精确关系/内容类型，不放开任意部件或外链。实际文件22条目通过OOXML后定位C16文本款号被保存为数字；workbook.py保留拒绝，API与上传组件改中文说明和错误代码。17项OOXML检查（含新增正常目录及三类非法目录）、Ruff/前端ESLint通过。实际解析停在预期catalog_text_cell_numeric，未声明整文件已可导入。4个实现文件同步七月source，同RunID恢复日志resume-xlsx.log READY；原文件不改、未代上传批准。状态ready_for_user_review，建议副本C16重新以文本输入1210，D16为名称编辑目标。systematic-debugging用于本次排错，无完整回归或阶段推进。

2026-09-10最新确认与交接：主/细分类联动筛选获用户“体验通过，进行下一步”，标记user_verified。接续XLSX往返，浏览器/catalog/maintenance发现旧export#3基于V2，已正常点击重新生成候选，export#4下载链接出现且旧版本警告消失，当前生效目录仍V34。未开始在线审核、下载、编辑、上传或批准。交付用户下载并在D盘任务目录保留原模板及编辑副本，只改款号1210标准名称末尾添加“（试用）”，上传校验预览应仅名称变化，身份/分类/SKU映射不变；止于预览。状态ready_for_user_review，下载入口就绪、离线编辑待用户操作。本批无需Skill，仅应用内生成标准模板及状态记录，未执行表格文件处理、测试、重启或Stage5。

2026-09-10 后续独立交接：用户授权准备主/细分类联动筛选体验。七月产品总表、当前事实/事件日期、目录V34，只读浏览器操作核实主分类裤子8款、休闲长裤7款、西裤1款1210（销量1、US$39.99、占比100%），切换全部分类作为体验起点。状态ready_for_user_review；未改代码、上传、写库或重启，无新增测试。本批无需Skill。体验路径：7月产品总表→裤子/应用筛选→休闲长裤/应用筛选→西裤/应用筛选→全部分类/应用筛选。既有标题分类与重复上传user_verified不变。

后续状态纠正：用户明确指出本项同文件重复上传已经体验通过并要求更新计划，按本次确认记录 user_verified；以下交接保留为历史记录，不再作为待办执行。未重新上传、创建草稿或核验数据库，不推断具体批次/版本变化；不将本项通过扩大到更正或合并冲突。已同步主计划索引和七月体验清单。本批无需Skill，纯文档状态更新。

用户明确反馈“体验通过，进行下一步”，本轮标题分类结果标记user_verified。上轮32款经商品卡预览批准，加上原2款，共34款分类，当前目录V34；探索批次#2已撤回。此次确认不代替分类筛选等未独立确认路径或整体试用验收。

按七月完整体验清单第4项，准备7月7日原文件重复导入体验。浏览器实核/review/2026-07-07显示经营/退货v1、经营22行及高级审核区域上传原表控件。已核实samples/1/20260707-BusinessReport-09-7-26.csv存在，未代上传或创建草稿。预期同文件识别重复，已发布22行/US$1328.69/31件/666会话不重复累计。更正金额案例后续先止于草稿校验。七月现场与所有未提交成果保留；本批无需Skill，未运行测试、重启、进入Stage5或提交/合并/部署。整体导航遗漏排查仍待收尾执行。


2026-09-11 审核工作台加载反馈：导入6摘要与来源证据首屏API抽查均约0.05秒；前端此前等待五类数据及全部分页齐备才显示工作台。现先显示摘要/状态及五类加载进度，剩余分页并行读取；完整同修订数据返回前不展示编辑/工作流操作或虚假零待办。目标组件测试2项、两文件ESLint通过，源码同步至july-baseline-20260910/source，待用户复体验。Skill：systematic-debugging。此项为加载体验优化，未证明所有请求或冷启动均无性能问题；未执行全量验收。本轮最初核对为修订27等待批准；用户操作期间页面已显示当前目录V36，此次加载优化未执行任何提交或批准。此前V35与待办记录为历史快照。


2026-09-11 用户在8月1–6日1202产品总表明确“体验通过，进行下一步”：记录本轮加载优化及批准后1202路径为 user_verified（july-baseline-20260910、目录V36）。本轮只读API核实导入6已approved、修订28；1202销量23件、销售额USD807.78，范围内unmatched=0。未将确认扩展为全Stage4或release_validation；历史V35/日报逐日完整对账仍保留证据待办。下一步E独立虚构演练已准备：2099-05-01，SKU SYNNEW9501-Blue-S，2件/USD119.98，文件位于隔离目录exercises/sku-discovery-2099-05-01；batch85已上传并解析1行（parse baseline87），尚未发布。入口http://localhost:20601/review-advanced/2099-05-01?report_type=business_report&batch_id=85（已核实显示批次85识别确认，可点确认并解析继续；普通日期页在草稿建立前显示未导入）；发布后从同日/catalog/unmatched查询，应直接发现新SKU，不先生成目录导出。等待用户体验发布和发现路径。本批无需Skill，复用既定计划与现有API，未修改业务代码、未运行回归。


2026-09-11 E演练日期修正及空状态缺陷：用户截图同日待归属0，API核实批次85已发布版本81，但目录快照coverage_end限定截至当前日期，未来2099-05-01被排除。此样例不能证明新SKU发现通过。用户授权解决后，CatalogUnmatchedPage在无范围发布依据且无待归属事实时不显示零指标/无未归属成功提示；未来范围明确日期限制，其他空范围提示核对报告日期与发布状态。目标测试2项、ESLint及diff检查通过，源码同步隔离实例；systematic-debugging用于根因及回归。已只读确认2026-06-01无既有经营版本，准备明确SYNTHETIC样本批次86（上传、识别完成，尚未发布），SKU SYNNEW9501-Blue-S，2件/USD119.98。文件位于隔离目录exercises/sku-discovery-2026-06-01/20260601-BusinessReport-SYNTHETIC-SKU-DISCOVERY.csv；首次相同文件字节上传被duplicate_import拒绝指向85，随后仅修改标题加入演练日期区别于未来样本，保留旧样本。新入口http://localhost:20601/review-advanced/2026-06-01?report_type=business_report&batch_id=86，发布后核对/catalog/unmatched?from=2026-06-01&to=2026-06-01&return_basis=event_date。状态development_complete/ready_for_user_review，E仍待体验；真实8月1–6日确认继续有效。
