# RustFS S3 资格报告

- 状态：**QUALIFIED**
- 开始：`2026-08-20T18:09:27Z`
- 完成：`2026-08-20T18:09:58Z`
- 镜像：`ghcr.io/rustfs/rustfs:1.0.0-rc.2-glibc`
- Manifest digest：`sha256:450779bc3f86400e934b4506e2ca53e1e3c2e332965ae0c55fe8b3afed89c831`
- Endpoint：`http://127.0.0.1:9000`（报告不记录凭据）

## P0-E01--E10

| Case | 结果 | 耗时 | 说明 |
| --- | --- | ---: | --- |
| P0-E01 | **PASS** | 81 ms | 通过 |
| P0-E02 | **PASS** | 1 ms | 通过 |
| P0-E03 | **PASS** | 506 ms | 通过 |
| P0-E04 | **PASS** | 3625 ms | 通过 |
| P0-E05 | **PASS** | 3479 ms | 通过 |
| P0-E06 | **PASS** | 1096 ms | 通过 |
| P0-E07 | **PASS** | 14573 ms | 通过 |
| P0-E08 | **PASS** | 1013 ms | 通过 |
| P0-E09 | **PASS** | 2501 ms | 通过 |
| P0-E10 | **PASS** | 0 ms | 通过 |

## 未完成项

- 无。十个资格项均已通过本次运行。

## 复跑与边界

```bash
bash qualification/s3/run.sh
```

测试 adapter 只调用 boto3 的标准 S3 API；未调用 RustFS 管理或私有 API。
本报告验证的是本机 Docker SNSD：重启一致性和停止后目录快照恢复均不等价于分布式副本、异地备份或生产 RPO/RTO。
生命周期必须在限定等待窗口内观察到对象过期，否则状态为 `NOT_PROVEN`，不会被算作通过。

## 证据文件

- `docs/evidence/rustfs-qualification.json`
- `infra/rustfs/compose.yaml`
- `qualification/s3/adapter.py`
- `qualification/s3/runner.py`
