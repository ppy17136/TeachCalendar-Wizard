import json
import io
import re
from docxtpl import DocxTemplate
import streamlit as st
from docx import Document
from docx.shared import RGBColor, Pt
from docx.enum.text import WD_COLOR_INDEX
import zipfile
import xml.etree.ElementTree as ET

def page_calendar_template_maker():
    """
    将上传的Word文档转换为带标签的模板
    """
    st.subheader("🛠️ Word文档标签化工具")
    st.markdown("将您的Word文档转换为带`{{标签}}`的模板文件")
    
    # 创建两个选项卡
    tab1, tab2 = st.tabs(["📤 自动标签化", "✏️ 手动添加标签"])
    
    with tab1:
        st.markdown("### 自动标签化（智能识别）")
        st.info("系统将尝试识别文档中的特定内容并自动替换为标签")
        
        # 上传原始文档
        uploaded_file = st.file_uploader(
            "上传原始Word文档", 
            type=['docx'],
            help="请上传.docx格式的Word文档"
        )
        
        if uploaded_file:
            # 预览原始内容
            if st.checkbox("预览原始文档内容"):
                try:
                    doc = Document(io.BytesIO(uploaded_file.read()))
                    uploaded_file.seek(0)  # 重置文件指针
                    
                    preview_text = []
                    for i, para in enumerate(doc.paragraphs[:20]):  # 限制预览前20段
                        if para.text.strip():
                            preview_text.append(f"第{i+1}段: {para.text}")
                    
                    if preview_text:
                        st.text_area("文档内容预览", "\n".join(preview_text), height=200)
                    else:
                        st.warning("文档内容为空或无法读取")
                except Exception as e:
                    st.error(f"读取文档失败: {e}")
            
            # 自动标签化选项
            col1, col2 = st.columns(2)
            with col1:
                auto_tags = st.multiselect(
                    "选择要自动替换的内容类型",
                    ["课程名称", "学时数", "周数", "教师姓名", "教材信息", "考核方式", "日期"],
                    default=["课程名称", "学时数", "周数"]
                )
            
            with col2:
                highlight_color = st.selectbox(
                    "标签高亮颜色",
                    ["黄色", "绿色", "蓝色", "粉色", "灰色"],
                    index=0
                )
            
            # 转换按钮
            if st.button("🔄 开始自动标签化", type="primary"):
                with st.spinner("正在处理文档..."):
                    try:
                        # 读取上传的文件
                        uploaded_file.seek(0)
                        doc_bytes = uploaded_file.read()
                        
                        # 进行自动标签化
                        processed_doc, tag_count = auto_tag_document(
                            doc_bytes, 
                            auto_tags,
                            highlight_color
                        )
                        
                        # 保存到session_state
                        st.session_state.tagged_template = processed_doc
                        
                        # 显示统计信息
                        st.success(f"✅ 标签化完成！共添加/替换了 {tag_count} 个标签")
                        
                        # 预览部分标签
                        if st.checkbox("预览生成的标签"):
                            preview_tags(processed_doc)
                        
                        # 提供下载
                        st.download_button(
                            label="📥 下载标签化模板",
                            data=processed_doc,
                            file_name="标签化模板_教学日历.docx",
                            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                        )
                        
                    except Exception as e:
                        st.error(f"处理失败: {str(e)}")
                        st.code(traceback.format_exc())
    
    with tab2:
            st.markdown("### 手动添加/编辑标签")
            st.info("手动指定文档中需要替换为标签的文本")
            
            if uploaded_file:
                # 修复：包裹 try 块
                try:
                    # 读取文档内容供手动编辑
                    uploaded_file.seek(0)
                    doc = Document(io.BytesIO(uploaded_file.read()))
                    uploaded_file.seek(0)
                    
                    # 提取所有段落
                    paragraphs = []
                    for i, para in enumerate(doc.paragraphs):
                        if para.text.strip():
                            paragraphs.append({
                                "id": i,
                                "text": para.text,
                                "tag": ""
                            })
                    
                    # 手动编辑界面
                    st.markdown("#### 手动编辑标签")
                    
                    # 显示前50段供编辑
                    for i, para in enumerate(paragraphs[:50]):
                        cols = st.columns([3, 1])
                        with cols[0]:
                            st.text_input(
                                f"段落 {i+1}",
                                value=para["text"],
                                key=f"para_text_{i}",
                                disabled=True
                            )
                        with cols[1]:
                            tag_input = st.text_input(
                                "标签名",
                                value=para.get("tag", ""),
                                key=f"para_tag_{i}",
                                placeholder="如: course_name"
                            )
                            if tag_input:
                                paragraphs[i]["tag"] = tag_input

                    # --- 批量添加标签 ---
                    st.markdown("---")
                    st.markdown("#### 批量添加标签")
                    
                    col_a, col_b, col_c = st.columns(3)
                    with col_a:
                        search_text = st.text_input("搜索文本")
                    with col_b:
                        replace_tag = st.text_input("替换为标签")
                    with col_c:
                        if st.button("批量替换", type="secondary"):
                            if search_text and replace_tag:
                                for para in paragraphs:
                                    if search_text in para["text"]:
                                        para["tag"] = replace_tag
                                st.rerun()
                    
                    # --- 生成模板 ---
                    if st.button("🛠️ 生成手动标签化模板", type="primary"):
                        try:
                            uploaded_file.seek(0)
                            doc_bytes = uploaded_file.read()
                            processed_doc = manual_tag_document(doc_bytes, paragraphs)
                            st.session_state.tagged_template = processed_doc
                            st.success("✅ 手动标签化完成！")
                            st.download_button(
                                label="📥 下载手动标签化模板",
                                data=processed_doc,
                                file_name="手动标签化_教学日历.docx",
                                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                            )
                        except Exception as e:
                            st.error(f"处理失败: {str(e)}")

                # --- 新增这个 except 块来修复错误 ---
                except Exception as e:
                    st.error(f"读取文档失败: {e}")
    
    # 模板示例部分
    st.markdown("---")
    with st.expander("📚 标签使用示例"):
        st.markdown("""
        ### 常用标签示例
        
        | 标签 | 说明 | 示例 |
        |------|------|------|
        | `{{course_name}}` | 课程名称 | `{{course_name}}` |
        | `{{english_name}}` | 英文课程名 | `{{english_name}}` |
        | `{{total_hours}}` | 总学时 | `{{total_hours}}` |
        | `{{total_weeks}}` | 总周数 | `{{total_weeks}}` |
        | `{{teacher}}` | 教师姓名 | `{{teacher}}` |
        | `{{textbook}}` | 教材信息 | `{{textbook}}` |
        | `{{assessment}}` | 考核方式 | `{{assessment}}` |
        | `{{semester}}` | 学期 | `{{semester}}` |
        
        ### 表格循环标签示例
        
        对于教学日历表格，使用循环标签：
        ```python
        {% for week in calendar_table %}
        <tr>
            <td>{{ week.week_num }}</td>
            <td>{{ week.content }}</td>
            <td>{{ week.hours }}</td>
            <td>{{ week.method }}</td>
        </tr>
        {% endfor %}
        ```
        
        ### 条件标签示例
        
        ```python
        {% if is_required %}
        必修课
        {% else %}
        选修课
        {% endif %}
        ```
        """)
        
        # 提供空白模板下载
        st.markdown("### 下载空白模板")
        blank_template = create_blank_template()
        st.download_button(
            label="📄 下载空白标签模板",
            data=blank_template,
            file_name="教学日历_空白模板.docx",
            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        )

