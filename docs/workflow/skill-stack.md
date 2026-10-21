# CLSEN Data Web Skill 搭配表

## 用途与边界

2026-09-14状态更新：Stage 4开发和本轮真实数据体验收尾完成，development_complete / user_verified仅限确认范围（42组确认/3组部分确认）；release_validation未开始，V35历史证据不足仍未验证，未整合部署。唯一下一任务为[新主线](../superpowers/plans/2026-09-14-current-release-and-java-evolution-roadmap.md)的发布范围与基线核对（not_started）；Stage5.1/5.2为not_started / scope_pending。原完整5.1设计仅作延期参考；Java/Python详细规划在部署准备完成后，当前不安装Java或微服务Skill、不创建相关骨架。Skill选择及轻量验证规则不变。

本表面向 CLSEN Data Web 的 React 前端与 FastAPI/Python 后端。它是项目 `AGENTS.md` 的补充参考，不替代其中的开发效率、验证范围、数据边界和用户体验确认规则。

每次任务先判断改动类型，只选择最小适用 Skill 集。小型、低风险改动可以直接实施；不能因为安装了 Skill 就自动扩大为完整设计、全量测试或复杂评审流程。

默认顺序：明确可用功能 → 集中实现 → 一轮定向验证 → 提供体验入口 → 根据用户反馈修正。完整测试集中到部署准备阶段，在正式上线前完成；另行明确要求的专项验收按指定范围执行。普通开发、提交、合并准备和计划收尾不自动触发完整门禁。

当前执行范围先读[计划索引](project-plan-index.md)及[当前版本交付与Java/Python演进主线](../superpowers/plans/2026-09-14-current-release-and-java-evolution-roadmap.md)。商品主档R/A/B1/B2/C/D、Stage4页面及真实数据试用保留既有交付与确认范围。当前范围核对允许无需Skill；需要整理重大范围时使用writing-plans，按实际缺陷或UI问题再选对应指导，不由技能自动实施旧5.1四批、重开试用或启动完整验收。全局Skill文件保持原样。

## 选择方式与调用链边界

- 先判断是否需要 Skill，再选一条主流程；仅遇到具体技术问题时补充参考。无需为每个任务装配一整套 Skill。
- 小型文案、样式、配置或明确修改可直接实施；常规代码修改遵循现有实现与最小 diff，`karpathy-guidelines` 按需参考，不附加审批或前后全量测试。
- 本表对直接调用和下游调用同样有效。原 Skill 的强制措辞不能覆盖项目的测试预算、内联工作、授权和数据边界。
- 不修改全局 Skill，不因为本项目未使用就卸载。旧计划保留需求和历史验收事实，流程与验证范围按当前项目规则执行；明确有效的阶段前置条件仍须满足。

| 原 Skill 或调用链 | 本项目覆盖规则 |
| --- | --- |
| `brainstorming` → `writing-plans` | 仅重大产品选择、架构调整需要完整设计；普通任务不要求设计文档、分节批准或计划自带提交。 |
| `writing-plans` → 执行 Skill | 计划按完整使用路径组织，不把每个文件修改拆成独立测试、提交和评审任务。 |
| `executing-plans` → 子代理 / `finishing-a-development-branch` | 当前代理内联执行；完成后交付结果，不自动创建工作树、启用子代理、全量测试、push 或 merge。确有隔离需要时才准备工作树。 |
| `test-driven-development` → 完成前全量测试 | 只执行本轮目标验证。缺陷需要能识别原问题的复现；关键规则缺少覆盖时补测试，不要求普通修改每一步红绿循环。 |
| `verification-before-completion` → 当前消息重跑 | 引用仍有效的开发证据并说明版本和范围；变化影响证据有效性时才重跑受影响部分。局部结果不能外推为全量或发布通过。 |
| `code-review` / `requesting-code-review` → 并行评审 | 默认内联检查相关 diff，复用当前需求上下文；不启用子代理，不因缺少独立 spec 或 issue tracker 而新增配套流程。 |
| `systematic-debugging` → `diagnosing-bugs` | 普通缺陷从 `systematic-debugging` 开始；仅跨模块、偶发、并发、一致性或难定位的泄漏、性能问题升级到 `diagnosing-bugs`。沿用已有复现、日志和目标测试，不启动第二套排错流程。 |
| `product-design:audit` → 设计 / 外部参考 / 浏览器工具 | 只审查一条受影响使用路径，默认内联给出证据、问题和建议；不自动串联设计、外部参考、画布或浏览器回归，不新增审计系统或逐步审批。实际缺陷转入既有排错流程。 |

## 开发与部署的验证分工

开发期优先使用已有目标测试，必要时才补缺陷回归或关键规则测试。普通定向检查预算约 3 分钟，MySQL 定向验证约 10 分钟；关键问题未解决不能宣称完成，超过预算也不自动升级为全量。通过后不重复验证，失败后只重跑失败节点及受影响隔离检查。

完整回归、双版本 MySQL、完整 E2E、性能、备份恢复及部署演练留到部署准备阶段。具体命令与待办分别见 [验证策略](../operations/development-verification-policy.md) 和 [开发流程](../operations/development-workflow.md)。当前远端 CI 尚未随本表调整，不能把此策略描述为 CI 已按改动范围执行。

## 默认工作集

