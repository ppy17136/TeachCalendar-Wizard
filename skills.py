import re
import json
from llm_wrapper import ai_generate

class SyllabusSkills:
    def __init__(self, keys_config, model_name="gemini-1.5-pro"):
        self.keys_config = keys_config
        self.provider = "Gemini" if keys_config.get("Gemini") else "Qwen"  # Default provider strategy
        self.model_name = model_name

    def validate_obe_compliance(self, course_target_text):
        """
        Skill: 检查课程目标是否符合 OBE (Outcome Based Education) 标准。
        
        Args:
            course_target_text (str): 课程目标的描述文本。
            
        Returns:
            dict: {"is_compliant": bool, "suggestions": str}
        """
        prompt = f"""
        你是一位工程教育认证专家。请检查以下课程目标是否符合 OBE 理念（以学生为中心，成果导向，动词准确）。
        
        目标文本：
        {course_target_text}
        
        请严格检查动词使用（如“了解”、“掌握”在 OBE 中属于低阶，建议用“分析”、“设计”、“评价”等）。
        请以 JSON 格式返回：
        {{
            "is_compliant": true/false,
            "analysis": "简短分析",
            "revised_text": "如果如果不合规，请给出修改建议"
        }}
        """
        try:
            res = ai_generate(prompt, self.provider, self.model_name, self.keys_config)
            # Simple JSON extraction
            match = re.search(r'(\{.*\})', res, re.DOTALL)
            if match:
                return json.loads(match.group(1))
            return {"is_compliant": False, "analysis": "AI output parsing failed", "raw": res}
        except Exception as e:
            return {"is_compliant": False, "error": str(e)}

    def search_knowledge_base(self, query, text_corpus, top_k=3):
        """
        Skill: 在提供的文本库中搜索最相关的内容段落。
        解决 Token 限制问题，模拟 RAG。
        """
        if not text_corpus:
            return "知识库为空。"
            
        # 这里用简单的关键词匹配或把任务交给 LLM 做摘要
        # 为了更 Agentic，我们让 LLM 来决定这段文本里是否有答案
        # 但考虑到效率，我们先切片
        
        # 简单切片策略
        chunks = [text_corpus[i:i+2000] for i in range(0, len(text_corpus), 2000)]
        results = []
        
        prompt = f"""
        请阅读下面这段文本，判断是否包含问题的答案。
        问题：{query}
        
        若包含，请提取相关句子。若不包含，回答 NONE。
        
        文本片段：
        """
        
        # 实际应用中这一步会很慢，简化为：直接返回包含关键词的段落
        # 或者直接返回前 10000 字（Assume 传入的 corpus 已经是筛选过的）
        pass 
        # For this prototype, returns the first 5000 chars and let the LLM handle it, 
        # assuming the agent decided to "read" the file.
        return text_corpus[:5000] + "\n...(内容过长，仅显示前5000字)"

    def extract_graduation_matrix(self, file_path):
        """
        Specialized skill to extract 'Course vs Graduation Requirement' matrix from PDF.
        Returns a structured list of {requirement, point, strength}
        """
        import pdfplumber
        import os
        
        extracted_data = []
        
    def extract_graduation_matrix(self, file_path, course_name="数值模拟"):
        """
        Specialized skill to extract 'Course vs Graduation Requirement' matrix from PDF.
        Args:
            file_path: PDF path
            course_name: Name of the course to find in the matrix
        """
        import pdfplumber
        import os
        
        extracted_data = []
        debug_log = []
        
        target_row = None
        header_row = None
        
        try:
            with pdfplumber.open(file_path) as pdf:
                for i, page in enumerate(pdf.pages):
                    text = page.extract_text() or ""
                    
                    # 1. Try Table Extraction
                    tables = page.extract_tables()
                    for table in tables:
                        # Clean table data
                        clean_table = [[(c.strip() if c else "") for c in row] for row in table]
                        
                        # A. Search for Header Row (contains "毕业要求" or "指标点" or points like "1.1", "1.2")
                        # We assume header is one of the first few rows
                        for row_idx, row in enumerate(clean_table[:5]):
                            row_str = " ".join(row)
                            if "毕业要求" in row_str or "指标点" in row_str or "1.1" in row_str:
                                # Found potential header
                                if not header_row or len(row) > len(header_row):
                                    header_row = row
                                    debug_log.append(f"Found Header on Page {i+1}")
                        
                        # B. Search for Course Row
                        for row in clean_table:
                            # Fuzzy match course name in the first few columns
                            # usually course name is in col 0, 1, or 2
                            row_start = " ".join(row[:4])
                            # Simple fuzzy: check if key parts of name exist
                            # e.g. "数值" and "模拟"
                            name_keywords = [k for k in course_name if k.isalnum()]
                            # Allow partial match (e.g. if name is short)
                            if course_name in row_start:
                                target_row = row
                                debug_log.append(f"Found Course Row on Page {i+1}: {row}")
                                break
                        
                        if target_row and header_row:
                            break
                    
                    if target_row and header_row:
                        break

            if target_row and header_row:
                # Map headers to values
                mapped_data = []
                count = min(len(header_row), len(target_row))
                for c in range(count):
                    val = target_row[c]
                    head = header_row[c]
                    # Check for valid support value (H, M, L, or symbols)
                    # Some PDFs use checks or filled circles. We assume H/M/L/High/Low for now based on previous info
                    if val and val in ["H", "M", "L", "High", "Low", "●", "◎", "○", "√"]:
                        mapped_data.append({"req": "毕业要求", "point": head, "strength": val})
                
                if mapped_data:
                    return json.dumps(mapped_data, ensure_ascii=False)
                else:
                    return f"找到课程行，但未能提取到有效支撑值 (H/M/L). Headers: {header_row}, Row: {target_row}"

            # Fallback: If programmatic search failed, dump debug info
            return f"未能精确定位课程 '{course_name}' 的支撑数据。Debug: {'; '.join(debug_log)}"
            
        except Exception as e:
            return f"矩阵提取异常: {str(e)}"
            
        except Exception as e:
            return f"矩阵提取异常: {str(e)}"
    
    def generate_section(self, section_name, context_info):
        """
        Skill: 生成大纲的特定章节
        """
        prompt = f"""
        请为教学大纲撰写【{section_name}】部分。
        上下文信息：
        {json.dumps(context_info, ensure_ascii=False)}
        
        要求：语言学术，符合大学教学大纲规范。
        """
        return ai_generate(prompt, self.provider, self.model_name, self.keys_config)
