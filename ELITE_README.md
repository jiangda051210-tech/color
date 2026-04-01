# Elite 对色引擎（全场景版）

## 核心能力

- 双模式：
  - `single`：一张现场图自动识别大板+小样并对色
  - `dual`：样板图 + 彩膜图标准对色
- 批量模式：目录级自动跑批，导出 `batch_summary.json/csv`
- 工位定位：支持 ArUco 定位点直接锁定大板四角
- 材质自适应：`auto / solid / wood / stone / metallic / high_gloss`
- 纹理抑制：对木纹/石纹做双边滤波 + 稳健统计
- 抗干扰：自动屏蔽手写字、贴纸、高光异常点
- 手动兜底：支持 `board/sample ROI` 或 `四点坐标` 强制指定检测区域
- 质量控制：输出 `p50/p75/p90/p95/p99` + `dL/dC/dH` + `置信度` + `quality_flags`
- 工艺闭环建议：根据 `dL/dC/dH` 自动匹配调参动作（`process_action_rules.json` 可配置）
- 智能决策中心：自动生成放行决策、三方评分（客户/老板/公司）与预计成本
- 客户分层策略：按 `vip/standard/growth/economy` 自动套用不同放行策略
- 客户反馈闭环：支持回写客诉/退货/返工结果并自动生成策略调优建议
- 反事实数字孪生：基于历史数据模拟“如果这样调会怎样”，输出三套最优策略
- 客诉早预警：输出 `green/yellow/orange/red` 风险等级与 7/30 天客诉概率
- Champion-Challenger：策略自动灰度升级建议（PROMOTE/CANARY/REJECT）
- 开放算法创新：LinUCB 上下文赌博机自动推荐下一阶段策略
- v14 创新引擎：光谱重建同色异谱、纹理感知色差、老化预测、自动墨量处方
- v14 市场能力：批次混拼优化、客户容忍度学习、数字色彩护照、防篡改验真
- MVP2 核心管线：预检门禁、CCM 标定、匹配评估、策略推荐、SOP 建议、会话沉淀
- 生命周期盲区全补齐：环境补偿、基材底色、湿干预测、运行监控、跨批次匹配、墨水批次、校准守卫、边缘效应、辊筒寿命、金样管理、操作员画像、全链路追溯
- 阈值可配：支持 `--target-avg/--target-p95/--target-max` 按线体覆盖默认标准
- 产线配置文件：支持 `--profile-config` 外部 JSON 覆盖档位阈值
- 报告形态：支持 `--html-report` 直接生成可分享诊断页
- 光照稳定化：默认启用 shading correction，可用 `--disable-shading-correction` 关闭
- 工业输出：JSON 报告 + 检测标注图 + 热力图 + 掩码预览

## 脚本

- `D:\color match\autocolor\elite_color_match.py`
- `D:\color match\autocolor\elite_api.py`（FastAPI 服务层）
- `D:\color match\autocolor\elite_quality_history.py`（历史数据库与漂移评估）
- `D:\color match\autocolor\elite_process_advisor.py`（工艺建议规则引擎）
- `D:\color match\autocolor\elite_decision_center.py`（智能决策中心）
- `D:\color match\autocolor\elite_counterfactual.py`（反事实策略孪生引擎）
- `D:\color match\autocolor\elite_customer_tier.py`（客户分层策略引擎）
- `D:\color match\autocolor\elite_rollout_engine.py`（Champion-Challenger 灰度引擎）
- `D:\color match\autocolor\elite_open_bandit.py`（LinUCB 开放算法策略引擎）
- `D:\color match\autocolor\elite_innovation_engine.py`（v14 创新引擎）
- `D:\color match\autocolor\color_film_mvp_v2.py`（MVP2 七模块核心管线）
- `D:\color match\autocolor\ultimate_color_film_system.py`（M08-M19 生命周期盲区模块）
- `D:\color match\autocolor\color_film_mvp_v3_optimized.py`（生产级核心管线加固版：冲突仲裁/数据门禁/局部极差兜底/动态阈值）
- `D:\color match\autocolor\ultimate_color_film_system_v2_optimized.py`（生产级生命周期加固版：首段废品/过渡段/防篡改追溯/CAPA闭环 + M20-M31 高级仲裁/规则版本/争议处理/客户场景/多机台一致性）
- `D:\color match\autocolor\elite_runtime.py`（运行时配置中心）
- `D:\color match\autocolor\run_elite_api.ps1`（一键启动 API）
- `D:\color match\autocolor\run_full_e2e_flow.py`（全链路 E2E 验收）
- `D:\color match\autocolor\run_release_gate.py`（发布门禁：quick-check + E2E + 角色边界）
- `D:\color match\autocolor\test_production_blindspots.py`（生产盲区专项测试：局部极差/脏数据/首段与过渡段/卷尾漂移/静置复判/复测争议/硬门槛仲裁/规则与版本追溯）
- `D:\color match\autocolor\run_release_gate.ps1`（发布门禁 PowerShell 包装）
- `D:\color match\autocolor\elite_runtime.env.example`（环境变量模板）
- `D:\color match\autocolor\process_action_rules.json`（工艺建议规则模板）
- `D:\color match\autocolor\decision_policy.default.json`（决策策略默认模板）
- `D:\color match\autocolor\customer_tier_policy.default.json`（客户分层策略模板）
- `D:\color match\autocolor\profile_config.example.json`（产线阈值配置模板）
- `D:\color match\autocolor\SENIA_ELITE_总整理_v2.5.0.md`（全栈技术白皮书，评审/售前/交接推荐）
- `D:\color match\autocolor\SENIA_ELITE_v14_创新全案.md`（v14 创新与市场化方案）

