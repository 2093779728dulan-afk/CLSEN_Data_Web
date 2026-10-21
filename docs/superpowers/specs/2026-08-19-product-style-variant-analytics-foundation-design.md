# 商品款式主档与变体趋势基础设计（P0）

- 日期：2026-08-19
- 状态：2026-08-20 原始基线已书面批准；Task 1 successor candidate 待再次书面批准，批准前不得开始 P0 业务编码
- 实施顺序：先于《成品生产订单与完工入库实施计划》
- 适用范围：当前站点、单一 Amazon Seller Account、美国站

## 1. 背景

业务最终需要把运营下单、工厂生产、广州成品仓、Amazon 出货、海运在途、FBA 实收、销售日报和退货日报按具体 SKU 串联。这里的 SKU 必须具体到“一个款式的一个颜色和一个尺码”。

现有产品总表和商品卡只从 Seller SKU 文本临时拆出款号、颜色和尺码，并按款号汇总。它没有权威款式名称，也没有稳定的内部 SKU 身份，因此产生两个直接问题：

1. 同款不同变体的 Amazon Listing 标题不同，产品总表显示“多个变体名称”；
2. 每日趋势只保留款号总计，无法按颜色或尺码比较。

这不是单独的前端文案问题。当前契约会为每个 Seller SKU 选择最近一次发布的原始标题，再对同款标题做精确比较；只要不同变体标题不同，商品名称状态就是 `multiple`。当前趋势又在款号层提前合并全部 Seller SKU，浏览器无法恢复已经丢失的颜色和尺码维度。

因此，在生产订单与完工入库计划开始前，先交付独立 P0“商品款式主档与变体趋势基础”。P0 建立权威款式名称和稳定变体身份，解决当前看板问题，并成为后续生产、库存及 Amazon 映射阶段共同复用的身份基础。

## 2. 真实输入核验

用户确认以下两类 CSV 是每日上传、审核和发布的事实报表，不是商品主档：

- `20260701-BusinessReport-02-7-26.csv`；
- `亚马逊物流买家退货-20260701-80191020636.csv`。

只读核验结论如下：

### 2.1 经营日报

- UTF-8 BOM、逗号分隔，共 22 列、24 条数据；
- 与当前 `business_report_v1` 规则一致，可完整解析；
- 文件内容没有报告日期列，`2026-07-01` 仅来自文件名，仍需人工确认；
- 24 个 Seller SKU 均符合当前严格三段格式，归属 9 个候选款号；
- 其中 5 个款号在单份日报内已经存在多个不同标题，不能靠截取颜色或尺码安全生成标准款名；
- 源列“转化率 - 总计”的样本值实际表现为会话占比；真正等于“订购件数 ÷ 会话数”的是“商品会话百分比”。

### 2.2 退货日报

- 13 列、10 条数据，与当前 `return_report_v1` 规则一致；
- `return-date` 是带偏移的事件时间，共涉及两个事件日，且不完全等于文件名报告日；
- 10 个 Seller SKU 均符合当前严格三段格式，归属 6 个候选款号；
- 实际 SKU 组合不是颜色和尺码的完整笛卡尔积，系统只能采用真实出现的变体；
- 订单号、物流牌照号和买家留言属于敏感来源字段，不进入商品主档或普通看板。

### 2.3 当前全量数据事实

当前数据库只读核验得到：

- 34 个可解析候选款号；
- 224 个不同 Seller SKU 原值，其中 222 个符合当前严格三段规则，2 个异常值进入待处理队列；
- 28 个款号存在多个最新原始标题；
- 91 个 Seller SKU 的标题曾随报告日期变化；
- 125 个 Seller SKU 原值只出现在经营日报，7 个只出现在退货日报，92 个同时出现，三类合计 224；
- 异常 Seller SKU 必须进入待处理流程，不能被临时解析器自动升格为正式身份；
- Parent ASIN 曾随时间变化，不能作为稳定款式或具体变体主键。

上述数字用于冻结 P0 的真实验收基线，不表示系统只能支持这些数量。

## 3. 目标与非目标

### 3.1 目标

P0 必须完成：

1. 一款一个稳定 `style_id`、一个款号和一个权威标准商品名称；
2. 一个实际款色码一个稳定 `sku_id`，身份不依赖 Seller SKU 文本；
3. 通过系统生成的标准 XLSX 初始化并修订商品主档；
4. 从全部历史日期的当前发布版经营和退货日报预填候选；
5. 保存来源颜色、尺码、原始标题和外部标识证据，但不把它们当内部主键；
6. 对 Seller SKU 做带 Seller Account 和 Marketplace 作用域的精确映射；
7. 未知、歧义和冲突项进入人工队列，不自动创建正式身份；
8. 产品总表显示标准商品名称，并保留原始标题差异提示；
9. 每日趋势支持款式总计、颜色比较和选中颜色后的尺码比较；
10. 明确订购件数、销售额、退货件数、会话数、转化率、日期和缺报口径；
11. 目录、款式、SKU 和映射均可版本化、审计和重放；
12. 让后续生产订单直接复用 P0 的稳定身份和 SKU revision。

### 3.2 非目标

P0 不包含：

- 生产订单、工厂完工、广州库存的业务实现；
- FBA 出货、海运在途或 FBA 实收；
- 多账号、多站点管理界面；
- FNSKU、Child ASIN、Parent ASIN 的自动身份解析；
- E0 的完整 Amazon mapping snapshot、逐行 evidence entries/candidates 和历史回填任务；
- 根据标题相似度、翻译、颜色近义词或 ASIN 自动合并 SKU；
- 两个既有 `sku_id` 的合并、生产事实重绑或删除；
- 从当前报表推导真正的去重订单数；
- 把全部 18 个经营指标加入首版趋势。

## 4. 已批准产品决策

| 主题 | 决策 |
| --- | --- |
| 款式名称 | 人工维护唯一、权威的标准商品名称；Amazon 标题只作证据 |
| 初始化来源 | 系统标准 XLSX，不把每日 CSV 当主档 |
| 候选生成 | 从全部历史日期的当前发布版经营和退货日报预填 |
| 异常处理 | 必须映射、修正或填写理由排除；目录草稿有未处理项时不得批准 |
| 颜色尺码 | 同时保存来源原值和标准展示值，统计按标准值聚合 |
| Seller SKU 变更 | 人工确认后，新旧 Seller SKU 可以映射到同一稳定 `sku_id` |
| 当前 Amazon 范围 | 单一 Seller Account、美国站；数据结构保留作用域 |
| 修订 | 每次批准生成不可变目录版本，旧版本可追溯和重放 |
| 退货日期 | 默认实际事件日，可切换报告所属日 |
| 首版指标 | 订购件数、销售额、退货件数、会话数、重算转化率 |
| 趋势层级 | 默认比较颜色；选择颜色后比较尺码；明细表列出全部实际 SKU |
| 总体方案 | 分层 P0；Seller SKU 精确映射先行，FNSKU/ASIN 完整快照留给 E0 |
| 主档批准权限 | `data_manager` 可批准自己提交的普通变更；高风险既有身份变更仅限 `admin` |

## 5. 术语与核心不变量

### 5.1 术语

- **款式（Style）**：款号层的稳定商品族，拥有唯一标准商品名称。
- **变体（SKU）**：具体到一个款式、一个标准颜色和一个标准尺码的稳定身份。
- **来源值**：日报中的 Seller SKU、解析颜色/尺码、Listing 标题、ASIN 和 FNSKU。
- **标准值**：经人工确认的款号、标准名称、标准颜色、标准尺码和内部展示 SKU。
- **商品目录版本**：一次批准时全部款式 revision、SKU revision、Seller SKU 映射和排除决定的不可变集合。
- **当前目录**：每个站点唯一的当前商品目录版本指针。
- **候选**：从当前发布日报生成、尚未被批准为正式身份的款式、变体或映射建议。
- **未归类**：尚未映射到稳定 `sku_id` 的发布行。
- **明确排除**：经授权用户填写理由、确认不应进入正式商品主档的来源标识。
- **事实口径（fact basis）**：分析所读日报事实的版本选择；`current` 表示请求快照中的当前发布指针，`catalog_snapshot` 表示目录批准时冻结的 publication snapshot。
- **publication snapshot**：一次一致性读取中实际使用的日报 publication/version 成员、指针 revision、来源 scope、站点配置和截止点的不可变集合。

### 5.2 身份链

当前事实分析链固定为：

`请求内当前 publication 指针 → active 日报行 → 指定商品目录版本中的作用域 Seller SKU 映射 → sku_id → style_id`

历史精确重放链固定为：

`目录 publication_snapshot 成员 → 该成员的 active 日报行 → 同一目录版本映射 → sku_id → style_id`

生产链固定为：

`生产或库存事实行 → sku_id + 当时 sku_revision_id + 当时 style_revision_id`

日报原始行不因目录修改而更新。当前分析采用当前目录重新归类；只有同时指定目录版本和 `fact_basis=catalog_snapshot` 才称为对该目录批准时结果的精确重放。`fact_basis=current` 不允许搭配历史目录，避免“旧身份＋新事实”产生无法解释的缺口。

### 5.3 不变量

1. `style_id` 和 `sku_id` 一经创建永久稳定，不由展示字符串构造。
2. 同一站点的规范化款号只能对应一个款式。
3. 同一站点、同一款式的规范化“标准颜色＋标准尺码”只能对应一个 `sku_id`。
4. 同一站点的规范化内部展示 SKU 只能对应一个 `sku_id`。
5. 任一曾在批准目录中使用的款号键、款式＋颜色＋尺码键和内部展示 SKU 键永久保留给原 `style_id` 或 `sku_id`；修改或停用不释放旧键，P0 不提供解除保留的接口。
6. 需要冻结身份的生产或库存事实只能绑定一个 `sku_id`、一个真实存在的 `sku_revision_id` 和一个真实存在的 `style_revision_id`；日报行在 P0 中通过明确的商品目录版本解析，不伪造持久化 SKU revision 绑定。
7. 一个商品目录版本内，同一 Seller Account、Marketplace 和 Seller SKU 匹配键只能指向一个 `sku_id`。
8. 多个 Seller SKU 可以经人工确认后指向同一个 `sku_id`。
9. Seller SKU、FNSKU、ASIN、标题、款号、颜色和尺码都不能代替稳定内部 ID。
10. Parent ASIN 只作证据，不能直接绑定具体 SKU。
11. 颜色×尺码组合只来自正式 SKU，不生成笛卡尔积。
12. 已批准版本、revision、来源证据和审计事件不能更新或删除。
13. 当前投影必须与当前目录版本引用的 revision 完全一致。
14. 草稿中的任一阻断项会阻止整份目录批准，不允许部分批准。
15. 未匹配和明确排除的数据必须可计数、可筛选，不能静默丢弃。
16. 一次候选导出或分析响应的全部读取必须固定在同一个 MySQL `REPEATABLE READ` 一致性快照内，不能混合事务中途切换前后的目录、日报或时区版本。
17. 一次分析只能选择一套事实来源；`current` 与 `catalog_snapshot` 不得在同一响应、同一汇总或回退分支中混读。
18. `row_origin=system` 且正式 ID 为空的候选只有进入第 10.3 节批准投影时才创建身份、revision、目录成员或 reservation；未进入投影的候选永久只作该导入批次的审计证据，不能产生孤立正式身份。

## 6. 架构与组件边界

P0 分为六个边界清晰的组件：

1. **商品目录领域**：管理款式、SKU、revision、目录版本、当前指针和权限；
2. **候选生成器**：只读取当前发布日报，生成候选、证据和来源快照摘要；
3. **安全工作簿组件**：生成和解析固定 XLSX 契约，不访问数据库业务状态；
4. **目录审核服务**：保存不可变上传、草稿修改、校验、风险分类、预览和批准；
5. **商品分析查询**：按指定目录版本在 MySQL 中聚合款式、颜色、尺码和 SKU；
6. **前端商品主档与商品看板**：只组合 API，不在浏览器推断身份或重算跨行业务规则。

候选生成器不创建正式款式或 SKU。安全工作簿组件不决定权限。目录审核服务不读取浏览器计算的差异摘要作为权威。商品分析查询不读取草稿目录，也不把 Python 内存聚合作为默认查询路径。

### 6.1 初始化数据流

1. 取得当前站点的 Seller Account scope 和 Marketplace scope；
2. 枚举全部日期、两种报表的 `dataset_publications` 当前指针；
3. 只读取当前版本中的 active 发布行；
4. 按 Seller SKU 精确规范键汇总来源标题、标识、日期和出现次数；
5. 运行严格三段候选解析，异常和冲突进入待处理集合；
6. 固化来源 publication ID、版本、行摘要及候选生成规则版本；
7. 生成带不可变导出 ID 的 XLSX；
8. 用户填写、上传、校验和审核；
9. 批准事务创建 revision、目录版本和当前指针；
10. 当前产品分析开始使用新目录版本。

### 6.2 当前查询数据流

1. 读取当前目录指针，或校验用户有权访问的显式旧版本；
2. 在指定日期和报表版本范围内读取当前发布行；
3. 以目录版本、Seller Account、Marketplace 和 Seller SKU 匹配键连接 `sku_id`；
4. 连接该目录版本的 SKU 和款式 revision；
5. 在 MySQL 按日期、`style_id`、标准颜色、标准尺码或 `sku_id` 聚合；
6. 单独返回报表覆盖、身份匹配覆盖、未归类和排除计数；
7. 前端仅负责选择指标、系列和展示。

## 7. 逻辑数据模型

本节定义领域事实和约束。实施计划再确定最终表名、索引长度和迁移 SQL。

### 7.1 款式

`product_styles` 第一版保存以下稳定身份和当前投影字段：

- `site_id`；
- `style_id`；
- 当前款号及规范化键；
- 当前标准商品名称；
- 启用状态；
- 数值 `current_revision`；
- 创建和最近变更时间。

`product_style_revisions` 每行保存：

- 稳定 `style_revision_id`；
- `site_id + style_id + revision`；
- 完整款号、标准名称和状态快照；
- 变更原因、操作者和时间；
- 来源目录导入或管理命令定位符。

revision 从 1 开始。`product_styles.current_revision` 是乐观并发计数，不建立会造成首条插入循环的非空反向 revision 外键。

### 7.2 SKU

`product_skus` 继承并调整原生产计划中的稳定 SKU 模型，第一版字段为：

- `site_id`；
- `sku_id`；
- `style_id`；
- 当前内部展示 SKU 及规范化键；
- 当前标准颜色、标准尺码及规范化键；
- 启用状态；
- 数值 `current_revision`。

`product_sku_revisions` 保存稳定 `sku_revision_id`、所属 `style_id` 和完整 SKU 字段快照。款号不再重复作为 SKU 的独立身份来源。

所有后续生产订单、完工行、入库行和库存来源都同时保存 `sku_id`、当时的 `sku_revision_id` 和当时的 `style_revision_id`。这样款号或标准名称的后来修订不会改写历史单据，也不需要因为款式名称变化而为全部子 SKU 级联创建伪 revision。

`product_sku_revisions` 只复合引用稳定 `style_id`，不固定某个 `style_revision_id`。商品目录版本分别选择一个 SKU revision 和其所属款式的 style revision；生产或库存事实再同时冻结这两个 revision。目录 SKU 成员必须通过复合外键保证所属 `style_id` 在同一目录版本中恰有一个 style revision 成员。

`product_identity_key_reservations` 保存每个曾批准的款号键、款色码键和内部展示 SKU 键及其原稳定 ID。当前字段改变后旧 reservation 仍存在；所有创建和修订事务都必须先检查 reservation，防止历史身份键被另一个 ID 复用。

### 7.3 商品目录版本

`product_catalog_versions` 保存：

- 站点内单调递增版本号；
- 可空基础版本；
- 工作簿 schema 版本、规范化 schema 版本；
- 唯一 ready `fact_snapshot_tuple_id`；该 tuple 权威拥有 `publication_snapshot_id`、`return_dedup_snapshot_id`、`site_config_version_id`、`fact_cutoff_at` 和完整性摘要；
- 导入、验证和批准摘要；
- 风险级别 `normal|high`；
- 批准人、批准时间和原因；
- 不可变状态。

版本成员分别引用：

- 本版使用的全部 `style_revision_id`；
- 本版使用的全部 `sku_revision_id`；
- 本版带作用域的 Seller SKU 映射；
- 本版明确排除的来源标识及理由。

`publication_snapshots` 保存 `report_source_scope_id`、`site_config_version_id`、候选规则版本、规范化规则版本、`coverage_start_date`、`coverage_end_date`、事务开始时间和 `fact_cutoff_at`。首次初始化的 coverage 从该 scope 两类日报最早 dataset report date 取最小值，到截止时间所在业务日；后继导出沿用已批准起点并推进终点。其不可变成员对 coverage 内每个日期、每种报表逐项保存 `dataset_id`、report type、report date、published version ID、publication pointer revision、active-row 数量和 active-row 投影摘要；没有发布版本的应有报告日保存显式 missing 成员。摘要只校验完整性，不能替代可查询成员。active-row 投影摘要只包含 P0 允许的身份与指标字段，禁止直接复用含 order ID、物流牌照号或买家留言的整行 digest。

`return_dedup_snapshots` 固定保存 `site_id`、唯一 `report_source_scope_id`、所覆盖当前退货 publication 成员的规范 `return_publication_set_digest`、规则版本、base/checkpoint、delta depth、状态和不可变决定结构。逻辑上每条 active 退货行都有四状态；物理上不复制全部行：未进入疑似重复组的行按规则版本隐式为 `unique`，只持久化不可变 candidate-group revision、组成员、canonical/人工决定和 snapshot 到 group revision 的 delta 引用。每 32 个 snapshot 或 delta depth 将达到 32 前，在事务外生成只包含当时疑似组的 checkpoint，查询链深永不超过 32。只有逻辑覆盖完整、group 无悬空引用且 digest 校验通过的 `ready` snapshot 可发布。

候选 export 的写事务创建不可变 `fact_snapshot_tuples` 行，固定 `site_id/scope/publication_snapshot_id/return_dedup_snapshot_id/site_config_version_id/fact_cutoff_at/tuple_digest/status`，并用复合外键证明 publication snapshot 的退货 digest 与 ready dedup snapshot 完全相同。只有同一次 RR 读取 payload 最终化出的 tuple 可进入 `ready`；tuple digest 只作完整性校验，不能由批准事务临时对任意四项自由计算。export 和后续 catalog version 都只引用这个已存在的 `fact_snapshot_tuple_id`，四个组成项从 tuple 派生，从而证明它们确实来自同一候选读取。

候选导出先在一个只读 MySQL `REPEATABLE READ` 事务中固定站点配置、当前目录指针、两类日报 publication 指针和 digest 匹配的退货重复决定版本，并在内存/临时 artifact 形成完整规范 snapshot/tuple payload；提交只读事务后，再由独立写事务以 export operation token 幂等持久化这份精确 payload，禁止重读当前指针。写事务完成前 export、publication snapshot 和 fact tuple 状态均为 `building`，不可下载、上传或被目录引用；完整成员、复合约束和 digest 成功，并且物化结果已经原子分类为“通过同一上传验证器的安全 artifact”或“记录完整容量违规且无 artifact”后，export 才进入 `ready`。结构、摘要或非容量类 artifact 失败进入 `failed`，不能伪装成容量超限。目录批准只能引用 export 的 ready fact tuple，不能在批准事务中把部分成员替换成“当时最新值”。已知 Seller SKU 后来新增标题、ASIN、FNSKU 或事实行时，批准预览显示 `evidence_drift` 及新旧摘要，但不改变本版证据；出现新的匹配键、规范化碰撞、scope 变化或基础目录变化时必须显式变基，不能继续批准。

`product_catalog_publications` 保存每个站点唯一的当前目录版本指针和单调 `catalog_publication_revision`。revision 在尚无目录时从 0 开始；approve、restore 或任何未来允许的目录指针切换都必须在同一事务 CAS 当前 revision、把它恰好加 1 并写不可变 publication event，永不回退或复用。草稿不进入该指针，失败事务不消耗 revision。所有需要 `expected_catalog_publication_revision` 的 GET、export 和 preview 都从这条权威行返回值，不能从目录版本号推算。

### 7.4 Seller SKU 映射

P0 的 Seller SKU 映射是商品目录版本成员，不写入生产计划中无 Amazon 作用域的通用 `sku_aliases`。

P0 同时建立一个站点级日报来源 scope。它保存非空 Seller Account scope key、工作簿安全的规范显示名和美国站 Marketplace scope code；显示名由 `admin` 在确认时填写，必须符合第 9.2 节 `T(128)` 安全文本域，不直接复用未经约束的外部账号文本。`admin` 必须在任何 scope assignment 或候选 export 前完成不可逆确认；确认后为每个现有历史 dataset 插入唯一、不可变的 `report_dataset_scope_assignment` sidecar，新导入批次和每日 dataset 在创建事务中插入同一 scope assignment。该过程不更新原日报行或既有 dataset 字段，后续配置变化也不得改写 assignment。P0 不提供切换到第二个账号或站点的界面。

每条映射固定保存：

- `site_id`；
- `catalog_version_id`；
- `seller_account_scope_key`；
- `marketplace_scope_code`；
- Seller SKU 原值；
- Seller SKU 匹配键；
- 目标 `sku_id`；
- 决策来源、操作者、时间和证据摘要。

映射必须以复合外键指向同一商品目录版本内的目标 SKU 成员，不能只引用一个在该版本中不存在的全局 `sku_id`。

日报来源 scope 使用稳定内部 ID；账号显示名称不参与唯一键。内部代码固定为本地单账号范围，Marketplace 内部代码固定为 `amazon_us`。确认和 sidecar assignment 一旦开始，P0 永久冻结该唯一 scope；发现错误只能停止 P0 并进入 E0 的正式 scope 纠错设计，P0 不重写历史、不创建后继 scope，也不允许混合 scope。

P0 当前只有一个 Seller Account 和美国站，但映射唯一键必须包含两个 scope，查询也必须使用日报冻结的来源 scope，不能只凭 `site_id + Seller SKU` 连接。E0 后续把 scope ID 映射到正式 Seller Account/Marketplace 实体，并把已批准映射作为首个完整 snapshot 的候选输入。

### 7.5 来源证据、碰撞和排除

数据库来源证据按实际发布行保存不可变成员，固定包含 scope、Seller SKU 原值与匹配键、report type、publication/version、source row ID 或安全定位摘要、report date、原始标题、Parent/Child ASIN、FNSKU 和该报表契约允许的日期字段。一个 Seller SKU 的多个标题或标识分别保存，不能只保留最新值。

XLSX `来源证据` 不逐条复制会随历史持续增长的完整 tuple，而是上述成员的只读摘要投影。聚合键固定为 `scope + Seller SKU原值 + report type`，每个键恰好一行；它返回首次/最近日期、出现次数、标题/Parent ASIN/Child ASIN/FNSKU 的 distinct 数量、最近标题的安全预览和完整 evidence-set digest。digest payload 精确为 distinct `[[title_or_null,parent_asin_or_null,child_asin_or_null,fnsku_or_null], ...]`：tuple 按四个字段依次比较，null 排在字符串前，字符串按原样 UTF-8 bytes 二进制排序；数组按 RFC 8785 JSON Canonicalization Scheme（JCS）编码为 UTF-8 bytes。digest 固定为 `sha256:`＋payload bytes 的 64 位小写十六进制。

