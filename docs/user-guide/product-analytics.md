# 产品分析使用指南

产品分析以商品主档标准名称和稳定 `style_id/sku_id` 汇总，不使用旧 Seller SKU 解析器回退。列表页为 `/products`，详情页为 `/products/:style_id`。

## 正式本地启动

本地 Docker 环境必须在仓库根目录 `.env` 中成对设置以下值，不能只切换前端或后端：

```text
APP_PRODUCT_ANALYTICS_SOURCE=p0_catalog
VITE_PRODUCT_ANALYTICS_SOURCE=p0_catalog
```

Docker 已初始化且数据库迁移到当前 revision 后，可在仓库根目录启动并检查状态：

```powershell
docker compose --env-file .\.env -f .\ops\docker-compose.yml config
docker compose --env-file .\.env -f .\ops\docker-compose.yml up -d
docker compose --env-file .\.env -f .\ops\docker-compose.yml ps
```

入口为 `https://localhost:8443/products`，商品主档为 `https://localhost:8443/catalog`，原日报审核和已发布看板继续保留。首次部署或 schema revision 改变时，必须先按 `ops/DEPLOYMENT.md` 显式执行迁移，不能依赖普通 `up` 自动迁移。

本机 bootstrap 默认生成自签 HTTPS 证书；不要关闭证书验证。共享部署应替换为受信任域名证书，本机需要无警告访问时应由管理员按组织策略信任本机证书。

## 五项指标与日期口径

- 销售额、销量、退货数量、会话和经营转化率；转化率固定为 `销量 ÷ 会话`，分母小于等于零时显示空值。
- 退货可切换报告日或事件业务日。事件日按已冻结站点时区计算，可能引用报告日在查询区间外的 publication。
- `0` 表示真实零；`—`/null 表示不可计算；`missing` 表示缺报；`partial` 表示只有部分事实来源。它们不能互相替代。

## 列表与详情

列表显示标准名称、来源标题数量徽标、五指标、coverage 与六桶 reconciliation。详情只显示真实观察到的颜色、尺码和 SKU；选择颜色后才列出该颜色存在的尺码。趋势图最多选择八条系列，第九条会被明确阻止；每日等价矩阵提供相同数值的表格/读屏表示。

筛选、日期、退货口径、颜色、尺码、SKU 和系列都保存在 URL，可刷新、后退和分享。金额与比例使用十进制定点显示，浏览器不会先转成浮点数重算。

当入口处于 legacy 模式时，产品直达路由会在发起 P0 请求前返回旧商品页；商品主档 `/catalog` 在两种模式均按权限保留。
