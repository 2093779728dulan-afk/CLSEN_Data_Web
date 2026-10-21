# 商品主档与目录工作簿优化实施计划 v1.0

编制日期：2026-09-07；状态同步：2026-09-08。R、A、B1/B2、C、D 均为 `development_complete / user_verified`，本专项开发与人工体验已完成；`release_validation` 待部署准备，未标记正式 accepted。成果仍在 `codex/stage4-1-app-shell` 的未提交改动中，未合并或部署。本次仅同步文档，不重跑测试或启动后续开发。

执行方式：当前代理内联，按完整使用路径分批交付。项目 AGENTS.md 覆盖通用 Skill 的子代理、逐步审批、强制红绿循环、自动提交和全量测试要求。

## 1. 目标与范围

采用方案 B：商品卡承接单商品日常查看、修改与异常处理；批量维护中心承接候选生成、在线批量审核、标准 XLSX 往返和首次初始化。所有写入入口共用领域校验、权限、版本和审计规则。

本计划细化 Stage 4.2② 反馈修正、4.2③ 和 4.3 的商品主档部分，不替代全项目 Stage 4.3，也不启动 Stage 5。历史生效日期、追溯重述、结账冻结、规模化存储与流式导出仍属 Stage 5。生产/供应链、11A、11B、RAG 接入、多级分类、自动分类、图片/PIM/ERP 继续暂停。

需求来源：[商品卡设计](../specs/2026-09-02-product-catalog-card-maintenance-design.md)、[P0 身份与审批合同](../specs/2026-08-19-product-style-variant-analytics-foundation-design.md)及本次 v0.1 审阅和补充建议。总体排程以[计划索引](../../workflow/project-plan-index.md)为准；本文件承接该专项的执行细节，不另建平行主线。

## 2. 基线与执行条件（历史计划，专项已交付）

- 计划编制时，Git 登记开发工作树为 `D:/CLSEN_Data_Web/.worktrees/stage4-1-app-shell`，分支 `codex/stage4-1-app-shell`，HEAD 为 `ec0a72e907cf7787536cf73964f7897485e28c97`。4.1、4.2①、4.2② 成果在未提交改动中，不能只按 HEAD 重建或覆盖。
- 编制时索引记录 4.1、4.2① 为 `development_complete / user_verified`，4.2② 为 `development_complete / ready_for_user_review`。这些是已有交付记录，本轮没有重跑或独立认证；本计划不把用户对方案的批准等同体验通过。
- 后续用户发起执行时，先读取主工作区 AGENTS.md、计划索引、本计划及 Skill 搭配表，再核对目标分支、相关 diff、已有任务是否仍在编辑。Git 状态使用 `--untracked-files=no`，未跟踪文件仅检查明确业务路径。
- 原执行顺序为 R → A → B1/B2 → C → D，均已完成并获得相应体验确认，不再作为待执行入口。下一项按总索引核对剩余 Stage 4.3 页面；不以本计划历史开始条件重复开工。
- 文档权威版本保存在主工作区。若在其他工作树执行，先读取这些文件；不得假设未提交文档会自动随分支继承。不为同步规则覆盖其他任务的文档或业务改动。

## 3. 固定业务规则

### 3.1 身份和分类

| 概念 | 本期规则 |
| --- | --- |
| 款式编号 `style_code` | 用户可识别的业务编号，如 1102；永久身份为 `style_id`。编号修正遵守历史键保留合同，不能由字符串重建身份。 |
| 内部展示 SKU | 如 1102-BLACK-M，永久变体身份为 `sku_id`；只建立实际存在且经确认的变体，不生成颜色×尺码组合。 |
| Seller SKU | 按 site、Seller Account、Marketplace、规范化 Seller SKU 共同定位；允许多个别名指向一个稳定变体，同作用域不能有两个有效归属。 |
| 产品分类 | 首版一款式一个主分类；分类独立于编号、变体和 Seller SKU，不影响身份或自动变更映射。未关联时显示“待分类”，不猜测分类。 |

分类字典采用站点作用域，保存稳定 ID、规范化唯一代码、显示名称、别名、启停状态及审计信息。代码使用 NFKC、去首尾空白与统一大小写，服务端和数据库共同防止代码/别名键冲突；语义同义词不承诺自动识别，创建时先展示已有分类供选择。SHIRT/衬衫、BLAZER/西装外套是首批预设，自定义名称可用中文，代码按相同规则录入并校验。

viewer 按现有站点权限查看；data_manager/admin 可为商品选择现有启用分类，只有 admin 可创建、改名、维护别名或停用分类。已使用分类不硬删除，停用只禁止新选择；不提供自动合并分类。单纯字典治理写独立审计；商品分类关联随款式 revision 进入目录版本，并保存当时的代码/名称快照，使字典改名不会改写历史目录。旧版本未记录分类时显示“未记录分类”，不套用当前分类。

