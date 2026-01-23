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
