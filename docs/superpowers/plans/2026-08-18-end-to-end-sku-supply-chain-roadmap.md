# 全链路 SKU 供应链实施路线图

日期：2026-08-18

最近优化：2026-08-19

状态：优化草案，待用户确认决策门后拆分为 E0/C/D/E 详细实施计划

关联第一期设计：`docs/superpowers/specs/2026-08-18-finished-goods-production-receipt-design.md`

关联第一期实施：`docs/superpowers/plans/2026-08-18-finished-goods-production-receipt-implementation.md`

## 1. 目标与完成边界

本路线图承接完整业务目标：

`运营下单 → 工厂生产 → 完工入广州成品仓 → 按运营要求出货 → 海运在途 → Amazon FBA 实收 → 每日销售/退货数据`

所有业务事实必须解析到稳定、站点隔离的内部 `sku_id`。展示 SKU、Seller SKU、FNSKU、ASIN、工厂编码和历史编码都是可审计的外部标识，不能代替内部主键。

只有 A～E（含 Amazon 标识前置阶段 E0）全部完成且通过第 9 节端到端验收，才可以称为“完整业务闭环”。A/B 完成只代表第一期“订单到广州成品仓”上线。

## 2. 阶段划分

| 阶段 | 可独立体验的业务结果 | 状态 |
| --- | --- | --- |
| A | 消费 P0 商品目录、维护 production alias、运营订单上传、内部订单号、工厂订单导出 | 已有详细计划，暂停等待 P0 Milestone A 与本计划 successor 批准 |
| B | 工厂完工上传、人工审核、广州成品仓入库与冲销 | 已有详细计划，待按优化稿实施 |
| E0 | Amazon Seller Account、Marketplace、Seller SKU/FNSKU/Child ASIN 映射与不可变快照 | 后续阶段共同前置，待决策门完成后写详细计划 |
| C | 运营出货要求、出货表、广州仓扣减、海运在途 | 待决策门完成后写详细计划 |
| D | FBA 入库文件、分批实收、短溢收对账、在途转 FBA | 待决策门完成后写详细计划 |
| E | 销售/退货 CSV 解析到稳定 `sku_id`，历史数据回填与全链分析 | 待决策门完成后写详细计划 |

A 的“可独立体验”是实施计划 Task 7 继续进入 B 前的顺序验收点；P0 `0022` 先拥有商品身份，A 再在 production `0023` 保存浏览器和完整栈证据。B 开始后最终第一期代码最低 schema head 为 `0024`，路线图不把 A 的历史验收证据解释为最终代码长期兼容纯 `0023`。生产阶段不得再次创建 `product_styles/product_skus` 或两类 identity revision。

库存链关键路径固定为 `A → B → C → D`，同时存在不可绕过的标识依赖 `A → E0 → Amazon-bound Shipment 审核批准` 和 `E0 → D/E`。C 可以先创建草稿出货要求和草稿 Shipment，但任何发往 Amazon 的 Shipment 在执行 `pending_review → approved` 前必须引用一个兼容的 E0 映射快照；D 的 FBA 实收和 E 的日报解析也必须引用映射快照。E0 可以在 B/C 期间并行实施，但不能把“并行”解释成 D 可以先于 E0 上线。只有 D/E 都完成后才能做完整供应链验收。允许 B 完成后独立运营广州库存，但不得把广州库存解释为在途库存或 FBA 库存。

### 2.1 第一期边界与工厂订单导出候选契约

A/B 的正式范围、状态和实施任务仍以上述第一期设计及实施计划为准；本路线图不把 E0/C/D/E 字段反向视为第一期已经批准。为保证运营订单可以稳定交给工厂，以下《工厂生产订单》导出契约已同步写入第一期设计和实施计划，三处共同构成**第一期正式批准契约**，不能只实施其中一处：

- 文件格式为 `.xlsx`，一份文件对应一张已确认生产订单，工作表固定为 `工厂生产订单`；
- 下载文件名固定为 `production-order-{internal_order_number}-r{revision}.xlsx`，HTTP 使用安全 `Content-Disposition`；同一订单 revision 的重复导出文件名和业务单元格值均保持一致；
- 导出版本固定为 `production_factory_order_v1`，表头顺序固定为 `导出版本 | 系统生产订单号 | 订单修订号 | 外部订单号 | 订单日期 | 生产窗口开始日 | 生产窗口结束日 | SKU编码 | 款号 | 颜色 | 尺码 | 下单数量 | 备注`；除外部订单号和备注外均必填；
- `生产窗口开始日`、`生产窗口结束日` 分别对应只读派生字段 `expected_completion_from = 订单日期 + 7 个自然日`、`expected_completion_to = 订单日期 + 30 个自然日`，使用 `yyyy-mm-dd`，不维护人工预计日期；
- 每行代表一个订单明细，`SKU编码` 使用订单确认时固化的工厂编码快照；后续展示码变化不得改写历史导出或导致完工回传断链；
- 导出沿用第一期工作簿安全规则，禁止公式和外部链接；用户文本显式写为字符串单元格但不改变逻辑值，特殊前缀 SKU 必须可逐字符回传；
- 同一订单 revision 的重复导出必须得到相同业务单元格值；任何列名、顺序或派生口径变化都必须提升导出版本，不能静默改列。
- 工厂完工回传必须抄录该导出的 `导出版本` 和 `订单修订号`；订单后来调量时，旧 revision 作为生产证据保留，正式入库仍按当前有效订单事实复核。

## 3. 跨阶段不变量

### 3.1 SKU 身份

