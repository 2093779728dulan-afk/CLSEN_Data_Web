# 服务器容器部署与维护

本页适用于阶段 10B 的单机 Docker Compose 部署，目标规模约 20 人。命令均在仓库根目录使用 PowerShell 7 执行。容器部署使用独立 Docker 卷，不会连接 Windows 本机 MySQL；正式业务数据仍应先备份并在测试环境演练升级。

## 部署边界

- 仅 Nginx 暴露 HTTPS，默认绑定 `127.0.0.1:8443`；MySQL 只存在于内部网络。
- 后端、worker 和前端以非 root 用户运行，默认只读根文件系统并移除 Linux capabilities。
- 应用、迁移、备份和 MySQL root 使用不同凭据。运行中的后端和 worker 不持有迁移、备份或 root 密钥。
- MySQL 内部连接强制 TLS 1.2/1.3、CA 校验和 `caching_sha2_password`。
- `ops/secrets` 只用于当前机器并已被 Git 忽略。它和 `backup_keyring` 卷必须有独立、加密的恢复副本。
- `reset-test-database` 只接受 `clsen_data_test` 或 `clsen_data_test_*`，但仍会删除对应测试库中的全部数据。它不能用于业务库。

## 首次本地体验

确认 Docker Desktop/Engine、Docker Compose v2 和 PowerShell 7 可用：

```powershell
docker version
docker compose version
pwsh --version
```

生成本机随机密码、MySQL 内部 CA 和本地自签 HTTPS 证书：

```powershell
pwsh .\ops\bootstrap-secrets.ps1
```

若密钥目录已经存在，只需要让旧的本地证书增加容器验证域名，使用：

```powershell
pwsh .\ops\bootstrap-secrets.ps1 -RotateEdgeCertificate
```

该参数只替换边缘证书和私钥，不会轮换数据库密码、session 密钥或 MySQL CA。不要为了更新 HTTPS 证书使用 `-Force`。

构建并启动：

```powershell
docker compose --env-file .\.env -f .\ops\docker-compose.yml config
docker compose --env-file .\.env -f .\ops\docker-compose.yml `
  --profile operations --profile verification --profile maintenance --profile load-test build --pull
docker compose --env-file .\.env -f .\ops\docker-compose.yml `
  --profile operations run --rm migrate
docker compose --env-file .\.env -f .\ops\docker-compose.yml up -d
docker compose --env-file .\.env -f .\ops\docker-compose.yml ps
```

`migrate` 只属于 `operations` profile。首次空库也必须把迁移作为单独步骤执行；普通 `docker compose up` 不会创建迁移容器，schema 不兼容时 backend 和 worker 会失败关闭。

首次创建容器数据库管理员；命令会在终端内安全提示密码，密码不进入命令行：

```powershell
docker compose --env-file .\.env -f .\ops\docker-compose.yml run --rm backend `
  admin create-admin --username TCJ --display-name "TCJ"
