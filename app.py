import os
import streamlit as st
import pdfplumber
import fitz  # PyMuPDF
from docx import Document
from docx.shared import Pt
import mammoth
import requests
import re
import numpy as np
import matplotlib.pyplot as plt
from openai import OpenAI
import base64
import io
from PIL import Image
import google.generativeai as genai



# --- 1. 基础环境与配置 ---
plt.rcParams['font.family'] = ['SimHei', 'sans-serif']
plt.rcParams['axes.unicode_minus'] = False

st.set_page_config(page_title="智能教学辅助系统", layout="wide", initial_sidebar_state="expanded")

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
    """高性能、低内存占用文本提取 (针对大教材优化)"""
    if not file: return ""
    try:
        text_list = []
        if file.name.endswith(".pdf"):
            # 使用 PyMuPDF (fitz) 进行流式读取，内存占用极小
            with fitz.open(stream=file.read(), filetype="pdf") as doc:
                for page in doc:
                    text_list.append(page.get_text())
                    # 达到长度限制即刻停止解析，防止内存溢出
                    if sum(len(t) for t in text_list) > max_chars:
                        break
            return "".join(text_list)[:max_chars]
            
        elif file.name.endswith(".docx"):
            doc = Document(file)
            full_text = [p.text for p in doc.paragraphs]
            return "\n".join(full_text)[:max_chars]
            
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
        ("📝", "智能批卷系统", "批卷"), ("📈", "成绩分析报告", "分析"), ("⚙️", "系统设置", "设置")
    ]
    for i, (icon, title, link) in enumerate(modules):
        with cols[i % 3]:
            st.markdown(f'<div style="border:1px solid #ddd;padding:20px;border-radius:10px;text-align:center;"><span style="font-size:40px;">{icon}</span><h4>{title}</h4></div>', unsafe_allow_html=True)
            if st.button(f"进入{title}", key=f"nav_{i}", use_container_width=True):
                st.query_params["page"] = link
                st.rerun()

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
                st.session_state['assessment_method'] = assessment # 考核方式
                st.session_state['course_objectives'] = obj # 存储原始输入的课程目标文本
                st.session_state['ideology_points'] = ideology # 存储思政点，以便日历中安排思政课次                

                st.success("✅ 大纲生成成功！")

    if st.session_state.gen_content["syllabus"]:
        st.markdown("---")
        st.container(border=True).markdown(st.session_state.gen_content["syllabus"])
        col1, col2 = st.columns(2)
        col1.download_button("💾 下载 Word 版大纲", create_docx(st.session_state.gen_content["syllabus"]), file_name=f"{name}_大纲.docx")
        col2.download_button("📝 下载文本版 (TXT)", st.session_state.gen_content["syllabus"], file_name=f"{name}_大纲.txt")        


import os
import io
import json
import re
import streamlit as st
from docx import Document
from docxtpl import DocxTemplate  # 必须安装 docxtpl

# ==================== 1. 核心渲染与辅助函数 ====================

def read_local_docx_structure(file_path):
    """读取本地模版文字，供 AI 学习标签位置"""
    if not os.path.exists(file_path):
        return f"错误：文件 {file_path} 不存在。"
    try:
        doc = Document(file_path)
        return "\n".join([p.text for p in doc.paragraphs if "{{" in p.text])
    except:
        return "模版读取失败"

def render_calendar_docx(template_path, json_str):
    try:
        clean_json = re.sub(r'```json\s*|\s*```', '', json_str).strip()
        data = json.loads(clean_json)
        
        # --- 新增：确保 schedule 键存在，防止 's' is undefined 报错 ---
        if "schedule" not in data:
            data["schedule"] = [] 
            
        doc = DocxTemplate(template_path)
        doc.render(data)
        
        target_stream = io.BytesIO()
        doc.save(target_stream)
        return target_stream.getvalue()
    except Exception as e:
        st.error(f"模版填充失败: {str(e)}")
        return None
