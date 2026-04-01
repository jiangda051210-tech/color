# SENIA Elite 自动对色系统 — 全栈技术白皮书

**版本**: v2.5.0  
**更新**: 2026-03-31  
**定位**: 技术评审 · 售前演示 · 运维手册 · 研发交接 · 上线门禁

---

## 目录

1. 系统概述与定位
2. 三方价值与 ROI 量化
3. 全链路业务闭环
4. 系统架构（四层八域）
5. 核心算法体系（深度版）
6. 13 模块创新引擎（8基础 + 5新增）
7. 数据架构（代码真值 + 字段定义）
8. API 全景（72 总路由 / 68 业务路由）
9. 前端体系
10. 安全治理与审计
11. 运维可靠性与告警
12. 发布门禁与验收
13. 部署与扩展
14. 故障处理与运维手册（生产级）
15. 竞品对比、售前话术与 PoC 打单模板
16. 已知局限与改进计划（诚实可落地）
17. 下一阶段路线图（可执行 + 可验收）

---

## 1. 系统概述与定位

SENIA Elite 不是一个色差检测脚本，而是一套 **从拍照到放行到学习的无人闭环系统**。

四层能力递进：

- **L1 标准化采集** — 把"人看颜色"变成"机器可测量"
- **L2 稳健测色** — 把"平均色差"升级为"分布 + 风险 + 置信度"
- **L3 决策运营化** — 把"判定结果"升级为"可执行动作 + 三方评分 + 成本预估"
- **L4 闭环自学习** — 把"历史记录"升级为"策略迭代 + 自动调优"

当前实测状态（2026-03-31）：

- 服务代码版本: `2.3.0`
- FastAPI 路由总数: 72（含文档与系统路由）
- 业务 API 路由: 68
- 门禁状态: `system_quick_check` PASSED · `e2e_flow` PASSED · `release_gate` OK
- 默认端口: `8877`

---

## 2. 三方价值与 ROI 量化

### 2.1 客户视角

| 痛点 | Elite 解决方案 | 量化目标 |
|------|--------------|---------|
| 同批次色偏波动 | 7×7 多点采样 + IQR 滤波 + 置信度 | 批内一致性 σ < 0.5 ΔE |
| 不同光源下色差 | 光谱重建 + 同色异谱检测 | 跨光源 ΔE 变异 < 1.0 |
| 产品几年后变色 | 老化预测 + 差异老化 | 保修期内 ΔE 预测偏差 < 15% |
| 投诉无处追溯 | 数字色彩护照 + 防篡改签名 | 100% 可追溯 |

### 2.2 老板视角

| 痛点 | Elite 解决方案 | 量化目标 |
|------|--------------|---------|
| 调色依赖老师傅 | 自动墨量处方 + 分步计划 | 调色时间 30min → 5min |
| 误放行导致客诉 | 决策中心 + 客户分层策略 | 客诉率降低 40-60% |
| 过度拦截影响交期 | 纹理感知色差 + 动态阈值 | 误拦截率降低 30% |
| 策略变更靠拍脑袋 | Policy Lab 仿真 + 灰度上线 | 策略变更风险可控 |

### 2.3 公司视角

| 痛点 | Elite 解决方案 | 量化目标 |
|------|--------------|---------|
| 质量标准不统一 | 可配置阈值体系 + 产线 profile | 跨线标准偏差 < 5% |
| 退货损失不可控 | 批次混拼优化 + 投诉概率预测 | 退货率降低 25-40% |
| 新线上线慢 | 自学习闭环 + LinUCB 策略 | 新线达标周期缩短 50% |
| 无法规模化管理 | 多租户 + 角色权限 + 审计链 | 支持 N 条线并行治理 |

### 2.4 ROI 综合测算

假设单条产线年产 50,000 批，单批均值 200 元：

| 项目 | 降幅 | 年节省 |
|------|------|--------|
| 客诉退货（原 3%→1.5%） | -1.5% | ¥150,000 |
| 过度拦截返工（原 5%→3%） | -2% | ¥200,000 |
| 调色人工（原 2人→0.5人） | -1.5人 | ¥120,000 |
| 加速老化测试减少 | -60% | ¥50,000 |
| **单线年化 ROI** | | **¥520,000** |

### 2.5 ROI 计算口径（可复盘）

为避免“只给结论不给口径”，统一采用下述计算方法：

```
年节省 = Σ(原始损失 - 上线后损失)
总投入 = 一次性改造成本 + 年运维成本
ROI(%) = (年节省 - 年运维成本) / 一次性改造成本 × 100%
回本周期(月) = 一次性改造成本 / ((年节省 - 年运维成本) / 12)
```

建议默认参数（可按客户项目替换）：

- 一次性改造：¥180,000（部署+对接+标定+培训）
- 年运维：¥60,000（维护+巡检+升级）
- 年节省：¥520,000（上表口径）

则：

- 年净收益：`520,000 - 60,000 = 460,000`
- 投入回报率：`460,000 / 180,000 = 255.6%`
- 回本周期：`180,000 / (460,000/12) = 4.7个月`

### 2.6 敏感性分析（老板最关心）

| 场景 | 年节省 | 年净收益 | 回本周期 |
|------|--------|---------|---------|
| 保守（仅实现 60%） | ¥312,000 | ¥252,000 | 8.6 个月 |
| 基准（当前测算） | ¥520,000 | ¥460,000 | 4.7 个月 |
| 激进（实现 130%） | ¥676,000 | ¥616,000 | 3.5 个月 |

结论：即使按保守口径，仍可在 1 年内完成投资回收。

### 2.7 ROI 月度追踪口径（上线后怎么验）

为避免“上线前 ROI 很好看、上线后没人追”，建议将 ROI 拆成 8 个月度指标并固化到经营例会：

| 指标 | 计算方式 | 目标值 | 责任人 |
|------|---------|-------|--------|
| 自动放行率 | `AUTO_RELEASE / 总批次` | `> 70%`（稳态） | 质量经理 |
| 误放行率 | `投诉批次中曾 AUTO_RELEASE 的比例` | `< 1.5%` | 质量经理 |
| 人工复核占比 | `MANUAL_REVIEW / 总批次` | `< 20%` | 产线主管 |
| 重拍率 | `RECAPTURE_REQUIRED / 总批次` | `< 8%` | 工艺工程师 |
| 客诉率 | `投诉批次 / 发货批次` | `< 1.5%` | 客服经理 |
| 单批质控成本 | `(人工+返工+停线+客诉)/总批次` | 持续下降 | 财务BP |
| 平均调色时长 | 每批从检测到达标耗时 | `< 8min` | 工艺工程师 |
| 预测命中率 | 漂移/老化预警后实际发生占比 | `> 70%` | 算法工程师 |

建议每月输出 1 页《ROI 复盘卡》：目标、实际、偏差、纠偏动作（最多 3 条），防止指标漂移。

---

## 3. 全链路业务闭环

```
采集图像 ──→ 对色引擎 ──→ 工艺建议 ──→ 决策中心 ──→ 创新引擎叠加
   │                                          │              │
   │                                          ▼              ▼
   │                                    历史入库        老化预测
   │                                   quality_runs    墨量处方
   │                                          │        混拼优化
   │                                          ▼        客诉概率
   │                                    结果回写        色彩护照
   │                                  quality_outcomes
   │                                          │
   │                                          ▼
   │                                    策略学习
   │                                  Policy Lab
   │                                  Counterfactual
   │                                  Champion-Challenger
   │                                  LinUCB
   │                                          │
   │                                          ▼
   └────────── 反馈闭环 ◄──────────── 管理看板 + 执行简报
```

关键闭环路径：

1. **检测闭环**: 拍照 → 分析 → 判定 → 入库（秒级）
2. **工艺闭环**: 色差 → dL/dC/dH 分解 → 墨量处方 → 验证 → Jacobian 校正（分钟级）
3. **策略闭环**: 历史累积 → 策略建议 → 仿真验证 → 灰度上线 → 效果回写（天/周级）
4. **客户闭环**: 发货 → 客诉回写 → 容忍度学习 → 动态阈值更新（持续）

---

## 4. 系统架构（四层八域）