def auto_tag_document(doc_bytes, tag_types, highlight_color):
    """
    自动将文档中的特定内容替换为标签
    """
    # 颜色映射
    color_map = {
        "黄色": WD_COLOR_INDEX.YELLOW,
        "绿色": WD_COLOR_INDEX.GREEN,
        "蓝色": WD_COLOR_INDEX.BLUE,
        "粉色": WD_COLOR_INDEX.PINK,
        "灰色": WD_COLOR_INDEX.GRAY_25
    }
    
    # 读取文档
    doc = Document(io.BytesIO(doc_bytes))
    
    # 常见的替换模式
    patterns = {
        "课程名称": [
            r"课程名称[：:]\s*([^\n]+)",
            r"《([^》]+)》课程",
            r"课程[：:]\s*([^\n]+)"
        ],
        "学时数": [
            r"(\d+)\s*学时",
            r"总学时[：:]\s*(\d+)",
            r"(\d+)\s*小时"
        ],
        "周数": [
            r"(\d+)\s*周",
            r"总周数[：:]\s*(\d+)",
            r"教学周数[：:]\s*(\d+)"
        ],
        "教师姓名": [
            r"教师[：:]\s*([^\n]+)",
            r"主讲教师[：:]\s*([^\n]+)",
            r"任课教师[：:]\s*([^\n]+)"
        ],
        "教材信息": [
            r"教材[：:]\s*([^\n]+)",
            r"参考书目[：:]\s*([^\n]+)",
            r"使用教材[：:]\s*([^\n]+)"
        ],
        "考核方式": [
            r"考核方式[：:]\s*([^\n]+)",
            r"成绩评定[：:]\s*([^\n]+)",
            r"考试方式[：:]\s*([^\n]+)"
        ],
        "日期": [
            r"\d{4}年\d{1,2}月\d{1,2}日",
            r"\d{4}-\d{1,2}-\d{1,2}",
            r"\d{4}/\d{1,2}/\d{1,2}"
        ]
    }
    
    tag_count = 0
    
    # 处理段落
    for para in doc.paragraphs:
        original_text = para.text
        if not original_text.strip():
            continue
            
        modified_text = original_text
        
        # 对每个选中的标签类型进行处理
        for tag_type in tag_types:
            if tag_type in patterns:
                for pattern in patterns[tag_type]:
                    # 查找匹配
                    matches = list(re.finditer(pattern, original_text, re.IGNORECASE))
                    matches.reverse()  # 从后往前替换，避免位置偏移
                    
                    for match in matches:
                        # 获取匹配的文本
                        matched_text = match.group(0)
                        
                        # 生成标签
                        tag_name = generate_tag_name(tag_type, matched_text)
                        
                        # 替换文本
                        start = match.start()
                        end = match.end()
                        modified_text = modified_text[:start] + f"{{{{{tag_name}}}}}" + modified_text[end:]
                        
                        tag_count += 1
        
        # 如果文本被修改，更新段落
        if modified_text != original_text:
            para.clear()
            run = para.add_run(modified_text)
            
            # 高亮显示
            if highlight_color in color_map:
                run.font.highlight_color = color_map[highlight_color]
    
    # 处理表格
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                for para in cell.paragraphs:
                    original_text = para.text
                    if not original_text.strip():
                        continue
                    
                    modified_text = original_text
                    
                    # 对每个选中的标签类型进行处理
                    for tag_type in tag_types:
                        if tag_type in patterns:
                            for pattern in patterns[tag_type]:
                                matches = list(re.finditer(pattern, original_text, re.IGNORECASE))
                                matches.reverse()
                                
                                for match in matches:
                                    matched_text = match.group(0)
                                    tag_name = generate_tag_name(tag_type, matched_text)
                                    
                                    start = match.start()
                                    end = match.end()
                                    modified_text = modified_text[:start] + f"{{{{{tag_name}}}}}" + modified_text[end:]
                                    
                                    tag_count += 1
                    
                    if modified_text != original_text:
                        para.clear()
                        run = para.add_run(modified_text)
                        if highlight_color in color_map:
                            run.font.highlight_color = color_map[highlight_color]
    
    # 保存到内存
    output = io.BytesIO()
    doc.save(output)
    output.seek(0)
    
    return output.getvalue(), tag_count