## 用法

### 1) 单图现场模式（推荐给业务拍照）

```bash
python "D:\color match\autocolor\elite_color_match.py" \
  --mode single \
  --image "现场照片.jpg" \
  --profile auto \
  --grid 6x8 \
  --output-dir "D:\color match\autocolor\out_elite"
```

### 2) 双图标准模式（样板 vs 彩膜）

```bash
python "D:\color match\autocolor\elite_color_match.py" \
  --mode dual \
  --reference "sample.png" \
  --film "film.png" \
  --profile auto \
  --grid 6x8 \
  --output-dir "D:\color match\autocolor\out_elite"
```

可选增强：
- `--profile-config "D:\color match\autocolor\profile_config.example.json"`
- `--html-report`
- `--action-rules-config "D:\color match\autocolor\process_action_rules.json"`
- `--decision-policy-config "D:\color match\autocolor\decision_policy.default.json"`

### 3) 手动兜底（极端拍摄条件）

```bash
python "D:\color match\autocolor\elite_color_match.py" \
  --mode single \
  --image "现场照片.jpg" \
  --board-roi "24,84,534,744" \
  --sample-roi "343,352,108,279" \
  --profile wood \
  --target-avg 2.0 --target-p95 3.2 --target-max 4.5 \
  --output-dir "D:\color match\autocolor\out_elite_manual"
```

### 4) 批量跑批（日检/抽检）

```bash
python "D:\color match\autocolor\elite_color_match.py" \
  --mode single \
  --batch-dir "D:\color match\autocolor\batch_test" \
  --batch-glob "*.jpg,*.png" \
  --recursive \
  --profile auto \
  --output-dir "D:\color match\autocolor\out_elite_batch"
```

### 5) 多张融合判定（同批次多拍）

```bash
python "D:\color match\autocolor\elite_color_match.py" \
  --mode single \
  --ensemble-dir "D:\color match\autocolor\batch_test" \
  --ensemble-glob "*.jpg,*.png" \
  --ensemble-min-count 3 \
  --profile auto \
  --html-report \
  --output-dir "D:\color match\autocolor\out_elite_ensemble"
```

### 6) ArUco 工位定位（无人化推荐）

```bash
python "D:\color match\autocolor\elite_color_match.py" \
  --mode single \
  --image "现场照片.jpg" \
  --use-aruco \
  --aruco-dict DICT_4X4_50 \
  --aruco-ids "0,1,2,3" \
  --profile auto \
  --action-rules-config "D:\color match\autocolor\process_action_rules.json" \
  --output-dir "D:\color match\autocolor\out_elite_aruco"
```

## API 服务（无人化接入）

### 启动

```powershell
powershell -ExecutionPolicy Bypass -File "D:\color match\autocolor\run_elite_api.ps1" -ApiHost 0.0.0.0 -Port 8877
```