### 4.1 架构总图

```
┌──────────────────────────────────────────────────────────┐
│                     接入层                                │
│  elite_api.py (FastAPI) · elite_web_console.py (前端)    │
│  鉴权 · 限流 · 审计 · 租户隔离                            │
├──────────────────────────────────────────────────────────┤
│                     业务编排层                             │
│  对色执行域 · 创新域 · 历史分析域 · 系统治理域             │
├──────────────────────────────────────────────────────────┤
│                     核心引擎层                             │
│  ┌─────────┐ ┌───────────┐ ┌────────────┐ ┌───────────┐ │
│  │视觉对色  │ │决策与学习  │ │创新8模块    │ │运维治理    │ │
│  │color_    │ │decision_  │ │innovation_ │ │runtime/   │ │
│  │match     │ │center/    │ │engine      │ │slo/alert  │ │
│  │          │ │policy_lab/│ │            │ │           │ │
│  │          │ │bandit/    │ │            │ │           │ │
│  │          │ │rollout    │ │            │ │           │ │
│  └─────────┘ └───────────┘ └────────────┘ └───────────┘ │
├──────────────────────────────────────────────────────────┤
│                     数据层                                │
│  quality_history.sqlite · innovation_state.sqlite        │
│  logs/elite_audit.jsonl · 配置 JSON 文件集                │
└──────────────────────────────────────────────────────────┘
```

### 4.2 文件职责清单

| 文件 | 职责 | 行数级别 |
|------|------|---------|
| `elite_api.py` | FastAPI 路由编排、中间件、生命周期 | 主干 |
| `elite_color_match.py` | 视觉对色核心（检测/校正/采样/计算） | 核心 |
| `elite_decision_center.py` | 风险评估 + 四档决策 + 三方评分 + 成本 | 核心 |
| `elite_process_advisor.py` | 规则引擎：dL/dC/dH → 工艺动作 | 核心 |
| `elite_innovation_engine.py` | 13 模块统一创新引擎（8基础+5新增） | 核心 |
| `elite_innovation_state.py` | 创新模块状态持久化(SQLite) | 支撑 |
| `elite_quality_history.py` | quality_runs/outcomes 读写 + 漂移 | 支撑 |
| `elite_customer_tier.py` | 客户分层策略补丁 | 策略 |
| `elite_policy_lab.py` | 多策略仿真 + Pareto | 策略 |
| `elite_counterfactual.py` | GBR + Conformal 反事实 | 策略 |
| `elite_rollout_engine.py` | Champion-Challenger 灰度 | 策略 |
| `elite_open_bandit.py` | LinUCB 上下文赌博机 | 策略 |
| `elite_runtime.py` | 运行时配置中心 (env → 结构化) | 运维 |
| `elite_web_console.py` | Web 前端模板 (控制台/驾驶舱/简报) | 前端 |

### 4.3 配置文件体系

| 文件 | 用途 | 修改频率 |
|------|------|---------|
| `decision_policy.default.json` | 决策阈值 + 三方权重 + 成本模型 | 低（上线前调好） |
| `process_action_rules.json` | 工艺建议规则表达式 | 中（按产线定制） |
| `customer_tier_policy.default.json` | 客户分层定义 + 策略补丁 | 中（客户变更时） |
| `profile_config.example.json` | 产线/材质阈值覆盖 | 高（新线上线时） |
| `elite_runtime.env.example` | 运行时环境变量模板 | 低 |

---

## 5. 核心算法体系（深度版）

### 5.1 视觉对色引擎

**阶段 1 — 几何检测与区域定位**

输入为原始拍摄图像，目标是定位大板和小样的有效区域。

- 轮廓检测: Canny 边缘 → findContours → 面积筛选 → 按面积排序取 top-2（大板/小样）
- ArUco 定位: 检测指定 ID 的 ArUco 标记 → 四角坐标 → 透视校正目标区域
- 手动兜底: `--board-roi` / `--sample-roi` 或 `--board-quad` / `--sample-quad` 四点坐标
- 优先级: ArUco > 自动轮廓 > 手动 ROI

**阶段 2 — 透视校正与归一化**

检测到的区域通过 `cv2.getPerspectiveTransform` + `cv2.warpPerspective` 校正为正面视图，消除拍摄角度带来的形变。校正后图像统一缩放到标准分辨率以保证采样网格密度一致。

**阶段 3 — 光照与纹理稳健化**

这一阶段至关重要，直接决定测色精度：

- **Gray-world 白平衡**: 假设场景平均反射率为灰色，计算 R/G/B 通道均值比值作为校正因子。适用于大部分室内场景，但对强色偏背景（如全红墙面前拍摄）可能失效。
- **Shading Correction（光照场校正）**: 用大核高斯模糊提取低频光照分量，将原图除以该分量后重归一化，消除渐变阴影和不均匀照明。这一步对产线侧光场景效果显著。
- **纹理抑制**: 对木纹/石纹材质启用双边滤波（`cv2.bilateralFilter`），在保持边缘的前提下平滑纹理细节，避免纹理高频信号污染色差计算。
- **无效像素掩码**: 自动检测并排除手写文字（高对比度小区域）、贴纸（色相突变区域）、高光反射（亮度 > 阈值）。使用形态学运算和颜色空间联合判定。

**阶段 4 — 网格采样与统计**

将校正后的有效区域按 N×M 网格均匀采样（默认 6×8 = 48 个点）。每个采样点取中心 R×R 像素块的均值 RGB，转换为 CIELab 后计算 CIEDE2000 色差。

统计输出：
- 位置统计: avg / p50 / p75 / p90 / p95 / p99 / max
- 分量分解: dL* (明度) / dC* (彩度) / dH* (色相)
- 质量旗标: `low_contrast` / `uneven_lighting` / `high_texture` / `low_coverage` / `blur_detected`
- 捕获指导: 当旗标触发时自动生成重拍建议

**阶段 5 — 置信度评估**

综合三个维度给出 0~1 的置信度分数:

```
confidence = 0.40 × geometry_score
           + 0.32 × lighting_score
           + 0.28 × coverage_score
```

- `geometry_score`: 检测到的区域面积比例、矩形度、透视畸变程度
- `lighting_score`: 光照均匀性（区域内亮度标准差的倒数归一化）、白平衡偏移量
- `coverage_score`: 有效像素占比（排除掩码后的比例）

**置信度低于 0.6 时自动触发 `RECAPTURE_REQUIRED` 决策。** 这是防止垃圾数据污染历史库的第一道防线。

### 5.2 CIEDE2000 算法要点

采用 CIE 于 2000 年发布的色差公式，相比 CIE76 (简单欧氏距离) 和 CIE94，CIEDE2000 引入了:

- **明度权重函数 SL**: 在 L*=50 附近最敏感，两端衰减
- **彩度权重函数 SC**: 高彩度区域的色差容忍度更高
- **色相权重函数 SH**: 考虑色相角度对感知的非线性影响
- **交互项 RT**: 蓝色区域(h≈275°)的彩度-色相耦合补偿

这使得 CIEDE2000 在感知一致性上显著优于前代公式。我们的实现严格遵循 CIE 技术报告 142-2001 的完整公式，包括 G 因子、T 因子和 RT 旋转项。

### 5.3 决策中心算法

决策中心接收对色引擎的量化结果，输出四档决策码和三方评分。

**风险评估模型:**

```
risk = max(
    avg_de / target_avg,      # 均值达标率
    p95_de / target_p95,      # 尾部达标率
    max_de / target_max,      # 极值达标率
) × (2 - confidence)          # 低置信度放大风险
  + flag_penalty              # 质量旗标惩罚
```

**决策映射:**

| risk 区间 | 决策码 | 含义 |
|-----------|--------|------|
| < 0.8 | `AUTO_RELEASE` | 自动放行 |
| 0.8 ~ 1.2 | `MANUAL_REVIEW` | 转人工复核 |
| 1.2 ~ 2.0 | `RECAPTURE_REQUIRED` | 要求重拍 |
| ≥ 2.0 | `HOLD_AND_ESCALATE` | 停线上报 |

**三方评分（0-100）:**

