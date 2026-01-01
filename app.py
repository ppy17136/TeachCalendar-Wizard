
# app_mcp_manus.py
# Teaching Agent Suite (MCP-style tools + Manus-style multi-step runner)
# - Safe "MCP-like" tool registry (local tools)
# - "Manus-like" task runner (multi-step pipelines calling tools)
# - Base plan 1–11 extraction + appendix tables 7–10 extraction & MERGE across pages
# - Template Tagger: convert uploaded DOCX into a tagged docxtpl template (best-effort)
# - Fix Streamlit key collisions + sidebar logo rendering
#
# NOTE:
# - This is NOT the official Manus product, and NOT a remote-VM controller.
#   It implements the same *idea*: "agent -> call tools -> produce artifacts" in a safe, local way.

from __future__ import annotations

import io
import re
import json
import time
import base64
import hashlib
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
import pdfplumber
from docx import Document
from docxtpl import DocxTemplate

# Optional: keep your existing AI backends (Gemini / Qwen). If keys missing, app still runs.
try:
    import google.generativeai as genai
except Exception:
    genai = None

try:
    from openai import OpenAI
except Exception:
    OpenAI = None


# =========================
# 0) Basic helpers
# =========================
def _now_str() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())

def _short_id(s: str) -> str:
    return hashlib.md5(s.encode("utf-8")).hexdigest()[:10]

def _safe_text(x: Any) -> str:
    return "" if x is None else str(x).strip()

def _compact_lines(s: str) -> str:
    s = (s or "").replace("\u00a0", " ")
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()