```

打开 [https://localhost:8443](https://localhost:8443)。本地证书为自签证书，浏览器会提示不受信任；共享部署前必须替换。

查看状态和日志：

```powershell
docker compose --env-file .\.env -f .\ops\docker-compose.yml ps
docker compose --env-file .\.env -f .\ops\docker-compose.yml logs --tail 200 backend worker nginx
```

## 服务器上线

1. 将 `tls_certificate.pem` 和 `tls_private_key.pem` 替换为服务器域名的可信证书；不要把私钥提交到 Git。
2. 在受控环境文件或服务管理器中设置：

```text
BIND_ADDRESS=0.0.0.0
HTTPS_PORT=8443
APP_PUBLIC_ORIGIN=https://data.example.com
```

3. 防火墙只开放 HTTPS 端口。不要映射 MySQL 3306。
4. 将 `ops/secrets`、`backup_keyring` 卷和加密备份保存到不同故障域。仅有备份而没有密钥环无法恢复。
5. 在反向代理或负载均衡器前使用时，只信任明确的代理来源，并保留客户端真实 IP；当前单机 Compose 的 Nginx 是唯一可信入口。

## 升级

升级必须使用“停止旧进程 → 备份并验证 → 显式迁移 → 核对 revision → 启动匹配制品”的顺序。先记录候选 SHA、镜像 digest 和代码声明的 `CURRENT_SCHEMA_REVISION`，然后停止所有可能访问目标数据库的旧 API 和 worker：

```powershell
docker compose --env-file .\.env -f .\ops\docker-compose.yml stop backend worker
```

按本页“加密备份”和“随机隔离恢复”章节创建备份、完成解密校验并验证随机恢复。只有备份证据有效且迁移另行获批后，才构建并执行 operations 作业：

```powershell
docker compose --env-file .\.env -f .\ops\docker-compose.yml `
  --profile operations --profile verification --profile maintenance --profile load-test build --pull
docker compose --env-file .\.env -f .\ops\docker-compose.yml `
  --profile operations run --rm migrate
```

由获批数据库账号执行只读查询：

```sql
SELECT version_num FROM alembic_version;
```

结果必须恰好一行，并与候选代码的 `CURRENT_SCHEMA_REVISION` 完全相同。随后启动匹配制品：

```powershell
docker compose --env-file .\.env -f .\ops\docker-compose.yml up -d --remove-orphans
docker compose --env-file .\.env -f .\ops\docker-compose.yml ps
```

迁移容器会先同步账号密码，再升级 Alembic，并按 `scripts/database-privileges.json` 精确收敛应用和备份权限。容器临时 IP 变化时，它会安全重绑定迁移账号的不可变数据维护身份。

不要把“镜像能构建”视为升级成功；必须确认 backend/worker 的 `schema_compatibility` 成功事件，等待所有长期服务健康，并验证 `/api/health/ready`、一次受控认证 canary 和 Worker idle/drain canary。完整错误码与处置见 [Schema 兼容性 runbook](../docs/operations/schema-compatibility.md)。

## 回滚

应用镜像只能回滚到与当前 schema revision 已证明兼容的版本。数据库已前移时优先前向修复或部署匹配制品；不得绕过启动检查、手工编辑 `alembic_version`、自动 downgrade，或让旧制品连接更新 schema。需要恢复数据时，先停止写入并在新的隔离环境验证已有加密备份，只有单独审批和演练确认后才切换。

严禁使用以下命令处理日常故障：

```text
docker compose down -v
```

`-v` 会删除 MySQL、原始文件、备份、恢复演练和密钥环卷，通常不可恢复。

产品分析 source 切换必须同时注入后端 `APP_PRODUCT_ANALYTICS_SOURCE` 与前端 build-time `VITE_PRODUCT_ANALYTICS_SOURCE`。生产前先按[商品主档发布 runbook](../docs/operations/product-catalog-rollout.md)完成 fresh legacy→P0→fresh legacy 演练、业务 checksum、性能、SELECT-only canary 和加密恢复；只回滚应用 artifact，不 downgrade 数据库或历史目录版本。

## 加密备份

首次初始化容器密钥环：

```powershell
docker compose --env-file .\.env -f .\ops\docker-compose.yml --profile maintenance run --rm maintenance `
  maintenance keyring-init `
  --path /var/lib/clsen/keyring/backup-keyring.json `
  --key-id server-initial
```

创建备份：

```powershell
docker compose --env-file .\.env -f .\ops\docker-compose.yml --profile maintenance run --rm maintenance `
  maintenance backup `
  --destination /var/lib/clsen/backups `
  --keyring /var/lib/clsen/keyring/backup-keyring.json