完整 distinct tuple、来源 publication 和安全行定位符只在数据库与第 10.6 节授权页面分页查询。XLSX 摘要行数只随 `Seller SKU原值 × report type` 增长，不随同一 SKU 的标题或标识历史变化增长；工作簿中的系统 evidence row ID 和 digest 用于防篡改，不用预览文本反查身份。

Seller SKU 规范键采用应用层 NFKC＋trim 后的 UTF-8 bytes，并以二进制列或 `SHA-256 + 原字节碰撞复核` 建索引和唯一约束；禁止依赖站点默认的大小写不敏感 collation。多个原值形成同一规范键时建立 collision group，映射 entry 对规范键唯一，全部原值保存在证据成员中。批准只能明确确认全部原值同指一个 `sku_id`，或让碰撞保持阻断；P0 不允许同一规范键的原值分别指向不同 SKU。

身份排除默认按 `report_source_scope_id + Seller SKU匹配键` 跨经营、退货和全部日期生效，并随目录版本保存。若同一键同时出现映射和排除，目录阻断。单个来源行因数据质量被排除属于日报审核决定，不是商品目录身份排除，两者不得混用。

### 7.6 导出、导入和命令

目录工作流固定保存：

- 候选导出 job 的 `export_status=building|ready|failed`；进入 ready 后不可变的 publication 成员摘要、每表行数和 `workbook_status=ready|capacity_exceeded`；
- 不可变原始 XLSX 引用和上传元数据；
- 导入批次、不可变 `source_kind=xlsx|online`、不可变 `owner_id`、解析尝试、解析行和草稿修订；XLSX 的 owner 是上传操作者，online 的 owner 是 `from-export` 创建操作者，rebase 后继继承原 owner；
- 批次单调 `workflow_revision`、单调 `parse_attempt_revision` 和不可猜测解析租约 token；
- 阻断问题、警告确认和异常处理决定；
- 验证运行、差异预览和批准摘要；
- UUID v4 命令 claim、effect 和安全结果定位符；
- 全量审计事件。

原文件内容可复用现有内容寻址存储，但导入批次必须保存本次上传自己的安全原文件名和声明 media type，不能从共享 `raw_files` 记录误取另一批次的元数据。

## 8. 规范化与候选解析

P0 的全部 Unicode 规范化、属性判断和大小写折叠都固定使用 Unicode Character Database 15.1.0 的内置表，不能直接继承宿主语言升级后的默认 Unicode 版本。`seller_sku_match_v1`、`catalog_identity_key_v1` 和 `safe_source_projection_v1` 分别保存自己的算法版本；升级必须新建版本、保留 known-answer fixture，并且不得用新版本重算既有目录键或摘要。

### 8.1 Seller SKU

Seller SKU 匹配键采用 `seller_sku_match_v1`：

1. 保存解析器已经解码的逐字符原值、UTF-8 SHA-256 和规范化规则版本；
2. 对原值执行 Unicode NFKC；
3. 去除首尾 Unicode White_Space；
4. 保留大小写，不做 case-fold 合并；
5. 把结果保存为二进制 UTF-8 bytes，并以 `SHA-256 + 完整 bytes 碰撞复核` 建匹配索引；内部 NUL 或控制字符也不得从证据集合中丢失。

规范结果为空、含不满足 XML 1.0 Fifth Edition `Char` production 的 scalar、Unicode `Cc|Cf|Zl|Zp` 或换行时标记 `unsafe_source_text`，禁止自动候选解析，但仍以系统来源行 ID 和二进制匹配键进入待处理流程，可人工映射或明确排除。非 Unicode-scalar 输入继续由既有严格 UTF-8 解码门拒绝；日志、XLSX 和 HTML 不直接插入这些原始字符。

多个原值形成同一规范键时产生 `seller_sku_normalization_collision`，必须人工确认，不能静默合并。

### 8.2 款号、颜色和尺码候选

现有严格候选规则仍为：

`^[0-9]+-[^-]+-[^-]+$`

它只负责生成“款号－来源颜色－来源尺码”建议，不创建正式身份。只有 Seller SKU 通过第 8.1 节安全字符门、总长不超过 255 个 Unicode scalar 且三个分段分别不超过款号/颜色/尺码的 128 scalar 上限时才运行。字母款号、包含额外连字符、空段、超长或其他异常格式进入待处理表；无法安全展示的候选列为空，完整来源仍通过系统行 ID 访问。

标准款号、颜色和尺码的唯一性比较采用 `catalog_identity_key_v1`：先按 UCD 15.1.0 执行 NFKC，再只删除首尾具有 Unicode `White_Space` 属性的 scalar，随后执行默认、非 Turkic 的 Unicode full case-fold（`CaseFolding.txt` 的 C＋F 映射，不使用 T 映射），最后编码为 UTF-8 bytes；中间不使用区域语言规则或数据库 collation。展示值保留用户批准的大小写和字符，唯一键不得为空。系统不自动翻译、合并近义词或从标题补字段。

### 8.3 内部展示 SKU

内部展示 SKU 是可修订的显示和业务录入编码，不是主键。其唯一键使用同一个 `catalog_identity_key_v1`，以二进制列或 `SHA-256 + 原字节复核` 约束，不依赖 MySQL 默认 collation。旧展示编码在生产阶段按现有设计保留为 `internal_legacy` 别名并继续参与 reservation 冲突检查。修改展示编码不能创建第二个相同款色码，也不能重写历史事实。

## 9. 商品主档 XLSX 精确契约

### 9.1 文件、ZIP 与 OOXML allowlist

第一版只接受 `.xlsx` 和官方 media type `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`；只有扩展名、ZIP 签名、`[Content_Types].xml` 和内部关系全部通过时才兼容声明为 `application/octet-stream`。拒绝 `.xls`、`.xlsm`、加密包、宏、公式、外链、OLE/DDE、隐藏内容和异常 ZIP。

固定容量上限为：`生成信息` 恰好 9 条数据行；其余每张表最多 30,000 条数据行、16 列；六张表合计最多 75,000 条数据行。上传 ZIP 的实际字节数不得超过 `min(APP_STORAGE_MAX_UPLOAD_BYTES, 100 MiB)`，最多 128 个 member；单 member 实际解压内容最多 64 MiB，全部 member 实际累计解压内容最多 200 MiB，单 member 压缩比 `actual_uncompressed_bytes / max(actual_compressed_bytes, 1)` 最多 `200:1`。这些上限支持第 20.5 节固定 fixture 的 11,200 条映射和 22,400 条来源证据，不得由实现另设更小的隐式限制。

候选 export 先生成数据库中的完整候选，再决定能否物化单一 XLSX，绝不为满足上限截断、抽样或拆掉证据。物化资格不只检查行数：生成器必须在临时位置完成最终 ZIP，按与上传端相同的实际字节计数和 allowlist 验证 archive 字节、member 数、每个 member 解压字节、累计解压字节和压缩比；高度可压缩的合法 member 可以改用 `stored`，但不得放宽上传门。任何行数或上述字节/比例容量门超过限制都使 export 仍以 `ready + workbook_status=capacity_exceeded` 用于在线审核，并记录非空 `capacity_violations`；每项固定含 `code=sheet_row_limit|workbook_row_limit|archive_bytes_limit|member_uncompressed_bytes_limit|workbook_uncompressed_bytes_limit|member_compression_ratio_limit`、nullable allowlist `sheet_or_member`、十进制字符串 `actual/limit` 和 `unit=rows|bytes|ratio`。容量内固定返回空数组。128-member 上限属于 ZIP 安全门而非在线兜底容量；固定 allowlist 的生成器若违反 member 数量或 part 契约，必须按非容量安全失败进入 `failed`，不能记录成 `capacity_exceeded`。

容量超限不保留临时或部分 artifact，下载端点返回 409 `catalog_workbook_capacity_exceeded`。用户通过第 13.1 节 `from-export` 入口创建同一快照的在线草稿，分页处理全部行并走完全相同的校验、风险和批准状态机。P0 不接受多工作簿分片导入；这样容量超限会失去 Excel 入口，但不会让商品目录初始化或后继修订停摆。任何可下载的生成文件必须先通过一次 generator→uploader 原样往返验证；生成器产生未知 part、错误关系或其他非容量安全失败时 export 进入 `failed`。

解析前和流式解压过程中都检查重复或 Unicode/路径规范化后冲突的 member、路径穿越、绝对路径、反斜杠、NUL、加密标志、压缩方法、CRC、local/central header 一致性、声明与实际长度、单 member 大小、压缩比和累计解压上限；只允许 ZIP `stored` 或 `deflate`。上传端安全门判定顺序固定为：先按收到的 archive 实际字节检查上传上限；再解析 central directory 并检查结构与 128 个 member 上限；再检查路径、重复/规范化冲突、part/relationship allowlist 及 local/central header；最后才流式检查每个 member 的实际解压大小、累计大小和压缩比。一个文件同时触发多项时只记录最先失败的安全内部诊断，外部仍统一返回 `catalog_workbook_unsafe`；例如 129 个 member 且同时含 unknown part 时，内部原因必须先为 `zip_member_count_exceeded`。恰好 128 个 member 只代表通过数量门，仍须继续通过 OOXML allowlist，因此该数量边界可用独立 ZIP validator fixture 验证。任何一个门失败立即停止继续解压。打开时使用只读模式、`data_only=False`、`keep_links=False` 和安全 XML 解析；库选项和 ZIP header 声明值都不能代替实际字节计数。

`product_catalog_workbook_v1` 只允许以下 part：

- `[Content_Types].xml`、`_rels/.rels`；
- `docProps/core.xml`、`docProps/app.xml`；
- `xl/workbook.xml`、`xl/_rels/workbook.xml.rels`、`xl/styles.xml`；
- 可选 `xl/sharedStrings.xml` 和 `xl/theme/theme1.xml`；
- 恰好六个 `xl/worksheets/sheetN.xml`，其顺序必须与第 9.3 节一致。

`[Content_Types].xml` 只允许且必须精确匹配下表；`sharedStrings` 与 `theme` 行只在对应 part 存在时出现，其他行恰好一次。Default/Override 的 XML 顺序不参与语义，但重复 extension、重复 part name、大小写或 URI 变体都拒绝。

| Extension 或 PartName | ContentType |
| --- | --- |
| Default `rels` | `application/vnd.openxmlformats-package.relationships+xml` |
| Default `xml` | `application/xml` |
| `/docProps/core.xml` | `application/vnd.openxmlformats-package.core-properties+xml` |
| `/docProps/app.xml` | `application/vnd.openxmlformats-officedocument.extended-properties+xml` |
| `/xl/workbook.xml` | `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml` |
| `/xl/styles.xml` | `application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml` |
| `/xl/sharedStrings.xml` | `application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml` |
| `/xl/theme/theme1.xml` | `application/vnd.openxmlformats-officedocument.theme+xml` |
| `/xl/worksheets/sheet1.xml` 至 `/xl/worksheets/sheet6.xml` | `application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml` |

关系只接受 Transitional 完整 URI：

- `http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument`；
- `http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties`；
- `http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties`；
- `http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet`；
- `http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles`；
- `http://schemas.openxmlformats.org/officeDocument/2006/relationships/sharedStrings`；
- `http://schemas.openxmlformats.org/officeDocument/2006/relationships/theme`。

`_rels/.rels` 恰好含前三类各一条，target 分别为 `xl/workbook.xml`、`docProps/core.xml`、`docProps/app.xml`。`xl/_rels/workbook.xml.rels` 恰好含六条 worksheet 关系和一条 styles 关系；`xl/sharedStrings.xml` 或 `xl/theme/theme1.xml` 存在，当且仅当 workbook relationship part 中恰好存在一条对应类型且 target 正确的关系，part 缺失时对应关系也必须缺失。六个 worksheet target 必须互异并按 workbook 中六个 sheet 的 `r:id` 精确映射到 `worksheets/sheet1.xml` 至 `sheet6.xml`。关系 ID 在各自 part 内唯一，禁止 `TargetMode=External`，每个 target 规范化后必须解析到上述 allowlist 中的现有 part，且不得存在其他 `.rels` part。Strict URI、缺失/悬空/重复关系、未知 content type、未知 part 或未知 relationship 一律失败关闭。

`xl/workbook.xml` 可以省略 `<definedNames>`，也可以包含一个没有 `<definedName>` 子元素的空 `<definedNames/>`；任何非空 `<definedName>` 都拒绝。`externalLinks`、`connections`、`customXml`、`vbaProject`、宏表、`embeddings`、`oleObjects`、DDE、ActiveX、query table、pivot、slicer、printer settings、远程模板和 `calcChain` 一律拒绝。所有 worksheet 的任意 `<f>` 节点、合并单元格、隐藏 sheet、隐藏行和隐藏列均返回 `catalog_workbook_unsafe`。

下载令牌固定为 `SHA-256(export_id UTF-8)` 的前 16 位小写十六进制，文件名精确为 `product-catalog-{token}.xlsx`。响应固定官方 media type、`X-Content-Type-Options: nosniff`、`Cache-Control: private, no-store` 和 `Content-Disposition: attachment; filename="product-catalog-{token}.xlsx"`；不得回显上传文件名或任意业务文本组成 header 或下载路径。

### 9.2 单元格、数据区域与编辑标记

下表使用这些精确记号：

- `T(n)`：OOXML `s` 或 `inlineStr`，最多 `n` 个 Unicode scalar；系统 ID、编码和日期都必须是文本，禁止数字单元格造成精度或前导零丢失；
- `I`：非负十进制整数的 OOXML 数值单元格，不接受小数、指数、布尔或字符串数字；
- `RO`：系统只读，上传值必须逐字符等于导出记录；
- `E`：用户可编辑；`K`：系统生成行只读、用户新增行可填写且随后不可变；
- `C`：可填写的核对字段，不是权威引用；非空时必须与权威目标一致。

第 9.3 节“必填”指完整 `validate` 和批准门，不是候选生成或结构解析门。系统导出的 `RO` 必填字段始终有值；来源无法权威提供的 `E` 字段可以在初始候选、上传解析结果和 `needs_attention` 中为空，而不是从标题猜值或让结构解析失败。处于第 10.3 节当前 `projection_state=included` 的行缺少条件必填值时，空值必须形成可编辑的 blocking issue，只有补齐后才可进入 `validated`；映射到既有 SKU 或明确排除后变为 `audit_only` 的未批准系统候选不再要求身份 E 字段，也不会被批准。XLSX 空单元格和在线 JSON 的 `null` 使用同一草稿语义，API 不用空字符串表示空值。

所有以“预览”结尾的来源列都必须有紧邻的 `SHA256` 列。对非空原始 Unicode 值，digest 固定为 `sha256:`＋其原样 UTF-8 bytes 的 64 位小写十六进制；预览把每个连续 Unicode White_Space、不满足 XML 1.0 Fifth Edition `Char` production 的 scalar 或类别 `Cc|Cf|Zl|Zp` 的序列替换为一个 U+0020、首尾 trim，再截取该列上限的 Unicode scalar，结果为空时写固定字面值 `[不可显示]`。因此 U+0000、U+007F、U+0080、U+009F、U+FFFE 和 U+FFFF 都不能进入 worksheet XML 或普通 API 预览。原始值为空时预览和 digest 同时为空。对来源候选集合，digest 改为完整原值按 UTF-8 bytes 排序后、使用 RFC 8785 JCS 编码的 distinct JSON 数组摘要；预览使用各元素的安全预览组成 compact JSON 数组并按列上限截断。摘要用于完整性和区分，不提供保密性。

完整来源值只保存在数据库，并按第 10.6 节字段权限在安全页面/API 中编码显示。XLSX 的映射、异常和证据引用只以系统行 ID、工作簿键及服务端恢复的不可变导出记录为权威；任何预览或摘要都不能由客户端反向提交成身份键。这样既有 v1 已发布文本即使含换行或 OOXML 不可表示字符也能进入人工流程，而不会进入公式、XML、日志或下载文件名。

文本不得含 NUL、禁止控制字符或换行；除自由原因/备注外均先 trim，再执行字段规则。自由原因/备注保留内部普通空格，但首尾 trim。日期固定为文本 `YYYY-MM-DD`，生成时间固定为 UTC RFC 3339 秒精度 `YYYY-MM-DDTHH:MM:SSZ`。所有以 `= + - @` 开头的合法文本仍按 OOXML 字符串逐字符往返，禁止通过前缀撇号改变逻辑值。

每张表的第 1 行必须是下述精确表头，数据从第 2 行开始且连续。第一条全空行之后只能有全空尾行；其后出现任意值、重复表头、部分空主键行，或该表下述固定最后一列之后出现任意非空值，均为 `catalog_sheet_contract_mismatch`；“最多 16 列”只是资源上限，不能授权匿名附加列。格式化但无值的尾部单元格忽略。`生成信息` 恰好 10 行（1 行表头＋9 行值）；其他表允许全空数据区。不得删除或复制任何系统导出行；用户只能在 `款式主档` 和 `SKU变体` 的尾部新增行。行顺序、样式、颜色、批注、数据验证和 sheet protection 不参与业务语义。

### 9.3 固定工作表与逐列契约

工作簿依次、恰好包含六个可见工作表：`生成信息`、`款式主档`、`SKU变体`、`SellerSKU映射`、`待处理异常`、`来源证据`。不得增删、隐藏、重命名或重排。

#### `生成信息`

表头固定为 `字段 | 值`。九项按下表顺序出现，不允许额外键；两列均为 `RO` 且必填，只有首次初始化的 `基础目录版本` 可为空。

| 字段 | 值类型与约束 |
| --- | --- |
| `模板版本` | `T(64)`，固定 `product_catalog_workbook_v1` |
| `目录导出ID` | `T(64)`，不透明系统 ID |
| `站点代码` | `T(64)` |
| `Seller Account` | `T(128)`，显示值；实际 scope 由导出 ID 恢复 |
| `Marketplace` | `T(32)`，固定 `amazon_us` |
| `基础目录版本` | `T(64)`，首次初始化为空 |
| `来源快照摘要` | `T(71)`，固定 `sha256:`＋64 位小写十六进制 |
| `规范化规则版本` | `T(64)` |
| `生成时间` | `T(20)`，UTC RFC 3339 秒精度 |

`规范化规则版本` 指向不可变复合 manifest；`product_catalog_workbook_v1` 首版固定包含 `seller_sku_match_v1`、`catalog_identity_key_v1`、`safe_source_projection_v1` 和 `source_evidence_jcs_v1`。导出记录、导入批次和目录版本都保存该 manifest ID；算法升级必须新建版本并显式迁移，不能用新库版本重算旧摘要。

#### `款式主档`

| 列（固定顺序） | 类型 | 必填 | 编辑 |
| --- | --- | --- | --- |
| 工作簿款式键 | `T(64)` | 是 | `K` |
| 系统款式ID | `T(64)` | 仅既有批准目录成员是；系统候选和用户新增行必须空 | `RO` |
| 款号 | `T(128)` | 是 | `E` |
| 标准商品名称 | `T(255)` | `included` 行完整验证时是；`audit_only` 系统候选可空 | `E` |
| 启用状态 | `T(16)`，`enabled|disabled` | 是 | `E` |
| 候选SellerSKU数 | `I` | 系统行是；新增行必须空 | `RO` |
| 来源标题数 | `I` | 系统行是；新增行必须空 | `RO` |
| 首次出现日期 | `T(10)` | 有证据时是；新增行必须空 | `RO` |
| 最近出现日期 | `T(10)` | 有证据时是；新增行必须空 | `RO` |
| 变更原因 | `T(500)` | 修改既有款号、名称或状态时是 | `E` |

#### `SKU变体`

| 列（固定顺序） | 类型 | 必填 | 编辑 |
| --- | --- | --- | --- |
| 工作簿变体键 | `T(64)` | 是 | `K` |
| 系统SKUID | `T(64)` | 仅既有批准目录成员是；系统候选和用户新增行必须空 | `RO` |
| 工作簿款式键 | `T(64)` | 是 | `E` |
| 内部展示SKU | `T(128)` | `included` 行完整验证时是；`audit_only` 系统候选可空 | `E` |
| 标准颜色 | `T(128)` | `included` 行完整验证时是；`audit_only` 系统候选可空 | `E` |
| 标准尺码 | `T(128)` | `included` 行完整验证时是；`audit_only` 系统候选可空 | `E` |
| 启用状态 | `T(16)`，`enabled|disabled` | 是 | `E` |
| 来源颜色候选预览 | `T(1000)` | 系统行可空；新增行必须空 | `RO` |
| 来源颜色候选集SHA256 | `T(71)` | 有候选集合时是；新增行必须空 | `RO` |
| 来源尺码候选预览 | `T(1000)` | 系统行可空；新增行必须空 | `RO` |
| 来源尺码候选集SHA256 | `T(71)` | 有候选集合时是；新增行必须空 | `RO` |
| 首次出现日期 | `T(10)` | 有证据时是；新增行必须空 | `RO` |
| 最近出现日期 | `T(10)` | 有证据时是；新增行必须空 | `RO` |
| 变更原因 | `T(500)` | 修改既有身份字段或状态时是 | `E` |

#### `SellerSKU映射`

该表每个 `scope + Seller SKU匹配键` 恰好一行；若多个原值发生规范化碰撞，预览和摘要取完整 UTF-8 bytes 二进制最小的代表原值，全部原值仍各自在 `来源证据` 摘要中，并在 `待处理异常` 形成碰撞项。不得新增或删除映射行。

| 列（固定顺序） | 类型 | 必填 | 编辑 |
| --- | --- | --- | --- |
| 系统映射行ID | `T(64)` | 是 | `RO` |
| Seller Account | `T(128)` | 是 | `RO` |
| Marketplace | `T(32)`，`amazon_us` | 是 | `RO` |
| Seller SKU预览 | `T(255)` | 是 | `RO` |
| Seller SKU SHA256 | `T(71)` | 是 | `RO` |
| 身份决定 | `T(16)`，`mapped|excluded` | 批准时是 | `E` |
| 目标工作簿变体键 | `T(64)` | `mapped` 时是 | `E` |
| 目标内部展示SKU | `T(128)` | 否 | `C` |
| 首次出现日期 | `T(10)` | 是 | `RO` |
| 最近出现日期 | `T(10)` | 是 | `RO` |
| 经营出现次数 | `I` | 是 | `RO` |
| 退货出现次数 | `I` | 是 | `RO` |
| 排除理由 | `T(500)` | `excluded` 时是 | `E` |
| 变更原因 | `T(500)` | 改变既有批准决定、目标或理由时是 | `E` |