### 3.2 单商品变更与批准

统一路径为：当前生效内容 → 编辑独立变更草稿 → 服务端校验与原值/新值预览 → 批准 → 新目录版本。保存草稿不等于生效。

- 单商品草稿记录站点、目标身份、基线目录指针/版本、草稿 revision、允许字段、来源和提交者。复用现有审批服务和事务边界，不另建可绕过安全门的直接写表入口。
- 独立草稿在基线目录上叠加本商品差异，并验证受影响关联；批准后形成包含其他未变商品的新目录版本，不能丢失其他目录成员，也不能带入另一份批量草稿的修改。
- 保留“同一份草稿的阻断项全部解决才能批准”，不对已有整批草稿实施部分批准。本设计新增独立商品草稿入口，非放宽旧 XLSX 批准条件。
- 批准固定 publication/catalog 快照并检查目录指针、草稿 revision、权限和风险。基线改变时保留用户输入，要求刷新差异并重新预览；不得静默覆盖或自动批准重基后的内容。
- 写入沿用认证、站点隔离、CSRF、幂等和期望 revision；重复提交不得创建两个版本。普通变更权限沿用 data_manager/admin，高风险既有身份操作仅 admin，viewer 不允许写入。
- API 返回明确的草稿状态、校验问题、风险与变化摘要；批准成功返回新目录版本及更新后的 revision。客户端展示“草稿已保存”“校验通过，待批准”“已批准生效”，以服务端结果为准。
- 本期不新增历史追溯或有效日期语义；涉及跨既有身份转移、历史重述的操作继续使用现有明确支持的高风险合同，现有合同无法表达则阻止并归入 Stage 5，不能以普通别名编辑代替。

### 3.3 候选、冲突与忽略

同一作用域的草稿预占、已批准映射、明确排除必须统一判定。草稿临时预占与 P0 永久身份键保留分别建模；撤回/拒绝/过期只释放该草稿的临时预占，不能释放曾批准的身份键。冲突记录同时引用相关商品卡，各页面打开同一记录，后端串行化写入或唯一约束保证一致性。

增量来源按不可变来源版本/行 digest 去重；人工确认的名称、颜色、尺码、分类、映射和排除决定不被新报告覆盖。新值成为候选，不直接变成正式商品资料。永久忽略必须有原因、操作者、时间、作用域和版本；继续累计来源信息但不重复提醒。恢复审核明确撤销忽略并重新进入候选，不能因置信度变化自动恢复。

### 3.4 工作簿兼容

当前 `workbook.py` 使用精确六表结构和表头，包含“款号”；已有安全测试校验表头、类型和公式拒绝。R 只改网页文案和帮助提示，旧 XLSX 表头及接口字段 `style_code` 保留。A 增加分类时同时设计显式模板版本与适配，新模板才统一“款式编号”并增加分类字段。

- 仅接受明确支持的旧/新模板版本，分别精确校验结构，再转入同一领域校验；不通过“忽略未知列”兼容，也不放宽公式、压缩包、容量、元数据和来源校验。
- 旧模板没有分类列：已有商品保持原分类，新商品为待分类；不把列缺失当作清空请求。新模板区分“保持原值”“明确清空”和选择分类，不由空白自动清空。
- 第一版“待分类”不阻断目录初始化与普通批准；后续若要求分类必填，属于另行产品规则。XLSX 只能引用已存在的分类代码，未知代码返回行级问题，不暗中创建分类。
- 原始上传不可变保存并审计；旧模板在新目录基线上仍受 stale 校验，兼容格式不等于允许过期导入覆盖当前版本。
- 在线审核直接校验/批准；只有离线分支需要下载、修改、上传 XLSX。页面迁移期间始终保留已有初始化和批量处理能力。

## 4. 页面使用约定

默认展示已生效商品，提供“待我处理”入口；待办计数和筛选来自服务端授权范围。“待我处理”指当前用户有权处理的待办，不额外建设人员指派系统。

卡片只显示编号、名称、分类、状态和待办摘要；展开后按款式 → 实际变体 → Seller SKU → 来源组织。当前值与待确认值分区显示，来源默认安全摘要、按需加载；原值 reveal 权限沿用原合同。

返回列表保留筛选、排序、页码、视图和合理的展开上下文；支持“处理下一项”，列表刷新后不跳入用户无权查看或已不存在的待办。编辑失败保留输入，离开未保存内容时提示；站点切换、退出或权限撤销时清除旧站点敏感状态，不向 localStorage 持久化来源原值。

