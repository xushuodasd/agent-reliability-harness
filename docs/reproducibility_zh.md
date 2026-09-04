# 可复现性指南

本指南用于复现实验框架的工程行为，不承诺逐字复现付费模型输出。正式采集前必须记录操作系统、Python版本、代码提交、任务目录哈希、计划哈希、模型标识、接口地址、访问日期、解码参数、输出上限和价格。

## 本地验证

```powershell
python -m pip install -e .
python -m unittest discover -s tests -v
python -m pilot_harness.rehearsal --output runs/full-matrix-rehearsal-864
python -m pilot_harness.acceptance runs/full-matrix-rehearsal-864 `
  --milestone M4 `
  --output-dir runs/full-matrix-rehearsal-864/acceptance `
  --engineering-rehearsal
```

彩排应包含864个唯一且已完成的设计单元。由于数据来自确定性夹具，科学结论必须保持为REVISE，不能解释为真实模型证据。

## 发布前检查

1. 从干净检出运行全部测试。
2. 确认所有跟踪文件都不含密钥或个人数据。
3. 冻结版本标签并生成源码归档。
4. 将同一版本上传至Zenodo等可生成DOI的长期存档。
5. 把公开仓库地址、DOI、提交哈希和版本号补入`CITATION.cff`及论文。
6. 只发布脱敏示例数据，不公开私有供应商轨迹。
