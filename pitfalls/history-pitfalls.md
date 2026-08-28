# 项目历史踩坑归档（按需调取，按模块分类）
## 【数据库模块】
## 【后端接口模块】
## 【前端页面模块】
## 【权限&安全模块】

### 凭据泄露与扫描（2026-08-28 全库安全基线扫描）

- **.env 变量名对不上会静默回落到默认值**：`config.py` 读 `ADMIN_PASSWORD`，
  旧 `env.example` / `install.sh` 写的是 `ADMIN_INIT_PASSWORD`；pydantic 找不到就用
  `admin_password: str = "change-me"`，不报错。`install.sh` 之前也完全没写
  `JWT_SECRET_KEY`，等于用公开已知的 "change-me" 签 JWT。加 env 变量必须回头对
  `Settings` 字段名。
- **两个示例文件并存必出事**：`env.example`（孤儿，无任何引用）和 `.env.example`
  （README/INSTALL 实际引用的）曾同时存在，孤儿那个的 `ADMIN_INIT_PASSWORD`
  填的是线上真实在用的 Web 管理员密码。只留 `.env.example`。
- **gitleaks 默认规则漏掉本项目最严重的两类**：规则是熵驱动 + 已知格式驱动，
  所以 10 字符的人类密码（熵不够）和 PAN-OS API Key（`LUFRPT` 前缀，厂商专有格式）
  都不报。已在 `.gitleaks.toml` 补三条自定义规则，装门禁跑
  `bash scripts/install-git-hooks.sh`。
- **写 gitleaks 规则时 `\s` 会跨行**：它把整个文件当一个字符串匹配，
  `PASSWORD[ \t]*=[ \t]*` 写成 `\s*=\s*` 的话，空值的 `SMTP_PASSWORD=` 会把下一行
  `SMTP_FROM=a@b.c` 当成自己的值而误报。另外 gitleaks 用 Go RE2，**不支持
  负向前瞻** `(?!...)`，排除占位符要用 `[rules.allowlist]` + `regexTarget = "match"`。
- **pre-push 门禁不能扫全量历史**：历史里已经有过泄露，全量扫会永远红，门禁形同虚设。
  用 `--log-opts="--all --not --remotes"` 只扫还没推上去的 commit。
- **删文件 ≠ 消除泄露**：凭据一旦进过 git 历史，`git rm` / `git rm --cached` 只清工作树
  和索引，历史里照旧。唯一有效的修复是轮换凭据，然后验证旧凭据失效。
- **PAN-OS API Key 是从用户口令派生的**：改设备管理员密码会让此前签发的所有 API Key
  失效，所以轮换设备密码同时也就吊销了泄露的 Key（改完记得让 `keygen` 重新取一次）。
- **容器里跑 gitleaks 扫 git 历史要设 `safe.directory`**：容器内是 root，宿主目录属主
  是普通用户，git 会报 dubious ownership 直接退出。用
  `-e GIT_CONFIG_COUNT=1 -e GIT_CONFIG_KEY_0=safe.directory -e GIT_CONFIG_VALUE_0=/src`。
- **开发对话导出不要进仓库**：`docs/vibecoding-log.md` 里累积了 `curl` 明文密码、
  API Key、JWT，而且会一直长。已 `git rm --cached` + 写进 `.gitignore`。

### 安全关卡（2026-08-28）

- **全量报警的关卡等于没有关卡**：这个仓库有 30 条已判定为误报的 bandit 命中和 5 条已轮换的
  历史泄露，不做 baseline 的关卡第一次就是红的，很快会被 `--no-verify` 绕过或删掉。
  关卡必须**只报增量**。四个工具的机制各不相同：gitleaks `--baseline-path`（按 fingerprint）、
  bandit `-b`（按 文件+行号+test_id，**重构后行号漂移会误报新增**，那时要重新生成）、
  trivy `.trivyignore`（按 ID）、semgrep 就地 `# nosemgrep: <rule-id>`。
- **baseline 只能压误报，不能压"真的但暂缓"**。后者压进去就等于悄悄消失，必须同时记进
  `docs/roadmap.md`。这条是 `security-gate.sh` 和 `.trivyignore` 注释里反复强调的原因。
