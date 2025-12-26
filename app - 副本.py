"""
TeachGenius - 教学日历智能生成系统
主应用文件
"""
import streamlit as st

# 设置页面配置
st.set_page_config(
    page_title="TeachGenius - 教学日历智能生成系统",
    page_icon="🎓",
    layout="wide",
    initial_sidebar_state="expanded"
)

# 自定义CSS样式
st.markdown("""
<style>
    .main-header {
        font-size: 2.5rem;
        color: #1E3A8A;
        text-align: center;
        margin-bottom: 2rem;
        font-weight: bold;
    }
    .sub-header {
        font-size: 1.5rem;
        color: #3B82F6;
        margin-top: 1.5rem;
        margin-bottom: 1rem;
    }
    .feature-card {
        background-color: #F0F9FF;
        padding: 1.5rem;
        border-radius: 10px;
        border-left: 5px solid #3B82F6;
        margin-bottom: 1rem;
    }
    .stButton>button {
        background-color: #3B82F6;
        color: white;
        font-weight: bold;
        border-radius: 8px;
        padding: 0.5rem 2rem;
    }
</style>
""", unsafe_allow_html=True)

# 主页内容
def main():
    # 标题和简介
    st.markdown('<h1 class="main-header">🎓 TeachGenius 教学日历智能生成系统</h1>', unsafe_allow_html=True)
    
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.image("https://cdn-icons-png.flaticon.com/512/2232/2232688.png", width=200)
    
    st.markdown("""
    ## ✨ 欢迎使用 TeachGenius
    
    一个专为教育工作者设计的智能教学日历生成工具，帮助您快速、高效地创建专业级教学日历。
    """)
    
    # 功能介绍
    st.markdown('<h2 class="sub-header">🌟 核心功能</h2>', unsafe_allow_html=True)
    
    cols = st.columns(3)
    
    with cols[0]:
        st.markdown("""
        <div class="feature-card">
            <h3>📄 智能模板制作</h3>
            <p>自动识别文档内容，转换为带标签的专业模板</p>
            <ul>
                <li>自动标签识别</li>
                <li>手动标签编辑</li>
                <li>模板预览下载</li>
            </ul>
        </div>
        """, unsafe_allow_html=True)
    
    with cols[1]:
        st.markdown("""
        <div class="feature-card">
            <h3>🚀 智能内容填充</h3>
            <p>AI驱动的内容提取与自动填充</p>
            <ul>
                <li>AI智能数据提取</li>
                <li>完美格式保留</li>
                <li>批量处理支持</li>
            </ul>
        </div>
        """, unsafe_allow_html=True)
    
    with cols[2]:
        st.markdown("""
        <div class="feature-card">
            <h3>📊 教学日历管理</h3>
            <p>完整的教学日历创建与管理</p>
            <ul>
                <li>多格式导出</li>
                <li>历史记录保存</li>
                <li>模板库管理</li>
            </ul>
        </div>
        """, unsafe_allow_html=True)
    
    # 快速开始
    st.markdown('<h2 class="sub-header">⚡ 快速开始</h2>', unsafe_allow_html=True)
    
    col_a, col_b, col_c = st.columns(3)
    
    with col_a:
        if st.button("📄 开始制作模板", use_container_width=True):
            st.switch_page("pages/1_📄_模板制作.py")
    
    with col_b:
        if st.button("🚀 智能填充日历", use_container_width=True):
            st.switch_page("pages/2_🚀_智能填充.py")
    
    with col_c:
        if st.button("📚 查看使用教程", use_container_width=True):
            st.switch_page("pages/3_📚_使用教程.py")
    
    # 特色展示
    st.markdown('<h2 class="sub-header">🎯 为什么选择 TeachGenius？</h2>', unsafe_allow_html=True)
    
    features = [
        ("🤖 AI智能识别", "基于先进的AI技术，智能识别文档内容，自动生成标签"),
        ("🎨 完美格式保留", "100%保留原文档格式，确保专业美观"),
        ("⚡ 高效省时", "将数小时的工作压缩到几分钟内完成"),
        ("🔧 灵活自定义", "支持手动编辑和调整，满足个性化需求"),
        ("📱 云端部署", "随时随地通过浏览器访问使用"),
        ("🔄 持续更新", "定期更新功能，提供更好的用户体验")
    ]
    
    for i in range(0, len(features), 2):
        cols = st.columns(2)
        for j in range(2):
            if i + j < len(features):
                with cols[j]:
                    title, desc = features[i + j]
                    st.markdown(f"""
                    <div style="padding: 1rem; border-radius: 8px; background: #f8fafc; margin-bottom: 1rem;">
                        <h4 style="color: #1E3A8A; margin-bottom: 0.5rem;">{title}</h4>
                        <p style="color: #4B5563; margin: 0;">{desc}</p>
                    </div>
                    """, unsafe_allow_html=True)
    
    # 底部信息
    st.markdown("---")
    st.markdown("""
    <div style="text-align: center; color: #6B7280; padding: 1rem;">
        <p>© 2024 TeachGenius 教学日历智能生成系统 | 版本 1.0.0</p>
        <p>如有问题或建议，请通过邮件联系我们</p>
    </div>
    """, unsafe_allow_html=True)

if __name__ == "__main__":
    main()