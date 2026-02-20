# ==========================================
# 2. 页面设置与逻辑
# ==========================================
st.set_page_config(page_title="LxU 关键词提炼工具", layout="wide")
st.title("🔍 LxU 详情页关键词批量提炼工具")

# --- 修改部分：侧边栏输入 API Key ---
with st.sidebar:
    st.header("🔑 密钥配置")
    input_key = st.text_input("输入你的 Gemini API Key", type="password", help="在此粘贴从 AI Studio 获取的 Key")
    
    # 逻辑判断：如果输入了 Key 优先用输入的，没输入就尝试读取 Secrets
    if input_key:
        api_key_to_use = input_key
    elif "GEMINI_API_KEY" in st.secrets:
        api_key_to_use = st.secrets["GEMINI_API_KEY"]
    else:
        api_key_to_use = None
        st.warning("⚠️ 请在左侧输入 API Key 以开始工作")

    st.markdown("---")
    st.header("排队设置")
    wait_time = st.slider("每个文件处理间隔(秒)", 10, 60, 25)
# --- 修改结束 ---

# 配置 API
if api_key_to_use:
    genai.configure(api_key=api_key_to_use)