## 5. 批次与实施文件

以下路径相对第 2 节已核对的开发工作树；执行时核对文件当前 diff，不按旧 HEAD 覆盖。React/TypeScript、FastAPI/Python、MySQL 和 Stage 3 组件体系保持不变。

| 批次 | 文件与责任 | 实施顺序及退出条件 |
| --- | --- | --- |
| **R / 4.2② 反馈修正** | 现有 `frontend/src/features/catalog/CatalogHomePage.tsx`、`CatalogStylePage.tsx`、`CatalogExportPanel.tsx`、`CatalogWorkflowActions.tsx` 及对应局部样式 | 统一网页“款式编号/内部展示 SKU”及帮助提示；重排卡片层级；将现有工作簿面板按生成、审核方式、校验批准组织；按服务端任务状态显示可执行步骤。保留真实恢复入口、旧模板及审批后端。用户能找到商品、理解身份、展开来源并知道下一步，修正版本交复体验。 |
| **A / 4.2③-A 分类与单商品普通修改** | 现有 `backend/app/catalog/service.py`、`approval.py`、`validation.py`、`projection.py`、`models.py`、`repository.py`、`workbook.py`、`types.py`；拟新增 `category_service.py`、`change_service.py`、`backend/app/api/catalog_changes.py`；前端现有 `catalogApi.ts`、`catalogTypes.ts`、`CatalogStylePage.tsx`，拟新增 `CatalogCategoryEditor.tsx`、`CatalogChangeReview.tsx` | 先落实独立草稿与批准合同和分类最小模型，再完成详情编辑名称/分类、前后差异、批准及历史显示；同时加入显式模板兼容。A 只包含普通字段变更，变体与别名写入留 B。退出路径：选择/创建允许分类 → 保存草稿 → 预览 → 批准 → 新目录读取，其他商品不变。 |
| **B / 4.2③-B 候选与异常就地处理** | 现有 `backend/app/catalog/candidates.py`、`validation.py`、`approval.py`、`import_repository.py`，A 的变更服务；现有 `backend/app/api/catalog_queries.py`、前端 `CatalogStylePage.tsx`、`CatalogUnmatchedPage.tsx`、`CatalogIssueSummary.tsx`；拟新增 `CatalogPendingItems.tsx` | 依次交付新变体/别名确认与临时预占，再统一冲突、忽略/恢复和增量保护；沿用 A 的写入通道，不重建第二套批准服务。跨卡冲突同时展示相关卡和来源。退出路径：从卡片待办进入 → 确认/排除/解决允许范围的冲突 → 校验批准 → 返回原列表/下一项，重复来源不重复提醒。 |
| **C / 4.3-A 商品主档导航** | 现有 `frontend/src/features/catalog/CatalogLayout.tsx`、`CatalogHomePage.tsx`、`CatalogUnmatchedPage.tsx`、`CatalogVersionsPage.tsx` 和 `frontend/src/app/App.tsx`；拟新增 `CatalogMaintenancePage.tsx` | 建立商品/待处理/目录版本/批量维护四入口；复用 A/B 数据与控件，保持原路由可访问或明确重定向，旧 `/catalog/imports/:import_id` 深链保持有效；按角色展示。批量页先承接已有可用控件，不设空入口。退出条件：深链、返回上下文、权限、窄屏与键盘主路径可体验。 |
| **D / 4.3-B 批量维护与初始化** | C 的批量页，现有 `CatalogExportPanel.tsx`、`CatalogImportPage.tsx`、`CatalogImportSectionTable.tsx`、`CatalogWorkflowActions.tsx`、`catalogImportState.ts`；后端现有 `export_service.py`、`upload_service.py`、`import_service.py`、`workbook.py` 只改适用联动 | 完成在线/离线两分支、行级错误定位、风险预览、版本生效反馈与任务恢复导航；空目录给初始化引导，无已发布来源时明确先完成来源发布。退出条件：在线首次建档与 XLSX 往返均有可用路径，普通用户首页不被低频工具占据。 |

A/B 涉及迁移时，在 `backend/alembic/versions` 根据执行时实际 head 新增迁移，不预占编号；读取已有 `0024` 及后继，禁止修改已应用迁移。必要 API 注册在实际应用注册处接入，更新已有生成客户端或契约，不为了拆文件全面重构 Repository。新增文件是职责建议，已有同职责模块则复用。

### 每批执行记录

