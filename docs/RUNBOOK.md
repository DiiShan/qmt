# QMT 本地数据库运行手册

## 前置条件

- Windows；
- MiniQMT 已启动并登录；
- 当前 Python 能导入 `xtquant.xtdata`；
- 默认数据根目录为 `E:\qmt_data`；
- 正式运行前确认 QMT cache 与项目目录所在磁盘空间。

## 1. Phase 0 Preflight

先做只读/缓存读取检查：

```powershell
python scripts/preflight_database.py --config config/data_config.yaml
```

首次闭环历史退市证券和过期合约时：

```powershell
python scripts/preflight_database.py --config config/data_config.yaml `
  --download-history-contracts --allow-sample-download
```

只有五项硬门槛全部 PASS 才能执行全量初始化。命令返回 2 表示 Gate 阻断。

## 2. 初始化

不带确认参数只显示计划，不下载：

```powershell
python scripts/init_database.py --config config/data_config.yaml
```

明确确认后执行：

```powershell
python scripts/init_database.py --config config/data_config.yaml --confirm-full-download
```

全量流程采用项目级单写者锁、有限证券批次、不可变 run、原子 active manifest 和 checkpoint。进程中断后重新运行同一范围会跳过 fingerprint 一致的成功批次。

## 3. 增量更新

```powershell
python scripts/update_daily.py --config config/data_config.yaml `
  --start 2026-08-01 --end 2026-08-23 --download
```

上游缺行不会自动解释为删除。重复业务主键由 DuckDB view 按 `_ingested_at` 和 `source_run_id` 选择最新已发布版本。

## 4. 验证与容量

```powershell
python scripts/validate_database.py --config config/data_config.yaml
python scripts/storage_audit.py --config config/data_config.yaml
```

容量阈值：目标 25 GiB、警告 30 GiB、硬停止 40 GiB。程序不自动删除 Raw、Processed 或 QMT cache。
容量预检由统一 manifest 发布路径执行，因此行情、财务、历史 universe 和 Derived 都不能
绕过硬限制；checkpoint、catalog 和容量报告写入前也会预留元数据空间。
财务下载还会在调用 XtData 前按 `financial_download_batch_reserve_mb`（默认 256 MiB）预留
空间，并自动发现 QMT cache 路径，分别检查项目盘和缓存盘的最低剩余空间。

## 5. 故障恢复

- 没有 `SUCCESS` 的 staging run 不进入 active manifest；
- checksum/文件缺失会让验证命令返回非零；
- stale lock 不能自动清理，必须检查持有者后显式处理；
- Derived 失败时从已发布 Processed 重建，不重新下载 Raw；
- 不要手工修改 `metadata/manifests/**/active.json`。

## 数据安全

GitHub 只保存代码、配置模板、schema、文档和合成测试数据。真实行情、财务数据、报告、日志、账号、Token、服务器地址与本机私有路径不得提交。