浏览器入口：
- `http://127.0.0.1:8877/`
- `http://127.0.0.1:8877/docs`
- `http://127.0.0.1:8877/v1/system/status`
- `http://127.0.0.1:8877/ready`
- `http://127.0.0.1:8877/v1/web/executive-dashboard`

局域网访问：
- 启动脚本会自动打印 `LAN entry: http://<你的IP>:8877/`
- 若同网段其他设备打不开，请用管理员 PowerShell 执行：

```powershell
powershell -ExecutionPolicy Bypass -File "D:\color match\autocolor\open_api_firewall_8877.ps1"
```

健康检查：

```powershell
Invoke-RestMethod -Uri "http://127.0.0.1:8877/health"
Invoke-RestMethod -Uri "http://127.0.0.1:8877/ready"
```

快速巡检：

```powershell
powershell -ExecutionPolicy Bypass -File "D:\color match\autocolor\system_quick_check.ps1" -ApiHost 127.0.0.1 -Port 8877
```

如开启鉴权，可增加：

```powershell
powershell -ExecutionPolicy Bypass -File "D:\color match\autocolor\system_quick_check.ps1" -ApiHost 127.0.0.1 -Port 8877 -ApiKey "operator-key" -AdminKey "admin-key"
```

如开启租户隔离，可增加：

```powershell
powershell -ExecutionPolicy Bypass -File "D:\color match\autocolor\system_quick_check.ps1" -ApiHost 127.0.0.1 -Port 8877 -ApiKey "operator-key" -AdminKey "admin-key" -TenantId "tenant-a"
```

停服：

```powershell
powershell -ExecutionPolicy Bypass -File "D:\color match\autocolor\stop_elite_api.ps1" -Port 8877
```

运行时环境变量（可选）：

- 参考 `D:\color match\autocolor\elite_runtime.env.example`
- 支持 `ELITE_API_HOST / ELITE_API_PORT / ELITE_LOG_LEVEL / ELITE_OUTPUT_ROOT / ELITE_HISTORY_DB / ELITE_INNOVATION_DB / ELITE_ACCEPTANCE_SYNC_TTL_SEC / ELITE_ENABLE_AUDIT_LOG / ELITE_AUDIT_LOG_PATH / ELITE_METRICS_WINDOW_SIZE / ELITE_ENABLE_API_KEY_AUTH / ELITE_API_KEYS_JSON / ELITE_AUTH_HEADER_NAME / ELITE_RATE_LIMIT_RPM / ELITE_ENFORCE_TENANT_HEADER / ELITE_TENANT_HEADER_NAME / ELITE_ALLOWED_TENANTS / ELITE_ALERT_WEBHOOK_URL / ELITE_ALERT_WEBHOOK_MAP_JSON / ELITE_ALERT_PROVIDER / ELITE_ALERT_DINGTALK_SECRET / ELITE_ALERT_TIMEOUT_SEC / ELITE_ALERT_MIN_LEVEL / ELITE_ALERT_COOLDOWN_SEC / ELITE_ALERT_RETRY_COUNT / ELITE_ALERT_RETRY_BACKOFF_MS / ELITE_ALERT_DEAD_LETTER_PATH / ELITE_ALERT_DEAD_LETTER_MAX_MB / ELITE_ALERT_DEAD_LETTER_BACKUPS / ELITE_ENABLE_SECURITY_HEADERS / ELITE_AUDIT_ROTATE_MAX_MB / ELITE_AUDIT_ROTATE_BACKUPS / ELITE_METRICS_MAX_PATH_ENTRIES / ELITE_OPS_SUMMARY_CACHE_TTL_SEC`

鉴权与角色（可选）：

- 开启：`ELITE_ENABLE_API_KEY_AUTH=true`
- 密钥：`ELITE_API_KEYS_JSON` 支持两种 JSON 结构  
  `{"viewer":"...","operator":"...","admin":"..."}` 或 `{"key-a":"viewer","key-b":"operator","key-c":"admin"}`
- 角色权限：`viewer < operator < admin`
- 建议：`admin` 仅用于系统接口（如 `/v1/system/audit-tail`、`/v1/system/self-test`）

多租户与告警（可选）：