def manual_tag_document(doc_bytes, paragraphs):
    """
    应用手动定义的标签
    """
    # 读取文档
    doc = Document(io.BytesIO(doc_bytes))
    
    # 创建段落映射
    para_map = {}
    for i, para in enumerate(doc.paragraphs):
        if para.text.strip():
            para_map[i] = para
    
    # 应用标签
    for para_info in paragraphs:
        para_id = para_info["id"]
        tag = para_info.get("tag", "").strip()
        
        if tag and para_id in para_map:
            para = para_map[para_id]
            original_text = para.text
            
            # 如果原文本包含可能被替换的内容，进行替换
            # 这里简化处理：如果用户指定了标签，就用标签替换整个段落
            # 实际应用中可能需要更精细的替换逻辑
            
            # 检查文本是否看起来像需要替换的内容
            if (len(original_text) < 100 and  # 不是大段文本
                not original_text.startswith((' ', '\t')) and  # 不是缩进段落
                tag not in original_text):  # 标签还不存在
                
                para.clear()
                run = para.add_run(f"{{{{{tag}}}}}")
                run.font.highlight_color = WD_COLOR_INDEX.YELLOW
    
    # 保存到内存
    output = io.BytesIO()
    doc.save(output)
    output.seek(0)
    
    return output.getvalue()

def generate_tag_name(tag_type, text):
    """
    根据标签类型和文本生成标签名
    """
    # 基础映射
    base_names = {
        "课程名称": "course_name",
        "学时数": "total_hours",
        "周数": "total_weeks",
        "教师姓名": "teacher_name",
        "教材信息": "textbook_info",
        "考核方式": "assessment_method",
        "日期": "course_date"
    }
    
    if tag_type in base_names:
        base_name = base_names[tag_type]
    else:
        # 从文本生成简化的标签名
        base_name = re.sub(r'[^\w]', '_', tag_type.lower())
    
    return base_name

