import google.generativeai as genai
from openai import OpenAI
from PIL import Image
import io
import base64

def get_llm_config(provider, keys_config):
    """
    Helper to get key and url based on provider.
    keys_config should be a dict like: {'Qwen': '...', 'Gemini': '...'}
    """
    # 2. OpenAI 兼容协议处理 (Qwen, Baidu, Kimi) 
    config_map = {
        "Qwen": {"key": keys_config.get("Qwen"), "url": "https://dashscope.aliyuncs.com/compatible-mode/v1"},
        "QwenM": {"key": keys_config.get("QwenM"), "url": "https://api-inference.modelscope.cn/v1"},
        "Baidu": {"key": keys_config.get("Baidu"), "url": "https://qianfan.baidubce.com/v2"},
        "Kimi": {"key": keys_config.get("Kimi"), "url": "https://api.moonshot.cn/v1"},
        "GLM": {"key": keys_config.get("GLM"), "url": "https://open.bigmodel.cn/api/paas/v4"}
    }
    return config_map.get(provider)


def ai_generate(prompt, provider, model_name, keys_config):
    """统一文本生成接口，支持多模型路由. 
    keys_config: dict containing API keys.
    """
    # 1. 官方 SDK 处理 (Gemini) 
    if provider == "Gemini":
        gemini_key = keys_config.get("Gemini")
        if not gemini_key: return "错误：未配置密钥"
        try:
            genai.configure(api_key=gemini_key)
            model = genai.GenerativeModel(model_name)
            response = model.generate_content(prompt)
            return response.text
        except Exception as e: return f"Gemini 失败: {str(e)}"

    # 2. OpenAI 兼容协议处理
    target = get_llm_config(provider, keys_config)
    
    if not target or not target["key"]:
        return f"错误：未配置 {provider} 密钥"
    
    try:
        # 利用 OpenAI 库的兼容性一键切换 
        client = OpenAI(api_key=target["key"], base_url=target["url"])
        completion = client.chat.completions.create(
            model=model_name, 
            messages=[{"role": "user", "content": prompt}]
        )
        return completion.choices[0].message.content
    except Exception as e:
        return f"{provider} 生成失败: {str(e)}"


def ai_ocr(image_bytes, provider, model_name, keys_config):
    """根据引擎进行图片文字识别"""
    if provider == "Gemini":
        gemini_key = keys_config.get("Gemini")
        if not gemini_key: return "错误：未配置密钥"
        try:
            genai.configure(api_key=gemini_key)
            model = genai.GenerativeModel(model_name)
            res = model.generate_content(["识别并输出图中文字内容。若是试卷，请提取题目和回答。", {"mime_type": "image/jpeg", "data": image_bytes}])
            return res.text
        except Exception as e: return f"Gemini 视觉识别失败: {str(e)}"
    else:
        qwen_key = keys_config.get("Qwen") # Default to Qwen for OCR if not Gemini
        if not qwen_key: return "错误：未配置密钥 (需要 Qwen Key)"
        
        # 图片压缩优化
        img = Image.open(io.BytesIO(image_bytes)).convert('RGB')
        max_width = 1024
        if img.width > max_width:
            scale = max_width / img.width
            img = img.resize((max_width, int(img.height * scale)))
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=90)
        b64img = base64.b64encode(buf.getvalue()).decode("utf-8")
        
        client = OpenAI(api_key=qwen_key, base_url="https://dashscope.aliyuncs.com/compatible-mode/v1")
        try:
            completion = client.chat.completions.create(
                model="qwen-vl-ocr-latest",
                messages=[{"role": "user", "content": [{"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64img}"}}, {"type": "text", "text": "请提取图中所有文字内容"}]}]
            )
            return completion.choices[0].message.content
        except Exception as e: return f"Qwen OCR 失败: {str(e)}"