```
customer_score = 100 - 30 × (avg_ratio - 1).clip(0) - 20 × flag_count
boss_score     = w_quality × quality_metric + w_throughput × (1 - reject_rate) + w_cost × (1 - cost_ratio)
company_score  = 0.4 × customer_score + 0.3 × boss_score + 0.3 × compliance_score
```

权重可在 `decision_policy.default.json` 中按产线定制。

**成本估计模型:**

| 成本项 | 计算方式 | 默认参数 |
|--------|---------|---------|
| 人工复核 | `base_cost × duration_min` | ¥15/次 |
| 重拍成本 | `line_stop_min × line_cost_per_min` | ¥50/次 |
| 停线上报 | `escalation_time × line_cost` | ¥500/次 |
| 逃逸损失 | `escape_prob × avg_claim_cost` | 按历史统计 |

### 5.4 闭环学习算法集

**Policy Lab（策略实验室）:**

在历史 quality_runs 数据上离线仿真多个候选策略补丁，同时评估三个目标: 逃逸率（越低越好）、自动放行率（越高越好）、预计成本（越低越好）。用 Pareto 前沿筛选非支配解，推荐 top-3 候选策略。

**Counterfactual Twin（反事实孪生）:**

用 GradientBoosting 拟合 `(策略参数, 检测特征) → outcome` 的映射，再用 Split Conformal Prediction 给出区间化预测。输出三类推荐策略: `customer_first` / `balanced` / `throughput_first`。

**Champion-Challenger（冠军-挑战者）:**

在历史数据上同时评估当前策略（冠军）和候选策略（挑战者）的表现差异，自动给出 `PROMOTE`（直接切换）/ `CANARY`（小流量灰度）/ `REJECT`（放弃挑战者）的建议，并生成分阶段灰度计划。

**LinUCB（上下文赌博机）:**

将每次检测的 `[avg_ratio, p95_ratio, confidence, risk, pass]` 作为上下文特征向量，三个策略臂 `quality_guard / balanced / throughput_boost` 各维护一个岭回归模型。用 UCB 公式平衡探索与利用，在线推荐当前场景的最优策略。alpha 参数控制探索强度。

### 5.5 关键参数与调参顺序（工程可执行）

| 参数 | 默认值 | 所在模块 | 调整方向 |
|------|--------|---------|---------|
| `grid` | `6x8` | 对色采样 | 纹理复杂场景可升到 `7x9`；算力紧张降到 `5x7` |
| `disable_shading_correction` | `false` | 对色预处理 | 若固定光场极稳定可关闭以提速 |
| `auto_release_min_confidence` | `0.82` | 决策中心 | 客诉高时上调（更严格），吞吐压力大时微降 |
| `manual_review_min_confidence` | `0.68` | 决策中心 | 人工资源紧张时可小幅上调 |
| `recapture_max_confidence` | `0.62` | 决策中心 | 采集质量差时建议不改，先优化工位 |
| `ELITE_RATE_LIMIT_RPM` | `0`(关闭) | 运行时 | 生产建议按租户能力配置为 300~1200 |
| `ELITE_OPS_SUMMARY_CACHE_TTL_SEC` | `15` | 运维接口 | 监控频繁时可调高降低查询压力 |

调参建议顺序（避免互相干扰）：

1. 先稳采集：光源/机位/遮挡规范化，再观察 `quality_flags` 分布。
2. 再调阈值：只动 `decision_policy`，每次改动幅度不超过 `±0.01 ~ ±0.03`。
3. 再开学习：开启闭环回写后再使用 policy-lab/counterfactual 建议。
4. 最后做自动化：确认 release gate 连续 7 天为绿再扩大 AUTO_RELEASE 占比。

### 5.6 算法边界条件（评审必答）

- 视觉方法对极端镜面反光敏感：需偏振方案或多角度补拍。
- 同色异谱模块默认矩阵未校准时，结果用于“预警”而非“硬拦截”。
- 统计分位数在样本极少时不稳定：低于最小有效像素时应强制重拍。
- 学习模块前期冷启动数据少：前 2~4 周建议采用 conservative policy。

### 5.7 算法输入输出契约（评审与联调最常问）

| 模块 | 必填输入 | 核心输出 | 失败码/降级 |
|------|---------|---------|------------|
| 视觉对色 | `image/reference` 或 `sample/film` | `avg_de,p95_de,max_de,dL,dC,dH,confidence` | 4xx（入参错误）/低置信度触发重拍 |
| 决策中心 | `avg/p95/max/confidence + flags` | `decision_code,risk,estimated_cost,三方评分` | 无硬失败，缺字段时采用保守阈值 |
| 光谱重建 | `rgb_sample,rgb_film` 或图像 | `MI,per_illuminant,worst_illuminant` | 返回 `innovation_engine.spectral.error` |
| 漂移预测 | `line_id,product_code,window` | `batches_remaining,urgency,changepoint` | 数据不足返回 `insufficient_history` |
| 墨量处方 | `dL,dC,dH,confidence` | `adjustments,new_recipe,predicted_residual` | 若约束冲突返回“建议两步调色” |
| 客户学习 | `customer_id,delta_e,complained` | `threshold_50,safe_threshold_10,complaint_prob` | 新客户返回 cold-start 默认阈值 |

联调建议：

1. 先联通主流程（对色+决策）再加创新模块，避免同时定位两类问题。
2. 每个模块先用 1 组“金样例”确认字段语义，再扩到真实数据回放。
3. 所有接口都保留 `request_id`，用于审计链路与问题追踪。

---

## 6. 13 模块创新引擎（8基础 + 5新增）

所有创新模块统一由 `elite_innovation_engine.py` 中的 `EliteInnovationEngine` 类管理，可单独调用也可通过 `/v1/analyze/full-innovation` 一次叠加。

### 6.1 光谱重建 + 同色异谱检测 (`SpectralReconstructor`)

**解决的问题**: RGB 相机只有 3 个通道，两种不同光谱分布的材料可能在 D65 下产生相同 RGB（同色异谱）。换到 TL84 商场灯下色差暴露 → 客诉。传统方案需要 10 万+的分光光度计。

**算法原理**: Wiener Estimation，用 31×3 矩阵将 RGB 映射到 400-700nm（每 10nm）的 31 通道光谱反射率。默认矩阵基于 Munsell 训练集近似，生产环境通过 ColorChecker 实拍数据校准。

**同色异谱指数 MI**: 在 D65/A/TL84/LED_4000K 四个光源下分别计算 ΔE，取最大差值。MI > 1.5 标记为高风险。

**接口**: `POST /v1/analyze/spectral`

**关键参数**: `image`, `reference` (或 `rgb_sample`, `rgb_film`)

**输出**: `metamerism_index`, `per_illuminant: {D65: ΔE, TL84: ΔE, ...}`, `worst_illuminant`, `risk_level`, `recommendation`

**已知局限**: 默认 Wiener 矩阵精度有限（RMSE 约 5-8%），需要通过 ColorChecker 校准提升到 2-3%。对高饱和度色彩（如纯红/纯蓝）重建精度下降。

### 6.2 纹理感知色差 (`TextureAwareDeltaE`)

**解决的问题**: 标准 ΔE2000 假设颜色在均匀平面上。但深木纹上 ΔE=2.5 人眼看不出（掩蔽效应），素色板上 ΔE=1.8 却一目了然。行业用统一阈值导致木纹误拦截、素色漏放行。

**算法原理**:

```
texture_adjusted_ΔE = standard_ΔE × masking_factor × texture_penalty
```

- `masking_factor`: 由纹理亮度标准差通过 Sigmoid 映射到 [0.5, 1.0]。纹理越复杂 → 值越小 → 色差感知越弱。材质类型提供额外修正系数（solid=1.0, wood=0.85, stone=0.80）。
- `texture_penalty`: 当两个表面纹理不一致时（基于 Gabor 能量向量余弦相似度），视觉差异被放大。

**接口**: `POST /v1/analyze/texture-aware`

**关键参数**: `standard_de`, `sample_texture_std`, `film_texture_std`, `texture_similarity`, `material_type`

**输出**: `texture_adjusted_deltaE`, `masking_factor`, `threshold_suggestion` (含动态阈值建议), `interpretation`

