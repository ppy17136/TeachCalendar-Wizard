import streamlit as st
import json
import time
from llm_wrapper import ai_generate
from skills import SyllabusSkills

class AgentCore:
    def __init__(self, keys_config, provider="Gemini", model_name="gemini-1.5-pro"):
        self.keys_config = keys_config
        self.provider = provider
        self.model_name = model_name
        self.skills = SyllabusSkills(keys_config, model_name)
        self.history = []
        
    def log(self, message):
        """Output to Streamlit UI or Console"""
        if "agent_logs" not in st.session_state:
            st.session_state.agent_logs = []
        st.session_state.agent_logs.append(message)
        # Using st.write directly might break if not in correct context, usually handled by caller
        
    def run_syllabus_generation(self, user_inputs, uploaded_texts):
        """
        Orchestrates the syllabus generation process (thinking + tool execution)
        Outputs: Structed JSON for rendering
        """
        yield "🤖 Agent 启动: 正在初始化大纲生成任务..."
        
        # 1. Check for Training Plan PDF to extract Matrix
        graduation_matrix_context = "未提供培养方案，需根据通用标准推导。"
        if "plan_file_path" in user_inputs and user_inputs["plan_file_path"]:
             yield "🔍 正在深入解析培养方案PDF (寻找毕业要求支撑矩阵)..."
             matrix_data = self.skills.extract_graduation_matrix(user_inputs["plan_file_path"])
             graduation_matrix_context = f"从PDF提取的支撑矩阵数据（请严格据此生成）：\n{matrix_data[:3000]}" # Limit size
        
        # 2. Construct the "System 2" Prompt (JSON Schema Enforcement)
        system_prompt = f"""
        # 角色
        你是一位工程教育认证（OBE）专家。请根据提供的课程信息和参考资料，生成一份标准的教学大纲。
        
        # 核心指令
        **必须输出符合以下 Schema 的纯 JSON 格式数据**。不要包含 markdown 代码块标记。
        
        # JSON Schema 定义
        {{
            "course_name": "{user_inputs.get('name', '未命名')}",
            "base_info": {{
                "name": "{user_inputs.get('name', '未命名')}", 
                "code": "BJxxxx", 
                "credits": {user_inputs.get('credits', 0)}, 
                "hours": {user_inputs.get('hours', 0)},
                "type": "{user_inputs.get('course_type', '必修')}", 
                "major": "{user_inputs.get('major', '未定')}", 
                "prerequisites": "先修课"
            }},
            "objectives": ["目标1", "目标2", "..."],
            "grad_support": [
                {{ "req": "毕业要求1", "point": "1.3 工程知识", "strength": "H" }},
                {{ "req": "毕业要求3", "point": "3.2 设计/开发", "strength": "M" }}
            ],
            "content": [
                {{ "chapter": "第一章 绪论", "details": "...内容...", "lec_hrs": 2, "lab_hrs": 0, "obj_ref": "目标1" }}
            ],
            "assessment": "平时成绩30%...",
            "textbook": "教材及参考书..."
        }}
        
        # 关键参考资料
        1. 课程基本信息：{json.dumps(user_inputs, ensure_ascii=False)}
        2. 教材辅助内容：{uploaded_texts.get('textbook', '')[:2000]}
        3. 毕业要求矩阵数据：{graduation_matrix_context}
        
        # 思考步骤
        1. **分析矩阵**：仔细阅读“毕业要求矩阵数据”，找出本课程对应的所有“毕业要求指标点”和“支撑强度”。如果数据中有，必须严格照搬，**严禁编造**。
        2. **设计目标**：根据支撑的指标点，反推3-5个课程目标。
        3. **规划内容**：根据总学时 ({user_inputs.get('hours', 0)}) 分配章节。
        """
        
        yield "🧠 正在进行 OBE 逆向设计 (指标点 -> 课程目标)..."
        
        # 3. Call LLM (First Pass for JSON)
        try:
            raw_response = ai_generate(system_prompt, self.provider, self.model_name, self.keys_config)
            
            # 4. Clean and Parse JSON
            yield "📝 正在组装结构化大纲数据..."
            json_str = raw_response.strip()
            # Remove ```json only if present
            if json_str.startswith("```"):
                json_str = json_str.strip("`").replace("json", "", 1).strip()
            
            syllabus_data = json.loads(json_str)
            
            # Yield the final result data wrapper
            yield {"final_result": syllabus_data}
            yield "✅ 结构化大纲生成完成！"
            
        except json.JSONDecodeError:
            yield "❌ 生成的 JSON 格式有误，正在进行 Markdown 降级处理..."
            # Failover: Return raw text wrapped in pseudo-structure so UI doesn't crash
            yield {"final_result": {"doc_type": "raw_markdown", "content": raw_response}}
        except Exception as e:
            yield f"❌ 发生未知错误: {str(e)}"
            return