- 多租户强制：`ELITE_ENFORCE_TENANT_HEADER=true`
- 租户头：`ELITE_TENANT_HEADER_NAME=x-tenant-id`
- 允许租户：`ELITE_ALLOWED_TENANTS=tenant-a,tenant-b`
- 告警 Webhook：`ELITE_ALERT_WEBHOOK_URL=https://...`
- 告警通道：`ELITE_ALERT_PROVIDER=webhook|wecom|dingtalk`
- 钉钉签名：`ELITE_ALERT_DINGTALK_SECRET=...`（当 provider=dingtalk）
- 分级告警路由：`ELITE_ALERT_WEBHOOK_MAP_JSON={"warning":"...","error":"...","critical":"..."}`（可选）
- 告警失败兜底队列：`ELITE_ALERT_DEAD_LETTER_PATH / ELITE_ALERT_DEAD_LETTER_MAX_MB / ELITE_ALERT_DEAD_LETTER_BACKUPS`
- 告警等级：`ELITE_ALERT_MIN_LEVEL=warning|error|critical`

### 主要接口

- `POST /v1/analyze/single`：单图自动对色
- `POST /v1/analyze/dual`：样板 vs 彩膜
- `POST /v1/web/analyze/single-upload`：浏览器文件直传（single）
- `POST /v1/web/analyze/dual-upload`：浏览器文件直传（dual）
- `POST /v1/analyze/batch`：目录批量跑批
- `POST /v1/analyze/ensemble`：多张融合判定
- `POST /v1/outcome/record`：回写真实业务结果（客诉/退货/返工等）
- `POST /v1/strategy/champion-challenger`：策略灰度升级评估（冠军-挑战者）
- `GET /v1/profiles`：查看所有材质档位阈值
- `GET /v1/system/status`：系统状态总览（运行时/路径/缓存/路由）
- `GET /ready`：生产就绪探针（失败时返回 503）
- `GET /v1/system/self-test`：一键自检关键依赖与可写性
- `GET /v1/system/metrics`：请求吞吐/错误率/热点路由时延指标
- `GET /v1/system/slo`：服务可用性与时延 SLO 观测（默认排除 analyze 重计算路由，可用 `include_analysis_paths=true` 切换）
- `GET /v1/system/auth-info`：鉴权启用状态、当前角色与限流配置
- `GET /v1/system/tenant-info`：租户隔离状态与当前租户上下文
- `POST /v1/system/alert-test`：告警链路联调测试（admin）
- `GET /v1/system/alert-dead-letter`：告警失败队列查询（admin）
- `POST /v1/system/alert-replay`：告警失败重放（admin）
- `GET /v1/system/audit-tail`：结构化审计日志尾部查询
- `GET /v1/system/ops-summary`：运维总览（状态/指标/审计/经营摘要）
- `GET /v1/system/executive-brief`：老板执行简报（GO/NO_GO + 评分 + 建议）
- `GET /v1/system/executive-weekly-card`：老板周报卡片（评分/ROI/风险）
- `GET /v1/system/cockpit-snapshot`：中控聚合快照（驾驶舱核心指标单请求）
- `GET /v1/system/next-best-action`：下一最佳动作（NBA）智能建议与执行序列
- `GET /v1/system/release-gate-report`：发布门禁结果查询（quick-check + E2E）
- `GET /v1/web/executive-brief`：老板执行简报网页（可筛选）
- `GET /v1/web/executive-dashboard`：老板视角经营驾驶舱
- `GET /v1/web/precision-observatory`：Precision Color Observatory 精密色彩观测站（内置 Live Command Pod，可实时拉取 cockpit + NBA）
- `GET /v1/web/assets/observatory-module.js`：观测站前端模块脚本（自动构建）
- `GET /v1/history/executive-export`：经营指标 CSV 导出
- `GET /v1/policy/customer-tier`：查看客户分层策略解析结果
- `GET /v1/history/overview`：历史总览（通过率/均值）
- `GET /v1/history/early-warning`：客诉风险早预警（7/30 天概率）
- `GET /v1/history/outcomes`：闭环结果明细
- `GET /v1/history/outcome-kpis`：客诉/退货/返工等闭环指标
- `GET /v1/history/policy-recommendation`：策略调优建议（自动收紧/放宽阈值）
- `GET /v1/history/policy-lab`：策略数字孪生仿真（多目标 Pareto 优选）
- `GET /v1/history/counterfactual-twin`：反事实策略孪生（Conformal 区间 + 三方案输出）
- `GET /v1/history/open-bandit-policy`：LinUCB 上下文赌博机策略推荐
- `POST /v1/analyze/spectral`：光谱重建 + 同色异谱风险
- `POST /v1/analyze/texture-aware`：纹理感知色差调制
- `POST /v1/analyze/full-innovation`：一次输出全量 v14 创新分析
- `GET /v1/history/drift-prediction`：基于历史库的漂移超标预测
- `POST /v1/predict/aging`：颜色老化预测（1/3/5/10/15 年）
- `POST /v1/predict/differential-aging`：样板-彩膜差异老化预测
- `POST /v1/correct/ink-recipe`：自动墨量修正处方
- `POST /v1/optimize/batch-blend`：多批次最优混拼
- `POST /v1/customer/acceptance-record`：客户容忍度在线学习样本写入
- `GET /v1/customer/acceptance-profile`：客户容忍度画像
- `GET /v1/customer/complaint-probability`：客户投诉概率预测
- `GET /v1/customer/dynamic-threshold`：目标投诉率反推动态阈值
- `POST /v1/passport/generate`：生成数字色彩护照
- `POST /v1/passport/verify`：护照验真 + 漂移核验
- `GET /v1/innovation/manifest`：查看创新引擎与路由清单
- `GET /v1/mvp2/manifest`：MVP2 七模块能力与接口清单
- `POST /v1/mvp2/pipeline/run`：执行 MVP2 端到端管线（预检->补偿->CCM->决策）
- `POST /v1/mvp2/ccm/calibrate`：CCM 标定矩阵求解（最小二乘）
- `POST /v1/mvp2/matcher/evaluate`：匹配策略评分（含风险与置信度）
- `POST /v1/mvp2/matcher/strategy`：动作策略推荐（放行/重检/工艺修正）
- `GET /v1/mvp2/sop`：工艺 SOP 建议库
- `GET /v1/mvp2/sessions`：MVP2 会话记录查询
- `GET /v1/lifecycle/manifest`：M08-M45 生命周期能力与接口清单
- `POST /v1/lifecycle/preflight-check`：任务前置条件完整性检查
- `POST /v1/lifecycle/environment/record`：记录车间温湿度/光源小时数
- `POST /v1/lifecycle/environment/check`：环境偏移检查（温湿/灯箱漂移）
- `POST /v1/lifecycle/environment/compensate`：环境补偿（Lab 偏移修正）
- `POST /v1/lifecycle/substrate/register`：基材底色入库
- `POST /v1/lifecycle/substrate/compare`：基材批次差异与传递影响评估
- `POST /v1/lifecycle/wet-dry/predict`：湿色到干色漂移预测
- `POST /v1/lifecycle/wet-dry/learn`：干燥模型在线学习更新
- `POST /v1/lifecycle/run-monitor/target`：设置在线监控目标线
- `POST /v1/lifecycle/run-monitor/add-sample`：运行中采样点写入（支持 `meter_position` / `roll_id` / `timestamp`）
- `GET /v1/lifecycle/run-monitor/report`：趋势/突变/连续漂移告警报告
- `POST /v1/lifecycle/roll/register`：卷材主数据登记（支持母卷/子卷/返工卷关联）
- `POST /v1/lifecycle/roll/mark-zone`：卷段区域标记（restart/transition/rework）
- `POST /v1/lifecycle/roll/add-measurement`：按米数写入卷段质量事件
- `GET /v1/lifecycle/roll/summary`：单卷前中后/过渡段风险摘要
- `GET /v1/lifecycle/roll/lot-summary`：批次内多卷风险总览
- `POST /v1/lifecycle/cross-batch/register`：跨批次生产上下文登记
- `POST /v1/lifecycle/cross-batch/match`：跨批次追加单匹配评估
- `POST /v1/lifecycle/ink-lot/register`：墨水批次色度信息登记
- `GET /v1/lifecycle/ink-lot/variation`：同型号跨批次波动统计
- `POST /v1/lifecycle/calibration/register`：设备校准计划登记（周/月/季）
- `POST /v1/lifecycle/calibration/record`：校准执行记录写入
- `GET /v1/lifecycle/calibration/status`：校准倒计时与逾期状态
- `POST /v1/lifecycle/edge/analyze`：版面边缘效应分析（四边最差）
- `POST /v1/lifecycle/roller/register`：辊筒寿命基线登记
- `POST /v1/lifecycle/roller/update`：辊筒寿命进度与质量关联更新
- `GET /v1/lifecycle/roller/status`：辊筒当前寿命状态
- `POST /v1/lifecycle/golden/register`：金样登记
- `POST /v1/lifecycle/golden/check`：金样漂移检查与更换触发
- `POST /v1/lifecycle/operator/record`：操作员任务结果记录
- `GET /v1/lifecycle/operator/profile`：操作员一次过率与技能画像
- `GET /v1/lifecycle/operator/leaderboard`：操作员排行榜
- `POST /v1/lifecycle/trace/add-event`：追溯链事件写入（哈希链）
- `GET /v1/lifecycle/trace/chain`：追溯链读取与验真
- `POST /v1/lifecycle/trace/root-cause`：客诉反向根因定位
- `GET /v1/lifecycle/advanced/manifest`：高级模块路由清单（time/process/appearance/customer/retest/machine/learning/rules）
- `POST /v1/lifecycle/msa/record`：MSA样本记录（重复性/再现性）
- `GET /v1/lifecycle/msa/report`：测量系统能力报告（gage风险/测量置信度）
- `POST /v1/lifecycle/spc/record`：SPC点位写入
- `GET /v1/lifecycle/spc/report`：SPC控制图状态与特殊原因告警
- `POST /v1/lifecycle/metamerism/evaluate`：同色异谱风险评估
- `POST /v1/lifecycle/post-process/evaluate`：后处理色移风险评估
- `POST /v1/lifecycle/storage/evaluate`：储运老化/延迟失效风险评估
- `POST /v1/lifecycle/state/transition`：生命周期状态机迁移（含审计）
- `GET /v1/lifecycle/state/snapshot`：生命周期状态快照
- `POST /v1/lifecycle/failure-mode/register`：失效模式登记（FMEA项）
- `GET /v1/lifecycle/failure-mode/list`：失效模式与RPN列表
- `POST /v1/lifecycle/failure-mode/capa-candidates`：按触发项生成CAPA候选
- `POST /v1/lifecycle/alerts/push`：告警写入（去重/聚合）
- `GET /v1/lifecycle/alerts/summary`：告警摘要
- `POST /v1/lifecycle/trace/revision`：追溯事件修订（append-only）
- `POST /v1/lifecycle/trace/override`：人工覆盖审计记录
- `POST /v1/lifecycle/decision/integrated`：综合仲裁（自动判定/建议复核/人工仲裁）
- `GET /v1/lifecycle/decision/snapshots`：历史判定快照查询
- `POST /v1/lifecycle/decision/replay`：按历史快照重放复算
- `POST /v1/lifecycle/decision/simulate-rules`：多规则版本批量模拟与结论差异评估
- `POST /v1/lifecycle/decision/simulate-rules-batch`：多快照+多规则组合的批量影响模拟
- `POST /v1/lifecycle/decision/role-view`：按角色生成操作工/工艺/质量/客服/管理层视图
- `POST /v1/lifecycle/case/open`：质量工单开启（NC/偏差/争议）
- `POST /v1/lifecycle/case/action`：工单行动项登记（责任人/描述/到期）
- `POST /v1/lifecycle/case/transition`：工单状态迁移（open->investigating->...）
- `POST /v1/lifecycle/case/waiver`：让步放行审计登记（批准人/原因）
- `POST /v1/lifecycle/case/close`：工单关闭与效果验证记录
- `GET /v1/lifecycle/case/get`：单工单详情+事件链
- `GET /v1/lifecycle/case/list`：工单列表查询
- `POST /v1/lifecycle/report/release`：批次放行报告（customer/internal 双视角）
- `POST /v1/lifecycle/report/complaint`：客诉调查摘要自动生成
- `GET /v1/lifecycle/known-boundaries`：当前系统显式边界清单（用于上线治理）
- `GET /v1/report/html`：在线查看 HTML 报告（项目目录内安全路径）
- `GET /v1/history/executive`：经营指标（放行率/三方指数/成本）
- `GET /v1/history/runs`：历史明细记录