def payload_to_jsonable(obj: Any) -> Any:
    """Make payload JSON-serializable (prevents json.dumps TypeError)."""
    # pandas
    if isinstance(obj, pd.DataFrame):
        df = obj.copy().fillna("")
        return {
            "__type__": "dataframe",
            "columns": [str(c) for c in df.columns.tolist()],
            "data": df.astype(str).values.tolist(),
        }
    # bytes
    if isinstance(obj, (bytes, bytearray)):
        return {"__type__": "bytes_base64", "data": base64.b64encode(bytes(obj)).decode("ascii")}
    # datetime-like
    try:
        import datetime as _dt
        if isinstance(obj, (_dt.date, _dt.datetime)):
            return obj.isoformat()
    except Exception:
        pass
    # numpy scalars/arrays
    try:
        import numpy as np
        if isinstance(obj, (np.integer, np.floating, np.bool_)):
            return obj.item()
        if isinstance(obj, np.ndarray):
            return obj.tolist()
    except Exception:
        pass
    # dict/list/tuple/set
    if isinstance(obj, dict):
        return {str(k): payload_to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [payload_to_jsonable(v) for v in obj]
    if isinstance(obj, (tuple, set)):
        return [payload_to_jsonable(v) for v in obj]
    # fallback
    try:
        json.dumps(obj)
        return obj
    except Exception:
        return str(obj)


# =========================
# 1) MCP-style Tool Registry (LOCAL tools)
# =========================
@dataclass
class ToolSpec:
    name: str
    description: str
    input_schema: Dict[str, Any]  # JSON-schema-ish (lightweight)
    handler: Callable[[Dict[str, Any]], Dict[str, Any]]

class ToolRegistry:
    def __init__(self) -> None:
        self._tools: Dict[str, ToolSpec] = {}

    def register(self, tool: ToolSpec) -> None:
        self._tools[tool.name] = tool

    def list_tools(self) -> List[Dict[str, Any]]:
        return [{
            "name": t.name,
            "description": t.description,
            "input_schema": t.input_schema
        } for t in self._tools.values()]

    def call_tool(self, name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        if name not in self._tools:
            return {"ok": False, "error": f"Unknown tool: {name}"}
        try:
            return self._tools[name].handler(args or {})
        except Exception as e:
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}


# =========================
# 2) Manus-style Task Runner (pipelines calling tools)
# =========================
@dataclass
class TaskStep:
    tool: str
    args: Dict[str, Any]
    save_as: Optional[str] = None  # store result in context

class TaskRunner:
    """Manus-like: run multiple steps (tools) deterministically and safely."""
    def __init__(self, registry: ToolRegistry):
        self.registry = registry

    def run(self, steps: List[TaskStep]) -> Dict[str, Any]:
        ctx: Dict[str, Any] = {}
        logs: List[Dict[str, Any]] = []

        for i, step in enumerate(steps, start=1):
            # allow simple templating from ctx: "{{key}}"
            args = _ctx_format(step.args, ctx)
            res = self.registry.call_tool(step.tool, args)
            logs.append({"step": i, "tool": step.tool, "args": _safe_preview(args), "result_ok": res.get("ok", False)})
            if not res.get("ok"):
                return {"ok": False, "error": res.get("error", "unknown"), "logs": logs, "ctx": ctx}
            if step.save_as:
                ctx[step.save_as] = res
        return {"ok": True, "logs": logs, "ctx": ctx}

def _ctx_format(obj: Any, ctx: Dict[str, Any]) -> Any:
    if isinstance(obj, str):
        # replace {{key}} with ctx[key] (stringified)
        def repl(m):
            k = m.group(1).strip()
            return str(ctx.get(k, m.group(0)))
        return re.sub(r"\{\{([^}]+)\}\}", repl, obj)
    if isinstance(obj, dict):
        return {k: _ctx_format(v, ctx) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_ctx_format(v) for v in obj]
    return obj

def _safe_preview(args: Dict[str, Any]) -> Dict[str, Any]:
    out = {}
    for k, v in (args or {}).items():
        if isinstance(v, (bytes, bytearray)):
            out[k] = f"<bytes:{len(v)}>"
        else:
            out[k] = v if len(str(v)) < 300 else str(v)[:300] + "..."
    return out


# =========================
# 3) Base plan extraction (1–11) + appendix tables (7–10) + merge across pages
# =========================
_SECTION_PATTERNS: List[Tuple[str, List[str]]] = [
    ("1", [r"一[、\.\s]*培养目标", r"1[、\.\s]*培养目标"]),
    ("2", [r"二[、\.\s]*毕业要求", r"2[、\.\s]*毕业要求"]),
    ("3", [r"三[、\.\s]*专业定位与特色", r"3[、\.\s]*专业定位与特色"]),
    ("4", [r"四[、\.\s]*主干学科", r"4[、\.\s]*主干学科"]),
    ("5", [r"五[、\.\s]*标准学制", r"5[、\.\s]*标准学制"]),
    ("6", [r"六[、\.\s]*毕业条件", r"6[、\.\s]*毕业条件"]),
    ("7", [r"七[、\.\s]*专业教学计划表", r"7[、\.\s]*专业教学计划表"]),
    ("8", [r"八[、\.\s]*学分统计表", r"8[、\.\s]*学分统计表"]),
    ("9", [r"九[、\.\s]*教学进程表", r"9[、\.\s]*教学进程表"]),
    ("10", [r"十[、\.\s]*课程设置对毕业要求支撑关系表", r"10[、\.\s]*课程设置对毕业要求支撑关系表"]),
    ("11", [r"十一[、\.\s]*课程设置逻辑思维导图", r"11[、\.\s]*课程设置逻辑思维导图"]),
]

def _read_pdf_pages_text(pdf_bytes: bytes) -> List[str]:
    pages = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for p in pdf.pages:
            txt = p.extract_text() or ""
            pages.append(_compact_lines(txt))
    return pages

def _join_pages(pages_text: List[str]) -> str:
    return _compact_lines("\n\n".join([t or "" for t in pages_text]))

def _build_section_spans(full_text: str) -> Dict[str, Tuple[int, int]]:
    hits: List[Tuple[str, int]] = []
    for sec_id, pats in _SECTION_PATTERNS:
        pos = None
        for pat in pats:
            m = re.search(pat, full_text)
            if m:
                pos = m.start()
                break
        if pos is not None:
            hits.append((sec_id, pos))

    hits.sort(key=lambda x: x[1])
    spans: Dict[str, Tuple[int, int]] = {}
    for i, (sec_id, start) in enumerate(hits):
        end = hits[i + 1][1] if i + 1 < len(hits) else len(full_text)
        spans[sec_id] = (start, end)
    return spans

def _extract_section_text(full_text: str, spans: Dict[str, Tuple[int, int]], sec_id: str) -> str:
    if sec_id not in spans:
        return ""
    s, e = spans[sec_id]
    chunk = full_text[s:e].strip()
    chunk = re.sub(r"^\s*(一|二|三|四|五|六|七|八|九|十|十一|\d+)[、\.\s]*[^\n]{0,40}\n", "", chunk)
    return _compact_lines(chunk)

def _valid_table_settings_lines() -> dict:
    return dict(
        vertical_strategy="lines",
        horizontal_strategy="lines",
        snap_tolerance=3,
        join_tolerance=3,
        edge_min_length=3,
        intersection_tolerance=3,
        text_tolerance=3,
    )

def _extract_tables_from_pages(pdf_bytes: bytes, page_idx_list: List[int]) -> List[Tuple[int, List[List[str]]]]:
    out: List[Tuple[int, List[List[str]]]] = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for idx in page_idx_list:
            if idx < 0 or idx >= len(pdf.pages):
                continue
            page = pdf.pages[idx]
            tables = []
            try:
                tables = page.extract_tables(table_settings=_valid_table_settings_lines()) or []
            except TypeError:
                tables = page.extract_tables() or []
            except Exception:
                try:
                    tables = page.extract_tables() or []
                except Exception:
                    tables = []

            for t in tables:
                norm = []
                for row in t:
                    norm.append([_safe_text(c) for c in row])
                out.append((idx, norm))
    return out

def _dedup_cols(cols: List[str]) -> List[str]:
    seen: Dict[str, int] = {}
    out: List[str] = []
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
    df = df.loc[~df.apply(lambda r: all((str(x).strip() == "") for x in r), axis=1)]
    df = df.loc[:, ~df.apply(lambda c: all((str(x).strip() == "") for x in c), axis=0)]
    return df.reset_index(drop=True)

def _table_to_df(table_rows: List[List[str]]) -> pd.DataFrame:
    rows = [r for r in table_rows if any(_safe_text(x) for x in r)]
    if not rows:
        return pd.DataFrame()
    max_cols = max(len(r) for r in rows)
    rows = [r + [""] * (max_cols - len(r)) for r in rows]

    header = rows[0]
    header_join = " ".join(header)
    header_like = any(k in header_join for k in ["课程", "学分", "周次", "指标", "支撑", "合计", "课程编码", "课程名称"])
    if header_like:
        cols = [c if c else f"列{i+1}" for i, c in enumerate(header)]
        df = pd.DataFrame(rows[1:], columns=_dedup_cols(cols))
    else:
        cols = [f"列{i+1}" for i in range(max_cols)]
        df = pd.DataFrame(rows, columns=cols)
    return _clean_df(df)

def _table_signature_text(df: pd.DataFrame) -> str:
    if df is None or df.empty:
        return ""
    head = " ".join([str(c) for c in df.columns.tolist()])
    top_rows = []
    for i in range(min(3, len(df))):
        top_rows.append(" ".join([str(x) for x in df.iloc[i].tolist()]))
    return (head + " " + " ".join(top_rows)).lower()

def _classify_table(df: pd.DataFrame) -> Tuple[str, int]:
    s = _table_signature_text(df)
    score7 = sum(3 for k in ["课程编码", "课程代码", "课程名称", "学分", "总学时", "考核", "开课"] if k in s)
    score8 = sum(3 for k in ["学分统计", "必修", "选修", "通识", "专业", "实践", "合计", "小计"] if k in s)
    score9 = sum(3 for k in ["周次", "教学内容", "进度", "章节", "学时", "实验"] if k in s)
    score10 = sum(3 for k in ["毕业要求", "指标点", "支撑", "达成", "对应", "课程设置对毕业要求"] if k in s)
    best = max([("7", score7), ("8", score8), ("9", score9), ("10", score10)], key=lambda x: x[1])
    return best if best[1] >= 6 else ("", 0)

def _merge_dfs_same_header(dfs: List[pd.DataFrame]) -> pd.DataFrame:
    if not dfs:
        return pd.DataFrame()
    base_cols = [str(c) for c in dfs[0].columns.tolist()]
    merged = dfs[0].copy()
    for df in dfs[1:]:
        cols = [str(c) for c in df.columns.tolist()]
        if cols != base_cols:
            continue
        def row_is_header_like(row: pd.Series) -> bool:
            row_txt = " ".join([str(x) for x in row.tolist()]).strip().lower()
            hits = sum(1 for c in base_cols if str(c).strip().lower() in row_txt)
            return hits >= max(2, len(base_cols)//3)
        df = df.loc[~df.apply(row_is_header_like, axis=1)].reset_index(drop=True)
        merged = pd.concat([merged, df], ignore_index=True)
    return _clean_df(merged)

def extract_appendix_tables_best_effort(pdf_bytes: bytes, pages_text: List[str]) -> Tuple[Dict[str, pd.DataFrame], Dict[str, Any]]:
    n = len(pages_text)
    tail_pages = list(range(max(0, n - 16), n))
    raw_tables = _extract_tables_from_pages(pdf_bytes, tail_pages)

    dfs: List[Tuple[int, pd.DataFrame]] = []
    for page_idx, t in raw_tables:
        df = _table_to_df(t)
        if df is None or df.empty:
            continue
        if df.shape[0] < 2 and df.shape[1] < 3:
            continue
        dfs.append((page_idx, df))

    scored: List[Tuple[int, int, str, int]] = []
    for i, (pidx, df) in enumerate(dfs):
        sec, score = _classify_table(df)
        if sec:
            scored.append((pidx, i, sec, score))

    grouped: Dict[str, List[Tuple[int, pd.DataFrame, int]]] = {}
    for pidx, i, sec, score in scored:
        grouped.setdefault(sec, []).append((pidx, dfs[i][1], score))

    assigned: Dict[str, pd.DataFrame] = {}
    merged_info: Dict[str, Any] = {}

    for sec, items in grouped.items():
        items.sort(key=lambda x: (x[0], -x[2]))
        first_cols = [str(c) for c in items[0][1].columns.tolist()]
        merge_list = [items[0][1]]
        used_pages = [items[0][0]]
        for pidx, df, score in items[1:]:
            cols = [str(c) for c in df.columns.tolist()]
            if cols == first_cols:
                merge_list.append(df)
                used_pages.append(pidx)
        assigned[sec] = _merge_dfs_same_header(merge_list)
        merged_info[sec] = {"pages": sorted(list(set(used_pages))), "parts": len(merge_list), "shape": list(assigned[sec].shape)}

    debug = {
        "tail_pages": tail_pages,
        "raw_tables_count": len(raw_tables),
        "dfs_count": len(dfs),
        "grouped": {k: len(v) for k, v in grouped.items()},
        "merged": merged_info,
    }
    return assigned, debug

def base_plan_from_pdf(pdf_bytes: bytes) -> Dict[str, Any]:
    pages = _read_pdf_pages_text(pdf_bytes)
    full = _join_pages(pages)
    spans = _build_section_spans(full)

    base: Dict[str, str] = {}
    for sec_id, _ in _SECTION_PATTERNS:
        base[sec_id] = _extract_section_text(full, spans, sec_id)

    for sec_id in ["7", "8", "9", "10", "11"]:
        if not base.get(sec_id, "").strip():
            base[sec_id] = f"{sec_id}：正文可能仅有标题；请尝试从 PDF 末尾附表自动抽取。"

    auto_tables, debug_meta = extract_appendix_tables_best_effort(pdf_bytes, pages)

    return {
        "pages": pages,
        "full_text": full,
        "sections": base,
        "tables": auto_tables,
        "debug": debug_meta,
    }


# =========================
# 4) Template Tagger (DOCX -> docxtpl template, best-effort)
# =========================
_TAG_MAP = {
    "学校名称": "school_name",
    "学年": "academic_year",
    "学期": "semester",
    "课程名称": "course_name",
    "课程英文名称": "english_name",
    "课程代码": "course_code",
    "课程编码": "course_code",
    "适用专业": "class_info",
    "适用专业及年级": "class_info",
    "主讲教师": "teacher_name",
    "职称": "teacher_title",
    "总学时": "total_hours",
    "本学期总学时": "term_hours",
    "上课周数": "total_weeks",
    "平均每周学时": "weekly_hours",
    "讲课学时": "lecture_hours",
    "实验学时": "lab_hours",
    "测验学时": "quiz_hours",
    "课外学时": "extra_hours",
    "课程性质": "course_nature",
    "教材名称": "textbook_name",
    "出版社": "publisher",
    "出版时间": "publish_date",
    "考核方式": "assessment_method",
    "成绩计算方法": "grading_formula",
    "备注": "note_1",
    "备注1": "note_1",
    "备注2": "note_2",
    "备注3": "note_3",
}

_SCHEDULE_HEADERS = ["周次", "课次", "教学内容", "重点", "学习重点", "学时", "教学方法", "支撑目标", "作业", "其它"]

def tag_docx_to_template(docx_bytes: bytes) -> Tuple[bytes, Dict[str, Any]]:
    doc = Document(io.BytesIO(docx_bytes))
    tags_used: Dict[str, int] = {}

    def use_tag(tag: str):
        tags_used[tag] = tags_used.get(tag, 0) + 1

    # tables
    for tbl in doc.tables:
        header_text = " ".join([c.text.strip() for c in tbl.rows[0].cells]) if len(tbl.rows) else ""
        header_hit = sum(1 for h in _SCHEDULE_HEADERS if h in header_text)
        is_schedule_like = header_hit >= 3

        if is_schedule_like and len(tbl.rows) >= 2:
            tpl_row = tbl.rows[1]
            cols = len(tpl_row.cells)

            tpl_row.cells[0].text = "{% for r in schedule %}"
            tpl_row.cells[-1].text = "{% endfor %}"

            headers = [c.text.strip() for c in tbl.rows[0].cells]
            for j in range(cols):
                if j == 0 or j == cols - 1:
                    continue
                h = headers[j] if j < len(headers) else ""
                key = None
                if "周次" in h:
                    key = "week"
                elif "课次" in h:
                    key = "sess"
                elif "教学内容" in h:
                    key = "content"
                elif "重点" in h:
                    key = "req"
                elif "学时" in h:
                    key = "hrs"
                elif "方法" in h:
                    key = "method"
                elif "支撑" in h:
                    key = "obj"
                elif "作业" in h or "其它" in h:
                    key = "other"
                if key:
                    tpl_row.cells[j].text = "{{ r." + key + " }}"
                    use_tag(f"schedule[].{key}")

            while len(tbl.rows) > 2:
                tbl._tbl.remove(tbl.rows[2]._tr)
            continue

        for row in tbl.rows:
            if len(row.cells) < 2:
                continue
            label = row.cells[0].text.strip()
            if label in _TAG_MAP:
                tag = _TAG_MAP[label]
                row.cells[1].text = "{{ " + tag + " }}"
                use_tag(tag)

    # paragraphs
    for p in doc.paragraphs:
        txt = p.text.strip()
        if "{{" in txt:
            continue
        m = re.match(r"^(.{2,12})[：:]\s*(.+)$", txt)
        if not m:
            continue
        label = m.group(1).strip()
        if label in _TAG_MAP:
            tag = _TAG_MAP[label]
            p.text = f"{label}：{{{{ {tag} }}}}"
            use_tag(tag)

    out = io.BytesIO()
    doc.save(out)
    meta = {"tags_used": tags_used, "note": "自动打标为 best-effort；未命中的字段可手工改成 {{标签}}。"}
    return out.getvalue(), meta


# =========================
# 5) Register tools
# =========================
@dataclass
class ToolSpec:
    name: str
    description: str
    input_schema: Dict[str, Any]
    handler: Callable[[Dict[str, Any]], Dict[str, Any]]

class ToolRegistry:
    def __init__(self) -> None:
        self._tools: Dict[str, ToolSpec] = {}

    def register(self, tool: ToolSpec) -> None:
        self._tools[tool.name] = tool

    def list_tools(self) -> List[Dict[str, Any]]:
        return [{"name": t.name, "description": t.description, "input_schema": t.input_schema} for t in self._tools.values()]

    def call_tool(self, name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        if name not in self._tools:
            return {"ok": False, "error": f"Unknown tool: {name}"}
        try:
            return self._tools[name].handler(args or {})
        except Exception as e:
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}

def build_registry() -> ToolRegistry:
    reg = ToolRegistry()

    def tool_extract_base(args: Dict[str, Any]) -> Dict[str, Any]:
        try:
            b = base64.b64decode(args["pdf_bytes"])
            payload = base_plan_from_pdf(b)
            return {"ok": True, "payload": payload}
        except Exception as e:
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}

    def tool_tag_docx(args: Dict[str, Any]) -> Dict[str, Any]:
        try:
            b = base64.b64decode(args["docx_bytes"])
            tpl_bytes, meta = tag_docx_to_template(b)
            return {"ok": True, "template_bytes": base64.b64encode(tpl_bytes).decode("ascii"), "meta": meta}
        except Exception as e:
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}

    reg.register(ToolSpec(
        name="base.extract_from_pdf",
        description="Extract base plan sections (1–11) + appendix tables (7–10) from PDF bytes.",
        input_schema={"type":"object","properties":{"pdf_bytes":{"type":"string","description":"base64 of PDF bytes"}},"required":["pdf_bytes"]},
        handler=tool_extract_base
    ))

    reg.register(ToolSpec(
        name="template.tag_docx",
        description="Convert a DOCX to a docxtpl template by inserting {{tags}} (best-effort).",
        input_schema={"type":"object","properties":{"docx_bytes":{"type":"string","description":"base64 of DOCX bytes"}},"required":["docx_bytes"]},
        handler=tool_tag_docx
    ))

    return reg