- 一个内部 `sku_id` 表示一个具体款号、颜色和尺码的实物变体。
- 同一站点不能存在两个正式 `sku_id` 表示同一规范化款色码；停用不释放身份，冲突必须阻断并人工处理。第一期不实现两个 `sku_id` 的 merge、不重绑或搬移历史事实；是否提供 merge 及其补偿规则留待后续单独决策。
- SKU 被订单、库存或 Amazon 事实引用后，款号、颜色和尺码不可直接改写历史语义。展示编码可以修改，旧编码保留为来源别名。
- 标识命名空间至少包含 `operations_excel`、`factory_completion_excel`、`amazon_seller_sku`、`amazon_fnsku`、`amazon_asin` 和 `internal_legacy`。第一期预留这些名称只表达扩展边界，不表示仅凭 `(site_id, source_type, external_code)` 就足以唯一解析 Amazon 标识；E0 必须加入下节规定的 Seller Account、Marketplace 和 ASIN 类型作用域。
- 每次 Amazon 标识的自动或人工匹配都保存匹配来源、操作者、时间、所使用的 mapping snapshot，以及本次输入的全部标识和全部候选/命中 entry；未知、歧义或多标识冲突进入待匹配队列，不能只保存被算法选中的一个 entry。只有必需的 Seller Account/Marketplace 作用域缺失，或所有可用于具体 SKU 解析的标识都缺失时才以“缺失”阻断；某个可选 Seller SKU、FNSKU 或 Child ASIN 未提供而其他已提供标识足以唯一解析时，不单独阻断。第一期 A/B 的运营/工厂编码匹配继续按设计保存来源行、`sku_id`、`sku_revision_id`、来源别名和字段快照，不要求尚未实施的 E0 mapping snapshot/evidence。

### 3.2 E0：Amazon 标识与不可变映射快照

E0 是 C/D/E 共用的后续基础阶段，不属于第一期 A/B，也不因本文出现候选字段而视为已经批准。E0 至少表达以下实体和约束：

- `sku_mapping_snapshots`：不可变快照头，保存站点、映射 schema 版本、适用的 Seller Account/Marketplace 范围、创建人、创建时间、来源映射版本和摘要；一经被 Shipment、FBA 实收或日报链接引用，不得更新或删除；
- `sku_mapping_snapshot_entries`：不可变快照项，保存快照、标识类型、规范化外部标识、Seller Account、Marketplace、ASIN 类型、目标 `sku_id`、匹配来源和证据定位符；同一快照内按下述作用域唯一；
- `sku_resolution_evidence`：不可变解析证据头，保存来源类型/来源行 ID、来源事实 revision、原始 Shipment snapshot、实际解析 snapshot、最终可空 `sku_id`、`matched | needs_match | ambiguous | conflict` 结果、规范输入摘要、匹配方式、操作者和时间；Shipment 行、FBA 导入/正式实收行、日报发布链接和回填结果都必须引用自己的证据头；
- `sku_resolution_evidence_entries`：不可变证据项，逐项保存本次实际提供的 Seller SKU、FNSKU、Child/Parent ASIN 的原始值、安全来源定位符、规范值、`normalization_schema_version`、作用域、可空的唯一 `resolved_snapshot_entry_id` 和 `matched | unknown | ambiguous | evidence_only | conflict`；只有唯一命中时才能填写 resolved entry，Parent ASIN 只能保存为 `evidence_only`；
- `sku_resolution_evidence_candidates`：不可变候选关联，保存 evidence entry、mapping snapshot 和本次解析实际命中的每一个候选 `snapshot_entry_id`。单个标识命中多个候选时必须全部保存并把 evidence entry 标为 `ambiguous`；多个标识各自唯一但指向不同 `sku_id` 时，各自候选同样全部保存并把证据头/相关项标为 `conflict`，不能让证据项上的单一外键丢失候选；
- Seller SKU 和 FNSKU 的解析键至少为 `seller_account_id + marketplace_id + identifier_type + normalized_value`；ASIN 的解析键至少为 `marketplace_id + asin_type + normalized_value`，不能把一个站点内所有 Amazon 标识当作无作用域的全局字符串；
- 只有 `child_asin` 可以直接绑定具体款色码 `sku_id`。`parent_asin` 只可作为商品族检索或证据，禁止建立一对一 SKU 映射；无法确认 ASIN 类型时进入待匹配队列；
- 同一来源行或 Shipment 行同时出现 Seller SKU、FNSKU 和 Child ASIN 时，所有已提供且已知的标识必须解析到同一 `sku_id`。任意歧义或冲突都以稳定原因码阻断，不能按静默优先级挑选一个结果；未知标识，以及必需作用域或全部可解析标识缺失时进入人工队列；单个可选标识未提供不产生伪错误；
- 新映射先形成新的不可变 snapshot；既有 snapshot 和引用它的历史事实不随当前映射变化。需要改正映射时创建后继 snapshot，并保存 `supersedes_snapshot_id`，不能原地改写旧 entry；
- Amazon-bound Shipment 在 `pending_review → approved` 时冻结映射：每条 Shipment 行保存 `sku_mapping_snapshot_id`、`sku_resolution_evidence_id`、Seller Account、Marketplace 及当时的 Seller SKU/FNSKU/Child ASIN 快照。证据中的全部命中必须与行内既定 `sku_id` 一致，否则审核失败；后续改映射不得改写已批准 Shipment；
- D 的 FBA 行先在原 Shipment 的 snapshot 内解析。只有经过明确匹配决策并创建后继 snapshot 后，才能处理旧 snapshot 未覆盖的新标识；此时 FBA 证据必须同时保存原 `shipment_mapping_snapshot_id`、实际 `resolution_mapping_snapshot_id` 和两个快照下的全部候选/命中 entry，且后继 snapshot 的唯一解析结果仍须等于 Shipment 行已经冻结的 `sku_id`，否则阻断，绝不能借 FBA 实收重绑历史 Shipment。E 的发布行链接和历史回填运行也必须引用具体 snapshot 和完整解析证据，不能引用会变化的“当前映射”。

E0 详细计划必须覆盖 snapshot 创建/审批、resolution evidence entries/candidates 的原始值/来源定位符、normalization schema/version、不可变性和完整性、待匹配队列、Seller Account/Marketplace 权限边界、跨站复合外键、幂等、冲突原因码和备份恢复。真实标识样本及谁有权批准映射仍由第 7 节决策门确认。

### 3.3 单据与数量守恒

- 订单、完工、出货、调拨、FBA 实收、销售和退货保留自己的业务单据，不互相覆盖。
- 库存变化只由审核通过的不可变流水产生；余额是流水的加速结果，不是独立事实。
- 仓间移动使用同一业务事务的双腿流水：来源仓负向、目标仓正向。两个腿必须同时成功或同时失败。
- 任意时点都能验证 `仓库余额 = 该仓全部有效流水之和`。
- 已进入下游环节后修正上游事实必须使用补偿流水。不能通过更新或删除旧流水伪造历史。