**效果**: 深木纹（complexity=20+）可将有效 ΔE 降低 30-45%，直接提升吞吐。素色（complexity<5）保持原始 ΔE，不放松标准。

### 6.3 漂移预测 (`DriftPredictor`)

**解决的问题**: 现有系统只能检测"已经飘了"，等发现时可能已生产数十批不合格品。

**算法原理**: 在线贝叶斯线性回归（递推 Kalman 更新），对 ΔE 时间序列拟合 `y = β0 + β1 × t`，预测 `threshold - β0) / β1` 得到剩余批次数（Time-to-Breach）。后验方差给出 90% 置信区间。

叠加 CUSUM 变点检测：在均值偏移超过累积阈值时触发突变告警，比简单趋势更快捕捉工艺异常。

**接口**: `GET /v1/history/drift-prediction`

**关键参数**: `db_path`, `line_id`, `product_code`, `window`, `threshold`

**输出**: `breach_predicted`, `batches_remaining`, `confidence_interval_90`, `slope_per_batch`, `urgency`, `changepoint`, `forecast_next_5`, `recommendation`

**紧急度分级**: critical (<5批) / high (<15批) / medium (<40批) / low (>40批)

### 6.4 色彩老化预测 (`ColorAgingPredictor`)

**解决的问题**: 客户使用数年后投诉变色。传统只能做加速老化测试（数月周期、高成本）。更关键的是：样板（三聚氰胺）和彩膜（PVC）材质不同，老化速率不同，出厂 ΔE 合格但 5 年后飘出规格。

**算法原理**: 基于材质老化参数（每年 dL/da/db 变化率 + 彩度衰减率）× 环境因子（UV/湿度/温度）× 非线性时间函数 `t_eff = ln(1+yr)/ln(2) × yr`。

支持 5 种材质: PVC膜 / PET膜 / 三聚氰胺 / HPL / UV涂层
支持 5 种环境: 室内普通 / 靠窗 / 厨卫 / 室外有遮挡 / 室外直晒

**差异老化（独创）**: 分别预测样板和彩膜在相同环境下的老化轨迹，计算各时间点的 ΔE 变化，找出色差开始超标的年份。

**接口**: `POST /v1/predict/aging`, `POST /v1/predict/differential-aging`

**输出**: 1/3/5/10/15 年预测 Lab + ΔE + 主要变化 + 视觉等级 + 保修风险评估

**已知局限**: 老化参数基于行业平均值拟合，特定配方（如含荧光增白剂）可能偏差较大。建议在积累实测老化数据后校准参数。

### 6.5 自动墨量修正处方 (`InkRecipeCorrector`)

**解决的问题**: 操作工看到 "ΔL=+1.2" 不知道怎么调墨水。经验丰富的调色师稀缺且不稳定。

**算法原理**: 维护墨水-色差 Jacobian 矩阵 J (3×4)，描述 CMYK 各通道单位变化对 dL/da/db 的影响。从目标色差反向计算修正量:

```
Δink = J^T × (J × J^T + λI)^-1 × Δlab_target
```

正则化参数 λ 与检测置信度负相关（低置信度 → 强正则化 → 保守调整）。安全约束: 单通道最大 5%，总量最大 10%。大调整自动拆分为 60%+40% 两步。

**自学习**: 每次调整的 before/after 结果写入 `ink_corrections` 表，可用于在线校正 Jacobian 矩阵。

**接口**: `POST /v1/correct/ink-recipe`

**关键参数**: `dL`, `dC`, `dH`, `current_recipe` (可选), `confidence`

**输出**: `adjustments`, `adjustments_description` (人可读), `new_recipe`, `predicted_residual_deltaE`, `safety_check`, `step_plan`

### 6.6 批次混拼优化 (`BatchBlendOptimizer`)

**解决的问题**: 多批次板材颜色略有差异，随机发货导致客户收到色差大的板材。

**算法原理**: 计算所有批次间的 ΔE 距离矩阵 → 按 Lab 主成分排序 → 贪心均匀分组使组内色差最小 → 若有客户分层信息则 VIP 分配到色差最小的组。

**接口**: `POST /v1/optimize/batch-blend`

**关键参数**: `batches` (含 batch_id, lab, quantity), `n_groups`, `customer_tiers`

**输出**: `groups` (每组的批次列表 + 组内最大/平均 ΔE + 客户分配), `improvement_percent`, `de_matrix`

### 6.7 客户容忍度自学习 (`CustomerAcceptanceLearner`)

**解决的问题**: 行业标准 ΔE≤3.0 是一刀切，但客户 A 在 ΔE=2.0 就投诉，客户 B 到 ΔE=4.0 都不在意。

**算法原理**: 在线 Logistic Regression（SGD 更新），为每个客户学习 `P(投诉|ΔE)` 曲线。核心输出:

- **50% 投诉阈值**: `sigmoid(θ₀ + θ₁ × ΔE) = 0.5 → ΔE = -θ₀/θ₁`（客户真实容忍度）
- **安全阈值**: `P(投诉)=10%` 对应的 ΔE（推荐放行标准）
- **动态阈值**: 给定目标投诉率反推阈值

**状态持久化**: 学习事件存入 `innovation_customer_acceptance_events`，模型快照存入 `innovation_customer_acceptance_models`。

**接口**:
- `POST /v1/customer/acceptance-record` — 记录发货结果
- `GET /v1/customer/acceptance-profile` — 客户画像
- `GET /v1/customer/complaint-probability` — 投诉概率预测
- `GET /v1/customer/dynamic-threshold` — 动态阈值建议

### 6.8 数字色彩护照 (`ColorPassport`)

**解决的问题**: 客户收货后发现色差，无法确定是生产时就有还是运输/存储导致。

**方案**: 每批次生成包含 Lab 指纹 + 检测条件 + 决策链 + SHA256 防篡改签名的数字护照。客户端可用新测量值对比验证。

**接口**: `POST /v1/passport/generate`, `POST /v1/passport/verify`

**验证结果**: `perfect` (ΔE<0.5) / `acceptable` (ΔE<1.5) / `drifted` (ΔE≥1.5) / `tampered` (签名不匹配)

### 6.9 创新模块接入逻辑（你最关心的“怎么调”）

统一入口有两种：

1. **随主分析叠加**：`/v1/analyze/single|dual|ensemble` 请求体设置 `with_innovation_engine=true`。  
2. **独立调用**：直接调用对应创新接口（aging/ink/blend/passport 等）。

主分析叠加时，数据流如下：

```
analyze_* 结果(report)
  └─ _report_to_innovation_input()
      └─ EliteInnovationEngine.full_analysis(run_result, innovation_context)
          └─ report["innovation_engine"] 写回
```

`innovation_context` 建议字段：

| 字段 | 用途 | 典型值 |
|------|------|--------|
| `customer_id` | 客户投诉概率/动态阈值 | `CUST-001` |
| `material` | 老化预测材质 | `pvc_film` |
| `sample_material` | 差异老化（样板） | `melamine` |
| `film_material` | 差异老化（彩膜） | `pvc_film` |
| `environment` | 环境工况 | `indoor_window` |
| `current_ink_recipe` | 墨量处方 | `{"C":42,"M":31,"Y":26,"K":7}` |

### 6.10 创新模块失败降级策略（生产必须有）

为保证主流程稳定，创新模块异常不阻断主分析，采用“模块级降级”：

- 单模块异常：在 `innovation_engine` 对应子项返回 `{"error": "..."}`
- 主分析仍返回 200，并保留 `pass/confidence/decision_center/process_advice`
- 仅当主分析核心失败（图像/参数非法）才返回 4xx/5xx

上线建议：

1. 首周只做旁路观测，不参与硬决策。
2. 第二周启用低风险模块（complaint-probability / passport verify）。
3. 第三周启用处方与老化建议，但仍人工确认。
4. 连续稳定后再将建议纳入 SOP 固化。

### 6.11 创新编排模板（建议直接复用）

推荐按“触发条件”编排，避免所有模块每次全量运行造成算力浪费：