`身份决定=mapped` 时目标键必填、排除理由必须空；`身份决定=excluded` 时目标键和核对 SKU 必须空、排除理由 trim 后至少 10 字符。`目标工作簿变体键` 是 mapped 决定的唯一权威目标；`目标内部展示SKU` 非空时必须等于所引用 SKU 行的展示值。首次候选可暂时留空决定；审核页填写异常动作时必须同步更新这一组级映射行，完整验证要求每行决定非空且与异常 payload 一致。账号显示值必须等于导出值，权限和唯一性仍使用导出记录恢复出的稳定 scope ID。

#### `待处理异常`

| 列（固定顺序） | 类型 | 必填 | 编辑 |
| --- | --- | --- | --- |
| 异常行ID | `T(64)` | 是 | `RO` |
| 原因代码 | `T(64)` | 是 | `RO` |
| Seller SKU预览 | `T(255)` | 是 | `RO` |
| Seller SKU SHA256 | `T(71)` | 是 | `RO` |
| 来源报表 | `T(16)`，`business|returns|both` | 是 | `RO` |
| 候选款号 | `T(128)` | 否 | `RO` |
| 候选颜色 | `T(128)` | 否 | `RO` |
| 候选尺码 | `T(128)` | 否 | `RO` |
| 处理动作 | `T(32)`，四个批准字面值之一 | 完整验证时是 | `E` |
| 目标工作簿变体键 | `T(64)` | 条件必填 | `E` |
| 修正款号 | `T(128)` | 条件必填 | `E` |
| 修正标准颜色 | `T(128)` | 条件必填 | `E` |
| 修正标准尺码 | `T(128)` | 条件必填 | `E` |
| 排除理由 | `T(500)` | 条件必填 | `E` |
| 备注 | `T(1000)` | 否 | `E` |

四种动作的条件矩阵固定为：

| 处理动作 | 目标变体键 | 三个修正字段 | 排除理由 | 目标约束 |
| --- | --- | --- | --- | --- |
| `映射现有变体` | 必填 | 必须全空 | 必须空 | 引用 `系统SKUID` 非空的 SKU 行 |
| `创建新变体` | 必填 | 必须全空 | 必须空 | 引用 `系统SKUID` 为空的新 SKU 行；其款式行可为既有或新增 |
| `修正解析` | 必填 | 款号、颜色、尺码全部必填 | 必须空 | 引用既有或新增 SKU 行，规范化款号/颜色/尺码必须与三个修正值完全一致 |
| `明确排除` | 必须空 | 必须全空 | 必填，trim 后长度下限为 10 字符 | 生成本目录版本的 scope＋匹配键排除决定 |

同一 Seller SKU 匹配键的全部异常行构成一个决定组。组内每行必须给出完全相同的规范 payload：`处理动作`、nullable `目标工作簿变体键`、三个 nullable 修正字段和 nullable、trim 后的 `排除理由`；任何不同都保持阻断。该组 payload 还必须与唯一 `SellerSKU映射` 行一致：前三种动作对应 `身份决定=mapped` 和同一目标，`明确排除` 对应 `身份决定=excluded`、空目标和逐字符相同的排除理由。任何空动作、无效引用、互斥字段同时出现或组级决定冲突都会阻止验证，行顺序不能用于挑选理由。

最终批准 XLSX 必须投影每个批准键的完整组级决定：已映射键在 `SellerSKU映射` 写 `mapped + 目标`，已排除键无论格式是否正常都写 `excluded + 空目标 + 批准理由`。仍由规则识别为异常或碰撞的来源继续出现在 `待处理异常`，但预填与映射行一致的批准 payload；普通格式的已排除键可以只出现在映射表。下一次修订可修改这些 E 列，任何已批准键在 `mapped↔excluded` 间切换、改绑目标或改变批准排除理由都归为高风险并要求 `admin`；因此最终导出可以无歧义地往返，而不依赖异常行是否存在。

#### `来源证据`

| 列（固定顺序） | 类型 | 必填 | 编辑 |
| --- | --- | --- | --- |
| 证据汇总行ID | `T(64)` | 是 | `RO` |
| Seller SKU预览 | `T(255)` | 是 | `RO` |
| Seller SKU SHA256 | `T(71)` | 是 | `RO` |
| 报表类型 | `T(16)`，`business|returns` | 是 | `RO` |
| 首次出现日期 | `T(10)` | 是 | `RO` |
| 最近出现日期 | `T(10)` | 是 | `RO` |
| 出现次数 | `I` | 是 | `RO` |
| 不同标题数 | `I` | 是 | `RO` |
| 最近标题预览 | `T(255)` | 有原始标题时是 | `RO` |
| 最近标题SHA256 | `T(71)` | 有原始标题时是 | `RO` |
| 不同父ASIN数 | `I` | 是 | `RO` |
| 不同子ASIN数 | `I` | 是 | `RO` |
| 不同FNSKU数 | `I` | 是 | `RO` |
| 证据集合SHA256 | `T(71)` | 是 | `RO` |

它只包含第 7.5 节固定聚合键产生的摘要，不得包含 order ID、fulfillment center、license plate、买家留言或其他单笔退货敏感文本。最近标题按最大 report date、再按完整标题 UTF-8 bytes 二进制最小值稳定选择；完整标题/ASIN/FNSKU tuple 只保存在数据库和 `data_manager|admin` 授权页面。所有计数、预览和摘要都由导出记录逐字符复核，不能用于反向替代完整来源值。

### 9.4 防篡改和服务端权威

系统根据 `目录导出ID` 逐行恢复导出记录，比较全部 `RO` 字段、系统行集合和 evidence digest；删除、复制、伪造或修改均返回 `catalog_export_tampered`。工作簿键在全文件内按二进制文本唯一，所有本地引用必须闭合。Excel 保护仅作用户提示，服务端不信任行顺序、样式、数据验证、计算缓存或客户端提交的摘要。

## 10. 候选生成、审核与批准

### 10.1 候选范围

候选生成读取全部历史日期中每种报表的当前发布版本：

- 草稿、解析失败批次、被替代版本和撤下版本不参与；
- 经营独有、退货独有和两边共有的 Seller SKU 都参与；
- 经营证据使用 report date；
- 退货证据同时保存 report date 和原始 `return-date`，但工作簿日期摘要不替代事件时间；
- 不读取订单号和买家留言生成候选；
- 不生成没有真实 Seller SKU 证据的颜色×尺码组合。

导出记录冻结实际读取的 publication ID、版本、当前指针 revision、行摘要和候选规则版本。工作簿上传后不能重新读取“现在的数据”冒充原导出快照。

### 10.2 状态模型

目录导入批次状态固定为 `uploaded|parsing|parse_failed|needs_attention|validated|ready_for_approval|approved|rejected|withdrawn|superseded`。XLSX 上传创建 `uploaded`；`from-export` 在一个事务从 ready export 复制或引用完整候选、运行与解析完成相同的结构校验，并直接创建为 `needs_attention` 或无问题时 `validated`，`parse_attempt_revision=0`，不伪造上传文件或解析 attempt。两种来源此后使用同一状态机。只有下表中的命令可以改变既有批次状态：

| 来源状态 | 命令 | 成功目标 | 角色与前置条件 |
| --- | --- | --- | --- |
| `uploaded` | 系统领取解析 | `parsing` | 有效上传 claim；最多一个活动解析租约 |
| `parsing` | 解析完成 | `validated` 或 `needs_attention` | 无问题可直接 `validated`；否则 `needs_attention` |
| `parsing` | 解析失败 | `parse_failed` | 保存不可变 attempt 和 `recoverable` 标记 |
| `parse_failed` | `resume` | `parsing` | 仅 XLSX 且 `recoverable=true`；当前仍为 `data_manager` 的 owner，或 `admin` |
| `needs_attention|validated|ready_for_approval` | `decisions` | `needs_attention` | `data_manager|admin`；任何语义修改都使旧验证、提交和预览失效 |
| `needs_attention|validated` | `validate` | `validated` 或 `needs_attention` | `data_manager|admin`；完整验证通过才进入 `validated` |
| `validated` | `submit` | `ready_for_approval` | `data_manager|admin`；记录 `submitted_by` 和当前 revision |
| `ready_for_approval` | `approval-preview` | 不变 | 当前仍为 `data_manager` 且等于 `submitted_by`，或 `admin`；持久化绑定 revision 的 projection，但不写目录 |
| `ready_for_approval` | `approve` | `approved` | 普通变更为当前仍为 `data_manager` 且等于 `submitted_by`，或 `admin`；高风险仅 `admin`；projection 未过期 |
| `ready_for_approval` | `reject` | `rejected` | 仅 `admin`，原因 trim 后长度下限为 10 字符 |
| `uploaded|parse_failed|needs_attention|validated|ready_for_approval` | `withdraw` | `withdrawn` | 当前仍为 `data_manager` 的 owner；`admin` 可代撤回但原因必填；活动解析租约期间拒绝 |
| `needs_attention|validated|ready_for_approval|rejected` | `rebase` | 原批次 `superseded`，新批次 `needs_attention` 或 `validated` | 当前仍为 `data_manager` 的 owner，或 `admin`；基于请求指定的 ready replacement export 原子创建 `source_kind=online` 后继，继承 owner，`parse_attempt_revision=0`；兼容决定只作候选复制并必须重新完整验证 |

`approved|withdrawn|superseded` 为终态；`rejected` 只能通过 `rebase` 创建后继批次，不能原地复活。`needs_attention → validated` 只能由显式 `validate` 完成，`validated → ready_for_approval` 只能由显式 `submit` 完成。rebase 的后继是新资源的初始状态，不是旧资源绕过状态边；它没有原始 XLSX，也不伪造 parsing。所有角色判断都使用请求时的当前角色；历史上的 owner 或 `submitted_by` 身份只构成附加条件，不能让已降级为 `viewer` 的账号继续写入。GET 不得产生业务副作用，禁止通过读取触发解析、验证、状态或 counter 推进；按第 13.1 节追加不含业务原值的安全访问审计不属于业务状态变化。

每个导入批次保存永不回退或复用的 `workflow_revision` 和 `parse_attempt_revision`。`workflow_revision` 从 0 开始，任何状态变化、解析租约领取/续租/释放/过期、草稿语义修改、验证绑定或提交元数据变化的成功事务都递增一次；`parse_attempt_revision` 从 0 开始，每次系统首次领取或 `resume` 创建新解析 attempt 时再递增一次。解析 worker 完成/失败必须 CAS 同时匹配当前 `parsing`、`workflow_revision`、`parse_attempt_revision` 和不可猜测 lease token；旧 attempt 即使遇到 `parse_failed → parsing → parse_failed` 的相同表面状态也只能返回 `catalog_parse_attempt_stale`，不得覆盖新结果。

所有 POST 都携带 UUID v4 `operation_token` 和请求语义摘要。创建 export、首次上传、`from-export` 以及管理员命令代查创建新资源或审计事件，不要求导入 revision；已有导入上的 `resume/decisions/validate/submit/approval-preview/approve/reject/rebase/withdraw` 一律要求 `expected_workflow_revision`，其中 `resume` 还要求 `expected_parse_attempt_revision`。`rebase` 另要求显式 `replacement_export_id` 和 `expected_catalog_publication_revision`；`approve` 另要求 `expected_catalog_publication_revision`、未过期 `projection_id` 与 projection digest；目录 restore 要求 `expected_catalog_publication_revision`。缺少或不匹配不能退化为“适用时”，分别返回 `catalog_workflow_revision_conflict`、`catalog_publication_revision_conflict` 或对应的 base/projection stale 错误。

`approval-preview` 是业务状态不变的幂等写命令，不是零写入读取：它必须持久化 command claim/effect 和不可变 projection，projection 绑定 `import_id/workflow_revision/validation_run_id/base_catalog_version_id/catalog_publication_revision/fact_snapshot_tuple_id/risk/diff_digest/created_at/expires_at`，其中 `expires_at=created_at+30 分钟`；但它不得改变导入状态、目录成员或当前目录指针。相同 token、相同语义返回首次 projection；不同 token 可产生内容相同但 ID 不同的 projection。`approve` 的事务开始时间必须不晚于 `expires_at`，并且只接受仍处于 `ready_for_approval` 且全部绑定值未变的 projection。

同 token、同摘要、同原始操作者在当前仍有权读取该资源和结果字段时返回首次状态和结果；操作者已离站、被降级或失去草稿读取权时返回 403，不重新执行 effect，也不披露 projection、diff、risk 或安全定位符。`admin` 仍只能走带原因的代查 POST。同 token、不同摘要或不同操作者返回 `idempotency_key_reused`。请求语义摘要覆盖路由资源、规范请求体和全部 expected counter，但不含 token 自身。来源状态已推进但 effect 已存在时仅按上述当前读取权限返回原结果；只有 claim 而没有 effect 时仍须重新检查当前写角色和全部 counter，claim 本身不授予权限；没有 effect 的非法来源状态返回 `catalog_state_transition_invalid`，不得猜测成功。长任务可以先用短事务领取 claim/lease；任何数据库业务变化必须与最终 effect 同事务提交，preview 的 projection 与 effect 也必须同事务提交。只有文件 artifact 继续使用第 16 节的数据库外对账边界，并以不可变 digest 在最终事务引用。

### 10.3 校验层次

校验依次执行：

1. 上传元数据和 OOXML/ZIP 安全；
2. 模板版本、工作表和精确表头；
3. 系统字段、导出 ID、scope 和基础版本；
4. 单元格基础类型、长度和枚举；
5. 工作簿内引用、组级决定和下述批准投影可达性；
6. 只对批准投影中的行检查条件必填、身份唯一性和 reservation 冲突；
7. 当前数据库中的款式、SKU、映射和 revision 冲突；
8. 当前 publication 集合中新出现的未覆盖 Seller SKU；
9. 权限和风险分级；
10. 规范化差异摘要、影响范围和 `audit_only` 候选摘要；
11. 批准事务内完整重算。

每个导出决定组在不可变 export 记录中保存 nullable `recommended_sku_row_key`；非空时必须引用同一 export 的 ID-null system SKU 候选，并进入 export 摘要。它不进入 XLSX E/RO 单元格，不由客户端提交，也不是批准决定；只用于未决定草稿的字段问题引导。异常或解析规则没有安全推荐时该值为 null。

批准投影使用唯一、服务端重算的可达性算法。根集合包含全部既有正式 ID 行、未删除的 `user_created` 行，以及每个最终 `identity_decision=mapped` 的目标 SKU 行；随后递归加入每个已纳入 SKU 引用的款式行。`row_origin=system` 且正式 ID 为空的款式/SKU 只有在该闭包内时 `projection_state=included`，否则为 `projection_state=audit_only`。草稿中尚未决定且有 `recommended_sku_row_key` 的组仅为尽早显示字段问题，临时把该推荐 SKU 视为 `included`；无推荐的未决定组不增加临时根。完整 `validate` 仍先要求每组得到最终决定，再按最终 mapped 目标重算。用户把来源改映到既有 SKU 或明确排除后，失去最后一个根引用的系统候选及其不可达款式立即变为 `audit_only`，其缺字段 issue 必须清除。

`audit_only` 系统候选保留原工作簿键、来源证据、解析建议、决定变更和审计事件，但不参加身份字段必填、唯一性、身份变更风险、revision、reservation 或目录成员生成；差异页只在独立的“未采用候选”审计摘要中计数。它不得被静默删除，也不算用户创建的停用身份。若用户确实要保留一个没有来源映射的新身份，必须显式新增 `user_created` 行；这样“人工建档”和“未采用的系统建议”不会混为一类。验证运行和 approval projection 都固化 `included|audit_only` 行键集合及摘要，批准事务必须逐键重算并完全一致。

基础商品目录版本已经变化时返回过期冲突，不得静默覆盖。初次批准前如果当前 publication 集合出现导出 snapshot 未包含的新 Seller SKU 匹配键、scope 变化或新的规范化碰撞，必须刷新候选或显式变基。仅为已知匹配键新增事实、标题、ASIN 或 FNSKU 不改变本目录版本冻结的证据，预览以 `evidence_drift` 明示新旧截止点、行数和摘要；用户可以继续按原 snapshot 批准，也可以变基，系统不得把新证据悄悄混入批准版本。

### 10.4 草稿修改

XLSX 是批量填写入口，不是唯一可修改载体。审核页面可以修改同一草稿中的标准字段、映射和异常决定；每次修改追加审计事件并递增 `workflow_revision`，使旧验证和批准预览失效。原始 XLSX 永久只读。

批准后系统生成与最终目录版本一致的 ready export。容量门内物化标准 XLSX，该最终导出而不是最初上传文件作为下一次批量修订基础；容量超限时不生成截断 XLSX，下一次修订从该 ready export 的 `from-export` 在线草稿开始。两条路径引用同一不可变目录/事实快照和组级决定。

### 10.5 差异与风险

审核页面固定区分：

- 新增款式；
- 标准名称或状态修改；
- 新增 SKU；
- SKU 款式、颜色、尺码、展示编码或状态修改；
- Seller SKU 首次绑定；
- Seller SKU 从一个 `sku_id` 改绑到另一个；
- 明确排除及排除理由变化；
- 未采用、仅保留审计的系统候选；
- 来源标题、ASIN 或 FNSKU 证据变化。

每项显示变更前后值、影响的当前发布行数和日期范围。生产阶段上线后还要显示订单、入库和库存事实引用数。

### 10.6 权限

P0 不新增角色。服务端权限矩阵固定为：

| 资源或操作 | viewer | data_manager | admin |
| --- | --- | --- | --- |
| 当前批准款式、SKU、标准字段和趋势 | 读 | 读 | 读 |
| 当前批准 Seller SKU 别名、ASIN、FNSKU | 只读 `SafeSourceRef`；不含原始字符串、证据历史和内部行定位符 | 读安全引用；可经授权 evidence API 读可逆转义 | 读安全引用；可经授权 evidence API 读可逆转义 |
| 来源标题 | 只读去重数量和“多个来源标题”标志 | 读安全预览及可逆转义的批准证据历史 | 读安全预览及可逆转义的批准证据历史 |
| 历史目录、版本列表和 diff | 拒绝 | 读 | 读 |
| export、上传、站点内全部草稿、异常和验证 | 拒绝 | 创建、读取、协作修改 | 全部 |
| 原始商品目录 XLSX | 拒绝 | 读自己及站点内协作草稿 | 全部；下载审计 |
| `submit` 和普通批准 | 拒绝 | 可提交任一有权协作的草稿；只可批准 `submitted_by` 为自己的普通草稿 | 全部 |
| 高风险批准、拒绝、恢复和 scope 管理 | 拒绝 | 拒绝 | 全部；原因必填 |
| 撤回 | 拒绝 | 只可撤回自己拥有的 XLSX 或 online 批次 | 可代撤回；原因必填 |
| 审计事件和内部安全定位符 | 拒绝 | 拒绝 | 读 |

`viewer` 可用 Seller SKU、ASIN 和 FNSKU 搜索当前批准商品，但响应只返回已经批准且用于当前目录的安全标识，不返回草稿、原文件、逐发布行证据、历史差异、操作者或审计摘要。列表/详情响应返回服务端计算的 `permissions`，前端据此隐藏操作；直接路由、API 和字段投影仍分别执行 403/脱敏，不能依赖导航隐藏。

`data_manager` 可在同一站点协作他人草稿；任何协作修改都记录操作者并递增 `workflow_revision`。无副作用的命令结果 GET 只允许原 `operation_token` 操作者；`admin` 必须通过独立的代查 POST 提交原因并写审计，其他协作者不能仅凭 import 访问权代查命令结果。所有 Cookie 认证写请求继续执行既有 CSRF 门禁。

`data_manager` 可以批准：

- 首次商品主档；
- 标准商品名称修改；
- 新款式或新 SKU；
- 从未在批准目录中生效的 Seller SKU 首次绑定；
- 无身份影响的说明信息。

以下变更仅限 `admin + 非空原因 + expected_workflow_revision`：

- 已批准 Seller SKU 改绑到另一个 `sku_id`；
- 已批准 Seller SKU 在 `mapped` 与 `excluded` 间切换，或修改已批准排除理由；
- 已批准款式修改款号；
- 任一已进入批准目录的 SKU 修改所属款式、内部展示 SKU、标准颜色或标准尺码；是否已有事实只影响差异摘要和能否恢复，不降低权限；
- 已被事实引用的款式或 SKU 停用，以及其他身份字段纠错；
- 需要恢复旧目录版本的管理操作。

一个草稿混合普通和高风险变更时，整份草稿需要 `admin` 批准，不拆分部分批准。

### 10.7 批准事务

批准命令携带 UUID v4 `operation_token`、`expected_workflow_revision`、`expected_catalog_publication_revision`、当前基础目录版本、验证运行 ID、未过期 projection ID/digest 和差异摘要。事务必须：

1. 恢复或登记命令；
2. 锁定站点商品目录同步行和当前指针；
3. 重读草稿、基础版本、权限、风险和全部相关实体；
4. 重算校验、差异和影响摘要；
5. 只为批准投影中既有成员、`user_created` 行和 `included` 系统候选创建所需款式/SKU revision 与稳定身份；`audit_only` 候选零身份、零 reservation；
6. 创建完整不可变目录版本成员；
7. 更新当前投影；
8. 切换当前目录指针；
9. 写 publication event、审计和命令结果；
10. 原子提交。

任一步失败全部回滚。同一 UUID 和同一摘要返回首次结果；同一 UUID 改变语义返回冲突。提交结果不确定时返回 `outcome_unknown`，客户端必须先查询命令状态，不能换 UUID 盲目重放。

## 11. 日报质量边界

P0 消费既有已批准日报，不重定义每日上传审核。`business_report_v1` 和 `return_report_v1` 的字段、严重度、警告确认、发布资格和历史发布结果全部保持兼容；商品主档问题不得反向把已发布日报变成未发布。

### 11.1 经营日报

22 个冻结结构字段、严格类型转换和额外列政策继续使用 `business_report_v1`。其中既有契约要求的子 ASIN 和 Seller SKU 仍是发布必填；父 ASIN/标题为空、负数量/会话/销售额和既有重复条件继续保持原契约中的可确认警告，不在 P0 静默升级为阻断错误。

源表头、原始字段和持久字段 `conversion_rate_total` 永久保留，旧 API 也不删除该名称。商品分析增加只读语义适配字段 `session_share_total` 指向同一来源值，并明确它不是购买转化率；P0 看板的 `conversion` 只使用 `SUM(units_ordered) / SUM(sessions_total)` 派生，不回写来源字段。

### 11.2 退货日报

13 个冻结结构字段、必填字段、正整数 quantity、事件时间解析、单文件重复和敏感字段政策继续使用 `return_report_v1`，P0 不改变严重度或发布门禁。`return-date` 仍按原偏移转 UTC；无偏移时使用该日报版本冻结的源时区。订单号、物流牌照号和买家留言不进入商品 API、XLSX 或日志。

### 11.3 跨报告退货重复

跨报告疑似重复是分析层的版本化决定，不修改原始退货行，也不改变既有日报审核状态。每个当前 publication 集合生成不可变 candidate membership 和 `return_dedup_snapshot_id`；同一 scope 下的行只能处于一个互斥状态：

