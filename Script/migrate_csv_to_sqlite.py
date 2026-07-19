"""
CSV -> SQLite 一次性迁移脚本

功能说明：
    - 遍历 chan_cache/{code}_{k_type}.csv，将历史 K 线导入 chan.db 的 kline 表
    - 旧 CSV 仅含 OHLC，volume/turnover/turnrate 写 NULL（后续增量更新时补齐）
    - 幂等：可重复运行，INSERT OR REPLACE 天然去重

使用方法：
    python Script/migrate_csv_to_sqlite.py
    python Script/migrate_csv_to_sqlite.py --cache chan_cache --db chan.db
"""
import argparse
import os
import sys
from pathlib import Path

# 将项目根目录加入路径，以便导入 chan 模块
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from Common.CEnum import AUTYPE  # noqa: E402
from DataAPI.sqlite_cache import ChanSqliteCache  # noqa: E402


def _parse_row(line: str):
    """解析一行 CSV（time,open,high,low,close[,volume,turnover,turnrate]）。
    功能：兼容旧版 5 列与含成交流的扩展列
    输入：line - 一行 CSV 文本
    输出：(date, open, high, low, close, volume, turnover, turnrate) 或 None（跳过空行）
    """
    parts = line.strip().split(",")
    if len(parts) < 5:
        return None
    date = parts[0]
    # 跳过 OHLC 任一为空的行（停牌日）
    if any(v == "" for v in parts[1:5]):
        return None
    open_ = _to_float(parts[1])
    high = _to_float(parts[2])
    low = _to_float(parts[3])
    close = _to_float(parts[4])
    volume = _to_float(parts[5]) if len(parts) > 5 and parts[5] != "" else None
    turnover = _to_float(parts[6]) if len(parts) > 6 and parts[6] != "" else None
    turnrate = _to_float(parts[7]) if len(parts) > 7 and parts[7] != "" else None
    return (date, open_, high, low, close, volume, turnover, turnrate)


def _to_float(v):
    """安全转浮点，空值返回 None。"""
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (ValueError, TypeError):
        return None


def migrate(cache_dir: str, db_path: str) -> None:
    """执行迁移：遍历 CSV -> 导入 SQLite。
    功能：读取 chan_cache 下所有 {code}_{k_type}.csv，批量写入 kline 表
    输入：cache_dir - CSV 缓存目录；db_path - SQLite 库路径
    输出：无（结果打印到控制台）
    """
    cache = ChanSqliteCache(db_path)
    cache_path = Path(cache_dir)
    if not cache_path.exists():
        print(f"缓存目录不存在：{cache_dir}")
        cache.close()
        return

    csv_files = sorted(cache_path.glob("*.csv"))
    total = len(csv_files)
    print(f"发现 {total} 个 CSV 缓存文件，开始迁移到 {db_path} ...")
    if total == 0:
        cache.close()
        return

    imported_files = 0
    imported_rows = 0
    for i, csv_file in enumerate(csv_files, 1):
        # 文件名格式 {code}_{k_type}.csv，如 sh.600519_day.csv
        name = csv_file.stem  # sh.600519_day
        # 从右切第一个下划线分隔 code 与 k_type
        idx = name.rfind("_")
        if idx < 0:
            continue
        code = name[:idx]
        k_type = name[idx + 1:]
        if not code or not k_type:
            continue

        rows = []
        with open(csv_file, "r", encoding="utf-8") as f:
            header = True
            for line in f:
                if header:
                    header = False
                    continue
                parsed = _parse_row(line)
                if parsed:
                    rows.append(parsed)

        if rows:
            cache.upsert_many(code, k_type, AUTYPE.QFQ, rows)
            imported_files += 1
            imported_rows += len(rows)

        # 进度显示
        pct = i / total * 100
        sys.stdout.write(f"\r迁移进度: {pct:5.1f}% ({i}/{total}) | {csv_file.name:<28}")
        sys.stdout.flush()

    print(f"\n迁移完成：导入 {imported_files}/{total} 个文件，共 {imported_rows} 行。")
    print(f"kline 表 day 周期总行数：{cache.row_count(k_type='day')}")
    cache.close()


def main():
    """命令行入口。"""
    parser = argparse.ArgumentParser(description="将 chan_cache CSV 缓存迁移到 SQLite")
    parser.add_argument("--cache", default="chan_cache", help="CSV 缓存目录（默认 chan_cache）")
    parser.add_argument("--db", default="chan.db", help="SQLite 库路径（默认 chan.db）")
    args = parser.parse_args()

    # 切到项目根目录运行（相对路径以根目录为基准）
    root = Path(__file__).resolve().parent.parent
    os.chdir(root)

    migrate(args.cache, args.db)


if __name__ == "__main__":
    main()
