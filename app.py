# app.py
# TeachCalendar Wizard / Teaching Agent Suite - Single-file Streamlit app (deployable)
# Focus:
# 1) "基座"：培养方案 PDF 抽取 1-11 + 附表(7-10) 自动抽取 & 多页合并
# 2) "模板"：把上传的 Word 范本自动改成“带标签的模板”，可下载（先不填充）
# 3) 路由/页面函数齐全：避免 NameError；Streamlit keys 规整：避免 DuplicateElementKey / ValueAssignmentNotAllowedError
#
# Dependencies (requirements.txt):
# streamlit, pandas, pdfplumber, python-docx, numpy, matplotlib, pillow
#
from __future__ import annotations

import base64
import datetime as dt
import hashlib
import io
import json
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

# Optional imports (fail-safe)
try:
    import pdfplumber
except Exception as _e:
    pdfplumber = None

try:
    from docx import Document
except Exception:
    Document = None


# -----------------------------
# Utils
# -----------------------------
APP_TITLE = "TeachCalendar Wizard"
APP_VERSION = "v0.8.3"

def _now_str() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())

def _short_id(s: str) -> str:
    return hashlib.md5(s.encode("utf-8")).hexdigest()[:10]

def _safe_text(x: Any) -> str:
    if x is None:
        return ""
    return str(x).replace("\u00a0", " ").strip()

def _compact_lines(s: str) -> str:
    s = (s or "").replace("\u00a0", " ")
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()

def _join_pages(pages_text: List[str]) -> str:
    return _compact_lines("\n\n".join([t or "" for t in pages_text]))

def _jsonable(obj: Any) -> Any:
    """Make payload JSON serializable (DataFrame/bytes/datetime/numpy)."""
    # DataFrame
    if isinstance(obj, pd.DataFrame):
        df = obj.copy().fillna("")
        return {"__type__": "dataframe", "columns": [str(c) for c in df.columns], "data": df.astype(str).values.tolist()}
    # bytes
    if isinstance(obj, (bytes, bytearray)):
        return {"__type__": "bytes_base64", "data": base64.b64encode(bytes(obj)).decode("ascii")}
    # datetime/date
    if isinstance(obj, (dt.datetime, dt.date)):
        return obj.isoformat()
    # Path
    if isinstance(obj, Path):
        return str(obj)
    # list/tuple/set
    if isinstance(obj, (list, tuple, set)):
        return [_jsonable(x) for x in obj]
    # dict
    if isinstance(obj, dict):
        return {str(k): _jsonable(v) for k, v in obj.items()}
    # numpy scalars/arrays
    try:
        import numpy as np
        if isinstance(obj, (np.integer, np.floating, np.bool_)):
            return obj.item()
        if isinstance(obj, np.ndarray):
            return obj.tolist()
    except Exception:
        pass
    # fallback
    try:
        json.dumps(obj)
        return obj
    except Exception:
        return str(obj)


# -----------------------------
# State / Projects
# -----------------------------
@dataclass
class Project:
    project_id: str
    name: str
    updated_at: str

def _init_state():
    if "projects" not in st.session_state:
        pid = _short_id(_now_str())
        st.session_state.projects = [Project(project_id=pid, name=f"默认项目-{time.strftime('%Y%m%d-%H%M')}", updated_at=_now_str())]
        st.session_state.active_project_id = pid

    if "project_data" not in st.session_state:
        # project_id -> payload dict
        st.session_state.project_data = {}

    if "logo_bytes" not in st.session_state:
        st.session_state.logo_bytes = None

    if "template_tag_maps" not in st.session_state:
        # project_id -> {"tags":..., "meta":...}
        st.session_state.template_tag_maps = {}


# -----------------------------
# Sidebar
# -----------------------------
def ui_sidebar_brand():
    with st.sidebar:
        col1, col2 = st.columns([1, 4])
        with col1:
            if st.session_state.logo_bytes:
                st.image(st.session_state.logo_bytes, width=44)
            else:
                svg = """
                <div style="width:44px;height:44px;border-radius:50%;
                            background:#2f6fed;display:flex;align-items:center;justify-content:center;
                            color:white;font-weight:800;font-family:Arial;">
                  TC
                </div>
                """
                components.html(svg, height=50)
        with col2:
            st.markdown(f"**{APP_TITLE}**")
            st.caption(f"{APP_VERSION} · 基座抽取 + 模板打标签")

        up = st.file_uploader("上传 Logo（可选，png/jpg）", type=["png", "jpg", "jpeg"], key="logo_uploader")
        if up is not None:
            st.session_state.logo_bytes = up.getvalue()