| 场景触发 | 必跑模块 | 可选模块 | 预期收益 |
|---------|---------|---------|---------|
| 新花色首单 | `spectral + texture-aware + passport` | `aging` | 首单风险前移 |
| 连续 3 批接近阈值 | `drift-prediction + decision-center` | `ink-recipe` | 提前避免超标停线 |
| VIP 客户发货前 | `batch-blend + acceptance-profile` | `dynamic-threshold` | 关键客户客诉下降 |
| 客诉复盘 | `passport-verify + complaint-probability` | `counterfactual` | 快速定位责任与纠偏 |
| 季度策略复盘 | `policy-lab + champion-challenger` | `linucb` | 策略可解释迭代 |

推荐执行顺序（可做成工作流）：

1. 主分析拿到 `avg/p95/max/confidence`。
2. 根据规则选择创新模块集合（不是每次全开）。
3. 输出统一 `innovation_summary`（风险、建议、可执行动作）。
4. 写回 `quality_runs + quality_outcomes`，用于下一轮学习。

### 6.12 v3 新增 5 模块（已上线）

| 模块 | 目标 | 核心接口 | 输出要点 |
|------|------|---------|---------|
| `SPCEngine` | 过程稳定性与能力评估 | `POST /v1/quality/spc/analyze` `GET /v1/quality/spc/from-history` | `Cp/Cpk`, OOC 点, 控制状态 |
| `MultiObserverSimulator` | 终端人群视觉差异风险 | `POST /v1/analyze/multi-observer` | 最敏感人群、人口风险、加权ΔE |
| `ShiftReportGenerator` | 班次质量经营化汇总 | `POST /v1/report/shift/generate` `GET /v1/report/shift/from-history` | 通过率、异常点、班报结论 |
| `SupplierScorecard` | 供应商一致性治理 | `POST /v1/supplier/record` `GET /v1/supplier/scorecard` | 评分、等级、趋势、建议 |
| `ColorStandardLibrary` | 标准色版本化与比对 | `POST /v1/standards/register` `POST /v1/standards/compare` `GET /v1/standards/*` | 标准版本、实测偏差、版本漂移 |

Web 入口：`GET /v1/web/innovation-v3`

---

## 7. 数据架构（代码真值 + 交接可用）

### 7.1 质量闭环库（`quality_history.sqlite`）

#### 表 `quality_runs`（真实字段）

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | INTEGER PK | 自增主键 |
| `created_at` | TEXT | 记录时间（`YYYY-MM-DD HH:MM:SS`） |
| `mode` | TEXT | `single_image / dual_image / ensemble_single` 等 |
| `profile` | TEXT | 使用的材质档位 |
| `line_id` | TEXT | 产线标识（可空） |
| `product_code` | TEXT | 产品编码（可空） |
| `lot_id` | TEXT | 批次号（可空） |
| `pass` | INTEGER | 0/1 合格标记 |
| `confidence` | REAL | 置信度 |
| `avg_de` | REAL | 均值色差 |
| `p95_de` | REAL | P95 色差 |
| `max_de` | REAL | 最大色差 |
| `dL` | REAL | 明度分量 |
| `dC` | REAL | 彩度分量 |
| `dH` | REAL | 色相分量 |
| `report_path` | TEXT | 报告路径 |
| `decision_code` | TEXT | 决策码 |
| `decision_priority` | TEXT | 决策优先级 |
| `decision_risk` | REAL | 风险概率 |
| `estimated_cost` | REAL | 预计损失 |
| `customer_score` | REAL | 客户评分 |
| `boss_score` | REAL | 老板评分 |
| `company_score` | REAL | 公司评分 |

索引（代码已建）：

- `idx_quality_runs_line_product_time(line_id, product_code, created_at)`

#### 表 `quality_outcomes`（真实字段）

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | INTEGER PK | 自增主键 |
| `created_at` | TEXT | 回写时间 |
| `run_id` | INTEGER | 对应 `quality_runs.id`（可空） |
| `report_path` | TEXT | 关联报告路径 |
| `line_id` | TEXT | 产线标识 |
| `product_code` | TEXT | 产品编码 |
| `lot_id` | TEXT | 批次号 |
| `decision_code` | TEXT | 当时决策码 |
| `predicted_risk` | REAL | 当时预测风险 |
| `outcome` | TEXT | `accepted/complaint_minor/complaint_major/return/rework/pending` |
| `severity` | REAL | 严重度 |
| `realized_cost` | REAL | 实际损失 |
| `customer_rating` | REAL | 客户评分 |
| `note` | TEXT | 备注 |

索引（代码已建）：

- `idx_quality_outcomes_line_product_time(line_id, product_code, created_at)`
- `idx_quality_outcomes_run_id(run_id)`

### 7.2 创新状态库（`innovation_state.sqlite`）

#### 表 `innovation_customer_acceptance_events`

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | INTEGER PK | 自增 |
| `created_at` | TEXT | 记录时间 |
| `customer_id` | TEXT | 客户编号 |
| `delta_e` | REAL | 当次色差 |
| `complained` | INTEGER | 0/1 是否投诉 |
| `extra_json` | TEXT | 扩展信息 |

#### 表 `innovation_customer_acceptance_models`

| 字段 | 类型 | 说明 |
|------|------|------|
| `customer_id` | TEXT PK | 客户编号 |
| `updated_at` | TEXT | 模型更新时间 |
| `total_shipments` | INTEGER | 发货总次数 |
| `total_complaints` | INTEGER | 投诉总次数 |
| `complaint_rate` | REAL | 投诉率 |
| `learned_threshold_50` | REAL | 50% 投诉阈值 |
| `safe_threshold_10` | REAL | 10% 投诉阈值 |
| `sensitivity` | TEXT | strict/normal/tolerant |
| `theta_json` | TEXT | 模型参数 |
| `profile_json` | TEXT | 画像快照 |

#### 表 `innovation_color_passports`

| 字段 | 类型 | 说明 |
|------|------|------|
| `passport_id` | TEXT PK | 护照ID |
| `lot_id` | TEXT | 批次号 |
| `created_at` | TEXT | 创建时间 |
| `verification_hash` | TEXT | 防篡改签名 |
| `payload_json` | TEXT | 完整护照载荷 |

#### 表 `innovation_supplier_records`

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | INTEGER PK | 自增 |
| `created_at` | TEXT | 入库时间 |
| `supplier_id` | TEXT | 供应商编号 |
| `delta_e` | REAL | 当次色差 |
| `product` | TEXT | 产品编码 |
| `passed` | INTEGER | 0/1 是否通过 |
| `ts` | TEXT | 业务时间戳 |

#### 表 `innovation_color_standards`

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | INTEGER PK | 自增 |
| `code` | TEXT | 标准色编码 |
| `version` | INTEGER | 版本号（同 code 递增） |
| `created_at` | TEXT | 创建时间 |
| `source` | TEXT | 来源（manual/e2e/colorimeter...） |
| `notes` | TEXT | 备注 |
| `lab_json` | TEXT | 标准 Lab 值 |

### 7.3 数据写入责任矩阵（交接重点）

| 入口 | 写入表 | 说明 |
|------|--------|------|
| `/v1/analyze/*` + `history` | `quality_runs` | 主检测结果入库 |
| `/v1/outcome/record` | `quality_outcomes` | 业务真实结果回写 |
| `/v1/customer/acceptance-record` | `innovation_customer_acceptance_events` + models | 客户容忍度学习 |
| `/v1/passport/generate`（带 `db_path`） | `innovation_color_passports` | 护照持久化 |
| `/v1/supplier/record` | `innovation_supplier_records` | 供应商质量事件 |
| `/v1/standards/register` | `innovation_color_standards` | 标准色版本登记 |

### 7.4 规划字段（未落地，避免误解）

以下字段在本文件中可用于设计讨论，但当前代码表结构未落地：

- `quality_runs.customer_id`
- `quality_runs.customer_tier`
- `quality_runs.flags_json`
- `quality_runs.extra_json`

### 7.5 数据治理规范（交接与审计必备）

