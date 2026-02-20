import streamlit as st
import pandas as pd
import google.generativeai as genai
import json
import os
import base64
import io

# --- 1. JELSZÓ ELLENŐRZŐ RENDSZER ---
def check_password():
    def password_entered():
        if (
            st.session_state["username"] == st.secrets["credentials"]["username"]
            and st.session_state["password"] == st.secrets["credentials"]["password"]
        ):
            st.session_state["password_correct"] = True
            del st.session_state["password"]
            del st.session_state["username"]
        else:
            st.session_state["password_correct"] = False

    if "password_correct" not in st.session_state:
        st.title("🔒 Bejelentkezés")
        st.text_input("Felhasználónév", on_change=password_entered, key="username")
        st.text_input("Jelszó", type="password", on_change=password_entered, key="password")
        return False
    elif not st.session_state["password_correct"]:
        st.title("🔒 Bejelentkezés")
        st.text_input("Felhasználónév", on_change=password_entered, key="username")
        st.text_input("Jelszó", type="password", on_change=password_entered, key="password")
        st.error("😕 Hibás felhasználónév vagy jelszó")
        return False
    else:
        return True

if check_password():
    # --- BEÁLLÍTÁSOK ---
    try:
        api_key = st.secrets["GEMINI_API_KEY"]
        genai.configure(api_key=api_key)
    except KeyError:
        st.error("❌ API kulcs hiányzik!")
        st.stop()

    DB_FILE = "forgalmi_adatbazis.csv"

    def load_data():
        if os.path.exists(DB_FILE):
            return pd.read_csv(DB_FILE)
        return pd.DataFrame(columns=[
            "Alvazszam", "Rendszam", "Tulajdonos", "Teljesitmeny_kW", 
            "Hengerurtartalom_cm3", "Elso_forgalomba_helyezes", "Magyarorszagi_elso_nyilvantartas"
        ])

    def save_data(df):
        df.to_csv(DB_FILE, index=False)

    def upsert_record(new_data_dict):
        df = load_data()
        alvaz = new_data_dict.get("Alvazszam")
        if alvaz:
            if alvaz in df["Alvazszam"].values:
                idx = df.index[df['Alvazszam'] == alvaz][0]
                for key, value in new_data_dict.items():
                    if value: df.at[idx, key] = value
                st.info(f"🔄 Adatok frissítve: {alvaz}")
            else:
                new_row = pd.DataFrame([new_data_dict])
                df = pd.concat([df, new_row], ignore_index=True)
                st.success(f"✅ Új jármű rögzítve: {alvaz}")
            save_data(df)

    def process_pdf_with_gemini(uploaded_file):
        try:
            available_models = [m.name.replace('models/', '') for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
        except:
            available_models = ['gemini-1.5-flash']
            
        model_name = 'gemini-1.5-flash' if 'gemini-1.5-flash' in available_models else available_models[0]

        prompt = """
        Elemezd a csatolt magyar forgalmi engedélyt (PDF). Keresd meg és gyűjtsd ki az alábbi adatokat JSON formátumban:
        - Alvazszam (E kód)
        - Rendszam (A kód)
        - Tulajdonos (C.1.1, C.1.2 vagy C.1.3 mezőnél szereplő név)
        - Teljesitmeny_kW (P.2 kód, csak a szám)
        - Hengerurtartalom_cm3 (P.1 kód, csak a szám)
        - Elso_forgalomba_helyezes (B kód, YYYY.MM.DD formátum)
        - Magyarorszagi_elso_nyilvantartas (I kód, YYYY.MM.DD formátum)

        Fontos: Csak a nyers JSON-t add vissza, ne írj hozzá magyarázatot!
        Ha valamit nem találsz, az értéke legyen null.
        Példa: {"Alvazszam": "...", "Rendszam": "...", "Tulajdonos": "...", "Teljesitmeny_kW": 110, "Hengerurtartalom_cm3": 1968, "Elso_forgalomba_helyezes": "2020.01.01", "Magyarorszagi_elso_nyilvantartas": "2020.02.15"}
        """
        
        pdf_part = {"mime_type": "application/pdf", "data": uploaded_file.getvalue()}
        
        try:
            model = genai.GenerativeModel(model_name)
            response = model.generate_content([prompt, pdf_part])
            clean_text = response.text.replace('```json', '').replace('```', '').strip()
            return json.loads(clean_text)
        except Exception as e:
            st.error(f"Hiba az AI feldolgozás során: {e}")
            return None

    # --- FELÜLET ---
    st.title("📄 Flotta Adatkinyerő")
    
    with st.sidebar:
        st.write(f"👤 Felhasználó: {st.secrets['credentials']['username']}")
        if st.button("Kijelentkezés"):
            del st.session_state["password_correct"]
            st.rerun()

    uploaded_file = st.file_uploader("Forgalmi engedély feltöltése (PDF)", type=['pdf'])

    if uploaded_file is not None:
        if st.button("Adatok kinyerése és mentése", type="primary", use_container_width=True):
            with st.spinner("AI mélyelemzés folyamatban..."):
                extracted_data = process_pdf_with_gemini(uploaded_file)
                
                if extracted_data:
                    st.subheader("Kinyert adatok")
                    st.table(pd.DataFrame([extracted_data]).T.rename(columns={0: "Érték"}))
                    upsert_record(extracted_data)

    st.divider()
    st.subheader("📊 Központi Flotta Adatbázis")
    df_admin = load_data()
    
    if not df_admin.empty:
        st.dataframe(df_admin, use_container_width=True, hide_index=True)
        
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df_admin.to_excel(writer, index=False, sheet_name='Flotta_Lista')
        
        st.download_button(
            label="📥 Teljes adatbázis letöltése (.xlsx)",
            data=output.getvalue(),
            file_name='flotta_nyilvantartas.xlsx',
            mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
    else:
        st.info("Nincs rögzített adat.")