### 3.4 时间与状态

- 生产保存订单日、实际完工日、上传/审核/入账时间，并按订单日确定性派生 `expected_completion_from/to` 和窗口状态。
- 海运保存计划出货日、实际出货日、ETD、预计到港窗口、实际到港和 FBA 实收时间。
- 业务日期使用 `DATE`；系统事件时间使用 UTC，页面按站点配置时区显示。
- “7～30 天”和“30～40 天”作为监控窗口，而不是阻止真实业务入账的硬约束；逾期产生状态和提醒，不篡改单据。7～30 天边界按第 2.1 节固定派生并进入 v1 工厂导出，窗口是否触发额外提醒或审批仍由用户决策。
- 30～40 天海运窗口的候选统一口径为“实际工厂发货日 → 首次 FBA 实收业务日”，按每个 `seller_account_id + marketplace_id + Shipment + sku_id` 对账行和自然日计算，实际发货日为 D0；港口到港事件继续独立保存，但不作为该窗口的截止点。Shipment 头分别聚合“首次实收 SLA 的最差状态”“未收/部分/全收履约状态”和“是否存在活动尾货逾期”三个维度，不能合并成一个状态，也不能用某一 SKU 的首次实收掩盖另一 SKU。该首次实收 SLA 与尚未实收余量的尾货 SLA 是两个独立维度。
- 若某 Shipment + SKU 行尚无 FBA 实收，以站点当前业务日期计算在途天数；首次实收发生在 D+29 或更早标记 `early_receipt`，D+30～D+40 标记 `on_time_receipt`，D+41 或更晚标记 `late_receipt`；到 D+41 仍完全未实收则同时标记 `overdue_in_transit`。
- 无论首次实收是否准时，只要该 Shipment + SKU 行在 D+41 仍有正数在途余量，就独立标记 `remaining_overdue`，并持续到余量通过后续实收、已批准损耗或其他有审计的补偿归零。一次 D+30 的少量实收不能掩盖 D+41 仍未到仓的尾货；首次实收时效、部分/全部实收状态和尾货状态分别保存，不能互相覆盖。

### 3.5 幂等、并发与恢复

- 每个写命令使用 UUID v4、规范命令摘要和可查询的结果定位符。
- 文件按字节摘要去重，语义重复作为可确认警告；撤回批次不永久占用活动去重键。
- 客户端在提交结果不确定时保留原 UUID，并先查询命令或目标资源状态。
- 所有跨实体外键同时约束 `site_id`；API、服务和数据库三层都拒绝跨站引用。

## 4. 阶段 C：出货与海运在途

### 4.1 业务结果

运营按 SKU 提交出货要求，系统校验广州可用库存并生成《出货表》。`approved` 只表示出货单已经审核，不改变库存，也不启动海运计时；只有系统取得经第 7 节批准来源的实际离厂事实并把 Shipment 转为 `dispatched` 时，才在一个事务中从广州成品仓扣减、增加海运在途库存并固定 30～40 天窗口的 D0。

### 4.2 核心实体

- `outbound_requests`、`outbound_request_lines`：运营要求、目标 Seller Account、Marketplace、FBA Shipment、期望发货日，以及每行的 `requested_quantity`、`reserved_quantity`、`shipped_quantity`、`cancelled_quantity` 和 `remaining_quantity`；
- `inventory_reservations`：已确认但尚未实际发货的 SKU 占用；可用量为在手余额减活动预留，预留本身不写库存流水；
- `factory_shipments`、`factory_shipment_lines`：实际发货批次、SKU、实际发货数量、实际发货日、实际离厂事实来源/证据定位符和箱唛/箱数辅助字段；一条出货要求明细可以拆到多个发货明细，每条发货明细必须反向绑定唯一出货要求明细；Amazon-bound 行还必须保存第 3.2 节的不可变 mapping snapshot 和完整 `sku_resolution_evidence`；
- `inventory_transfers`、`inventory_transfer_legs`：广州仓到海运在途仓的双腿流水；
- `shipment_events`：已计划、已审核、已出库、在途、到港、取消和异常事件；
- `warehouses` 扩展逻辑仓 `ocean_in_transit`，但不把船公司状态直接当库存仓。

### 4.3 数量与状态候选契约

以下数量和状态仍需结合真实《出货要求表》《出货表》审批，但 C 详细计划不得弱化这些守恒约束：

- 每条要求明细始终满足 `requested_quantity = shipped_quantity + cancelled_quantity + remaining_quantity`，且 `0 <= reserved_quantity <= remaining_quantity`；只有实际发货成功进入 `dispatched` 后才增加 `shipped_quantity`，并原子消费对应预留；
- 要求明细状态固定候选为 `draft | confirmed | partially_shipped | fulfilled | cancelled | closed_short`；部分发货后取消只能取消剩余量并释放未消费预留，不能改写已发数量；
- 实际发货状态固定候选为 `draft | pending_review | approved | dispatched | reversed`，不另设含义重叠的 `confirmed`。Amazon 映射 snapshot、原始标识快照和完整解析证据在 `pending_review → approved` 时冻结；`approved` 只证明单据和计划数量通过审核，不增加 `shipped_quantity`、不消费预留、不写库存流水，也不设置实际发货日或 D0；
- `approved → dispatched` 必须携带实际离厂数量、实际离厂业务日和经批准来源的不可变证据定位符，并在同一事务中增加 `shipped_quantity`、消费对应预留、创建广州负向/在途正向双腿流水、写离厂事件并固定 D0。任一步失败均保持 `approved` 且零部分库存；
- 实际离厂事实究竟来自运营确认、工厂回传表、物流接口还是其他来源，本文不替用户选择。详细计划必须等第 7 节确认来源、操作者、证据字段和更正方式后，才能固定 `dispatch` 命令或导入接口；
- Amazon-bound Shipment 在 `pending_review → approved` 和 `approved → dispatched` 时都必须重新验证其不可变 mapping snapshot、完整解析证据与每行 `sku_id` 一致；缺失 snapshot/证据、未知标识或多标识冲突均阻断；
- 确认预留和审核发货都必须锁内复核可用量。广州仓余额不得为负，任何角色都不能用“特殊授权”绕过；库存不足只能减少/拆分要求、等待补货或走另行批准的库存调整单，不能伪造发货流水；
- 超出运营要求数量的发货必须阻断；如业务确需增量，先以有原因的要求变更增加 `requested_quantity`，再重新预留和审核。

