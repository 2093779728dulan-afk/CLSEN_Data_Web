# 新发布 SKU 发现与商品归属衔接修复实施计划 v1.0

## 2026-09-11 用户确认保留V35证据缺口并完成本轮交付收尾

用户在明确了解“当前数据核对/已体验功能通过，不等于全部数据和功能完整验证；V35缺批准前全量快照是未验证而非已发现数据丢失”后回复“可以”，同意按保留项方式收尾。当前Stage4本轮交付收尾完成；既有development_complete及各项user_verified结论按原版本/样例范围保留。V35全量历史映射/排除前后不变继续标记未验证，用户同意保留仅解除本轮交付收尾阻塞，不等于证据补齐、风险消失或正式accepted。

适用边界：真实副本范围七月整月及八月1–6日；当前56956/c2704d51为独立虚构体验环境，不是七八月真实数据入口。沿用已有对账/体验证据，本轮不重新查询数据库或运行测试。未覆盖的全站导航、其他写操作和正式release_validation仍按原范围保留，不声称全量验证。成果仍未提交整合；不自动提交、合并、部署或进入Stage5。下一阶段须另行明确启动，本轮只完成记录收尾。本批无需Skill，仅用户确认和状态同步。本条覆盖此前“待用户决定保留V35缺口”的交接状态，历史核对记录保留。



## 2026-09-11 正式忽略确认与恢复入口修复

2026-09-11 用户明确“体验通过，下一步是”：正式忽略、恢复到草稿、重新映射、批准解除忽略完整路径记为development_complete/user_verified，适用新独立实例c2704d51、批次3/revision6、目录V3；覆盖本条此前恢复路径待确认状态，历史准备记录保留。沿用上一轮已核实的正式归属style2/sku12、ignored为空证据，不重新跑测试。下一项建议为独立虚构环境中的批量审核失败重试（此前暂停/恢复已通过，不重复）；该项尚未准备，不称入口就绪。之后保留多角色权限与返回筛选上下文专项、V35全量历史快照证据待办；不自动进入Stage5或正式发布验收。本批无需Skill，仅用户确认与计划更新。

2026-09-11 用户在56956/catalog/imports/3反馈“已完成”。本轮只读核实独立实例c2704d51的批次3为approved/revision6、生成目录V3；100-NAVY-L决定mapped，owners正式归属style2/sku12、ignored为空、drafts为空；商品卡确认款号100、NAVY/L、内部展示SKU SYNTHETIC-100-NAVY-L、seller_sku_count=1。正式忽略→恢复草稿→重新映射→批准解除忽略的操作闭环完成，记录用户操作完成及接口核实结果；不将“已完成”扩大为正式发布验收或其他环境体验通过。原正式忽略user_verified保留，恢复路径已完成操作、整体体验确认仍按用户明确反馈记录。本批无需Skill，只读核对及文档更新，无代码/业务数据写入或测试重跑。

2026-09-11 用户同意继续正式解除忽略体验。限定新独立实例c2704d51、草稿3：核对款号100/NAVY/L候选后，补内部展示SKU SYNTHETIC-100-NAVY-L并保存精确映射，执行目录业务校验。当前revision3/validated、validation_run3、issues为空、can_submit=true；owners显示草稿mapped，正式归属仍空，V2正式忽略及原因仍保留。交接用户刷新http://127.0.0.1:56956/catalog/imports/3，核对映射后提交审核、生成批准预览、填写原因并确认批准。尚未提交或批准，不预先标记解除忽略或user_verified。下一次核对以实际生成版本号为准。本批无需Skill，现有API准备虚构草稿与校验，无业务代码改动或全量测试。

