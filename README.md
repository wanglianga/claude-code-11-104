# 号卡更换与激活办理平台（SIM Replacement & Activation）

一个用于演练“客户申请换卡 → 身份核验 → 营业分配兼容卡 → 网络准备/停旧/启新 → 客户确认可用 → 结清”的全栈系统。
**所有客户、证件、号码、ICCID/IMSI、套餐、身份结果与网络回执均为虚构，由项目内置适配器与虚构卡库模拟，不接触任何真实通信账户。**

技术栈：React 18 + TypeScript + Vite、FastAPI + SQLAlchemy 2 + PostgreSQL 18；自带模拟时钟与网络/制卡适配器。

---

## 1. 一键启动（Docker Compose）

```bash
docker compose up --build
```

- PostgreSQL 18：compose 网络内 `db:5432`，宿主映射 `127.0.0.1:5433`（避开本机 5432），库/用户/密码均为 `ccdev`
- 应用与前端：<http://localhost:8000>（FastAPI 直接托管 `frontend/dist`）
- 首次启动自动建表并写入虚构数据
- 接口文档（附加项，全栈项目不强制）：Swagger UI <http://localhost:8000/docs>，OpenAPI <http://localhost:8000/openapi.json>

> 说明：本交付工作容器内没有 `docker` 可执行文件，因此 Compose/Dockerfile 已按规范编写并通过 YAML 解析校验，但**镜像构建未在本工作区实际执行**；下列“本地验证”全部使用预装运行时真实执行通过。

---

## 2. 本地开发启动（已在交付环境真实验证）

环境已预装：Python 3.12.10、Node 22.14.0、PostgreSQL 18.1（127.0.0.1:5432，库/用户/密码 `ccdev`）。

### 2.1 启动后端

```bash
cd backend
/opt/python-3.12/bin/python3 -m venv .venv
.venv/bin/pip install -r requirements.txt \
  -i https://pypi.tuna.tsinghua.edu.cn/simple

# 默认 DATABASE_URL 已指向 postgresql+psycopg://ccdev:ccdev@127.0.0.1:5432/ccdev
# 自动化验证建议关闭“自动走钟”，改为脚本显式 tick：
SIM_AUTO_START=0 ALLOW_RESET=1 \
  .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
```

健康检查：<http://127.0.0.1:8000/api/health>

### 2.2 启动前端（二选一）

方式 A：Vite 开发服务器（热更新，`/api` 代理到 8000）

```bash
cd frontend
/opt/node-22/bin/npm install --registry=https://registry.npmmirror.com
/opt/node-22/bin/npm run dev
# 打开 http://localhost:5173
```

方式 B：构建后由后端统一托管（推荐演示，单端口）

```bash
cd frontend && /opt/node-22/bin/npm run build
# 产物在 frontend/dist，FastAPI 会自动挂载到 http://127.0.0.1:8000/
```

---

## 3. 测试账号（密码见下，均为虚构）

| 角色 | 账号 | 密码 | 能做什么 |
| --- | --- | --- | --- |
| 管理员 | `admin` | `admin123` | 全部界面与全部操作（推荐演示用） |
| 营业员（王岚） | `clerk01` | `test1234` | 受理、身份核验、分配/改分兼容卡、看卡库存 |
| 网络办理员（陈工） | `net01` | `test1234` | 挂失、准备配置、停旧、启新、查询原指令、刷新配置、推进模拟钟 |
| 客户 李明 | `13900001111` | `test1234` | 仅本人号码申请、核验、确认可用、结清 |

另有 7 个虚构号码 `13900001111` ~ `13900007777`，开户证件号见验证脚本 `IDCARD` 或订单详情的“填入开户证件号”提示。登录页可一键填充账号，也可“重置虚构数据”。

---

## 4. 业务模型与关键规则（如何落到代码）

- **四类身份分离**：客户 `ss_customers`、号码 `ss_phone_numbers`、实体卡 `ss_sim_cards`、激活凭据 `ss_credentials` 各有独立 ID；订单 `ss_replace_orders` 只编排它们之间的关系。
- **唯一激活约束**：`ss_credentials` 上有 PostgreSQL **部分唯一索引** `ux_ss_credentials_one_active (number_id) WHERE status='active'`；服务层再对号码行 `SELECT … FOR UPDATE` 加锁。并发建单同样用号码行锁 + 在办单部分唯一索引 `ux_ss_orders_one_open_per_number` 双保险。
- **制卡完成 ≠ 激活**：准备配置成功只把新凭据置为 `prepared`（未激活就绪），只有启用回执成功才置 `active`。
- **配置继承**：准备时把当前已确认套餐、权限、账期日写入 `profile_snapshot`；已用流量/通话/权益计数与权益流水挂在号码/订阅上，**换卡不清零、不改账期**。准备期间若套餐变更获批（`plan_version+1`），快照变 stale，启用会被 `PROFILE_PLAN_STALE` 拒绝，必须 `refresh_profile` 后再启用。
- **两条办理时序**（模拟时长：准备 2 分钟、停旧 1 分钟、启新 1 分钟，总 4 分钟）：
  - `prepare_first`（旧卡在手的正常升级）：备 0–2、停 2–3、启 3–4；**预计中断 T+3~T+4**；准备失败时旧卡仍 active、零中断。
  - `stop_first`（旧卡不在手/先撤旧）：停 0–1、备 1–3、启 3–4；**预计中断 T+1~T+4**；若准备失败，客户已在中断中，需紧急改分卡重备，实际中断会拉长。