### 4.4 接口与表格

- 出货要求模板上传、逐行 SKU 匹配、库存预检和人工确认；
- `GET /api/logistics/templates/outbound-request`；
- `POST/GET /api/logistics/outbound-imports` 及匹配、确认、撤回；
- `GET/POST /api/logistics/shipments`、发货审核、冲销和事件更新；
- `GET /api/logistics/shipments/{id}/factory-export` 生成《出货表》。

实际离厂的写入边界保持候选：在第 7 节确认事实来源前，不预先决定采用 Shipment 操作接口、工厂回传表导入还是物流系统接口。无论最终选择哪一种，都必须调用同一个原子 `dispatch` 领域命令并保存来源证据。

### 4.5 阶段验收

- 同一出货要求可拆成多个实际发货批次，累计实发不得超过要求量，广州仓在任何并发顺序下均不得出现负库存；
- 确认出货要求时原子创建预留，实际发货消费对应预留，取消未发部分释放预留；
- 两个并发发货不能重复占用同一广州库存；
- Shipment 到达 `approved` 后广州和在途均不变化、D0 仍为空；取得实际离厂事实并成功转为 `dispatched` 后，广州 `-N`、在途 `+N`、D0 固定为实际离厂日，任一步失败均零部分流水；
- 取消未发货要求不改库存，已发货纠错只能走补偿流水；
- 固定验收“要求 80 → 预留 80 → 分两次实发 50 + 30”，逐步验证要求、预留、实发、剩余和广州/在途余额；
- Amazon-bound Shipment 缺失 E0 snapshot 或完整解析证据时不能从 `pending_review` 批准；snapshot 中 Seller SKU/FNSKU/Child ASIN 任意冲突时不能批准或离厂，映射变化后历史 Shipment 行仍引用原 snapshot 和全部命中证据；
- ETD/ETA 变化保留事件历史。

## 5. 阶段 D：FBA 入库与差异对账

### 5.1 业务结果

系统导入或录入 Amazon FBA 入库表，在 Seller Account + Marketplace 作用域内按 Shipment ID 和 SKU/FNSKU 关联原出货行。FBA 可以分批、多次实收；短收、超收和无法匹配行进入对账队列。

### 5.2 核心实体

- `fba_receipt_imports`、`fba_receipt_import_rows`：原始文件、行证据、匹配和警告；
- `fba_receipts`、`fba_receipt_lines`：审核通过的实收事实；每条正式实收行保存其 `sku_resolution_evidence_id`，不能只把导入预览的临时匹配结果带入库存事务；
- `fba_receipt_line_reversals`：对错误实收行的不可变整行冲销事实，保存原因、操作者、命令 UUID、原实收行及其正常转仓/超收组成和所生成的全部补偿流水；v1 一条原实收行最多一个有效冲销，不支持部分数量或只冲某个组成；
- `shipment_reconciliations`：发货、在途、实收和差异数量；
- FBA 逻辑仓按站点和必要的 Amazon fulfillment center 维度配置；
- 在途到 FBA 的双腿库存流水。

### 5.3 模板、接口与状态候选契约

真实 Amazon 样表优先；若用户选择系统标准模板，候选格式为 `.xlsx`，工作表固定为 `FBA入库`，最小表头为 `Amazon Shipment ID | FNSKU | Seller SKU | 本次实收数量 | 实收日期 | Fulfillment Center | Amazon实收事件ID | 备注`。Shipment ID、正整数实收数量和实收日期必填；FNSKU、Seller SKU 至少一项必填。Seller Account 与 Marketplace 必须由经批准的文件列或上传时不可变上下文明确提供，不能仅凭 Shipment ID 全站猜测。最终列名、上下文取得方式、日期口径和 Amazon 事件唯一键必须在真实样表审批后固化并版本化。

候选 API 边界为：

- `GET /api/logistics/templates/fba-receipt`：下载经批准的 FBA 入库模板；
- `GET/POST /api/logistics/fba-receipt-imports`、`GET /api/logistics/fba-receipt-imports/{id}`：上传、分页查询和恢复批次；
- `POST /api/logistics/fba-receipt-imports/{id}/matches`、`/submit`、`/withdraw`、`/review`：匹配、提交、撤回和审核；
- `GET /api/logistics/fba-receipts/{id}`：查询正式实收及来源行；
- `POST /api/logistics/fba-receipt-lines/{id}/reverse`：由经决策门批准的角色填写原因，对错误实收行的全部有效数量和组成创建一次原子补偿，不接受部分数量，不更新或删除原实收；
- `GET /api/logistics/fba-reconciliations`、`POST /api/logistics/fba-reconciliations/{id}/resolve`：查询和解决短溢收。

导入批次状态候选为 `uploaded | needs_attention | pending_review | partially_reviewed | completed | withdrawn`；导入行状态候选为 `needs_match | invalid | ready_for_review | approved | rejected | reversed`；对账状态候选为 `open | partially_received | short_pending | over_pending | resolved_loss | resolved_overage | closed`。详细计划必须给出完整转移表、操作者权限和稳定原因码。

### 5.4 对账与入账规则