| 工作 | 主责 Skill | 何时使用 | 验证边界 |
| --- | --- | --- | --- |
| 新的多步骤实现方案 | `writing-plans` | 架构改变、重大产品选择或不可逆操作 | 小任务不自动要求完整计划。 |
| 执行已批准计划 | `executing-plans` | 已有清晰且批准的计划 | 按当前项目范围内联推进，不继承旧计划的逐步测试和自动收尾流程。 |
| 常规业务实现 | 无必选 Skill；按需参考 `karpathy-guidelines` | 需求清楚，现有结构可沿用 | 集中实现后运行已有受影响测试。 |
| 缺陷回归、关键业务规则 | `test-driven-development` | 需要证明原缺陷或补足实质风险覆盖 | 目标测试或最小复现；不以 TDD 作为所有后端任务的必经流程。 |
| Python/FastAPI 测试设计 | `python-testing-patterns` | 已确定需要编写测试且存在 fixture、mock 或 API 测试设计问题 | 只补充所需技术细节，不自动引入 TDD 或扩大覆盖范围。 |
| 常规故障排查 | `systematic-debugging` | 测试、页面、API、数据库或构建异常 | 先复现并定位，再做最小修复。 |
| 复杂故障升级 | `diagnosing-bugs` | 跨模块、偶发、并发、一致性、泄漏或复杂性能问题 | 不作为普通报错的默认入口。 |
| 完成声明 | `verification-before-completion` | 准备标记 `development_complete`、`ready_for_user_review` 或完成时 | 复用仍有效的相关证据，不重跑无关检查。 |
| 定向代码审查 | `code-review` | 用户要求审查或重大变更需要检查实质风险 | 当前代理内联审查，不因每次提交自动触发；不为风格偏好扩大改动。 |

## 前端工作集

| 工作 | 主责 Skill | 使用限制 |
| --- | --- | --- |
| 简单字段、文案或局部样式修正 | 无必选 Skill | 需求明确且沿用既有组件时直接实施；不因修改前端就装配整套设计工具。 |
| 新页面、整页或多个区域的信息层级调整；同页反复出现布局反馈 | `frontend-design` | 先评估受影响页面的层级与布局再集中修改，沿用 Stage 3 Token、共享组件及 React/Vite 技术栈；不使用 `vue`，不扩大为全站重设计。 |
| 步骤过多、入口难找、保存与批准含义不清；同一路径反复出现交互反馈 | `product-design:audit` | 围绕一条受影响路径做简短内联审查，依据用户提供的相关截图或本轮授权页面证据；未观察到的判断标明待验证。不自动上传真实数据、创建 Figma 画布或扩展为完整产品审计。 |
| 按需页面快检 | `webapp-testing` | 页面缺陷、跨页面或 API 联动需要时，检查一条受影响路径；纯文案和样式不自动触发浏览器回归，不替代用户体验确认。 |
| 复杂浏览器自动化 | `playwright` | 仅当 `webapp-testing` 不足或任务明确要求浏览器自动化时。 |
| 需要外部界面参考 | `anti-ui-slop` 或 `uizze-ui-research` | 只有真实外部参考能帮助解决当前视觉问题时二选一；作为补充，不与 `frontend-design` 并列主责，不把业务数据用于外部检索。 |

按问题选择主流程：布局与视觉层级用 `frontend-design`，操作顺序与理解成本用 `product-design:audit`，报错或行为不符合约定用排错流程。混合问题先处理阻塞使用的部分，只在另一类问题确实存在时补充 Skill；不默认串联全部前端工作集。截图、DOM、测试各自只支持其观察到的结论，不能仅凭截图宣称完整无障碍检查通过。

## 后端、数据与安全工作集

| 工作 | 主责 Skill | 使用限制 |
| --- | --- | --- |
| FastAPI、Python 业务逻辑 | 无必选 Skill | 优先沿用现有结构和目标测试；明确缺陷或关键规则需要时才使用 TDD。 |
| MySQL、权限、公共接口或并发改动 | `systematic-debugging`（发生异常时） | 先执行目标测试，再按项目规则扩大到必要集成验证；仅使用可抛弃的任务专用 MySQL 容器。 |
| 实际表格样本的制作、检查或分析 | `spreadsheets:Spreadsheets` | 只处理授权或合成样本；解析器、字段映射、导出接口代码按普通后端流程，不引入表格制作运行时；禁止触碰 `data/`。 |
| 安全审查或安全设计指导 | `security-best-practices` | 用户明确要求安全审查或安全设计时使用；普通鉴权、上传等改动仍须定向检查安全边界，不自动扩展成全仓安全报告。 |
| 需要设计独立的数据工作流 | 暂不创建项目专属 Skill | 先通过真实任务证明重复的流程与失败模式。 |

## 交付与用户体验状态

技能验证不能替代用户体验确认。项目状态应分开记录：

```text
development_complete
ready_for_user_review
user_verified
release_validation
accepted
```

可体验功能交付时，提供已核实的访问入口、必要前置条件、3–5 步操作和预期结果。用户明确体验通过前，不得把 `ready_for_user_review` 表示为 `user_verified` 或 `accepted`。

在现有批次交付说明中用一行记录实际使用的 Skill 及用途，例如“Skill：`frontend-design`（商品详情信息层级调整）”；没有使用则写“本批无需 Skill”。只记录本批实际读取并应用的指导，运行 Vitest、浏览器或截图工具不等于使用了对应 Skill；不追补推测的历史使用记录，不建立独立台账。

## 不应迁入的 RAG 规则

下列内容只属于 CLSEN RAG，不能作为 Data Web 默认 Skill 或规则：

- `rag-ingestion-metadata`
- 30 SKU 的 Top-3、正确图片与文档 chunk 验收
- Qdrant、BGE-M3 与 VirtualBox VM 服务检查
- RAG 的 `source_version`、`chunk_id` 与 collection 约束

只有真实任务反复出现可复用的操作步骤或失败模式时，才考虑项目专属 Skill；先用简短说明试用，确认有效再固化，不预先建设生命周期和审批体系。