| 批次 | 本计划实施状态 | 依赖 |
| --- | --- | --- |
| R | `development_complete / user_verified` | 用户于 2026-09-07 明确确认修正版本体验通过 |
| A | `development_complete / user_verified` | 独立草稿、分类规则、详情编辑和模板兼容已实施；用户于 2026-09-07 确认修正版体验通过 |
| B | B1 `development_complete / user_verified`；B2 `development_complete / user_verified` | B2 已获用户确认体验通过，用户随后授权 C |
| C | `development_complete / user_verified` | 用户明确确认 C 体验通过；后续 D 也已完成体验 |
| D | `development_complete / user_verified` | 用户明确确认 D 体验通过，后续按总计划另行推进 |

记录仅在实际交付后更新：目标版本及未提交 diff 范围、定向检查、体验入口和结果、正式验收待办。计划批准不填开发完成或 user_verified。D 完成后继续总计划其余 4.3 页面，之后按总计划进入 Stage 5；不从 D 直接跳到部署。

以下为按时间保留的交付证据：各记录中的“本次不进入下一批”等限定只说明当时范围，最新状态以上表及本文件开头为准。历史体验 URL 不代表当前仍在线；本次状态同步未检查或重启这些实例。D 未实走最终批准、空库浏览器全链等证据限制保持原样。

### R 批次交付记录（2026-09-07）

- 目标仍为 `codex/stage4-1-app-shell`、基线 `ec0a72e907cf7787536cf73964f7897485e28c97`，所有 4.1、4.2①、4.2② 与本批修正继续保留为未提交成果。本批只增量修改 `CatalogHomePage.tsx`、`CatalogStylePage.tsx`、`CatalogExportPanel.tsx`、`CatalogWorkflowActions.tsx`、`CatalogWorkspace.css` 和三个对应测试文件。
- 网页用语统一为“款式编号”和“内部展示 SKU”，商品列表及详情明确款式、实际变体、Seller SKU、来源四层身份；启用状态使用带成功图标的绿色中文徽标，避免只靠颜色传意；目录工作簿按生成候选、选择审核方式、校验批准组织，并由真实任务状态决定下载、在线审核或恢复入口。旧 XLSX 表头、`style_code` 接口、恢复 API 和审批后端没有改变。商品自定义分类仍属于 A，本批未增加伪造类型或编辑入口。
- 定向证据：四个受影响组件测试文件共 7 项通过；目标 ESLint 与 TypeScript 检查通过；隔离合成实例中已实际核对商品卡入口、9 个真实变体、Seller SKU 展开、来源明细，以及失败任务不提供下载/在线审核入口。未执行全前端、完整 E2E、MySQL 8.4 或发布门禁。
- 复体验实例为 runner 自有临时 MySQL 8.0、临时存储、API、Worker 和前端，Run ID `11ca24be3ef74a5d932a12a3d8f0c26a`，入口 `http://127.0.0.1:46792/catalog`；登录凭据只保存在该运行目录的受限凭据文件中，不写入仓库。交付时等待用户复体验；后续 R 用户确认见下条，此处不再作为待办。

用户于 2026-09-07 明确确认上述 R 版本体验通过，并授权进入下一阶段；R 状态据此更新为 `user_verified`。

### A 批次交付记录（2026-09-07）

- 在未提交 Stage 4 成果上新增 `0025` 前向迁移、站点分类字典、分类别名与审计、单商品独立草稿及批准事务；批准只替换目标款式成员并复制当前目录的全部其他款式、SKU、映射和排除项，以发布 revision CAS 拒绝过期草稿，重复批准复用同一命令结果。
- 分类关联随目录版本保存代码/名称快照，字典改名不重写历史；旧版本显示“未记录分类”，新版本无分类显示“待分类”。预置 `SHIRT/衬衫`、`BLAZER/西装外套`，只有管理员可治理分类，data_manager/admin 可为商品选择启用分类，未提供硬删除入口。
- 商品详情新增名称/主分类编辑、前后差异预览和批准入口；管理员同页可创建分类、修改显示名/别名及启停状态。工作簿新增严格 v2 表头与“保持原值/明确清空/选择分类”，v1 继续按原精确表头读取并转换为保持分类，不忽略未知列。
- 定向证据包括工作簿与路由单元测试、页面/API 组件测试、TypeScript、目标 Ruff，以及可抛弃 MySQL 8.0 的 0025 往返迁移和单商品隔离/幂等/分类快照用例。未执行全仓回归、MySQL 8.4、完整 E2E 或发布门禁。
- 状态为 `development_complete / user_verified`；用户于 2026-09-07 明确确认修正版体验通过。代码、迁移与文档均未提交、push、merge、部署或应用到真实数据库；本次确认不自动启动 B。
- 初始 A 隔离体验实例 Run ID `bbb8b6ccf06047acb521d385ca379c0b`，已用临时管理员实走 STYLE #1 的名称/SHIRT 分类草稿、前后预览、批准与刷新。体验中发现分类新建请求显式提交空别名数组时被严格元组模型拒绝；已在 HTTP 边界将 JSON 数组规范化为内部不可变元组，并补充创建/更新请求目标测试。
- 修正版隔离体验实例 Run ID `2f86edc18ad04ea4b52e99b309060c36`，入口 `http://127.0.0.1:50512/catalog`；`SHORTS / 短裤 / aliases: []` 实际请求返回 HTTP 201，相关 API 单元测试 4 项和目标 Ruff 检查通过，随后用户确认体验通过。凭据仅保存在 runner 临时受限文件。

