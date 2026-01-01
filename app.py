import os
import streamlit as st
import pdfplumber
import fitz  # PyMuPDF
from docx import Document
import mammoth
import requests
import re
import numpy as np
import matplotlib.pyplot as plt
from openai import OpenAI
import base64
import io
import time
import hashlib
from dataclasses import dataclass
from pathlib import Path
from decimal import Decimal
import datetime as _dt
from PIL import Image
import google.generativeai as genai
import json
from docxtpl import DocxTemplate  # 必须安装 docxtpl
from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from datetime import datetime
# 签名插入示例
from docxtpl import InlineImage
from docx.shared import Mm, Pt
import pandas as pd  # 必须添加，用于数据类型清洗

# --- 1. 基础环境与配置 ---
plt.rcParams['font.family'] = ['SimHei', 'sans-serif']
plt.rcParams['axes.unicode_minus'] = False

# --- 2. 状态自动化初始化 (在 app.py 顶部) ---
if "calendar_data" not in st.session_state:
    st.session_state.calendar_data = [] # 初始化为空列表，防止 AttributeError
if "calendar_status" not in st.session_state:
    st.session_state.calendar_status = "Draft" # 初始状态为草拟
if "calendar_final_data" not in st.session_state:
    st.session_state.calendar_final_data = None # 提交后的完整数据包

st.set_page_config(page_title="智能教学辅助系统", layout="wide", initial_sidebar_state="expanded")

# --- 状态自动化初始化 (防止变量未定义报错) ---
if "school_name" not in st.session_state:
    st.session_state.school_name = "辽宁石油化工大学" # 给一个初始默认值
    
# --- 3. 密钥获取与侧边栏 ---
BACKEND_QWEN_KEY = st.secrets.get("QWEN_API_KEY", "")
BACKEND_GEMINI_KEY = st.secrets.get("GEMINI_API_KEY", "")

# --- 2. 状态自动化初始化 (防止变量未定义报错) ---
# 初始化全局会话状态
if "score_records" not in st.session_state:
    st.session_state.score_records = []
if "generated_syllabus" not in st.session_state:
    st.session_state.generated_syllabus = None
if "generated_calendar" not in st.session_state:
    st.session_state.generated_calendar = None
if "generated_program" not in st.session_state:
    st.session_state.generated_program = None
# 使用 setdefault 确保变量一定存在
st.session_state.setdefault("score_records", [])
st.session_state.setdefault("gen_content", {"syllabus": None, "calendar": None, "program": None})
# --- 3. 侧边栏：引擎切换与密钥管理 ---
with st.sidebar:
    st.header("⚙️ 模型引擎设置")
    selected_provider = st.radio("选择主 AI 引擎", ["Gemini", "Qwen (通义千问)"])
    
    ACTIVE_QWEN_KEY = BACKEND_QWEN_KEY
    ACTIVE_GEMINI_KEY = BACKEND_GEMINI_KEY

    if selected_provider == "Gemini":
        user_gem_key = st.text_input("填写 Gemini API Key (可选)", type="password", help="留空则使用后台默认 Key")
        if user_gem_key: ACTIVE_GEMINI_KEY = user_gem_key
        selected_model = st.selectbox("版本", ["gemini-2.5-flash", "gemini-2.0-flash-exp", "gemini-2.5-pro"])
        engine_id = "Gemini"
        if ACTIVE_GEMINI_KEY: 
            genai.configure(api_key=ACTIVE_GEMINI_KEY)
        else:
            st.error("⚠️ 未检测到有效 Gemini Key")
    else:
        user_qw_key = st.text_input("填写 Qwen API Key (可选)", type="password", help="留空则使用后台默认 Key")
        if user_qw_key: ACTIVE_QWEN_KEY = user_qw_key
        selected_model = st.selectbox("版本", ["qwen-plus", "qwen-max", "qwen-turbo"])
        engine_id = "Qwen"
        if not ACTIVE_QWEN_KEY:
            st.error("⚠️ 未检测到有效 Qwen Key")

    st.divider()
    st.info(f"💡 当前模式：使用 **{engine_id}** 处理。")
    # 侧边栏底部也可以加提示
    st.caption("🖥️ 建议环境：Google Chrome 浏览器")
    
# --- 4. 核心功能函数 --- 
def create_docx(text):
    """将文本转换为可下载的 Word，彻底清洗所有标记"""
    doc = Document()
    
    # 1. 首先通过正则表达式清除所有 HTML 标签 (如 <br/>)
    # 2. 接着通过链式 replace 清除 Markdown 的标题号和加粗符号
    clean_text = re.sub('<[^<]+?>', '', text) \
                   .replace("### ", "") \
                   .replace("## ", "") \
                   .replace("# ", "") \
                   .replace("**", "")
    
    # 写入 Word
    for line in clean_text.split('\n'):
        if line.strip(): # 过滤掉多余的空行
            p = doc.add_paragraph(line)
            p.style.font.size = Pt(12)
    
    bio = io.BytesIO()
    doc.save(bio)
    return bio.getvalue()

def ai_generate(prompt, provider, model_name):
    """统一文本生成接口"""
    if provider == "Gemini":
        if not ACTIVE_GEMINI_KEY: return "错误：未配置密钥"
        try:
            model = genai.GenerativeModel(model_name)
            response = model.generate_content(prompt)
            return response.text
        except Exception as e: return f"Gemini 失败: {str(e)}"
    else:
        if not ACTIVE_QWEN_KEY: return "错误：未配置密钥"
        client = OpenAI(api_key=ACTIVE_QWEN_KEY, base_url="https://dashscope.aliyuncs.com/compatible-mode/v1")
        try:
            completion = client.chat.completions.create(model=model_name, messages=[{"role": "user", "content": prompt}])
            return completion.choices[0].message.content
        except Exception as e: return f"Qwen 失败: {str(e)}"

def ai_ocr(image_bytes, provider, model_name):
    """根据引擎进行图片文字识别"""
    if provider == "Gemini":
        if not ACTIVE_GEMINI_KEY: return "错误：未配置密钥"
        try:
            model = genai.GenerativeModel(model_name)
            res = model.generate_content(["识别并输出图中文字内容。若是试卷，请提取题目和回答。", {"mime_type": "image/jpeg", "data": image_bytes}])
            return res.text
        except Exception as e: return f"Gemini 视觉识别失败: {str(e)}"
    else:
        if not ACTIVE_QWEN_KEY: return "错误：未配置密钥"
        # 图片压缩优化
        img = Image.open(io.BytesIO(image_bytes)).convert('RGB')
        max_width = 1024
        if img.width > max_width:
            scale = max_width / img.width
            img = img.resize((max_width, int(img.height * scale)))
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=90)
        b64img = base64.b64encode(buf.getvalue()).decode("utf-8")
        
        client = OpenAI(api_key=ACTIVE_QWEN_KEY, base_url="https://dashscope.aliyuncs.com/compatible-mode/v1")
        try:
            completion = client.chat.completions.create(
                model="qwen-vl-ocr-latest",
                messages=[{"role": "user", "content": [{"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64img}"}}, {"type": "text", "text": "请提取图中所有文字内容"}]}]
            )
            return completion.choices[0].message.content
        except Exception as e: return f"Qwen OCR 失败: {str(e)}"

# --- 5. 文档与工具函数 ---
def extract_text_from_file(file):
    """支持多格式文本提取"""
    try:
        if file.name.endswith(".docx"):
            return "\n".join([p.text for p in Document(file).paragraphs])
        elif file.name.endswith(".pdf"):
            with pdfplumber.open(file) as pdf:
                return "\n".join([page.extract_text() or "" for page in pdf.pages])
        elif file.name.endswith(".doc"):
            return mammoth.convert_to_text(file).value
        return "格式暂不支持"
    except Exception as e:
        return f"解析失败: {str(e)}"