2026-09-11 用户反馈“操作完成”。只读核实新独立实例 c2704d51 的批次 #3 已到 revision1/needs_attention，100-NAVY-L 的 identity_decision=null、target=null，恢复原因“恢复到待审核”；正式目录修订仍为2，owners仍保留V2的原忽略原因。记录恢复到草稿操作已完成、结果符合预期；未重新映射或批准新目录，正式解除忽略仍待后续体验。用户本次报告操作完成，不扩展为整个恢复闭环或正式发布验收通过。本批无需Skill，仅只读核对和状态记录，未改草稿或重跑测试。

用户在独立实例 `0dc6619a3118446ea42f5d4893baafe5` 的批次 #2 明确“体验通过”。只读核实批次已批准、目录 V2 生效，`100-NAVY-L` 仅存在正式忽略记录及原原因；该“正式忽略”路径记为 `user_verified`，不扩展为恢复路径通过。

继续生成 V2 后续草稿时发现正式忽略项只进入 candidate payload 的 exclusions，不进入 mappings；而“恢复到待审核”仅能从 mappings 行触发，造成正式忽略后没有恢复入口。修复 `build_catalog_candidates`：保留 exclusion 的同时生成无正式目标的 mapping candidate，使工作簿投影得到 `identity_decision=excluded` 的可审核行。目标测试先失败（StopIteration）后通过；`backend/tests/unit/catalog/test_candidates.py` 6 项通过，未执行全量回归。

为避免运行中旧实例热加载风险，使用修复后的同一 source 新建独立实例 `c2704d51cd984250b06483e943226d11`（前端 `http://127.0.0.1:56956`、API 14815、独立数据库）。仅用系统虚构 seed 自动复现用户已确认的 V2 正式忽略，生成恢复草稿 #3。新鲜接口核实草稿为 `validated`、可编辑，`100-NAVY-L` 显示正式忽略原因和 V2 归属证据，可执行恢复。状态：正式忽略 `user_verified`；恢复修复 `development_complete / ready_for_user_review`。Skill：`systematic-debugging` 用于根因追踪，`test-driven-development` 用于红绿目标测试，`verification-before-completion` 用于新鲜接口与测试证据。未改七八月实例、未提交/合并/部署或执行发布验收。

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

日期：2026-09-11。归属主线：Stage 4 真实数据试用与反馈修订。

状态：A–C development_complete；当前路径及加载优化 user_verified；D目录V36批准、1202与日报逐日对账完成，V35全量历史快照比较证据待补；E版本82已发布并发现新SKU，ready_for_user_review，未扩展用户确认。

执行约定：各对话内联工作，不启用子代理，不自动提交、push、merge 或部署。按完整使用路径组织工作，集中修改后做一轮定向验证；不按文件拆成红绿循环或逐步审批。Skill 的通用流程服从项目 AGENTS.md。

## 1. 目标、依据与当前边界

目标：当前有效发布报表中的新 Seller SKU 无需先导出工作簿即可被发现；用户可理解未归属数据对分析覆盖的影响，沿现有候选、校验和批准流程完成归属，生成新目录版本并刷新待处理与分析结果。

当前文档中的诊断证据：`1202-Light Blue-XXL` 存在于 2026-08-04 发布事实，诊断时目录 V35 没有相应 mapping/exclusion，catalog_source_refs 也没有记录。1202 当前分析为 22 件、US$771.79，源 SKU 对照的预期为 23 件、US$807.78，差额为 1 件、US$35.99。后者以业务确认此 SKU 确属1202、日期/币种/报告版本一致为前提，不能作为直接改数目标。

本轮源码只读复核确认：

- `backend/app/api/catalog_queries.py::list_catalog_unmatched` 读取 catalog_source_evidence，依赖已采集的目录证据；没有目录时直接返回空列表。
- `backend/app/analytics/style_sql.py::BUSINESS_BUCKETS_SQL` 从发布事实按 mapping/exclusion 分类；其有效版本由分析解析流程提供，不能仅筛 `status='published'` 代替当前发布指针。
- `CatalogUnmatchedPage.tsx` 目前仅显示最多50条安全摘要，未接完整翻页；产品总表已有 `CoverageReconciliation`，优先补强现有说明。