- 对每个 `seller_account_id + marketplace_id + Shipment + sku_id` 使用 `有效已发数量 + 有效已批准超收调整 = 在途剩余 + 有效 FBA 已实收 + 有效已确认损耗`，所有项均为非负整数；“有效”只统计未被冲销的事实和补偿后的净结果；
- FBA 实收不得仅凭展示 SKU 静默匹配。它必须先定位 Shipment，再按第 3.2 节生成保存全部输入和命中的不可变解析证据；默认使用 Shipment snapshot，授权使用后继 resolution snapshot 时也必须保留原 Shipment snapshot，且结果仍等于 Shipment 行既定 `sku_id`。多标识结果不一致、未经授权使用新 snapshot、标识不在允许 snapshot 或 Parent ASIN 被当作具体 SKU 时均阻断；
- 同一 Amazon 实收事件只能入账一次；完全相同文件、重复 API 请求和并发审核都不得重复实收；
- 超收、Shipment 不一致、未知 FNSKU 和已关闭 Shipment 必须显示稳定原因码；
- 正常实收在同一事务中按 `min(本次有效实收, 在途剩余)` 从在途转入 FBA。在途余额任何时候都不得为负；
- 超出累计已发量的部分先进入 `over_pending`，只有有权限的审核人确认原因后，才在同一审核事务中创建独立、可追溯的 `overage_adjustment` 正向 FBA 流水；不能通过多扣在途伪造来源；
- Shipment + SKU 行仍开放接收且尚未触发经批准的短收判定事件时，分批实收只进入 `partially_received` 并保留在途余量，不能把一次普通分批自动判成短收。只有 Amazon 权威关闭事件、授权人工关闭或第 7 节明确批准的 SLA 阈值之一发生后，正数余量才转为 `short_pending`；最终选择、证据和操作者必须写入决策门。后续允许的补收继续消费在途；长期无法收回时，由决策门确定的角色确认损耗并创建在途负向调整，原发货和实收行均不修改；
- 差异解决使用有原因的调整或补偿流水，保存命令 UUID、操作者、时间和被解决的对账记录。
- 实收行冲销必须幂等并在一个事务中整行完成。若同一原行同时包含正常“在途转 FBA”组成和超收 `overage_adjustment` 组成，必须原子创建正常组成的 FBA 负向/在途正向双腿补偿和超收组成的 FBA 负向补偿；任一组成失败则全部回滚。原实收、原流水和原对账记录保持不可变，只更新当前对账投影；
- 冲销前锁定实收行、Shipment 对账和相关余额并复核权限。任何补偿都不得使 FBA、在途或其他受影响仓余额为负；余额不足、已经冲销、下游补偿尚未完成或 revision 过期时稳定返回冲突，不能以管理员权限绕过非负约束。v1 不允许部分冲销；若未来确需部分数量或只冲一个组成，必须另行设计可独立寻址的 component 事实、各自数量上限、接口、幂等键和守恒测试，不能扩展本 v1 请求体偷渡实现。冲销权限和下游已使用库存时的补偿顺序仍由第 7 节批准；

### 5.5 阶段验收

- 一次发货可由多份 FBA 表分批实收；
- “已发 80、实收 75”在仍开放接收时产生在途 5、FBA 75 和 `partially_received`；只有模拟并保存经批准的短收判定事件后才进入 `short_pending`，确认损耗前不得自动抹平差异；
- “已发 80、实收 85”审核后产生在途转 FBA 80 和独立 `overage_adjustment +5`，在途保持 0，FBA 为 85，对账为 `resolved_overage`；
- 重复导入、回执丢失和两个窗口并发审核均只产生一次实收或超收调整；
- 每条 FBA 实收及调整都能回溯到原始文件、Shipment、出货行、生产订单和 `sku_id`；
- D+29、D+30、D+40、D+41 的首次实收分别在 `Shipment + sku_id` 粒度得到第 3.4 节规定的时效状态；无首次实收的 D+41 行为 `overdue_in_transit`；即使 D+30 已首次实收，只要 D+41 仍有在途余量就同时为 `remaining_overdue`，余量归零后该活动尾货状态解除但历史事件保留。Shipment 头分别正确聚合首次实收 SLA、履约状态和活动尾货 flag，不互相覆盖；
- 普通实收行和含正常/超收两个组成的混合实收行均可由授权角色整行冲销；混合行的所有组成要么全部补偿、要么全部不变。重复冲销、并发冲销、回执丢失和余额不足均不产生重复、部分或半完成补偿，所有仓库余额持续非负且对账公式成立。

## 6. 阶段 E：Amazon 销售与退货 SKU 串联

### 6.1 复用边界

继续复用现有 `business_report` 和 `return_report` CSV 上传、解析、审核和发布流程，不复制另一套日报系统。新增的是稳定 SKU 解析层和跨模块查询，不把生产单据塞进日报表。

“每天都有销售日报和退货日报”的完整性继续以现有 `/api/data-calendar/days`、dataset versions、当前发布指针和发布历史为权威来源；E 不创建第二套日报日历或静默改写既有发布语义。在第 7 节批准截止判定事件前，下列“首次有效发布”只是推荐候选，不表示已经获批：

- 每个站点业务日分别检查 `business_report` 与 `return_report`；是否应到、截止时间和使用的 IANA 时区由第 7 节批准；
- 截止时间后仍没有当前发布版本时显示 `missing`；首次有效发布晚于截止时间时保留 `late` 事实，即使之后补齐也不能抹去迟报历史；
- 更正 CSV 继续创建新的 dataset version 并通过既有发布流程切换当前发布指针，发布历史保留旧版本；全链查询默认读取当前发布版本，但可以按版本和 mapping snapshot 复现历史结果；
- 重传、迟报和更正只影响既有数据集版本/发布指针及其 SKU 链接，不直接改写生产、Shipment、FBA 实收或原始日报行。

### 6.2 稳定映射实体

- 发布行继续不可变地保存原始 Seller SKU、FNSKU 和 ASIN；解析时必须区分 Child/Parent ASIN，并使用 E0 snapshot 中的 Seller Account 与 Marketplace 作用域；
- `published_row_sku_links` 保存站点、报告类型、dataset version、发布行 ID、`sku_mapping_snapshot_id`、`sku_resolution_evidence_id`、可空 `sku_id`、`matched | needs_match | ambiguous | conflict`、匹配来源、被替代链接和审计信息；每个源行在同一 mapping snapshot 下最多一条结果，全部原始标识和候选/命中 entry 保存在关联的不可变 evidence entries/candidates，不能只留一个命中 ID；
- 映射变化先创建新的 `sku_mapping_snapshots`/entries，再由新链接替代旧链接；不能原地改写日报源行、旧 snapshot 或旧解析证据。查询默认使用当前发布版本对应的最新有效链接，并允许按 dataset version + mapping snapshot 复现历史结果；
- `sku_backfill_runs` 保存站点、报告类型/日期范围、固定的 `sku_mapping_snapshot_id`、游标、当前互斥结果计数 `matched/needs_match/ambiguous/conflict/failed/ignored`、累计扫描/尝试/失败尝试计数、安全错误和开始/结束时间；运行开始后不得切换 snapshot；
- `sku_backfill_failures` 保存 run ID、dataset version、发布行 ID、固定 snapshot、稳定原因码、尝试次数、最近安全错误、首次/最近失败时间和 `pending | resolved | ignored` 处理状态；不能保存未清理堆栈或用失败表替代原始行证据；
- 回填状态候选固定为 `queued | running | paused | completed | failed | cancelled`。`pause` 只在当前批次事务完成后停下，`resume` 从最后已提交游标继续；`retry` 只重跑当前 snapshot 下的未解决 failure 或从失败的已提交游标接续，不重复创建成功链接。每个 eligible source row 的当前结果始终恰好一个：pending failure 重试成功时在同一事务中把 failure 标为 `resolved`、当前 `failed - 1` 并把目标结果计数 `+1`；人工忽略时把 failure 标为 `ignored`、当前 `failed - 1`、`ignored + 1`。累计尝试/历史失败尝试只增不减并与当前结果计数分开，旧 failure 记录继续审计但不重复计入当前 `failed`。取消不删除结果、失败或审计。