# =========================
# 6) Manus-style Task Runner (pipelines)
# =========================
@dataclass
class TaskStep:
    tool: str
    args: Dict[str, Any]
    save_as: Optional[str] = None

class TaskRunner:
    def __init__(self, registry: ToolRegistry):
        self.registry = registry

    def run(self, steps: List[TaskStep]) -> Dict[str, Any]:
        ctx: Dict[str, Any] = {}
        logs: List[Dict[str, Any]] = []
        for i, step in enumerate(steps, start=1):
            res = self.registry.call_tool(step.tool, step.args)
            logs.append({"step": i, "tool": step.tool, "ok": res.get("ok", False)})
            if not res.get("ok"):
                return {"ok": False, "error": res.get("error", "unknown"), "logs": logs}
            if step.save_as:
                ctx[step.save_as] = res
        return {"ok": True, "ctx": ctx, "logs": logs}


# =========================
# 7) Streamlit UI
# =========================
def _init_state():
    st.session_state.setdefault("active_page", "首页")
    st.session_state.setdefault("logo_bytes", None)

    st.session_state.setdefault("project_id", _short_id(_now_str()))
    st.session_state.setdefault("project_updated_at", _now_str())

    st.session_state.setdefault("base_payload", None)
    st.session_state.setdefault("base_tables_edited", {})

    st.session_state.setdefault("tagger_last_meta", None)
    st.session_state.setdefault("tagger_last_template_bytes", None)