### B1 批次交付记录（2026-09-08）

- 在 `codex/stage4-1-app-shell`、基线 `ec0a72e907cf7787536cf73964f7897485e28c97` 的未提交 Stage 4 成果上新增 `0026` 前向迁移。同一站点、来源账号范围、Marketplace 与规范化 Seller SKU 在活动草稿中只能被一个导入预占；清空决定、拒绝、撤回、rebase 和批准成功均释放临时预占，已批准身份继续由原永久目录映射保护，冲突在 HTTP 边界返回 409。
- 在线导出从锁定的 `base_catalog_version_id` 回填不可变 STYLE/SKU 身份和正式字段；已批准 Seller SKU 自动指向原 SKU，销售别名解析与正式归属不一致时保留正式归属。商品详情新增黄色待处理区域，管理员可进入既有审核页，viewer 只读；本子批未实施 B2 的统一冲突、忽略/恢复或增量覆盖保护。
- 定向证据：可抛弃 MySQL 8.0 临时预占目标测试 3 项、后端路由/迁移合同 51 项、工作簿/API 单元测试 9 项、前端商品详情/API 测试 6 项通过；目标 Ruff 与 `git diff --check` 通过。新隔离实例完成 0001→0026 迁移，API/Worker schema compatibility 均为 compatible；未执行全仓回归、MySQL 8.4、完整 E2E 或发布门禁。
- 初次浏览器观察到审核页加载过程中的 `0/0` 瞬态；反查稳定运行态后，导入 2 实际为款式 `2/2`、SKU `10/12`、映射 `11/12`，仓储/API 未返回零行。默认“仅看待处理”会在已完成的款式页显示空结果，切换到 SKU 标准化可见候选。未为未复现的稳定态问题修改查询逻辑。
- 复体验实例为 runner 自有临时 MySQL 8.0、临时存储、API、Worker 和前端，Run ID `1df31eba47974b94b9d2071af162af13`，入口 `http://127.0.0.1:23840/catalog`；款式编号 `100` 显示“新增变体 1 / Seller SKU 1 / 100-NAVY-L”，进入导入 2 后可看到候选。登录凭据位于 `C:\Users\20937\AppData\Local\Temp\clsen-catalog-live-1df31eba47974b94b9d2071af162af13\experience-credentials.json`。交付时等待用户体验；后续 B1 确认及 B2/C 交付见后续记录。未提交、push、merge、部署或应用到真实数据库。

用户明确确认 Run ID `1df31eba47974b94b9d2071af162af13` 的 B1 版本体验通过，并授权继续 B2；本次人工确认不代替正式发布验收。

### B2 批次交付记录（2026-09-08）

