import streamlit as st
import pandas as pd
import google.generativeai as genai
import json
import os
import base64
import io

# --- 1. JELSZÓ ELLENŐRZŐ RENDSZER ---
def check_password():
    """Visszatérési értéke True, ha a felhasználó helyes jelszót adott meg."""
    def password_entered():
        """Ellenőrzi a hitelesítő adatokat a secrets alapján."""
        if (
            st.session_state["username"] == st.secrets["credentials"]["username"]
            and st.session_state["password"] == st.secrets["credentials"]["password"]
        ):
            st.session_state["password_correct"] = True
            del st.session_state["password"]  # Biztonság: töröljük a jelszót a memóriából
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

# --- CSAK AKKOR FUT LE A TÖBBI, HA A JELSZÓ HELYES ---
if check_password():
    # --- INNENTŐL MINDEN EGYSZERI BEHÚZÁSSAL (4 SZÓKÖZ) KEZDŐDIK ---

    # --- BEÁLLÍTÁSOK ÉS AI KONFIGURÁCIÓ ---
    try:
        api_key = st.secrets["GEMINI_API_KEY"]
        genai.configure(api_key=api_key)
    except KeyError:
        st.error("❌ API kulcs nem található a Secrets-ben!")
        st.stop()

    DB_FILE = "forgalmi_adatbazis.csv"

    # --- SEGÉDFÜGGVÉNYEK ---
    def load_data():
        if os.path.exists(DB_FILE):
            return pd.read_csv(DB_FILE)
        return pd.DataFrame(columns=["Alvazszam", "Rendszam"])

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
                st.info(f"🔄 Meglévő jármű frissítve (Upsert): {alvaz}")
            else:
                new_row = pd.DataFrame([new_data_dict])
                df = pd.concat([df, new_row], ignore_index=True)
                st.success(f"✅ Új jármű rögzítve: {alvaz}")
            save_data(df)
        else:
            st.error("❌ Nem található alvázszám a PDF-ben.")

    def display_pdf(uploaded_file):
        base64_pdf = base64.b64encode(uploaded_file.getvalue()).decode('utf-8')
        pdf_display = f'<iframe src="data:application/pdf;base64,{base64_pdf}" width="100%" height="400" type="application/pdf"></iframe>'
        st.markdown(pdf_display, unsafe_allow_html=True)

    def process_pdf_with_gemini(uploaded_file):
        # Automatikus modellválasztás a Google válasza alapján
        try:
            available_models = [m.name.replace('models/', '') for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
        except:
            available_models = ['gemini-1.5-flash', 'gemini-1.5-pro']
            
        preferred_order = ['gemini-1.5-pro', 'gemini-1.5-flash', 'gemini-1.5-pro-latest']
        models_to_try = [m for m in preferred_order if m in available_models] or [available_models[0]]

        prompt = """
        Te egy profi flotta adminisztrációs rendszer vagy. 
        Vizsgáld meg a magyar forgalmi engedélyt és add vissza JSON formátumban: 
        {"Alvazszam": "17 karakter", "Rendszam": "rendszám"}. 
        Csak a nyers JSON-t írd le, minden más szöveg nélkül!
        """
        
        pdf_part = {"mime_type": "application/pdf", "data": uploaded_file.getvalue()}
        
        for model_name in models_to_try:
            try:
                model = genai.GenerativeModel(model_name)
                response = model.generate_content([prompt, pdf_part])
                clean_text = response.text.replace('```json', '').replace('```', '').strip()
                data = json.loads(clean_text)
                st.toast(f"✅ AI Modell: {model_name}")
                return data
            except Exception as e:
                st.warning(f"⚠️ Hiba a {model_name} modellel: {e}")
                continue
        return None

    # --- FELÜLET ---
    st.title("📄 Forgalmi PDF Feldolgozó (Védett)")
    
    # Oldalsáv kijelentkezéssel
    with st.sidebar:
        st.write(f"Bejelentkezve: {st.secrets['credentials']['username']}")
        if st.button("Kijelentkezés"):
            if "password_correct" in st.session_state:
                del st.session_state["password_correct"]
            st.rerun()

    uploaded_file = st.file_uploader("Forgalmi engedély feltöltése (PDF)", type=['pdf'])

    if uploaded_file is not None:
        st.markdown("**Dokumentum előnézete:**")
        display_pdf(uploaded_file)
        
        if st.button("Feldolgozás indítása", type="primary", use_container_width=True):
            with st.spinner("AI elemzés folyamatban..."):
                extracted_data = process_pdf_with_gemini(uploaded_file)
                
                if extracted_data:
                    st.write("### Kinyert adatok:")
                    df_res = pd.DataFrame([extracted_data])
                    st.dataframe(df_res, use_container_width=True, hide_index=True)
                    
                    # Excel letöltés generálása
                    output = io.BytesIO()
                    with pd.ExcelWriter(output, engine='openpyxl') as writer:
                        df_res.to_excel(writer, index=False, sheet_name='Kinyert_Adat')
                    
                    st.download_button(
                        label="📥 Kinyert adat letöltése (.xlsx)",
                        data=output.getvalue(),
                        file_name=f"adat_{extracted_data.get('Rendszam', 'ismeretlen')}.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                    )
                    upsert_record(extracted_data)

    st.divider()
    
    # Adatbázis nézet
    st.subheader("📊 Teljes Flotta Adatbázis (Puffer)")
    df_admin = load_data()
    
    if not df_admin.empty:
        st.dataframe(df_admin, use_container_width=True, hide_index=True)
        
        db_output = io.BytesIO()
        with pd.ExcelWriter(db_output, engine='openpyxl') as writer:
            df_admin.to_excel(writer, index=False, sheet_name='Flotta_Lista')
        
        st.download_button(
            label="📥 Teljes adatbázis letöltése (Excel)",
            data=db_output.getvalue(),
            file_name='teljes_flotta_adatbazis.xlsx',
            mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
    else:
        st.info("Az adatbázis még üres.")