### 一键全链路验收（整项目）

```powershell
python "D:\color match\autocolor\run_full_e2e_flow.py" --base-url "http://127.0.0.1:8877"
```

如开启鉴权，可先设置：

```powershell
$env:ELITE_E2E_API_KEY = "operator-key"
$env:ELITE_E2E_ADMIN_KEY = "admin-key"
python "D:\color match\autocolor\run_full_e2e_flow.py" --base-url "http://127.0.0.1:8877"
```

如开启租户隔离，可再设置：

```powershell
$env:ELITE_E2E_TENANT = "tenant-a"
python "D:\color match\autocolor\run_full_e2e_flow.py" --base-url "http://127.0.0.1:8877"
```

该脚本会串联跑完整流程：
- analyze(dual/batch/ensemble) -> outcome -> history suite
- innovation suite（aging/ink/blend/acceptance/passport/full）
- strategy suite（champion-challenger）
- mvp2 suite（manifest/ccm/matcher/pipeline/sop/sessions）
- lifecycle suite（M08-M45：在 M08-M19 基础上新增 time-stability/process-coupling/appearance/customer/retest/machine/learning/rule-governance/integrated-decision/report + MSA/SPC/状态机/FMEA/卷段治理/回放复算/规则模拟/质量工单流/多角色视图）