- 目标仍为 `codex/stage4-1-app-shell`、基线 `ec0a72e` 的未提交成果。新增 `0027_catalog_draft_exclusion_reservations.py`：排除决定与映射共用同一作用域唯一预占，`decision_kind` 区分决定；排除时目标 SKU 可空。旧 0026 数据默认 mapped，旧应用通过 schema fail-fast 拒绝误用；降级前必须先撤回排除草稿，不能丢弃活动决定。真实数据库尚未迁移，正式备份恢复与升级演练留部署准备。
- 将统一占用校验接入最终批准，覆盖在线/XLSX；当前明确排除恢复映射需原因，仍由既有高风险批准规则限制管理员批准。历史永久身份不会因草稿恢复而释放。恢复到待审核沿用幂等决策命令，保存原因、操作者、修订和操作记录；原候选目标可恢复，正式目录仅在批准后变化。
- 审核页 Seller SKU 映射区域新增归属、冲突与恢复折叠入口，读取同站点同账号同 Marketplace 同规范化身份的占用记录，显示相关商品和审核批次链接、当前正式忽略原因及版本。来源证据沿用原审核页入口；viewer 仍不能访问管理接口。待处理计数尊重 audit_only，已排除或无映射目标的派生候选不会误报待办；商品卡待办按最近可用修订读取。
- 修复跨日增量导出缺陷：旧实现对已持久化来源证据提前跳过，导致新导出缺少自己的来源引用，保存时返回 409。现为每个导出建立受限引用，证据仍按不可变来源键/版本/行去重；身份解析以当前导出和冻结来源账号范围关联原文摘要。已有名称、颜色、尺码、状态与分类保持原领域合同，款式编号从冻结版本修订读取。
- 定向证据：MySQL 8.0 预占相关 4 项通过，迁移/工作簿目标检查 52 项通过，候选/证据聚合 10 项通过，新增增量引用与站点/账号边界回归 3 项通过，前端受影响组件 6 项通过，目标 ESLint、TypeScript、Ruff 与 diff 检查通过。来源解析修复后的新实例在种子阶段核对所有映射，0001→0027、API/Worker 兼容检查通过。未运行全仓、双版本矩阵或正式发布门禁。
- 最终复体验 Run ID `ef353bd36763453aa13ca6aedea39eec`，入口 `http://127.0.0.1:31138/catalog`。已实走款式 `100` / 导入 2 的 `100-NAVY-L` 排除（HTTP 200）、共享占用查询、填写原因恢复（HTTP 200）、恢复待审核行及商品卡待办；正式目录保持版本 1。当前草稿停在恢复待审核状态，凭据位于 `C:\Users\20937\AppData\Local\Temp\clsen-catalog-live-ef353bd36763453aa13ca6aedea39eec\experience-credentials.json`。
- 用户在完整体验后明确确认“体验通过”；对应 Run ID `ef353bd36763453aa13ca6aedea39eec`，状态更新为 `development_complete / user_verified`。正式发布验收仍留部署准备；未提交、push、merge、部署或访问 `data/`。本轮只记录体验确认，不进入 C。

### C 批次交付记录（2026-09-08）

- 基于 `codex/stage4-1-app-shell` / `ec0a72e` 的原有未提交成果实施。新增 `CatalogNavigationContext.tsx`、`CatalogMaintenancePage.tsx`、导航目标测试；修改商品首页/详情、待处理、版本、审核返回、布局及 App 路由。保留此前 A/B 成果，不提交、合并、部署或进入 D。
- 四入口按现有角色展示；viewer 仅进入商品，管理深链仍重定向。批量维护复用已有候选生成/恢复/在线审核/XLSX 控件，首页仅保留指向批量维护的引导，空目录仍可初始化。旧 `/catalog/unmatched` 与 `/catalog/imports/:import_id` 保持有效。
- 列表搜索、排序、每页 12 款、视图在内存 provider 中保留；provider 以用户、角色、站点和站点配置键隔离，退出时卸载，不写 localStorage。详情可返回原列表或待处理，审核页可返回来源或重新读取待处理选择下一项；路由变化卸载旧详情，避免显示上一个商品。
- 待处理页复用 B 的逐商品授权摘要，每次最多并行 4 个请求，未获处理权限的不展示审核入口；统计限定为已生效商品候选，不冒充完整新商品队列。未匹配来源沿用现有接口的前 50 条安全摘要，不把该页行数当成全量总数。规模化聚合及完整队列仍需在后续规模化工作评估。
- 实机发现旧未匹配 SQL 以 MySQL 保留字 `keys` 作别名导致 1064/HTTP 500，仅改为 `source_keys`，不变更筛选、权限或 schema。新隔离实例已实走该查询及待处理审核返回路径，修复后不再返回 500。另补全已有 B2 测试请求体的 undefined 类型守卫。
- 定向证据：前端相关 17 项通过（组件 12、App 角色路由 5；后续变更只重跑受影响导航/详情节点）；后端路由契约 1 项通过；TypeScript、目标 ESLint/Ruff、diff 检查通过。实机验证列表条件返回、旧导入 2 深链、待处理返回、批量维护、V1 版本展示、390px 窄屏与键盘进入，无页面 JS 错误。未运行全量构建/回归、MySQL 双版本或正式发布门禁。
- 体验 Run ID `173d1aa238c445d6b5cf1df7f868b743`，入口 `http://127.0.0.1:19264/catalog`，凭据 `C:\Users\20937\AppData\Local\Temp\clsen-catalog-live-173d1aa238c445d6b5cf1df7f868b743\experience-credentials.json`。专用 MySQL 从 0001 初始化至 0027，API/Worker compatible；实机快检仅导航与读取，正式目录保持 V1。
- 用户明确确认“可以，体验通过”；对应 C Run ID `173d1aa238c445d6b5cf1df7f868b743`，状态更新为 `development_complete / user_verified`。本次只记录人工体验确认，不启动 D；正式发布验收留部署准备，未提交、合并或部署。