本轮未读取数据库或业务文件，业务数值与 V35 来自现有诊断记录；执行数据修订前只读核实当前值，已有结果发生变化时保留差异，不强行复现旧状态。

环境基线：主工作区 `D:/CLSEN_Data_Web`，分支 `codex/development-throughput`，本轮 HEAD `7de0ee6`；业务工作树 `D:/CLSEN_Data_Web/.worktrees/stage4-1-app-shell`，分支 `codex/stage4-1-app-shell`，本轮 HEAD `ec0a72e`。业务成果包含未提交修改，仅 SHA 不能代表交付版本；执行者记录受影响文件差异/摘要及体验实例版本。

已记录的真实数据范围为授权隔离环境中的 **2026-08-01 至 2026-08-06**，不是整个八月。历史入口 `http://localhost:20601` 仅作定位线索，交付前核实在线情况、实例、角色与数据就绪状态。保留既有有效授权；缺少授权记录时只请求缺失范围，不重复索取已有授权。

## 最新体验确认与下一步

2026-09-11 用户在8月1–6日1202产品总表明确“体验通过，进行下一步”：记录本轮加载优化及批准后1202路径为 user_verified（july-baseline-20260910、目录V36）。本轮只读API核实导入6已approved、修订28；1202销量23件、销售额USD807.78，范围内unmatched=0。未将确认扩展为全Stage4或release_validation；历史V35/日报逐日完整对账仍保留证据待办。下一步E独立虚构演练已准备：2099-05-01，SKU SYNNEW9501-Blue-S，2件/USD119.98，文件位于隔离目录exercises/sku-discovery-2099-05-01；batch85已上传并解析1行（parse baseline87），尚未发布。入口http://localhost:20601/review-advanced/2099-05-01?report_type=business_report&batch_id=85（已核实显示批次85识别确认，可点确认并解析继续；普通日期页在草稿建立前显示未导入）；发布后从同日/catalog/unmatched查询，应直接发现新SKU，不先生成目录导出。等待用户体验发布和发现路径。本批无需Skill，复用既定计划与现有API，未修改业务代码、未运行回归。

## 2. 完整计划表

| 批次 | 职责与交付 | 依赖 | 定向验证与退出条件 | 当前状态 |
| --- | --- | --- | --- | --- |
| A：发布事实发现 | 建立共用未归属判定；待归属 API 查询当前发布事实；支持范围、稳定身份、总数和分页，返回安全来源引用 | 核对现有诊断、发布解析器及权限合同 | 新 SKU 无目录证据即可查询；旧版本、跨范围、映射/有效排除正确；查询无写入 | `development_complete` |
| B：发现到审核 | 发现项可进入现有候选/草稿，明确源范围与目录基线；复用预览、校验、批准和冲突处理 | A 的身份及查询合同 | 无先导出要求；重复操作不重复建候选；过期基线不可直接批准；历史目录不被改写 | `development_complete` |
| C：提示与完整操作路径 | 产品分析显示未归属数量/影响及入口；待归属页可翻页、区分候选状态；处理后刷新并保留筛选 | A API 稳定；B 处理入口稳定 | 一条“分析→待归属→审核→返回分析”路径可用；权限、错误及分页不误导 | `development_complete / ready_for_user_review` |
| D：已知 SKU 与范围内缺口 | 先准备1202已知 SKU 的归属预览；确认后正常批准新版本；其余8月1–6日缺口逐项待业务确认 | A–C 定向验证通过，体验环境更新并核实 | 1202同口径达到核实后的预期；日报不变；剩余缺口可见，不要求清零 | 归属草稿已就绪，待业务批准 |
| E：复体验与收尾 | 用户复体验本缺陷；虚构样本验证再发布新 SKU 的发现；同步主线记录与剩余事项 | A–D 对应交付就绪 | 用户明确确认的路径标 user_verified；正式发布验证仍待部署准备 | `ready_for_user_review`，虚构演练待执行 |

