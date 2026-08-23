# Storage Report

> 当前文件是代码阶段模板。真实全量初始化后，以 `E:\qmt_data\metadata\storage\latest.json` 为准。

审计输出包括：

```text
project_data_size
qmt_cache_size
staging_temp_size
free_disk_space
qmt_cache_free_disk_space
projected_bytes
projected_total
top_20_files
```

工程阈值：

```text
TARGET      <= 25 GiB
WARNING     >= 30 GiB
HARD LIMIT  >= 40 GiB
CEILING     <= 100 GiB
```

程序不会为了通过阈值自动删除项目数据或 QMT cache。