- **关卡 FAIL 时日志必须有明细**：gitleaks 不加 `-v` 只输出一句 `leaks found: N`，
  关卡红了却无从下手。生成 baseline 和检查两条路径要用同一个脚本（`--update-baseline` 开关），
  否则参数会漂移、baseline 和检查对不上。
- **绿灯不能证明关卡有用**，要反向验证：清空 baseline 应该 exit 1、注入一条新命中应该被拦到
  并给出准确行号。两个方向都测过才算数。
- **"工具跑挂了"必须和"发现问题了"分开报**。semgrep 拉不到规则库时退出码是 2（有命中是 1），
  原来 `if docker run ...; then` 一律当成"发现 ERROR 级命中"，配合 `--quiet` 就是
  「FAIL + 空日志」，排查方向完全错。按退出码分支，并在提示里写清 `--quiet` 会吞输出。
- **TLS 解密拦截是按域名的**：实测同一次运行里 `semgrep.dev` 报
  `self-signed certificate in certificate chain`，而 pypi / ghcr / registry.npmjs.org
  证书链全部正常。所以"别的联网步骤都过了"不能推出"没有代理拦截"。semgrep 是唯一每次都要
  现拉规则库、没有本地缓存的工具（trivy 的 DB 在命名卷里），所以它最先炸。
- **macOS bash 3.2 + `set -u` 下不能让数组初值为空**：`"${ARR[@]}"` 展开空数组会报
  `unbound variable`。`CA_ARGS` 就因此在"没配 CA bundle"这条**正常**路径上直接挂掉，
  而配了 CA bundle 的路径是好的 —— 于是先跑的那次反而是绿的。给数组塞一个无害初值。

### 出网 TLS 校验（2026-08-28）

- **`verify=False` 要按目的地分类**，不能一刀切。设备侧（PAN-OS API / SSH，管理网自签名证书）
  是有边界的既定取舍；出网侧（飞书、企业微信、AI 模型服务）header 里带 API Key /
  webhook token，关校验就是把凭据交给任意中间人。两条链路的开关必须分开，
  出网侧统一走 `app/outbound.py` 的 `outbound_verify()`。
- **httpx 0.28 起 `verify=<str>` 已废弃**，传 CA 路径会 DeprecationWarning，
  要传 `ssl.create_default_context(cafile=...)`。
- **`CERTIFICATE_VERIFY_FAILED` 只在开发机连着 GlobalProtect 时出现**，因为流量走进了
  有 TLS 解密代理的内网、证书链被企业根 CA 重签。生产不用 GP、不走那个内网，
  默认 `verify=True` 零配置就能通。所以这不是部署问题，别把 `OUTBOUND_CA_BUNDLE`
  写成安装必填项。**推论：同一段代码在 GP 连/断两种状态下表现不同**，
  出网相关的报错先确认 GP 状态再查代码。失败信息里要带排查指引（`tls_error_hint`），
  否则只看到一句 `CERTIFICATE_VERIFY_FAILED` 无从下手。

### 分组授权（scope）与凭据回显（2026-08-28 人工领域审计）

- **scope 校验是逐个接口写的，没有集中拦截点**，所以漏一个就是一个越权。审计时发现
  `/metrics/data` 漏了，而同文件的 `acc-trend`/`acc-ranking` 有 —— 靠"同文件其他函数怎么写"
  来判断是否遗漏，比靠印象可靠。新增任何读 `metric_data` / `alert_events` / `devices`
  的接口，必须显式过 `app/auth/scope.py`。
- **"没传 device_id" 不等于"不用过滤"**。跨设备聚合的接口省略 device_id 时如果直接不加
  WHERE，受限用户拿到的就是全局聚合 —— 比 IDOR 更好用，连 UUID 都不用猜。
  用 `scoped_device_sql()`，它把"全局"和"范围内全部"区分开了。
- **空 scope 必须 fail-closed 且不能用 `= ANY(:ids)`**：受限用户的分组里没有设备时
  `scoped_ids == []`，空列表传给 asyncpg 会因为推不出数组元素类型而报错，所以返回
  `AND FALSE`。