def ui_project_sidebar() -> Project:
    ui_sidebar_brand()
    with st.sidebar:
        st.divider()
        st.markdown("### 项目")
        labels = {p.project_id: f"{p.name} ({p.project_id})" for p in st.session_state.projects}
        ids = list(labels.keys())
        idx = ids.index(st.session_state.active_project_id) if st.session_state.active_project_id in ids else 0
        pid = st.selectbox("选择项目", options=ids, format_func=lambda x: labels[x], index=idx, key="project_select")
        st.session_state.active_project_id = pid
        return {p.project_id: p for p in st.session_state.projects}[pid]


def _render_top_header(project: Project):
    html = f"""
    <div style="border:1px solid #e7eefc; background:#f6f9ff; padding:16px 18px; border-radius:14px;">
      <div style="font-weight:900; font-size:26px;">教学文件工作台</div>
      <div style="color:#666; margin-top:4px; font-size:13px;">
        项目： <b>{project.name}</b>（{project.project_id}） · 最后更新： {project.updated_at}
      </div>
    </div>
    """
    st.markdown(html, unsafe_allow_html=True)


# -----------------------------
# PDF -> Base (1-11) + Appendix tables (7-10) merging
# -----------------------------
_SECTION_PATTERNS: List[Tuple[str, List[str]]] = [
    ("1", [r"^\s*(一|1)[、\.\s]*培养目标\b"]),
    ("2", [r"^\s*(二|2)[、\.\s]*毕业要求\b"]),
    ("3", [r"^\s*(三|3)[、\.\s]*专业定位与特色\b"]),
    ("4", [r"^\s*(四|4)[、\.\s]*主干学科\b", r"^\s*(四|4)[、\.\s]*主干学科.*核心课程", r"^\s*(四|4)[、\.\s]*主干学科.*实践"]),
    ("5", [r"^\s*(五|5)[、\.\s]*标准学制\b", r"^\s*(五|5)[、\.\s]*标准学制与授予学位\b"]),
    ("6", [r"^\s*(六|6)[、\.\s]*毕业条件\b"]),
    ("7", [r"^\s*(七|7)[、\.\s]*专业教学计划表\b"]),
    ("8", [r"^\s*(八|8)[、\.\s]*学分统计表\b"]),
    ("9", [r"^\s*(九|9)[、\.\s]*教学进程表\b"]),
    ("10", [r"^\s*(十|10)[、\.\s]*课程设置对毕业要求支撑关系表\b"]),
    ("11", [r"^\s*(十一|11)[、\.\s]*课程设置逻辑思维导图\b"]),
]

def _read_pdf_pages_text(pdf_bytes: bytes) -> List[str]:
    if pdfplumber is None:
        return ["[错误] 未安装 pdfplumber，无法解析 PDF。"]
    pages = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for p in pdf.pages:
            txt = p.extract_text() or ""
            pages.append(_compact_lines(txt))
    return pages

def _find_heading_positions(full_text: str) -> List[Tuple[str, int]]:
    hits: List[Tuple[str, int]] = []
    # Use multiline anchors; search each pattern
    for sec_id, pats in _SECTION_PATTERNS:
        pos = None
        for pat in pats:
            m = re.search(pat, full_text, flags=re.MULTILINE)
            if m:
                pos = m.start()
                break
        if pos is not None:
            hits.append((sec_id, pos))
    hits.sort(key=lambda x: x[1])
    return hits

def _build_section_spans(full_text: str) -> Dict[str, Tuple[int, int]]:
    hits = _find_heading_positions(full_text)
    spans: Dict[str, Tuple[int, int]] = {}
    for i, (sec_id, start) in enumerate(hits):
        end = hits[i + 1][1] if i + 1 < len(hits) else len(full_text)
        spans[sec_id] = (start, end)
    return spans

def _strip_heading_line(chunk: str) -> str:
    # remove first heading line
    chunk = re.sub(r"^\s*(一|二|三|四|五|六|七|八|九|十|十一|\d{1,2})[、\.\s]*[^\n]{0,40}\n", "", chunk)
    return _compact_lines(chunk)

