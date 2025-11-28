import streamlit as st
import easyocr
import cv2
import numpy as np
import sqlite3
import pandas as pd
import os

# --- 1. 初始化設定 ---
st.set_page_config(page_title="進階車牌辨識系統", layout="centered")

@st.cache_resource
def load_reader():
    return easyocr.Reader(['en'])

reader = load_reader()

DB_FILE = "lpr_system.db"

# --- 2. 資料庫功能 (含密碼與新欄位) ---
def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    
    # 建立車牌資料表 (新增 category, employee_id, parking_permit)
    c.execute('''
        CREATE TABLE IF NOT EXISTS plates (
            plate_number TEXT PRIMARY KEY,
            owner_name TEXT,
            department TEXT,
            category TEXT,
            employee_id TEXT,
            parking_permit TEXT
        )
    ''')
    
    # 建立設定資料表 (存放密碼)
    c.execute('''
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    ''')
    
    # 初始化預設密碼 (如果沒有的話)
    c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('frontend_pwd', '123456')")
    c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('backend_pwd', '123456')")
    
    conn.commit()
    conn.close()

def get_password(key):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT value FROM settings WHERE key = ?", (key,))
    res = c.fetchone()
    conn.close()
    return res[0] if res else "123456"

def update_password(key, new_pwd):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("UPDATE settings SET value = ? WHERE key = ?", (new_pwd, key))
    conn.commit()
    conn.close()

def clean_plate_text(text):
    return text.replace("-", "").replace(" ", "").upper()