### D 批次交付记录（2026-09-08）

- 用户在 C 体验通过后授权 D，继续在 `codex/stage4-1-app-shell` / `ec0a72e` 未提交成果上内联实现。未访问 `data/`，未提交、push、merge、部署或推进剩余 4.3/Stage 5。无新增数据库迁移，schema 0027 不变。
- 批量页保留首次初始化流程与已发布来源前提，在线无须文件，离线分支继续使用原六表安全模板。旧候选根据目录发布修订提示过期并禁用在线/下载入口；旧文件仍由后端 stale 校验拒绝，不放宽模板或批准规则。来源快照不可用时提示核对已发布报告、账号范围及快照配置，不把所有配置错误笼统判为无数据。
- 审核详情扩展安全问题列表：按站点、导入及不晚于当前工作流修订的最新行投影读取，最多 500 条，仅返回 section/row_key/field/severity/reason_code，不输出原始来源内容。返回该导入首次批准的版本号，页面在批准后显示生效结果与主档/目录版本入口。
- 页面问题按钮切换审核分类并定位到对应行，明确文件格式错误需修正后重传、暂时故障才可恢复解析。审核行按服务端分页全部读取，避免只读取首 200 行却显示完整进度；大规模流式/虚拟化仍待 Stage 5。只读/终态不提供行修改按钮，预览随修订变化失效，409 后清除过期预览，高风险批准按角色显示。
- 实机定位并修正刷新竞态：先前详情先展示，旧行读取可能在校验后返回 409 并残留错误。现完整收齐同修订数据再显示命令，按请求序号丢弃过期结果，成功刷新清除错误，工作流命令等待刷新完成；新增定向回归证明行数据加载前不能校验。
- 定向验证：前端受影响 16 项、六表与 v1/v2 工作簿安全 5 项、后端详情安全/修订查询 1 项通过；TypeScript、目标 ESLint/Ruff 与 diff 检查通过。实机新建 runner 专用 MySQL 8.0、0001→0027、API/Worker compatible；任务恢复生成实际文件，在线导入 3，原样 XLSX 往返导入 4，行保存→校验→提交→风险预览成功。未执行最终批准；批准成功显示有组件与已批准导入 1 的真实版本读取证据，未冒充本轮实际生成 V2。
- 测试导入 3/4 已经正式撤回并释放临时预占，重新上传原样文件生成导入 5，当前 `needs_attention`、两处问题（100-NAVY-L 映射决定及内部展示 SKU），供用户自行完成保存与批准。正式目录仍 V1。首次空目录引导由组件验证，现有后端初始化由 runner 种子路径覆盖；本轮未另跑空库浏览器全链或完整 XLSX 发布验收。
- Run ID `d97a3b79951e45b7bcbcde54bb5db159`；体验 `http://127.0.0.1:59874/catalog/imports/5`，批量入口 `http://127.0.0.1:59874/catalog/maintenance`。凭据 `C:\Users\20937\AppData\Local\Temp\clsen-catalog-live-d97a3b79951e45b7bcbcde54bb5db159\experience-credentials.json`。下载的合成候选在工作树 `.tmp/d-candidate.xlsx`，未改动工作簿内容。
- 用户明确确认“明白了，体验通过”；对应 D Run ID `d97a3b79951e45b7bcbcde54bb5db159`，状态更新为 `development_complete / user_verified`。本次只记录体验确认，不推断用户已执行具体批准操作或目录版本已变化；正式发布验收留部署准备。后续仍需按总计划推进剩余 4.3 页面，本轮不自动启动、提交、合并或部署。


## 6. 最小充分验证

本轮编制计划不运行下列命令。执行者每批先选能检测本批风险的已有节点，集中修改后验证一次；新逻辑仅为缺少覆盖的实质风险补目标测试。纯文案不新增形式化测试。普通约 3 分钟、MySQL 约 10 分钟预算，必要超出说明原因，不自动升级全量。