- **报失强制先挂失**：`reason=lost` 不允许 `prepare_first`，且没有成功的 `report_loss` 指令时，停旧/准备都会被 `LOSS_FIRST_REQUIRED` 拒绝。
- **指令四态 + 预计/实际时刻**：`ss_network_commands` 记录 `sent / succeeded / rejected / unknown`，分别保存预计完成时刻、适配器真实执行时刻、平台确认时刻；页面分“预计 vs 实际”展示。
- **停旧结果未知的纪律**：回执丢失时，适配器侧已成功但平台超时置 `unknown`，此时启用、改分/另开第二张卡都返回 409；只能对**原指令**发起 `query_command`，以适配器留底为准落地结果，中断起点按网络真实执行时刻追溯。
- **迟到/重复回执**：`ss_scheduled_receipts` 可编排未来回执；对已终态指令的重复/迟到成功回执只写 `ss_command_receipts`（`applied=false` + `ignore_reason`），不会复活旧凭据或产生第二个 active。
- **已启新不可一键回滚**：对已激活订单直接取消返回 `USE_CONTROLLED_EXCHANGE`；只能创建受控退换单，网络台停退新凭据（`returned`、卡 `quarantine`），**旧凭据保持 stopped 不恢复**，并留下营业重新发卡待办。
- **仍需办理的任务**：`ss_task_items` 在每个关键状态生成/完成/作废对应角色待办，四个界面与订单详情均可见。

---

## 5. 页面说明（对应题目四类界面）

顶部右侧是**模拟时钟**：可 `+1 分 / +5 分`、开关“自动走钟”（默认每 2.5 真实秒推进 1 模拟分钟，可用 `SIM_TICK_REAL_MS` 调整）。所有“2 分钟/1 分钟”均为**模拟分钟**，用手动 tick 可瞬间、确定地走完流程。

1. **① 客户申请**：选号码、换卡原因、旧卡是否在手；两张时序卡片实时说明中断窗口与失败恢复差异；可勾选“停旧回执丢失”故障注入。提交后在同页订单卡完成证件核验、运行可用性探测、确认新卡可用、结清，并能看到“失败后找谁”的联系人。
2. **② 营业办理**：卡库存状态统计、全量虚构卡库（外形/制式/profile）、营业待办、受理队列；完成身份核验、分配卡、准备被拒后改分兼容卡。
3. **③ 网络任务**：网络待办、unknown/sent 指令计数、最近指令表、快捷 tick；在订单详情中下发挂失/准备/停旧/启新/查询原指令/刷新配置。
4. **④ 激活核验**：全局凭据台账（每号 active 数、stale 配置、套餐版本）、待确认订单的探测与客户确认、已结清/退换订单。

订单详情是核心：分钟轴（预计中断描边格 + 实际中断红色格）、预计/实际时刻对照、全部指令四态、回执流水（含忽略原因）、任务清单、卡与配置快照、结算与受控退换、场景注入按钮。

---

## 6. 自动化验证（推荐核对方式）

### 6.1 80 项端到端断言（覆盖题目要求的五个验证点）

先按 2.1 启动后端（建议带 `SIM_AUTO_START=0`），然后：

```bash
# 在仓库根目录，使用后端 venv（已含 httpx、psycopg）
backend/.venv/bin/python scripts/verify_scenarios.py
# 可选环境变量：
#   VERIFY_BASE_URL=http://127.0.0.1:8000
#   VERIFY_PG_DSN="host=127.0.0.1 port=5432 dbname=ccdev user=ccdev password=ccdev"
```

脚本先调 `/api/test/reset` 重建数据，可重复执行；通过 HTTP 黑盒驱动 + psycopg 直查数据库约束。结束时应输出：

```
ALL SCENARIO CHECKS PASSED：80 项断言全部通过
```

场景与核对点对照：

