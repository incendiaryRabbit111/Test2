# 特征微生物分析工具 — 开发者手册

> **读者**：接手的开发者（人或 AI）。
> **目标**：读完这份文档，你能独立定位问题、修改功能、扩展模块，而不需要问原作者。
> **终端用户文档**见 `release/使用说明.txt`（交付给甲方的那份）。

---

## 目录

- [0. 怎么读这份文档](#0-怎么读这份文档)
- [1. 系统定位](#1-系统定位)
- [2. 五分钟跑起来](#2-五分钟跑起来)
- [3. 架构总览](#3-架构总览)
- [4. 核心数据结构](#4-核心数据结构)
- [5. 模块详解](#5-模块详解)
- [6. 使用逻辑（端到端）](#6-使用逻辑端到端)
- [7. AI 提示词设计](#7-ai-提示词设计)
- [8. 知识库流水线](#8-知识库流水线)
- [9. 界面层](#9-界面层)
- [10. 关键设计决策](#10-关键设计决策)
- [11. 技术债与已知缺陷](#11-技术债与已知缺陷)
- [12. 修改指南（需求 → 改哪里）](#12-修改指南需求--改哪里)
- [13. 测试](#13-测试)
- [14. 打包](#14-打包)
- [15. 术语表](#15-术语表)

---

## 0. 怎么读这份文档

| 你的情况 | 读哪些 |
|---|---|
| 刚接手，想跑起来 | 2 → 3.1 → 6 |
| 要改某个功能 | **12（修改指南）**，再回头查 5 |
| 要重构 / 做 API 化 | 3、4、10、11 |
| 排查线上问题 | 6、7.4（容错链）、11 |
| 只想知道数据长什么样 | 4 |

**先说三条最容易踩的约定：**

1. **`app/` 下除 `main_window.py` / `*_dialog.py` / `trend_view.py` / `onboarding.py` / `theme.py` 外，全部不依赖 Qt**。改业务逻辑时不要引入 Qt。
2. **`app/generated/` 是编译产物，不要手改**，改 `ui/main_window.ui` 后跑 `tools/build_ui.py`。
3. **改完必须跑 `tools/smoke_test.py`**（136 项，约 60 秒）。不跑就提交 = 埋雷。

---

## 1. 系统定位

### 1.1 它解决什么问题

污水处理厂用显微镜观察活性污泥里的微型动物（原生动物、后生动物），通过"谁多谁少"判断污泥健康状况。传统做法是老师傅凭经验看，**结果不可复现、无法追溯、新人学不会**。

本工具把这件事量化：

```
仪器输出的「物种 + 浓度」
        ↓
  指标计算（Shannon / Margalef / Pielou / 优势度）
        ↓
  与上次对比 → 趋势判定
        ↓
  检索专业文献 → 大模型生成评价与报告
        ↓
  一份可追溯、可导出、带文献出处的分析报告
```

### 1.2 边界

| ✅ 做 | ❌ 不做 |
|---|---|
| 解析**已有**的物种浓度数据 | 图像识别（不处理图片/视频） |
| 计算群落指标 | 判断水质达标（不做排放标准判定） |
| 生成文字评价 | 控制工艺设备 |
| 本地文献检索 | 联网搜索 |

> **重要**：识别层（图片 → 物种）由**另一方**负责，本项目只接收结构化数据。这是后续做 API 化的前提。

### 1.3 技术栈

| 层 | 选型 | 备注 |
|---|---|---|
| 界面 | PySide6 6.12（Qt Widgets） | 不用 QML |
| 界面定义 | Qt Designer `.ui` → `pyside6-uic` | 编译进 `app/generated/` |
| 数据存储 | SQLite（标准库 `sqlite3`） | 两个库：`history.db` / `api_configs.db` |
| 表格导出 | openpyxl | |
| HTTP | requests | 同步阻塞，在子线程里跑 |
| 检索 | rank_bm25 + jieba | 本地，无网络 |
| OCR | RapidOCR（onnxruntime） | 仅构建知识库时用，运行时不需要 |
| PDF | pymupdf | 同上 |
| 加密 | Windows DPAPI（ctypes 调 crypt32） | 只加密 API Key |
| Python | 3.13 | |

**运行时依赖**（`requirements.txt`）只有 5 个：PySide6 / pandas / openpyxl / xlrd / requests。

**构建知识库**才需要额外装：pymupdf / jieba / rank_bm25 / rapidocr-onnxruntime（约 100 MB）。**这两组依赖是分开的**，别混。

---

## 2. 五分钟跑起来

```bat
git clone https://github.com/incendiaryRabbit111/fishes_detection.git
cd fishes_detection

py -3.13 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt

:: 必须做：.ui 的编译产物不入库
.venv\Scripts\python.exe tools\build_ui.py

.venv\Scripts\python.exe main.py
```

**没有 API Key 也能跑**——会降级为「本地模拟」，指标计算和界面流程完全正常。

要配 Key：界面右上角「API 设置」，或复制 `.env.example` 为 `.env` 填 `DEEPSEEK_API_KEY`。

**验证环境是否正常**：

```bat
.venv\Scripts\python.exe tools\smoke_test.py
```

看到 `全部通过 ✅` 说明环境没问题。如果失败项全是 `SSLError` / `Connection`，是网络问题不是代码问题。

---

## 3. 架构总览

### 3.1 分层

```
┌─────────────────────────────────────────────────────┐
│  main.py           QApplication + 主题 + 主窗口       │
├─────────────────────────────────────────────────────┤
│  app/main_window.py      界面编排（唯一的"大脑"）      │
│  app/*_dialog.py         对话框                       │
│  app/trend_view.py       趋势图控件                   │
│  app/onboarding.py       引导遮罩                     │
│  app/theme.py            主题 QSS                     │
├─────────────────────────────────────────────────────┤
│  app/analyzer.py    ← 唯一对外部世界（AI）有副作用的一层 │
├─────────────────────────────────────────────────────┤
│  纯逻辑层（无 Qt / 无网络，可单测）                     │
│  parser / metrics / trend / times / batch /           │
│  history / rag / exporter / secure_store / api_config │
├─────────────────────────────────────────────────────┤
│  存储：data/*.db　knowledge/index/bm25.pkl             │
└─────────────────────────────────────────────────────┘
```

**设计原则**：越往下依赖越少。`metrics.py` 连 `import os` 都没有，只有 `math`。

**验证方法**：随便打开一个纯逻辑模块，搜 `PySide6` 或 `QMessageBox`，应该一个都搜不到。

### 3.2 端到端数据流

以「点一次分析」为例，标出每一步的类型：

```
[用户粘贴文本]
      │  str
      ▼
parser.parse(text) ──────────────────────────────► ParsedSample
      │                                            ├ species: dict[str, float]
      │                                            ├ unit: str
      │                                            ├ change: dict[str, float]   ← 文本自带的"较上次变化"
      │                                            └ warnings: list[str]
      │
      ├──► history.last() ────────────────────────► Record | None   （上一条，用于对比）
      │
      ▼
trend.compute_changes(current, previous, fallback) ► dict[str, Change]
      │
      ▼
metrics.compute(species) ─────────────────────────► MetricsResult
      │                                            ├ shannon_h / margalef_d / pielou_j
      │                                            ├ dominant / absolute: list[str]
      │                                            └ rows: list[SpeciesMetric]
      │
      ├──► trend.detect_trends(changes) ───────────► list[TrendHit]
      │
      ▼
analyzer.build_payload(parsed, metrics, changes, trends, prev_time) ► dict  （见 4.4）
      │
      ▼
rag.build_query(payload) ─────────────────────────► str  （检索词）
      │
      ▼
rag.KnowledgeBase.search(query, top_k=6) ─────────► list[Reference]
      │
      ▼
rag.format_context(refs) ─────────────────────────► str  （注入提示词的"参考资料"块）
      │
      ▼
analyzer.analyze(payload)      ← 内部两次 _chat()，见 §7
      │
      ▼
AnalysisResult
      ├ report: str                    「情况 / 变化 / 建议」纯文本
      ├ evaluations: list[SpeciesEval]
      ├ references: list[dict]
      ├ source: str                    "DeepSeek（deepseek-chat）" | "本地模拟"
      └ error: str                     失败时的可读原因
      │
      ▼
history.save(Record) ─────────────────────────────► int (rec_id)
history.update_analysis(rec_id, Record)            回填报告/评价/参考文献
      │
      ▼
[界面渲染] + [可导出 xlsx]
```

**注意顺序**：先 `save` 再 `update_analysis`。因为界面要立刻显示这条记录（进度条期间就要显示指标），而 AI 报告是后到的。

### 3.3 线程模型

**唯一的后台线程**：`AnalyzeWorker(QThread)`，只跑 `analyzer.analyze(payload)`。

```
主线程                        子线程
  │  on_analyze()
  │    ├ 解析（快，同步）
  │    ├ 建 payload（快，同步）
  │    ├ 启动 worker ──────────► analyze()：HTTP 请求 2 次，耗时 10~30s
  │    └ 返回，界面不冻结
  │
  │  ◄── finished(AnalysisResult) 信号
  │  _on_analysis_done()
  │    ├ 写库
  │    ├ 刷新列表/趋势
  │    └ 显示报告
```

**约定**：**子线程里绝对不能碰任何 QWidget**。`AnalyzeWorker.run()` 里只有纯计算和 HTTP。

**批量导入不进线程**——它不调 AI，纯本地计算，几百毫秒完成。如果以后要给批量导入加"同时生成 AI 报告"，必须先抽线程池。

---

## 4. 核心数据结构

> 这是本文档最重要的一节。改任何功能前先看清数据形状。

### 4.1 `ParsedSample`（`parser.py`）

```python
@dataclass
class ParsedSample:
    species: dict[str, float]   # {"表壳虫": 1.440, ...}  已排序：浓度降序
    unit: str                   # "10^6 个/L"
    extras: dict[str, str]      # 其他元数据（设备号等）
    change: dict[str, float]    # 文本自带的"较上次变化"，值是百分比数值（3.2 表示 +3.2%）
    strategy: str               # "scan" | "loose"  用了哪种解析策略
    warnings: list[str]         # 解析告警，会显示在核对弹窗里
```

**两个派生属性**：`total`（浓度合计）、`positive_count`（浓度>0 的物种数）。

### 4.2 `MetricsResult` / `SpeciesMetric`（`metrics.py`）

```python
@dataclass
class SpeciesMetric:
    name: str
    concentration: float
    relative: float        # 0~1
    dominance: float       # Y = (n_i/N) × f_i

    @property is_dominant  # dominance > 0.05
    @property is_absolute  # relative >= 0.10
    @property percent      # relative * 100，用于显示

@dataclass
class MetricsResult:
    total: float
    species_count: int
    shannon_h: float
    rows: list[SpeciesMetric]   # 浓度降序
    dominant: list[str]
    absolute: list[str]
    margalef_d: float
    pielou_j: float
```

**⚠️ 关键**：`compute(species, freq=None)` 的 `freq` 参数是多期数据才用的出现频率。**单样本时 `freq` 为空，`f_i` 取 1.0，于是 `dominance == relative`。** 这解释了为什么优势种判定等价于"相对丰度 > 5%"。

`margalef_d` 的计算里 `N = total × 1e6`（把「10⁶ 个/L」换算成「个/L」）。**换单位这个指数就废了**，见 §11。

### 4.3 `Change` / `TrendHit`（`trend.py`）

```python
@dataclass
class Change:
    species: str
    current: float
    previous: float | None
    pct: float | None       # 变化百分比，None 表示无对比数据
    source: str             # "历史库" | "文本自带" | "无"
    note: str
    @property text          # 显示用："+12.3%" / "新增" / "—"

@dataclass
class TrendHit:
    rule: str       # "楯纤虫急速变少"
    detail: str     # "减少 81.9%"
    meaning: str    # 给 AI 的解读提示
```

### 4.4 `payload`（`analyzer.build_payload()` 的返回）

**这是业务层和 AI 层之间的唯一契约**。要改提示词、要做 API，都从这看。

```python
{
  "unit": "10^6 个/L",
  "species_count": 13,
  "h": 2.031,
  "h_max": 2.565,
  "evenness": 0.792,          # 实为 pielou_j
  "d": 0.796,
  "dominant": ["表壳虫", "扭曲管叶虫", "内管虫", "袋鞭虫"],
  "absolute": ["表壳虫", "扭曲管叶虫"],
  "previous_time": "2026-10-09 09:00:00",   # 空字符串表示无上一条
  "rows": [                    # 每个物种一行
    {
      "name": "表壳虫",
      "concentration": 1.44,
      "percent": 41.0,
      "dominant": True,
      "absolute": True,
      "change_pct": 1.2,       # None 表示无变化数据
      "change_text": "+1.2%",
      "change_source": "历史库"
    }
  ],
  "changes": [{"species": "...", "pct": 1.2, "source": "历史库"}],
  "trends": [{"rule": "...", "detail": "...", "meaning": "..."}]
}
```

> **做 API 化时**：这个 dict 就是 `POST /evaluate` 的请求体雏形。外面再包一层 `device_id` / `sample_time` / `trace_id` 即可。

### 4.5 `SpeciesEval` / `AnalysisResult`（`analyzer.py`）

```python
@dataclass
class SpeciesEval:
    species: str
    comment: str      # 40~60 字，指示意义
    advice: str = ""  # 15~30 字，工艺建议

@dataclass
class AnalysisResult:
    report: str = ""
    evaluations: list[SpeciesEval] = []
    source: str = "本地模拟"          # "DeepSeek（deepseek-chat）" 等
    error: str = ""                   # 非空 = 走降级了
    references: list[dict] = []       # Reference.to_dict() 的列表

    @property eval_map: dict[str, SpeciesEval]
```

**判据**：`source == "本地模拟"` 或 `error != ""` → 这次是降级结果，界面要挂警告。

### 4.6 `Record`（`history.py`）↔ `samples` 表

**一一对应，16 列**。JSON 字段在库里以 TEXT 存。

| 列 | 类型 | 对应 `Record` 字段 | 说明 |
|---|---|---|---|
| `id` | INTEGER PK | `id` | |
| `device` | TEXT | — | 预留，目前固定空串 |
| `sample_time` | TEXT | `sample_time` | `YYYY-MM-DD HH:MM:SS` |
| `imported_at` | TEXT | `imported_at` | 入库时间 |
| `unit` | TEXT | `unit` | |
| `total` | REAL | `total` | |
| `species_count` | INTEGER | `species_count` | |
| `shannon_h` | REAL | `shannon_h` | |
| `species_json` | TEXT | `species` → `dict` | |
| `report` | TEXT | `report` | |
| `raw_text` | TEXT | `raw_text` | 原始粘贴文本 |
| `evaluations_json` | TEXT | `evaluations` → `list` | |
| `changes_json` | TEXT | `changes` → `list` | |
| `trends_json` | TEXT | `trends` → `list` | |
| `analysis_source` | TEXT | `analysis_source` | |
| `error_text` | TEXT | `error_text` | 降级原因 |
| `references_json` | TEXT | `references` → `list` | |

**加字段的规矩**（非常重要）：

```python
# 1. 在 CREATE TABLE 里加（新库）
# 2. 在 _EXTRA_COLUMNS 里加（老库自动 ALTER）
_EXTRA_COLUMNS = {"error_text": "TEXT", "references_json": "TEXT"}
# 3. 在 _COLS 里加（查询列）
# 4. 同步改 save() 的 INSERT 列 / 占位符 / 参数顺序
# 5. 同步改 update_analysis() 的 SET / 参数顺序
# 6. 同步改 _to_record() 的 row[i] 索引
```

> **踩过的坑**：合并别人代码时两边各加一列，`INSERT` 的 `?` 数量没跟着改，直接 `TypeError: execute expected at most 2 arguments`。改这 6 处缺一不可。

### 4.7 `Reference`（`rag.py`）

```python
@dataclass
class Reference:
    label: str        # "R1"
    book: str         # 书名
    author: str
    page_start: int
    page_end: int
    text: str         # 片段（约 140 字）
    score: float
    cited: bool       # 是否被 AI 真的引用（mark_cited 后置）
```

### 4.8 `ApiConfig`（`api_config.py`）

```python
@dataclass
class ApiConfig:
    id: int | None
    name: str            # 显示名，如 "DeepSeek"
    base_url: str        # https://api.deepseek.com（不带 /v1 也行）
    model: str           # 当前选中的模型
    models: list[str]    # 该配置下所有勾选的模型
    api_key: str         # 内存中是明文，落库前 DPAPI 加密
    temperature: float = 0.2
    timeout: int = 180
    is_default: bool
    source: str = "db"   # "db" | "env"

    @property configured   # base_url + api_key + model 都非空
    @property masked_key   # "sk-1234****abcd"
```

---

## 5. 模块详解

### 5.1 `parser.py` — 文本解析（231 行）

**职责**：把仪器输出的一段乱糟糟的文本，变成 `{物种: 浓度}`。

**公开 API**：`parse(text) -> ParsedSample`、`normalize(text)`、`normalize_name(name)`

**实现要点**：

```
normalize()          全角→半角、统一换行、去不可见字符
      ↓
_mask_metadata()     把「物种种类数：13」这类元数据行挖掉（换成等长空格）
      ↓                ↑ 不挖掉的话，会把它当成物种解析出来
_strategy_scan()     严格模式：要求「名称 + 分隔符 + 数字」
      ↓ 失败
_strategy_loose()    宽松模式：只要求「中文名(2~8字) + 空白 + 数字」
      ↓
_validate()          校验：物种数下限、浓度合理性，异常写进 warnings
```

**支持的格式**（smoke_test 第 2 节覆盖）：

```
表壳虫: 1.440            冒号
表壳虫：1.440            全角冒号
表壳虫 1.440             空格
表壳虫    1.440          多空格 / 制表符
1. 表壳虫 1.440          带序号
表壳虫:1.44              无空格
表壳虫 1.440 个/mL       带单位
（Excel 复制的两列表格）  制表符
```

**坑**：

- `_mask_metadata` 是**用空格覆盖**而不是删除，因为后续靠位置回溯。改这里要小心索引错位。
- `_acceptable(name)` 会过滤掉明显不是物种的词（纯数字、超长串）。**加新物种名不用改这里**，它只做粗筛。
- `species` 返回时已按浓度降序排好，下游不要再排。

---

### 5.2 `metrics.py` — 指标计算（86 行）

**职责**：`{物种: 浓度}` → 全部派生指标。

**公开 API**：`compute(species, freq=None) -> MetricsResult`

**实现要点**：

```python
total = sum(positive.values())          # 只算 > 0 的
for k, v in sorted(positive.items(), key=lambda x: -x[1]):
    rel = v / total
    dom = rel * freq.get(k, 1.0)        # ← f_i 缺省 1.0
shannon = -Σ(rel * ln(rel))
margalef = (S-1) / ln(total * 1e6)      # ← 单位换算在这里
pielou  = shannon / ln(S)
```

**阈值常量**在文件顶部：

```python
THRESHOLD_DOMINANT = 0.05   # 《污水处理的生物相诊断》1.4.3
THRESHOLD_ABSOLUTE = 0.10   # 本项目自定义，文献未定义
```

**坑**：

- `total <= 0` 时返回空结果（不要改成抛异常，界面会在空记录上调用）。
- `ln(total * 1e6)` 中的 `1e6` 是硬编码的单位换算。**这是技术债**，见 §11。

---

### 5.3 `trend.py` — 变化与趋势（126 行）

**公开 API**：

```python
compute_changes(current, previous=None, fallback=None) -> dict[str, Change]
detect_trends(changes) -> list[TrendHit]
```

**来源优先级**（`source` 字段）：

```
previous（历史库上一条）  >  fallback（文本自带的"较上次变化"）  >  "无"
```

**为什么这个顺序**：历史库是本程序自己记的，可靠；文本自带的可能来自别的设备/别的算法，只做兜底。

**5 条规则**（阈值来自甲方 xlsx）：

| 规则 | 条件 |
|---|---|
| 楯纤虫急速变少 | `pct <= -70` |
| 钟虫急速变少 | `pct <= -70` |
| 轮虫变多 | `pct >= 300` |
| 游泳纤毛虫占比变多 | ⏸ 未实现 |
| 固着纤毛虫占比变多 | ⏸ 未实现 |

后两条缺「物种 → 生态类群」对照表。**要启用需要先加一张 `{"钟虫": "固着", "草履虫": "游泳", ...}` 的表**，然后按类群汇总占比再比。

---

### 5.4 `times.py` — 时间解析（30 行）

**公开 API**：`parse_dt(text) -> datetime | None`、`fmt(dt) -> str`

**为什么单独一个模块**：`history.py`、`batch_dialog.py`、`trend_view.py` 都要解析用户输入的时间，且有 Qt 依赖的模块不能互相 import 太深。抽出来保证"零依赖"。

支持：`2026-10-09`、`2026/10/09`、`2026-10-09 09:00`、`2026年10月9日` 等。

---

### 5.5 `history.py` — 记录库（226 行）

**公开 API**：

```python
History(path=None)
  .save(rec) -> int                     # 插入，返回 id
  .update_analysis(rec_id, rec)         # 回填报告/评价/参考文献
  .get(rec_id) -> Record | None
  .last() -> Record | None              # 用作"对比基准"
  .recent(limit=500) -> list[Record]    # 趋势图用
  .all_desc() -> list[Record]           # 列表用（新→旧）
  .count() / .delete(id) / .clear()
```

**实现要点**：

- 每次操作开一个短连接（`with self._conn() as conn`），用完就关。**不做连接池**（单用户场景）。
- `_migrate()` 在每次建连时跑：读 `PRAGMA table_info`，缺的列用 `ALTER TABLE ADD COLUMN` 补。**这就是为什么老库能直接用**。
- JSON 字段用 `_loads(text, default)` 兜底——坏数据不会让整个列表挂掉。

**坑**：

- `last()` 返回的是**全库最后一条**，不是"同设备的最后一条"。`device` 列目前都是空串，多设备场景没实现。
- `save()` 和 `update_analysis()` 的 SQL 参数顺序必须和列顺序严格一致，改一处要全改。

---

### 5.6 `batch.py` — 批量切段（97 行）

**公开 API**：

```python
split_segments(raw) -> list[str]
parse_batch(raw, start_time="", interval_min=0) -> BatchResult
```

**切段规则**：空行、`---`、`===`、`***` 都算分隔符。

**时间推算**：每段第一行如果能解析成时间就用它，否则用 `start_time + n × interval_min` 推算。

**坑**：`parse_batch` 内部对每段调 `parser.parse()`，**不调 AI**。这是设计选择（见 §10）。

---

### 5.7 `analyzer.py` — AI 调用（558 行，最复杂的模块）

**公开 API**：

```python
DeepSeekAnalyzer(config: ApiConfig | None, model: str | None = None)
  .is_live            -> bool      # 配置完整吗
  .mode_text          -> str       # 显示用
  .test_connection()  -> (bool, str)
  .analyze(payload)   -> AnalysisResult

build_payload(parsed, metrics, changes=None, trends=None, previous_time="") -> dict
```

**内部链路**：

```
analyze(payload)
  ├ 检索：kb.search(build_query(payload), top_k=6) → refs
  ├ 格式化：format_context(refs) → reference_block
  ├ 阶段一：_chat(build_stage1_prompt(...), json_mode=True, max_tokens=8000, label="阶段一")
  │    └ 解析 JSON → list[SpeciesEval]
  │    └ 失败 → _mock() 返回本地模拟，直接结束
  ├ 阶段二：_chat(build_stage2_prompt(...), json_mode=False, max_tokens=4000, label="阶段二")
  │    └ 失败 → _fallback_report()（用各物种 advice 拼模板）
  └ mark_cited(refs, report, all_comments)   ← 回填 Reference.cited
```

**`_chat()` 的四层容错**（这是本项目最值得借鉴的一段）：

```python
① 带 response_format 请求
② 若「非 200」或「200 但正文为空」→ 去掉 response_format 重试一次
③ 仍失败 → 返回可读错误（含 usage、finish_reason）
④ 同时写 data/last_error.txt（原始请求 + 完整响应）
```

**为什么要第 ② 条**：很多中转站不认识 `response_format`，**不报错、直接返回 `content: null`**。原来的实现只在 `status_code != 200` 时重试，遇到这种就直接崩（`None.strip()` → AttributeError）。

**`_extract()` 处理四种返回形态**：

| 形态 | 处理 |
|---|---|
| `content` 是字符串 | 直接用 |
| `content` 是 `null` | JSON 阶段则回退到 `reasoning_content` |
| `content` 是数组（多模态） | 拼 `text` 字段 |
| 没有 `choices` | 报可读错误 |

**坑**：

- `_dump()` 写的是 `ROOT/data/last_error.txt`，**每次失败覆盖**（不追加），避免无限增长。
- 阶段一的 `max_tokens=8000` 是给推理模型的余量。**调小会让推理模型返回空正文**。
- `_mock()` 生成的报告里带"（本地模拟结果，未接入大模型。）"，**不要删这句**，它是用户判断结果可信度的唯一依据。

---

### 5.8 `rag.py` — 检索（201 行）

**公开 API**：

```python
KnowledgeBase(path=None)
  .available -> bool
  .search(query, top_k=6, min_score=0.0) -> list[Reference]

build_query(payload) -> str                  # 由物种/趋势拼检索词
format_context(refs) -> str                  # 拼成提示词里的"参考资料"块
mark_cited(refs, *texts) -> None             # 扫 [R1] 标记回填 cited
```

**初始化必须优雅降级**：

```python
if self.path.exists():
    try: load...
    except Exception: available = False      # ← 索引坏了不能崩
# search() 里：if not available: return []
```

**没有索引时 RAG 静默跳过**，不影响任何其他功能。这是刻意设计。

**`_ensure_jieba()`**：延迟加载 + 注册 `DOMAIN_WORDS`（表壳虫、楯纤虫等 50+ 个），否则 jieba 会把"表壳虫"切成"表/壳/虫"。

**`build_query` 的拼接逻辑**：绝对优势物种 + 前几个优势物种 + 趋势规则关键词 + 固定领域词。

**坑**：`_snippet(radius=70)` 是从 180 改小的。改大会让提示词变长、模型开始大段抄原文。

---

### 5.9 `exporter.py` — 导出（139 行）

**公开 API**：`export(path, sample_time, parsed, metrics, analysis, changes, device, trends, previous_time) -> Path`

**4 个 sheet**：

| Sheet | 列 |
|---|---|
| 物种评价 | 物种 / 浓度 / 相对丰度 / 等级 / 较上次变化 / 综合评价 / 指导意见 |
| 检测概要 | 设备 / 采样时间 / 导出时间 / 单位 / 浓度合计 / 物种数 / H' / **D** / **J** / 优势种群 / 绝对优势种群 / 对比基准 / 命中趋势 |
| AI 分析报告 | 情况 / 变化 / 建议 / 调用异常 |
| 参考来源 | 编号 / 书名 / 作者 / 页码 / 是否引用（**不含原文**） |

**坑**：

- `_safe(v)` 过滤掉 Excel 不接受的字符（`\x00-\x08` 等）。
- 列数改动必须同步 `_autosize` 的 `caps` 索引，否则列宽全乱。

---

### 5.10 `secure_store.py` / `api_config.py` — 配置与加密

**加密**：Windows DPAPI（`CryptProtectData`），用 `ctypes` 直接调 `crypt32.dll`。

```python
encrypt("sk-xxx") -> base64 字符串
decrypt(...)      -> 明文
# 特点：绑定「当前 Windows 用户」，换机器/换用户解不开
```

**非 Windows 环境**（比如将来的 Debian 服务端）`_dpapi_available()` 返回 False，此时 `encrypt` 直接返回明文。**这是已知技术债**，上服务器前必须换方案（见 §11）。

**`ApiConfigStore`**：SQLite 存多条配置，`default()` 取默认项，`seed_from_env()` 首次启动把 `.env` 导入成一条。

---

### 5.11 `paths.py` — 路径适配（27 行）

```python
app_root()    # 源码运行 = 项目根；打包后 = exe 所在目录
bundle_dir()  # 打包后的 _MEIPASS（只读资源）
```

**规则**：

| 场景 | 用哪个 | 为什么 |
|---|---|---|
| 写数据（db、日志） | `app_root() / "data"` | 要可写，且要留在 exe 旁边 |
| 读打包资源（图标） | `bundle_dir()` | PyInstaller 解压到临时目录 |

**坑**：写到 `bundle_dir()` 里 = 程序一关数据就没了。

---

## 6. 使用逻辑（端到端）

> 这一节是"用户做了什么" → "程序内部发生了什么"的对照表。

### 6.1 首次启动

```
main.py
 ├ QApplication → theme.apply() 装全局 QSS + 字体
 ├ MainWindow()
 │   ├ 读 ApiConfigStore，seed_from_env()
 │   ├ 建 History（自动迁移表结构）
 │   ├ _reload_providers()  填充模型下拉框
 │   └ _reload_sessions()   载入历史列表
 └ win.show()
      └ showEvent()
          ├ 首次？(QSettings "onboarded") → QTimer(600ms) → start_onboarding()
          └ 没配 API？→ 弹一次引导提示
```

**首次判定**：`QSettings("MicrobeAnalyzer", "App")` 的 `onboarded` 键（Windows 在注册表）。只在 `showEvent` 里判一次（`_guide_checked` 防重）。

### 6.2 新建分析 → 分析（核心流程）

```
点「＋ 新建分析」
  └ _on_new()
      ├ 清空输入框、重置时间
      └ 切到 inputPage

粘贴文本 → 点「分析」
  └ on_analyze()
      ├ parser.parse(text)                    失败 → 弹错误，中止
      ├ 用了"核对"选项？ → ConfirmDialog 让用户确认解析结果
      ├ metrics.compute(species)
      ├ history.last() → trend.compute_changes()
      ├ trend.detect_trends()
      ├ payload = build_payload(...)
      ├ history.save(Record(只有数据，无报告))   ← 先存，界面立刻能显示
      ├ 按钮变「分析中…」+ 遮罩盖上
      └ 启动 AnalyzeWorker(payload).start()
            │
            ▼ 子线程
          analyzer.analyze(payload)   （含 RAG 检索，见 §7）
            │
            ▼ finished 信号
          _on_analysis_done(result)
            ├ history.update_analysis(rec_id, ...)  回填报告/评价/参考文献
            ├ _reload_sessions(select_id=rec_id)
            ├ _refresh_trend()
            ├ 状态栏胶囊：物种 / H' / 评价 x/y / 趋势 n / 对比源
            ├ 恢复按钮 + 撤遮罩
            └ 有 error？→ 弹窗 + 写入 last_error.txt
```

**关键设计**：**先存后算**。这样即使 AI 挂了，指标数据也不会丢，用户至少能看到计算指标。

### 6.3 查看记录

```
点左侧列表项
  └ _on_row_changed()
      └ _show_record(rec)
          ├ _fill_metrics(compute(rec.species))      ① 计算指标
          ├ _fill_evaluations(...)                   ② 物种评价
          ├ _show_report(rec.report, rec.references) ③ AI 报告 + 参考文献
          │    └ 有 error_text？→ 顶部挂黄色横幅
          └ 切到 resultPage
```

**注意**：`_show_record` 会用 `rec.species` **重新计算**指标，不读库里的 `shannon_h`。这样指标逻辑一改，历史记录也跟着变（可能是好事也可能是坑，见 §11）。

### 6.4 批量导入

```
「批量导入」
  └ BatchDialog
      ├ 粘贴多段文本
      ├ 设起始时间 + 间隔（或每段自带时间）
      ├ 预览每段的解析结果
      └ 确认
  └ on_batch_import()
      ├ batch.parse_batch(...)
      ├ 逐条 metrics.compute + history.save()
      │    ↑ 不调 AI
      └ 刷新列表 + 趋势图
```

**为什么批量不调 AI**：5 条 × 2 次请求 = 10 次，1~2 分钟 + 10 次费用，而用户此时只想看曲线。需要报告就右键「载入到输入框」单独分析。

### 6.5 导出

```
「导出当前记录」
  └ QFileDialog 选路径
  └ exporter.export(path, ...) → openpyxl 写 4 个 sheet
```

### 6.6 切换模型

```
顶栏下拉框 → _apply_provider()
  ├ 从 ApiConfigStore 取对应配置
  ├ 重建 DeepSeekAnalyzer(config)
  └ 更新右上角状态（● 在线 / ○ 未配置）
```

---

## 7. AI 提示词设计

### 7.1 为什么分两阶段

**一阶段做不了**：

1. **13 个物种逐个评价**如果和综合报告一起生成，模型会偷懒——直接给整体结论，物种评价敷衍成"该物种较多/较少"
2. **综合报告需要看到全部评价**才能提炼"共同指向的问题"
3. **两段可以分别控制 token 和格式**：阶段一必须 JSON，阶段二必须是自然段

```
阶段一：结构化、受限（JSON）、温度低
   ↓ 全部评价作为阶段二的输入
阶段二：自由文本、要综合、要下判断
```

### 7.2 阶段一

| 项 | 值 |
|---|---|
| `json_mode` | `True`（`response_format={"type":"json_object"}`） |
| `max_tokens` | 8000 |
| 输出 | `{"species_evaluations": [{"species": "...", "comment": "...", "advice": "..."}]}` |
| 约束 | comment 40~60 字；advice 15~30 字；**不科普"这是什么虫"**；有变化数据要提及 |

**核心要求**：只讲**指示意义**（说明什么工况），不讲生物学特征。因为用户是工艺员，不是生物学家。

### 7.3 阶段二

| 项 | 值 |
|---|---|
| `json_mode` | `False`（要自然段） |
| `max_tokens` | 4000 |
| 输出格式 | 严格三行式：`情况：…` / `变化：…` / `建议：…`（2~4 条） |

**硬约束**：

- 情况 150~200 字，必须点明**主导因素**
- 变化 120 字以内，**没有变化数据就必须省略这一行**
- 禁止 markdown、禁止编号标题

**最关键的一句提示词**：

> 要主动找出多个物种**共同指向**的问题。例如多条评价都提到"溶解氧偏低"，就把这一点单独提炼出来、明确指出它是本次的主要矛盾；**不要只是把各物种结论罗列一遍**。

以及加入 J/D 之后的解读指引：

> J 偏低说明群落被少数种垄断，D 偏低说明种类贫乏，二者与 H' 合起来反映系统稳定性。

### 7.4 容错链（务必理解）

```
请求
 ├ 网络异常 ────────────────► 返回 "网络错误：…"，写 last_error.txt
 ├ HTTP != 200 ─────────────► 去掉 response_format 重试
 └ HTTP 200
     ├ content 为空 ─────────► 去掉 response_format 重试
     │    └ 仍为空 ──────────► 报错，附 usage + finish_reason
     └ content 正常 ─────────► 返回

analyze()
 ├ 阶段一失败 ──► _mock()          本地模拟，流程结束
 └ 阶段一成功
     └ 阶段二失败 ──► _fallback_report()  用各物种 advice 拼模板，source 仍是模型名
```

**`finish_reason` 的用处**：`length` 表示被截断（推理模型吃光 token），`stop` 表示正常结束。`_empty_hint()` 会据此给出不同建议。

### 7.5 降级的可见性（重要约定）

**任何降级都必须在界面上可见**，不允许静默：

| 情况 | 界面表现 |
|---|---|
| 走本地模拟 | 报告顶部黄色横幅 + 弹窗 + 状态栏 `完成 · 本地模拟` |
| 阶段二用了模板 | `source` 仍是模型名，但 `error` 非空 → 同样弹窗 |
| 有 error_text 的记录 | 回看时报告顶部挂横幅 |

---

## 8. 知识库流水线

```
PDF
 │ pymupdf 判断：该页有文字层吗？
 ├ 有 → page.get_text()                        method="text"
 └ 无 → 渲染成图 → RapidOCR 识别               method="ocr"
        ↓
knowledge/raw/<slug>.jsonl          每行 {"page": 49, "text": "...", "method": "ocr"}
        ↓  chunk_book()  约 700 字/块，overlap 120，保留书名+页码
chunks: [{"book":..., "page_start":..., "page_end":..., "text":...}]
        ↓  build_index()  jieba 分词 → BM25Okapi
knowledge/index/bm25.pkl            {"bm25": 对象, "chunks": [...]}
```

**关键脚本**：

| 脚本 | 用途 |
|---|---|
| `tools/build_knowledge.py` | 全量构建，**支持断点续跑**（读已有 jsonl 的行数，只补缺页） |
| `tools/build_index_subset.py` | 只索引指定的书（跳过没 OCR 完的） |
| `tools/verify_rag.py` | 验证检索，不调 AI |
| `tools/probe_pdfs.py` | 判断 PDF 有没有文字层 |
| `tools/ocr_probe.py` | OCR 首页确认书名（避免标错元数据） |

**书的元数据**在 `tools/build_knowledge.py` 的 `BOOKS` 列表里，**PDF 文件名必须和配置里的 `pdf` 字段完全一致**（否则会跳过，不报错）。

**版权约定**：`knowledge/books`、`raw`、`index` 全部在 `.gitignore` 里。打包时**只带 `bm25.pkl`**（约 1.3 MB），不带 PDF。

---

## 9. 界面层

### 9.1 控件树（`ui/main_window.ui`）

```
centralwidget (QWidget)
└ mainLayout (VBox)
   ├ topBar (QWidget, 卡片)
   │  └ topLayout (HBox)
   │     ├ titleBox: labelTitle / labelSubtitle
   │     ├ btnGuide          "?" 圆形，重看引导
   │     ├ topSpacer
   │     ├ labelMode / comboProvider / btnApiSettings / labelModeValue / btnMore(≡)
   ├ splitter (HBox)
   │  ├ leftPane (卡片)
   │  │  ├ btnNew
   │  │  ├ listStack (QStackedWidget)
   │  │  │   ├ listPage  → sessionList (QListWidget)
   │  │  │   └ emptyPage → labelEmptyList
   │  │  ├ labelCount / btnBatchImport
   │  │  └ (leftLayout)
   │  └ rightStack (QStackedWidget)
   │     ├ inputPage: inputText / timeInput / btnClear
   │     └ resultPage: tabResults (QTabWidget)
   │           ├ ① tblMetrics
   │           ├ ② tblEvaluations
   │           ├ ③ txtReport
   │           └ ④ trendHolder
   └ bottomLayout
      ├ labelSummary / pillBar(pillLayout)
      ├ bottomSpacer
      └ btnAnalyze / btnExport
```

### 9.2 状态栏胶囊

`_set_status(text, pills=None)` 是唯一入口：

```python
self._set_status("完成 · DeepSeek", [
    ("物种", "13"), ("H'", "2.031"), ("评价", "13/13"), ("趋势", "2"), ("对比", "历史库")
])
```

每次调用会**清空并重建** `pillLayout` 里的 QLabel（objectName=`pill`，样式在 `theme.py`）。

### 9.3 两个页面的切换

```python
_show_input_page(msg)    → rightStack.setCurrentWidget(inputPage)，btnExport 禁用
_show_result_page()      → 切到 resultPage，btnExport 启用
```

**没有记录时**停在输入页；有记录时默认选中最新的。

### 9.4 主题（`theme.py`）

所有颜色/字号/圆角集中在文件顶部的常量里，QSS 用 f-string 拼。

| 改什么 | 改哪里 |
|---|---|
| 主色调 | `PRIMARY` |
| 全局字号 | `FONT_PT`（当前 10pt） |
| 报告字号 | `main_window.REPORT_FONT_PT`（13pt） |
| 卡片圆角 | QSS 里的 `border-radius: 12px` |
| 表格行色 | `ROW_ABSOLUTE` / `ROW_DOMINANT` / `ROW_ALT` |

### 9.5 引导（`onboarding.py`）

`OnboardingOverlay(host, steps)`：全窗遮罩 + 目标控件挖洞 + 虚线箭头 + 卡片。

步骤用 `Step(title, text, target=objectName)` 定义，`target=None` 则卡片居中。

**触发条件**：

```python
FORCE_GUIDE      # main.py --guide
SUPPRESS_GUIDE   # 测试/截图时关掉
# 否则看 QSettings 的 "onboarded"
```

---

## 10. 关键设计决策

> 改代码前请先读这一节，避免"优化"掉某个刻意为之的设计。

| # | 决策 | 理由 | 如果改了会怎样 |
|---|---|---|---|
| 1 | **纯逻辑层不依赖 Qt** | 为了将来做 API / CLI / 服务端 | 引入 Qt 后服务端要装 150MB 的 GUI 库 |
| 2 | **先存指标，再算 AI** | AI 挂了数据不能丢 | 用户白等 20 秒才发现失败 |
| 3 | **失败时降级而不是报错中断** | 现场断网也要能出结果 | 甲方认为"这软件不能用" |
| 4 | **但降级必须可见** | 防止把模拟结果当真实结论 | 决策错误，责任在软件方 |
| 5 | **批量导入不调 AI** | 5 条 = 10 次请求、1~2 分钟 | 用户以为卡死 |
| 6 | **单样本 `f_i = 1`** | 一次检测没有"样点频率"概念 | 优势种判定需要历史数据才有意义 |
| 7 | **RAG 无索引时静默跳过** | 知识库是增强项不是必需项 | 没有书的用户完全无法使用 |
| 8 | **只打包 pkl，不打包 PDF** | 版权 + 体积（440MB → 1.3MB） | 侵权风险 + 交付包巨大 |
| 9 | **参考来源不显示原文** | OCR 噪声会毁掉观感（"Ｄ5 17.3 ｍｇ／Ｌ"） | 甲方觉得"这软件很粗糙" |
| 10 | **数字列右对齐 + 等宽字体** | 数据表格的可读性 | 个位数对不齐，显得不专业 |
| 11 | **`_mock()` 保留"本地模拟"字样** | 用户判断可信度的唯一依据 | 无法区分 AI 结果和模板 |
| 12 | **两个 SQLite 库分开** | 配置和业务数据生命周期不同（配置要加密、要跟人走） | 迁移/备份变得复杂 |

---

## 11. 技术债与已知缺陷

> 接手者优先处理清单。

### 🔴 高优先级

| # | 问题 | 位置 | 影响 | 建议 |
|---|---|---|---|---|
| 1 | **DPAPI 只支持 Windows** | `secure_store.py` | 上 Debian 服务端后 Key 明文落库 | 换 AES + 服务端密钥，或用系统 env |
| 2 | **SQLite 不支持多进程并发写** | `history.py` | 桌面版 + 服务版同时跑会 `database is locked` | 开 WAL；或换 PostgreSQL |
| 3 | **`last()` 不区分设备** | `history.py` | 多设备场景对比错误 | 按 `device` 过滤 |
| 4 | **`margalef_d` 硬编码 ×1e6** | `metrics.py` | 换单位后指数失真 | 从 `unit` 解析倍率 |
| 5 | **AI 调用同步阻塞在子线程** | `analyzer.py` | 单用户没问题，多并发会排队 | API 化时改 `asyncio` + 任务队列 |

### 🟡 中优先级

| # | 问题 | 影响 |
|---|---|---|
| 6 | 游泳/固着纤毛虫占比规则未实现 | 少 2 条趋势判定 |
| 7 | `_show_record` 重算指标而非读库 | 指标逻辑变更后历史数据"变脸" |
| 8 | OCR 错字导致 BM25 漏检 | 检索精度天花板 |
| 9 | 表格页 OCR 成词流 | 索引里有大量噪声块，挤占 top-k |
| 10 | `app/knowledge.py` 是死代码 | 混淆视听，可删 |
| 11 | `_PROJECT_DIR` 与 `paths.py` 重复 | 两套路径逻辑 |

### 🟢 低优先级

- `REPORT_FONT_PT` 和 `theme.FONT_PT` 分散两处
- `main_window.py` 已 730+ 行，职责偏多
- 缺类型检查（没跑 mypy）

---

## 12. 修改指南（需求 → 改哪里）

> 最常用的一节。

| 你想做 | 改哪些文件 | 注意 |
|---|---|---|
| **改优势种阈值** | `metrics.py` 顶部常量 | 同步改 `smoke_test` 的期望值 |
| **加一个指标** | `metrics.compute()` → `MetricsResult` → `build_payload()` → 提示词 | 五处都要改，漏一处 AI 看不到 |
| **改提示词** | `analyzer.py` 的 `STAGE1_TEMPLATE` / `STAGE2_TEMPLATE` | 用 `.format()`，改占位符要同步改调用处 |
| **换 AI 供应商** | 界面「API 设置」 | 只支持 OpenAI 兼容协议 |
| **加一条趋势规则** | `trend.detect_trends()` | 同步加进 `_trends_text()` 的展示 |
| **改导出的表头** | `exporter.py` 的 `_write_header` + `append` + `_autosize caps` | 三处索引要对齐 |
| **改界面布局** | `ui/main_window.ui` → `build_ui.py` | 不要手改 `app/generated/` |
| **改配色/字号** | `theme.py` 顶部常量 | |
| **加一个内置物种字典** | `rag.py` 的 `DOMAIN_WORDS` | 否则 jieba 会切碎 |
| **加一本知识库的书** | `build_knowledge.py` 的 `BOOKS` | PDF 文件名必须和 `pdf` 字段一致 |
| **加一个新记录字段** | `history.py` 六处（见 §4.6） | 最容易漏 |
| **做 API 化** | 新增 `service.py` + `api/`，**不动** `app/*` | 纯逻辑层已就绪 |

### 加字段的标准动作（六处）

```
1. CREATE TABLE           加列
2. _EXTRA_COLUMNS         加迁移项
3. _COLS                  加查询列
4. Record                 加 dataclass 字段
5. save()                 加 INSERT 列 + ? + 参数
6. update_analysis()      加 SET + 参数
7. _to_record()           加 row[i] 索引
```

> 实际是 7 处。少改任何一处，轻则数据丢失，重则 `TypeError` 崩溃。

---

## 13. 测试

### 冒烟测试（136 项）

```bat
.venv\Scripts\python.exe tools\smoke_test.py
```

| 节 | 覆盖 |
|---|---|
| 1 | 解析 / 计算（含 H'=2.031、D=0.796、J=0.792、优势种 4 个） |
| 2 | 输入格式容忍度（8 种） |
| 3 | 批量导入 |
| 4 | 变化计算 + 趋势规则 |
| 5 | 记录库（存/读/回填/删除） |
| 6 | API 配置 |
| 7 | **中转站兼容性（离线，喂假响应）** |
| 8 | AI 两阶段（需网络） |
| 9 | 导出（sheet 数 / 表头 / 行数） |
| 10 | 界面（offscreen 渲染） |

**三个必须知道的约定**：

1. 用**临时数据库**（`tempfile`），不碰 `data/history.db`
2. 界面用 `QT_QPA_PLATFORM=offscreen`
3. **必须关掉模态弹窗**（`FIRST_RUN_HINT=False`、`SHOW_ERROR_DIALOG=False`），否则测试会**永久挂起**——这是踩过的坑

### 界面截图

```bat
.venv\Scripts\python.exe tools\gui_preview.py
```

生成 `output/preview_*.png`。用于人工检查视觉问题（文字截断、颜色、对齐）——这些冒烟测试看不出来。

---

## 14. 打包

```bat
build_exe.bat
```

四个步骤：编译 UI → PyInstaller → 复制 `bm25.pkl` → 压缩。

产出 `output/特征微生物分析工具_Demo.zip`（约 90 MB），内容只有：

```
特征微生物分析工具\
├── 特征微生物分析工具.exe
├── _internal\              依赖
└── knowledge\index\bm25.pkl
```

**不带** PDF / raw / 说明文档。

### 打包三个坑

| 坑 | 现象 | 处理 |
|---|---|---|
| `base_library.zip` 被占用 | `Compress-Archive` 报权限错误 | 改用 Python `zipfile`；或等杀软扫描完 |
| 忘了 `build_ui.py` | 启动即 `ImportError: ui_main_window` | 打包前必跑 |
| 路径写死 | 打包后找不到资源 | 一律用 `paths.app_root()` / `bundle_dir()` |

---

## 15. 术语表

| 术语 | 含义 |
|---|---|
| **生物相** | 活性污泥里微型动物（原生动物 + 后生动物）的种类和数量构成 |
| **优势种** | 优势度 `Y > 0.05`，对群落起主导作用的物种 |
| **绝对优势种** | 相对丰度 ≥ 10%（本项目自定义分档） |
| **H'（Shannon）** | 多样性指数，兼顾种类数和均匀度 |
| **D（Margalef）** | 丰富度指数，只看种类数相对个体数 |
| **J（Pielou）** | 均匀度指数，`H'/lnS`，1 表示完全均匀 |
| **RAG** | Retrieval-Augmented Generation，先检索再生成 |
| **BM25** | 一种词项检索打分算法（TF-IDF 的改进） |
| **chunk** | 从书上切下来的文本块（约 700 字），检索的基本单位 |
| **降级 / 本地模拟** | AI 不可用时用模板生成结果，流程不中断 |
| **payload** | 业务层传给 AI 层的结构化数据（见 §4.4） |
| **ROM** | 本次范围外，但值得知道的：`standby` 待机段、`SRT` 污泥龄 |

---

## 附录：一句话说清每个模块

```
parser    文本 → 结构化数据
metrics   数据 → 指标
trend     数据 → 变化与趋势判定
times     字符串 → 时间对象
history   记录 → SQLite
batch     长文本 → 多条记录
analyzer  数据 → AI 报告（唯一有网络副作用的地方）
rag       查询 → 文献片段
exporter  全部 → Excel
secure    明文 → 密文
api_config 配置 → 数据库
paths     环境 → 路径
```

---

> 有疑问优先看代码，其次看本文档。
> 改完记得跑 `tools/smoke_test.py`。