### 2026-09-11 实施交接

用户复体验无日期入口时反馈页面长期停在“正在核对当前发布事实与商品归属”。定向计时确认无日期 `/api/catalog/unmatched` 约0.54秒，根因是 `CatalogUnmatchedPage` 等待当前34款逐款读取审核候选全部完成后才写入待归属主结果。现改为先读取并显示当前发布事实、影响和来源清单，再独立加载“已有审核候选”；候选读取期间显示局部状态，失败时只在该区域重试，不再阻断主清单。新增目标测试模拟候选请求一直未返回，主清单仍可见；1项Vitest及两文件ESLint通过。标准开发脚本先被既有pnpm无TTY依赖目录确认拦截，未安装或清理依赖，随后复用现有Vitest完成等价目标。修复已同步运行源码并由浏览器核实 `/catalog/unmatched` 立即显示13项及1202影响，候选区独立加载；状态 `development_complete / ready_for_user_review`。

业务工作树仍为 `codex/stage4-1-app-shell`、HEAD `ec0a72e` 加保留的未提交成果。A 新增 `backend/app/catalog/unmatched_repository.py`，并扩展 `/api/catalog/unmatched` 的日期、退货口径、准确总数、分页、事实/目录基线、影响与候选状态合同。GET 在只读一致性事务中从当前发布指针和活动事实发现来源，不要求 `catalog_source_refs` 预先存在，也不创建草稿或目录写入。B 继续复用既有目录导出、在线审核、校验、预览和批准流程；C 补齐待归属页、产品总表和款式详情的覆盖提示、同口径跳转、分页、返回地址及错误重试。

隔离体验实例 `b2f5960b07c74303ac2d26bf82d3be43` 已从同步源码完整重启并保持在 `http://localhost:20601`。实际 MySQL 请求 `/api/catalog/unmatched?from=2026-08-01&to=2026-08-06&return_basis=event_date&page=1&page_size=25` 返回目录 V35 / 发布修订35、13个去重待归属身份，合计16件、US$614.84及1件退货。`1202-Light Blue-XXL` 来自2026-08-04当前发布版本66，经营影响1件/US$35.99，`source_ref_id=null`，读取前没有候选。

D 已生成 export 6 和在线审核草稿 import 6，并仅保存1202的两项归属预览：新增 `1202 / Light Blue / XXL` 稳定变体，并将精确 Seller SKU 映射到该变体。草稿仍为 `needs_attention`，其余12个未知SKU保留24个阻断项；当前目录仍为V35，产品分析仍为22件/US$771.79，日报与历史目录未改。1202在待归属API中现显示 `draft` 并链接 `/catalog/imports/6`。这份草稿可审阅，但没有提交、生成批准预览或批准；达到23件/US$807.78仍以业务确认和正常批准后的对账为准。

开发定向证据：Python编译与受影响文件Ruff通过；`backend/tests/unit/test_catalog_api.py` 5项通过；`CatalogUnmatchedPage`、`CoverageReconciliation`、`ProductLedgerPage`、`ProductDetailPage` 共13项前端测试通过。前端完整typecheck仅剩既有 `MergeDecisionMatrix.test.tsx:170` 的可空 `reason` 错误，与本批文件无关；未运行完整回归、双MySQL、E2E、性能或部署演练。实际Skill：`executing-plans` 用于按本计划实施，沿用 `systematic-debugging` 的根因证据。

推荐依次分发 A → B → C → D → E。A–C 使用同一业务工作树时必须串行交接，禁止两个对话同时修改同一工作树或更新同一体验实例。可提前只读研究下一批，不自行启动后台任务或新增对话。E 不再重跑 A–C 已有效通过的检查。

## 3. 共用业务与接口合同

### 3.1 身份与范围