### 6.3 发布前解析与历史回填

- 新文件在发布前完成 SKU 解析；未知 SKU 是否允许继续发布仍由第 7 节决策门批准。默认保留原始日报审核能力，但 `needs_match/ambiguous/conflict` 行不得进入已完成的全链分析；
- 历史已发布行按稳定主键和日期顺序回填。任务中断后从最后已提交游标继续；单行错误原子写入 `sku_backfill_failures` 后才允许游标越过该行，后续 `retry` 必须能重新定位该失败，不能把越过游标误当成成功或永久漏行；
- mapping snapshot 变化时创建新回填运行，或对受影响外部标识创建限定范围运行；新结果以 `supersedes` 关系替代旧链接，旧 snapshot、链接和 dataset version 继续可审计；
- 当前互斥结果必须满足 `eligible_rows = matched + needs_match + ambiguous + conflict + failed + ignored`；其中 `failed` 只表示仍为 `pending` 且尚无成功替代结果的 failure，`ignored` 单列且不得进入已完成全链分析。累计尝试/失败尝试不参与该恒等式；源行数量、金额、销售数量和退货数量均不因解析或回填改变；
- SKU 展示码修改后，历史事实仍通过稳定 `sku_id` 汇总；新增 Seller SKU/FNSKU snapshot entry 后，使用新 snapshot 对待匹配队列或限定历史范围幂等重跑，旧结果不变。

### 6.4 接口候选契约

- `GET/POST /api/production/sku-mapping-snapshots`、`GET /api/production/sku-mapping-snapshots/{id}`：创建和查询不可变 E0 mapping snapshot；创建/审批的最终分工和权限由 E0 详细计划按决策门固定；
- `GET /api/production/sku-resolution-queue`、`POST /api/production/sku-resolution-queue/{id}/resolve`：查询和解决未匹配、歧义及多标识冲突行；
- `GET/POST /api/production/sku-backfill-runs`、`GET /api/production/sku-backfill-runs/{id}`：创建、分页查询和查看回填；
- `POST /api/production/sku-backfill-runs/{id}/pause`、`/resume`、`/retry`、`/cancel`：在事务边界暂停、从已提交游标恢复、重试未解决失败或有审计地取消；
- `GET /api/production/sku-backfill-runs/{id}/failures`：分页查询稳定失败原因及其处理状态；
- `GET /api/data-calendar/days`：继续作为每日缺报、当前版本和发布状态入口；E 只扩展必要的 SKU 链接摘要，不复制日期状态 API；
- `GET /api/analytics/supply-chain/skus/{sku_id}`：按稳定 SKU 查询生产、广州、出货、FBA 实收、销售和退货来源关系。

### 6.5 FBA 库存边界

本路线图中的 FBA 余额明确指“系统账面收货余额”：审核通过的在途转入、`overage_adjustment` 和其他已批准 FBA 调整流水之和。页面和 API 必须标注“系统账面收货余额（非 Amazon 实时在手）”。销售日报和退货日报先作为经营事实与 FBA 实收关联，不直接增减该余额，以免订单、取消、移除和时间差造成假库存。

若用户要求权威实时 FBA 在手，必须另行纳入具有明确结算时点的 Amazon 库存、移除、赔偿和站内调拨报告，定义其流水来源、去重键和对账周期，再提升 FBA 余额的业务名称及完成边界；没有这些报告时不得把系统账面收货余额宣传为实时可售库存。

### 6.6 阶段验收

- 同一款色码的生产、广州库存、出货、FBA 实收、销售和退货返回同一个 `sku_id`；
- Seller SKU/FNSKU 按 Seller Account + Marketplace、Child ASIN 按 Marketplace 正确解析；Parent ASIN 不能直接绑定具体 SKU，多标识冲突必须阻断；
- Shipment、FBA 和日报行的解析证据都可重放全部输入标识和全部候选/命中 entry；FBA 使用后继 snapshot 时仍保留 Shipment 原 snapshot，并阻断解析到不同 `sku_id` 的结果；
- Seller SKU 改名或新增 FNSKU 后，新 snapshot 下的新旧日报仍汇总到同一变体，旧 snapshot 的历史结果可复现；
- 未匹配、歧义和多标识冲突行都有互斥计数、队列、权限、审计和可重复回填；pending failure 重试成功与 ignored 处置均原子迁移当前计数，历史尝试单独累计且不双计；
- 回填可安全 pause/resume；中途失败后从已提交游标恢复，`sku_backfill_failures` 可按同一 snapshot 重试；新 snapshot 生成新链接版本，不重复、不漏行且旧结果可复现；
- `/api/data-calendar/days` 可查询每天两类日报的缺报、迟报、当前 dataset version 和更正发布历史；重传、版本切换及回填不改变既有金额和数量；
- 现有 62 份 CSV 固定样本回归结果不丢行、不改金额和数量。

## 7. E0/C/D/E 详细计划的决策门

开始编写 E0/C/D/E 的逐任务实施计划前，必须确认：

第 3～6 节新增的字段、状态、公式、模板和 API 均是供评审的候选契约，不表示用户已经批准，也不授权直接创建迁移、后端路由或 UI。E0/C/D/E 只有在真实样表（或经用户明确选择的系统标准模板）和以下决策全部确认后，才能分别编写详细规格与实施计划：