| 主题 | 规范 |
|------|------|
| 主键策略 | 业务表统一整数自增或业务唯一键（如 `passport_id`），禁止复用业务字段作主键 |
| 时间字段 | 统一 UTC 存储，接口返回可按租户时区渲染 |
| 枚举字段 | `decision_code/outcome/sensitivity` 采用白名单校验，避免脏值 |
| 写入幂等 | 回写接口建议携带 `idempotency_key`，防止重试重复入库 |
| 数据保留 | 明细保留 24 个月，聚合报表长期保留；超期归档至冷存储 |
| 备份策略 | 每日增量 + 每周全量；每月执行一次恢复演练并留记录 |
| 审计追踪 | 关键写入必须带 `request_id + operator + tenant` |

建议新增两个定时巡检 SQL（每日凌晨）：

```sql
-- 1) 查 run/outcome 孤儿记录
SELECT o.id
FROM quality_outcomes o
LEFT JOIN quality_runs r ON r.id = o.run_id
WHERE o.run_id IS NOT NULL AND r.id IS NULL;

-- 2) 查异常枚举值
SELECT decision_code, COUNT(*)
FROM quality_runs
GROUP BY decision_code
HAVING decision_code NOT IN ('AUTO_RELEASE','MANUAL_REVIEW','RECAPTURE_REQUIRED','HOLD_AND_ESCALATE');
```

---

## 8. API 全景（72 总路由 / 68 业务路由）

说明：

- `72` 为 FastAPI 运行时总路由（含 docs/openapi/redoc 等系统路由）。
- `68` 为业务路由（去除 docs/openapi/redoc 系统路由后统计）。
- 下表“最小角色”口径按“开启 API Key 鉴权后”计算；未开启鉴权时均可访问。

### 8.1 权限模型（按前缀）

| 前缀 | 最小角色 | 备注 |
|------|---------|------|
| `/health` `/ready` `/` | public | 公共探针与首页 |
| `/v1/system/alert-*` `/v1/system/audit-tail` `/v1/system/self-test` | admin | 高风险治理接口 |
| `/v1/system/ops-summary` `/v1/system/executive-brief` `/v1/system/metrics` `/v1/system/slo` `/v1/system/release-gate-report` | operator | 经营与运维中枢 |
| `/v1/analyze/*` `/v1/web/analyze/*` `/v1/outcome/record` `/v1/strategy/*` `/v1/predict/*` `/v1/correct/*` `/v1/optimize/*` `/v1/passport/generate` | operator | 生产执行与策略变更 |
| 其余 `/v1/*` 读接口 | viewer | 读权限即可 |

特殊说明：

- `/v1/web/executive-dashboard` 在代码中列为 public path（便于老板查看大盘）。

### 8.2 系统治理域（关键接口）

| 路由 | 方法 | 最小角色 | 返回类型 | 说明 |
|------|------|---------|---------|------|
| `/v1/system/status` | GET | viewer | JSON | 版本、路径、缓存、路由数 |
| `/v1/system/metrics` | GET | operator | JSON | 请求统计与热点路径（非 Prometheus 文本） |
| `/v1/system/slo` | GET | operator | JSON | 可用性/时延/SLO 状态 |
| `/v1/system/auth-info` | GET | viewer | JSON | 鉴权开关、当前角色、限流配置 |
| `/v1/system/tenant-info` | GET | viewer | JSON | 租户隔离状态与上下文 |
| `/v1/system/alert-test` | POST | admin | JSON | 告警链路联调 |
| `/v1/system/alert-dead-letter` | GET | admin | JSON | 死信队列查看 |
| `/v1/system/alert-replay` | POST | admin | JSON | 死信重放 |
| `/v1/system/audit-tail` | GET | admin | JSON | 审计日志尾部 |
| `/v1/system/self-test` | GET | admin | JSON | 依赖可用性自检 |

### 8.3 生产执行域

| 路由 | 方法 | 最小角色 | 说明 |
|------|------|---------|------|
| `/v1/analyze/single` | POST | operator | 单图对色 |
| `/v1/analyze/dual` | POST | operator | 样板-彩膜对色 |
| `/v1/analyze/batch` | POST | operator | 批量跑批 |
| `/v1/analyze/ensemble` | POST | operator | 多图融合判定 |
| `/v1/web/analyze/single-upload` | POST | operator | Web 单图上传 |
| `/v1/web/analyze/dual-upload` | POST | operator | Web 双图上传 |
| `/v1/outcome/record` | POST | operator | 闭环结果回写 |

### 8.4 创新与学习域

| 路由 | 方法 | 最小角色 | 说明 |
|------|------|---------|------|
| `/v1/analyze/spectral` | POST | operator | 光谱重建/同色异谱 |
| `/v1/analyze/texture-aware` | POST | operator | 纹理感知色差 |
| `/v1/analyze/multi-observer` | POST | operator | 多观察者视觉差异仿真 |
| `/v1/analyze/full-innovation` | POST | operator | 创新全量叠加 |
| `/v1/history/drift-prediction` | GET | viewer | 漂移与超标预测 |
| `/v1/predict/aging` | POST | operator | 老化预测 |
| `/v1/predict/differential-aging` | POST | operator | 差异老化 |
| `/v1/correct/ink-recipe` | POST | operator | 墨量处方 |
| `/v1/optimize/batch-blend` | POST | operator | 混拼优化 |
| `/v1/customer/acceptance-record` | POST | operator | 客户学习写入 |
| `/v1/customer/acceptance-profile` | GET | viewer | 容忍度画像 |
| `/v1/customer/complaint-probability` | GET | viewer | 投诉概率 |
| `/v1/customer/dynamic-threshold` | GET | viewer | 动态阈值 |
| `/v1/passport/generate` | POST | operator | 护照生成 |
| `/v1/passport/verify` | POST | viewer | 护照验证 |
| `/v1/innovation/manifest` | GET | viewer | 创新能力清单 |

### 8.5 历史与经营域

| 路由 | 方法 | 最小角色 | 说明 |
|------|------|---------|------|
| `/v1/history/overview` | GET | viewer | 历史总览 |
| `/v1/history/early-warning` | GET | viewer | 客诉早预警 |
| `/v1/history/outcomes` | GET | viewer | 回写明细 |
| `/v1/history/outcome-kpis` | GET | viewer | KPI 汇总 |
| `/v1/history/policy-recommendation` | GET | viewer | 策略建议 |
| `/v1/history/policy-lab` | GET | viewer | 离线仿真 |
| `/v1/history/counterfactual-twin` | GET | viewer | 反事实孪生 |
| `/v1/history/open-bandit-policy` | GET | viewer | LinUCB 推荐 |
| `/v1/history/executive` | GET | viewer | 经营指标 |
| `/v1/history/executive-export` | GET | operator | CSV 导出 |
| `/v1/history/runs` | GET | viewer | run 明细 |

### 8.6 其余核心路由

| 路由 | 方法 | 最小角色 | 说明 |
|------|------|---------|------|
| `/v1/strategy/champion-challenger` | POST | operator | 灰度策略评估 |
| `/v1/quality/spc/analyze` | POST | operator | SPC 子组分析 |
| `/v1/quality/spc/from-history` | GET | operator | 基于历史自动建 SPC |
| `/v1/report/shift/generate` | POST | operator | 班次报告生成 |
| `/v1/report/shift/from-history` | GET | viewer | 历史驱动班次报告 |
| `/v1/supplier/record` | POST | operator | 供应商质量事件写入 |
| `/v1/supplier/scorecard` | GET | viewer | 供应商评分卡 |
| `/v1/standards/register` | POST | operator | 标准色版本登记 |
| `/v1/standards/get` | GET | viewer | 读取标准色 |
| `/v1/standards/compare` | POST | viewer | 标准色对比实测 |
| `/v1/standards/version-drift` | GET | viewer | 标准版本漂移分析 |
| `/v1/standards/list` | GET | viewer | 标准库列表 |
| `/v1/policy/customer-tier` | GET | viewer | 分层策略解析 |
| `/v1/profiles` | GET | viewer | 材质阈值 |
| `/v1/report/html` | GET | viewer | HTML 报告渲染 |
| `/v1/web/executive-dashboard` | GET | public | 经营驾驶舱 |
| `/v1/web/executive-brief` | GET | operator | 执行简报网页 |
| `/v1/web/innovation-v3` | GET | public | 13 模块作战看板 |