- 账号、站点及 report_source_scope_id 均按服务器授权范围解析，客户端筛选不能扩大权限。范围不明确时明确报错/要求选择，不默认为所有账号。
- 沿用 report_source_keys 的完整 Seller SKU 匹配规则：scope、match_sha256 和 match_bytes。哈希不单独充当身份，不按款号前缀推断，不新增大小写/空白归一化规则。
- 款式、稳定变体与 Seller SKU 映射分别处理；确认1202归属时同时核对颜色 Light Blue、尺码 XXL 及目标稳定变体，存在变体则复用。
- 经营与退货来源均使用各自已有有效事实/去重规则；退货日期口径保留 report_date/event_date 区别，不把退货数量当销量，也不改变既有指标定义。

### 3.2 有效事实与目录

- 复用当前分析的有效发布版本解析、active 行、最新 source key 与退货去重语义；被替换版本、草稿、失效事实不进入当前待办。
- 一次查询固定目录版本与发布事实集合，使列表、总数和影响来自同一读取基线；返回可追溯版本/一致时间。翻页基线变化时提示刷新，不声称多次读取天然属于同一快照。
- 当前待归属默认按当前已批准目录判定。历史目录、fact_basis=snapshot 的分析维持原合同，跳转当前待办时明确口径变化，不能用当前待办数量冒充历史覆盖结果。
- 没有已批准目录时仍发现有效来源，标明需要初始化并使用既有初始化流程，不能返回“没有未归属数据”。
- 已批准有效排除不列为待归属，草稿中的排除/映射不提前生效；恢复排除或新目录切换后重新判定。

### 3.3 API 交接字段与兼容

A 沿用 `/api/catalog/unmatched` 并交付具体请求/响应示例，字段名称在A结束时写入本计划供B/C沿用；下表规定必须表达的含义。优先扩展既有 API，不创造第二套归属系统。

| 内容 | 合同 |
| --- | --- |
| 输入范围 | 授权账号/站点、日期范围、报告类型与适用退货日期口径；未传日期表示授权范围内当前有效发布集合，响应明确实际范围 |
| 读取基线 | 所用 catalog_version（可为空）、事实口径及一致时间/版本引用；复用现有来源结构 |
| 分页 | 保留 page/page_size/items，补准确 total_items；total_items 明确表示同一范围下去重 SKU 身份数；使用稳定排序 |
| item 身份 | 不依赖 catalog_source_refs 已存在的稳定来源/身份标识；不能伪造 source_ref_id，缺失时显式为空或省略并同步消费者 |
| 来源摘要 | 使用现有安全编码、截断和敏感输出规则；报告类型、归属日期、发布版本和源记录引用可追溯。不可定位原CSV行时明确说明 |
| 影响 | 整个筛选范围的未归属件数、金额（标明币种）、退货量与事实记录数，不能仅合计当前分页；不同币种分开 |
| 处理状态 | 未开始、已有相关待审核候选及可操作入口；候选存在时仍属未归属，直到正式批准；遵守读取与处理权限 |

查看待归属 GET 不采集证据、不建草稿、不写审计业务记录。用户显式选择进入候选处理后，沿用既有写接口保存来源证据和审核上下文。禁止浏览器端抓取所有来源自行归属；查询在数据库内过滤、聚合和分页，不为本修复新建 Worker、物化缓存或迁移架构。若出现实际查询瓶颈，再凭查询证据提出必要索引变更。

SKU 数、事实行数与审核任务数分别展示。同一 SKU 跨多日报出现只计一个对应范围的待归属身份，但有效事实的数量和金额按原口径加总；同名 SKU 不跨账号/站点合并。

## 4. 分批执行内容与文件职责

以下路径均相对业务工作树 `D:/CLSEN_Data_Web/.worktrees/stage4-1-app-shell`。列出的现有文件已只读定位；执行者只读所属文件和必要依赖，按实际改动选择测试节点，不遍历全部模块。

### A：修复发现机制