1. 是否整体接受已经同步写入第一期设计/计划的第 2.1 节 `production_factory_order_v1` 导出补充契约；《出货要求表》《出货表》《FBA 入库表》是否提供真实样表或同意采用系统标准模板；
2. Amazon Shipment ID 在哪个环节产生，是否允许一个出货要求对应多个 Shipment；
3. 箱数、箱唛、承运人、柜号、提单号是否为必填业务字段；库存单位仍统一为“件”；
4. 7～30 天除固定派生并写入 v1 工厂导出外，是否还触发提醒或影响审批；30～40 天是否接受第 3.4 节按 `Shipment + sku_id` 计算，并在 Shipment 头分别聚合首次实收 SLA、履约状态和活动尾货 flag 的自然日及起止口径，窗口是否只提醒还是影响审批；首次实收 SLA 与 D+41 尚有余量的 `remaining_overdue` 是否采用不同提醒、升级或审批规则；
5. FBA 仓按站点统一逻辑仓，还是细分 fulfillment center；
6. FBA 分批实收从 `partially_received` 转为 `short_pending` 的权威触发究竟是 Amazon 关闭事件、授权人工关闭还是某个 SLA 阈值，以及所需证据；短收长期未解决时的损耗确认权限、超收 `overage_adjustment` 的审核权限、整条实收行冲销权限和下游已使用库存时的补偿顺序；v1 已固定不允许部分冲销，若业务拒绝该限制，必须先批准独立 component 事实与接口并重新评审 D 的范围；
7. 未匹配 Amazon 日报行是否允许发布但从全链分析排除；
8. 是否另有 Amazon 库存、移除、赔偿或调拨报告需要纳入权威库存；
9. 运营下单、工厂发货、FBA 对账和 Amazon 标识映射分别由哪些现有角色操作，是否允许本人审核本人创建的出货、实收或 mapping snapshot；
10. `approved → dispatched` 的实际离厂事实来自运营确认、工厂回传表、物流接口还是其他权威来源；由谁提交和复核，必须保存哪些证据，错误离厂日期或数量如何补偿；在该决定批准前不能自行选择输入通道；
11. 本次上线涉及哪些 Seller Account 和 Marketplace，并提供能区分 Seller SKU、FNSKU、Child ASIN 与 Parent ASIN 的真实标识样本；是否接受 Seller SKU/FNSKU 按 Seller Account + Marketplace、Child ASIN 按 Marketplace 的作用域，以及 Parent ASIN 禁止一对一绑定、多标识冲突阻断和 Shipment 保存不可变 mapping snapshot 的候选契约；
12. 每个站点业务日的销售/退货 CSV 是否都必须到齐、各自截止时间、采用哪个版本化 IANA 时区、周末/节假日是否例外；截止达成事件明确选择“上传完成”“解析成功”或“首次有效发布”（当前推荐候选），并确认缺报、迟报、补报和更正版本在 `/api/data-calendar/days` 上如何显示，不能把候选发布口径默认为已经批准。

没有真实样表时，详细计划必须先交付带版本号的模板契约和经用户确认的示例文件，不能直接假定列名。批准记录必须写明模板版本、状态枚举、数量公式、角色和时间窗口口径；后续变化走版本升级，不能静默改列或改变既有单据语义。

## 8. 建议任务拆分

决策门完成后，把后续工作拆成四个独立计划：

- E0 计划：Seller Account/Marketplace 作用域、`sku_mapping_snapshots`/entries、`sku_resolution_evidence`/entries/candidates、Child/Parent ASIN 规则、待匹配队列、snapshot 审批/API/UI、权限、冲突、幂等和完整栈验收；E0 必须先于 Amazon-bound Shipment 的 `pending_review → approved` 和 D 上线；
- C 计划：经批准的表格契约、要求/预留/实发状态转移、实际离厂事实来源、mapping snapshot 固化、迁移、出货领域服务、库存调拨、API/UI、原因码、并发与完整栈验收；
- D 计划：经批准的 FBA 表契约、导入/实收/对账状态转移、E0 snapshot 解析、Shipment 对账、短溢收入账、实收行冲销与补偿流水、API/UI、权限和完整栈验收；
- E 计划：`published_row_sku_links`、`sku_backfill_runs`、`sku_backfill_failures`、mapping snapshot 引用、发布前解析、pause/resume/retry、历史回填、日报完整性复用、跨模块查询、权限审计和完整栈验收。

每个计划继续采用“迁移可独立升级、后端集成通过、前端可独立体验、完整栈冒烟通过”的里程碑门禁。

## 9. 全链端到端验收

固定使用同款不同颜色或尺码的两个具体 SKU-A/SKU-B，并另设跨 Seller Account/Marketplace 的隔离映射，覆盖以下时间线：