def clean_none(obj):
    if isinstance(obj, dict):
        return {k: clean_none(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [clean_none(x) for x in obj]
    return "" if obj is None else obj
<<<<<<< HEAD


from docx import Document
from docx.shared import Inches, Pt
import zipfile
import tempfile
import os

def create_fixed_template_from_xml():
    """从正确的 XML 创建模板文件"""
    # 使用你提供的正确 XML
    correct_xml = '''<?xml version='1.0' encoding='UTF-8' standalone='yes'?>
<w:document xmlns:wpc="http://schemas.microsoft.com/office/word/2010/wordprocessingCanvas" xmlns:mo="http://schemas.microsoft.com/office/mac/office/2008/main" xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006" xmlns:mv="urn:schemas-microsoft-com:mac:vml" xmlns:o="urn:schemas-microsoft-com:office:office" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" xmlns:m="http://schemas.openxmlformats.org/officeDocument/2006/math" xmlns:v="urn:schemas-microsoft-com:vml" xmlns:wp14="http://schemas.microsoft.com/office/word/2010/wordprocessingDrawing" xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" xmlns:w10="urn:schemas-microsoft-com:office:word" xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" xmlns:w14="http://schemas.microsoft.com/office/word/2010/wordml" xmlns:wpg="http://schemas.microsoft.com/office/word/2010/wordprocessingGroup" xmlns:wpi="http://schemas.microsoft.com/office/word/2010/wordprocessingInk" xmlns:wne="http://schemas.microsoft.com/office/word/2006/wordml" xmlns:wps="http://schemas.microsoft.com/office/word/2010/wordprocessingShape" mc:Ignorable="w14 wp14"><w:body><w:p><w:pPr><w:pStyle w:val="Title"/></w:pPr><w:r><w:t>教学日历</w:t></w:r></w:p><w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>一、课程基本信息</w:t></w:r></w:p><w:tbl><w:tblPr><w:tblStyle w:val="TableGrid"/><w:tblW w:type="auto" w:w="0"/><w:tblLook w:firstColumn="1" w:firstRow="1" w:lastColumn="0" w:lastRow="0" w:noHBand="0" w:noVBand="1" w:val="04A0"/></w:tblPr><w:tblGrid><w:gridCol w:w="4320"/><w:gridCol w:w="4320"/></w:tblGrid><w:tr><w:tc><w:tcPr><w:tcW w:type="dxa" w:w="4320"/></w:tcPr><w:p><w:r><w:t>项目</w:t></w:r></w:p></w:tc><w:tc><w:tcPr><w:tcW w:type="dxa" w:w="4320"/></w:tcPr><w:p><w:r><w:t>内容</w:t></w:r></w:p></w:tc></w:tr><w:tr><w:tc><w:tcPr><w:tcW w:type="dxa" w:w="4320"/></w:tcPr><w:p><w:r><w:t>课程名称</w:t></w:r></w:p></w:tc><w:tc><w:tcPr><w:tcW w:type="dxa" w:w="4320"/></w:tcPr><w:p><w:r><w:t>{{course_name}}</w:t></w:r></w:p></w:tc></w:tr><w:tr><w:tc><w:tcPr><w:tcW w:type="dxa" w:w="4320"/></w:tcPr><w:p><w:r><w:t>英文名称</w:t></w:r></w:p></w:tc><w:tc><w:tcPr><w:tcW w:type="dxa" w:w="4320"/></w:tcPr><w:p><w:r><w:t>{{english_name}}</w:t></w:r></w:p></w:tc></w:tr><w:tr><w:tc><w:tcPr><w:tcW w:type="dxa" w:w="4320"/></w:tcPr><w:p><w:r><w:t>课程编码</w:t></w:r></w:p></w:tc><w:tc><w:tcPr><w:tcW w:type="dxa" w:w="4320"/></w:tcPr><w:p><w:r><w:t>{{course_code}}</w:t></w:r></w:p></w:tc></w:tr><w:tr><w:tc><w:tcPr><w:tcW w:type="dxa" w:w="4320"/></w:tcPr><w:p><w:r><w:t>总学时</w:t></w:r></w:p></w:tc><w:tc><w:tcPr><w:tcW w:type="dxa" w:w="4320"/></w:tcPr><w:p><w:r><w:t>{{total_hours}}</w:t></w:r></w:p></w:tc></w:tr><w:tr><w:tc><w:tcPr><w:tcW w:type="dxa" w:w="4320"/></w:tcPr><w:p><w:r><w:t>学分数</w:t></w:r></w:p></w:tc><w:tc><w:tcPr><w:tcW w:type="dxa" w:w="4320"/></w:tcPr><w:p><w:r><w:t>{{credits}}</w:t></w:r></w:p></w:tc></w:tr><w:tr><w:tc><w:tcPr><w:tcW w:type="dxa" w:w="4320"/></w:tcPr><w:p><w:r><w:t>开课学期</w:t></w:r></w:p></w:tc><w:tc><w:tcPr><w:tcW w:type="dxa" w:w="4320"/></w:tcPr><w:p><w:r><w:t>{{semester}}</w:t></w:r></w:p></w:tc></w:tr></w:tbl><w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>二、教学日历</w:t></w:r></w:p><w:tbl><w:tblPr><w:tblStyle w:val="TableGrid"/><w:tblW w:type="auto" w:w="0"/><w:tblLook w:firstColumn="1" w:firstRow="1" w:lastColumn="0" w:lastRow="0" w:noHBand="0" w:noVBand="1" w:val="04A0"/></w:tblPr><w:tblGrid><w:gridCol w:w="1234"/><w:gridCol w:w="1234"/><w:gridCol w:w="1234"/><w:gridCol w:w="1234"/><w:gridCol w:w="1234"/><w:gridCol w:w="1234"/><w:gridCol w:w="1234"/></w:tblGrid><w:tr><w:tc><w:tcPr><w:tcW w:type="dxa" w:w="1234"/></w:tcPr><w:p><w:r><w:t>周次</w:t></w:r></w:p></w:tc><w:tc><w:tcPr><w:tcW w:type="dxa" w:w="1234"/></w:tcPr><w:p><w:r><w:t>课次</w:t></w:r></w:p></w:tc><w:tc><w:tcPr><w:tcW w:type="dxa" w:w="1234"/></w:tcPr><w:p><w:r><w:t>教学内容</w:t></w:r></w:p></w:tc><w:tc><w:tcPr><w:tcW w:type="dxa" w:w="1234"/></w:tcPr><w:p><w:r><w:t>学习重点</w:t></w:r></w:p></w:tc><w:tc><w:tcPr><w:tcW w:type="dxa" w:w="1234"/></w:tcPr><w:p><w:r><w:t>学时</w:t></w:r></w:p></w:tc><w:tc><w:tcPr><w:tcW w:type="dxa" w:w="1234"/></w:tcPr><w:p><w:r><w:t>教学方法</w:t></w:r></w:p></w:tc><w:tc><w:tcPr><w:tcW w:type="dxa" w:w="1234"/></w:tcPr><w:p><w:r><w:t>支撑目标</w:t></w:r></w:p></w:tc></w:tr><w:tr><w:tc><w:tcPr><w:tcW w:type="dxa" w:w="1234"/></w:tcPr><w:p><w:r><w:t>{% for s in schedule %}{{ s.week_num }}</w:t></w:r></w:p></w:tc><w:tc><w:tcPr><w:tcW w:type="dxa" w:w="1234"/></w:tcPr><w:p><w:r><w:t>{{ s.session_num }}</w:t></w:r></w:p></w:tc><w:tc><w:tcPr><w:tcW w:type="dxa" w:w="1234"/></w:tcPr><w:p><w:r><w:t>{{ s.teaching_content }}</w:t></w:r></w:p></w:tc><w:tc><w:tcPr><w:tcW w:type="dxa" w:w="1234"/></w:tcPr><w:p><w:r><w:t>{{ s.learning_focus }}</w:t></w:r></w:p></w:tc><w:tc><w:tcPr><w:tcW w:type="dxa" w:w="1234"/></w:tcPr><w:p><w:r><w:t>{{ s.hours }}</w:t></w:r></w:p></w:tc><w:tc><w:tcPr><w:tcW w:type="dxa" w:w="1234"/></w:tcPr><w:p><w:r><w:t>{{ s.teaching_method }}</w:t></w:r></w:p></w:tc><w:tc><w:tcPr><w:tcW w:type="dxa" w:w="1234"/></w:tcPr><w:p><w:r><w:t>{{ s.objective }}{% endfor %}</w:t></w:r></w:p></w:tc></w:tr></w:tbl><w:p><w:r><w:t>说明：</w:t></w:r></w:p><w:p><w:r><w:t>1. 表格中的 {{标签}} 将在填充时被替换为实际内容</w:t></w:r></w:p><w:p><w:r><w:t>2. 如需多行数据，请在Word中复制表格行</w:t></w:r></w:p><w:p><w:r><w:t>3. 标签命名建议使用英文和下划线，如：{{teacher_name}}</w:t></w:r></w:p><w:sectPr w:rsidR="00FC693F" w:rsidRPr="0006063C" w:rsidSect="00034616"><w:pgSz w:w="12240" w:h="15840"/><w:pgMar w:top="1440" w:right="1800" w:bottom="1440" w:left="1800" w:header="720" w:footer="720" w:gutter="0"/><w:cols w:space="720"/><w:docGrid w:linePitch="360"/></w:sectPr></w:body></w:document>'''
    
    # 创建临时目录
    with tempfile.TemporaryDirectory() as tmp_dir:
        # 创建基本目录结构
        word_dir = os.path.join(tmp_dir, "word")
        rels_dir = os.path.join(word_dir, "_rels")
        os.makedirs(rels_dir, exist_ok=True)
        
        # 保存 document.xml
        xml_path = os.path.join(word_dir, "document.xml")
        with open(xml_path, "w", encoding="utf-8") as f:
            f.write(correct_xml)
        
        # 创建简单的 _rels 文件
        rels_content = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
</Relationships>'''
        
        rels_path = os.path.join(rels_dir, "document.xml.rels")
        with open(rels_path, "w", encoding="utf-8") as f:
            f.write(rels_content)
        
        # 创建简单的 styles.xml
        styles_content = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
<docDefaults><rPrDefault><rPr><rFonts ascii="Times New Roman" eastAsia="宋体" hAnsi="Times New Roman"/><sz w:val="24"/></rPr></rPrDefault></docDefaults>
<latentStyles count="267" defLockedState="0" defUIPriority="99" defSemiHidden="0" defUnhideWhenUsed="0" defQFormat="0">
<lsdException locked="0" name="Normal" priority="0" qFormat="1"/>
<lsdException locked="0" name="Heading1" priority="9" qFormat="1"/>
<lsdException locked="0" name="Title" priority="10" qFormat="1"/>
</latentStyles>
</styleSheet>'''
        
        styles_path = os.path.join(word_dir, "styles.xml")
        with open(styles_path, "w", encoding="utf-8") as f:
            f.write(styles_content)
        
        # 创建 [Content_Types].xml
        content_types = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>
</Types>'''
        
        content_types_path = os.path.join(tmp_dir, "[Content_Types].xml")
        with open(content_types_path, "w", encoding="utf-8") as f:
            f.write(content_types)
        
        # 打包为 docx
        output_path = "template_fixed.docx"
        with zipfile.ZipFile(output_path, "w") as zipf:
            for root, dirs, files in os.walk(tmp_dir):
                for file in files:
                    file_path = os.path.join(root, file)
                    arcname = os.path.relpath(file_path, tmp_dir)
                    zipf.write(file_path, arcname)
        
        print(f"✅ 已创建正确的模板: {output_path}")
        return output_path
def render_calendar_docx(template_path, json_str):
    try:
        st.info(f"正在渲染模板: {template_path}")
        
        # 1) 提取最外层 JSON
=======
def render_calendar_docx(template_path, json_str):
    try:
        # 1. 深度清洗：只提取最外层 {} 之间的内容，排除所有 Markdown 说明
>>>>>>> parent of e07a703 (d)
        match = re.search(r'\{.*\}', json_str, re.DOTALL)
        if not match:
            return "ERROR: AI 生成的数据格式不正确，未发现 JSON 对象。"
        
        # 2. 移除 JSON 字符串中可能破坏 XML 的非法控制字符
        clean_json = match.group(0)
        clean_json = "".join(ch for ch in clean_json if ord(ch) >= 32 or ch in "\n\r\t")
        
        data = json.loads(clean_json)
        data = clean_none(data)
        # 3. 容错处理：确保进度表列表存在
        if "schedule" not in data or not isinstance(data["schedule"], list):
            data["schedule"] = []
            
<<<<<<< HEAD
        # 显示数据预览
        with st.expander("🔍 查看渲染数据"):
            st.json(data)
            st.write(f"schedule 列表长度: {len(data.get('schedule', []))}")

        # 检查模板路径
        if isinstance(template_path, str):
            if not os.path.exists(template_path):
                st.error(f"模板文件不存在: {template_path}")
                return None
        else:
            # template_path 可能是文件流
            pass

        doc = DocxTemplate(template_path)
        doc.render(data, autoescape=True)

        buf = io.BytesIO()
        doc.save(buf)
        out = buf.getvalue()

        # docx 必须是 zip，开头一般是 PK
        if not out.startswith(b"PK"):
            st.error("渲染输出不是合法 docx（zip 头不是 PK）")
            # 保存错误文件供调试
            with open("error_output.bin", "wb") as f:
                f.write(out)
            return None

        st.success("✅ 模板渲染成功！")
        return out

    except json.JSONDecodeError as e:
        st.error(f"JSON 解析错误: {str(e)}")
        st.error(f"JSON 内容: {json_str[:500]}...")
        return None
    except Exception as e:
        st.error("模板渲染失败，请看下面的报错信息：")
        st.exception(e)
        
        # 尝试保存模板供调试
        try:
            if isinstance(template_path, str):
                with open("debug_template.docx", "wb") as f:
                    with open(template_path, "rb") as src:
                        f.write(src.read())
            st.info("模板已保存为 debug_template.docx 供调试")
        except:
            pass
            
        return None


=======
        # 4. 执行渲染
        doc = DocxTemplate(template_path)
        # 允许不规范字符填充
        doc.render(data, autoescape=True) 
        
        target_stream = io.BytesIO()
        doc.save(target_stream)
        return target_stream.getvalue()
    except json.JSONDecodeError as e:
        return f"ERROR: JSON 数据解析失败，请检查调试面板。错误详情: {str(e)}"
    except Exception as e:
        return f"ERROR: 模板填充崩溃。这通常是因为 Word 模板内部标签被拆分。错误详情: {str(e)}"
# ==================== 2. 教学日历模块页面 ====================
>>>>>>> parent of e07a703 (d)




def page_calendar():
    nav_bar(show_back=True)
    st.subheader("📅 智能填充教学日历 (基于 docxtpl 模版技术)")
    
    # --- 1. 基础参数与状态同步 ---
    col_u1, col_u2, col_u3 = st.columns(3)
    name = col_u1.text_input("课程名称", value=st.session_state.get('course_name', "数值模拟在材料成型中的应用"))
    
    try:
        default_hours = int(st.session_state.get('total_hours', 24))
    except:
        default_hours = 24
        
    total_hours = col_u2.number_input("总学时", value=default_hours)
    total_weeks = col_u3.number_input("总周数", value=12)  
    
    # --- 2. 模版选择 ---
    st.divider()
    t_col1, t_col2 = st.columns([1, 2])
    
    with t_col1:
        template_choice = st.selectbox(
            "选择要填充的模版", 
            ["使用修复后的模板", "辽宁石油化工大学模版", "通用模版", "上传自定义模版"],
            key="template_choice"
        )
    
    # 确定物理模版路径
    current_template_path = ""
    
    if template_choice == "上传自定义模版":
        custom_file = st.file_uploader("上传您的 .docx 模版", type=["docx"], key="custom_uploader")
        if custom_file:
            # 保存为临时文件
            with tempfile.NamedTemporaryFile(delete=False, suffix=".docx") as tmp:
                tmp.write(custom_file.getvalue())
                current_template_path = tmp.name
    elif template_choice == "通用模版":
        if os.path.exists("template_general.docx"):
            current_template_path = "template_general.docx"
        else:
            st.warning("template_general.docx 不存在，将使用修复后的模板")
            current_template_path = "template_fixed.docx"
    elif template_choice == "辽宁石油化工大学模版":
        if os.path.exists("template_lnpu.docx"):
            current_template_path = "template_lnpu.docx"
        else:
            st.warning("template_lnpu.docx 不存在，将使用修复后的模板")
            current_template_path = "template_fixed.docx"
    else:  # "使用修复后的模板"
        # 确保修复后的模板存在
        if not os.path.exists("template_fixed.docx"):
            create_fixed_template_from_xml()
        current_template_path = "template_fixed.docx"
    
    # --- 3. 数据来源关联 ---
    st.markdown("##### 📚 数据提取来源")
    col_u4, col_u5 = st.columns(2)
    syllabus_file = col_u4.file_uploader("上传教学大纲 (可选)", type=['pdf', 'docx'], key="syllabus_uploader")
    
    if st.button("🚀 提取大纲数据并填充模版", key="generate_data_btn"):
        if not current_template_path or not os.path.exists(current_template_path):
            st.error("请先指定有效的模版文件")
            return

        with st.spinner("AI 正在解析大纲并构建填充数据集..."):
            # 获取上下文资料
            syl_ctx = ""
            if syllabus_file:
                syl_ctx = safe_extract_text(syllabus_file)
            elif st.session_state.get("gen_content", {}).get("syllabus"):
                syl_ctx = st.session_state.gen_content["syllabus"]
            else:
                syl_ctx = "未提供具体大纲，请按常识生成标准数据。"

            # 关键：要求 AI 输出 JSON 字典
            final_prompt = f"""
            你是一个教学数据处理专家。请阅读【教学大纲】，将其内容转化为一个 JSON 字典。
            这个字典的键名（Key）必须严格匹配以下【模版标签】。

            **必须提取并填充的标签清单：**
            - course_name (填充 {name}), english_name, course_code
            - total_hours (必须为 {total_hours}), credits, semester
            - schedule: 这是一个列表，包含每一课次的: week_num, session_num, teaching_content, learning_focus, hours, teaching_method, objective
            
            **结构要求：**
            - 进度表必须是一个名为 "schedule" 的数组。
            - 数组中的每个对象必须包含键：week_num, session_num, teaching_content, learning_focus, hours, teaching_method, objective。

            **约束条件：**
            1. 只输出纯 JSON 字符串，不要任何多余描述。
            2. 确保 JSON 结构合法，不要截断。
            3. 参考大纲内容：{syl_ctx[:8000]}
            
            **示例格式：**
            {{
              "course_name": "{name}",
              "english_name": "Numerical Simulation in Material Forming",
              "course_code": "ME401",
              "total_hours": {total_hours},
              "credits": 2.0,
              "semester": "第7学期",
              "schedule": [
                {{
                  "week_num": "1",
                  "session_num": "1",
                  "teaching_content": "课程介绍与数值模拟概述",
                  "learning_focus": "了解课程目标与数值模拟基本概念",
                  "hours": "2",
                  "teaching_method": "讲授+讨论",
                  "objective": "课程目标1"
                }}
              ]
            }}
            """
            
            # 调用 AI 引擎提取 JSON
            json_res = ai_generate(final_prompt, engine_id, selected_model)
            
            # 将生成的 JSON 和模版路径存入缓存
            st.session_state.generated_json_data = json_res
            st.session_state.active_template_path = current_template_path
            
            st.success("✅ 数据提取完成！")

    # --- 4. 预览与下载 ---
    if st.session_state.get("generated_json_data"):
        with st.expander("🔍 查看 AI 提取的填充数据（JSON 格式）", expanded=True):
            st.code(st.session_state.generated_json_data, language="json")
        
<<<<<<< HEAD
        # 执行填充
        with st.spinner("正在渲染模板..."):
            filled_docx = render_calendar_docx(
                st.session_state.active_template_path, 
                st.session_state.generated_json_data
            )
=======
        # 执行填充并提供下载
        filled_docx = render_calendar_docx(
            st.session_state.active_template_path, 
            st.session_state.generated_json_data
        )
>>>>>>> parent of e07a703 (d)
        
        if filled_docx:
            # 确保文件名安全
            safe_name = "".join(c for c in name if c.isalnum() or c in (' ', '-', '_')).rstrip()
            file_name = f"{safe_name}_教学日历.docx" if safe_name else "教学日历.docx"
            
            st.download_button(
                label="💾 点击下载已自动填充的模版文件 (.docx)",
                data=filled_docx,
                file_name=file_name,
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                key="download_filled_docx"  # 唯一 key
            )
<<<<<<< HEAD
        else:
            st.error("模板渲染失败，请检查数据和模板格式。")



=======
>>>>>>> parent of e07a703 (d)
        
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
route = {
    "首页": page_home, "大纲": page_syllabus, "日历": page_calendar, 
    "方案": page_program, "批卷": page_grading, "分析": page_analysis
}
current = st.query_params.get("page", "首页")
route.get(current, page_home)()