| 状态 | 含义 | 正式退货 KPI |
| --- | --- | --- |
| `unique` | 没有重复候选，或被确认为一个重复组中唯一计数的 canonical row | 计数一次 |
| `confirmed_distinct` | 有相似候选，但授权审核确认是不同退货事件 | 每条分别计数 |
| `duplicate_of` | 明确指向同 snapshot 内一个 canonical row | 不计数；只在重复对账桶出现 |
| `unresolved` | 存在跨报告疑似重复，尚未决定 | 不计数；汇总标记 partial |

`duplicate_of` 目标必须同站点、同 scope、存在且不能形成链或环；canonical row 必须为 `unique` 或 `confirmed_distinct`。决定只允许 `data_manager|admin`，更改决定生成新 dedup snapshot，不更新旧 snapshot。`fact_basis=current` 使用请求一致性快照中当前 dedup pointer；`fact_basis=catalog_snapshot` 使用目录冻结的 dedup snapshot。响应分别返回 `duplicate_quantity` 和 `unresolved_quantity`，不得把它们隐藏在零值里。

退货发布采用“事务外预构建＋短事务 CAS”，不在 publication 锁内全量复制：

1. 待发布日报版本保持非 current，以当前退货 publication-set digest、各 pointer revision 和拟替换版本组成 proposed set；
2. worker 在事务外读取 proposed set，只对新增/移除行的版本化指纹及索引命中的既有相关组重算 candidate-group revision；未进组行继续隐式 `unique`，稳定组引用旧 revision，新组或成员变化组为 `unresolved`；
3. 生成 `staged` checkpoint/delta snapshot，验证 proposed digest、逻辑全覆盖、链深和所有引用；
4. 最终短读写 `REPEATABLE READ` 事务按固定顺序锁定站点退货发布同步行、目标 dataset publication 和 dedup pointer，CAS 证明 base digest、全部相关 pointer revision、scope 和 proposed version 未变后，同时把日报版本设为 current、snapshot 设为 ready，并推进 `return_dedup_publication`；
5. CAS 失败则 staged snapshot 标为 superseded 并按新 base 重建；任一步失败时日报 publication 和 dedup pointer 都保持旧值。

人工改变 dedup 决定同样在事务外构建相同 publication-set digest 的后继 delta，再以短 CAS 只推进 dedup pointer，不改变日报 publication。current 查询和候选导出校验实际退货 publication-set digest 与 ready dedup snapshot 完全相等；不相等属于损坏或未完成切换，返回 `return_dedup_not_ready` 且不产出退货 KPI/目录 export。初始化 P0 时先在事务外为全部当前退货 publication 构建首个 checkpoint，再以短事务安装 ready pointer，之后才允许启用新分析。

若未来要把父 ASIN/标题非空、负值或其他警告升级为发布阻断，必须新建 `business_report_v2`/`return_report_v2` 或独立规格，明确历史回填和切换政策；不属于 P0。

## 12. 商品分析口径

### 12.1 数据版本

每个分析请求必须选择一个 `fact_basis`：

- `current`（默认）：在一个 MySQL `REPEATABLE READ` 只读事务中固定当前目录、所需日期的当前 publication 指针、匹配该 publication-set digest 的当前 return dedup pointer 和当前 `site_config_version_id`，只读这些版本的 active 行；
- `catalog_snapshot`：必须显式提供有权限访问的 `catalog_version`，只读该目录保存的 `publication_snapshot_id`、`return_dedup_snapshot_id`、`site_config_version_id` 和 snapshot 成员。

`catalog_snapshot` 的 `to` 不得晚于 `fact_cutoff_at` 所在业务日，且请求日期必须由 snapshot 的 published/missing 成员完整覆盖，否则返回 `catalog_snapshot_range_out_of_bounds`。`current` 省略 `catalog_version` 或只接受与当前目录相同的 ID；历史目录与 current 组合返回 `analytics_identity_fact_combination_invalid`。

草稿、失败批次、被替代日报版本、目录草稿和非 active 行不能混入任一口径。响应必须回显 `fact_basis`、实际目录 ID/版本号、publication snapshot ID 或逐 publication 引用摘要、dedup snapshot ID、`site_config_version_id`、reporting timezone、事务一致性时间和事实截止点。

### 12.2 指标

首版固定支持：

| 指标 | 公式与口径 |
| --- | --- |
| 订购件数 | `SUM(units_ordered)`；不称为去重订单数 |
| 销售额 | `SUM(ordered_product_sales)`，币种 USD |
| 退货件数 | `SUM(quantity)`，不是退货行数 |
| 会话数 | `SUM(sessions_total)` |
| 转化率 | `SUM(units_ordered) / SUM(sessions_total)`；汇总分母小于等于 0 时返回 `null` |

B2B 列是总计的子集，不能再次加到总计。`total_order_items` 也不能冒充去重订单数，首版不作为趋势主指标。

### 12.3 退货日期

默认 `return_basis=event_date`：`from/to` 筛选事件业务日；把原始 `return-date` 转换到响应冻结的美国站 reporting timezone 后分组。查询通过事件时间索引筛选全部所选 publication 行，不以文件 report date 截断。

切换 `return_basis=report_date` 时，`from/to` 筛选每日数据集的人工确认报告日，并按该日分组。两种口径在聚合前使用同一个 dedup snapshot。界面必须明确显示当前口径和时区，不能把两者混成一条序列。

### 12.4 缺报、零值和身份覆盖

报表存在性、商品身份决定、退货去重决定和数值状态是四个独立维度。分析 API 禁止 `to` 晚于请求一致性快照中 reporting timezone 的当前业务日，因此不序列化未来趋势点：

- `report_status=published|missing`：按 report date 分别为经营、退货返回；
- `identity_status=not_applicable|partial|complete`：报告缺失为 `not_applicable`；仍有 unmatched 为 `partial`；每个合格 Seller SKU 行都已映射或明确排除为 `complete`；
- `dedup_status=not_applicable|partial|complete`：经营报告或退货报告缺失为 `not_applicable`；退货有 `unresolved` 为 `partial`；其余为 `complete`；
- `value_state=observed|zero|missing_report|undefined_denominator`：按下述每日点与区间矩阵解释；
- `source_completeness=complete|partial|indeterminate`：区间来源报告齐全、存在缺报、或事件日无法由报告日证明完整。

经营指标和 `return_basis=report_date` 退货的每日 `TrendPoint` 允许组合固定为：有一条或多条贡献事实时 `observed + 非空 value + null_reason=null`，即使正负抵消后 value 恰为零也仍是 observed；报表已发布但该系列没有贡献事实时，加法指标为 `zero + 精确零 + null`；所需 report-date 报表缺失时为 `missing_report + value=null + null_reason=missing_report`；conversion 在有观察来源但汇总分母小于等于 0 时为 `undefined_denominator + value=null + null_reason=undefined_denominator`。已发布但该系列无事实时 conversion 的分子/分母为 0/0，因此也使用 undefined_denominator，不能伪装成零。

经营指标和 `return_basis=report_date` 退货的区间 `MetricValue` 组合不同：只要 `observed_days>0`，加法指标返回已观察日报的部分合计，按是否存在贡献事实使用 observed 或 zero；conversion 从已观察日总分子/分母重算，分母小于等于 0 时使用 undefined_denominator。只有这两类口径在 `observed_days=0` 时才返回 `value_state=missing_report + value=null + null_reason=no_observed_reports`，此时 conversion numerator/denominator 也为 null。`missing_report + null_reason=missing_report` 只属于每日点，不属于区间对象。分子可为负，正分母下的比率也可大于 1，API 不夹断或静默修正 v1 已发布事实。

退货事件日与 report date 不一一对应，实际贡献 publication 的 report date 可以落在事件 `[from,to]` 之外。`return_basis=event_date` 是上述两张状态矩阵的明确例外：每日点和区间始终按区间内实际事件事实返回 observed 或 zero、`null_reason=null`，并附加 `source_completeness=indeterminate`；即使 `[from,to]` 的 report-date `observed_days=0`，已有跨日 publication 贡献的事件事实也必须返回非空 observed 值，没有事件事实则返回零，不能改成 `no_observed_reports`。接口另行返回同一 `[from,to]` 日历区间按 report date 排列的退货来源覆盖带和所有实际贡献 publication 的 report-date 范围。`observed_days/expected_days` 在该口径只作来源覆盖元数据，不控制事件值/null；某报告日缺失不能直接变成某事件日的 `missing_report`，也不能据此宣称某事件日零退货是完整观察。退货报告日口径可使用同日 `report_status`，此时 `source_completeness=complete|partial`。

覆盖对象固定为：

- **报表覆盖率**：合法闭区间内每个日历日都是应有日；published 日数 ÷ 应有日数，经营和退货分别计算；
- **身份决定覆盖率**：`(mapped_rows + excluded_rows) / eligible_rows`；
- **映射行覆盖率**：`mapped_rows / eligible_rows`；
- **退货去重决定覆盖率**：`(unique_rows + confirmed_distinct_rows + duplicate_of_rows) / return_eligible_rows`。

`eligible_rows` 是有非空 Seller SKU 且通过既有 v1 发布资格的 active 行。三种行数按经营和退货分别返回；覆盖率不按销售额或数量加权。排除是已完成的身份决定，因此可使 `identity_status=complete`，但它不计入 mapped rate，也不进入正式款式指标。

区间汇总同时返回 `is_partial`、`observed_days`、`expected_days` 和分报表 coverage；不能因缺一天把其余已观察值全部置空。产品总表和商品卡使用同一矩阵和同一状态文案。

`MetricValue.observed_days/expected_days` 始终指该指标来源报表在 `[from,to]` 的 report-date coverage，不是“出现该 SKU 的天数”。事件日退货也返回这组来源报告天数并配合 `source_completeness=indeterminate`，但遵守上段例外，不让该计数覆盖实际事件值；不能把有退货事件的日期数冒充报告覆盖。

### 12.5 聚合守恒

对每个日期和整个查询区间必须满足：

- 同款全部具体 SKU 之和＝款式总计；
- 同色全部尺码之和＝颜色总计；
- 全部颜色之和＝款式总计；
- 别名映射到同一 `sku_id` 的行只按来源事实值相加，不去重合法事实；
- 未归类和排除值不进入正式款式，但必须进入全局对账桶。

转化率不参与直接求和，所有层级都从该层级聚合后的分子和分母重新计算。

产品总表响应必须返回同一 scope、日期和事实口径下的站点级 `reconciliation`：`source_totals`、`mapped_totals`、`unmatched_totals`、`excluded_totals`、`duplicate_totals` 和 `unresolved_duplicate_totals`。退货先分桶：`duplicate_of` 进入 duplicate，`unresolved` 进入 unresolved；剩余 `unique|confirmed_distinct` 再按商品身份进入 mapped/unmatched/excluded，因此五个结果桶互斥。每个桶都含 units、sales、returns、sessions 以及 conversion 的 numerator/denominator；不适用或不可评估的指标为显式 `null`，不是省略。只有第 13.2 节 `metric_status=evaluable` 的指标执行来源总计等于各互斥适用桶之和；正式款式合计只等于 `mapped_totals`。

单款商品卡不返回全站六桶；它返回 `style_reconciliation`。`summary` 与 `variants` 始终覆盖整款并逐项相等；`total|color|sku` 维度的全部可用系列也覆盖整款；`size` 维度只覆盖请求所选颜色，因此全部尺码系列只与 `selected_color_totals` 相等，不能伪称等于整款 summary。未归类和排除行没有权威款式，不能为满足商品卡结构而扫描或猜测归属。全站六桶和身份覆盖只由产品总表 envelope 及目录审核页展示。

## 13. API 与查询边界

### 13.1 商品目录 API

第一版资源固定包括：

- `POST /api/catalog/exports`：基于当前 publication 集合生成候选导出记录；
- `GET /api/catalog/exports/{export_id}`：读取 `building|ready|failed` 状态；failed 只披露下述矩阵中的安全 `failure_reason`；
- `GET /api/catalog/exports/{export_id}/file`：下载安全 XLSX artifact；
- `POST /api/catalog/imports`：上传商品主档；
- `POST /api/catalog/imports/from-export`：从 ready export 直接创建无原始 XLSX 的在线审核草稿；
- `GET /api/catalog/imports/{import_id}`：只读取状态、每个 section 的非负 `row_count/blocking_issue_count/warning_issue_count`、差异摘要和 counter，不内联全量候选或 issue；
- `GET /api/catalog/imports/{import_id}/rows`：按 section 分页读取款式、SKU、映射、异常或证据摘要；
- `POST /api/catalog/imports/{import_id}/resume`：恢复可恢复解析；
- `POST /api/catalog/imports/{import_id}/decisions`：保存字段修正和异常决定；
- `POST /api/catalog/imports/{import_id}/validate`：运行完整验证；
- `POST /api/catalog/imports/{import_id}/submit`：把当前 validated revision 显式提交审批；
- `POST /api/catalog/imports/{import_id}/approval-preview`：业务状态不变地重算风险、影响和摘要，并持久化不可变 projection 与命令结果；
- `POST /api/catalog/imports/{import_id}/approve`：批准并发布新目录版本；
- `POST /api/catalog/imports/{import_id}/reject`：管理员拒绝 ready 草稿；
- `POST /api/catalog/imports/{import_id}/rebase`：以请求明确指定的 ready replacement export 创建后继批次并 supersede 原批次；
- `POST /api/catalog/imports/{import_id}/withdraw`：批准前撤回；
- `GET /api/catalog/styles`、`GET /api/catalog/styles/{style_id}`：查询当前批准主档；
- `GET /api/catalog/source-identifiers/{source_ref_id}`：仅 `data_manager|admin` 按安全引用读取可逆转义的批准来源值；
- `GET /api/catalog/imports/{import_id}/source-identifiers/{source_ref_id}`：仅 `data_manager|admin` 在明确草稿和 workflow revision 内读取可逆转义；
- `GET /api/catalog/evidence`：仅 `data_manager|admin` 按批准目录版本和安全引用分页读取来源证据历史；
- `GET /api/catalog/imports/{import_id}/source-identifiers/{source_ref_id}`：仅当前有权读取该草稿的 `data_manager|admin` 解码草稿内 unsafe/collision 引用；
- `GET /api/catalog/unmatched`：分页查询未匹配与排除队列；
- `GET /api/catalog/versions`、`GET /api/catalog/versions/{version_id}/diff`：版本历史和差异；
- `POST /api/catalog/versions/{version_id}/restore`：管理员创建复制旧内容的向前版本；
- `GET /api/catalog/commands/{operation_token}`：仅原操作者无副作用恢复写命令结果；
- `POST /api/catalog/commands/{operation_token}/admin-inspect`：管理员带原因代查并写审计。

状态来源、目标、当前角色、幂等和并发字段以第 10.2 节为唯一契约。除下述 raw-body 上传外，所有 JSON 写请求体含 `operation_token`；首次上传和 `from-export` 都是创建资源，不要求 import revision；已有导入上的九个 POST 全部含 `expected_workflow_revision`，`resume` 另含 `expected_parse_attempt_revision`，`approve/rebase/restore` 使用该节规定的目录 publication counter 和附加绑定。管理员代查请求使用独立的新 `operation_token`，路径中的 token 只是被检查目标。所有资源先由服务端 `CurrentSiteContext` 限定站点，请求体、查询参数和自定义头不接受客户端构造的 `site_id`。

`POST /api/catalog/imports` 的 wire contract 固定为原始 XLSX bytes 请求体，不使用 `multipart/form-data`，以免在流式容量门前增加第二层无界缓冲。请求 required 携带 UUID v4 `Idempotency-Key` header，服务端把它作为本命令的 `operation_token`；required `X-Original-Filename` 是严格 percent-encoded UTF-8，解码后必须是 1～255 个 Unicode scalar 的单一 basename，不含 `/`、反斜杠、NUL、控制字符或换行，并以 ASCII 大小写不敏感的 `.xlsx` 结尾；required `Content-Type` 必须精确为官方 XLSX media type 或第 9.1 节条件兼容的 `application/octet-stream`，不接受参数。文件名只作不可变元数据和扩展名门，不进入存储路径、响应 header 或普通日志。multipart 或不支持的 Content-Type 返回 415 `catalog_workbook_metadata_invalid`；缺失/非法 `Idempotency-Key` 或文件名、空 body、错误扩展名及非法 Content-Length 返回 422 同码。

服务端先检查可选 `Content-Length` 是否为非负十进制并在上限内，再把 request stream 写入有同一硬上限的临时 spool，同时计算实际 bytes 和 SHA-256；header 不能替代实际计数，超过上限立即停止并返回 413 `catalog_workbook_unsafe`，不创建 import/raw file。上传幂等摘要固定覆盖 route、当前 `site_id`、原操作者、解码后的逐字符文件名、规范 Content-Type、实际 byte count 和 raw-body SHA-256，不含 token 自身；同 token 同摘要恢复首次 201 结果，改变 bytes、文件名、media type、站点或操作者都返回 `idempotency_key_reused`。通过流式门后才原子登记不可变 raw file 与 `source_kind=xlsx` import；201 响应使用第 13.1 节统一 counter/permissions envelope。Cookie 认证仍 required `X-CSRF-Token`。OpenAPI requestBody 必须只有两个允许 media type 的 `string/binary` schema，把 `Idempotency-Key` 和 `X-Original-Filename` 标为 required header parameter，并沿用共享 CSRF 安全契约生成前端类型。

`POST /imports/from-export` 请求体恰好含 required UUID v4 `operation_token`、字符串 `export_id` 和非负整数 `expected_catalog_publication_revision`。服务端先完成当前站点和角色授权，再按固定顺序判断：building 返回 409 `catalog_export_not_ready`；failed 返回 409 `catalog_export_failed`；只有 ready 才比较 export 保存值、请求 expected 值和当前权威 `catalog_publication_revision`，三者不等返回 `catalog_publication_revision_conflict`。`workbook_status=ready|capacity_exceeded` 的 ready export 都可创建草稿。一个 ready export 可以由不同 operation token 创建多个独立在线草稿，但同 token 仍只创建一个。

`GET /imports/{import_id}/rows` 的参数固定为 `section=styles|skus|mappings|exceptions|evidence`、trim 后最多 100 字符的可选 `search`、`page>=1`、`page_size=1..200` 和可选非负 `at_workflow_revision`；指定 revision 与当前值不等时返回 409，未指定时读取当前 revision。在线与 XLSX 草稿共用这些 API，不能把超容量行一次性送到浏览器或 Python 内存再分页。

#### 在线草稿行类型

本节全部 JSON schema 固定 `additionalProperties=false`；下列属性全部 required，只有标明 nullable 的值可以显式为 `null`。`row_key` 是导入批次内、section 范围中的不可变 `T(64)` 二进制键：XLSX 行使用工作簿 K/RO 键，online 行由导出记录或 create mutation 产生。`row_origin=system|user_created` 只表示该草稿行来自 export 还是用户创建，不表示正式身份是否存在；款式或 SKU 是既有身份还是待创建身份，只能分别根据 `system_style_id` 或 `system_sku_id` 是否为 null 判断。默认按 `row_key` 原样 UTF-8 bytes 二进制升序。每行还 required 返回 `issues: CatalogImportIssue[]`；issue 固定含不透明 `issue_id`、`severity=blocking|warning`、稳定 `reason_code`、nullable JSON Pointer `field` 和不回显来源原值的 `safe_message`。

`CatalogImportIssue.field` 使用 RFC 6901，并且相对它所在的单个 `CatalogImportRow`，绝不带 section、`rows` 或数组下标；非 null 时必须是恰好一个 segment 的 `/字段名`。只有问题可由该行恰好一个可见、可编辑控件修复时才返回非 null；批次级、跨行、无法唯一归属控件的组级问题、只读字段问题和全部 evidence 行问题必须返回 JSON null，不能返回空字符串。允许的非 null 值按 row type 冻结如下：

| row type | 允许的 `CatalogImportIssue.field` |
| --- | --- |
| `styles` | `/style_code`、`/standard_name`、`/status`、`/change_reason` |
| `skus` | `/style_row_key`、`/internal_display_sku`、`/standard_color`、`/standard_size`、`/status`、`/change_reason` |
| `mappings` | `/identity_decision`、`/target_sku_row_key`、`/target_internal_display_sku`、`/exclusion_reason`、`/change_reason` |
| `exceptions` | `/action`、`/target_sku_row_key`、`/corrected_style_code`、`/corrected_standard_color`、`/corrected_standard_size`、`/exclusion_reason`、`/note` |
| `evidence` | 无；始终为 null |

`CatalogImportRowsResponse` required 返回 `import_id`、请求 `section`、本页读取时的 `workflow_revision`、`parse_attempt_revision`、`current_catalog_publication_revision`、该 section 的 `rows` 判别联合、`total_rows/page/page_size` 和 `permissions`。同一页只能出现所请求的 row type；客户端跨页时若见 revision 改变必须丢弃已拼接页面并从第一页重读，保存时必须把响应 revision 原样作为 expected 值。

`CatalogImportDetailResponse` 除第 13.1 节统一状态、source、counter 和 permissions 字段外，required 返回 `section_counts`，且恰好含 `styles/skus/mappings/exceptions/evidence` 五个键；每个值 required 含非负整数 `row_count/blocking_issue_count/warning_issue_count`，全部计数来自同一 workflow revision。它不返回 issue 文本或行数组，前端只能结合对应 rows 页显示可聚焦问题。

`CatalogImportRow` 是以下五种 schema 以 `row_type` 为 discriminator 的 `oneOf` 联合：