1. D0：运营下单 SKU-A 100 件、SKU-B 40 件；订单确认后、任何完工发生前，导出第 2.1 节候选《工厂生产订单》，逐列验证固定文件名、内部订单号、订单 revision 和两个 SKU 的编码快照；
2. D+7 与 D+30：SKU-A 分两次完工 60 + 40；SKU-B 完工 30、欠 10 后带原因关闭。审核后广州仓为 SKU-A 100、SKU-B 30，逐 SKU 事实不串行；
3. 为指定 Seller Account + Marketplace 创建覆盖 SKU-A/SKU-B 的 E0 mapping snapshot；逐行保存 Seller SKU/FNSKU/Child ASIN 的全部候选和命中证据，验证它们各自同指既定 `sku_id`，单标识多候选为 `ambiguous`、多标识指向不同 SKU 为 `conflict`，Parent ASIN 不能直接绑定且旧 snapshot 不被新映射改写。Seller SKU/FNSKU 分别验证“同 Marketplace 不同 Seller Account”和“同 Seller Account 不同 Marketplace”可以按各自作用域映射到不同 SKU；Child ASIN 验证同值在不同 Marketplace 可映射不同 SKU，但同 Marketplace 下不能因 Seller Account 不同而改变映射；各自同一作用域内冲突必须阻断；
4. 运营要求 SKU-A 出货 80、SKU-B 出货 10 并分别原子预留，再创建引用该 snapshot 的实际发货批次；所有批次到 `approved` 时库存和 D0 不变，取得经批准来源的实际离厂事实并转为 `dispatched` 后，广州仓为 SKU-A 20、SKU-B 20，在途为 SKU-A 80、SKU-B 10，并分别固定实际离厂日；
5. SKU-A 累计分批实收 50 + 25，SKU-B 实收 10；此时 SKU-A 在途 5、SKU-B 在途 0，FBA 贡献分别为 75 和 10，SKU-A 先保持 `partially_received`。再模拟第 7 节批准的短收判定事件后才形成 `short_pending`；确认损耗前不抹平 5 件；
6. 在第二张生产订单中为 SKU-A 下单 80，先导出对应工厂订单，再完工并审核 80，使广州仓 SKU-A 从 20 回到 100；随后创建另一 Amazon-bound Shipment、预留并实际离厂 80，使广州仓 SKU-A 回到 20、该 Shipment 在途为 80；
7. 对第 6 步 Shipment 验证同一实收行“已发 80、实收 85”：正常组成从在途转入 80，审核后另建 `overage_adjustment +5`，该 Shipment 在途为 0、FBA 贡献为 85。主时间线最终逐 SKU 守恒为 SKU-A：`生产入库 180 + 超收 5 = 广州 20 + 在途 5 + FBA 160 = 185`；SKU-B：`生产入库 30 = 广州 20 + 在途 0 + FBA 10 = 30`；全局为 `广州 40 + 在途 5 + FBA 170 = 215`；
8. 以各 Shipment 的实际离厂日为 D0，在独立时效用例中分别于 D+29、D+30、D+40、D+41 首次实收并按 `Shipment + sku_id` 验证 `early_receipt/on_time_receipt/late_receipt`；验证完全未收的 D+41 行同时为 `overdue_in_transit`，D+30 首收但 D+41 仍有余量时为 `remaining_overdue`，且 Shipment 头分别聚合首次实收 SLA、履约状态和尾货 flag；
9. 在隔离的可重复 fixture 中整行冲销一条仅有正常组成的 FBA 实收行，验证 FBA 负向/在途正向双腿补偿；再整行冲销一条同时含正常 80 与超收 5 组成的实收行，验证三条补偿要么全部成功、要么全部回滚。重复、并发、余额不足或权限不足均零部分流水且仓库不为负；
10. 导入同时包含 SKU-A/SKU-B 的新销售和退货 CSV，并对历史发布行执行固定 mapping snapshot 的可中断回填；新旧 Seller SKU/FNSKU 分别解析到正确 `sku_id`，完整 evidence entries 可复现，pause/resume 和 `sku_backfill_failures` retry 后不重不漏；
11. 通过 `/api/data-calendar/days` 按第 7 节批准的截止事件验证销售/退货日报缺报、迟报、补报、当前 dataset version 和更正发布历史；版本切换后当前全链查询变化，但旧 dataset version + mapping snapshot + resolution evidence 仍可复现；
12. 修改 SKU-A 展示编码并创建后继 mapping snapshot，历史订单、流水、Shipment、FBA 实收、销售和退货关系及旧 snapshot 结果不变；用后继 snapshot 解析旧 Shipment 未覆盖的 FBA 标识时同时保存两份 snapshot 和全部命中，并证明结果不同于 Shipment 既定 `sku_id` 时阻断；
13. 对上传、审核、预留、`approved → dispatched`、实收、实收整行冲销、超收调整和回填分别模拟重复点击、并发、提交回执丢失和恢复；
14. 本固定验收 fixture 明确不创建其他库存调整；在此前提下，对 SKU-A、SKU-B 分别验证 `有效生产入库 + 有效已批准超收调整 = 广州余额 + 海运在途余额 + FBA 系统账面收货余额 + 有效已确认损耗`，再验证全局合计。通用账本若存在另行批准的外部流入/流出调整，必须分别加入等式两侧并按 SKU 展示，不能套用本 fixture 简式漏项；每个仓库余额等于有效流水之和，销售/退货导入不直接改变该库存公式，FBA 页面明确显示“系统账面收货余额（非 Amazon 实时在手）”；
15. 验证跨站访问全部拒绝；Seller SKU/FNSKU 按 Seller Account + Marketplace 两轴隔离，Child ASIN 只按 Marketplace 隔离，不得因字符串相同或错误引入 Seller Account 维度而串到另一个 SKU；
16. 在货物已进入下游后冲销一笔上游入库，验证系统要求先生成下游补偿流水，不直接改写旧事实；
17. 完成含生产、物流、FBA、mapping snapshots、resolution evidence entries/candidates 和 SKU 回填/失败队列的备份恢复 canary，恢复后逐 SKU 数量、游标、snapshot、全部候选/命中证据、冲突计数、失败记录、dataset version 和来源关系不变。

## 10. 总体完成定义

只有同时满足以下条件才算完成用户要求：

1. A～E（含 E0）均有正式批准的规格、详细实施计划、经批准的真实样表或版本化标准模板，以及真实测试证据；
2. 生产订单、完工和广州库存事实能按稳定 `sku_id`、具体 `sku_revision_id`、来源行和字段快照回溯；Amazon-bound Shipment、FBA、销售和退货事实在此基础上还能按不可变 mapping snapshot 及包含原始值、规范版本和全部候选/命中项的 resolution evidence 回溯；
3. 广州、海运在途和 FBA 系统账面收货余额的流水守恒，且未接入 Amazon 权威报告前不宣称 FBA 实时在手；
4. 7～30 天生产、实际离厂事实来源、按 `Shipment + sku_id` 计算的“实际工厂发货日 → 首次 FBA 实收日”30～40 自然日窗口和 D+41 尚有余量的尾货 SLA 均有批准的业务口径和可追溯状态；
5. 文件重复、命令重试、并发和回执丢失不会生成重复单据或部分库存；
6. 未匹配、标识冲突、差异、超额、短收、回填失败/retry 和冲销均有人工处理、权限和审计；
7. 每日销售/退货截止达成事件已经明确批准，缺报、迟报、补报和更正版本通过既有数据日历、dataset versions 和发布历史可查询；
8. 完整栈端到端、MySQL 集成、备份恢复和现有日报回归全部通过。