def safe_extract_text(file, max_chars=15000):
    if not file: return ""
    try:
        text_list = []
        if file.name.endswith(".pdf"):
            with fitz.open(stream=file.read(), filetype="pdf") as doc:
                for page in doc:
                    text_list.append(page.get_text())
                    if sum(len(t) for t in text_list) > max_chars: break
            return "".join(text_list)[:max_chars]
            
        elif file.name.endswith(".docx"):
            doc = Document(file)
            for p in doc.paragraphs:
                if p.text.strip(): text_list.append(p.text)
            
            for table in doc.tables:
                for row in table.rows:
                    processed_cells = []
                    for cell in row.cells:
                        content = cell.text
                        # --- 核心改进：非互斥全量替换，涵盖更多 Word 特殊符号 ---
                        # 识别“已选中”符号
                        checked_chars = ['☑', 'þ', '\xfe', '\uf0fe', '☒', '√']
                        # 识别“未选中”符号
                        unchecked_chars = ['☐', '¨', '\xa8', '\uf0a1', '□']
                        
                        for c in checked_chars:
                            content = content.replace(c, '[已选中]')
                        for u in unchecked_chars:
                            content = content.replace(u, '[未选中]')
                        
                        processed_cells.append(content.strip())
                    
                    row_text = [c for c in processed_cells if c]
                    if row_text: text_list.append(" | ".join(row_text))
            
            return "\n".join(text_list)[:max_chars]
        elif file.name.endswith(".doc"):
            return mammoth.convert_to_text(file).value[:max_chars]            
        return ""

    except Exception as e:
        st.error(f"文件 {file.name} 解析出错: {str(e)}")
        return ""

def render_pdf_images(pdf_file):
    images = []
    pdf_file.seek(0)
    with fitz.open(stream=pdf_file.read(), filetype="pdf") as pdf:
        for page in pdf:
            pix = page.get_pixmap(matrix=fitz.Matrix(2,2))
            images.append(pix.tobytes("png"))
    return images