- `StyleImportRow`：`row_type="styles"`、`row_key`、`row_origin`、`projection_state=included|audit_only`、nullable `system_style_id`、非空 `style_code`、nullable `standard_name`、`status=enabled|disabled`、nullable 非负 `candidate_seller_sku_count/source_title_count`、nullable 日期 `first_seen_date/latest_seen_date`、nullable `change_reason`、`issues`。`projection_state` 由第 10.3 节服务端计算、不可提交；`system_style_id` 仅对既有批准目录成员非空，系统候选和用户新增行都为 null；两个计数仅 `row_origin=system` 时非空。`included` 行的 `standard_name=null` 只允许停留在候选或 `needs_attention`，完整验证阻断；`audit_only` 系统候选允许保持 null；
- `SkuImportRow`：`row_type="skus"`、`row_key`、`row_origin`、`projection_state=included|audit_only`、nullable `system_sku_id`、非空 `style_row_key`、nullable `internal_display_sku/standard_color/standard_size`、`status=enabled|disabled`、nullable `source_color_candidates_preview/source_color_candidates_sha256/source_size_candidates_preview/source_size_candidates_sha256`、nullable日期 `first_seen_date/latest_seen_date`、nullable `change_reason`、`issues`。`projection_state` 由服务端计算、不可提交；`system_sku_id` 仅对既有批准目录成员非空，系统候选和用户新增行都为 null；`included` 行的三个 nullable 身份字段每个 null 都形成 blocking issue并阻止完整验证，`audit_only` 系统候选允许保持 null；
- `MappingImportRow`：`row_type="mappings"`、`row_origin="system"`、`row_key`、固定等于 row key 的非空 `decision_group_key`、`seller_account`、`marketplace="amazon_us"`、`seller_sku: SafeSourceRef`、日期 `first_seen_date/latest_seen_date`、非负 `business_occurrence_count/return_occurrence_count/exception_count`、nullable `identity_decision=mapped|excluded`、nullable `target_sku_row_key/target_internal_display_sku/exclusion_reason/change_reason`、`issues`；该行不得创建或删除，关联异常行共享此 group key；
- `ExceptionImportRow`：`row_type="exceptions"`、`row_origin="system"`、`row_key/decision_group_key/reason_code`、`seller_sku: SafeSourceRef`、`source_report=business|returns|both`、nullable `candidate_style_code/candidate_color/candidate_size`、nullable `action=map_existing_variant|create_new_variant|correct_parse|exclude`、nullable `target_sku_row_key/corrected_style_code/corrected_standard_color/corrected_standard_size/exclusion_reason/note`、`issues`；同一 group 的规范决定字段相同，note 仍属于单行；
- `EvidenceImportRow`：`row_type="evidence"`、`row_origin="system"`、`row_key`、`seller_sku: SafeSourceRef`、`report_type=business|returns`、日期 `first_seen_date/latest_seen_date`、非负 `occurrence_count/distinct_title_count/distinct_parent_asin_count/distinct_child_asin_count/distinct_fnsku_count`、nullable `latest_title: SafeSourceRef`、非空 `evidence_set_sha256`、`issues`；全部业务字段只读。

所有来源预览都复用第 13.2 节的 `SafeSourceRef`；普通 rows 响应不返回原字符串。字符串长度、trim、条件必填和动作矩阵与第 9.2～9.3 节逐字段一致；草稿可表达的暂时缺失保存为 null，当前 `included` 或未决定组推荐候选的条件必填缺失产生 blocking issue，`audit_only` 系统候选不产生身份字段 issue；非法类型、超长、未知引用或修改 RO 字段不能持久化。

#### 在线草稿 mutation

`CatalogDecisionBatchRequest` required 且只含 UUID v4 `operation_token`、非负 `expected_workflow_revision` 和 `mutations: CatalogDecisionMutation[]`；`POST /imports/{import_id}/decisions` 只接受该 schema，数组为 1～500 项。每项 required 含批次内唯一 UUID v4 `mutation_id` 和下列 `type` 判别字段，未列字段拒绝；`CatalogDecisionMutation` 是这些类型以 `type` 为 discriminator 的 `oneOf` 联合：

- `create_style`：UUID v4 `client_row_key`、非空 `style_code`、nullable `standard_name`、`status`、nullable `change_reason`；
- `update_style`：`row_key` 加完整替换的 `style_code`、nullable `standard_name`、`status`、nullable `change_reason`；
- `delete_style`：`row_key`；只允许无 SKU 引用的 user-created 行；
- `create_sku`：UUID v4 `client_row_key`、非空 `style_row_key`、nullable `internal_display_sku/standard_color/standard_size`、`status`、nullable `change_reason`；
- `update_sku`：`row_key` 加完整替换的非空 `style_row_key`、nullable `internal_display_sku/standard_color/standard_size`、`status` 和 nullable `change_reason`；
- `delete_sku`：`row_key`；只允许没有 mapping/exception 引用的 user-created 行；
- `map_seller_sku`：`decision_group_key/target_sku_row_key`、nullable `target_internal_display_sku_check/change_reason`；
- `exclude_seller_sku`：`decision_group_key`、10～500 scalar `exclusion_reason`、nullable `change_reason`；
- `clear_seller_sku_decision`：`decision_group_key`、nullable `change_reason`；
- `resolve_exception_map_existing` 或 `resolve_exception_create_new`：`decision_group_key/target_sku_row_key`、nullable `change_reason`；前者目标必须满足 `system_sku_id != null`，后者必须满足 `system_sku_id == null`，均不按 `row_origin` 判断；
- `resolve_exception_correct_parse`：`decision_group_key/target_sku_row_key/corrected_style_code/corrected_standard_color/corrected_standard_size`、nullable `change_reason`；
- `resolve_exception_exclude`：`decision_group_key`、10～500 scalar `exclusion_reason`、nullable `change_reason`；
- `clear_exception_group`：`decision_group_key`、nullable `change_reason`；
- `update_exception_note`：异常 `row_key` 和 nullable `note`。

同批次的 `client_row_key` 必须唯一，并可被同一批次的 SKU、mapping 或 exception mutation 引用；服务端先解析全部 create key 再校验引用，因此超容量在线路径可以在一个原子批次创建款式、创建 SKU 并解决异常。一个请求不得两次定位同一 `(row_type,row_key)` 或 `decision_group_key`，不得创建后又删除同一 key，也不得形成引用环。含异常行的 group 只接受 exception-group mutation；该 mutation 在同一事务同步更新组内全部异常行和唯一 mapping 行，普通 mapping mutation不得制造第二套 payload。

非幂等重放的成功批次全成或全败，只把 `workflow_revision` 增加一次；`CatalogDecisionBatchSuccess` required 返回 `import_id/source_kind/raw_file_id/workflow_revision/parse_attempt_revision/current_catalog_publication_revision/applied_mutation_count/permissions`。成功新 revision 精确等于 expected＋1，相同 token 重放返回首次结果。成功后客户端使受影响 section 缓存失效并重读。

字段或交叉引用校验失败返回 422 `catalog_decisions_invalid`，零业务写入、revision 不变；`CatalogDecisionValidationError` required 返回 `import_id`、固定 `reason_code="catalog_decisions_invalid"`、当前 `workflow_revision` 和 `issues: CatalogDecisionIssue[]`。每个 issue 的 `mutation_id/row_key/decision_group_key/field` 都 required 但可为 null，另有稳定 `reason_code` 和安全 `message`。`CatalogDecisionIssue.field` 同样使用 RFC 6901，但相对非 null `mutation_id` 精确定位的单个 mutation 对象，绝不返回 `/mutations/{index}/...`；非 null 时必须是恰好一个 segment。`mutation_id=null`、问题跨 mutation、目标定位符本身无效、没有唯一可编辑控件或属于只含定位符的 delete mutation 时，`field` 必须为 JSON null。允许的非 null 值按 mutation type 冻结如下：

| mutation type | 允许的 `CatalogDecisionIssue.field` |
| --- | --- |
| `create_style`、`update_style` | `/style_code`、`/standard_name`、`/status`、`/change_reason` |
| `delete_style`、`delete_sku` | 无；始终为 null |
| `create_sku`、`update_sku` | `/style_row_key`、`/internal_display_sku`、`/standard_color`、`/standard_size`、`/status`、`/change_reason` |
| `map_seller_sku` | `/target_sku_row_key`、`/target_internal_display_sku_check`、`/change_reason` |
| `exclude_seller_sku` | `/exclusion_reason`、`/change_reason` |
| `clear_seller_sku_decision` | `/change_reason` |
| `resolve_exception_map_existing`、`resolve_exception_create_new` | `/target_sku_row_key`、`/change_reason` |
| `resolve_exception_correct_parse` | `/target_sku_row_key`、`/corrected_style_code`、`/corrected_standard_color`、`/corrected_standard_size`、`/change_reason` |
| `resolve_exception_exclude` | `/exclusion_reason`、`/change_reason` |
| `clear_exception_group` | `/change_reason` |
| `update_exception_note` | `/note` |

issue reason 至少包含 `required|invalid_enum|too_long|conditional_fields_invalid|invalid_reference|immutable_field|duplicate_target|system_row_delete_forbidden|group_payload_conflict|reference_cycle`。revision 不匹配仍优先返回既有 409；鉴权先于 counter 和字段 issue。任何 issue/message 都不得回显危险来源原值。

#### 来源证据分页与安全 reveal

`GET /api/catalog/evidence` 参数固定为 `source_ref_id`（kind 必须为 `seller_sku`）、可选 `catalog_version_id`、`page>=1` 和 `page_size=1..200`；省略版本使用当前批准目录，历史版本按第 10.6 节鉴权。响应 required 返回 `catalog_version_id/source_ref_id/rows/total_rows/page/page_size`。每个 evidence row required 含不透明 `evidence_id`、`report_type/report_date`、nullable `event_date`、不透明 `publication_id`、`seller_sku: SafeSourceRef`、nullable `title/parent_asin/child_asin/fnsku: SafeSourceRef` 和 nullable `source_locator_ref`；后者仅 admin 非空。排序固定为 report type、report date、publication ID、evidence ID 的 UTF-8 bytes 二进制升序。ref 必须属于请求目录中的 mapped 或 excluded 成员。权限判定先于资源定位：viewer 固定返回 403；对有 evidence 权限的 `data_manager|admin`，错误 kind、跨站点 ref、非该目录成员、不属于所选目录版本或跨 import/catalog 复用一律返回 404 `catalog_source_ref_not_found`，不得以状态、正文或时序披露目标是否在其他资源中存在。

批准来源 reveal 使用 `/source-identifiers/{source_ref_id}` 并接受可选 `catalog_version_id`（省略即当前目录）。草稿来源 reveal 精确使用 `/imports/{import_id}/source-identifiers/{source_ref_id}`，required 携带非负 `at_workflow_revision`。服务端每次先按当前 `site_id`、角色和 catalog/import 读取权限鉴权，viewer 固定返回 403；已授权 `data_manager|admin` 的草稿请求再比较 revision，不等时在任何 ref 定位前返回 409 `catalog_workflow_revision_conflict`，相等后才验证明确 membership。两类 reveal 都只返回第 13.2 节的 ASCII code-point 转义和 UTF-8 base64url，不直接返回原字符串。历史 evidence 页面必须把同一 catalog version 带到 reveal，禁止拿一个草稿 ref 到另一个 import 或批准端点解码。已授权角色遇到错误 kind、跨站点、错误 catalog/import membership、错误目录版本及跨批准/草稿端点复用，统一返回 404 `catalog_source_ref_not_found`。证据分页和 reveal GET 可以追加只含安全对象 ID 的访问审计，这是 HTTP safe 方法允许的观察性日志副作用；它们不得改变目录、导入状态或任何 revision/counter。响应固定 `Cache-Control: private, no-store`，viewer 永不 reveal。

客户端取得 counter 的响应契约固定为：

- `POST /imports` 或 `/imports/from-export` 初始响应、`GET /imports/{import_id}` 和已有导入的每个成功 POST 都 required 返回 `source_kind=xlsx|online`、nullable `raw_file_id`、最新非负整数 `workflow_revision`、`parse_attempt_revision`、`current_catalog_publication_revision` 及按当前角色计算的 `permissions`；online 的 raw file 永远为 null 且 `can_download_original=false`。409 revision 冲突的安全错误 `meta` 也返回三个当前 counter；
- `POST /exports` 和 `GET /exports/{export_id}` 使用下述同一 `CatalogExport` 状态矩阵；rebase 的 `replacement_export_id` 必须引用该站点仍为 ready 且 publication revision 与请求 expected 值相同的 export；
- `GET /versions` 及 `GET /versions/{version_id}/diff` 的 envelope required 返回非负整数 `current_catalog_publication_revision`，供 restore 使用；
- `approval-preview` 成功响应 required 返回 `projection_id/projection_digest/created_at/expires_at/workflow_revision/validation_run_id/base_catalog_version_id/catalog_publication_revision/fact_snapshot_tuple_id/risk/diff_digest`，其中 `risk=normal|high`；摘要字段只返回当前角色有权读取的脱敏投影，完整内部定位符不出 API。

导入响应中的 `permissions: CatalogImportPermissions` 固定含十一个 required boolean：`can_view`、`can_edit`、`can_validate`、`can_submit`、`can_preview`、`can_approve_normal`、`can_approve_high_risk`、`can_reject`、`can_withdraw`、`can_rebase`、`can_download_original`。它们同时考虑当前角色、所有权、`submitted_by`、风险和当前状态；前端可用来禁用动作，但服务端命令仍重新鉴权。

上述 counter 都是 JSON number 的非负安全整数。服务端先完成当前站点成员、资源和字段读取授权，再返回 409 counter `meta`，不能向无权主体披露 revision。命令重放和 `GET /commands/{operation_token}` 每次披露结果前也重新执行当前权限；权限丢失只返回 403，不改变已保存 effect。OpenAPI 将这些字段标为 required，前端不得从状态名推算 revision。

`CatalogExport` 的全部键都 required，但按状态 nullable：

| 字段 | `building` | `ready` | `failed` |
| --- | --- | --- | --- |
| `export_id/export_status/created_at/updated_at` | 非空 | 非空 | 非空 |
| `failure_reason` | `null` | `null` | 非空稳定 reason code |
| `base_catalog_version_id` | `null` | nullable；只在首次初始化为 `null` | `null` |
| `catalog_publication_revision/fact_snapshot_tuple_id` | `null` | 非空 | `null` |
| 六表 `row_counts` 与 `total_rows` | `null` | 非空非负整数 | `null` |
| `workbook_status` | `null` | `ready|capacity_exceeded` | `null` |
| `capacity_violations` | `null` | workbook ready 时为空数组；capacity exceeded 时非空 | `null` |
| `workbook_download_url` | `null` | 仅 workbook ready 时为同站点相对 URL，否则 `null` | `null` |

`export_status` 只允许 `building|ready|failed` 且单向终结；failed 不伪造 fact tuple 或行数。文件端点对 building 返回 409 `catalog_export_not_ready`，failed 返回 409 `catalog_export_failed`，ready＋capacity exceeded 返回 409 `catalog_workbook_capacity_exceeded`，只有 ready＋workbook ready 返回文件。

### 13.2 商品分析 API

现有接口保持原路径和原语义，兼容期内不得把路径参数改解释为 `style_id`：

- `GET /api/dashboard/product-ledger`：现有按临时 `style_code` 聚合的旧响应；
- `GET /api/dashboard/product-card/{style_code}`：现有款号商品卡。

P0 新建无歧义资源：

- `GET /api/dashboard/style-ledger`：按稳定款式分页的产品总表；
- `GET /api/dashboard/styles/{style_id}/card`：按稳定款式返回汇总、实际变体、覆盖和趋势。

新旧端点双轨时绝不互相 fallback，也不根据“是否为数字”猜参数类型。旧接口只在兼容验收完成后经单独弃用变更移除。

#### 产品总表请求

`GET /api/dashboard/style-ledger` 的参数固定为：

| 参数 | 规则与默认值 |
| --- | --- |
| `from`、`to` | `YYYY-MM-DD` 闭区间；默认截至当前业务日的 31 天；跨度 1～366 天；`to` 不得晚于请求一致性快照中 reporting timezone 的当前业务日 |
| `search` | trim 后 0～100 字符；匹配当前批准标准字段和允许搜索的批准标识 |
| `sort` | `style_code|standard_name|units|sales|returns|sessions|conversion`，默认 `units` |
| `direction` | `asc|desc`，默认 `desc`；最后总以 `style_id ASC` 稳定打破并列 |
| `page` | 1 起，默认 1 |
| `page_size` | `1..100`，默认 50 |
| `catalog_version` | 不透明 ID；current 时省略或必须等于当前目录，snapshot 时必填；历史版本受第 10.6 节权限限制 |
| `fact_basis` | `current|catalog_snapshot`，默认 `current` |
| `return_basis` | `event_date|report_date`，默认 `event_date` |

响应 `rows` 每项固定返回：字符串 `style_id/style_code/standard_name`、枚举 `status`、非负整数 `sku_count/color_count/size_count/source_title_count`、nullable 日期 `latest_report_date` 和含五个 `MetricValue` 的 `metrics`。分页 envelope 返回非负整数 `total_rows`、正整数 `page/page_size`、枚举 `sort/direction`，并在顶层返回站点级 `coverage`、`reconciliation`、`provenance` 和 `permissions`；搜索不产生“未归类款式”伪行，全局未匹配值只进入站点级对账桶。

#### 商品卡请求

`GET /api/dashboard/styles/{style_id}/card` 接受相同的 `from/to/catalog_version/fact_basis/return_basis`，另有：

| 参数 | 规则与默认值 |
| --- | --- |
| `metric` | `units|sales|returns|sessions|conversion`，默认 `units` |
| `dimension` | `total|color|size|sku`，默认 `color` |
| `color_key` | 目录版本内稳定、不透明的标准颜色 revision key；`size` 必填，其他维度禁止 |
| `series` | 逗号分隔的稳定 series key，显式提供时 1～8 个且不重复；省略时使用第 14.3 节默认算法，空字符串非法 |

版本内 key 使用无 padding 的完整 base64url SHA-256：输入依次为 `catalog_version_id`、NUL、`style_id`、NUL、dimension、NUL 和该维度规范值的 UTF-8 bytes；size 再追加 NUL＋颜色规范值，sku 维度改用稳定 `sku_id`。服务端用完整 tuple 复核 digest，客户端只保存响应给出的 key、不得自行构造。标准值在后继目录修订后 key 可以变化，因此 URL 恢复必须按第 14.3 节处理失效 key。

`return_basis` 始终决定 summary 和 variants 中 returns 的分组，因此 `effective_return_basis` 总是回显其有效值；当折线 metric 不是 returns 时，另返回 `trend_effective_return_basis=null`，表示该参数没有改变当前折线。`dimension=total` 只有固定系列 `total`；`color` 返回全部实际颜色；`size` 只返回所选颜色下的实际尺码；`sku` 返回日期区间内有事实或当前启用的实际 SKU。停用 SKU 在所选历史范围有事实时仍可显示。

响应固定包含：

- `style`：字符串 `style_id/style_code/standard_name`、枚举 `status` 和非负整数 `sku_count/color_count/size_count`；
- `summary`：只含五个 `MetricValue` 的 `metrics`；
- `available_series`：稳定 key、展示 label、维度值、区间合计、默认排序和是否活动；
- `series`：仅活动系列，每条含按日期升序的连续日点；
- `variants`：每项固定为字符串 `sku_id/standard_color/standard_size/internal_display_sku`、枚举 `status`、按服务端二进制匹配键排序的 `seller_sku_aliases: SafeSourceRef[]` 和五个 `MetricValue`；
- 仅基于 publication 表的 `source_report_coverage`、本款 `style_reconciliation`、`provenance` 和 `permissions`；不返回全站身份 coverage 或六桶。

每日点固定 required 返回 `date`、`value`、`value_state`、`null_reason`、`source_completeness`、`numerator` 与 `denominator`；非 conversion 点的后两项显式为 null，conversion 按状态矩阵返回整数或 null。`available_series` 按区间合计降序、规范化 label、稳定 key 排序，不能依数据库偶然顺序。

#### 数值与 provenance

五项区间指标都使用固定 `MetricValue` 对象，不以一个总 `is_partial` 混合不同报表：`value`、`value_state`、`null_reason`、`is_partial`、`observed_days`、`expected_days`、`source_completeness`、`numerator` 和 `denominator` 全部 required，并遵守第 12.4 节区间矩阵。`null_reason` schema 允许 `null|missing_report|undefined_denominator|no_observed_reports`，但区间对象不得使用 `missing_report`；该字面值只供每日点使用。非 conversion 的 numerator/denominator 固定为 `null`；conversion 有观察来源时返回整数分子分母，无观察来源时两者为 `null`。units/sales/sessions/conversion 的 partial 只由经营 coverage 决定；returns 的 partial 由退货 coverage 或 unresolved duplicate 决定，不能把一类报表缺口传播到全部五项。

JSON 中 units、sessions 和 conversion numerator/denominator 是有符号整数；returns、天数和行数是非负整数。USD sales 的 `value` 是可带负号、两位小数的十进制字符串，例如 `"-12.50"`；conversion 是可带负号、六位小数十进制字符串或 `null`，不设 1 上限；只有覆盖率限制在 0～1。所有 decimal 使用精确 Decimal，conversion/coverage 量化到六位时采用 `ROUND_HALF_UP`，禁止 binary float。所有 ID 都是字符串。产品总表的 `coverage.scope` 和 `reconciliation.scope` 固定为 `site`；单款内部守恒由 `style_reconciliation` 验证。

第一版嵌套结构固定如下，字段均为 required；标为 nullable 的字段必须显式返回 `null`：

- `SafeSourceRef`：不透明字符串 `source_ref_id`、安全字符串 `preview`、`sha256:`＋64 位小写十六进制 `sha256`、boolean `is_unsafe/is_truncated`。preview 使用第 9.2 节同一算法和 255 scalar 上限；任一 scalar 被替换或使用 `[不可显示]` 时 `is_unsafe=true`，安全化结果截断前超过 255 scalar 时 `is_truncated=true`。普通商品 API 永远不返回原始来源字符串。授权 source-identifiers 端点返回同一 ref、枚举 `kind=seller_sku|parent_asin|child_asin|fnsku|title`、ASCII `escaped_codepoints` 和无 padding `utf8_base64url`；`escaped_codepoints` 把每个 Unicode scalar 写为大写 `U+`＋4～6 位十六进制并以单个空格分隔，因而可逆且不会把 NUL、换行、bidi 或不可见字符送入 DOM。该端点响应为 `private, no-store`，访问写审计，应用日志只记 ref/digest，不记转义串或 base64。
- `CoverageBlock`：`report_type` 为枚举；`coverage_from/to` 为日期字符串；`expected_days/published_days/missing_days`、`eligible_rows/mapped_rows/unmatched_rows/excluded_rows` 为非负整数；`unique_rows/confirmed_distinct_rows/duplicate_of_rows/unresolved_rows` 为 nullable 非负整数；`report_coverage_rate/identity_decision_rate/mapping_rate/dedup_decision_rate` 为 nullable 六位小数字符串；`identity_status`、`dedup_status` 为第 12.4 节枚举。经营报告的四个 dedup 行数和 `dedup_decision_rate` 为 `null`，状态为 `not_applicable`；任何 rate 分母为零时为 `null`。
- 产品总表 `coverage`：`scope="site"`、`business: CoverageBlock`、`returns: CoverageBlock`。
- `PublicationDay`：枚举 `report_type`、日期字符串 `report_date`、枚举 `report_status`、nullable 字符串 `dataset_id/published_version_id/snapshot_member_id` 和 nullable 非负整数 `pointer_revision`。`source_report_coverage` 含日期字符串 `coverage_from/to`、按 report type/date 排序的 `days: PublicationDay[]`，以及 nullable 日期字符串 `contributing_report_date_from/to`。
- `MetricTotals`：nullable 有符号整数 `units/sessions/conversion_numerator/conversion_denominator`、nullable 两位有符号小数字符串 `sales`、nullable 非负整数 `returns`；不适用或不可评估项为 `null`，适用且可评估的真零不得写 null。
- `MetricEvaluability`：五个 required 枚举 `units/sales/returns/sessions/conversion=evaluable|not_evaluable`；conversion 状态指其 numerator/denominator 能否对账，分母为零仍是 evaluable。
- 产品总表 `reconciliation`：`scope="site"`、`metric_status: MetricEvaluability`，以及六个 required `MetricTotals`：`source_totals`、`mapped_totals`、`unmatched_totals`、`excluded_totals`、`duplicate_totals`、`unresolved_duplicate_totals`。
- 商品卡 `style_reconciliation` 有七个 required 字段：`scope="style"`、`metric_status: MetricEvaluability`、`series_scope=style|selected_color`、`summary_totals: MetricTotals`、`variant_totals: MetricTotals`、`series_scope_totals: MetricTotals` 和 nullable `selected_color_totals: MetricTotals`。`summary_totals` 与覆盖整款全部 SKU 的 `variant_totals` 始终逐项相等。`dimension=total|color|sku` 时 `series_scope=style`、`selected_color_totals=null`，并且 `series_scope_totals=summary_totals`；`dimension=size` 时 `series_scope=selected_color`，`selected_color_totals` 非空且只汇总 `color_key` 下全部 SKU，`series_scope_totals=selected_color_totals`。`series_scope_totals` 始终使用该请求维度和筛选范围的全部 available series，不只使用当前最多八个活动系列。
- `permissions`：七个 required boolean：`can_view_catalog_history`、`can_manage_catalog`、`can_view_evidence_history`、`can_download_original`、`can_submit`、`can_approve_normal`、`can_approve_high_risk`。
- `PublicationRefs`：`mode=current|catalog_snapshot`、nullable `snapshot_id`、固定 `members_digest_version="publication_refs_jcs_v1"`、`members_digest`、`members: PublicationDay[]`。current 返回实际影响经营区间、退货事件区间和来源覆盖带的全部 publication；snapshot 返回所用 snapshot 的对应成员。`publication_refs_jcs_v1` 的 payload 精确为每个成员只含 `report_type/report_date/report_status/dataset_id/published_version_id/snapshot_member_id/pointer_revision` 七个 required 键（nullable 值仍编码为 JSON null）的对象数组；先按这七项依次排序，null 在非 null 前，字符串按原样 UTF-8 bytes、整数按数值升序，再用 RFC 8785 JCS 编码为 UTF-8。digest 固定为 `sha256:`＋payload bytes 的 64 位小写十六进制；版本和 digest 随 provenance 保存，算法升级不得重算旧响应/快照摘要。