| 脚本段落 | 构造的场景 | 实际核对内容 |
| --- | --- | --- |
| 场景 1 | 8 个请求**同时**给 `13900001111` 换卡 | 恰好 1 个 200、其余 7 个 409 `ORDER_IN_PROGRESS`；先准备路径预计/实际中断均为 T+3~T+4；办结后每号恰 1 个 active 且为新凭据；旧凭据 stopped、旧卡 retired；配置继承 PLAN_5G_199 与权限；用量/账期不变；无遗留待办 |
| 场景 2 | 给 Mate70-X 分配 `K0001`（legacy_v1） | 准备指令 `rejected/PROFILE_INCOMPATIBLE`、订单 `prepare_failed`；旧凭据仍 active、零中断；出现 `reassign_card` 待办；K0001 释放回库；改分 K0003 后成功办结 |
| 场景 3 | 准备中批准套餐升 299 档 | plan_version 1→2 而账期/用量不变；准备完成快照 v1 且 stale；启新被 `PROFILE_PLAN_STALE` 拒；`refresh_profile` 后快照变为 PLAN_5G_299 且含“机场贵宾厅”；再启用成功，权益数据仍不变 |
| 场景 4 | 停旧指令注入 `lose_response` | 到期适配器真实成功但平台仍 `sent`，再 tick 变 `unknown/stop_old_unknown`；启用 409、改分卡 409 `STOP_UNKNOWN_QUERY_FIRST`；查询原指令后才落地 succeeded；中断起点追溯为网络真实执行 T+1；因 unknown+查询+重备，实际中断 T+1~T+6 |
| 场景 5 | 编排旧启用指令的 6 分钟后**重复迟到回执** | 回执留痕 `applied=false / duplicate_late_receipt_ignored`；active 仍唯一且为新凭据，旧凭据仍 stopped；已启新直接回滚 409 `USE_CONTROLLED_EXCHANGE`；受控退换后新凭据 returned、新卡 quarantine、旧凭据仍不恢复，并保留 `exchange_reissue` 待办 |
| 场景 6 | 客户报失 `13900006666` | 报失选 prepare_first 被 422 拒；未挂失先停旧被 422 拒；挂失→停旧→备→启名义窗口精确为 T+1~T+4；旧凭据 `loss_blocked`；结算 20 元 |
| 场景 7 | 先停旧路径再遇准备不兼容 | T+1 已实际中断且失败时无中断终点；改分后状态正确恢复为 `old_stopped`（不要求重新停旧）；重试成功，实际终点 T+6 |
| DB 级 | 直连 PG 插入第二个 active 凭据 | 触发 `UniqueViolation`，证明部分唯一索引是最终防线；卡库存总数守恒 20、reserved=0、retired=7、in_use=6、quarantine=1、in_stock=6 |

### 6.2 UI 渲染冒烟（可选）

```bash
cd frontend
/opt/node-22/bin/npm install --registry=https://registry.npmmirror.com
/opt/node-22/bin/npm install -D jsdom --cache /tmp/npm-cache  # 如尚未安装
npm run smoke:ui    # 需后端已在 :8000
```

用 jsdom 真实挂载整个 React 应用、注入 admin 登录态并切换四个页签，断言关键区块与订单详情均渲染，输出 `UI_SMOKE_OK`。

---

## 7. 本工作区实际执行过的验证结论

以下均为本交付过程中**真实执行**的结果（非推断）：

- `backend/.venv` 按 `requirements.txt` 安装成功；`reset_and_seed()` 建表、建部分唯一索引、写入 7 客户/号码/在用凭据与 20 张卡成功。
- uvicorn 多次启动成功，`GET /api/health` 200；`/docs` 200；`/openapi.json` 200（35 个路径）。
- `scripts/verify_scenarios.py` 对运行中的 uvicorn + 预装 PostgreSQL 18 反复执行，最终结果：**`ALL SCENARIO CHECKS PASSED：80 项断言全部通过`，退出码 0**（脚本会先 reset，可重复）。
- 前端 `npm run build`（`tsc --noEmit && vite build`）**通过**，产物约 183 KB JS / 9.4 KB CSS；FastAPI 托管后 `GET /` 与 `/assets/*.js` 均 200。
- `npm run smoke:ui`（jsdom 挂载真实 App）**通过**：客户申请、订单详情（时间线/指令/回执/任务）、营业办理、网络任务、激活核验全部渲染，`UI_SMOKE_OK`，未捕获致命运行时错误。
- `docker-compose.yml` 通过 YAML 解析校验；但本容器无 docker CLI，**未实际执行镜像构建/Compose 启动**，该路径需在装有 Docker 的环境用第 1 节命令做最终确认。

---

## 8. 目录结构

```
.
├── Dockerfile                 # 多阶段：node 构建前端 -> python 运行并托管 dist
├── docker-compose.yml         # db(postgres:18) + app
├── scripts/
│   └── verify_scenarios.py    # 80 项端到端断言（五场景 + 挂失/恢复/DB 约束）
├── backend/
│   ├── requirements.txt
│   └── app/
│       ├── main.py            # FastAPI、异常处理、自动 tick、静态托管
│       ├── config.py db.py models.py enums.py schemas.py seed.py
│       ├── serializers.py
│       ├── routers/api.py     # 全部 /api 路由
│       └── services/
│           ├── auth.py clock.py tasks.py commands.py
│           ├── effects.py     # 回执落地的状态机副作用
│           ├── simulator.py  # 虚构适配器 + tick/unknown/迟到回执
│           ├── workflow.py    # 申请/核验/分卡/动作守卫/确认结清/退换
│           └── scenarios.py   # 套餐变更、迟到回执编排
└── frontend/
    ├── vite.config.ts         # dev /api -> 127.0.0.1:8000
    └── src/
        ├── App.tsx api.ts labels.ts ui.tsx styles.css
        ├── components/OrderDetail.tsx OrderBrowser.tsx
        └── pages/Login/Customer/Clerk/Network/Activation
```