def ui_sidebar_brand():
    with st.sidebar:
        col1, col2 = st.columns([1, 4])
        with col1:
            if st.session_state.logo_bytes:
                st.image(st.session_state.logo_bytes, width=44)
            else:
                components.html(
                    """<div style="width:44px;height:44px;border-radius:50%;
                                background:#2f6fed;display:flex;align-items:center;justify-content:center;
                                color:white;font-weight:800;font-family:Arial;">TA</div>""",
                    height=52
                )
        with col2:
            st.markdown("**Teaching Agent Suite**")
            st.caption("MCP tools + Manus runner (local)")

        up = st.file_uploader("上传 Logo（可选）", type=["png","jpg","jpeg"], key="logo_uploader")
        if up is not None:
            st.session_state.logo_bytes = up.getvalue()

def ui_sidebar_nav():
    with st.sidebar:
        st.divider()
        st.session_state.active_page = st.radio(
            "导航",
            ["首页", "基座", "模板打标", "工具/MCP"],
            index=["首页","基座","模板打标","工具/MCP"].index(st.session_state.active_page),
            key="nav_radio"
        )

def render_top_header():
    pid = st.session_state.project_id
    updated = st.session_state.project_updated_at
    st.markdown(
        f"""<div style="border:1px solid #e7eefc;background:#f6f9ff;padding:14px 16px;border-radius:14px;">
            <div style="font-weight:900;font-size:26px;">智能教学辅助系统（MCP + Manus 风格）</div>
            <div style="color:#666;margin-top:4px;font-size:13px;">项目ID：<b>{pid}</b> · 最后更新：{updated}</div>
            </div>""",
        unsafe_allow_html=True
    )