def _extract_section_text(full_text: str, spans: Dict[str, Tuple[int, int]], sec_id: str) -> str:
    if sec_id not in spans:
        return ""
    s, e = spans[sec_id]
    return _strip_heading_line(full_text[s:e])

def _valid_table_settings_lines() -> dict:
    # Stable-ish settings for pdfplumber tables
    return dict(
        vertical_strategy="lines",
        horizontal_strategy="lines",
        snap_tolerance=3,
        join_tolerance=3,
        edge_min_length=3,
        intersection_tolerance=3,
        text_tolerance=3,
    )

def _extract_tables_with_meta(pdf_bytes: bytes, page_idx_list: List[int]) -> List[Tuple[int, int, List[List[str]]]]:
    """Return list of (page_idx, table_idx_on_page, table_rows)."""
    if pdfplumber is None:
        return []
    out: List[Tuple[int, int, List[List[str]]]] = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for idx in page_idx_list:
            if idx < 0 or idx >= len(pdf.pages):
                continue
            page = pdf.pages[idx]
            tables: List[List[List[str]]] = []
            try:
                tables = page.extract_tables(table_settings=_valid_table_settings_lines()) or []
            except TypeError:
                tables = page.extract_tables() or []
            except Exception:
                try:
                    tables = page.extract_tables() or []
                except Exception:
                    tables = []

            for ti, t in enumerate(tables):
                norm = [[_safe_text(c) for c in row] for row in (t or [])]
                if norm:
                    out.append((idx, ti, norm))
    return out

def _dedup_cols(cols: List[str]) -> List[str]:
    seen = {}
    out = []
    for c in cols:
        c0 = (c or "").strip() or "列"
        if c0 not in seen:
            seen[c0] = 1
            out.append(c0)
        else:
            seen[c0] += 1
            out.append(f"{c0}_{seen[c0]}")
    return out

