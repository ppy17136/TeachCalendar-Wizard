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
from PIL import Image
import google.generativeai as genai
import json
from docxtpl import DocxTemplate  # 必须安装 docxtpl
from datetime import datetime
# 签名插入示例
from docxtpl import InlineImage
from docx.shared import Mm, Pt
import pandas as pd  # 必须添加，用于数据类型清洗
# --- New Imports for Agent Architecture ---
from file_utils import extract_text_from_file, safe_extract_text
from docx_renderer import create_rich_docx
from llm_wrapper import ai_generate, ai_ocr
from agent_core import AgentCore


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
BACKEND_QWENM_KEY = st.secrets.get("QWENM_API_KEY", "")
BACKEND_QWEN_KEY = st.secrets.get("QWEN_API_KEY", "")
BACKEND_GEMINI_KEY = st.secrets.get("GEMINI_API_KEY", "")
BACKEND_GLM_KEY = st.secrets.get("GLM_API_KEY", "")
BACKEND_BAIDU_KEY = st.secrets.get("BAIDU_API_KEY", "")
BACKEND_KIMI_KEY = st.secrets.get("KIMI_API_KEY", "")

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
    providers = ["Qwen (摩搭)", "Qwen (通义千问)", "Baidu (文心一言)", "Kimi (Moonshot)", "GLM (智谱)", "Gemini"]
    # 默认选择 Gemini (索引为 3) 
    selected_provider = st.radio("选择主 AI 引擎", providers, index=5)
    ACTIVE_QWENM_KEY = BACKEND_QWENM_KEY
    ACTIVE_QWEN_KEY = BACKEND_QWEN_KEY
    ACTIVE_GEMINI_KEY = BACKEND_GEMINI_KEY
    ACTIVE_BAIDU_KEY = BACKEND_BAIDU_KEY
    ACTIVE_KIMI_KEY = BACKEND_KIMI_KEY
    ACTIVE_GLM_KEY = BACKEND_GLM_KEY
      
            
    if selected_provider == "Gemini":
        user_gem_key = st.text_input("填写 Gemini API Key (可选)", type="password", help="留空则使用后台默认 Key")
        if user_gem_key: ACTIVE_GEMINI_KEY = user_gem_key
        selected_model = st.selectbox("版本", ["gemini-2.5-flash", "gemini-2.0-flash-exp", "gemini-2.5-pro", "自定义..."])
        if selected_model == "自定义...":
            selected_model = st.text_input("Model（自定义输入）", value="gemini-2.5-pro")          
        engine_id = "Gemini"
        if ACTIVE_GEMINI_KEY: genai.configure(api_key=ACTIVE_GEMINI_KEY)
        if not ACTIVE_GEMINI_KEY: st.error("⚠️ 未检测到有效Gemini Key") 

        
    elif selected_provider == "Qwen (摩搭)":
        user_qw_key = st.text_input("填写 Qwen API Key (可选)", type="password", help="留空则使用后台默认 Key")
        if user_qw_key: ACTIVE_QWENM_KEY = user_qw_key
        selected_model = st.selectbox("版本", ["Qwen/Qwen3-VL-8B-Instruct", "Qwen/Qwen3-VL-30B-A3B-Instruct", "Qwen/Qwen3-VL-235B-A22B-Instruct",  "Qwen/Qwen2.5-VL-7B-Instruct", "自定义..."])
        if selected_model == "自定义...":
            selected_model = st.text_input("Model（自定义输入）", value="Qwen/Qwen3-VL-8B-Instruct")         
        engine_id = "QwenM"
        if not ACTIVE_QWENM_KEY: st.error("⚠️ 未检测到有效通义千问 Key")    

    elif selected_provider == "Qwen (通义千问)":
        user_qw_key = st.text_input("填写 Qwen API Key (可选)", type="password", help="留空则使用后台默认 Key")
        if user_qw_key: ACTIVE_QWEN_KEY = user_qw_key
        selected_model = st.selectbox("版本", ["qwen-plus", "qwen-max", "qwen-turbo", "自定义..."])
        if selected_model == "自定义...":
            selected_model = st.text_input("Model（自定义输入）", value="qwen-max")         
        engine_id = "Qwen"
        if not ACTIVE_QWEN_KEY: st.error("⚠️ 未检测到有效通义千问 Key")  

    elif selected_provider == "Baidu (文心一言)":
        user_bd_key = st.text_input("填写百度千帆 API Key (可选)", type="password", help="留空则使用后台默认 Key")
        if user_bd_key: ACTIVE_BAIDU_KEY = user_bd_key
        # 百度常用的 OpenAI 兼容模型名
        selected_model = st.selectbox("版本", ["ERNIE-4.5-Turbo-Latest", "ERNIE-4.5-Turbo-128K", "ERNIE-4.5-Turbo-32K", "ERNIE-4.5-Turbo", "ERNIE-4.5-Turbo-VL-Latest", "ERNIE-4.5-Turbo-VL-32K", "ERNIE-4.5-Turbo-VL", "ERNIE-5.0-Thinking-Latest", "自定义..."])
        if selected_model == "自定义...":
            selected_model = st.text_input("Model（自定义输入）", value="ERNIE-5.0-Thinking-Preview")         
        engine_id = "Baidu"
        if not ACTIVE_BAIDU_KEY: st.error("⚠️ 未检测到有效百度 Key")

    elif selected_provider == "Kimi (Moonshot)":
        user_km_key = st.text_input("填写 Kimi API Key (可选)", type="password", help="留空则使用后台默认 Key")
        if user_km_key: ACTIVE_KIMI_KEY = user_km_key
        selected_model = st.selectbox("版本", ["moonshot-v1-8k", "moonshot-v1-32k", "moonshot-v1-128k", "kimi-k2-thinking", "kimi-k2-thinking-turbo", "kimi-latest", "自定义..."])
        if selected_model == "自定义...":
            selected_model = st.text_input("Model（自定义输入）", value="kimi-latest")        
        engine_id = "Kimi"
        if not ACTIVE_KIMI_KEY: st.error("⚠️ 未检测到有效 Kimi Key") 
        
    elif selected_provider == "GLM (智谱)":
        user_glm_key = st.text_input("填写 GLM API Key (可选)", type="password", help="留空则使用后台默认 Key")
        if user_glm_key: ACTIVE_GLM_KEY = user_glm_key
        # 智谱模型名可能会更新，这里给常用项 + 自定义
        selected_model = st.selectbox("版本", ["glm-4.5-flash", "glm-4.7", "glm-4.6", "glm-4.5-air", "glm-4.5-airx", "自定义..."])
        if selected_model == "自定义...":
            selected_model = st.text_input("Model（自定义输入）", value="glm-4.7")
        engine_id = "GLM"
        if not ACTIVE_GLM_KEY: st.error("⚠️ 未检测到有效 GLM Key")      
        
    st.divider()
    st.info(f"💡 当前模式：使用 **{engine_id}** 处理。")
    # 侧边栏底部也可以加提示
    st.caption("🖥️ 建议环境：Google Chrome 浏览器")
    
    st.divider()
    st.markdown("### 📖 官方资源")
    st.link_button("📺 官方教程", "https://telyon.click")
    st.link_button("💰 赞助支持", "https://telyon.click/donate")
    st.info("提示：教程站内有详细的 Prompt 编写指南。")



    st.divider()
    st.markdown("### ✉️ 联系我们")
    st.caption("BUG 反馈 / 合作意向：")
    st.code("839146331@qq.com", language=None) # 使用 st.code 方便用户一键点击复制