```

输出中的 `directory` 是恢复命令使用的备份目录。备份包含加密数据库 dump、严格清单和内容对象；成功状态只有在逐项解密校验后才写入。

## 随机隔离恢复

```powershell
docker compose --env-file .\.env -f .\ops\docker-compose.yml --profile maintenance run --rm restore-verifier `
  restore-verify `
  --backup-directory /var/lib/clsen/backups/<backup_uuid> `
  --temporary-root /var/lib/clsen/restore-tests `
  --keyring /var/lib/clsen/keyring/backup-keyring.json
```

恢复只创建随机 `clsen_restore_<uuid>` 数据库和随机目标目录，默认保留供人工检查。自动演练可加 `--cleanup`，仅在全部验证通过后清理随机目标。

## 完整部署验收

`verify-deployment.ps1` 会重建 `clsen_data_test_container`，执行镜像构建、迁移往返、最小权限、完整 MySQL 分组、HTTPS/TLS、20 读 1 发布以及备份恢复。它不会删除 Docker 卷，也不会访问本机 MySQL：

```powershell
pwsh .\ops\verify-deployment.ps1
```

需要保留现有镜像或跳过耗时约束时，可查看脚本帮助。只有脚本完整成功和 GitHub CI 全绿后，阶段 10B 才能标记完成。

## 日常维护

- 每日检查 `docker compose ps`、readiness、worker 重启次数、备份状态和磁盘余量。
- 定期创建备份，并至少周期性执行真实随机恢复；只校验文件存在不算恢复演练。
- 轮换边缘证书不会改变数据库密码。数据库密码轮换必须在维护窗口内同时更新 Docker secrets 并运行迁移容器同步账号。
- 密钥环轮换后必须保留所有仍有备份引用的旧 key，并立即验证异地密钥副本可恢复。
- 停止服务但保留数据使用 `docker compose stop`；删除容器但保留卷可使用不带 `-v` 的 `docker compose down`。


## B 1.1.0 的独立发布扩展

A 继续使用原 docker-compose.yml。B 使用同一固定来源中的两个文件：
docker-compose.yml 与 docker-compose.production.yml。
下面是准备好的操作入口，生产迁移、停写和切换仍需相应授权；
不得把 .12/.13 模拟库、虚构订单或本机体验启动脚本复制到生产。

B 的最小服务组成是原 Python API、worker、前端、MySQL，加内部 Java 订单库存服务。
Java 不发布主机端口，只在 data 内网提供服务；API/worker 使用单独的服务凭据。
Python 保持商品主档唯一写入方，Java 对已批准目录及期初核对表仅有 SELECT 权限。
正式配对固定为 clsen_data / clsen_production；
隔离演练配对固定为 clsen_data_test_<同一后缀> / clsen_production_test_<同一后缀>。
其他库名、不同后缀及用测试目录配正式库存库均拒绝。

### 构建和启动顺序

1. 先固定完整来源，包括未跟踪实现、Alembic 迁移、Flyway V1—V20、
   frontend 锁文件、Java pom 和本扩展；准备快照不能代替正式 Git SHA/CI。
2. 用现有 JDK21/Maven 构建 backend-java/target/dataweb-production-1.1.0-SNAPSHOT.jar。
   Dockerfile 只复制这个明确制品，不下载 Maven 依赖或挑选其他历史 JAR。
   Java 镜像使用 eclipse-temurin:21-jre-jammy，正式镜像构建后记录实际 digest；
   本机无该镜像时，已有宿主 JDK 检查不能冒充 Linux 镜像验证。
3. 复用原私有 secrets 目录及原 TLS/会话凭据。首次空目录先走原 bootstrap-secrets.ps1；
   然后运行 bootstrap-production-secrets.ps1，只补四个 B 凭据，不覆盖原凭据。
   不使用 -Force 重建原密钥。B 的运行容器不挂载 root、迁移或备份密码。
4. 仅在已明确的隔离项目/上线窗口，按以下顺序执行，不把 operations profile 并入普通 up：

~~~powershell
# $ProjectName / $EnvFile 必须属于当次获准目标；从仓库根目录执行。
$compose = @('compose', '--project-name', $ProjectName, '--env-file', $EnvFile,
  '-f', 'ops/docker-compose.yml', '-f', 'ops/docker-compose.production.yml')
docker @compose config --quiet
docker @compose build backend worker frontend production production-migrate production-bootstrap
docker @compose up -d mysql
docker @compose --profile operations run --rm migrate
docker @compose --profile operations run --rm production-bootstrap
docker @compose --profile operations run --rm production-migrate
docker @compose up -d
docker @compose ps
~~~

每条命令必须检查退出码；失败即停止，不继续下一步。原 migrate 负责 Python 迁移、
原权限同步和触发器合同，production-bootstrap 负责配对订单库及独立角色，
production-migrate 仅使用迁移凭据执行 Flyway。Java 普通启动先 validate，
运行账户不执行 migrate；CA/主机身份校验保留。
原 MySQL log_bin_trust_function_creators 前置保持，不给 migrator 增加 SUPER。

B 构建启用生产页、生产建档和人工表格入口；API 配置内部服务及持久化根目录。
演示模式/QA目录模式明确关闭。来源文件、待核草稿和人工整理文件写入 production_data，
平台日报原件仍写 raw_data。普通 up 不导入本机资料、初始化库存或复制模拟流水。
正式店铺范围、稳定ID、期初日期、未结订单/在途与盘点覆盖必须在切换前另行核对。
历史151件在途仍按期初保留，不能为了补链路制造FBA货件或验收。

### 双库、来源文件备份与隔离恢复

沿用既有备份 keyring 和 AES-256-GCM 分块加密；密钥继续独立加密保存，不随备份包传播。
B 备份是新格式 clsen-production-backup-v1，旧单库维护入口保留；
B 新增内容必须使用本节双库入口。

~~~powershell
pwsh ops/backup-production.ps1 -ProjectName $ProjectName -EnvFile $EnvFile -KeyringFile keyring.json
~~~

脚本记录原先运行的 backend/worker/production，只停止这三项并核实已停，
再以备份角色导出两个数据库及 raw_data / production_data。
manifest 保存两库全部基础表的行数/CHECKSUM和全部来源文件SHA256；
同一次停写期内保存，不能把不同时点的独立备份拼成一份。
密文验证完成且 catalog.json 落盘后才报告成功。
无论备份成功与否，仅恢复原先运行的三项；启动恢复失败继续报错。

恢复验证只能在归属明确、可抛弃的 MySQL 项目执行。该项目的环境必须包含：
APP_DEPLOYMENT_DATABASE=clsen_data_test_<后缀>、
PRODUCTION_DATABASE_NAME=clsen_production_test_<同一后缀>、
APP_DISPOSABLE_TEST_RUN=true。默认正式库配置在连接前拒绝 restore-test。
将备份包和 keyring 分别放入该任务隔离卷后：

~~~powershell
docker @compose --profile maintenance run --rm --no-deps production-restore-verifier restore-test --directory /var/lib/clsen/backups/<备份ID> --keyring /var/lib/clsen/keyring/keyring.json
~~~

该操作只创建本轮随机 clsen_data_test_restore_* / clsen_production_test_restore_*，
逐库导入后核对全部基础表行数/CHECKSUM，解密后核对全部来源文件摘要。
无论结果如何，清理仅限本轮创建的随机测试库和已解析、限定在临时根下的解密目录；
不覆盖源库、生产库、体验库或既有目录。保留密文/密钥受保护副本和脱敏结果。

B 上线前仍需在固定发布来源上完成完整兼容CI与适用正式门禁，
并完成目标环境、正式数据增量、停写窗口、双库/附件恢复及回退兼容确认。
若B上线后已写入新订单/收发数据，不能仅回退旧A镜像或恢复旧单库备份。