def _clean_df(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    df = df.copy()
    df.replace({None: ""}, inplace=True)
    df = df.applymap(lambda x: "" if str(x).strip().lower() == "nan" else str(x).strip())

    # drop all-empty rows/cols
    df = df.loc[~df.apply(lambda r: all((str(x).strip() == "") for x in r), axis=1)]
    df = df.loc[:, ~df.apply(lambda c: all((str(x).strip() == "") for x in c), axis=0)]
    return df.reset_index(drop=True)

def _table_to_df(table_rows: List[List[str]]) -> pd.DataFrame:
    rows = [r for r in (table_rows or []) if any(_safe_text(x) for x in r)]
    if not rows:
        return pd.DataFrame()

    max_cols = max(len(r) for r in rows)
    rows = [r + [""] * (max_cols - len(r)) for r in rows]

    # header-like?
    header = rows[0]
    header_join = " ".join(header)
    header_like = any(k in header_join for k in ["课程", "学分", "周次", "指标", "支撑", "合计", "课程编码", "课程名称", "学时"])
    if header_like:
        cols = _dedup_cols([c if c else f"列{i+1}" for i, c in enumerate(header)])
        df = pd.DataFrame(rows[1:], columns=cols)
    else:
        df = pd.DataFrame(rows, columns=[f"列{i+1}" for i in range(max_cols)])

    df = _clean_df(df)

    # remove repeated header rows inside body
    if not df.empty:
        col_text = [str(c).strip() for c in df.columns]
        def is_repeated_header(row: pd.Series) -> bool:
            vals = [str(x).strip() for x in row.tolist()]
            # if many cells match column names
            matches = sum(1 for a, b in zip(vals, col_text) if a and b and a == b)
            return matches >= max(2, len(col_text)//2)
        df = df.loc[~df.apply(is_repeated_header, axis=1)].reset_index(drop=True)

    return df

def _table_signature_text(df: pd.DataFrame) -> str:
    if df is None or df.empty:
        return ""
    head = " ".join([str(c) for c in df.columns.tolist()])
    top_rows = []
    for i in range(min(3, len(df))):
        top_rows.append(" ".join([str(x) for x in df.iloc[i].tolist()]))
    return (head + " " + " ".join(top_rows)).lower()

def _classify_table(df: pd.DataFrame) -> Tuple[str, int]:
    """Return (section_id, score) where section_id in {"7","8","9","10"}."""
    s = _table_signature_text(df)

    score7 = sum(3 for k in ["课程编码", "课程代码", "课程名称", "学分", "总学时", "考核", "开课"] if k in s)
    score8 = sum(3 for k in ["学分统计", "必修", "选修", "通识", "专业", "实践", "合计", "小计"] if k in s)
    score9 = sum(3 for k in ["周次", "教学内容", "进度", "章节", "学时", "实验"] if k in s)
    score10 = sum(3 for k in ["毕业要求", "指标点", "支撑", "达成", "对应", "课程设置对毕业要求"] if k in s)

    best = max([("7", score7), ("8", score8), ("9", score9), ("10", score10)], key=lambda x: x[1])
    return best if best[1] >= 6 else ("", 0)

def _merge_dfs(parts: List[pd.DataFrame]) -> pd.DataFrame:
    """Merge multi-page table parts to one df (best-effort)."""
    parts = [p for p in parts if p is not None and not p.empty]
    if not parts:
        return pd.DataFrame()
    # choose base columns by most frequent / longest
    base = max(parts, key=lambda d: d.shape[1])
    base_cols = [str(c) for c in base.columns]

    aligned: List[pd.DataFrame] = []
    for df in parts:
        d = df.copy()
        # if same col count but different names, keep base cols
        if d.shape[1] == len(base_cols):
            d.columns = base_cols
        else:
            # align by padding/truncation
            cols = [f"列{i+1}" for i in range(d.shape[1])]
            d.columns = cols
            # pad
            if d.shape[1] < len(base_cols):
                for i in range(d.shape[1], len(base_cols)):
                    d[f"列{i+1}"] = ""
            d = d.iloc[:, :len(base_cols)]
            d.columns = base_cols
        aligned.append(d)

    merged = pd.concat(aligned, axis=0, ignore_index=True)
    merged = _clean_df(merged)

    # remove duplicate consecutive rows (common in page breaks)
    if not merged.empty:
        merged = merged.loc[~merged.duplicated()].reset_index(drop=True)
    return merged

def extract_appendix_tables_best_effort(pdf_bytes: bytes, pages_text: List[str]) -> Tuple[Dict[str, pd.DataFrame], Dict[str, Any]]:
    """
    从 PDF 末尾页面抽取表格，自动分类到 7-10，并对“跨多页”的同一附表进行合并。
    说明：
      - 先用关键词打分分类；
      - 再用“续接”启发式：如果某页表格未命中关键词，但紧跟在已识别附表后、且列结构相近，则视为同一附表的后续页。
    Returns:
      tables_map: {"7":df, "8":df, "9":df, "10":df}
      debug_meta
    """
    n = len(pages_text)
    tail_pages = list(range(max(0, n - 18), n))  # last 18 pages (更稳一点)
    raw = _extract_tables_with_meta(pdf_bytes, tail_pages)
    raw_sorted = sorted(raw, key=lambda x: (x[0], x[1]))

    parts_with_meta: Dict[str, List[Tuple[int, int, pd.DataFrame]]] = {"7": [], "8": [], "9": [], "10": []}
    classified_log = []

    # “续接”上下文
    active_sec: Optional[str] = None
    active_until_page: int = -1
    active_cols: Optional[List[str]] = None
    active_ncols: int = -1

    def _col_similarity(cols_a: List[str], cols_b: List[str]) -> float:
        if not cols_a or not cols_b:
            return 0.0
        a = set([c.strip().lower() for c in cols_a if c.strip()])
        b = set([c.strip().lower() for c in cols_b if c.strip()])
        if not a or not b:
            return 0.0
        return len(a & b) / max(1, len(a | b))

    for page_idx, ti, rows in raw_sorted:
        df = _table_to_df(rows)
        if df is None or df.empty:
            continue
        if df.shape[0] < 2 and df.shape[1] < 3:
            continue

        sec, score = _classify_table(df)
        cols = [str(c) for c in df.columns]
        ncols = df.shape[1]

        used_as_continuation = False
        if not sec and active_sec and page_idx <= active_until_page:
            # 续接判据：列数相近 或 列名相似
            sim = _col_similarity(cols, active_cols or [])
            if abs(ncols - (active_ncols if active_ncols > 0 else ncols)) <= 1 or sim >= 0.35:
                sec = active_sec
                score = 1  # 续接分（低于关键词命中）
                used_as_continuation = True

        if sec:
            parts_with_meta[sec].append((page_idx, ti, df))
            classified_log.append({
                "page": page_idx, "table": ti, "sec": sec, "score": score,
                "shape": list(df.shape), "continuation": used_as_continuation
            })

            # 更新上下文：关键词命中时更强；续接时也延长一点点
            if not used_as_continuation:
                active_sec = sec
                active_until_page = page_idx + 3
                active_cols = cols
                active_ncols = ncols
            else:
                # continuation：轻微延长
                active_until_page = max(active_until_page, page_idx + 2)

        else:
            classified_log.append({
                "page": page_idx, "table": ti, "sec": "", "score": 0,
                "shape": list(df.shape), "continuation": False
            })

    merged_map: Dict[str, pd.DataFrame] = {}
    for sec in ["7", "8", "9", "10"]:
        sec_parts = sorted(parts_with_meta[sec], key=lambda x: (x[0], x[1]))
        merged_map[sec] = _merge_dfs([x[2] for x in sec_parts])

    debug = {
        "tail_pages": tail_pages,
        "raw_tables_count": len(raw),
        "classified_log": classified_log[:120],
        "merged_shapes": {k: (list(v.shape) if isinstance(v, pd.DataFrame) else None) for k, v in merged_map.items()},
    }
    return merged_map, debug



def base_plan_from_pdf(pdf_bytes: bytes) -> Dict[str, Any]:
    pages = _read_pdf_pages_text(pdf_bytes)
    full = _join_pages(pages)
    spans = _build_section_spans(full)

    sections: Dict[str, str] = {}
    for sec_id, _ in _SECTION_PATTERNS:
        sections[sec_id] = _extract_section_text(full, spans, sec_id)

    # If 7-11 empty in main body, put hint
    for sec_id in ["7", "8", "9", "10", "11"]:
        if not sections.get(sec_id, "").strip():
            sections[sec_id] = f"{sec_id}：正文可能仅有标题；请尝试从 PDF 末尾附表自动抽取。"

    tables, debug = extract_appendix_tables_best_effort(pdf_bytes, pages)
    return {"pages": pages, "full_text": full, "sections": sections, "tables": tables, "debug": debug}


# -----------------------------
# Word Template Tagger (create tagged template for docxtpl)
# -----------------------------
def _set_cell_text_keep_style(cell, new_text: str):
    # Clear cell content but keep cell formatting
    # python-docx doesn't have a direct clear; replace first paragraph then clear others
    paras = cell.paragraphs
    if not paras:
        cell.text = new_text
        return
    # set first paragraph
    p0 = paras[0]
    # clear runs
    for r in list(p0.runs):
        r.text = ""
    if p0.runs:
        p0.runs[0].text = new_text
    else:
        p0.add_run(new_text)
    # clear remaining paragraphs
    for p in paras[1:]:
        for r in list(p.runs):
            r.text = ""

def _set_paragraph_text_keep_style(p, new_text: str):
    # Keep paragraph style; keep first run formatting as much as possible
    runs = list(p.runs)
    if not runs:
        p.add_run(new_text)
        return
    # overwrite first run text
    runs[0].text = new_text
    # clear other runs
    for r in runs[1:]:
        r.text = ""

def tag_docx_to_template(docx_bytes: bytes, mode: str = "all") -> Tuple[bytes, Dict[str, str], Dict[str, Any]]:
    """
    Replace non-empty texts with {{tags}}.
    mode:
      - "tables": only tag table cells
      - "paragraphs": only tag paragraphs
      - "all": both
    Return: (template_bytes, tag_map[tag]=original_text, meta)
    """
    if Document is None:
        raise RuntimeError("未安装 python-docx，无法处理 Word。")

    doc = Document(io.BytesIO(docx_bytes))
    tag_map: Dict[str, str] = {}
    counters = {"p": 0, "t": 0, "h": 0, "f": 0}

    def make_tag(prefix: str) -> str:
        counters[prefix] += 1
        return f"{prefix}{counters[prefix]:03d}"

    def should_skip(text: str) -> bool:
        t = _safe_text(text)
        if not t:
            return True
        # already has docxtpl tag
        if "{{" in t and "}}" in t:
            return True
        # skip pure page number / short punctuation
        if len(t) <= 1:
            return True
        if re.fullmatch(r"[\d\-\./]+", t):
            return True
        return False

    # paragraphs in body
    if mode in ("all", "paragraphs"):
        for p in doc.paragraphs:
            raw = p.text
            if should_skip(raw):
                continue
            tag = make_tag("p")
            tag_text = "{{" + tag + "}}"
            tag_map[tag] = raw
            _set_paragraph_text_keep_style(p, tag_text)

    # tables in body
    if mode in ("all", "tables"):
        for tb_i, table in enumerate(doc.tables, start=1):
            for r_i, row in enumerate(table.rows, start=1):
                for c_i, cell in enumerate(row.cells, start=1):
                    raw = cell.text
                    if should_skip(raw):
                        continue
                    tag = make_tag("t")
                    tag_text = "{{" + tag + "}}"
                    tag_map[tag] = raw
                    _set_cell_text_keep_style(cell, tag_text)

    # headers/footers
    def tag_header_footer(container, prefix: str):
        for p in container.paragraphs:
            raw = p.text
            if should_skip(raw):
                continue
            tag = make_tag(prefix)
            tag_text = "{{" + tag + "}}"
            tag_map[tag] = raw
            _set_paragraph_text_keep_style(p, tag_text)
        for table in container.tables:
            for row in table.rows:
                for cell in row.cells:
                    raw = cell.text
                    if should_skip(raw):
                        continue
                    tag = make_tag(prefix)
                    tag_text = "{{" + tag + "}}"
                    tag_map[tag] = raw
                    _set_cell_text_keep_style(cell, tag_text)

    if mode == "all":
        for sec in doc.sections:
            tag_header_footer(sec.header, "h")
            tag_header_footer(sec.footer, "f")

    out = io.BytesIO()
    doc.save(out)
    meta = {"tag_count": len(tag_map), "mode": mode, "counters": counters}
    return out.getvalue(), tag_map, meta


# -----------------------------
# Pages
# -----------------------------
def nav_bar():
    # simple nav via query params
    with st.sidebar:
        st.divider()
        st.markdown("### 导航")
        pages = ["首页", "大纲", "日历", "方案", "基座", "模板", "批卷", "分析", "设置"]
        current = st.query_params.get("page", "首页")
        choice = st.radio("页面", pages, index=pages.index(current) if current in pages else 0, key="nav_radio")
        st.query_params["page"] = choice

def page_home():
    st.subheader("🏠 首页")
    st.write("这里是教学文件工作台的首页。建议使用左侧导航进入【基座】或【模板】。")
    st.info("如果你只想先验证“Word 模板打标签”是否成功：进入【模板】→ 上传 docx → 一键生成标签模板并下载。")

def page_syllabus():
    st.subheader("📘 大纲")
    st.info("占位页：你可以把“课程大纲生成/校对”模块放在这里。")

def page_calendar():
    st.subheader("📅 教学日历")
    st.info("占位页：你可以把“教学日历填充/导出”模块放在这里（稍后接入 DocxTemplate 渲染）。")

def page_program():
    st.subheader("🧩 培养方案")
    st.info("占位页：你可以把“培养方案管理/对比/审核”模块放在这里。")

def page_grading():
    st.subheader("📝 批卷")
    st.info("占位页：你可以把“试卷上传/识别/批阅/评价”模块放在这里。")

def page_analysis():
    st.subheader("📊 分析")
    st.info("占位页：你可以把“数据统计/质量分析/达成度分析”模块放在这里。")

def page_settings():
    st.subheader("⚙️ 设置")
    st.write("这里放一些开关、默认参数等。")
    st.checkbox("启用 PDF 附表抽取（7-10）", value=True, key="cfg_enable_appendix")
    st.checkbox("模板打标签时同时处理页眉页脚", value=True, key="cfg_tag_header_footer")

def page_base():
    """Alias for compatibility: route may call page_base()."""
    return page_base_plan()

def page_base_plan():
    st.subheader("🧱 培养方案基座（全量内容库）")
    st.caption("上传培养方案 PDF → 抽取填充 1–11 → 并尝试从末尾附表自动抽表填充 7–10（支持多页合并）。")

    project: Project = st.session_state.__active_project  # set in main
    left, right = st.columns([1, 1.4], gap="large")

    with left:
        if pdfplumber is None:
            st.error("当前环境未安装 pdfplumber，无法解析 PDF。请在 requirements.txt 添加 pdfplumber。")
            return

        pdf = st.file_uploader("上传培养方案 PDF（.pdf）", type=["pdf"], key=f"pdf_{project.project_id}")

        if st.button("抽取并写入基座", use_container_width=True, type="primary", key=f"extract_btn_{project.project_id}"):
            if not pdf:
                st.warning("请先上传 PDF。")
            else:
                pdf_bytes = pdf.getvalue()
                payload = base_plan_from_pdf(pdf_bytes)
                st.session_state.project_data[project.project_id] = payload

                # update project timestamp
                for i, p in enumerate(st.session_state.projects):
                    if p.project_id == project.project_id:
                        st.session_state.projects[i] = Project(project_id=p.project_id, name=p.name, updated_at=_now_str())
                        st.session_state.__active_project = st.session_state.projects[i]
                        break

                st.success("已抽取并写入基座。右侧已联动填充。")
                st.rerun()

        payload = st.session_state.project_data.get(project.project_id)

        if payload:
            # Download JSON (fixed)
            json_payload = _jsonable(payload)
            st.download_button(
                label="下载基座 JSON",
                data=json.dumps(json_payload, ensure_ascii=False, indent=2).encode("utf-8"),
                file_name=f"base_{project.project_id}.json",
                mime="application/json",
                use_container_width=True,
                key=f"dl_{project.project_id}",
            )

        st.divider()
        if payload:
            # quality checks: section text mostly for 1-6, tables for 7-10
            miss = []
            for k in [str(i) for i in range(1, 7)]:
                if not (payload.get("sections", {}).get(k, "") or "").strip():
                    miss.append(k)
            if miss:
                st.warning(f"正文抽取缺少栏目：{miss}（可能 PDF 标题格式不一致）")
            else:
                st.success("正文 1–6 已抽取（建议人工扫读）。")

            assigned = payload.get("debug", {}).get("merged_shapes", {})
            st.write("附表抽取结果（合并后形状）:", assigned)

        with st.expander("调试：分页原文 (raw_pages_text)"):
            if payload:
                st.write(payload.get("pages", []))
            else:
                st.info("先抽取后可见。")

        with st.expander("调试：附表抽取信息 (appendix_debug)"):
            if payload:
                st.json(payload.get("debug", {}))
            else:
                st.info("先抽取后可见。")

    with right:
        st.markdown("#### 培养方案内容（按栏目展示，可编辑）")

        payload = st.session_state.project_data.get(project.project_id)
        if not payload:
            st.info("请先在左侧上传 PDF 并点击“抽取并写入基座”。")
            return

        sections = payload.get("sections", {})
        tables = payload.get("tables", {}) or {}

        toc = [
            ("1", "培养目标"),
            ("2", "毕业要求"),
            ("3", "专业定位与特色"),
            ("4", "主干学科/核心课程/实践环节"),
            ("5", "标准学制与授予学位"),
            ("6", "毕业条件"),
            ("7", "专业教学计划表（附表1）"),
            ("8", "学分统计表（附表2）"),
            ("9", "教学进程表（附表3）"),
            ("10", "支撑关系表（附表4）"),
            ("11", "逻辑思维导图（附表5）"),
        ]
        title_map = dict(toc)

        sec_pick = st.radio(
            "栏目",
            options=[x[0] for x in toc],
            format_func=lambda x: title_map[x],
            horizontal=True,
            key=f"sec_radio_{project.project_id}",
        )

        st.markdown(f"##### {sec_pick}、{title_map[sec_pick]}")

        txt = sections.get(sec_pick, "") or ""

        # extra safety truncate: 6 should not contain 7+
        if sec_pick == "6":
            m = re.search(r"^\s*(七|7)[、\.\s]*专业教学计划表\b", txt, flags=re.MULTILINE)
            if m:
                txt = _compact_lines(txt[:m.start()])

        st.text_area(
            f"{sec_pick} 文本抽取结果（可编辑）",
            value=txt,
            height=220,
            key=f"sec_text_{project.project_id}_{sec_pick}",
        )

        # Table editors for 7-10
        if sec_pick in ["7", "8", "9", "10"]:
            st.markdown("###### 表格区（可编辑，行可增删）")
            df0 = tables.get(sec_pick)
            if df0 is None or (isinstance(df0, pd.DataFrame) and df0.empty):
                st.warning("未自动抽取到该附表（可能 PDF 表格是图片或线条不规则）。可先手工补全，或稍后接入 OCR。")
                df0 = pd.DataFrame()

            editor_key = f"tbl_editor_{project.project_id}_{sec_pick}"
            edited = st.data_editor(df0, num_rows="dynamic", use_container_width=True, key=editor_key)
            # store value separately (avoid ValueAssignmentNotAllowedError)
            st.session_state[f"{editor_key}__value"] = edited

        if sec_pick == "11":
            st.info("逻辑思维导图（附表5）通常是图片/流程图；如需自动抽取，可后续加“末页图片提取”或手动上传图片。")


def page_template_tagger():
    st.subheader("🏷️ Word 模板打标签（先不填充）")
    st.caption("上传 docx → 自动把段落/表格中的非空文字替换为 {{tag}} → 下载模板 + 下载标签映射表。")

    if Document is None:
        st.error("当前环境未安装 python-docx，无法处理 Word。请在 requirements.txt 添加 python-docx。")
        return

    project: Project = st.session_state.__active_project
    col1, col2 = st.columns([1, 1])

    with col1:
        mode = st.selectbox("打标签范围", options=["all", "tables", "paragraphs"],
                            format_func=lambda x: {"all":"段落+表格+页眉页脚","tables":"仅表格","paragraphs":"仅段落"}[x],
                            key=f"tag_mode_{project.project_id}")
        docx = st.file_uploader("上传 Word 范本（.docx）", type=["docx"], key=f"tmpl_{project.project_id}")

        run_btn = st.button("一键生成标签模板", type="primary", use_container_width=True, key=f"tag_btn_{project.project_id}")

    with col2:
        st.markdown("**说明**")
        st.write("- 每个被替换的位置会生成一个唯一标签，如 `{{p001}}` / `{{t012}}`。")
        st.write("- 标签映射表会记录 `tag -> 原始文字`，便于你后续对接 AI 填充。")
        st.write("- 目前策略是“尽量保持格式”，但复杂 run 级别样式可能会被简化。")

    if run_btn:
        if not docx:
            st.warning("请先上传 docx。")
        else:
            with st.spinner("正在生成标签模板..."):
                tpl_bytes, tag_map, meta = tag_docx_to_template(docx.getvalue(), mode=mode)
                st.session_state.template_tag_maps[project.project_id] = {"tag_map": tag_map, "meta": meta, "template_bytes": tpl_bytes, "source_name": docx.name, "ts": _now_str()}
            st.success(f"✅ 已生成标签模板：共 {len(tag_map)} 个标签。")

    result = st.session_state.template_tag_maps.get(project.project_id)
    if result:
        st.divider()
        st.markdown("#### 下载")
        base_name = Path(result.get("source_name", "template.docx")).stem
        st.download_button(
            "下载：标签模板（docx）",
            data=result["template_bytes"],
            file_name=f"{base_name}_tagged.docx",
            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            use_container_width=True,
            key=f"dl_tagged_{project.project_id}",
        )
        st.download_button(
            "下载：标签映射表（json）",
            data=json.dumps(_jsonable({"tag_map": result["tag_map"], "meta": result["meta"]}), ensure_ascii=False, indent=2).encode("utf-8"),
            file_name=f"{base_name}_tag_map.json",
            mime="application/json",
            use_container_width=True,
            key=f"dl_tagmap_{project.project_id}",
        )

        with st.expander("预览：前 30 个标签映射"):
            tag_map = result["tag_map"]
            items = list(tag_map.items())[:30]
            st.dataframe(pd.DataFrame(items, columns=["tag", "original_text"]), use_container_width=True)


# -----------------------------
# Router
# -----------------------------
def _route_call(page: str):
    # Keep both names to avoid NameError even if old route dict uses page_base/page_base_plan.
    route = {
        "首页": page_home,
        "大纲": page_syllabus,
        "日历": page_calendar,
        "方案": page_program,
        "基座": page_base,                 # compatibility
        "模板": page_template_tagger,
        "批卷": page_grading,
        "分析": page_analysis,
        "设置": page_settings,
    }
    fn = route.get(page, page_home)
    fn()


def main():
    st.set_page_config(page_title=APP_TITLE, page_icon="🧠", layout="wide")
    _init_state()

    prj = ui_project_sidebar()
    st.session_state.__active_project = prj  # internal convenience

    nav_bar()
    _render_top_header(prj)

    # main page based on query param
    current = st.query_params.get("page", "首页")
    _route_call(current)


if __name__ == "__main__":
    main()