---

## 9. 前端体系

入口文件: `elite_web_console.py`

四个页面:

1. **首页控制台** `/` — 单图/双图上传对色、实时调用状态与经营接口、关键 KPI
2. **经营驾驶舱** `/v1/web/executive-dashboard` — 放行率、三方指数、成本趋势、风险热力图
3. **执行简报** `/v1/web/executive-brief` — GO/NO_GO 判定、当日 KPI、告警摘要
4. **创新作战看板** `/v1/web/innovation-v3` — SPC/观察者/班报/供应商/标准库一体化操作

设计规范: 统一暗色工业风、响应式布局（移动端断点已配置）、所有数据实时从后端 API 拉取。

---

## 10. 安全治理与审计

**鉴权**: 三级角色 `viewer < operator < admin`，通过 `ELITE_ENABLE_API_KEY_AUTH=true` 开启。支持两种 JSON 格式映射。

**租户隔离**: `ELITE_ENFORCE_TENANT_HEADER=true` 强制要求租户头，支持白名单。

**限流**: 租户+IP 维度 RPM 限流。

**安全头**: `nosniff` / `deny` / `referrer-policy` 等默认启用。

**审计日志**: `logs/elite_audit.jsonl`，支持滚动与备份。敏感字段自动脱敏。`/v1/system/audit-tail` 在线查看。

---

## 11. 运维可靠性与告警

**探针**: `/health`（存活）、`/ready`（就绪，失败返回 503）、`/v1/system/self-test`（依赖自检）

**SLO**: `/v1/system/slo` 输出可用性 + 时延 SLO，支持排除分析重路由。

**告警链路**: Provider 支持 `webhook / wecom / dingtalk`，分级路由，失败进死信队列，支持重放。

**管理入口**: `/v1/system/ops-summary`（运维总览）、`/v1/system/executive-brief`（执行简报）

---

## 12. 发布门禁与验收

三级门禁脚本:

| 脚本 | 级别 | 耗时 | 覆盖 |
|------|------|------|------|
| `system_quick_check.ps1` | 快速 | ~5s | 健康 + 就绪 + 状态 |
| `run_full_e2e_flow.py` | 全链路 | ~30s | 分析 + 闭环 + 创新 + 历史 |
| `run_release_gate.ps1` | 发布级 | ~60s | 全部 + SLO + 角色边界 + 前端探针 |

门禁覆盖清单: 基础健康、系统状态/指标/SLO、自检/审计/告警、前端页面、全模式分析链路、创新模块全链路、闭环记录与历史分析、角色边界验证（可选）。

---

## 13. 部署与扩展

**启动命令**:

```powershell
powershell -ExecutionPolicy Bypass -File "D:\color match\autocolor\run_elite_api.ps1" -ApiHost 0.0.0.0 -Port 8877
```

**访问入口**: 本机 `http://127.0.0.1:8877/`，API 文档 `http://127.0.0.1:8877/docs`，局域网 `http://<IP>:8877/`

**防火墙**:

```powershell
powershell -ExecutionPolicy Bypass -File "D:\color match\autocolor\open_api_firewall_8877.ps1"
```

**多实例部署建议**: 当前为单机部署。扩展到多产线时，建议每条产线一个实例，共享 SQLite 替换为 PostgreSQL，加入 Nginx 反向代理做负载均衡。配置中心可用 consul/etcd 替代本地 JSON。

---

## 14. 故障处理与运维手册（生产级）

### 14.1 事件分级与响应 SLA

| 级别 | 典型场景 | 首次响应 | 恢复目标 | 升级路径 |
|------|---------|---------|---------|---------|
| P0 | 服务不可用、关键客户停线 | 10 分钟内 | 60 分钟内恢复可用 | 值班工程师 → 技术负责人 → 业务负责人 |
| P1 | 主流程可用但误判激增 | 15 分钟内 | 4 小时内收敛 | 值班工程师 → 算法负责人 |
| P2 | 创新模块异常、降级运行 | 30 分钟内 | 24 小时内修复 | 模块负责人 |
| P3 | 报表延迟、非核心功能异常 | 4 小时内 | 3 个工作日内 | 排期处理 |

### 14.2 故障处理总流程（统一动作）

1. 定级：先按 P0/P1/P2/P3 判级，不清楚时先按高一级处理。
2. 止血：先保主流程（`/v1/analyze/*`）可用，创新模块允许降级。
3. 取证：固定 `request_id`、日志片段、异常请求样例、数据库快照时间点。
4. 修复：优先走“可回滚变更”，避免现场大改。
5. 复盘：24 小时内提交 RCA（根因、影响面、改进动作、责任人、截止日）。

### 14.3 启动失败 Runbook

先执行环境基线检查：

```powershell
cd "D:\color match\autocolor"
python --version
pip show fastapi uvicorn opencv-python
Get-NetTCPConnection -LocalPort 8877 -ErrorAction SilentlyContinue
```

| 现象 | 快速定位 | 标准修复 |
|------|---------|---------|
| `ModuleNotFoundError` | `pip show` 缺包 | `pip install -r requirements.txt` |
| `Address already in use` | 8877 端口被占用 | 换端口启动或结束占用进程 |
| `sqlite3.OperationalError: database is locked` | 多进程并发写同库 | 停止重复实例，确认 WAL 开启 |
| 启动后 `/ready` 返回 503 | 依赖自检失败 | 调用 `/v1/system/self-test` 看具体依赖项 |

### 14.4 分析结果异常 Runbook

优先看 4 个指标：`avg_de`、`p95_de`、`confidence`、`quality_flags`。

| 现象 | 高概率原因 | 处理步骤 |
|------|-----------|---------|
| 置信度持续 < 0.6 | 光照不均/模糊/遮挡 | 按 `capture_guidance` 重拍；检查灯位、焦距、曝光 |
| ΔE 偏高但肉眼可接受 | 光源不一致或白平衡漂移 | 固定 D65 光源；核查 shading correction 与灰卡 |
| ΔE 偏低但客户投诉 | 同色异谱或纹理错判 | 追加 `/v1/analyze/spectral` 与 `/v1/analyze/texture-aware` |
| HOLD 激增 | 阈值过严或 flags 过多 | 回看 `decision_policy` 变更；对比昨日策略版本 |

快速判定树：

```text
先看 confidence
  ├─ <0.6: 采集问题优先
  └─ >=0.6: 再看 avg/p95/max 与 flags
         ├─ flags 高: 采集/材质问题
         └─ flags 低: 策略或算法参数问题
```

### 14.5 创新模块异常 Runbook

| 模块 | 现象 | 处理原则 |
|------|------|---------|
| 漂移预测 | `insufficient_history` | 非故障，提示补数据；低于最小样本不报警 |
| 老化预测 | 长期预测偏差大 | 校准材质参数并对比实测老化曲线 |
| 墨量处方 | 建议与实操不一致 | 回写实际调整结果，更新 Jacobian |
| 客户学习 | 始终 `unknown` | 校验 `customer_id` 是否统一、事件是否入库 |
| 色彩护照 | `tampered` | 检查签名链与是否有人工改 JSON |

降级策略：创新模块异常一律不阻断主判定，主流程继续并记录告警。

### 14.6 性能与容量 Runbook

| 指标 | 目标 | 告警阈值 | 处置 |
|------|------|---------|------|
| P95 响应时间 | < 3s | > 5s 持续 10 分钟 | 限制上传尺寸、降级非关键模块 |
| 错误率 | < 0.5% | > 2% 持续 5 分钟 | 回滚最近策略变更，查看错误热点 |
| 就绪探针失败率 | 0 | 连续 3 次失败 | 触发 P0/P1，转人工接管 |
| DB 写入时延 | < 100ms | > 300ms | 检查 WAL、I/O、锁等待 |

### 14.7 数据一致性与恢复 Runbook

每日自检 SQL（建议定时任务）：