`MetricTotals` 的 null 与守恒按下述矩阵解释，不能由实现自行选择：business 来源的 units/sales/sessions/conversion 在 `observed_days=0` 时全部六桶相应字段为 null、`metric_status=not_evaluable`，不执行数值等式；`observed_days>0` 时 source/mapped/unmatched/excluded 为数值（包括真零）、duplicate/unresolved 对这些业务字段始终为不适用 null，且 source 精确等于前三个结果桶之和。`return_basis=report_date` 的 returns 在 `observed_days=0` 时六桶 returns 全为 null且 not_evaluable，观察日大于零时六桶均为非负数并执行 source＝mapped＋unmatched＋excluded＋duplicate＋unresolved。`return_basis=event_date` 的 returns 无论 report-date `observed_days` 是否为零都为 evaluable，六桶必须返回非负数并执行同一等式；没有事件事实是真零，`source_completeness=indeterminate` 仍不能改成 null。商品卡使用相同 metric status；not_evaluable 时相应 summary/variant/series totals 全为 null 并按状态一致性比较，不把 all-null 当数值等式。

产品总表每行和商品卡 summary/variant 的五项指标都使用 `MetricValue`。`available_series` 每项固定返回 `key`、`label`、`dimension`、`total: MetricValue`、`active`、`sort_order`；总值为 null 的系列排最后，其余按 Decimal 数值降序（包括零和负数）排序。趋势点在区间对象基础上固定返回 `date/value/value_state/null_reason/source_completeness/numerator/denominator`，非 conversion 的 numerator/denominator 为 null。

两个新响应都含同一结构的 `provenance`：

- `catalog_version_id`、站点内版本号、`fact_basis`；
- `identity_source=legacy_parser|p0_catalog|e0_snapshot` 和对应字符串 `identity_version_id`；新端点在 P0 切换后固定为 `p0_catalog + catalog_version_id`；
- `publication_refs: PublicationRefs`；
- `return_dedup_snapshot_id`、`site_config_version_id`；
- IANA `reporting_timezone`、`consistent_as_of`、`fact_cutoff_at`；
- `from/to/return_basis/effective_return_basis/trend_effective_return_basis`。

兼容旧端点继续原 JSON 语义，并通过响应头 `X-Identity-Source: legacy_parser` 与 `X-Identity-Version: seller_sku_parser_v1` 声明来源；新端点不得返回 legacy 来源。E0 切换后 current 新端点原子改为 `e0_snapshot`，一次响应只能出现一个 identity source。

脱敏商品卡示例：

```json
{
  "style": {"style_id": "sty_demo", "style_code": "2301", "standard_name": "示例上衣", "status": "enabled"},
  "summary": {
    "metrics": {
      "units": {"value": 12, "value_state": "observed", "null_reason": null, "is_partial": false, "observed_days": 1, "expected_days": 1, "source_completeness": "complete", "numerator": null, "denominator": null},
      "sales": {"value": "359.88", "value_state": "observed", "null_reason": null, "is_partial": false, "observed_days": 1, "expected_days": 1, "source_completeness": "complete", "numerator": null, "denominator": null},
      "returns": {"value": 1, "value_state": "observed", "null_reason": null, "is_partial": false, "observed_days": 1, "expected_days": 1, "source_completeness": "indeterminate", "numerator": null, "denominator": null},
      "sessions": {"value": 80, "value_state": "observed", "null_reason": null, "is_partial": false, "observed_days": 1, "expected_days": 1, "source_completeness": "complete", "numerator": null, "denominator": null},
      "conversion": {"value": "0.150000", "value_state": "observed", "null_reason": null, "is_partial": false, "observed_days": 1, "expected_days": 1, "source_completeness": "complete", "numerator": 12, "denominator": 80}
    }
  },
  "available_series": [
    {"key": "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA", "label": "Black", "dimension": "color", "total": {"value": 7, "value_state": "observed", "null_reason": null, "is_partial": false, "observed_days": 1, "expected_days": 1, "source_completeness": "complete", "numerator": null, "denominator": null}, "active": true, "sort_order": 1}
  ],
  "series": [
    {"key": "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA", "points": [
      {"date": "2026-07-01", "value": 7, "value_state": "observed", "null_reason": null, "source_completeness": "complete", "numerator": null, "denominator": null}
    ]}
  ],
  "style_reconciliation": {
    "scope": "style",
    "metric_status": {"units": "evaluable", "sales": "evaluable", "returns": "evaluable", "sessions": "evaluable", "conversion": "evaluable"},
    "series_scope": "style",
    "summary_totals": {"units": 12, "sales": "359.88", "returns": 1, "sessions": 80, "conversion_numerator": 12, "conversion_denominator": 80},
    "variant_totals": {"units": 12, "sales": "359.88", "returns": 1, "sessions": 80, "conversion_numerator": 12, "conversion_denominator": 80},
    "series_scope_totals": {"units": 12, "sales": "359.88", "returns": 1, "sessions": 80, "conversion_numerator": 12, "conversion_denominator": 80},
    "selected_color_totals": null
  },
  "provenance": {
    "catalog_version_id": "cat_demo_1", "catalog_version": 1, "fact_basis": "current",
    "identity_source": "p0_catalog", "identity_version_id": "cat_demo_1",
    "publication_refs": {"mode": "current", "snapshot_id": null, "members_digest_version": "publication_refs_jcs_v1", "members_digest": "sha256:71782801412e329363ce8df0b8498cd590b079664432cfe63ba6bfeb996b829a", "members": [{"report_type": "business", "report_date": "2026-07-01", "report_status": "published", "dataset_id": "ds_demo", "published_version_id": "ver_demo", "pointer_revision": 1, "snapshot_member_id": null}]},
    "return_dedup_snapshot_id": "rds_demo",
    "site_config_version_id": "cfg_demo", "reporting_timezone": "America/Los_Angeles",
    "consistent_as_of": "2026-08-19T02:00:00Z", "fact_cutoff_at": "2026-08-19T02:00:00Z",
    "from": "2026-07-01", "to": "2026-07-01", "return_basis": "event_date", "effective_return_basis": "event_date", "trend_effective_return_basis": null
  }
}
```

示例只展示结构子集；OpenAPI schema 中商品卡上述顶层字段全部 required。产品总表的 reconciliation 六个桶全部 required，不能因值为零或不适用而省略。

#### 参数组合与稳定错误

| 条件 | HTTP | reason code |
| --- | --- | --- |
| 日期格式、顺序、366 天上限或未来 `to` 错误 | 422 | `analytics_date_range_invalid` |
| `catalog_snapshot` 未给目录版本 | 422 | `analytics_catalog_version_required` |
| current 搭配历史目录，或其他身份源/事实口径非法组合 | 409 | `analytics_identity_fact_combination_invalid` |
| snapshot 不覆盖请求范围 | 409 | `catalog_snapshot_range_out_of_bounds` |
| 无权读取历史目录 | 403 | `catalog_history_forbidden` |
| 稳定款式不存在于所选目录 | 404 | `catalog_style_not_found` |
| 非 size 维度携带颜色，或 size 缺颜色 | 422 | `analytics_dimension_parameter_invalid` |
| 颜色 key 不属于所选款式/目录 | 404 | `catalog_color_not_found` |
| series 为空字符串、重复、未知或超过 8 个 | 422 | `analytics_series_invalid` |
| metric、dimension、sort 或分页枚举/边界错误 | 422 | `analytics_parameter_invalid` |

全部参数组合必须由表驱动契约测试覆盖。响应由 OpenAPI 生成前端类型，禁止手改生成文件；生成后必须通过仓库现有 OpenAPI drift check。

### 13.3 查询执行

商品分页、筛选、排序和指标聚合在 MySQL 完成。每个响应在一个 `REPEATABLE READ` 只读事务中先固定站点配置、目录、事实成员和 dedup snapshot；产品总表再执行计数、页数据、站点 coverage/六桶，商品卡只执行本款趋势、publication coverage 和 style reconciliation。事务内任一指针变化不可见。查询必须先限定站点、目录版本、事实成员和日期，再连接映射；不能先读取整月所有行到 Python 后聚合。

第一版索引覆盖：

- 当前 publication 版本与 report date；
- 发布行 Seller SKU 匹配键；
- 目录版本＋scope＋Seller SKU 匹配键；
- `style_id`、`sku_id` 和标准颜色/尺码规范键；
- 退货事件时间；
- 商品目录当前指针。

实施计划必须用第 20.5 节固定脱敏 fixture 执行 `EXPLAIN ANALYZE`，证明过滤和聚合不退化为无界全表读取。

## 14. 前端体验

### 14.1 路由

- `/products`：面向运营的稳定款式产品总表；
- `/products/:style_id`：独立商品详情与变体趋势页；
- `/catalog`：当前批准商品主档；
- `/catalog/styles/:style_id`：款式、变体和当前批准标识；证据历史与 revision tab 按角色服务端裁剪；
- `/catalog/imports/:import_id`：XLSX 审核；
- `/catalog/unmatched`：待处理队列；
- `/catalog/versions`：版本历史。

商品趋势不再复用现有 modal，也不使用对话框焦点陷阱；详情采用可直达、刷新、前进/后退恢复的页面。商品主档是分析和生产共同基础，不放在 `/production` 内。原生产计划的“SKU 档案”入口改为链接共享商品主档，不复制第二套 CRUD。

### 14.2 产品总表

产品总表继续一款一行：

- 商品名称固定显示标准商品名称；
- 原始标题差异显示“多个来源标题”徽标和数量，不再把该文案当商品名称；数量来自当前目录版本冻结的全部历史来源证据，不随产品表当前日期筛选变化；
- 显示订购件数、销售额、退货件数、会话数、转化率和数据覆盖状态；
- 支持款号、标准名称、Seller SKU、ASIN、FNSKU、标准颜色和标准尺码搜索；
- 支持服务端排序、分页和 URL 状态恢复。

`/products` 固定使用 `from`、`to`、`search`、`sort`、`direction`、`page`、`page_size`、`return_basis`、`catalog_version` 和 `fact_basis` 查询参数；默认值、枚举和边界与第 13.2 节一致。搜索、排序或日期改变时 page 重置为 1；从详情返回必须恢复完整列表 URL。

区间缺报时仍显示已观察日的部分合计，并在数值旁固定显示“数据不完整（已发布 X/Y 天）”；不得把 partial 合计伪装成完整月度值。转化率空值分别显示“无已发布数据”或“会话为 0”，不能统一显示 `--` 隐藏原因。

### 14.3 商品详情与趋势

商品详情顶部显示标准名称、款号、实际变体数、最近发布日和分报表 publication 覆盖。本款内部只展示已映射事实的 SKU/颜色/尺码守恒；全站身份决定覆盖、映射行覆盖和六桶只在 `/products` 顶部显示，商品卡不猜测未归类行属于哪个款式。

趋势默认：

- 指标为订购件数；
- 维度为颜色；
- 退货口径为事件日。

选择一个颜色后进入该颜色的尺码比较。明细表始终展示全部实际 SKU、标准颜色、标准尺码、内部展示 SKU、批准 Seller SKU 的服务端安全预览及选定周期指标；unsafe 或 truncated 引用显示明确徽标和摘要后缀，普通页面的文本、复制值、DOM、ARIA 和客户端日志都不得包含原始危险字符。只有 `data_manager|admin` 从证据入口打开可逆 code-point 视图。

`/products/:style_id` 的 URL 查询参数恰好使用：`from`、`to`、`metric`、`dimension`、`color_key`、`series`、`return_basis`、`catalog_version`、`fact_basis`。`series` 是逗号分隔、按当前活动显示顺序排列的稳定 key；展示颜色/尺码文字不作为 URL 身份。

默认值与第 13.2 节一致。切换到 `size` 必须先选颜色；切换回 `total|color|sku` 立即清除 `color_key`。语法或枚举非法的 URL 值在请求前用 `replace` 规范为默认值并显示恢复提示；颜色/series 是否属于所选目录只能由服务端判断，首次请求收到稳定 404/422 后再清除失效 key、用 `replace` 写回默认选择并显示一次说明。用户交互使用 `push`，浏览器后退可逐步恢复之前状态。显式 `series=` 按非法参数恢复默认；有可用系列时最少保留 1 条活动系列，尝试取消最后一条必须阻止；没有可用系列时响应和 URL 都不写 `series`。

折线图同时激活最多 8 个系列。没有 URL 选择时，默认选择当前指标区间合计最高的 8 个，按合计倒序、规范化标签和稳定 key 打破并列；全部系列仍保留在可选择图例和明细表中，不合并为“其他”。已有 8 条时选择第 9 条必须阻止、保持原 8 条不变，并提示“最多同时比较 8 个系列”；不得自动淘汰任何已选系列。切换指标、维度、颜色、日期、活动系列、退货口径、目录版本和事实口径都同步 URL。

### 14.4 目录审核交互

目录审核页按 section 分页展示系统候选、用户新增行和全部 `CatalogImportIssue`。款式/SKU 行必须显示服务端返回的 `projection_state`：`included` 使用“将进入目录”，`audit_only` 使用“仅保留审计，不创建身份”；后者仍显示只读来源证据和导致状态变化的最终映射/排除决定，不能从页面或审计中消失。映射目标、排除决定或 SKU 所属款式保存成功后，客户端采用新 revision 重读受影响的 styles、skus、mappings 和 exceptions section，不在浏览器自行推断可达性。用户试图保留没有来源映射的身份时，界面引导其新增 `user_created` 行，而不是把 `audit_only` 系统建议偷偷升格。

每个带 `field` JSON Pointer 的 blocking issue 必须绑定到对应输入：输入设置 `aria-invalid=true`，并用稳定 error element ID 经 `aria-describedby` 关联不含来源原值的 `safe_message`。当前分页响应的页首问题汇总按 blocking/warning 分组，显示本页总数和可聚焦的安全标签；选择一项只聚焦同页对应控件。跨页总数继续使用 `GET /imports/{import_id}` 的 section 计数，用户先进入 section/page，首版不增加一次性拉取全量 issue 的隐藏接口；任何导航都不把危险原值写入 URL、DOM 属性或日志。补齐 nullable 字段并成功保存后，旧 issue 不能乐观清除；只有按新 `workflow_revision` 重读、确认服务端已移除该 issue 才清除关联。完整路径必须支持 `from-export → needs_attention → 补齐或改映/排除 → decisions → 重读 → validate → validated`。

证据历史与 reveal 使用独立 request key：批准 evidence 分页固定包含 endpoint kind、`catalog_version_id/source_ref_id/page/page_size`；批准 reveal 固定包含 endpoint kind、`catalog_version_id/source_ref_id`；草稿 reveal 固定包含 endpoint kind、`import_id/source_ref_id/at_workflow_revision`。三者还包含当前 authz generation；它是客户端单调 counter，每当认证主体、CurrentSiteContext、角色或任一服务端 permissions envelope 变化时递增，不发送给服务端。任一 key、角色或权限 generation 改变时，立即清空可见 evidence rows、可逆转义/base64 缓冲和复制目标并禁用复制，旧响应即使随后成功也不得落 UI。当前请求收到 403 或 404 `catalog_source_ref_not_found` 时只显示绑定当前 key 的安全错误，不回退到当前目录、其他版本或另一个 import，也不以旧缓存填充；角色在加载中降级时遵守相同清理规则。

仍匹配 latest key、sequence 和 authz generation 的草稿 reveal 收到 409 `catalog_workflow_revision_conflict` 时，是第 14.5 节“保留安全本地编辑”通则的敏感数据例外：客户端必须立即移除该 import 的可见 evidence/reveal 值，销毁 `escaped_codepoints`、`utf8_base64url`、解码文本及复制缓冲/目标，并保持复制禁用。客户端只采用错误 `meta` 中的三个最新 counter，使用新 `workflow_revision` 生成全新 request key，重读 import detail 与当前 section rows；不得用旧 key 或旧 ref 自动重试 reveal，也不得在重读后自动恢复旧值。只有重读完成且用户再次明确触发 reveal 时，客户端才以新 revision 请求，由服务端重新验证当前 membership；新请求成功后才重新启用该值的复制。

### 14.5 请求一致性与加载态

产品总表、商品详情和目录审核页都从规范化路由及全部规范查询参数生成不可变 `request_key`；导入分页还包含 `import_id/section/search/page/page_size/at_workflow_revision`，evidence/reveal 使用第 14.4 节更严格的资源与权限 key。每次请求另取单调本地 sequence。取消旧请求只用于节省资源；响应写入 UI 前必须同时匹配当前 latest key、sequence 和 authz generation，旧响应不得更新数据、权限、revision、URL 恢复状态、证据缓冲或错误提示。

URL 或审核分页 key 改变后，旧结果可以留在内存缓存，但必须立即从新筛选标题下的可见指标、图表和表格移除；页面显示保持布局的 loading skeleton，相关容器 `aria-busy=true`，通过 `aria-live` 宣告正在加载。全局筛选控件保持可操作，依赖新响应的 mutation、复制、下载和系列选择暂时禁用。成功只显示当前 key 的响应并清除 busy；失败不得把旧值伪装成新条件结果，显示绑定失败 key 的错误，retry 精确复用该 key。mutation 成功后采用返回的新 revision，并使受影响 section 的缓存失效；409 保留尚未提交的安全本地编辑，重新读取当前 revision/行后再由用户确认合并。

### 14.6 可访问性与响应式

- 图表必须有同一响应数据生成的等价“日期 × 活动系列”每日点矩阵和文字摘要；表格逐格显示数值、零、缺报或分母未定义原因；
- 图例使用可聚焦 checkbox 列表，维度和指标使用语义化 radio/tab；键盘可切换，8 条上限和异步更新通过 `aria-live` 公告；
- 颜色不作为唯一识别方式，系列同时有文字或线型标识；
- 详情页遵循正常文档焦点顺序，不设焦点陷阱；路由离开、参数快速变化时取消旧请求，返回列表时恢复触发链接焦点；
- 在 1440px、768px 和 390px 视口及 200% 缩放下页面本身不得横向溢出；只有标注的表格容器可横向滚动，不把批量字段压成不可核对的卡片；
- 缺报、零值、未归类和加载失败使用不同文案与状态样式。

## 15. 稳定错误码与失败语义

第一版固定提供以下稳定原因码：

| 原因码 | 含义 |
| --- | --- |
| `catalog_workbook_metadata_invalid` | raw-body 上传 header、文件名、扩展名、media type、Content-Length、空 body 或内容类型不符合固定 wire contract |
| `catalog_workbook_unsafe` | 实际 archive bytes 超安全上限，或存在宏、公式、外链、隐藏内容及异常 ZIP |
| `catalog_workbook_capacity_exceeded` | 完整候选超过单一 XLSX 的行、archive、单 member/累计解压或压缩比容量，必须改用 ready export 的在线审核入口；ZIP member 数量或 allowlist 失败不走该兜底 |
| `catalog_export_not_ready` | 候选 export 仍在 building，尚不可下载或创建草稿 |
| `catalog_export_failed` | 候选 export 已失败，响应只返回安全失败原因 |
| `catalog_template_version_unsupported` | 模板版本不支持 |
| `catalog_sheet_contract_mismatch` | 工作表或表头不符合契约 |
| `catalog_export_tampered` | 系统字段或导出证据被修改 |
| `catalog_source_snapshot_stale` | 初次候选后出现未覆盖来源 SKU |
| `catalog_base_version_stale` | 基础目录已变化 |
| `catalog_duplicate_style` | 规范化款号重复 |
| `catalog_duplicate_variant` | 款式＋标准颜色＋标准尺码重复 |
| `seller_sku_normalization_collision` | 多个原值形成同一匹配键 |
| `seller_sku_mapping_conflict` | 一个作用域 Seller SKU 指向多个 SKU |
| `catalog_unresolved_candidate` | 异常项尚未处理 |
| `catalog_invalid_exclusion` | 排除缺少理由或证据 |
| `catalog_admin_required` | 草稿包含仅管理员可批准的变更 |
| `catalog_validation_stale` | 草稿或相关事实变化使验证过期 |
| `catalog_projection_stale` | 批准预览摘要已失效 |
| `catalog_workflow_revision_conflict` | 已有导入命令缺少或不匹配当前单调 workflow revision |
| `catalog_publication_revision_conflict` | 目录指针 counter 缺少、过期或与所选 export 不一致 |
| `catalog_parse_attempt_stale` | 解析 attempt revision 或租约 token 已被后继 attempt 替代 |
| `catalog_state_transition_invalid` | 命令不允许从当前状态执行 |
| `catalog_decisions_invalid` | 在线草稿 mutation 的字段、引用、目标唯一性或组级 payload 不合法；零业务写入 |
| `idempotency_key_reused` | 同一 operation token 被用于不同语义 |
| `catalog_snapshot_range_out_of_bounds` | 历史事实快照不能覆盖请求区间 |
| `catalog_history_forbidden` | 当前角色无权读取历史目录或证据 |
| `catalog_source_ref_not_found` | 已授权 evidence/reveal 请求中的安全引用不属于明确站点、目录版本或 import membership；统一 404 且不披露跨资源存在性 |
| `catalog_style_not_found` | 稳定款式不在所选目录中 |
| `catalog_color_not_found` | 颜色 key 不属于所选款式或目录 |
| `analytics_date_range_invalid` | 分析日期格式、顺序、跨度或未来 `to` 不合法 |
| `analytics_catalog_version_required` | snapshot 口径缺少显式目录版本 |
| `analytics_identity_fact_combination_invalid` | 身份来源、目录版本和事实口径组合不允许 |
| `analytics_dimension_parameter_invalid` | 维度与颜色参数组合不合法 |
| `analytics_series_invalid` | 系列未知、重复或超过八条 |
| `analytics_parameter_invalid` | 其他分析枚举或分页参数不合法 |
| `return_dedup_not_ready` | 当前退货 publication 集合没有 digest 匹配的 ready 去重快照 |
| `outcome_unknown` | 提交结果不确定，必须查询命令状态 |

