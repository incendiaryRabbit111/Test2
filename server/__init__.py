"""HTTP API 服务层。

只做协议适配，不复制分析算法：
  - 请求校验（Pydantic）
  - 调用现有 parser/metrics/trend/history/analyzer
  - 把结果序列化成 JSON

现有 PySide6 桌面端不依赖本包，二者可以独立运行。
"""