### 一键发布门禁（推荐）

```powershell
powershell -ExecutionPolicy Bypass -File "D:\color match\autocolor\run_release_gate.ps1" -ApiHost 127.0.0.1 -Port 8877
```

如开启鉴权 + 租户隔离（并执行角色边界验证）：

```powershell
powershell -ExecutionPolicy Bypass -File "D:\color match\autocolor\run_release_gate.ps1" `
  -ApiHost 127.0.0.1 -Port 8877 `
  -ApiKey "operator-key" -AdminKey "admin-key" `
  -TenantId "tenant-a" -TenantHeaderName "x-tenant-id" `
  -ViewerKey "viewer-key" -OperatorKey "operator-key" -RoleTenant "tenant-a" `
  -RequireRoleBoundary
```

门禁输出：
- 控制台打印每个阶段结果（`quick_check` / `full_e2e` / `auth_probe` / `alert_dead_letter_probe` / `slo_gate` / `executive_brief_probe` / `executive_brief_page_probe` / `role_boundary`）
- 结构化报告：`D:\color match\autocolor\out_e2e_flow\release_gate_result.json`

可选 SLO 强约束（要求必须 healthy）：

```powershell
powershell -ExecutionPolicy Bypass -File "D:\color match\autocolor\run_release_gate.ps1" `
  -ApiHost 127.0.0.1 -Port 8877 `
  -SloAvailabilityTarget 99.5 -SloP95TargetMs 1200 `
  -RequireSloHealthy
```