错误响应不得包含原始买家留言、完整订单号、数据库凭据、内部路径或未经清理的异常堆栈。页面收到冲突后重新读取当前状态，并保留用户尚未提交的安全编辑内容。

## 16. 并发、恢复与版本回退

- 每个站点最多一个当前目录指针；
- 同一导入批次最多一个活动推进命令；
- 已有导入的每个 POST 都按第 10.2 节使用 `expected_workflow_revision`，解析恢复再匹配 `expected_parse_attempt_revision`；
- worker 的 staged 解析行、校验结果或 artifact 在最终 effect/CAS 事务前不得被普通 GET、审批或分析查询视为业务有效；
- 批准按稳定顺序锁定命令、目录同步行、当前指针、草稿、受影响款式/SKU 和映射；
- MySQL 死锁或锁等待超时从完整事务边界以同一命令 token 重试，不能从中段继续；
- 文件落盘与数据库不能组成单事务，沿用现有租约、内容寻址和孤儿文件对账；
- 批准事务失败时旧当前目录继续生效。

旧商品目录版本永久可查询。管理员发起“恢复旧版本”时，系统不是把当前指针直接指回旧行：它为每个需要恢复旧字段值的现有身份创建 revision 号继续递增的新 revision，再以这些新 revision 创建后继目录版本；后来新增且尚未被引用的身份也创建明确停用的新 revision 并纳入后继版本。该后继版本必须完整复用被恢复目标版本唯一的 ready `fact_snapshot_tuple_id`，先以复合外键验证同站点和 ready 状态；不得改用命令时 current tuple，也不得拆分混合 publication、dedup 或配置成员。因此新后继版本的 `catalog_snapshot` 精确重放目标版本事实，而 `fact_basis=current` 仍按请求时当前 publication 读取。任何当前或后继 revision 已被订单、入库或库存事实引用且恢复会改变其可用身份时，恢复命令阻断，只允许创建人工审核的向前纠错版本。当前投影永远只前进到新 revision，不能回指旧 revision 产生 ABA。

日报分析在任何目录版本下都通过不可变来源行和版本成员重放，不修改原日报。

## 17. 隐私与安全

- 候选生成和商品目录不复制退货 order ID、license plate、fulfillment center 或 customer comments；
- `viewer` 不访问目录草稿、原工作簿和内部审计；
- 真实标识证据按当前站点和角色隔离；
- 原始商品目录 XLSX 和最终批准导出沿用 `raw_files` 的不可变、加密备份分类；P0 不提供删除或自动过期，因此只要导入/目录引用存在就永久保留。未来若增加保留期，必须先设计如何保持目录版本重放和审计，不得直接清理共享内容对象；
- 原始 XLSX 下载仅限第 10.6 节角色并记录操作者、import ID、时间和原因；访问日志只记安全对象 ID，不记 Seller SKU、ASIN/FNSKU、标题或单元格内容；
- 所有复合关系都以 `site_id` 外键约束站点一致性，不能只靠应用层过滤；
- API 不接受客户端提供的站点身份；
- 审计记录操作者、时间、命令 UUID、前后 revision、原因和安全摘要，不记录整份文件正文；
- 真实 CSV 只用于本地只读 canary，不把订单号或买家留言提交到测试 fixture、日志或文档。

## 18. 迁移与上线顺序

### 18.1 迁移编号

当前实际已实现线性头仍须在开工时重新读取；按 2026-08-19 已知状态，P0 预留：

- `0022`：商品款式、稳定 SKU、revision、目录版本、单一来源 scope、publication/dedup tuple、Seller SKU 映射、导入审核和命令账本；
- 原生产计划订单迁移顺延为 `0023`，删除重复创建商品身份表的内容；
- 原完工、入库和库存迁移顺延为 `0024`。

Task 1 successor 已把尚未实施的 Agent 计划固定 `0022` 占位归档，并把发布管理计划改为执行时从实际 head 分配下一 revision；两份计划继续暂停。Task 0 已证明 `0020/0021` 不可重写且 P0 的实际下一 revision 为 `0022`；若在本 successor 获批前迁移事实再次变化，仍必须停止并向前修订，禁止改写历史、产生 Alembic 分叉，或让 P0 和 production 分别创建同名 `product_skus` 与不兼容 SKU revision。

### 18.2 兼容切换

1. 先部署新增表和新路径 API，旧 `/product-ledger` 与 `/product-card/{style_code}` 保持原实现；
2. 生成初次候选并完成主档审核；
3. 首个目录版本批准后，在固定事实快照上对账旧款号总计与新 mapped＋unmatched＋excluded 桶；
4. 对账款式、颜色、尺码、全局未归类、排除和来源总计，并通过第 20.5 节性能门；
5. 原子把前端读取源从 `legacy_parser` 切到 `p0_catalog`；单个请求只读一种身份源，不做行级 fallback；
6. 验证通过后移除旧的“多个变体名称”作为主名称的 UI 契约，但旧 API 继续兼容至单独退役；
7. 更新用户指南和 OpenAPI 客户端。

首个目录尚未批准时，系统显示“商品主档尚未初始化”，旧日报查询仍可工作，但不能把临时 Seller SKU 解析称为正式身份。

### 18.3 硬开工门

以下文档和运维契约在 P0 任何编码任务前必须正式修订并各自标注替代关系；未完成时，《成品生产订单与完工入库实施计划》以及本 P0 都不得开始编码：

| 现有来源 | 必须修订的冲突 |
| --- | --- |
| `2026-08-06-daily-data-review-platform-design.md` | 增加首次 scope 确认门、历史 dataset 不可变 scope assignment sidecar，以及退货 publication 与 dedup pointer 的同事务 CAS；当前查询必须验证 publication-set digest 匹配 ready dedup snapshot |
| `2026-08-06-daily-data-review-platform-implementation.md` | 把 sidecar 回填/新建、publication staging/CAS、失败恢复、权限、最小 grant、备份恢复和并发测试写入真实日报发布流程，不能只在 P0 查询层旁路补表 |
| `2026-08-14-ledger-home-and-workflow-optimization-design.md` 及实施计划 | “不建人工主档”、`style_code` 作为正式身份、旧 API/名称状态；旧端点只保留兼容语义 |
| `2026-08-18-finished-goods-production-receipt-design.md` | SKU 身份所有权、revision 关联、生产内直接建 SKU、共享目录入口、权限和迁移号 |
| `2026-08-18-finished-goods-production-receipt-implementation.md` | 删除重复 SKU 建模任务；生产迁移顺延为 `0023/0024`；所有脚本、测试、grant、备份和里程碑 head 改写 |
| `2026-08-18-end-to-end-sku-supply-chain-roadmap.md` | 在生产里程碑前插入 P0，并更新 A/B 迁移与身份依赖 |
| `2026-08-12-read-only-agent-analysis-implementation.md` 与发布管理后继计划 | 解除 `0022` 占用并按真实实施顺序重排，或明确归档不执行 |
| 迁移 contract、管理员 CLI、测试库准备脚本、最小权限 manifest、备份 writer/restore canary | 从实际新 head 推导允许版本和 source-of-truth 表，不能只改文档数字 |

本规格只声明替代关系，不在本次文档提交中悄悄改写上述已批准文件。下一步实施计划的第一个门必须完成这些修订并再次验证实际 HEAD；在门通过前，旧生产计划视为“批准但暂停、不可执行”。

### 18.4 当前工作区保护

当前商品看板、导入审核、批量审核和生产文档存在大量未提交或未跟踪改动。P0 开工前必须：

- 记录 `git status`、当前 HEAD 和相关文件清单；
- 创建私有、不可误提交的基线快照和 checksum manifest；
- 明确 P0 允许修改的文件；
- 只提交本阶段文件；
- 完成后重新核对用户原有改动未丢失。

不得用 `git reset --hard`、覆盖式 checkout 或清理未跟踪文件建立“干净环境”。

## 19. 与生产计划和 E0 的边界

### 19.1 生产订单计划

原《成品生产订单与完工入库实施计划》需要在 P0 后重新编排：

- 删除创建 `product_skus/product_sku_revisions` 和独立 SKU CRUD 的重复任务；
- 生产订单直接引用 P0 的 `sku_id`、具体 `sku_revision_id` 和具体 `style_revision_id`；
- `/production/skus` 页面改为链接或复用共享 `/catalog`；
- 运营订单 Excel、工厂完工 Excel 和 `internal_legacy` 仍由生产阶段的通用 `sku_aliases` 管理；
- 生产上传遇到未知 SKU 时，进入共享商品目录草稿或待处理队列，不能在订单事务里旁路创建第二套身份；
- 订单确认时继续固化 SKU revision、款式 revision、展示属性和工厂编码快照；
- 完工和库存事实继续引用确认时的 SKU 与款式 revision，不读取当前目录覆盖历史。

### 19.2 E0

P0 的 Seller SKU 映射只满足当前单账号美国站的商品分析，并且按目录版本精确匹配。它不宣称完成 E0。

E0 后续仍需增加：

- 正式 Seller Account 和 Marketplace 实体；
- Seller SKU、FNSKU、Child ASIN 的不可变 mapping snapshots；
- Parent/Child ASIN 类型区分；
- resolution evidence、entries 和全部 candidates；
- Shipment、FBA 和发布行对具体 snapshot 的引用；
- 可暂停、恢复和重试的历史回填；
- 多账号、多站点冲突与权限。

E0 必须复用 P0 的 `style_id`、`sku_id` 和 revision，不再创建新的商品身份。P0 已批准 Seller SKU 映射作为候选输入，经 E0 完整 scope 和证据审核后形成首个 mapping snapshot。

E0 切换使用两个站点级字段：`identity_source_kind=p0_catalog|e0_snapshot` 与 nullable `active_e0_snapshot_id`。P0 状态固定为 `p0_catalog + null`；E0 状态固定为 `e0_snapshot + 非空 ready snapshot`。来源 kind 只允许单向改变，活动 E0 pointer 可在 E0 内继续向后继 snapshot 前进。

身份来源与事实口径矩阵固定为：

| fact basis | 当前 source kind | 身份解释 |
| --- | --- | --- |
| `current` | `p0_catalog` | 当前 P0 目录映射＋当前目录 revision |
| `current` | `e0_snapshot` | `active_e0_snapshot_id` 映射＋当前目录 revision；历史 catalog 参数非法 |
| `catalog_snapshot` | 任意 | 显式 P0 目录自己的 mapping/publication/dedup/config tuple；始终返回 `identity_source=p0_catalog`，不受当前 E0 开关影响 |

P0 不定义“E0 历史事实快照”查询；将来由 E0 规格新增独立 fact basis 或 endpoint，不能复用 `catalog_snapshot` 改变既有语义。切换步骤为：

1. 在仍使用 `p0_catalog` 时生成 E0 snapshot，不影响当前查询；
2. 用固定脱敏 fixture 和最近 365 天冻结事实，对账每个 Seller SKU 决定、mapped/unmatched/excluded 桶、款式/SKU 归属和五项指标；差异必须为零或有逐项批准说明；
3. 验证所有当前 P0 映射在 E0 中有唯一 successor、每个 E0 目标 `sku_id` 都是当前目录成员、E0 coverage 不低于 P0，且查询性能通过同一预算；
4. `admin` 以幂等命令在同一事务把 `identity_source_kind` 从 `p0_catalog` 改为 `e0_snapshot` 并设置已验证 snapshot ID；kind 命令只允许这个方向；
5. 切换后所有 `fact_basis=current` 查询只读 active E0 snapshot，不再同时连接 P0 映射，也不做缺失行 fallback；P0 目录仍提供当前 revision、生产身份和 `catalog_snapshot` 历史审计；
6. E0 错误通过管理员 CAS 命令把 `active_e0_snapshot_id` 从当前值推进到已验证、generation 更大且目标均属于当前目录的后继 snapshot；失败时旧 pointer 不变，不把 kind 切回 P0。

任何响应必须在 provenance 中声明唯一 identity source 和 snapshot/catalog ID；对账工具可以并行计算两套结果，但不能向正式业务查询返回混合结果。

## 20. 测试策略

### 20.1 单元测试

- Seller SKU、款号、颜色、尺码和内部展示 SKU 规范化；`catalog_identity_key_v1` 用 `Straße→strasse`、`I→i`、`İ→i＋U+0307`、dotless `ı` 保持、全角兼容字符和 White_Space 边界做 UCD 15.1.0 known-answer，宿主 Unicode 升级不改变结果；
- 严格三段候选解析和所有异常分支；
- 标准名称不从标题自动推断；`from-export` 初始候选能把 nullable `standard_name/internal_display_sku/standard_color/standard_size` 序列化为 JSON null，当前 `included` 或未决定组的推荐候选对每个缺值形成字段级 blocking issue；create/update mutation 可保存 null 草稿，补齐 `included` 行或把来源最终改映/排除使候选变为 `audit_only` 后才能进入 validated；
- 空目录初始化和已有目录的后继候选都覆盖 `row_origin=system + system_style_id/system_sku_id=null`；既有批准成员的 system ID 非空，新增/已有动作只按 ID 空值判断，不能按 row origin 判断；
- 批准投影可达性覆盖“推荐候选未决定→临时 `included`”“创建/映射到新候选→最终 `included`”“改映既有 SKU 或明确排除→`audit_only`”，并验证 `audit_only` 缺字段不阻断、`included` 缺字段稳定阻断；
- 带 NUL、换行、bidi/控制字符和仅不可显示字符的 Seller SKU/标题可生成稳定安全预览＋摘要；U+007F、U+0080、U+009F、U+FFFE 和 U+FFFF 均有边界 fixture，原值不进入 XML/普通 API/日志，系统行 ID 仍可完成决定；
- `SafeSourceRef`、ASCII code-point 转义和 UTF-8 base64url 可逆；XML 1.0 禁止的 noncharacter、NUL、换行、bidi 与仅不可见值都不会出现在普通 API 原始字符串字段；
- 工作簿六表、逐列类型/长度/必填/枚举、四动作矩阵、连续数据区、系统 ID 文本往返和防篡改；
- OOXML part/ContentType/Transitional relationship allowlist 与基数、sharedStrings/theme 四种存在组合的 part⇔relationship 双向约束、空/非空 defined names、恶意 ZIP、宏、公式、外链、连接、嵌入包、隐藏行列/表、合并单元格、每表固定最后一列后的值和错误 MIME；30,000/75,000 行、64/200 MiB、`200:1` 压缩比各自的等于上限成功与超过一单位失败边界；archive 实际字节上限分别覆盖 `APP_STORAGE_MAX_UPLOAD_BYTES < 100 MiB` 和 `>= 100 MiB` 两个配置分支，每支都验证精确上限成功、上限＋1 byte 失败；独立 ZIP validator 验证 128 member 通过数量门、129 member 失败，129 member＋unknown part 必须先记录 `zip_member_count_exceeded`，OOXML 集成层仍拒绝含 unknown part 的 128-member fixture；
- raw-body 上传 OpenAPI 只接受两个 XLSX media type，required `Idempotency-Key/X-Original-Filename`、条件 CSRF、文件名严格解码、空 body、multipart 拒绝、Content-Length 与实际流式上限都有契约测试；同 token＋同 bytes/文件名/media type 返回首次 201，任一摘要成员变化稳定冲突且不重复登记 raw file/import；
- 以最大合法长度行验证 row limit 内仍可能触发 byte capacity，生成器返回非空 capacity violation 且无 artifact；所有可下载 artifact 原样走 uploader 必须成功；
- 候选去重、按 Seller SKU 原值＋report type 的证据汇总和 publication snapshot 摘要；同一键增加任意标题/ASIN/FNSKU tuple 只改变计数/digest，不增加 XLSX 摘要行；`source_evidence_jcs_v1` 与 `publication_refs_jcs_v1` 都有 RFC 8785 known-answer，升级后不重算旧摘要；
- 风险分类、权限和稳定错误码；
- 订购件数、销售额、退货件数、会话和转化率公式；
- 事件日、报告日和夏令时转换；
- 缺报、零值、未归类、排除、duplicate 和 unresolved 状态；
- 每个状态机命令的允许来源、目标、角色、幂等重放和非法转移。

### 20.2 MySQL 集成测试

- `style_id`、`sku_id`、revision 和目录版本复合外键；
- 当前投影始终等于当前目录成员 revision；
- 款号和款色码唯一性；
- Seller Account＋Marketplace＋Seller SKU 唯一映射；
- 同一 UUID 幂等、不同摘要冲突；
- 两个并发批准最多一个成功；
- 过期基础版本、过期验证和过期预览零部分写入；
- `REPEATABLE READ` 中途切换日报/目录/时区指针仍只产生一个一致响应；
- `current` 与 `catalog_snapshot` 使用各自精确 publication、dedup 和配置成员，禁止混读；
- return duplicate 四状态、无环 canonical 约束和历史 snapshot 重放；
- 退货 publication 与 dedup digest/pointer 同事务推进；并发发布、失败回滚和人工后继决定不会暴露不匹配 tuple；
- 普通变更与高风险管理员门禁；
- 最终导出中 mapped/excluded 组级决定可往返；碰撞组理由不一致稳定阻断，已批准键 mapped↔excluded 只允许管理员；
- 系统新候选映射到既有 SKU、全部来源明确排除时，批准前后 `style_id/sku_id/revision/reservation/catalog member` 数量均不增长，候选证据和 `audit_only` 摘要仍可追溯；最终映射到新候选时只创建一次可达身份，同 token 重放不重复；
- 完整候选超过工作簿任一行或字节容量门时 export 保持 ready、记录具体 violation、无部分 artifact、文件下载稳定 409；`from-export` 在线草稿覆盖全部行并可完成同一批准流程；
- export `building|ready|failed` nullable 矩阵和四种文件下载结果；`from-export` 的 export/current revision 三方 CAS、owner 权限、200 行分页、500 mutation 原子批次和 stale 零写入；
- `from-export` 对 building/failed/revision stale 使用三个不同稳定错误；ready＋capacity exceeded 可创建草稿；五种 row 联合、同批次 create key 引用、重复 target/环拒绝、字段级 422 零写入和成功 revision＋1 通过 OpenAPI/数据库契约测试；
- 字段 issue JSON Pointer 的 known-answer 与 OpenAPI 契约覆盖五种 row、全部 mutation type、允许值和必须为 null 的条件；明确 XLSX/row 映射核对字段使用 `/target_internal_display_sku`，而 `map_seller_sku` mutation 使用 `/target_internal_display_sku_check`，两者不得混用；拒绝带 section/rows/mutations/数组下标的路径，并验证分页、行排序及 mutation 数组重排都不改变同一 issue 的相对 pointer，修正核对值后按新 revision 重读会清除旧 issue；
- 当前与历史批准 evidence 分页、草稿 scoped reveal、SafeSourceRef 资源绑定和角色降级；表驱动固定草稿 reveal 的“鉴权→revision→membership”优先级：viewer 对 stale/current revision 与 member/任意错误 ref 的组合都返回 403 且不含 counter；有草稿读取权的 `data_manager|admin` 对 stale revision 与 member、错误 kind、跨站点、非成员、跨 import ref 的组合都在 source-ref repository 调用前返回相同 409，并只含安全 counter；只有 current revision 才对这些错误 ref 统一返回 404 `catalog_source_ref_not_found`，current＋member 返回 200。GET 只增加安全访问审计，不改变业务 revision/counter；
- XLSX 与 online 批次 owner 规则一致；capacity-exceeded rebase 原子生成 online `needs_attention|validated` 后继、继承 owner、没有 raw file/parsing attempt，并重新完整验证；
- restore 后继完整复用目标版本 ready fact tuple；current 查询仍读 current facts，catalog_snapshot 精确重放目标 tuple，禁止拆分混搭；
- 目录批准失败时旧指针不变；
- 备份恢复后版本、成员、revision、映射、指针和审计一致。

### 20.3 分析守恒与契约测试

- 每天和整段范围的 SKU→尺码→颜色→款式守恒；
- 新旧 Seller SKU 映射到同一 `sku_id` 后历史连续；
- 改绑只影响明确选择的新目录版本，旧版本可重放；
- 转化率按汇总分子分母重算；
- v1 经确认发布的负经营值原样聚合，conversion 可小于 0 或大于 1，分母小于等于 0 才返回 undefined；
- 经营/退货 `published|missing` × 身份 `complete|partial|not_applicable` 的正交表，未来 `to` 稳定拒绝且不生成趋势点；
- 缺失整份报表不生成伪零，已发布无 SKU 行生成真零；
- event date/report date、一份报告跨两个事件日、UTC 跨日、美国夏令时边界、报告日缺失但事件日仍有历史来源行；event-date 区间 `observed_days=0` 但有区间外 report-date publication 贡献时仍返回 observed 非空值，没有事件事实则返回 indeterminate 零；
- 区间 partial 合计、observed/expected days、`no_observed_reports` 与 `undefined_denominator` 分开；
- source/mapped/unmatched/excluded/duplicate/unresolved 六桶逐指标守恒；business/report-date returns 在零观察日为 all-null＋not_evaluable，event-date returns 在零观察日仍为数值＋evaluable＋indeterminate，并逐格验证；
- 六桶只由产品总表站点 envelope 返回；商品卡不扫其他款式，验证整款 summary=variants；`total|color|sku` 再验证全部系列等于整款，`size` 验证全部尺码系列等于所选颜色小计；
- 经营独有和退货独有 SKU 都进入候选；
- 旧 `style_code` API 与新 `style_id` API 同时存在且路径参数不串义；
- `current`/`catalog_snapshot` × P0/E0 source 矩阵逐格验证，非法历史目录＋current 稳定拒绝；
- OpenAPI 生成物稳定、五种 TrendPoint 均 required 返回 numerator/denominator（非 conversion 为 null）、全部参数组合和 reason code 通过契约测试。
- 商品目录上传在 OpenAPI 中是 raw `string/binary` 而非 multipart 或 JSON；header `Idempotency-Key` 与内部 `operation_token` 逐次一致，前端生成类型不能要求把 token 塞入二进制 body；
- GET/preview 返回的 required counter 可直接组成下一次合法 POST；旧 counter 稳定 409，成功响应返回新 counter，`parse_failed → resume → parse_failed` 的旧 attempt 不能 ABA；