```sql
-- 孤儿 outcome
SELECT COUNT(*) AS orphan_outcomes
FROM quality_outcomes o
LEFT JOIN quality_runs r ON r.id = o.run_id
WHERE o.run_id IS NOT NULL AND r.id IS NULL;

-- 最近24小时决策分布
SELECT decision_code, COUNT(*) AS cnt
FROM quality_runs
WHERE created_at >= datetime('now','-1 day')
GROUP BY decision_code;
```

恢复原则：

1. 先恢复写路径（新数据不丢）。
2. 再做历史补录（可离线）。
3. 所有恢复脚本必须落审计日志并记录执行人。

### 14.8 日常运维清单（班组可执行）

| 周期 | 必做项 |
|------|-------|
| 每日 | 健康探针、错误率、P95、告警死信、昨日客诉回写 |
| 每周 | 策略变更审计、漂移预警命中率、ROI 周报 |
| 每月 | 备份恢复演练、权限盘点、阈值策略复盘 |

---

## 15. 竞品对比、售前话术与 PoC 打单模板

### 15.1 能力对比（销售可直接展示）

| 能力维度 | X-Rite (10万+/台) | Datacolor (8万+/台) | 普通视觉方案 | **SENIA Elite** |
|---------|:-:|:-:|:-:|:-:|
| ΔE2000 色差 | ✓ | ✓ | ✓ | ✓ |
| 多光源色差 | 需硬件切换 | 需硬件切换 | ✗ | **✓ (算法)** |
| 同色异谱检测 | 需分光光度计 | 需分光光度计 | ✗ | **✓ (光谱重建)** |
| 纹理感知色差 | ✗ | ✗ | ✗ | **✓** |
| 漂移预测 | ✗ | ✗ | ✗ | **✓** |
| 色彩老化预测 | ✗ | ✗ | ✗ | **✓** |
| 自动墨量处方 | ✗ | ✗ | ✗ | **✓** |
| 批次混拼优化 | ✗ | ✗ | ✗ | **✓** |
| 客户容忍度学习 | ✗ | ✗ | ✗ | **✓** |
| 数字色彩护照 | ✗ | ✗ | ✗ | **✓** |
| 决策闭环 + 自学习 | ✗ | ✗ | ✗ | ✓ |
| **独有能力数** | **0** | **0** | **0** | **8+** |

### 15.2 竞品压制点（售前四句话）

1. 竞品解决“测得准”，Elite 解决“怎么决策、怎么调、怎么防客诉”。
2. 竞品是单点设备，Elite 是从检测到经营复盘的全链路系统。
3. 竞品要加硬件扩能力，Elite 主要靠算法增量升级，边际成本更低。
4. 竞品缺少客户容忍度与老化预测，Elite 能把未来风险前移到出厂前。

### 15.3 PoC 打单流程（2 周可落地）

| 阶段 | 时间 | 动作 | 产出 |
|------|------|------|------|
| D1-D2 | 第1-2天 | 接入相机与接口、采样规范培训 | 基线数据包 |
| D3-D5 | 第3-5天 | 双轨运行（人工 vs Elite） | 命中率对比表 |
| D6-D9 | 第6-9天 | 开启创新模块（老化/处方/混拼） | 客诉风险前移报告 |
| D10-D14 | 第10-14天 | 输出 ROI、上线建议、风险清单 | 签约版 PoC 总结 |

PoC 验收门槛（建议合同写入）：

- 误放行率下降 ≥ 30%
- 人工复核占比下降 ≥ 25%
- 调色平均时长下降 ≥ 40%
- 关键客户投诉率下降 ≥ 20%

---

## 16. 已知局限与改进计划（诚实可落地）

| 局限 | 业务影响 | 当前缓解 | 下一步动作 | 优先级 |
|------|---------|---------|-----------|--------|
| 光谱重建依赖默认矩阵 | 同色异谱精度受限 | 仅作预警不硬拦截 | 上线 ColorChecker 校准接口 | P1 |
| 老化参数基于行业平均 | 特定配方可能偏差 | 给出置信区间 | 接入实测老化数据库重拟合 | P2 |
| SQLite 并发有限 | 多线并发写入有锁风险 | WAL + 重试 | 迁移 PostgreSQL | P1 |
| Jacobian 初始值非产线定制 | 处方前期精度波动 | 两步调色+人工确认 | 采集闭环样本自动学习 | P1 |
| 极端反光场景 | 置信度下降、误判上升 | 质量旗标提示重拍 | 偏振方案 + 去反光算法 | P2 |
| 跨设备色域不统一 | 不同相机可比性弱 | 设备 profile 手工切换 | 自动设备域校准 | P2 |

---

## 17. 下一阶段路线图（可执行 + 可验收）

### 17.1 总体节奏（明确日期）

| Phase | 时间窗口 | 核心目标 | 退出条件 |
|------|---------|---------|---------|
| Phase 1 | 2026-04-01 ~ 2026-04-14 | 精度与稳定性夯实 | 核心指标连续 7 天达标 |
| Phase 2 | 2026-04-15 ~ 2026-04-30 | 闭环学习与经营可视化 | 闭环数据完整率 > 95% |
| Phase 3 | 2026-05-01 ~ 2026-05-31 | 多产线规模化治理 | 10+ 并发写入稳定 |
| Phase 4 | 2026-06-01 起 | 智能化持续进化 | 每月发布可量化改进 |

### 17.2 分阶段任务清单（负责人 + 依赖 + 验收）

| Phase | 任务 | 负责人 | 依赖 | 交付物 | 验收标准 |
|------|------|-------|------|--------|---------|
| 1 | 光谱校准流程落地 | 算法负责人 | ColorChecker 数据 | 校准工具 + 参数包 | MI RMSE < 3% |
| 1 | 墨量 Jacobian 产线化 | 工艺负责人 | 近 2 周调色记录 | 产线 J 矩阵 | 处方残余 ΔE < 0.8 |
| 1 | 采集规范固化 | 质量负责人 | 机位与灯位改造 | SOP + 培训记录 | 低置信度率 < 8% |
| 2 | 客诉历史批量导入 | 数据负责人 | ERP/CRM 导出 | 导入脚本 + 校验报告 | 客户画像覆盖 > 80% |
| 2 | 漂移预警接入告警链 | 平台负责人 | 告警渠道配置 | 自动预警规则 | 突变检测延迟 < 3 批 |
| 2 | Dashboard 升级时序分析 | 前端负责人 | 历史接口稳定 | 多时间尺度图表 | 管理层周会可直接使用 |
| 3 | PostgreSQL 迁移 | 后端负责人 | 数据迁移窗口 | 新数据层 + 回滚脚本 | 并发写入 10+ 稳定 |
| 3 | 多租户配置中心 | 平台负责人 | 权限模型 | 配置中心 + 版本化 | 新线接入 < 10 分钟 |
| 3 | Release Gate 接入 CI | DevOps 负责人 | 测试脚本稳定 | CI 工作流 | 合并前自动门禁 |
| 4 | 主动学习闭环 | 算法负责人 | 标注资源 | 低置信度采样机制 | 标注成本下降 50% |
| 4 | 跨设备域统一 | 算法+硬件 | 多设备样本 | 设备域校准模型 | 跨设备偏差 < 0.3 ΔE |
| 4 | 反光补偿 | 算法负责人 | 反光场景数据 | 去反光模型 | 反光场景置信度 > 0.7 |

### 17.3 每周治理节奏（防“计划落空”）

1. 周一：上周 KPI 复盘（误放行、客诉、ROI、预警命中率）。
2. 周三：策略变更评审（仅允许小步变更 + 可回滚）。
3. 周五：风险盘点（P1/P2 问题关闭率、下周资源安排）。

### 17.4 发布门禁（上线前最后一关）

| 门禁项 | 通过标准 |
|------|---------|
| 健康与就绪 | 连续 24 小时无异常 |
| 主流程准确性 | 对照人工抽检偏差在目标范围 |
| 闭环完整性 | `quality_runs` 与 `quality_outcomes` 关联率 > 95% |
| 安全与审计 | 权限与审计抽查 100% 可追溯 |
| 回滚能力 | 30 分钟内可回滚到上版本 |

---

*本文档为 SENIA Elite v2.5.0 全栈基线，覆盖：售前演示、技术评审、研发交接、运维值守、发布门禁与经营复盘。*