def preview_tags(doc_bytes):
    """
    预览文档中的标签
    """
    try:
        doc = Document(io.BytesIO(doc_bytes))
        
        tags_found = []
        for para in doc.paragraphs:
            text = para.text
            # 查找所有 {{...}} 模式的标签
            matches = re.findall(r'\{\{([^}]+)\}\}', text)
            if matches:
                tags_found.extend(matches)
        
        # 检查表格
        for table in doc.tables:
            for row in table.rows:
                for cell in row.cells:
                    for para in cell.paragraphs:
                        text = para.text
                        matches = re.findall(r'\{\{([^}]+)\}\}', text)
                        if matches:
                            tags_found.extend(matches)
        
        if tags_found:
            st.markdown("### 检测到的标签")
            # 去重并排序
            unique_tags = sorted(set(tags_found))
            
            col1, col2 = st.columns(2)
            with col1:
                st.markdown("**标签列表:**")
                for tag in unique_tags:
                    st.code(f"{{{{{tag}}}}}", language=None)
            
            with col2:
                st.markdown("**统计信息:**")
                st.write(f"总标签数: {len(tags_found)}")
                st.write(f"唯一标签数: {len(unique_tags)}")
                
                # 标签类型统计
                tag_types = {}
                for tag in unique_tags:
                    if '_' in tag:
                        prefix = tag.split('_')[0]
                    else:
                        prefix = tag
                    tag_types[prefix] = tag_types.get(prefix, 0) + 1
                
                st.markdown("**标签类型分布:**")
                for prefix, count in tag_types.items():
                    st.write(f"- {prefix}: {count}个")
        else:
            st.warning("未检测到任何标签。请确保标签格式为 {{标签名}}")
            
    except Exception as e:
        st.error(f"预览失败: {e}")

def create_blank_template():
    """
    创建一个带示例标签的空白模板
    """
    doc = Document()
    
    # 标题
    title = doc.add_heading('教学日历', 0)
    title_run = title.runs[0]
    title_run.font.size = Pt(22)
    
    # 基本信息
    doc.add_heading('一、课程基本信息', level=1)
    
    # 基本信息表格
    table = doc.add_table(rows=6, cols=2)
    table.style = 'Table Grid'
    
    # 表头
    cells = table.rows[0].cells
    cells[0].text = '项目'
    cells[1].text = '内容'
    
    # 数据行
    data_rows = [
        ('课程名称', '{{course_name}}'),
        ('英文名称', '{{english_name}}'),
        ('课程编码', '{{course_code}}'),
        ('总学时', '{{total_hours}}'),
        ('学分数', '{{credits}}'),
        ('开课学期', '{{semester}}')
    ]
    
    for i, (item, value) in enumerate(data_rows, 1):
        cells = table.rows[i].cells
        cells[0].text = item
        cells[1].text = value
    
    # 教学日历表格
    doc.add_heading('二、教学日历', level=1)
    
    calendar_table = doc.add_table(rows=2, cols=7)
    calendar_table.style = 'Table Grid'
    
    # 表头
    headers = ['周次', '课次', '教学内容', '学习重点', '学时', '教学方法', '支撑目标']
    header_cells = calendar_table.rows[0].cells
    for i, header in enumerate(headers):
        header_cells[i].text = header
    
    # 示例数据行（使用循环标签）
    data_cells = calendar_table.rows[1].cells
    data_cells[0].text = '{{ week_num }}'
    data_cells[1].text = '{{ session_num }}'
    data_cells[2].text = '{{ teaching_content }}'
    data_cells[3].text = '{{ learning_focus }}'
    data_cells[4].text = '{{ hours }}'
    data_cells[5].text = '{{ teaching_method }}'
    data_cells[6].text = '{{ objective }}'
    
    # 说明文字
    doc.add_paragraph('\n说明：')
    doc.add_paragraph('1. 表格中的 {{标签}} 将在填充时被替换为实际内容')
    doc.add_paragraph('2. 如需多行数据，请在Word中复制表格行')
    doc.add_paragraph('3. 标签命名建议使用英文和下划线，如：{{teacher_name}}')
    
    # 保存到内存
    output = io.BytesIO()
    doc.save(output)
    output.seek(0)
    
    return output.getvalue()

# 添加跟踪backtrace
import traceback

# 在Streamlit应用中调用
if __name__ == "__main__":
    st.set_page_config(page_title="Word文档标签化工具", layout="wide")
    page_calendar_template_maker()