主要文件：`backend/app/api/catalog_queries.py`（API）；`backend/app/analytics/style_sql.py`、`style_repository.py`（现有事实口径）；`backend/app/catalog/scope_repository.py`（仅需复用范围解析时）。如现有模块无法合理承载，新增 `backend/app/catalog/unmatched_repository.py` 封装发现查询，避免 API 中重复大段 SQL。

- [x] 复核当前诊断涉及的函数和有效发布解析，保留既有复现；用目标测试表达“发布事实存在、目录来源证据不存在”的缺陷。
- [x] 实现当前事实发现、完整身份匹配及有效排除；经营/退货遵循既有分析规则，不改变映射指标。
- [x] 实现空目录、分页、去重计数、安全摘要、范围与基线；复用目录快照协调器的当前发布事实选择，避免另建事实选择规则。
- [x] 运行A受影响节点并在授权隔离MySQL执行只读语义核对；具体响应、文件与版本见本计划“实施交接”。

输入：已诊断缺陷、现有分析口径。输出：可供B/C消费的发现 API 和来源身份合同；没有生成业务候选或变更目录。

### B：打通处理入口

主要文件：`backend/app/api/catalog_imports.py`、`backend/app/catalog/import_service.py`、`import_repository.py`、`commands.py`；候选冻结复用 `backend/app/worker/catalog_exports.py` 的必要既有逻辑，不要求下载 XLSX。仅改实际阻塞的文件。

- [x] 接收A的来源身份与筛选基线；复用已有候选生成路径，让未采集来源可形成带证据的候选，明确目标目录版本。
- [x] 显式写操作才建立来源/草稿；已有相关草稿时提供继续入口，重试遵守现有操作令牌与幂等机制。
- [x] 来源被替换、目录已更新或映射冲突时仍使用现有刷新/重校验、revision与批准权限合同，不自动套用过期批准。
- [x] 保留既有“批准后生成新目录版本并保留历史”的流程；本批只完成入口和草稿交接，没有执行真实批准。

输入：A API及身份合同。输出：从发现项到既有候选审核的可用接口/路由；本批在可抛弃测试环境验证写流程，不自行批准真实1202归属。

### C：补齐提示与用户路径

主要文件：`frontend/src/features/catalog/CatalogUnmatchedPage.tsx`、`catalogApi.ts`；`frontend/src/features/products/CoverageReconciliation.tsx`、`ProductLedgerPage.tsx`、`ProductDetailPage.tsx`、`productAnalyticsApi.ts`；只按实际需要修改关联样式。

- [x] 补强现有覆盖说明：已归属、已排除、未归属分开；未归属不为零时清楚说明商品汇总仅覆盖已归属部分，保留原日报总计。
- [x] 产品总表到待归属传递支持的范围；未知SKU提示限定为账号与时间范围，不伪装成已确定款式归属。
- [x] 待归属接入总数/翻页、来源摘要、已有候选状态与B入口；只读影响说明和处理权限继续沿用服务端合同。
- [x] 返回保留日期与适用筛选；重试清除旧错误，加载/失败不显示“没有未归属”。批准后的数据刷新待D实际批准后核对。
- [x] 受影响组件定向检查通过并准备3–5步体验路径；未改ProductTrendChart。

输入：A响应示例、B处理入口。输出：一条完整可体验路径；不新增整站重设计。只有流程审查实际需要时使用 product-design:audit，布局达到整页调整范围时才使用 frontend-design。

### D：修复现有缺口