def page_home():
    st.subheader("首页")
    st.write("本版本把能力拆成“工具（MCP 风格）”，再用“多步骤任务（Manus 风格）”串联。")
    st.markdown("- ✅ 解决：JSON 下载 TypeError、Streamlit key 冲突、侧栏 logo 渲染")
    st.markdown("- ✅ 增强：附表 7–10 支持跨页合并（附表1/附表4 多页可合并）")
    st.markdown("- ✅ 新增：Word 模板自动打标（生成 docxtpl 模板并下载）")

def page_tools(reg: ToolRegistry):
    st.subheader("工具/MCP（本地）")
    st.json(reg.list_tools())

def page_base(reg: ToolRegistry, runner: TaskRunner):
    st.subheader("培养方案基座（1–11 + 附表 7–10）")
    left, right = st.columns([1, 1.4], gap="large")

    with left:
        pdf = st.file_uploader("上传培养方案 PDF", type=["pdf"], key="base_pdf_uploader")
        if st.button("抽取并写入基座（Manus 流程）", type="primary", use_container_width=True, key="base_run_btn"):
            if not pdf:
                st.warning("请先上传 PDF。")
            else:
                pdf_bytes = pdf.getvalue()
                steps = [TaskStep(
                    tool="base.extract_from_pdf",
                    args={"pdf_bytes": base64.b64encode(pdf_bytes).decode("ascii")},
                    save_as="base_res"
                )]
                result = runner.run(steps)
                if not result["ok"]:
                    st.error(f"抽取失败：{result.get('error')}")
                    st.json(result.get("logs", []))
                else:
                    payload = result["ctx"]["base_res"]["payload"]
                    st.session_state.base_payload = payload
                    st.session_state.project_updated_at = _now_str()
                    st.success("已写入基座。右侧已联动填充。")

        payload = st.session_state.base_payload
        if payload:
            json_payload = payload_to_jsonable(payload)
            st.download_button(
                "下载基座 JSON",
                data=json.dumps(json_payload, ensure_ascii=False, indent=2).encode("utf-8"),
                file_name=f"base_{st.session_state.project_id}.json",
                mime="application/json",
                use_container_width=True,
                key="dl_base_json"
            )
            with st.expander("调试：附表合并信息（merged）"):
                st.json(payload.get("debug", {}).get("merged", {}))
        else:
            st.info("先抽取后可下载 JSON。")

    with right:
        payload = st.session_state.base_payload
        if not payload:
            st.info("请先在左侧上传 PDF 并点击“抽取并写入基座”。")
            return

        sections = payload.get("sections", {}) or {}
        tables = payload.get("tables", {}) or {}

        toc = [("1","培养目标"),("2","毕业要求"),("3","专业定位与特色"),("4","主干学科/核心课程/实践环节"),
               ("5","标准学制与授予学位"),("6","毕业条件"),
               ("7","专业教学计划表（附表1）"),("8","学分统计表（附表2）"),
               ("9","教学进程表（附表3）"),("10","支撑关系表（附表4）"),("11","逻辑思维导图（附表5）")]

        sec_pick = st.radio("栏目", options=[x[0] for x in toc], format_func=lambda x: dict(toc)[x],
                            horizontal=True, key="base_sec_radio")
        st.markdown(f"##### {sec_pick}、{dict(toc)[sec_pick]}")

        st.text_area("文本抽取结果", value=sections.get(sec_pick, ""), height=220, key=f"sec_text_{sec_pick}")

        if sec_pick in ["7","8","9","10"]:
            st.markdown("###### 表格区（跨页已自动合并，可编辑）")
            df0 = tables.get(sec_pick)
            if df0 is None or (isinstance(df0, pd.DataFrame) and df0.empty):
                st.info("未自动抽取到该附表（可能表格是图片或线条不规则）。")
                df0 = pd.DataFrame()
            editor_key = f"tbl_editor_{sec_pick}"
            edited_df = st.data_editor(df0, num_rows="dynamic", use_container_width=True, key=editor_key)
            st.session_state.base_tables_edited[sec_pick] = edited_df

