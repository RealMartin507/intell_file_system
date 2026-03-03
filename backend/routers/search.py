"""
搜索路由

GET /api/search
  q     : 关键词，空格分隔多词（AND 逻辑）
  type  : 文件类型筛选（file_type 字段值）
  sort  : relevance / modified / name / size
  page  : 页码（从 1 开始）
  size  : 每页条数（1-200）

搜索策略：
  1. FTS5 全文搜索（unicode61 tokenizer，速度快）
  2. LIKE 兜底（每个词 AND，支持中文）
  3. 两者结果取并集
"""

from typing import Any, Optional

from fastapi import APIRouter, Query

from backend.database import get_db

router = APIRouter(tags=["search"])

# 单次 FTS / LIKE 各自最多取多少 ID（避免 SQLite 参数数量超限）
_MAX_HITS = 800

_SORT_MAP = {
    "modified": "f.modified_time DESC",
    "name":     "f.file_name COLLATE NOCASE ASC",
    "size":     "f.file_size DESC",
}


# ── 内部工具 ────────────────────────────────────────────────────────────────────

def _tokenize(q: str) -> list[str]:
    """按空格拆词，过滤空串。"""
    return [t.strip() for t in q.split() if t.strip()]


def _build_fts_expr(terms: list[str]) -> str:
    """构造 FTS5 MATCH 表达式：每词双引号包裹（防注入），词间空格 = AND。"""
    return " ".join(f'"{t.replace(chr(34), "")}"' for t in terms)


def _get_fts_ids(conn, terms: list[str]) -> set[int]:
    """FTS5 全文搜索，失败时静默返回空集合（如 tokenizer 不支持该词形）。"""
    try:
        rows = conn.execute(
            "SELECT rowid FROM files_fts WHERE files_fts MATCH ? LIMIT ?",
            (_build_fts_expr(terms), _MAX_HITS),
        ).fetchall()
        return {r[0] for r in rows}
    except Exception:
        return set()


def _get_like_ids(conn, terms: list[str], type_filter: Optional[str]) -> set[int]:
    """LIKE 兜底搜索：对每个词做 file_name OR file_path 匹配，词间 AND 逻辑。"""
    conds = " AND ".join("(file_name LIKE ? OR file_path LIKE ?)" for _ in terms)
    params: list[Any] = [x for t in terms for x in (f"%{t}%", f"%{t}%")]
    if type_filter:
        conds += " AND file_type = ?"
        params.append(type_filter)
    rows = conn.execute(
        f"SELECT id FROM files WHERE {conds} LIMIT ?",
        params + [_MAX_HITS],
    ).fetchall()
    return {r[0] for r in rows}


def _sort_by_relevance(
    records: list[dict], fts_set: set[int], first_term: str
) -> list[dict]:
    """
    相关度排序（Python 侧稳定排序）：
      优先级1：FTS5 命中 > 仅 LIKE 命中
      优先级2：文件名包含首词 > 仅路径包含
      优先级3：修改时间倒序（越新越前）
    """
    # 先按修改时间倒序（稳定排序基础）
    records.sort(key=lambda r: r.get("modified_time") or "", reverse=True)
    # 再按相关度升序覆盖（稳定排序保留时间顺序作次序）
    records.sort(key=lambda r: (
        0 if r["id"] in fts_set else 1,
        0 if first_term in (r.get("file_name") or "").lower() else 1,
    ))
    return records


def _group_shapefiles(rows: list[dict]) -> list[dict]:
    """
    将同一 shapefile_group 的文件合并为一条记录：
    - 优先选 .shp 文件作为代表（替换时保留 related_count）
    - related_count 记录本次搜索结果中该组的文件数
    - 非 shapefile 的文件 related_count = None
    """
    seen: dict[str, int] = {}   # group_key -> result 列表下标
    result: list[dict] = []

    for row in rows:
        sg = row.get("shapefile_group")
        if sg:
            if sg in seen:
                idx = seen[sg]
                result[idx]["related_count"] += 1
                # 遇到 .shp 文件则替换为代表，保留计数
                if row["extension"] == ".shp":
                    cnt = result[idx]["related_count"]
                    result[idx] = {**row, "related_count": cnt}
            else:
                seen[sg] = len(result)
                result.append({**row, "related_count": 1})
        else:
            result.append({**row, "related_count": None})

    return result


# ── 主接口 ─────────────────────────────────────────────────────────────────────

@router.get("/search")
async def search_files(
    q: str = Query("", description="搜索关键词，空格分隔多词（AND 逻辑）"),
    type: Optional[str] = Query(None, description="文件类型：document/image/gis_vector 等"),
    sort: str = Query("relevance", description="排序：relevance / modified / name / size"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=200),
):
    terms = _tokenize(q)
    conn = get_db()
    try:
        # ── q 为空：只按 type / sort 浏览，不做文本搜索 ───────────────────────
        if not terms:
            if not type:
                return {"total": 0, "page": page, "size": size, "items": []}

            order_sql = _SORT_MAP.get(sort, "f.modified_time DESC")
            offset = (page - 1) * size

            total_row = conn.execute(
                "SELECT COUNT(*) FROM files f WHERE f.file_type = ?", (type,)
            ).fetchone()
            total = total_row[0] if total_row else 0

            rows = conn.execute(
                f"""
                SELECT f.id, f.file_name, f.extension, f.file_type, f.file_size,
                       f.modified_time, f.parent_dir, f.file_path, f.shapefile_group
                FROM files f
                WHERE f.file_type = ?
                ORDER BY {order_sql}
                LIMIT ? OFFSET ?
                """,
                (type, size, offset),
            ).fetchall()

            return {
                "total": total,
                "page": page,
                "size": size,
                "items": [dict(r) for r in rows],
            }

        # ── 有关键词：FTS5 + LIKE 合并搜索 ───────────────────────────────────
        # ① FTS5 搜索
        hits_fts = _get_fts_ids(conn, terms)

        # ② LIKE 兜底（中文支持），始终执行，结果与 FTS5 取并集
        hits_like = _get_like_ids(conn, terms, type)

        all_ids = list(hits_fts | hits_like)
        if not all_ids:
            return {"total": 0, "page": page, "size": size, "items": []}

        # ③ 按 ID 拉取完整字段
        ph = ",".join("?" * len(all_ids))
        extra_where: str = ""
        extra_params: list[Any] = []
        if type:
            # FTS5 未过滤 type，此处补充
            extra_where = " AND f.file_type = ?"
            extra_params = [type]

        order_clause = ""
        if sort != "relevance":
            order_clause = f"ORDER BY {_SORT_MAP.get(sort, 'f.modified_time DESC')}"

        rows = conn.execute(
            f"""
            SELECT f.id, f.file_name, f.extension, f.file_type, f.file_size,
                   f.modified_time, f.parent_dir, f.file_path, f.shapefile_group
            FROM files f
            WHERE f.id IN ({ph}){extra_where}
            {order_clause}
            """,
            all_ids + extra_params,
        ).fetchall()

        records = [dict(r) for r in rows]

        # ④ relevance 排序（在 Python 侧完成，可利用 FTS5 命中集合）
        if sort == "relevance":
            records = _sort_by_relevance(records, hits_fts, terms[0].lower())

        # ⑤ Shapefile 分组（合并同组文件，保持排序）
        grouped = _group_shapefiles(records)

        # ⑥ 分页
        total = len(grouped)
        offset = (page - 1) * size
        items = grouped[offset: offset + size]

        return {"total": total, "page": page, "size": size, "items": items}

    finally:
        conn.close()
