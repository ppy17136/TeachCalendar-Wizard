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
        Main Agent Loop for Syllabus Generation.
        user_inputs: dict of form fields (course_name, hours, etc.)
        uploaded_texts: dict of { "textbook": "...", "plan": "..." }
        """
        
        # 1. Planning Phase
        yield "🤖 Agent 启动: 正在阅读用户需求..."
        course_name = user_inputs.get('course_name')
        
        yield f"📘 正在分析教材: {user_inputs.get('textbook_name', '未命名')}"
        textbook_content = uploaded_texts.get('textbook', '')
        # Simulate simple "Thought" - check if textbook is long
        if len(textbook_content) > 20000:
             yield "⚠️ 教材内容过长，启动智能切片阅读模式..."
             textbook_excerpt = textbook_content[:15000] # Simple truncate for now
        else:
             textbook_excerpt = textbook_content
             
        # 2. Validation Phase (Skill Use)
        yield "🔍 正在进行 OBE 目标校验..."
        obe_check = self.skills.validate_obe_compliance(user_inputs.get('objectives', ''))
        if not obe_check.get("is_compliant"):
            yield f"💡 发现优化空间: {obe_check.get('analysis')}"
            # Auto-optimize logic could go here, for now we just log it
        
        # 3. Generation Phase
        yield "✍️ 开始构思大纲结构..."
        
        # Construct the mega-prompt (similar to original app but structured by Agent)
        # In a full Agent system, this would be broken down into steps like:
        # Step 1: Generate Basic Info Table
        # Step 2: Generate Chapter Allocation
        # Step 3: Refine
        
        # For stability, we keep the robust single-pass generation but wrap it in the Agent's persona
        final_prompt = f"""
        你是一个智能教学辅助 Agent。请根据以下信息撰写《{course_name}》的教学大纲。
        
        [输入参数]
        {json.dumps(user_inputs, ensure_ascii=False)}
        
        [教材摘要]
        {textbook_excerpt}
        
        [培养方案]
        {uploaded_texts.get('plan', '')[:10000]}
        
        [OBE 校验反馈]
        {json.dumps(obe_check, ensure_ascii=False)}
        
        请生成完整大纲，Markdown 格式。
        """
        
        yield "🚀 正在生成最终大纲内容 (这可能需要 30 秒)..."
        result = ai_generate(final_prompt, self.provider, self.model_name, self.keys_config)
        
        # Yield the final result data wrapper
        yield {"final_result": result}
        yield "✅ 生成完成！"