def add_plate(data):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    plate = clean_plate_text(data['plate'])
    try:
        c.execute('''
            INSERT INTO plates (plate_number, owner_name, department, category, employee_id, parking_permit) 
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (plate, data['name'], data['dept'], data['cat'], data['eid'], data['permit']))
        conn.commit()
        return True, f"成功新增: {plate}"
    except sqlite3.IntegrityError:
        return False, f"車牌已存在: {plate}"
    finally:
        conn.close()

def delete_plate(plate):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("DELETE FROM plates WHERE plate_number = ?", (plate,))
    conn.commit()
    conn.close()

def delete_all_plates():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("DELETE FROM plates")
    conn.commit()
    conn.close()

def search_plates(query, fuzzy=False):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    clean_q = clean_plate_text(query)
    
    if fuzzy:
        # 模糊搜尋：前後加上 %
        c.execute("SELECT * FROM plates WHERE plate_number LIKE ?", (f'%{clean_q}%',))
        results = c.fetchall()
    else:
        # 精確搜尋 (用於 OCR)
        c.execute("SELECT * FROM plates WHERE plate_number = ?", (clean_q,))
        results = c.fetchall()
        
    conn.close()
    return results

def load_data():
    conn = sqlite3.connect(DB_FILE)
    df = pd.read_sql_query("SELECT * FROM plates", conn)
    conn.close()
    return df

# 初始化
init_db()

# --- 3. 圖像辨識 ---
def recognize_plate(image_bytes):
    file_bytes = np.asarray(bytearray(image_bytes.read()), dtype=np.uint8)
    img = cv2.imdecode(file_bytes, 1)
    results = reader.readtext(img)
    detected = []
    for (bbox, text, prob) in results:
        cleaned = clean_plate_text(text)
        if len(cleaned) >= 3 and prob > 0.3:
            detected.append(cleaned)
    return detected

# --- 4. 登入介面邏輯 ---
def check_login(role):
    """role: 'frontend' or 'backend'"""
    # Session key 區分前後台
    session_key = f"logged_in_{role}"
    
    if st.session_state.get(session_key):
        return True
        
    pwd_key = f"{role}_pwd"
    correct_pwd = get_password(pwd_key)
    
    st.subheader(f"🔒 {role} 登入")
    input_pwd = st.text_input("請輸入密碼", type="password", key=f"input_{role}")
    
    if st.button("登入", key=f"btn_{role}"):
        if input_pwd == correct_pwd:
            st.session_state[session_key] = True
            st.rerun()
        else:
            st.error("密碼錯誤")
    return False

# --- 5. 主程式 ---
st.sidebar.title("導航選單")
menu = st.sidebar.radio("前往", ["📸 車牌辨識 (前台)", "⚙️ 後台管理"])

# ================= ⚙️ 後台管理 =================
if menu == "⚙️ 後台管理":
    if check_login('backend'):
        st.title("⚙️ 後台管理系統")
        
        # 登出按鈕
        if st.sidebar.button("登出後台"):
            st.session_state['logged_in_backend'] = False
            st.rerun()

        tab1, tab2, tab3, tab4 = st.tabs(["➕ 新增/匯入", "📃 資料列表/刪除", "⚠️ 資料庫重置", "🔐 密碼設定"])

        with tab1:
            st.subheader("新增車牌")
            col1, col2 = st.columns(2)
            with st.form("add_form"):
                p_plate = st.text_input("車牌號碼")
                p_cat = st.selectbox("類別", ["汽車", "機車"])
                p_name = st.text_input("姓名")
                p_dept = st.text_input("部門")
                p_eid = st.text_input("工號")
                p_permit = st.text_input("停車證號")
                
                if st.form_submit_button("新增"):
                    if p_plate and p_name:
                        data = {
                            'plate': p_plate, 'name': p_name, 'dept': p_dept,
                            'cat': p_cat, 'eid': p_eid, 'permit': p_permit
                        }
                        s, m = add_plate(data)
                        if s: st.success(m)
                        else: st.error(m)
                    else:
                        st.warning("車牌與姓名為必填")

            st.divider()
            st.subheader("CSV 批次匯入")
            st.info("CSV 欄位需包含：車牌, 姓名, 部門, 類別, 工號, 停車證")
            uploaded_file = st.file_uploader("上傳 CSV", type=['csv'])
            if uploaded_file:
                try:
                    try:
                        df_up = pd.read_csv(uploaded_file)
                    except:
                        uploaded_file.seek(0)
                        df_up = pd.read_csv(uploaded_file, encoding='big5')
                    
                    # 檢查並補齊缺失欄位 (避免 CSV 只有舊格式時報錯)
                    expected_cols = ['車牌', '姓名', '部門', '類別', '工號', '停車證']
                    for col in expected_cols:
                        if col not in df_up.columns:
                            df_up[col] = "" # 若無該欄位則填空

                    if st.button("確認匯入"):
                        count = 0
                        for _, row in df_up.iterrows():
                            data = {
                                'plate': str(row['車牌']), 'name': str(row['姓名']),
                                'dept': str(row['部門']), 'cat': str(row.get('類別', '汽車')),
                                'eid': str(row.get('工號', '')), 'permit': str(row.get('停車證', ''))
                            }
                            s, m = add_plate(data)
                            if s: count += 1
                        st.success(f"成功匯入 {count} 筆資料")
                except Exception as e:
                    st.error(f"匯入失敗: {e}")

        with tab2:
            st.subheader("現有資料")
            df = load_data()
            st.dataframe(df, use_container_width=True)
            
            st.write("刪除單筆資料")
            del_target = st.selectbox("選擇車牌", df['plate_number'].tolist() if not df.empty else [])
            if st.button("刪除此車牌"):
                delete_plate(del_target)
                st.rerun()

        with tab3:
            st.error("⚠️ 危險區域：清除所有資料")
            st.warning("此操作將會刪除資料庫內「所有」車牌資料，且無法復原！")
            confirm_clear = st.checkbox("我確認要清空所有資料庫")
            
            if st.button("🔴 執行清空資料庫", disabled=not confirm_clear):
                delete_all_plates()
                st.success("資料庫已清空！")
                st.rerun()

        with tab4:
            st.subheader("修改登入密碼")
            p_type = st.selectbox("選擇要修改的密碼", ["前台 (frontend)", "後台 (backend)"])
            new_p = st.text_input("輸入新密碼", type="password")
            if st.button("更新密碼"):
                key = "frontend_pwd" if "前台" in p_type else "backend_pwd"
                update_password(key, new_p)
                st.success(f"{p_type} 密碼已更新！")

# ================= 📸 前台辨識 =================
elif menu == "📸 車牌辨識 (前台)":
    if check_login('frontend'):
        st.title("📸 車牌查詢系統")
        
        if st.sidebar.button("登出前台"):
            st.session_state['logged_in_frontend'] = False
            st.rerun()
        
        # 1. 拍照區塊
        st.subheader("📷 拍照辨識")
        img_file = st.camera_input("拍攝")
        if img_file:
            candidates = recognize_plate(img_file)
            if candidates:
                found = False
                for t in candidates:
                    # 這裡使用精確搜尋
                    results = search_plates(t, fuzzy=False)
                    if results:
                        row = results[0] # 取第一筆
                        st.success(f"✅ 辨識成功: {row[0]}")
                        c1, c2 = st.columns(2)
                        c1.info(f"👤 姓名: {row[1]}")
                        c1.info(f"🏢 部門: {row[2]}")
                        c2.info(f"🛵 類別: {row[3]}")
                        c2.info(f"🅿️ 證號: {row[5]}")
                        found = True
                        break
                if not found:
                    st.warning(f"⚠️ 辨識出 {candidates}，但無資料。")
            else:
                st.error("❌ 無法辨識")

        st.divider()

        # 2. 模糊查詢區塊
        st.subheader("🔍 手動模糊查詢")
        with st.form("search_form"):
            col1, col2 = st.columns([3, 1])
            with col1:
                query_input = st.text_input("輸入車牌 (可只輸入部分數字)", placeholder="例如: 9012")
            with col2:
                st.write("")
                st.write("")
                search_btn = st.form_submit_button("搜尋")
        
        if search_btn and query_input:
            # 開啟 fuzzy=True
            results = search_plates(query_input, fuzzy=True)
            if results:
                st.success(f"找到 {len(results)} 筆符合資料：")
                # 整理顯示格式
                res_df = pd.DataFrame(results, columns=['車牌', '姓名', '部門', '類別', '工號', '停車證'])
                st.dataframe(res_df, use_container_width=True)
            else:
                st.info("❌ 查無符合資料")