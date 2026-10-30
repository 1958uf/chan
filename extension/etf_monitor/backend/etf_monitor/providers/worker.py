"""隔离AKShare工作进程：只执行固定白名单，第三方日志不污染JSON协议。"""
import contextlib
import io
import json
import sys

ALLOWED = {
    "fund_etf_hist_em", "fund_etf_hist_min_em", "fund_open_fund_info_em",
    "tool_trade_date_hist_sina", "stock_margin_sse", "stock_margin_szse",
    "stock_sse_deal_daily", "stock_szse_summary",
}


def main():
    """功能：执行单次白名单调用；输入：stdin JSON；输出：stdout JSON及退出码。"""
    try:
        request = json.load(sys.stdin)
        name = request["function"]
        if name not in ALLOWED:
            raise ValueError("不允许调用该函数")
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            import akshare as ak
            frame = getattr(ak, name)(**request.get("kwargs", {}))
            # pandas处理时间和缺失值，最终再用标准JSON保证无NaN。
            rows = json.loads(frame.to_json(orient="records", date_format="iso", force_ascii=False))
        json.dump({"ok": True, "rows": rows}, sys.stdout, ensure_ascii=False, allow_nan=False)
        return 0
    except Exception as exc:
        json.dump({"ok": False, "error": f"{type(exc).__name__}: {exc}"}, sys.stdout, ensure_ascii=False)
        return 1


if __name__ == "__main__":
    sys.exit(main())