### 示例：Dual API（含历史闭环）

```powershell
$body = @{
  reference = @{ path = "D:\color match\autocolor\demo_data\sample_reference.png" }
  film = @{ path = "D:\color match\autocolor\demo_data\film_capture.png" }
  profile = "auto"
  grid = "6x8"
  output_dir = "D:\color match\autocolor\out_elite_api_dual"
  html_report = $true
  history = @{
    db_path = "D:\color match\autocolor\quality_history.sqlite"
    line_id = "SMIS-L1"
    product_code = "oak-gray"
    lot_id = "LOT-20260330"
    window = 30
  }
} | ConvertTo-Json -Depth 12

Invoke-RestMethod `
  -Uri "http://127.0.0.1:8877/v1/analyze/dual" `
  -Method Post `
  -ContentType "application/json" `
  -Body $body
```

### 示例：回写客户结果并获取策略调优建议

```powershell
$outcome = @{
  db_path = "D:\color match\autocolor\quality_history.sqlite"
  run_id = 123
  outcome = "complaint_major"
  severity = 0.9
  realized_cost = 420
  customer_rating = 60
  note = "客户反馈色差偏大"
} | ConvertTo-Json -Depth 8

Invoke-RestMethod `
  -Uri "http://127.0.0.1:8877/v1/outcome/record" `
  -Method Post `
  -ContentType "application/json" `
  -Body $outcome

Invoke-RestMethod `
  -Uri "http://127.0.0.1:8877/v1/history/policy-recommendation?db_path=D:\color%20match\autocolor\quality_history.sqlite&line_id=SMIS-L1&product_code=oak-gray&window=200&policy_config=D:\color%20match\autocolor\decision_policy.default.json"