### 20.4 前端与端到端测试

- 产品总表显示标准名称和来源标题徽标；
- 商品主档生成、上传、异常处理、差异、批准和版本历史；
- `from-export` nullable issue 逐字段显示安全原因、`aria-invalid/aria-describedby` 和可聚焦问题汇总；row issue 只按 enclosing row 相对 pointer 绑定，decision error 先按 `mutation_id` 定位 mutation 再按相对 pointer 绑定，分页、排序和 mutation 重排均不改变焦点目标；null field 留在问题汇总且不伪造控件关联。补齐后保存、按新 revision 重读并清除 issue，再 validate 到 validated，改映/排除则显示候选变为“仅保留审计”；
- `data_manager` 自行批准普通草稿；
- 高风险草稿对 `data_manager` 阻断、对 `admin` 原因必填；
- 默认颜色趋势、选择颜色后的尺码趋势和全部 SKU 明细；
- 五种指标、两种退货日期口径和 URL 恢复；
- 经营完整但退货缺报/未决重复时，只有 returns 的 `MetricValue.is_partial` 为真；provenance 始终声明唯一 identity source；
- URL 直达、刷新、前进/后退、非法参数规范化、颜色改名、目录切换和非 ASCII 展示值；
- 快速切换日期/颜色/尺码及人工乱序完成请求时只有 latest request key＋sequence 可落 UI；新 URL 下不显示旧指标，初载/刷新/error/retry 的 `aria-busy` 和禁用动作正确；
- 省略 series 使用默认、`series=` 恢复默认、不可取消最后一条，以及服务端判定语义失效 key 后 replace；
- 图表最多八条活动线；选第九条被阻止且原选择不变，所有系列仍可选择；
- viewer 对草稿、原文件、证据历史、版本、diff、审计拒绝，对批准 Seller SKU/ASIN/FNSKU 允许；
- viewer 商品卡含 NUL、换行、bidi、XML noncharacter 和全不可见 Seller SKU 时只见安全 preview/digest，DOM、ARIA、复制值和前后端日志无原字符；`data_manager|admin` 的 evidence code-point/base64 端点可逆且逐次审计；
- evidence/reveal 快速切换目录版本、import 和 ref 的乱序响应只能由 latest resource key＋authz generation 落 UI；stale ref 404 或加载中角色降级 403 立即清空旧证据/可逆缓冲并禁用复制，不 fallback 到其他资源；另覆盖同角色、同 import/ref 被协作者推进 revision 并移除或改映 membership：旧 revision reveal 的当前 409 立即销毁可见 reveal、base64/解码/复制缓冲并禁用复制，采用安全 meta counter 重读 import/rows、以新 revision 生成 request key，且必须由用户再次触发并通过服务端 membership 验证，绝不自动恢复旧值；
- 超容量 online 草稿在同一 mutation 批次创建款式、创建 SKU、解决异常并完成 validate/submit/approve；删除被引用或系统生成行稳定 422 且零写入；
- `data_manager` 成功 preview 后被降级为 viewer 时，原 POST token 重放和命令结果 GET 都为 403 且不重新执行 effect；管理员代查仍要求新 token 和原因；
- 键盘、每日等价矩阵、读屏公告、焦点恢复，以及 1440/768/390px 与 200% 缩放无页面横向溢出；
- 网络重试、`outcome_unknown` 恢复和冲突后保留编辑内容。

### 20.5 固定性能门

提交可重复生成的脱敏 fixture `analytics_scale_v1`，固定 seed `20260819`：1,700 款、11,200 个有事实的 Seller SKU 原值/匹配键、365 个报告日、4,088,000 条经营 active 行、408,800 条退货 active 行（每日 1,120 条），并包含其中 560 个指向既有 SKU 的别名键、224 个未归类键、112 个明确排除键、8,176 个疑似重复组成员（duplicate/canonical 与 unresolved 各 4,088）、12 个缺报日和一个恰好 16 条可选颜色/尺码系列的款式。每个 Seller SKU/report type 在历史中轮换恰好三个合成标题/标识 tuple，但第 7.5 节摘要仍使标准工作簿的来源证据行数精确为 22,400；生成、Excel 往返后的再上传和审核页解析必须同时通过第 9.1 节全部行数、archive、member、累计解压和压缩比门。fixture 不含真实订单号、标题或用户标识。

参考 profile 固定为 MySQL 8.0 与 8.4 各一轮、4 vCPU、8 GiB RAM、2 GiB InnoDB buffer pool、loopback API、release build；先预热 3 次，再执行 20 次并取 p95。预算为：

| 场景 | p95 服务端响应预算 |
| --- | --- |
| 31 天产品总表，第 1 页 50 款，默认排序，含总数/coverage/reconciliation | ≤ 1,500 ms |
| 单款 31 天、8 条颜色或尺码趋势 | ≤ 750 ms |
| 单款 365 天、8 条趋势 | ≤ 1,500 ms |
| 连续 365 次退货 publication 的事务外 dedup staging | 每次 p95 ≤ 30 s |
| 退货 publication＋dedup pointer 最终 CAS 锁事务 | p95 ≤ 500 ms |

`EXPLAIN ANALYZE` 必须保存为测试 artifact。事实表不得出现无日期/publication 边界的 `ALL` 扫描；单款趋势必须从该款目录映射键集合进入，不能扫描同站点其他款全部事实；产品总表扫描范围不得越过所选 publication 成员和日期区间。Python 层最多接收“页行＋日期×活动系列＋coverage/reconciliation”聚合行，不得接收原始日报行再聚合。

365 次发布后 dedup delta depth 必须 ≤32，物理 candidate-group membership 行总数必须 ≤150,000，不能出现 408,800×365 的全量复制；备份恢复后每个 snapshot 的 base/checkpoint/delta、digest 和逻辑四状态相同。任一 MySQL 版本超预算、查询计划越界、容量门超限或连接池耗尽都阻止发布，不能用提高 API timeout 通过。

### 20.6 真实数据 canary

自动测试使用脱敏合成 fixture。两份用户提供的真实 CSV 只在本地执行只读 canary，验证：

- 当前解析器完整识别；
- 24 条经营行和 10 条退货行进入候选证据；
- 单日报内多个原始标题不会覆盖标准款名；
- 报告日和退货事件日保持分离；
- CSV 中带逗号的标题和留言由标准 CSV 解析器正确处理；
- canary 输出不打印完整订单号、买家留言或物流牌照号。

另以当前数据库只读快照固定执行全量基线查询，必须重现：34 个可解析候选款号、224 个不同 Seller SKU 原值、其中 222 个符合严格三段规则、2 个异常；125 经营独有＋7 退货独有＋92 两边共有＝224。查询文本、规范化规则版本、`consistent_as_of` 和只含计数的摘要随 canary 证据保存，不提交真实行值。

## 21. 端到端验收场景

使用固定脱敏验收集：同款有 3 个颜色和 9 个尺码候选，理论笛卡尔积为 27，实际只存在 10 个 SKU（故意缺少 17 个组合）；其中 1 个 SKU 有新旧两个 Seller SKU，另含 1 个待修正异常、1 个待明确排除异常、1 个 unresolved duplicate、1 个缺失经营报告日和 9 个可选趋势系列。完成以下验收：

1. 从全部当前发布日报生成初始 XLSX；
2. 人工填写一个标准款名，原始标题仍完整可查；
3. 将旧、新 Seller SKU 映射到同一具体 `sku_id`；
4. 一个异常 SKU 被人工修正，另一个填写理由明确排除；
5. 未处理异常阻止批准；
6. `needs_attention → validate → validated → submit → ready_for_approval → preview → approve` 完整推进，`data_manager` 完成普通初次批准并生成目录版本 1；
7. 产品总表从“多个变体名称”切换为标准名称；
8. 默认颜色趋势和选择颜色后的尺码趋势数值正确；
9. 款式、颜色、尺码和 SKU 指标守恒；
10. 缺少经营日报的日期显示缺口，已发布但无该 SKU 的日期显示零；
11. 退货在事件日和报告日视图分别落到正确日期，事件日不从报告缺失推断缺口；unresolved duplicate 不进入正式 KPI 并标记 partial；
12. 新日报出现未知 Seller SKU 后进入未归类队列，当前目录不被修改；
13. 新目录版本完成首次绑定后当前分析重新归类，版本 1 仍可重放；
14. `data_manager` 尝试改绑既有 Seller SKU 被拒绝；`admin` 填写原因后创建后继版本；
15. 后继版本被生产事实引用后，直接恢复不兼容旧版本被阻断，只能向前纠错；
16. 同一批准命令重复提交只产生一个版本；
17. 加密备份恢复后目录、revision、映射、当前指针和趋势结果一致。
18. `fact_basis=current` 与 `catalog_snapshot` 在新日报发布后得到预期不同结果，旧 snapshot 仍逐成员精确重放；
19. 新旧商品 API 同时存在，数字款号不会路由成 `style_id`；
20. 已选 8 个系列时第 9 个被阻止，URL、刷新和后退保持原选择；
21. viewer 能看当前批准标识和趋势，但对草稿、原文件、历史版本、diff、证据历史和审计均收到稳定 403；
22. export 后仅新增已知 Seller SKU 证据时显示 drift 但批准仍冻结原 snapshot；新增未知匹配键时必须 rebase；
23. reject、withdraw、admin 代撤回和 rebase 均按状态表、角色及幂等规则执行；
24. 新 Seller SKU 的系统候选改映到既有 SKU 后，候选显示 `audit_only`，批准不创建新款式、SKU、revision 或 reservation；
25. 一个候选的全部来源被明确排除后同样零身份增长，但来源证据和排除审计仍可查询；
26. 另一个最终映射到新候选的路径只创建一个稳定身份，幂等重放后计数不变；
27. nullable 字段从安全 issue 定位、补齐保存到 validated 的键盘与读屏路径通过，stale evidence 404 和加载中角色降级不显示旧可逆值。

## 22. 风险与缓解

| 风险 | 缓解 |
| --- | --- |
| Seller SKU 三段格式被误当正式身份 | 只生成候选，正式身份必须经过目录批准 |
| 标题差异继续污染标准名称 | 标准名称只来自款式主档，标题只作证据 |
| 新日报让工作簿证据漂移 | 冻结导出快照；已知键显示 evidence drift，新键/scope/碰撞必须变基，批准不混读 |
| Seller SKU 改绑重写历史解释 | 目录版本不可变，旧版本可重放；改绑仅限管理员 |
| 未采用的系统候选创建孤立身份 | 批准投影按最终映射可达性重算；`audit_only` 候选不建 ID、revision、member 或 reservation |
| 动态版本连接影响性能 | MySQL 服务端聚合、明确索引、真实和放大数据查询计划验收 |
| 缺报被误读为零销量 | 每日返回报表覆盖，缺报指标为 `null` |
| 退货报告日和事件日混用 | 两种口径独立参数、独立标签和时区声明 |
| P0 与生产计划重复建 SKU | P0 优先占用开工时实际下一线性迁移（当前预留 `0022`）；生产计划删除身份建模任务并整体顺延 |
| P0 被误称为完整 E0 | 明确只映射 Seller SKU；FNSKU/ASIN snapshot 和逐行证据仍属 E0 |
| 当前脏工作区被覆盖 | 开工前私有基线快照、文件清单和增量提交 |

## 23. 完成定义

P0 只有同时满足以下条件才算完成：

1. 商品目录 schema、迁移、API、前端和文档全部上线；
2. 当前真实 canary 与固定 scale fixture 的初始 XLSX 可从同一 `REPEATABLE READ` 快照中的全部当前发布历史摘要生成并按逐列/OOXML 安全契约往返；超容量 fixture 则稳定不生成部分文件，并可由同一 ready export 的在线草稿处理全部候选；
3. 固定 canary 重现 34 个可解析候选款号、224 个 Seller SKU 原值、222 个严格可解析值和 2 个异常值，且三类集合 125＋7＋92＝224；
4. 首次批准的 publication snapshot 中 100% 合格 Seller SKU 匹配键都有唯一决定：映射或明确排除；unmatched、未解决碰撞组和未决定数均为 0，`audit_only` 系统候选产生的正式身份、revision、目录成员和 reservation 均为 0；
5. 当前目录拥有唯一标准款名和稳定款色码身份；
6. 产品总表不再把“多个变体名称”作为商品名称；
7. 颜色和尺码趋势、五项指标、两种退货日期、partial/null、coverage 和六桶对账全部通过验收；
8. `current`/`catalog_snapshot` 精确重放、退货 dedup、普通/高风险权限、版本、幂等和并发测试通过；
9. 新旧 API 无歧义并存，OpenAPI drift、URL、8 系列上限和三档响应式验收通过；
10. 第 20.5 节两个 MySQL 版本的查询计划、三项分析查询 p95 和两项退货去重 p95 性能预算全部通过；
11. 加密备份恢复 canary 通过；
12. 第 18.3 节旧规格、计划、路线图、迁移引用、权限和备份脚本已正式修订，旧生产计划解除冲突前保持不可执行；
13. 用户书面复核本规格后，另行批准详细实施计划；
14. 开始 P0 编码前及开始生产订单编码前分别重新冻结工作区基线。

## 24. 批准记录

用户于 2026-08-19 逐项批准以下设计结论：

- 正式款式主档和稳定变体身份；
- 标准 XLSX 初始化；
- 全历史当前发布版候选范围；
- 异常阻断、来源值与标准值并存；
- Seller SKU 别名连续性；
- 单一 Seller Account、美国站当前范围；
- 不可变目录修订；
- 退货事件日默认口径；
- 五项趋势指标；
- 颜色后尺码的分层交互；
- 分层 P0 总体方案；
- `data_manager` 可自行批准普通变更；
- 身份、XLSX、审核权限、产品总表、变体趋势、错误处理、迁移顺序和验收的总体边界。

原始批准基线固定为 Git commit `1ead0fd952d0aba45ad2bc39fc744c1967f8d587`、SHA-256 `cab5b39b6e2cc04749a6ae7b467bc797dd7cd1d65ce47ef2ebdd028fd70019f7`。下列第 25 节是 Task 1 新增的 successor candidate；它必须取得新的 SHA-256 和用户再次书面批准，批准前不得开始 Task 2 或任何 P0 业务编码、迁移、数据库写入、合并或推送。

## 25. Task 1 successor candidate（待再次书面批准）

本节补齐原批准基线中跨文档仍不够精确的退货指纹、publication staging、scope/dedup API、原文件下载、worker 恢复和切换边界。若本节与前文发生歧义，以本节为 successor candidate；在再次批准前，本节仅供契约测试和文档同步，不授权业务实现。

### 25.1 `return_event_fingerprint_v1`

输入必须是 `return_report_v1` 已完成严格解析后的 13 个 typed 字段，键名和顺序固定为 `return_date/order_id/sku/asin/fnsku/product_name/quantity/fulfillment_center_id/detailed_disposition/reason/status/license_plate_number/customer_comments`。`return_date` 必须编码为 UTC、六位微秒、尾随 `Z` 的 `YYYY-MM-DDTHH:MM:SS.ffffffZ`；`quantity` 是 JSON integer；其余 11 项是解析后原样 Unicode string，不额外 trim、case-fold 或替换。用这些固定键组成 JSON object，按本规格冻结的 JCS 子集编码为 UTF-8，再计算 SHA-256；持久值为 32-byte digest，算法版本另存 `return_event_fingerprint_v1`。任何字段变化都产生不同 fingerprint，规则升级只能创建新版本，禁止重算旧 snapshot。

只有同一 `report_source_scope_id`、不同 current return publication member 出现相同 fingerprint 时才形成跨报告 candidate group；同一 publication 内重复仍由既有 `return_report_v1` 审核契约处理，不进入跨报告组。组内初始 canonical 按 `report_date/dataset_id/published_version_id/active_row_id` 的固定类型 tuple 做二进制升序选择；新增组或成员集合变化一律为 `unresolved`，稳定组才可复用旧 group revision。订单号、物流牌照号和买家留言只参与 JCS/digest 与授权摘要，不得进入普通日志、trace、XLSX、普通 JSON、DOM、ARIA、URL或测试失败文本。

### 25.2 scope、dedup、原文件与命令 API

以下资源是唯一 wire contract，全部 JSON schema `additionalProperties=false`，所有写请求要求 Cookie session、CSRF、服务器派生 `CurrentSiteContext`、UUID v4 `operation_token` 和 header `Idempotency-Key` 与 body token 完全相同：

- `GET /api/catalog/source-scope/status`：`viewer|data_manager|admin` 可读；required 返回 `status=unconfirmed|confirmed`、nullable `report_source_scope_id/seller_account_display_name`、固定 `marketplace_scope_code=amazon_us`、非负 `site_config_revision` 和 server-computed `permissions`。客户端不得提交 `site_id`；
- `POST /api/catalog/source-scope/confirm`：仅 `admin`；body 恰含 `operation_token/expected_site_config_revision/seller_account_scope_key/seller_account_display_name/marketplace_scope_code/reason`。同 token 同语义恢复首次结果，不同语义为 409 `idempotency_key_reused`；已确认同语义返回原结果，不同语义为 409 `catalog_scope_already_confirmed`；
- `GET /api/catalog/return-dedup/groups`：仅 `data_manager|admin`，按当前 ready snapshot、`status=unresolved|resolved|all`、`page/page_size` 分页，只返回 SafeSourceRef、成员计数、group revision、current decision 和安全摘要；
- `POST /api/catalog/return-dedup/groups/{group_id}/decision`：仅 `data_manager|admin`；body 键恰为 `operation_token/expected_dedup_publication_revision/expected_group_revision/decision/canonical_member_id/reason`，其中 `decision` 闭集为 `confirmed_distinct|duplicate_of`。`confirmed_distinct` 要求 `canonical_member_id=null`；`duplicate_of` 要求它是当前 group revision 中非空且有效的 member ID，并把其余成员判为该 canonical 的 duplicate。非法组合为 422 `return_dedup_decision_invalid`；counter、group revision 或成员集合变化为稳定 409 且零 pointer 变化；
- `GET /api/catalog/imports/{import_id}/original-file`：仅能读取该站点该 import 的 `data_manager|admin`；`source_kind=online` 固定 404 `catalog_original_file_not_available`。XLSX 返回不可变原始 bytes、固定安全下载名、`Content-Type`、`ETag`、`Cache-Control: private, no-store`，写安全审计且不从用户文件名生成响应 header；
- `GET /api/catalog/commands/{operation_token}` 只允许原操作者恢复首次安全结果；管理员代查继续使用带新 token/原因的 `POST .../admin-inspect`，GET 无业务副作用。

固定判定顺序为 authentication → server site context → role/permission → resource membership → expected revision/counter → command semantic hash → domain state。跨站或无权资源使用规格既有的统一 403/404，不允许通过 counter、错误细节或时序泄露存在性。安全错误 `meta` 只允许当前 counter、状态、SafeSourceRef 和 issue pointer 白名单，未知验证正文、SQL/异常文本或 raw source 必须丢弃。

### 25.3 publication dedup staging 与 worker 恢复

退货 publish、rollback、published move 和 undo 在改变 current publication 前必须使用同一 staging handshake：

1. `POST /api/publications/return-dedup-staging` 仅 `data_manager|admin`，body 恰含 `operation_token/dataset_id/proposed_version_id/expected_publication_revision/expected_dedup_publication_revision`；返回 202 `job_id/status=building/command_url/status_url`，同语义重放返回同一 job；
2. `GET /api/publications/return-dedup-staging/{job_id}` 返回 `building|ready|failed|superseded`、非负 `job_revision`、固定 proposed-set digest、nullable safe `failure_reason/retry_allowed` 和下一 counter；GET 不领取 worker、不推进 publication；
3. `POST /api/publications/return-dedup-staging/{job_id}/retry` 仅在 `failed && retry_allowed=true`，要求新 `operation_token`、`expected_job_revision` 与同一 proposed-set digest；业务冲突、校验失败或 outcome unknown 不得换 UUID 猜测重放；
4. publication command 的 202/409/503 响应必须返回同一个 staging 定位符；客户端轮询到 ready 后用原 publication operation token 恢复最终 CAS。`GET /api/publications/commands/{operation_token}` 只恢复结果，不触发新的 staging；
5. worker claim、续租、takeover、complete、fail 都要求 `(job_id, expected_job_revision, lease_token, fencing_token)`；旧 worker 不能覆盖新 attempt。lease 超时且没有 effect 才可 retry；存在 effect 或提交结果不确定时只能由 command recovery 收敛；
6. ready snapshot 必须精确匹配 proposed publication set、scope、rule version、所有相关 pointer revisions、group revisions、digest 和 delta depth。最终短事务采用“site return sync → dataset publication ID 升序 → dedup pointer”的唯一锁序，同时 CAS publication 与 dedup pointer；任一条件失败两个 pointer 都不变，staged job 变 `superseded` 后按新 base 重建。

稳定失败码至少包括 `return_dedup_staging_not_ready`、`return_dedup_staging_failed`、`return_dedup_staging_superseded`、`return_dedup_job_revision_conflict`、`return_dedup_publication_revision_conflict`、`return_dedup_decision_invalid` 和 `outcome_unknown`。`building` 不能冒充 published，failed/superseded 不能参与最终 CAS。

### 25.4 release 级身份来源闭集

商品分析身份来源只能由同一 release/build 注入 `legacy_parser|p0_catalog` 闭集值：后端 `APP_PRODUCT_ANALYTICS_SOURCE` 与前端 `VITE_PRODUCT_ANALYTICS_SOURCE` 必须相同，缺失、非法或不一致均 fail closed。禁止 query、header、cookie、用户、站点、SKU、行或 404 分支覆盖；新旧 API 可双轨存在，但单个响应只能声明一个 source/version，`p0_catalog` 请求不得回退旧 parser，`legacy_parser` 页面不得读取 P0 endpoint。切换与 rollback 只能以新的完整 build/process 执行，不修改目录、publication、dedup、日报事实或审计。

### 25.5 迁移、共享 revision 与文档替代关系

Task 0 已只读确认：Git 已提交 head `0019`，文件系统唯一 head `0021`，业务库及其备份为 `0020`，测试库已应用 `0021`。因此 `0020/0021` 都不可重写，P0 使用 `0022_product_catalog_foundation`；生产订单计划必须消费 P0 的 `style_id/sku_id/style_revision_id/sku_revision_id`，不得再次创建 `product_skus/product_sku_revisions`，其订单与完工迁移顺延为 `0023/0024` 并保持暂停。CLI、backup writer、restore reader、bootstrap、grant sync、matrix 和 CI 从 `backend/app/maintenance/schema_revision.py` 或对它的受控调用取得 revision；Task 1 当前 writer 精确接受 `0021`，restore reader兼容 `0020/0021`，Task 3 创建 P0 迁移时再一次性推进 writer 到 `0022`。