- [x] 从当前计划索引定位已授权副本、隔离实例和账号；只读确认8月1–6日发布集合、当前目录、1202及所有未归属项，未读取/枚举项目data、搜索原件或连接业务数据库。
- [x] 为 `1202-Light Blue-XXL` 准备完整归属草稿；确认V35没有该稳定变体，草稿新增Light Blue/XXL并列明8月4日、1件、US$35.99及发布版本66。
- [x] 已交付可审阅草稿并停在业务决定前；没有把计划实施授权解释为真实目录批准授权。
- [x] 批准生成目录V36；1202同口径23件/807.78及日报逐日与总计对账已完成，按既有收尾证据及用户确认记录，不重新改数。
- [ ] V35全量映射/排除快照批准前后不变：缺批准前完整快照或摘要，保留未验证状态；1202单商品别名比较不能替代此项。
- [x] 其他12项已随用户批准的导入6/目录V36处理；8月1–6日待归属0，经本轮只读确认。范围不扩展为全八月。

输入：A–C完成且隔离实例核实可用、有效业务授权。输出：新目录版本/差异、1202核对结果、其余缺口清单；已有日报与其他功能体验确认继续有效。

### E：复体验与记录

交付用户的操作路径：

1. 打开已核实的8月1–6日产品分析，核对日期、账号、目录版本和未归属影响说明。
2. 从提示进入待归属，检查范围、SKU数量、来源及分页；已处理1202项应消失，其他未确认项仍在。
3. 查看1202及目录版本差异，核对实际已确认的归属与23件/807.78预期，确认日报总计未变化。
4. 在明确虚构日期/样本的独立演练中发布含新SKU的报表，刷新后直接发现待归属，不先导出；此操作仅在已有授权覆盖演练发布时执行。
5. 用户确认本路径或反馈具体问题；仅修正并复体验受影响部分。

样例检查不要求全局推送或WebSocket；“立即发现”指发布成功后下一次读取/明确刷新可见。真实日期不用于缺陷复现演练。

用户反馈先更新本计划批次表，再同步主工作区 `docs/workflow/project-plan-index.md` 与 `docs/operations/development-workflow.md` 的同项记录，注明范围、版本/实例、未解决项及实际Skill使用。不得用旧待体验记录覆盖新确认，不自动标整体Stage4完成或进入Stage5。

## 5. 定向验证矩阵

| 场景 | 主要批次 | 必须验证的结果 |
| --- | --- | --- |
| 首次发布新SKU且无目录来源证据 | A | 首次GET即发现；读取前后无新证据/草稿/目录写入 |
| 无批准目录 | A/C | 有效来源可见且提示初始化，非“无未归属” |
| 同SKU多日报、多来源行、经营与退货 | A | SKU身份去重，事实指标保留各自有效记录与日期规则 |
| 重传/替换发布、失效事实 | A | 只计当前有效版本，旧版本不重复；退货既有去重有效 |
| 同名SKU跨账号/站点、非法范围 | A/B | 不串范围、不泄露摘要，未授权读写被拒绝 |
| 已映射、有效排除、草稿排除及恢复 | A/B | 已批准状态生效，草稿不提前改变分析；恢复后按基线重新发现 |
| 多于50个SKU | A/C | 准确总数、可翻页、稳定排序，影响不局限当前页 |
| 不同目录/事实基线 | A/C | 当前与历史/快照口径明确；基线变化可识别，不伪称一致 |
| 重复创建、过期批准、并发修改 | B | 幂等重试，无重复候选；过期revision/目录基线按现有合同拒绝并刷新 |
| 批准后返回、请求失败后重试 | C | 待归属/目录/分析同步更新；保留适用筛选，旧错误被清除 |
| 金额/数量对账 | D | 同币种Decimal金额、日报不变、1202差额可解释；历史快照不改 |
| 再次发布新SKU | E | 独立虚构演练下一次读取可见，原缺陷不再依赖导出规避 |

已有目标测试入口（只选择实际受影响节点，不默认全跑）：