```

### 示例：反事实策略孪生（Counterfactual Twin）

```powershell
Invoke-RestMethod `
  -Uri "http://127.0.0.1:8877/v1/history/counterfactual-twin?db_path=D:\color%20match\autocolor\quality_history.sqlite&line_id=SMIS-L1&product_code=oak-gray&window=260&policy_config=D:\color%20match\autocolor\decision_policy.default.json&max_scenarios=260"
```

返回重点：
- `recommended.customer_first`：客户满意优先策略
- `recommended.balanced`：质量/效率均衡策略
- `recommended.throughput_first`：产能优先策略
- `top_scenarios`：前 N 个候选策略及区间化预测

### 示例：开放算法策略推荐（LinUCB）

```powershell
Invoke-RestMethod `
  -Uri "http://127.0.0.1:8877/v1/history/open-bandit-policy?db_path=D:\color%20match\autocolor\quality_history.sqlite&line_id=SMIS-L1&product_code=oak-gray&window=220&alpha=0.35"
```

返回重点：
- `recommendation.arm`：推荐策略臂（`quality_guard / balanced / throughput_boost`）
- `recommendation.policy_patch`：建议应用的策略补丁
- `arms.*.ucb_score`：每个策略在当前上下文下的 UCB 评分

说明：
- `image/reference/film` 支持 `path` 或 `b64`（data URI 也可）
- 如需返回完整报告内容，可加 `include_report = true`
- `history` 可选；配置后会自动做历史漂移评估并入库
- `with_process_advice` 默认 `true`；可用 `action_rules_config` 指定自定义规则文件
- `with_decision_center` 默认 `true`；可用 `decision_policy_config` 指定自定义决策策略
- 请求支持 `customer_id / customer_tier / customer_tier_config`，可按客户层级自动套策略
- 即使 `include_report = false`，响应也会返回 `process_advice` 摘要字段
- 即使 `include_report = false`，响应也会返回 `decision_center` 摘要字段
- 命中客户分层时，响应会包含 `customer_tier_applied`
- 配置 `history` 后，报告会包含 `policy_recommendation`（闭环调优建议摘要）
- `policy-recommendation` 可返回 `suggested_policy`（在当前策略基础上自动应用 patch）
- `policy-lab` 可返回多候选策略、Pareto 前沿与推荐策略，建议先灰度上线
- `counterfactual-twin` 返回 `customer_first / balanced / throughput_first` 三类建议
- `early-warning` 返回风险等级、驱动因子与 7/30 天客诉概率预测
- `champion-challenger` 返回 `PROMOTE/CANARY/REJECT` 与灰度上线计划
- `single / dual / ensemble` 支持 `with_innovation_engine` 与 `innovation_context`
- 客户容忍度接口支持 `db_path` 持久化（重启后可继续学习）
- 护照接口支持 `db_path` 存储与 `passport_id` 回查验证

## 输出文件

- `elite_color_match_report.json`：主报告
- `batch_summary.json` / `batch_summary.csv`：批量模式汇总
- `ensemble_report.json` / `ensemble_members.csv`：融合判定结果
- `elite_color_match_report.html`：可视化诊断报告（启用 `--html-report`）
- `process_advice`：工艺建议（风险等级 + 命中规则 + 建议动作）
- `decision_center`：决策中心（决策码 + 三方评分 + 预计成本 + 执行动作）
- `policy_recommendation`：策略调优建议（基于闭环结果的阈值调整建议）
- `elite_detection_overlay.png`：单图模式检测框
- `elite_heatmap_board.png` / `elite_heatmap_dual.png`：色差热力图
- `elite_board_warp.png` / `elite_sample_warp.png`：透视校正结果
- `elite_mask_preview.png`：有效像素掩码预览

## 工程建议（上线前）

- 固定光源（D65）+ 固定机位 + 治具定位
- 加入灰卡/ColorChecker，开启每日自动校准
- 先旁路运行 2-4 周，验证误判率后再自动放行
- 对每条产线单独学习阈值，不跨线混用
- 可用 `profile_config.example.json` 为不同线体建立独立阈值