- **过滤条件写在 if/elif/else 的某个分支里就等于没写**。`batch-acknowledge` 的 scope 过滤
  只在"确认全部"那条分支上，带 `event_ids` 调用时完全不过滤。授权检查要无条件执行。
- **Copilot 是 REST 之外的第二条数据出口**，共用同一批表。5 个 action 里只有一个应用了
  scope，`device_status` 把所有设备名+IP 返回给任意 viewer。**给 Copilot 加 action 时，
  授权按"这是一个新接口"来审，不是"这是一段查询函数"。**
- **脱敏靠 key 名匹配时，先列清楚"值本身就是凭据"的字段**。原来只匹配
  `password`/`secret`，而飞书/企微的 `webhook_url` 本身就是 bearer 凭据（拿到就能往客户群
  发消息），明文回显给了任意登录用户。
- **加脱敏必须同时做回写保护**：前端编辑时会把读到的值原样提交回来，掩码直接落库就把
  真凭据覆盖成 `***` 了。约定"掩码值 = 保持不变"（`_merge_config`）。这个坑原本就已经
  存在于 email 的 `password` 字段上 —— 编辑任何字段都会把 SMTP 口令清空。
- **验证越权不需要知道任何口令**：在容器里建临时用户 + `create_access_token()` 直接签
  token，比找口令快，而且能同时造"受限"和"全局"两个身份做对照。用完记得连
  `UserGroupScope` 一起删。

### 端口发布（2026-08-28）

- **`ports: "5432:5432"` 是发布到 `0.0.0.0`**，绕过宿主防火墙。实测 LAN 内可直连本项目的
  Postgres、Redis 和后端 8000。要绑回环得写全 `"127.0.0.1:5432:5432"`，
  用 `docker compose config` 看解析出来的 `host_ip` 确认。
- **Redis 同时是 Celery broker，且本项目没设 requirepass**：暴露 6379 等于把任务队列开放，
  LAN 内任意主机可投递任务消息让 worker 执行，无需任何账号。这是当轮审计里唯一一条
  不需要账号的通路。
- **后端 8000 直连是明文 HTTP**，发布出去就等于给了一条绕过 nginx TLS 的旁路，登录口令和
  JWT 明文过网 —— "前端只开 HTTPS" 不代表系统只有 HTTPS。
- **`${VAR:-default}` 给凭据兜底 = 静默用上公开已知口令**。存设备凭据的库改成
  `${POSTGRES_PASSWORD:?...}`，没配就直接报错退出。改之前先确认 .env 里已有真值
  （对比 sha256 指纹，别打印明文），否则会拦住现有部署。

### 容器非 root 化（2026-08-28）

- **`COPY --chown` 不改 WORKDIR 目录本身的属主**。`/app` 仍是 root:root 755，
  于是 `celery beat` 往 CWD 写 `celerybeat-schedule` 直接 `Permission denied` 起不来。
  修法是把 schedule 挪走（`--schedule=/tmp/celerybeat-schedule`），
  而不是把 `/app` 整体 chown 给应用用户（那样代码目录就可写了，RCE 能落地持久化）。
- **命名卷的属主是首次创建时从镜像路径继承的**。`reportdata` 早先由 root 建出，
  切到 uid 1000 后变成只读，报表生成会挂。所以镜像里的 uid 要写死（不能用系统分配），
  且升级脚本要幂等地 `chown -R 1000:1000 /app/data`（已加进 `upgrade.sh`）。
- **nginx 非 root 要同时做三件事**，少一件起不来：pid 从 `/run` 挪到 `/tmp`、
  删掉 `user` 指令（非 root master 下无效只刷 warning）、监听端口改到 8080/8443
  （<1024 需要 root），compose 的 ports 映射同步改。
  另外 `certs/server.key` 必须对容器内 uid 101 可读（`install.sh` 生成的是 644），
  想收紧到 600 得先解决宿主/容器 uid 不一致的问题。
- **matplotlib / fontconfig 要往 `$HOME` 写缓存**，非 root 下 `HOME` 未设会退化成临时目录
  并打警告，Dockerfile 里显式设 `HOME` 和 `MPLCONFIGDIR`。