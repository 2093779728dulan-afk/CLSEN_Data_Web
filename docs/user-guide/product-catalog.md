# 商品主档使用指南

商品主档是款式名称、实际颜色/尺码组合与 Seller SKU 映射的唯一 P0 身份来源。一个款式拥有稳定 `style_id`，每个实际存在的款色码拥有稳定 `sku_id`；系统不会补出未观察到的颜色×尺码组合。

## 本地隔离体验

Docker 启动后，在仓库根目录运行：

```powershell
.\scripts\run-product-catalog-live-e2e.ps1 -Milestone Catalog -Experience
```

脚本会创建随机端口、临时数据库和私有本地会话，完成真实审核验收后输出体验 URL 与 run ID，并持续监控 API、Worker、前端和数据库容器。体验结束后在另一个 PowerShell 窗口运行脚本输出的停止命令；停止脚本只写入带 run ID 的停止请求，原 runner 复核进程和容器所有权后执行清理。此模式不会复用默认服务或业务数据库。

## 初始化与审核

1. 数据管理员打开“商品主档”，确认站点与 Seller 账号范围。
2. 生成候选并下载标准 XLSX，或直接进入在线审核。候选名称只是来源证据，必须填写最终标准名称。
3. 依次处理款式、SKU、映射、异常和来源证据。每个 eligible Seller SKU 必须明确映射或排除；未分类、规范化碰撞和 unresolved duplicate 都会阻止批准。
4. 重新校验，生成批准预览，再确认批准。高风险操作需要相应权限和新的确认计数。

批准会创建不可变目录版本。需要纠错时创建向前版本，不修改历史 revision，也不直接回拨 current pointer。

## 来源与敏感信息

普通页面只显示安全 preview、摘要计数和 digest。完整 Seller SKU 只能由获授权人员临时 reveal；切换角色、目录版本或页面后会销毁。订单号、物流牌照、买家留言和危险字符不会进入普通 JSON、DOM、ARIA、URL、日志或导出的审核证据。

## 状态说明

- `mapped`：Seller SKU 已映射到稳定 `sku_id`。
- `excluded`：已明确排除，并保留原因。
- `unmatched`：尚未分类，不能批准。
- `duplicate/unresolved`：退货去重决定；未决状态不会被当作零退货。
- `audit_only`：只审核证据，不创建身份、revision、member 或 reservation。
