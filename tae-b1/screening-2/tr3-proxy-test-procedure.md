# TR-3 代理连通性测试步骤（给 Hermes，2 分钟）

目的：VPS 路线已死（2026-10-31 实测交易接口全 451）。验 Hermes 机器上的代理能不能走到币安**交易接口**——公开行情通不等于交易接口通。

## 要求

- 在 Hermes 的机器上跑（代理 `127.0.0.1:7890` 所在的那台）。
- **不需要 API key**：ping 与 time 均为公开端点。绝不用 key 测。

## 命令

```bash
curl -sS -m 15 -x http://127.0.0.1:7890 https://api.binance.com/api/v3/ping; echo
curl -sS -m 15 -x http://127.0.0.1:7890 https://api.binance.com/api/v3/time; echo
curl -sS -m 15 -x http://127.0.0.1:7890 https://testnet.binance.vision/api/v3/ping; echo
curl -sS -m 15 -x http://127.0.0.1:7890 "https://api.binance.com/api/v3/exchangeInfo?symbol=BTCUSDT" | head -c 200; echo
```

ccxt 版（与现有代码一致）：

```python
import ccxt
ex = ccxt.binance({"proxies": {"http": "http://127.0.0.1:7890", "https": "http://127.0.0.1:7890"}, "timeout": 15000})
print(ex.fetch_status())
```

## 判读

| 结果 | 含义 |
|---|---|
| ping 返回 `{}`，time 返回 `serverTime` | 代理可走交易接口，Hermes 机器可作执行器主机候选 |
| 返回 `{"code":0,"msg":"Service unavailable from a restricted location..."}` 或 451 | 代理出口同样被拦，Hermes 机器也不可作主机 |
| 超时/连接失败 | 代理本身不稳，先修代理，再重测 |

## 回报格式

把 4 条命令的原样输出贴回仓内新文件（或经用户转交），注明测试时间（UTC）。不贴任何 key。
