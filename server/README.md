# 后端 API（第一版）

这一层只负责把现有分析链路暴露成 HTTP 接口，不修改解析、指标、趋势和 AI 提示词。
API 使用独立数据目录 `data/api/`，不会读写桌面端的 `data/history.db` 和
`data/api_configs.db`。

## 启动

```bat
start_api.bat
```

启动后：

- 健康检查：<http://127.0.0.1:8000/health>
- 接口文档：<http://127.0.0.1:8000/docs>

停止：控制台按 `Ctrl+C`，或直接关闭窗口。

### 同一 WiFi 联调

推荐直接使用：

```bat
start_api_lan.bat
```

它会：

- 请求管理员权限；
- 监听 `0.0.0.0`；
- 添加仅专用网络/本子网的防火墙规则；
- 读取或生成 `data/api/lan_api_key.txt`；
- 打印本机 IPv4 和 API Key；
- 启动后端。

也可以指定端口：

```bat
start_api_lan.bat 8001
```

仪器端请求地址：

```text
http://电脑局域网IP:8000/api/v1/evaluate
```

并带请求头：

```http
X-API-Key: 控制台打印的令牌
```

注意：

- Windows 网络必须设置为“专用网络”，否则防火墙规则不生效；
- 规则只允许本子网，不要对公网做端口映射；
- 普通本机测试仍用 `start_api.bat`。

## 接口

### `GET /health`

```json
{"status": "ok", "name": "特征微生物分析工具 API", "version": "0.1.0", "data_dir": "..."}
```

### `POST /api/v1/evaluate`

请求体是**裸文本**，不是 JSON：

```http
POST /api/v1/evaluate
Content-Type: text/plain; charset=utf-8

表壳虫：2.15，匣壳虫：0.42，内管虫：0.31，轮虫：0.21，线虫：0.15，袋鞭虫：0.12，扭曲管叶虫：0.09，钟虫：0.06，盖纤虫：0.05，累枝虫：0.04，楯纤虫：0.03，摩门虫：0.02，斜管虫：0.02
```

成功返回 `metrics`、`changes`、`trends`、`evaluations`、`report_text`、
`warnings`、`references`、`meta`。

对这行样例，预期：

```text
species_count = 13
total = 3.67
shannon_h = 1.538
margalef_d = 0.794
pielou_j = 0.600
```

AI 未配置或调用失败时返回 HTTP 200，`status` 为 `degraded`，指标仍然可用。

### 采样时间

单条评价可以用 query 或 Header 指定采样时间：

```http
POST /api/v1/evaluate?sample_time=2026-11-11%2008%3A00%3A00
X-Sample-Time: 2026-11-11 08:00:00
```

优先使用 query；没传时使用服务器接收时间，并在响应里返回：

```json
{
  "sample_time": "2026-11-11 08:00:00",
  "time_source": "client"
}
```

`time_source` 可能是：

```text
client       客户端提供
received     服务器接收时间兜底
segment      批量段内自带
inferred     按 start_time + interval 推算
无           批量数据没有时间
```

### `POST /api/v1/batch/preview`

只预览批量文本，不写库：

```http
POST /api/v1/batch/preview?start_time=2026-10-09%2008%3A00%3A00&interval_min=60
Content-Type: text/plain; charset=utf-8
```

多段之间用空行或 `---` 分隔。返回每段的解析结果、指标、时间来源和警告。

### `POST /api/v1/batch/import`

同样的请求，写入 API 独立历史库：

```http
POST /api/v1/batch/import?start_time=2026-10-09%2008%3A00%3A00&interval_min=60
Content-Type: text/plain; charset=utf-8
```

批量导入**不调用 AI**。每条记录会本地计算指标、变化和趋势，并返回 `batch_id`
和 `record_id`。批次内第一条没有变化基准，之后和批次内上一条比较。

### `POST /api/v1/batch/{batch_id}/analyze-last`

只对批次最后一条调用 AI：

```http
POST /api/v1/batch/7b65ec09b822/analyze-last
```

前面各条只使用本地指标、变化和趋势，不会逐条调用大模型。响应除了最后一条的
`metrics`、`changes`、`trends`、`evaluations`、`report_text` 外，还会返回：

```json
{
  "history_context": "【批次历史摘要】...",
  "meta": {
    "batch_records": 5,
    "previous_time": "..."
  }
}
```

`history_context` 就是实际放进 AI 提示词的批次摘要，包含首末对比、最近记录、
关键物种轨迹、趋势统计和数据质量说明。导入后最后一条的报告会回填到原记录，
不会新建一条记录。

### `GET /api/v1/batch/{batch_id}/records`