def page_template_tagger(reg: ToolRegistry, runner: TaskRunner):
    st.subheader("模板打标：Word → docxtpl 模板（先只生成模板，不填充）")
    docx = st.file_uploader("上传范本（.docx）", type=["docx"], key="tagger_uploader")
    if st.button("一键打标并生成模板（Manus 流程）", type="primary", use_container_width=True, key="tagger_btn"):
        if not docx:
            st.warning("请先上传 docx。")
        else:
            docx_bytes = docx.getvalue()
            steps = [TaskStep(
                tool="template.tag_docx",
                args={"docx_bytes": base64.b64encode(docx_bytes).decode("ascii")},
                save_as="tag_res"
            )]
            result = runner.run(steps)
            if not result["ok"]:
                st.error(f"打标失败：{result.get('error')}")
            else:
                tag_res = result["ctx"]["tag_res"]
                tpl_bytes = base64.b64decode(tag_res["template_bytes"])
                st.session_state.tagger_last_template_bytes = tpl_bytes
                st.session_state.tagger_last_meta = tag_res.get("meta", {})
                st.success("已生成模板，可下载测试是否可用。")

    if st.session_state.tagger_last_template_bytes:
        st.download_button(
            "下载打标后的模板（.docx）",
            data=st.session_state.tagger_last_template_bytes,
            file_name="tagged_template.docx",
            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            use_container_width=True,
            key="dl_tagged_tpl"
        )
        with st.expander("查看自动识别到的标签"):
            st.json((st.session_state.tagger_last_meta or {}).get("tags_used", {}))
        st.info((st.session_state.tagger_last_meta or {}).get("note", ""))

def main():
    st.set_page_config(page_title="Teaching Agent Suite (MCP+Manus style)", page_icon="🧠", layout="wide")
    _init_state()

    reg = build_registry()
    runner = TaskRunner(reg)

    ui_sidebar_brand()
    ui_sidebar_nav()
    render_top_header()

    page = st.session_state.active_page
    if page == "首页":
        page_home()
    elif page == "基座":
        page_base(reg, runner)
    elif page == "模板打标":
        page_template_tagger(reg, runner)
    else:
        page_tools(reg)

if __name__ == "__main__":
    main()