# --- 5. 文档与工具函数 ---
# (Functions extract_text_from_file, safe_extract_text, ai_generate, ai_ocr have been moved to modules)
# Still keeping render_pdf_images here as it uses fitz directly for UI rendering


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
        ("📝", "智能批卷系统", "批卷"), ("📈", "成绩分析报告", "分析"), ("📚", "使用教程与帮助", "教程")
    ]
    
    # 在循环中处理跳转
    for i, (icon, title, link) in enumerate(modules):
        with cols[i % 3]:
            st.markdown(f'<div style="border:1px solid #ddd;padding:20px;border-radius:10px;text-align:center;"><span style="font-size:40px;">{icon}</span><h4>{title}</h4></div>', unsafe_allow_html=True)
            
            if title == "使用教程与帮助":
                st.link_button("🚀 点击进入官方教程站", "https://telyon.click", use_container_width=True)
            else:
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
            # Prepare extraction
            book_ctx = safe_extract_text(book_file) if book_file else "未提供教材"
            plan_ctx = safe_extract_text(plan_file) if plan_file else "未提供培养方案"   
            
            # Prepare Agent Inputs
            inputs = {
                "course_name": name,
                "major": major,
                "course_type": course_type,
                "hours": hours,
                "credits": credits,
                "assessment": assessment,
                "semester": semester,
                "prerequisites": prerequisites,
                "objectives": obj,
                "ideology": ideology,
                "textbook_name": book_file.name if book_file else "未提供"
            }
            
            uploaded_texts = {
                "textbook": book_ctx,
                "plan": plan_ctx
            }
            
            # Collect Keys
            keys_config = {
                "Gemini": ACTIVE_GEMINI_KEY,
                "Qwen": ACTIVE_QWEN_KEY,
                "QwenM": ACTIVE_QWENM_KEY,
                "Baidu": ACTIVE_BAIDU_KEY,
                "Kimi": ACTIVE_KIMI_KEY,
                "GLM": ACTIVE_GLM_KEY
            }
            
            # Initialize Agent
            agent = AgentCore(keys_config, provider=engine_id, model_name=selected_model)
            
            # Run Agent Loop with UI Feedback
            with st.status("🤖 Agent 智能体深度思考中...", expanded=True) as status:
                final_res = "生成失败"
                try:
                    gen = agent.run_syllabus_generation(inputs, uploaded_texts)
                    for step in gen:
                        # Check if it's the final result payload
                        if isinstance(step, dict) and "final_result" in step:
                            final_res = step["final_result"]
                            continue
                        
                        # Handle normal string logs
                        step_log = str(step)
                        if step_log.startswith("✅"):
                            status.update(label="✅ 大纲生成完成", state="complete", expanded=False)
                        else:
                            st.write(step_log)
                except Exception as e:

                    st.error(f"Agent 运行出错: {str(e)}")
                    status.update(label="❌ 生成失败", state="error")
            
            # Store Result
            st.session_state.gen_content["syllabus"] = final_res
            st.session_state['course_name'] = name
            st.session_state['total_hours'] = hours
            st.session_state['major'] = major # 适用专业
            st.session_state['course_objectives'] = obj # 存储原始输入的课程目标文本
            st.session_state['ideology_points'] = ideology # 存储思政点

            st.success("✅ 大纲生成成功！")

    if st.session_state.gen_content["syllabus"]:
        st.markdown("---")
        st.container(border=True).markdown(st.session_state.gen_content["syllabus"])
        col1, col2 = st.columns(2)
        col1.download_button("💾 下载 Word 版大纲", create_rich_docx(st.session_state.gen_content["syllabus"]), file_name=f"{name}_大纲.docx")
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
        #teacher_title = t2.text_input("职称", value=st.session_state.get('teacher_title', ""))
        teacher_title = t2.selectbox("职称", ["教授", "副教授", "讲师", "助教", "研究员", "副研究员", "助理研究员", "助理研究员", "高级实验师", "实验师", "助理实验师"])
        #academic_year = t3.text_input("学年 (如 2025-2026)", value="2025-2026")
        
        # 1. 使用 number_input 获取起始年份，设置 step=1 激活加减号
        start_year = t3.number_input("学年 (起始)", value=2025, step=1, help="点击 +/- 切换学年")

        # 2. 动态计算完整的学年字符串
        academic_year = f"{start_year}-{start_year + 1}"

        # 3. 在下方显示一个提示，让老师确认完整的学年范围
        t3.caption(f"当前选择：:blue[{academic_year}]")
        
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
                    "extra_hours": 课外学时(数字),
                    "major": 适用专业
                }},

                "schedule": [
                    {{ "week": 1, "sess": 1, "content": "章节内容", "req": "重点要求", "hrs": 数字, "method": "方法", "other": "作业", "obj": "目标", "source_text": "大纲原文片段" }}
                ]
            }}
            
            # 参考资料
            教学大纲内容：{syl_ctx[:10000]}
            """
            
            # Collect Keys for Calendar Split
            keys_config = {
                "Gemini": ACTIVE_GEMINI_KEY,
                "Qwen": ACTIVE_QWEN_KEY,
                "QwenM": ACTIVE_QWENM_KEY,
                "Baidu": ACTIVE_BAIDU_KEY,
                "Kimi": ACTIVE_KIMI_KEY,
                "GLM": ACTIVE_GLM_KEY
            }
            res = ai_generate(split_prompt, engine_id, selected_model, keys_config)
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
                st.session_state["major"] = bi.get("major", "")
                st.session_state["lecture_hours"] = bi.get("lecture_hours", "")
                st.session_state["lab_hours"] = bi.get("lab_hours", "")
                st.session_state["quiz_hours"] = bi.get("quiz_hours", "")
                st.session_state["extra_hours"] = bi.get("extra_hours", "")
                
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

def page_calendar():
    nav_bar(show_back=True)
    
    # 1. 创建两列，比例建议为 3:1 或 4:1，让标题占据更多空间
    col1, col2 = st.columns([4, 1])
    
    with col1:
        # 放置主标题
        st.subheader("📅 教学日历编报与多级审批")
    
    with col2:
        # 2. 放置选择框，并使用 label_visibility="collapsed" 隐藏标签，使其与标题对齐
        user_role = st.selectbox(
            "角色视图", 
            ["授课教师", "系主任", "主管院长"],
            label_visibility="collapsed",  # 隐藏标签，节省垂直空间
            index=0,
            key="role_selector" # 建议加上 key 保证状态稳定
        )
    
    st.divider() # 增加一条分割线，让头部布局更清晰
    
    # 后续业务逻辑可以使用 user_role 变量
    #st.info(f"当前正在以 【{user_role}】 视角查看系统")

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
                st.session_state.gen_content["program"] = ai_generate(prompt, engine_id, selected_model)

    if st.session_state.gen_content["program"]:
        st.markdown("---")
        st.container(border=True).markdown(st.session_state.gen_content["program"])
        st.download_button(
            "💾 下载 Word 版培养方案", 
            create_docx(st.session_state.gen_content["program"]), 
            file_name="培养方案.docx"
        )
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