查看批次内每条的本地指标、变化、趋势和是否已有报告，供前端做选择：

```json
{
  "batch_id": "...",
  "count": 5,
  "records": [
    {
      "record_id": 1,
      "index": 1,
      "sample_time": "2026-10-01 08:00:00",
      "time_source": "段内自带",
      "metrics": {"species_count": 4, "total": 2.4},
      "changes": [],
      "trends": [],
      "has_report": false,
      "analysis_source": "",
      "error_text": ""
    }
  ]
}
```

### `POST /api/v1/batch/{batch_id}/analyze/{record_id}`

分析批次内任意一条，而不是只能分析最后一条：

```http
POST /api/v1/batch/7b65ec09b822/analyze/3
```

关键规则：分析第 3 条时，`history_context` 只取第 1~2 条，**不会把第 4 条以后的数据喂给 AI**。
目标记录的报告会回填到原记录，不新增记录。

## 历史与反馈

桌面端 API 模式会用这些接口：

```http
GET    /api/v1/history?limit=100&offset=0
GET    /api/v1/history/{record_id}
DELETE /api/v1/history/{record_id}
GET    /api/v1/trends?limit=500
```

- `/history` 返回列表摘要，含 `has_report` 和 `feedback`；
- `/history/{id}` 返回完整物种、指标、变化、趋势、报告和反馈；
- `/trends` 按时间升序返回趋势图数据；
- 删除历史会同时删除对应反馈，并移出历史案例库。

### 点赞/点踩

只对整份报告反馈：

```http
POST /api/v1/history/{record_id}/feedback
Content-Type: application/json

{"verdict": "up", "note": "结论准确"}
```

撤销：

```http
DELETE /api/v1/history/{record_id}/feedback
```

规则：

- `up` 且报告非空、真实 AI 成功，才进入内部历史案例库；
- `down` 不进入；
- 重新分析导致报告变化时，旧反馈自动失效；
- 历史案例只作为 AI 提示词里的内部经验，**不在客户端响应里展示引用**；
- 删除反馈就是移出历史案例库，原始历史记录保留。

## 用户导入知识

用户导入的知识保存在 `data/api/knowledge/`，会和内置知识库合并后重新构建
BM25 索引。下一次评价就能检索到。

### 导入纯文字

```http
POST /api/v1/knowledge/text
Content-Type: application/json
```

```json
{
  "title": "现场经验：表壳虫",
  "content": "表壳虫数量突然升高，通常说明污泥龄偏长或有机负荷偏低。"
}
```

### 导入文字版 PDF

```http
POST /api/v1/knowledge/pdf
Content-Type: multipart/form-data
```

表单字段名为 `file`，只支持有文字层的 PDF；扫描版 PDF 会返回 422，需要先 OCR。

### 查看、检索、删除

```text
GET    /api/v1/knowledge
GET    /api/v1/knowledge/status
GET    /api/v1/knowledge/search?q=表壳虫&top_k=6
DELETE /api/v1/knowledge/{doc_id}
```

`GET /knowledge/search` 是调试用接口，可以直接确认用户导入的内容有没有进入检索结果。
评价返回的 `references` 也会包含用户知识；如果用户知识匹配，最多保留 2 个检索位置，
避免被内置的 341 个文本块全部挤掉。

## Postman 测试

1. 先调 `GET /health`；
2. 新建 `POST /api/v1/evaluate`；
3. Body 选 `raw`，格式选 `Text`，贴入固定文本；
4. Header 设置 `Content-Type: text/plain; charset=utf-8`；
5. 请求超时建议设置 120 秒。

参数错误返回结构化 422；文本解析失败时也会返回 422，并在 `error.message` 中说明原因。

## Qt 调试台

启动后端后，打开桌面程序，点右上角 `≡` → **API 调试台 / 知识库**。

- `API 地址`：本机填 `http://127.0.0.1:8000`；局域网填 `http://电脑IP:8000`
- `X-API-Key`：后端设置 `MICROBE_API_KEY` 时填写
- `调用 API 分析`：裸文本 → `/api/v1/evaluate`
- `知识库`：导入文字、文字版 PDF，刷新/删除用户知识

调试台走真实 HTTP，不调用本地分析函数；原来的桌面分析按钮仍然保留本地流程，方便对照。

## 当前边界

- 只接受固定文本，不接受 JSON；
- 知识只支持纯文字和文字版 PDF，扫描版 PDF 暂不支持；
- 用户导入的知识是全局共享的，不分用户；
- 同步返回，不做异步任务；
- 不提供 Excel 导出、历史列表和配置管理接口；
- 独立数据库，与桌面端历史互不相通；
- 第一版未做 HTTPS、限流和 Windows 服务化。