| 批次 | 已有目标起点 | 必须证明的变化 |
| --- | --- | --- |
| R | `CatalogHomePage.test.tsx`、`CatalogStylePage.test.tsx`、`CatalogExportPanel.test.tsx` 中受影响用例；目标 ESLint/TypeScript 按需 | 文案层级调整不破坏展开/切换；任务未成功不能下载或伪装已批准。 |
| A | `backend/tests/unit/test_catalog_api.py`、`backend/tests/unit/catalog/test_workbook.py`；`backend/tests/integration/test_catalog_concurrency.py::test_two_approvals_with_same_catalog_counter_have_one_cas_winner`、`test_catalog_approval.py::test_projection_expiry_and_high_risk_require_admin` | viewer 写入/跨站点拒绝；独立草稿不带入其他草稿、不漏目录成员；过期 revision 被拒、重复批准幂等；分类快照不漂移；旧模板不清空分类、新模板精确校验。现有节点不足处补相应专项用例。 |
| B | `backend/tests/integration/test_catalog_identity_reservations.py` 中适用节点、`test_catalog_concurrency.py`；前端详情/未匹配组件目标用例 | 并发临时预占只有一个成功、撤回只释放临时预占；P0 永久键仍保留；忽略/恢复有权限原因与审计；重复来源去重、人工字段不覆盖。 |
| C | `frontend/src/app/App.test.tsx`、商品页面目标用例 | 老深链和权限不变；保留列表上下文；站点切换清理旧数据。 |
| D | `CatalogImportPage.test.tsx`、`CatalogWorkflowActions.test.tsx`；`test_workbook.py::test_six_sheet_generator_round_trips_through_same_safe_parser` 及 `test_headers_are_exact_and_formula_is_rejected_before_business_parse` | 在线无须上传；模板升级安全边界保持；行级错误可修正；空目录路径和旧目录入口均存在。必要隔离 API 链路只跑受影响路径。 |

开发命令示例（在支持这些参数的目标工作树执行；按本批适用目标选择，不逐项照跑）：

```powershell
./scripts/run-dev-check.ps1 -Kind Frontend -Targets frontend/src/features/catalog/CatalogExportPanel.test.tsx
./scripts/run-dev-check.ps1 -Kind Backend -Targets backend/tests/unit/catalog/test_workbook.py::test_headers_are_exact_and_formula_is_rejected_before_business_parse
./scripts/test-mysql-matrix.ps1 -Suites mysql-p0 -PythonExecutable D:\CLSEN_Data_Web\.venv\Scripts\python.exe -DevelopmentTests tests/integration/test_catalog_concurrency.py::test_two_approvals_with_same_catalog_counter_have_one_cas_winner
```

现有脚本或运行时不存在时先核对其他已安装入口，不重复安装完整依赖或下载镜像。数据库验证只使用任务专用可抛弃 MySQL 8.0，按正式脚本账户/TLS/触发器和清理规则执行；失败先停在首因，不迁移真实库、不访问 `data/`。

每批体验提供核实可用的地址、对应版本/未提交范围、授权或合成样例前提和 3–5 步操作；不能沿用旧端口当作在线证明。R 用查看与展开路径；A 用普通修改批准路径；B 用候选处理与恢复路径；C 用导航返回路径；D 用首次初始化或 XLSX 路径。只有用户明确确认该版本才记 user_verified。

## 7. 迁移、恢复与正式验收

- A/B 模型优先加表/可空字段及兼容读写，历史分类不回填猜测值。每批先写迁移与部署兼容说明，再运行隔离目标检查；schema fail-fast 随新 head 更新，旧应用不兼容时明确拒绝运行。
- 切换新写入路径前保留旧入口可用性；发生缺陷可关闭该入口并修复，不能靠回滚已批准数据消除错误。目录修复/恢复采用既有向前版本机制，不能重写历史 revision。
- 模板升级保持旧格式的显式解析器；UI 回退不能使新格式已批准版本丢字段。不得把破坏性 downgrade 当作普通恢复方式。部署层完整迁移/恢复演练留部署准备。
- 完整回归、MySQL 8.0/8.4、完整 E2E/XLSX 往返与安全门、无障碍/视觉/响应式、性能和备份恢复集中到部署准备。当前远端 CI 仍按已有工作流运行，本计划不宣称 CI 已缩小。
- 本期适用版本语义、分类并发唯一性、草稿 isolation、永久身份保留和敏感来源输出都需列入部署前完整证据；开发目标通过不能替代这些门禁。

## 8. 需求覆盖与后续执行口令

v0.1 编号对应：1/5/6 → R；2/3/4 → A；7/11 → A+B；8/9 → D（A 先保证模板兼容）；10 → C；12 → R+C+D。本次补充的独立草稿、即时生效反馈、统一校验、上下文保留、分类治理和初始化兼容已归入上述批次。没有取消原 4.2③ 的增量、预占、冲突、忽略及恢复，也没有取消总计划其他 4.3/Stage 5 工作。

本专项已交付，后续开发可发送：

> 读取主工作区 AGENTS.md 和项目计划索引，核对 stage4-1-app-shell 工作树及未提交成果，继续剩余 Stage 4.3 页面迁移。先按页面登记与实际差距确定下一批完整使用路径，不重做商品主档 R/A/B1/B2/C/D；定向验证后提供体验入口，不提前进入 Stage 5、不自动提交、合并或部署。