# -----------------------------
# JSON 可序列化工具（用于下载基座/调试）
# -----------------------------
def payload_to_jsonable(obj):
    """递归把常见不可 JSON 序列化对象转成可序列化结构。"""
    # pandas
    try:
        if isinstance(obj, pd.DataFrame):
            df = obj.copy().fillna("")
            return {
                "__type__": "dataframe",
                "columns": [str(c) for c in df.columns.tolist()],
                "data": df.astype(str).values.tolist(),
            }
        if hasattr(pd, "Timestamp") and isinstance(obj, pd.Timestamp):
            return obj.isoformat()
    except Exception:
        pass

    # numpy
    try:
        import numpy as _np
        if isinstance(obj, (_np.integer, _np.floating, _np.bool_)):
            return obj.item()
        if isinstance(obj, _np.ndarray):
            return obj.tolist()
    except Exception:
        pass

    # bytes
    if isinstance(obj, (bytes, bytearray)):
        return {
            "__type__": "bytes_base64",
            "data": base64.b64encode(bytes(obj)).decode("ascii"),
        }

    # datetime / date
    if isinstance(obj, (_dt.datetime, _dt.date)):
        return obj.isoformat()

    # Path
    if isinstance(obj, Path):
        return str(obj)

    # Decimal
    if isinstance(obj, Decimal):
        return float(obj)

    # set/tuple
    if isinstance(obj, (set, tuple)):
        return [payload_to_jsonable(x) for x in obj]

    # dict / list
    if isinstance(obj, dict):
        return {str(k): payload_to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [payload_to_jsonable(x) for x in obj]

    # 其它：尽量原样返回，必要时转字符串
    try:
        json.dumps(obj)
        return obj
    except Exception:
        return str(obj)


# -----------------------------
# 培养方案基座：PDF 文本 + 附表（7-10）抽取与跨页合并
# -----------------------------
_SECTION_PATTERNS = [
    ("1", [r"一[、\.\s]*培养目标", r"1[、\.\s]*培养目标"]),
    ("2", [r"二[、\.\s]*毕业要求", r"2[、\.\s]*毕业要求"]),
    ("3", [r"三[、\.\s]*专业定位与特色", r"3[、\.\s]*专业定位与特色"]),
    ("4", [r"四[、\.\s]*主干学科", r"4[、\.\s]*主干学科"]),
    ("5", [r"五[、\.\s]*标准学制", r"5[、\.\s]*标准学制"]),
    ("6", [r"六[、\.\s]*毕业条件", r"6[、\.\s]*毕业条件"]),
    ("7", [r"七[、\.\s]*专业教学计划表", r"附表\s*1", r"7[、\.\s]*专业教学计划表"]),
    ("8", [r"八[、\.\s]*学分统计表", r"附表\s*2", r"8[、\.\s]*学分统计表"]),
    ("9", [r"九[、\.\s]*教学进程表", r"附表\s*3", r"9[、\.\s]*教学进程表"]),
    ("10", [r"十[、\.\s]*课程设置对毕业要求支撑关系表", r"附表\s*4", r"10[、\.\s]*课程设置对毕业要求"]),
    ("11", [r"十一[、\.\s]*课程设置逻辑思维导图", r"附表\s*5", r"11[、\.\s]*课程设置逻辑思维导图"]),
]


def _compact_lines(s: str) -> str:
    s = (s or "").replace("\u00a0", " ")
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


def _read_pdf_pages_text(pdf_bytes: bytes) -> list[str]:
    pages = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for p in pdf.pages:
            txt = p.extract_text() or ""
            pages.append(_compact_lines(txt))
    return pages


def _join_pages(pages_text: list[str]) -> str:
    return _compact_lines("\n\n".join([t or "" for t in pages_text]))


def _build_section_spans(full_text: str) -> dict[str, tuple[int, int]]:
    hits = []
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
    spans = {}
    for i, (sec_id, start) in enumerate(hits):
        end = hits[i + 1][1] if i + 1 < len(hits) else len(full_text)
        spans[sec_id] = (start, end)
    return spans


def _extract_section_text(full_text: str, spans: dict[str, tuple[int, int]], sec_id: str) -> str:
    if sec_id not in spans:
        return ""
    s, e = spans[sec_id]
    chunk = (full_text[s:e] or "").strip()
    # 去掉标题行
    chunk = re.sub(r"^\s*(一|二|三|四|五|六|七|八|九|十|十一|\d+)[、\.\s]*[^\n]{0,60}\n", "", chunk)
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


def _safe_text(x) -> str:
    return "" if x is None else str(x).strip()


def _table_to_df(table_rows: list[list[str]]) -> pd.DataFrame:
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
        cols = _dedup_cols([_safe_text(c) for c in cols])
        df = pd.DataFrame(rows[1:], columns=cols)
    else:
        df = pd.DataFrame(rows, columns=[f"列{i+1}" for i in range(max_cols)])

    return _clean_df(df)


def _dedup_cols(cols: list[str]) -> list[str]:
    seen = {}
    out = []
    for c in cols:
        c0 = c.strip() or "列"
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
    df = df.loc[~df.apply(lambda r: all(str(x).strip() == "" for x in r), axis=1)]
    df = df.loc[:, ~df.apply(lambda c: all(str(x).strip() == "" for x in c), axis=0)]
    return df.reset_index(drop=True)


def _header_similarity(cols_a: list[str], cols_b: list[str]) -> float:
    a = {re.sub(r"\s+", "", c.lower()) for c in cols_a if str(c).strip()}
    b = {re.sub(r"\s+", "", c.lower()) for c in cols_b if str(c).strip()}
    if not a or not b:
        return 0.0
    return len(a & b) / max(1, len(a | b))


def _classify_table(df: pd.DataFrame) -> tuple[str, int]:
    if df is None or df.empty:
        return ("", 0)
    s = (" ".join([str(c) for c in df.columns.tolist()]) + " " + " ".join(df.astype(str).head(3).values.flatten())).lower()

    def score(keys):
        return sum(3 for k in keys if k in s)

    score7 = score(["课程编码", "课程代码", "课程名称", "学分", "总学时", "考核", "开课"])
    score8 = score(["学分统计", "必修", "选修", "通识", "专业", "实践", "合计", "小计"])
    score9 = score(["周次", "教学内容", "进度", "章节", "学时", "实验"])
    score10 = score(["毕业要求", "指标点", "支撑", "达成", "对应", "支撑关系"])

    best = max([("7", score7), ("8", score8), ("9", score9), ("10", score10)], key=lambda x: x[1])
    return best if best[1] >= 6 else ("", 0)


def _extract_tables_with_meta(pdf_bytes: bytes, page_idx_list: list[int]) -> list[dict]:
    out = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for pno in page_idx_list:
            if pno < 0 or pno >= len(pdf.pages):
                continue
            page = pdf.pages[pno]
            try:
                tables = page.extract_tables(table_settings=_valid_table_settings_lines()) or []
            except Exception:
                tables = page.extract_tables() or []
            for ti, t in enumerate(tables):
                norm = [[_safe_text(c) for c in row] for row in t]
                df = _table_to_df(norm)
                if df.empty:
                    continue
                out.append({"page": pno, "ti": ti, "df": df})
    return out


def _merge_tables_across_pages(items: list[dict]) -> pd.DataFrame:
    """把同一附表分布在多页的 df 合并：按页排序，表头相似则拼接行。"""
    if not items:
        return pd.DataFrame()
    items = sorted(items, key=lambda x: (x["page"], x["ti"]))
    base = items[0]["df"].copy()

    for it in items[1:]:
        df = it["df"].copy()
        sim = _header_similarity(base.columns.tolist(), df.columns.tolist())
        if sim < 0.45:
            # 表头差异太大：不合并
            continue

        # 去掉重复表头行（常见：第一页表头在每页重复出现）
        if len(df) >= 1:
            first_row = [str(x).strip() for x in df.iloc[0].tolist()]
            col_row = [str(x).strip() for x in df.columns.tolist()]
            if _header_similarity(first_row, col_row) > 0.7:
                df = df.iloc[1:].reset_index(drop=True)

        # 统一列
        all_cols = list(dict.fromkeys(list(base.columns) + list(df.columns)))
        base = base.reindex(columns=all_cols, fill_value="")
        df = df.reindex(columns=all_cols, fill_value="")
        base = pd.concat([base, df], ignore_index=True)

    return _clean_df(base)


def extract_appendix_tables_best_effort(pdf_bytes: bytes, pages_text: list[str]) -> tuple[dict[str, pd.DataFrame], dict]:
    n = len(pages_text)
    tail_pages = list(range(max(0, n - 24), n))  # 把范围扩大，覆盖“附表”常见位置
    items = _extract_tables_with_meta(pdf_bytes, tail_pages)

    buckets: dict[str, list[dict]] = {"7": [], "8": [], "9": [], "10": []}
    scored_preview = []
    for it in items:
        sec, score = _classify_table(it["df"])
        if sec:
            buckets[sec].append({**it, "score": score})
            scored_preview.append((it["page"], it["ti"], sec, score, list(it["df"].shape)))

    assigned = {}
    for sec in ["7", "8", "9", "10"]:
        if not buckets[sec]:
            continue
        # 只用得分较高的一组，并允许跨页合并
        buckets[sec].sort(key=lambda x: (x["score"], x["page"], x["ti"]), reverse=True)
        best_score = buckets[sec][0]["score"]
        group = [x for x in buckets[sec] if x["score"] >= max(6, best_score - 3)]
        assigned[sec] = _merge_tables_across_pages(group)

    debug = {
        "tail_pages": tail_pages,
        "tables_found": len(items),
        "scored_preview": scored_preview[:30],
        "assigned_shapes": {k: list(v.shape) for k, v in assigned.items()},
    }
    return assigned, debug


def base_plan_from_pdf(pdf_bytes: bytes) -> dict:
    pages = _read_pdf_pages_text(pdf_bytes)
    full = _join_pages(pages)
    spans = _build_section_spans(full)
    sections = {sec_id: _extract_section_text(full, spans, sec_id) for sec_id, _ in _SECTION_PATTERNS}

    # 若 7-11 在正文只有标题，给提示（不强行塞其他内容）
    for sec_id in ["7", "8", "9", "10", "11"]:
        if not sections.get(sec_id, "").strip():
            sections[sec_id] = f"{sec_id}：正文可能仅有标题；请尝试从 PDF 末尾附表自动抽取。"

    tables, debug = extract_appendix_tables_best_effort(pdf_bytes, pages)
    return {
        "pages": pages,
        "full_text": full,
        "sections": sections,
        "tables": tables,
        "debug": debug,
    }


# -----------------------------
# Word 教学日历：自动“转标签模板”工具（先不填充）
# -----------------------------
_TAG_MAP = [
    (r"课程名称", "course_name"),
    (r"英文名称|英文名", "english_name"),
    (r"课程代码|课程编码", "course_code"),
    (r"总学时|学时", "hours"),
    (r"教材", "textbook"),
    (r"考核方式|考核", "assessment"),
]


def _replace_after_colon(text: str, field_key: str) -> str:
    # 形如：课程名称：XXXX → 课程名称：{{ course_name }}
    m = re.search(r"(:|：)\s*([^\n]+)", text)
    if not m:
        return text
    prefix = text[: m.start(2)]
    return prefix + f"{{{{ {field_key} }}}}"


def _tag_paragraph(p, pattern: str, key: str):
    if not p.text:
        return
    if re.search(pattern, p.text) and "{{" not in p.text:
        p.text = _replace_after_colon(p.text, key)


def _insert_row_before(table, row_idx: int):
    """python-docx 原生没有 insert_row，使用 oxml 插入。"""
    tbl = table._tbl
    tr = OxmlElement('w:tr')
    tbl.insert(row_idx, tr)
    # 创建与列数一致的单元格
    for _ in range(len(table.columns)):
        tc = OxmlElement('w:tc')
        tcPr = OxmlElement('w:tcPr')
        tc.append(tcPr)
        p = OxmlElement('w:p')
        tc.append(p)
        tr.append(tc)
    return table.rows[row_idx]


def auto_tag_calendar_template(docx_bytes: bytes) -> bytes:
    doc = Document(io.BytesIO(docx_bytes))

    # 1) 段落字段替换
    for p in doc.paragraphs:
        for pat, key in _TAG_MAP:
            _tag_paragraph(p, pat, key)

    # 2) 表格字段替换 + 识别“日历表”并重建为 for-loop 结构
    for t in doc.tables:
        # 先对所有单元格做“字段：值”替换
        for row in t.rows:
            for cell in row.cells:
                for pat, key in _TAG_MAP:
                    if re.search(pat, cell.text) and "{{" not in cell.text:
                        cell.text = _replace_after_colon(cell.text, key)

        # 再判断是否为“教学日历表”
        if len(t.rows) < 2:
            continue
        header = [c.text.strip() for c in t.rows[0].cells]
        header_join = "|".join(header)
        if ("周次" in header_join) and ("课次" in header_join) and (len(header) >= 6):
            # 若已包含 for-loop，就不重复处理
            all_text = "\n".join([c.text for r in t.rows for c in r.cells])
            if "{% for" in all_text:
                continue

            # 删除除表头外的所有行
            while len(t.rows) > 1:
                t._tbl.remove(t.rows[1]._tr)

            # 插入 for-row / data-row / endfor-row
            start_row = t.add_row()
            data_row = t.add_row()
            end_row = t.add_row()

            start_row.cells[0].text = "{% for s in calendar_table %}"
            end_row.cells[0].text = "{% endfor %}"

            # 根据列名给默认占位
            col_keys = []
            for h in header:
                h2 = h.replace(" ", "")
                if "周次" in h2:
                    col_keys.append("week")
                elif "课次" in h2:
                    col_keys.append("session")
                elif "教学内容" in h2:
                    col_keys.append("content")
                elif "学习重点" in h2 or "重点" in h2:
                    col_keys.append("focus")
                elif "学时" in h2:
                    col_keys.append("hours")
                elif "教学方法" in h2 or "方法" in h2:
                    col_keys.append("method")
                elif "支撑" in h2:
                    col_keys.append("objective")
                else:
                    col_keys.append("col")

            for j, ck in enumerate(col_keys[: len(data_row.cells)]):
                if ck == "col":
                    data_row.cells[j].text = "{{ s.get('col', '') }}"
                else:
                    data_row.cells[j].text = f"{{{{ s.get('{ck}', '') }}}}"

            # 保持 start/end 行其它单元格为空
            for j in range(1, len(start_row.cells)):
                start_row.cells[j].text = ""
                end_row.cells[j].text = ""

    out = io.BytesIO()
    doc.save(out)
    return out.getvalue()

def nav_bar(show_back=False):
    st.markdown(f'<div style="background:#1E2129;padding:20px;border-radius:10px;margin-bottom:10px;"><h1 style="color:white;margin:0;font-size:24px;">🎓 智能教学与批卷系统 <span style="font-size:14px;color:#888;">{engine_id} 引擎在线</span></h1></div>', unsafe_allow_html=True)
    if show_back:
        if st.button("⬅️ 返回主页", use_container_width=True):
            st.query_params["page"] = "首页"
            st.rerun()

# --- 6. 页面功能定义 ---
def page_home():
    nav_bar()
    st.markdown("### 🛠️ 教务与批改功能矩阵")
    cols = st.columns(3)
    modules = [
        ("📄", "教学大纲生成", "大纲"), ("📅", "教学日历生成", "日历"), ("📋", "培养方案生成", "方案"),
        ("🏗️", "培养方案基座抽取", "基座"), ("🏷️", "Word 模板转标签", "模板"),
        ("📝", "智能批卷系统", "批卷"), ("📈", "成绩分析报告", "分析"), ("⚙️", "系统设置", "设置")
    ]
    for i, (icon, title, link) in enumerate(modules):
        with cols[i % 3]:
            st.markdown(f'<div style="border:1px solid #ddd;padding:20px;border-radius:10px;text-align:center;"><span style="font-size:40px;">{icon}</span><h4>{title}</h4></div>', unsafe_allow_html=True)
            if st.button(f"进入{title}", key=f"nav_{i}", use_container_width=True):
                st.query_params["page"] = link
                st.rerun()


def page_base_plan():
    """培养方案 PDF → 1–11 栏目抽取 + 末尾附表(7–10)跨页合并。"""
    nav_bar(show_back=True)
    st.subheader("🏗️ 培养方案基座抽取（1–11 + 附表 7–10）")
    st.caption("上传培养方案 PDF → 自动抽取正文栏目与末尾附表；附表 1/4 这类跨多页的表会自动合并。")

    pdf = st.file_uploader("上传培养方案 PDF", type=["pdf"], key="base_plan_pdf")
    c1, c2 = st.columns([1, 1])
    with c1:
        tail_pages = st.number_input("附表抽取：从末尾向前取页数", min_value=5, max_value=60, value=20, step=1)
    with c2:
        min_score = st.number_input("表格分类阈值（越大越保守）", min_value=3, max_value=15, value=6, step=1)

    if st.button("开始抽取并写入基座", type="primary", use_container_width=True, key="base_plan_extract"):
        if not pdf:
            st.error("请先上传 PDF。")
        else:
            with st.spinner("正在解析 PDF 并抽取..."):
                payload = base_plan_from_pdf(pdf.getvalue(), tail_pages=int(tail_pages), min_score=int(min_score))
                st.session_state["base_plan_payload"] = payload
            st.success("抽取完成。下方可查看/下载。")

    payload = st.session_state.get("base_plan_payload")
    if not payload:
        st.info("请上传 PDF 并点击“开始抽取并写入基座”。")
        return

    # 下载 JSON
    json_payload = payload_to_jsonable(payload)
    st.download_button(
        "下载基座 JSON（含栏目文本+附表表格）",
        data=json.dumps(json_payload, ensure_ascii=False, indent=2).encode("utf-8"),
        file_name="base_plan_payload.json",
        mime="application/json",
        use_container_width=True,
        key="dl_base_plan_json",
    )

    tabs = st.tabs(["栏目 1–11", "附表 7–10（可编辑）", "调试信息"])
    with tabs[0]:
        toc = [
            ("1", "培养目标"), ("2", "毕业要求"), ("3", "专业定位与特色"), ("4", "主干学科/核心课程/实践环节"),
            ("5", "标准学制与授予学位"), ("6", "毕业条件"), ("7", "专业教学计划表（附表1）"),
            ("8", "学分统计表（附表2）"), ("9", "教学进程表（附表3）"), ("10", "支撑关系表（附表4）"),
            ("11", "逻辑思维导图（附表5）"),
        ]
        sec_pick = st.selectbox("选择栏目", options=[x[0] for x in toc], format_func=lambda x: dict(toc)[x], key="base_plan_sec")
        st.markdown(f"#### {sec_pick}、{dict(toc)[sec_pick]}")
        st.text_area("抽取文本", value=payload.get("sections", {}).get(sec_pick, ""), height=280, key=f"base_plan_text_{sec_pick}")

    with tabs[1]:
        st.info("提示：这里展示的是自动抽取并跨页合并后的表；你可以直接编辑后导出。")
        for sec in ["7", "8", "9", "10"]:
            st.markdown(f"#### 附表 {sec}")
            df0 = payload.get("tables", {}).get(sec)
            if df0 is None or (isinstance(df0, pd.DataFrame) and df0.empty):
                st.warning("未抽取到该表（可能是图片表、线条不规则或版式特殊）。")
                df0 = pd.DataFrame()
            editor_key = f"base_tbl_{sec}"
            edited = st.data_editor(df0, num_rows="dynamic", use_container_width=True, key=editor_key)
            st.session_state[f"{editor_key}__value"] = edited

    with tabs[2]:
        st.json(payload.get("debug", {}))


def page_template_tagger():
    """把用户上传的 docx（普通范本）转换成可用 docxtpl 的“带标签模板”，并提供下载。"""
    nav_bar(show_back=True)
    st.subheader("🏷️ Word 范本 → 带标签模板（仅转换，不填充）")
    st.caption("把“课程名称/课程代码/学时/教材/考核”等字段自动替换成 {{ 标签 }}，并把‘教学日历表’改成可循环的 {% for %} 模板结构。")

    up = st.file_uploader("上传 Word 范本（.docx）", type=["docx"], key="tpl_tag_in")
    col1, col2 = st.columns([1, 1])
    with col1:
        loop_var = st.text_input("循环变量名", value="s", help="用于 calendar_table 循环，例如 {% for s in calendar_table %}")
    with col2:
        strict_mode = st.checkbox("严格模式（只替换已识别字段）", value=True)

    if st.button("转换为带标签模板并生成下载", type="primary", use_container_width=True, key="tpl_tag_btn"):
        if not up:
            st.error("请先上传 .docx 范本。")
        else:
            with st.spinner("正在转换..."):
                tagged_bytes, report = auto_tag_calendar_template(up.getvalue(), loop_var=loop_var.strip() or "s", strict=strict_mode)
                st.session_state["tagged_tpl_bytes"] = tagged_bytes
                st.session_state["tagged_tpl_report"] = report
            st.success("转换完成。请下载并人工快速检查：封面字段是否被正确替换、教学日历表是否只保留一行占位+循环标签。")

    tagged = st.session_state.get("tagged_tpl_bytes")
    if tagged:
        st.download_button(
            "下载带标签模板（.docx）",
            data=tagged,
            file_name="calendar_template_tagged.docx",
            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            use_container_width=True,
            key="tpl_tag_dl",
        )
        with st.expander("转换报告（方便排查）"):
            st.json(st.session_state.get("tagged_tpl_report", {}))

def page_syllabus():
    nav_bar(show_back=True)
    st.subheader("📄 深度智造：教学大纲 (支持上传教材分析)")
    
    # 5.1 上传辅助资料区域
    with st.expander("##### 📚 第一步：上传参考资料 (教材/培养方案/参考文献)", expanded=True):
        col_u1, col_u2 = st.columns(2)
        book_file = col_u1.file_uploader("上传教材/参考书 PDF/Word", type=["pdf", "docx"])
        plan_file = col_u2.file_uploader("上传人才培养方案 PDF/Word", type=["pdf", "docx"])
        
    # 5.2 手工填写基本信息
    with st.form("syllabus_form"):
        st.markdown("##### 📚 第二步：填写关键参数")        
        # 第一排：基础课程信息 
        c1, c2, c3 = st.columns(3)
        name = c1.text_input("课程名称", value="数值模拟在材料成型中的应用")
        major = c2.text_input("适用专业", value="材料成型及控制工程（焊接方向）")
        course_type = c3.selectbox("课程性质", ["必修", "限选", "选修"], index=1)

        # 第二排：学分学时与考核 
        c4, c5, c6 = st.columns(3)
        hours = c4.number_input("总学时", value=32)
        credits = c5.number_input("总学分", value=2.0, step=0.5)
        assessment = c6.selectbox("考核方式", ["考试", "考查"], index=1)

        # 第三排：学期与要求 
        c7, c8 = st.columns(2)
        semester = c7.selectbox("开课学期", ["一", "二", "三", "四", "五", "六", "七", "八"], index=4)
        prerequisites = c8.text_area("先修课程要求", value="高等数学、工程力学，具备基本微积分和工程力学知识", height=68)

        # 核心目标与思政
        obj = st.text_area("培养目标", placeholder="输入课程培养目标...", value="课程目标1：能够了解材料成型的数值模拟软件的原理和方法，并理解其局限性；\n课程目标2：能够选用合适的专业数值模拟软件分析材料成型工程中的复杂问题；\n课程目标3：能够选用适合的数值模拟软件预测材料成型工程问题，并分析其局限性。")
        ideology = st.text_area("思政融入点", value="国产工业软件发展、两弹一星精神")

        if st.form_submit_button("🚀 结合上传资料生成 OBE 标准大纲"):
            with st.spinner("正在阅读文档并构思大纲..."):
                #book_ctx = extract_text_from_file(book_file) if book_file else "未提供教材"
                plan_ctx = extract_text_from_file(plan_file) if plan_file else "未提供培养方案"   
                book_ctx = safe_extract_text(book_file) if book_file else "未提供教材"
                #plan_ctx = safe_extract_text(plan_file) if plan_file else "未提供培养方案"
                
                prompt = f"""
                        你是一位资深的高校工程教育认证专家。请为《{name}》课程撰写一份高质量教学大纲。文字专业且符合OBE理念。
                        
                        **严格排版要求：**
                        1. 禁止使用任何 HTML 标签（如 <br/>, <b> 等）。
                        2. 所有的表格必须使用标准 Markdown 格式：| 列1 | 列2 |。
                        3. 必须包含分隔线：| :--- | :--- |。
                        4. 每个表格上方和下方必须各留一行空行。
                        
                        **背景资料（请务必参考以下内容）：**
                        1. 教材/内容核心：{book_ctx[:12000]} (注：由于长度限制，已截取前1万字符)
                        2. 专业培养要求：{plan_ctx[:10000]}
                        
                        **手工填写的参数：**                    
                        - 课程性质：{course_type} | 考核方式：{assessment} | 学分：{credits} | 学时：{hours}
                        - 适用专业：{major} | 思政：{ideology} | 开课学期{semester} | 先修课程及其要求{prerequisites}                   
                        - 课程目标支撑毕业要求表（含课程目标{obj}
                        
                        **大纲必须包含：**
                        - 课程基本信息表，包含大纲名称、课程名称{name}、英文名称、编码、课程性质{course_type}、适用专业{major}、考核方式{assessment}、总学分{credits}、总 学 时{hours}（理论学时X、实验学时X、实训学时X、其他（讨论）	学时X）、开课学期{semester}、先修课程及其要求{prerequisites}等
                        - 课程简介（理实结合，不少于200字）
                        - 建议教材	 
                        - 参考资料	 
                        - 教学条件
                        - 课程目标支撑毕业要求表（含课程目标{obj}、支撑指标点如4.1/5.1及支撑强度H/M/L）
                        - 德育目标
                        - 教学内容学时分配表（确保总学时为{hours}）（教学内容参考教材和参考材料{book_ctx}，包含序号、教学内容、学生学习预期成果、计划学时、支撑目标、教学方式、其它（作业、习题、实验等）
                        - 课程目标考核
                        - 课程目标达成情况评价
                        - 考核评价表（包含平时成绩与期末考试占比）                    
                        - 课程考核，包含标准考试评分标准、作业评分标准
                        - 大作业评分标准，包含作业内容、评价标准（90-100分	70-89 分	60-69分	0-59分）、所占比重
                        - 课程思政实施方案（结合：{ideology}），包含思政内容切入点、典型案例、教育载体及方法、预期达到的目标、	体现的价值观或思政元素
                        
                        **尤其注意构建《课程目标支撑毕业要求表》时：**
                        请基于培养方案{plan_ctx}严格以下对应关系生成表格，禁止随意发挥：
                        1. 课程目标1：{obj.split('课程目标2')[0] if '课程目标2' in obj else obj} 
                           --> 必须支撑：5.1 (工具使用)。
                        2. 课程目标2：... (以此类推，请解析用户输入的 {obj})

                        **表格格式要求：**
                        | 课程目标 | 支撑毕业要求及指标点 | 支撑强度 (H/M/L) |
                        | :--- | :--- | :--- |
                        | 课程目标1：[简述目标内容] | 5.1 了解常用现代仪器... | H |
                        | 课程目标2：[简述目标内容] | 5.2 能够选择与使用恰当仪器... | M |

                        **特别注意：**
                        - 每一行只能对应一个课程目标。
                        - 每一个课程目标只能对应一个毕业要求及指标点
                        - 指标点描述必须完整。
                        - 支撑强度必须根据该目标对指标点的支撑力度给出唯一的 H、M 或 L。                        
                        """            
                # 执行生成并存入缓存
                st.session_state.gen_content["syllabus"] = ai_generate(prompt, engine_id, selected_model)
                st.session_state['course_name'] = name
                st.session_state['total_hours'] = hours
                st.session_state['major'] = major # 适用专业
                #st.session_state['assessment_method'] = assessment # 考核方式
                st.session_state['course_objectives'] = obj # 存储原始输入的课程目标文本
                st.session_state['ideology_points'] = ideology # 存储思政点，以便日历中安排思政课次                

                st.success("✅ 大纲生成成功！")

    if st.session_state.gen_content["syllabus"]:
        st.markdown("---")
        st.container(border=True).markdown(st.session_state.gen_content["syllabus"])
        col1, col2 = st.columns(2)
        col1.download_button("💾 下载 Word 版大纲", create_docx(st.session_state.gen_content["syllabus"]), file_name=f"{name}_大纲.docx")
        col2.download_button("📝 下载文本版 (TXT)", st.session_state.gen_content["syllabus"], file_name=f"{name}_大纲.txt")        



# ==================== 1. 核心渲染与辅助函数 ====================
# --- 辅助函数：读取模版结构 ---
def read_local_docx_structure(file_path):
    if not os.path.exists(file_path):
        return "模版文件不存在"
    try:
        doc = Document(file_path)
        return "\n".join([p.text for p in doc.paragraphs if "{{" in p.text])
    except:
        return "模版读取失败"

# --- 核心函数：渲染 Word 文档 ---
def render_calendar_docx(template_path, data_dict, sig_images=None):
    """
    data_dict: 包含所有标签键值的字典
    sig_images: 字典，格式为 {"标签名": 文件流}
    """
    try:
        doc = DocxTemplate(template_path)
        
        # 1. 递归清洗数据中的 None 或 N/A
        def clean_val(v):
            if v is None or str(v).lower() in ["none", "n/a", "未提供"]: return ""
            return v

        processed_data = {}
        for k, v in data_dict.items():
            if k == "schedule": # 进度表特殊处理
                processed_data[k] = [{sk: clean_val(sv) for sk, sv in item.items()} for item in v]
            else:
                processed_data[k] = clean_val(v)

        # 2. 注入签名图片
        if sig_images:
            for key, img_stream in sig_images.items():
                if img_stream:
                    # 将上传的图片转换为 Word 内部对象，宽度设为 30mm
                    processed_data[key] = InlineImage(doc, img_stream, width=Mm(30))
                else:
                    processed_data[key] = ""

        # 3. 渲染并导出
        doc.render(processed_data, autoescape=True)
        target_stream = io.BytesIO()
        doc.save(target_stream)
        return target_stream.getvalue()
    except Exception as e:
        st.error(f"渲染失败: {str(e)}")
        return None


# --- 教师端：编报页面 ---
def render_teacher_view():
    st.markdown("#### 📝 教师端：教学日历编报")
    
    # --- 1. 基础与课程信息 (全项) ---
    with st.container(border=True):
        st.markdown("##### 👤 1. 基本信息")
     
        c1, c2, c3 = st.columns([1.5, 2, 1.5])
        school_name = c1.text_input("学校名称", key="school_name")
        course_name = c2.text_input("课程名称", value=st.session_state.get('course_name', ""))
        class_info = c3.text_input("适用专业及年级", value=st.session_state.get('major', ""))
        
        t1, t2, t3, t4 = st.columns(4)
        teacher_name = t1.text_input("主讲教师", value=st.session_state.get('teacher_name', ""))
        teacher_title = t2.text_input("职称", value=st.session_state.get('teacher_title', ""))
        academic_year = t3.text_input("学年 (如 2025-2026)", value="2025-2026")
        semester = t4.selectbox("学期", ["1", "2"])

    # --- 2. 学时与教材配置 (全项) ---
    with st.container(border=True):
        st.markdown("##### 📚 2. 学时分配与教材")
        h1, h2, h3, h4 = st.columns(4)
        total_hours = h1.number_input("总学时数", value=int(st.session_state.get('total_hours', 24)))
        term_hours = h2.number_input("本学期总学时", value=total_hours)
        total_weeks = h3.number_input("上课周数", value=12)
        weekly_hours = h4.number_input("平均每周学时", value=total_hours//total_weeks if total_weeks > 0 else 2)

        d1, d2, d3, d4, d5 = st.columns(5)
        lec_h = d1.number_input("讲课学时", value=total_hours)
        lab_h = d2.number_input("实验学时", value=0)
        qui_h = d3.number_input("测验学时", value=0)
        ext_h = d4.number_input("课外学时", value=0)
        course_nature = d5.text_input("课程性质", value="专业必修")

        st.markdown("---")
        m1, m2, m3, m4 = st.columns([2, 1, 1, 1])
        book_name = m1.text_input("教材名称", value=st.session_state.get("textbook_name", ""))
        publisher = m2.text_input("出版社", value=st.session_state.get("publisher", ""))
        pub_date = m3.text_input("出版时间", value=st.session_state.get('publish_date', ""))
        book_remark = m4.text_input("获奖情况", value=st.session_state.get('textbook_remark', ""))
        ref_books = st.text_area("参考书目", value=st.session_state.get("references_text", ""))
        
        k1, k2 = st.columns(2)
        current_val = st.session_state.get('assessment_method', '考查')
        assess_method = k1.radio("考核方式", ["考试", "考查"], horizontal=True, 
                                 index=0 if "考试" in current_val else 1)
        grading_formula = k2.text_input("成绩计算方法", value="总成绩=平时成绩 30%+考试成绩 70%")                         


    # --- 3. 备注与签名 ---
    with st.container(border=True):
        st.markdown("##### 📝 3. 其他信息")
        n1, n2, n3 = st.columns(3)
        note_1 = n1.text_input("备注1", value="在授课过程中，可能根据学生接受情况，微调课程进度")
        note_2 = n2.text_input("备注2", value="遇到偶发情况需要调课，需履行调停课手续")
        note_3 = n3.text_input("备注3", value="")
        
        teacher_sig_file = st.file_uploader("✍️ 上传/更换手写签名", type=['png', 'jpg'], key="t_sig_up")

    # --- 4. 进度表编辑 (含学时拆分) ---
    st.divider()
    st.markdown("##### 🗓️ 4. 进度安排 (学时 > 2 自动拆分)")
    syllabus_file = st.file_uploader("通过大纲抽取内容 (可选)", type=['docx', 'pdf'])
    
    # 在点击按钮后的逻辑中
    if st.button("🪄 依据大纲抽取并自动拆分学时"):
    
        syl_content = ""
        if syllabus_file:
            syl_content = safe_extract_text(syllabus_file)
        else:
            # 尝试从上一页生成的大纲中获取，若无则为空字符串
            syl_content = st.session_state.gen_content.get("syllabus") or ""
        
        if not syl_content.strip():
            st.warning("⚠️ 未检测到大纲内容。请先上传大纲文件，或在“教学大纲生成”页面先生成大纲。")
            return

        with st.spinner("正在深度解析大纲并同步填报信息..."):
            syl_ctx = safe_extract_text(syllabus_file) if syllabus_file else st.session_state.gen_content.get("syllabus", "")
            
            # 定义完整提取提示词
            split_prompt = f"""
            # 角色
            你是一位精通 OBE 理念的高校教务专家。
            
            # 任务
            解析提供的【教学大纲】，提取所有填报项，并生成严格对齐课次的教学日历 JSON。
            
            # 核心约束（最高优先级）
            1. **数学平衡**：总学时为 {total_hours}，总周数为 {total_weeks}。经计算，每周必须精确安排 【{weekly_hours}】 学时。
            2. **周学时定额**：在 schedule 列表中，同一周(week)内所有项的 hrs 之和必须【绝对等于】{weekly_hours}。
            3. **拆分逻辑**：若大纲某模块学时 > {weekly_hours}，必须拆分为连续的两周（或更多）。例如：模块X(4学时) -> 第N周(2学时) + 第N+1周(2学时)。
            4. **合并逻辑**：若某模块学时为 1，必须与大纲下一个模块合并在同一周(week)内，确保该周总学时为 {weekly_hours}。
            
            # 提取字段要求
            请从大纲中提取并输出以下 JSON 结构：
            {{
                "base_info": {{
                    "course_name": "从大纲标题或第一表提取课程名称",
                    "textbook_name": "教材名称",
                    "publisher": "出版社",
                    "publish_date": "出版时间",
                    "textbook_remark": "获奖情况",
                    "references": "参考书目字符串",
                    "assessment_method": "考试或考查",
                    "grading_formula": "成绩计算方法",
                    "lecture_hours": 讲课学时(数字),
                    "lab_hours": 实验学时(数字),
                    "quiz_hours": 测验学时(数字),
                    "extra_hours": 课外学时(数字)
                }},

                "schedule": [
                    {{ "week": 1, "sess": 1, "content": "章节内容", "req": "重点要求", "hrs": 数字, "method": "方法", "other": "作业", "obj": "目标", "source_text": "大纲原文片段" }}
                ]
            }}
            
            # 参考资料
            教学大纲内容：{syl_ctx[:10000]}
            """
            
            res = ai_generate(split_prompt, engine_id, selected_model)
            try:
                # # 1. 解析 JSON
                # match = re.search(r'\{.*\}', res, re.DOTALL)
                # full_data = json.loads(match.group(0))
                
                # # 2. 自动刷新 UI 字段（将提取的信息存入 session_state）
                # bi = full_data.get("base_info", {})
                
                # --- 核心修复：解决 Extra Data 报错 ---
                # 贪婪匹配最后一个花括号，确保只截取最完整的 JSON 块
                match = re.search(r'(\{.*\})', res, re.DOTALL)
                if not match:
                    st.error("AI 未返回有效的 JSON 格式")
                    return
                
                json_str = match.group(1).strip()
                full_data = json.loads(json_str)
                bi = full_data.get("base_info", {})  
                st.session_state["textbook_name"] = bi.get("textbook_name", "")
                st.session_state["publisher"] = bi.get("publisher", "")
                st.session_state["publish_date"] = bi.get("publish_date", "")
                st.session_state["textbook_remark"] = bi.get("textbook_remark", "")
                st.session_state["references_text"] = bi.get("references", "")
                st.session_state["assessment_method"] = bi.get("assessment_method", "考查")
                st.session_state["grading_formula"] = bi.get("grading_formula", "")
                
                # 3. 进度表数据处理
                raw_schedule = full_data.get("schedule", [])
                st.session_state.calendar_data = pd.DataFrame(raw_schedule).fillna("").astype(str).to_dict('records')
                
                st.success("✅ 大纲信息已同步刷新至上方表单！")
                st.rerun() # 强制刷新页面以显示新数据
            except Exception as e:
                st.error(f"解析并同步失败: {str(e)}")

    if st.session_state.calendar_data:
        # 隐藏 source_text 以保持页面整洁，但保留在数据中
        st.session_state.calendar_data = st.data_editor(
            pd.DataFrame(st.session_state.calendar_data).astype(str),
            column_config={
                "source_text": None, # 隐藏原文依据列，不显示但保留数据
                "content": st.column_config.TextColumn("教学内容", width="large"),
                "hrs": st.column_config.NumberColumn("学时", min_value=1, max_value=4)
            },
            num_rows="dynamic", use_container_width=True
        ).to_dict('records')
        
        
    # --- 5. 提交审批 (统一变量名为 calendar_final_data) ---
    if st.button("📤 提交教学日历审批", type="primary", use_container_width=True):
        if not st.session_state.calendar_data:
            st.error("进度表内容为空，无法提交。")
        else:
            ref_list = [line.strip() for line in ref_books.split('\n') if line.strip()]
            # 封装为 template_general.docx 需要的所有键 
            st.session_state.calendar_final_data = {
                "school_name": school_name, "academic_year": academic_year, "semester": semester,
                "course_name": course_name, "class_info": class_info, "teacher_name": teacher_name,
                "teacher_title": teacher_title, "total_hours": total_hours, "term_hours": term_hours,
                "total_weeks": total_weeks, "weekly_hours": weekly_hours, "course_nature": course_nature,
                "lecture_hours": lec_h, "lab_hours": lab_h, "quiz_hours": qui_h, "extra_hours": ext_h,
                "textbook_name": book_name, "publisher": publisher, "publish_date": pub_date,
                "textbook_remark": book_remark, 
                #"references": [ref_books], 
                "assessment_method": assess_method,
                "grading_formula": grading_formula, "schedule": st.session_state.calendar_data,
                "note_1": note_1, "note_2": note_2, "note_3": note_3,
                "sign_date_1": datetime.now().strftime("%Y年 %m月 %d日"),
                "references": ref_list, # 传入拆分后的列表，确保模板可以循环渲染
            }
            st.session_state.teacher_sign_img_file = teacher_sig_file
            st.session_state.calendar_status = "Pending_Head"
            st.success("✅ 已提交至系主任审批！")
            st.rerun()

def render_approval_view(role):
    st.markdown(f"#### 🛡️ {'系主任' if role == 'Head' else '主管院长'}审批界面")
    
    # 核心安全检查：如果数据包不存在，显示提示而非报错
    data = st.session_state.get("calendar_final_data")
    if not data:
        st.info("🍵 目前没有待处理的教学日历申请。")
        return

    target_status = "Pending_Head" if role == "Head" else "Pending_Dean"
    if st.session_state.calendar_status == target_status:
        st.info(f"待处理：{data['course_name']} (教师：{data['teacher_name']})")
        st.table(pd.DataFrame(data['schedule']).drop(columns=['source_text'], errors='ignore'))
        
        with st.form(f"form_{role}"):
            opinion = st.text_area("审批意见", value="同意。")
            sig_file = st.file_uploader("签署手写签名", type=['png', 'jpg'])
            c1, c2 = st.columns(2)
            if c1.form_submit_button("✅ 批准"):
                st.session_state[f"{role.lower()}_opinion"] = opinion
                st.session_state[f"{role.lower()}_sig_img"] = sig_file
                st.session_state[f"{role.lower()}_date"] = datetime.now().strftime("%Y年 %m月 %d日")
                st.session_state.calendar_status = "Pending_Dean" if role == "Head" else "Approved"
                st.rerun()
            if c2.form_submit_button("❌ 退回"):
                st.session_state.calendar_status = "Draft"
                st.rerun()
    else:
        st.write("🍵 暂无待办事项。")

def page_calendar():
    nav_bar(show_back=True)
    st.subheader("📅 教学日历编报与多级审批")
    
    user_role = st.sidebar.selectbox("切换角色视图", ["授课教师", "系主任", "主管院长"])
    
    if user_role == "授课教师": render_teacher_view()
    elif user_role == "系主任": render_approval_view("Head")
    else: render_approval_view("Dean")

# --- 7. 审批过程实时显示 (新增模块) ---
    st.divider()
    st.markdown("##### 🚥 教学日历审批进度监控")
    
    # 定义状态映射与进度百分比
    status_map = {
        "Draft": {"val": 10, "label": "草拟中", "color": "gray"},
        "Pending_Head": {"val": 40, "label": "待教研室主任审批", "color": "blue"},
        "Pending_Dean": {"val": 70, "label": "待学院主管领导审批", "color": "orange"},
        "Approved": {"val": 100, "label": "审批已通过", "color": "green"}
    }
    
    curr_status = st.session_state.get("calendar_status", "Draft")
    progress_info = status_map.get(curr_status, status_map["Draft"])
    
    # 渲染进度条
    st.progress(progress_info["val"])
    
    # 渲染可视化节点
    n1, n2, n3, n4 = st.columns(4)
    nodes = [("Draft", "草拟"), ("Pending_Head", "系主任审核"), ("Pending_Dean", "主管院长审批"), ("Approved", "完成归档")]
    for i, (status_key, label) in enumerate(nodes):
        col = [n1, n2, n3, n4][i]
        if status_map[curr_status]["val"] >= status_map[status_key]["val"]:
            col.success(f"● {label}")
        else:
            col.write(f"○ {label}")

    # 审批结果与详细意见查看区域
    with st.expander("📋 查看审批意见与结果详情", expanded=(curr_status != "Draft")):
        if curr_status == "Draft":
            st.info("💡 当前处于草拟阶段，尚未提交审批。")
        else:
            # 1. 教研室主任审批信息
            st.markdown("**【教研室主任审批】**")
            head_op = st.session_state.get("head_opinion", "等待处理...")
            st.write(f"> 审批意见：{head_op}")
            if "head_date" in st.session_state:
                st.caption(f"审批时间：{st.session_state.head_date}")
            if st.session_state.get("head_sign_img"):
                st.image(st.session_state.head_sign_img, width=120, caption="系主任签名")
            
            st.divider()
            
            # 2. 学院领导审批信息
            st.markdown("**【学院主管领导审批】**")
            dean_op = st.session_state.get("dean_opinion", "等待处理...")
            st.write(f"> 审批意见：{dean_op}")
            if "dean_date" in st.session_state:
                st.caption(f"审批时间：{st.session_state.dean_date}")
            if st.session_state.get("dean_sign_img"):
                st.image(st.session_state.dean_sign_img, width=120, caption="院长签名")

    # --- 下载区域 ---
    if curr_status == "Approved":
        st.balloons()
        final_data = st.session_state.calendar_final_data
        # 补全审批意见 
        final_data.update({
            "head_opinion": st.session_state.get("head_opinion", ""),
            "sign_date_2": st.session_state.get("head_date", ""),
            "dean_opinion": st.session_state.get("dean_opinion", ""),
            "sign_date_3": st.session_state.get("dean_date", "")
        })
        sig_map = {
            "teacher_sign_img": st.session_state.get("teacher_sign_img_file"),
            "head_sign_img": st.session_state.get("head_sig_img"),
            "dean_sign_img": st.session_state.get("dean_sig_img")
        }


        # 核心修复：直接从已提交的数据包里读学校名
        submitted_school = final_data.get("school_name", "").strip()
        
        # 使用 if-elif-else 结构更清晰
        if submitted_school == "辽宁石油化工大学":
            target_tpl = "template_lnpu.docx"
        else:
            target_tpl = "template_general.docx"

        # 执行填充
        doc_bytes = render_calendar_docx(target_tpl, final_data, sig_map)

        if doc_bytes:
            st.download_button("📥 下载完整审批版 (.docx)", data=doc_bytes, file_name="教学日历_已审批.docx")
  
def page_program():
    nav_bar(show_back=True)
    st.subheader("📋 专业人才培养方案生成")
    with st.form("program_form"):
        major = st.text_input("专业名称", value="材料成型及控制工程")
        pos = st.text_area("专业特色", value="服务石油化工行业，聚焦焊接成型与无损检测")
        if st.form_submit_button("生成人才培养方案"):
            prompt = f"撰写{major}专业2024级培养方案。含培养目标、12项毕业要求、特色定位({pos})、核心课程。专业严谨。"
            with st.spinner("正在构建方案..."):
                st.session_state.generated_program = ai_generate(prompt, engine_id, selected_model)

    if st.session_state.generated_program:
        st.markdown("---")
        st.container(border=True).markdown(st.session_state.gen_content["program"])
        st.download_button("💾 下载 Word 版培养方案", create_docx(st.session_state.gen_content["program"]), file_name="培养方案.docx")

def page_grading():
    nav_bar(show_back=True)
    st.subheader("📝 智能试卷批阅与评价")
    c1, c2 = st.columns(2)
    with c1:
        q_file = st.file_uploader("1. 上传试题 (PDF/Word)", type=["pdf", "docx"], key="q")
        q_txt = extract_text_from_file(q_file) if q_file else ""
    with c2:
        s_file = st.file_uploader("2. 上传标准答案 (PDF/Word)", type=["pdf", "docx"], key="s")
        s_txt = extract_text_from_file(s_file) if s_file else ""

    st.divider()
    papers = st.file_uploader("3. 批量上传学生卷纸 (图片/PDF)", type=["jpg", "png", "pdf"], accept_multiple_files=True)

    for idx, paper in enumerate(papers or []):
        with st.container(border=True):
            st.write(f"**学生 {idx+1}:** {paper.name}")
            s_name = st.text_input("姓名", value=f"学生_{idx+1}", key=f"sn_{idx}")
            
            ocr_text = ""
            if paper.type == "application/pdf":
                imgs = render_pdf_images(paper)
                for i, img in enumerate(imgs):
                    st.image(img, width=350)
                    with st.expander("🔍 查看高清大图"): st.image(img, use_container_width=True)
                    with st.spinner("识别中..."): ocr_text += ai_ocr(img, engine_id, selected_model) + "\n"
            else:
                img_data = paper.read()
                st.image(img_data, width=350)
                with st.expander("🔍 查看高清大图"): st.image(img_data, use_container_width=True)
                with st.spinner("识别中..."): ocr_text = ai_ocr(img_data, engine_id, selected_model)
            
            final_ans = st.text_area("识别结果校对", value=ocr_text, key=f"ocr_{idx}", height=150)
            
            if st.button(f"🚀 {engine_id} 自动批改", key=f"go_{idx}"):
                with st.spinner("正在评分..."):
                    p = f"题目：{q_txt}\n答案：{s_txt}\n学生：{final_ans}\n请评分(满分100)并给出批注。格式：\n分数：[数字]\n批注：[解析]"
                    res = ai_generate(p, engine_id, selected_model)
                    st.markdown(res)
                    score = int(re.search(r"分数[：:]\s*(\d+)", res).group(1)) if re.search(r"分数[：:]\s*(\d+)", res) else 0
                    st.session_state.score_records.append({"学生": s_name, "分数": score, "评价": res})

def page_analysis():
    nav_bar(show_back=True)
    st.subheader("📈 成绩与分析报告")
    if not st.session_state.score_records:
        st.warning("当前无批改记录")
        return
    st.dataframe(st.session_state.score_records, use_container_width=True)
    scores = [r["分数"] for r in st.session_state.score_records]
    col1, col2 = st.columns(2)
    with col1:
        st.metric("平均分", f"{np.mean(scores):.1f}")
        fig, ax = plt.subplots(figsize=(8, 4))
        ax.hist(scores, bins=range(0, 110, 10), color='#4F8BF9', edgecolor='white')
        st.pyplot(fig)
    with col2:
        st.download_button("导出成绩记录 (CSV)", str(st.session_state.score_records), "scores.csv")

# --- 7. 路由逻辑 ---
# -----------------------------
# Router (fix NameError)
# -----------------------------
route = {
    "首页": lambda: page_home(),
    "大纲": lambda: page_syllabus(),
    "日历": lambda: page_calendar(),
    "方案": lambda: page_program(),    
    "基座": lambda: page_base(),
    "模板": lambda: page_template_tagger(),
    "批卷": lambda: page_grading(),
    "分析": lambda: page_analysis(),
    "设置": lambda: page_settings(),  # ✅ 延迟到点击时才解析名字
}

current = st.query_params.get("page", "首页")
route.get(current, lambda: page_home())()