- A：`backend/tests/unit/analytics/test_style_sql.py`、`backend/tests/unit/test_catalog_api.py`；实际数据语义需必要的 `backend/tests/integration/test_product_analytics_reconciliation.py`、`test_catalog_scope.py` 目标，不能只凭SQL字符串断言证明正确。
- B：`backend/tests/unit/worker/test_catalog_exports.py`；必要的 `backend/tests/integration/test_catalog_api_workflow.py`、`test_catalog_approval.py`、`test_catalog_concurrency.py` 目标。
- C：`frontend/src/features/catalog/CatalogUnmatchedPage.test.tsx`、`frontend/src/features/products/CoverageReconciliation.test.tsx`，涉及页面联动时选 `ProductLedgerPage.test.tsx` / `ProductDetailPage.test.tsx` 中受影响现有检查。

新缺陷没有覆盖时补有价值的目标测试，节点名由实施者定义并记录。使用**业务工作树自身**的脚本，避免主工作区脚本跑到旧代码：

```powershell
Set-Location 'D:\CLSEN_Data_Web\.worktrees\stage4-1-app-shell'
# A的一个已有SQL约束节点示例，不能代替数据库语义验证
.\scripts\run-dev-check.ps1 -Kind Backend -Targets 'backend/tests/unit/analytics/test_style_sql.py::test_latest_source_keys_are_publication_and_single_style_bounded'
# C的目标组件示例，仅在该组件改变时运行
.\scripts\run-dev-check.ps1 -Kind Frontend -Targets 'frontend/src/features/catalog/CatalogUnmatchedPage.test.tsx'
```

MySQL使用 `scripts/test-mysql-matrix.ps1 -DevelopmentTests` 的显式目标模式，执行前读取参数声明，指定本任务可抛弃单版本MySQL；不借用真实试用库运行pytest或迁移业务库。普通定向预算约3分钟，MySQL约10分钟，超出时说明必要性，不自动扩大验证。复用已有依赖，不触发重复安装；完整回归、双MySQL、性能和恢复演练留部署准备。

## 6. 交接格式与分发提示词

每批在现有交付记录中附：批次、修改文件、代码SHA及未提交差异标识、实际检查与结果、接口/路由变化、体验实例和数据前置、未解决事项、下批可开始条件、实际Skill及用途。涉及A合同新增字段时附一份虚构示例，禁止贴凭据或真实原始报表到计划中。

可直接发送给目标对话：

```text
请读取 D:\CLSEN_Data_Web\AGENTS.md 和主工作区 docs/workflow/project-plan-index.md 中“新发布SKU漏入待归属”的最新条目，再读取：
D:\CLSEN_Data_Web\docs\superpowers\plans\2026-09-11-published-sku-discovery-and-assignment-fix.md

本对话仅执行我指定的批次；先确认该批依赖已交付，再沿用上批接口和证据。业务代码位于 D:\CLSEN_Data_Web\.worktrees\stage4-1-app-shell，主工作区维护权威计划。保留全部未提交成果，开始前确认没有其他对话正在修改相同文件或实例；不要以HEAD代替未提交版本。

内联执行完整使用路径，一轮定向验证后交付结果及可用体验入口。遵守数据与已有授权范围，不因分发计划自动批准商品归属、不扩大为整个八月。未指定的批次、订单指标、Stage5和部署不在本轮范围。
```

在该提示词末尾追加对应一句：

| 分发目标 | 追加指令 |
| --- | --- |
| 对话A | 本轮执行批次A。交接发现API的具体字段示例、身份/范围/版本合同及定向证据。 |
| 对话B | 本轮执行批次B。先核对A交接，接通发现项到现有候选审核，不批准真实商品归属。 |
| 对话C | 本轮执行批次C。先核对A/B交接，交付分析到待归属再返回的一条完整路径。 |
| 对话D | 本轮执行批次D。核实已授权隔离范围，先生成1202归属预览；实际批准依照已明确的业务授权，其余未知项保留待确认。 |
| 对话E | 本轮执行批次E。复用有效开发证据，准备本缺陷的用户复体验与授权虚构演练，同步最新确认与剩余缺口。 |

本计划不替代实际运行结果；文件创建和计划审阅完成不等于A–E开发、业务批准或体验通过。
