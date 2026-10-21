# Golden manifest 工具

这里的脚本在业务解析器实现之前，为现有 CSV 建立独立、可重复验证的基线。它们只使用 Python 标准库，不导入 `backend` 中的业务代码。

## 生成与验证

从仓库根目录运行：

```powershell
python tools/build_golden_manifest.py --source .\表格 --output .\data\golden\golden-manifest.json
python tools/verify_golden_manifest.py --source .\表格 --manifest .\data\golden\golden-manifest.json
python -m unittest discover -s tools/tests -v
```

当前批准的真实数据基线为：

- 62 份 CSV、1,393 条数据行；
- 31 份经营报告、944 条数据行；
- 31 份退货报告、449 条数据行；
- 141 条退货记录的 UTC 事件日与文件名报告日不同。

生成文件位于被 Git 忽略的 `data/golden/`。不要提交该文件、原始 CSV 或任何私有测试样本。

## 编码约定

- 带 UTF-8 BOM 的经营报告用 `utf-8-sig` 解码；
- 已识别的无 BOM 退货报告按同一 Amazon 导出族用 `windows-1252` 解码；
- CSV 必须通过标准 CSV 语义读取，保留原始表头、字段尾随空格和原始文件字节哈希。

不能把退货报告回退为 GB18030：真实留言中的 Windows-1252 智能引号和 `ñ` 会被静默错误解码。

## 隐私边界

清单只记录文件级摘要、确定性哈希、行数、列数和数值合计。百分比按比例（例如 `15.90%` → `0.159`）规范化，并只保存有序值哈希、解析数量与范围，不做误导性的列求和。SKU、订单号、商品标题、买家留言和物流牌照等行级值不得以明文写入清单或测试输出。

合成测试样本已经去标识化，可以提交到仓库；真实回归样本只能放在被忽略的 `backend/tests/fixtures/private/`。
