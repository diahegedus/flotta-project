import streamlit as st
import pandas as pd
import google.generativeai as genai
import json
import os
import base64
import io

# --- BEÁLLÍTÁSOK ÉS BIZTONSÁG ---
try:
    api_key = st.secrets["GEMINI_API_KEY"]
    genai.configure(api_key=api_key)
except KeyError:
    st.error("❌ Hiba: Nem található a GEMINI_API_KEY a secrets beállításokban!")
    st.stop()

DB_FILE = "forgalmi_adatbazis.csv" 

def load_data():
    if os.path.exists(DB_FILE):
        return pd.read_csv(DB_FILE)
    else:
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
                if value: 
                    df.at[idx, key] = value
            st.info(f"🔄 Meglévő jármű frissítve: {alvaz}")
        else:
            new_row = pd.DataFrame([new_data_dict])
            df = pd.concat([df, new_row], ignore_index=True)
            st.success(f"✅ Új jármű rögzítve: {alvaz}")
        save_data(df)
    else:
        st.error("❌ Nem sikerült alvázszámot azonosítani a PDF-ből.")

def display_pdf(uploaded_file):
    base64_pdf = base64.b64encode(uploaded_file.getvalue()).decode('utf-8')
    pdf_display = f'<iframe src="data:application/pdf;base64,{base64_pdf}" width="100%" height="400" type="application/pdf"></iframe>'
    st.markdown(pdf_display, unsafe_allow_html=True)

def process_pdf_with_gemini(uploaded_file):
    # 1. OKOS MODELLVÁLASZTÁS: Megkérdezzük a Google-t, hogy mik az engedélyezett modellek
    try:
        available_models = [m.name.replace('models/', '') for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
    except Exception as e:
        st.error(f"❌ API Kulcs hiba: Nem sikerült lekérdezni az elérhető modelleket. Részletek: {e}")
        return None
        
    if not available_models:
        st.error("❌ A Google egyetlen modellt sem engedélyez ehhez az API kulcshoz.")
        return None

    # 2. Prioritási sorrend felállítása (a legjobbtól a legrégebbi felé)
    preferred_order = ['gemini-1.5-pro', 'gemini-1.5-flash', 'gemini-1.5-pro-latest', 'gemini-1.0-pro', 'gemini-pro']
    
    # Kiválogatjuk azokat, amik tényleg benne vannak a Te engedélyezett listádban
    models_to_try = [m for m in preferred_order if m in available_models]
    
    # Ha a preferáltak közül egyik sincs, próbáljuk meg azt, amit a Google legelsőként felkínál
    if not models_to_try:
        models_to_try = [available_models[0]]

    prompt = """
    Te egy profi flotta adminisztrációs adatkinyerő rendszer vagy. 
    Vizsgáld meg a csatolt PDF dokumentumot, ami egy magyar forgalmi engedély.
    Keresd meg rajta a rendszámot és az alvázszámot.
    Pontosan az alábbi JSON formátumban válaszolj (markdown formázás és egyéb szöveg nélkül, csak a nyers JSON):
    {
        "Alvazszam": "ide jön a 17 karakteres alvázszám, ha van",
        "Rendszam": "ide jön a rendszám, ha van"
    }
    Ha egy adatot nem találsz, az értéke legyen null.
    """
    
    pdf_part = {
        "mime_type": "application/pdf",
        "data": uploaded_file.getvalue()
    }
    
    # 3. Próbálkozás a dinamikusan kiválasztott modellekkel
    for model_name in models_to_try:
        try:
            model = genai.GenerativeModel(model_name)
            response = model.generate_content([prompt, pdf_part])
            clean_text = response.text.replace('```json', '').replace('```', '').strip()
            data = json.loads(clean_text)
            
            st.toast(f"✅ AI Modell sikeresen használva: {model_name}")
            return data
            
        except Exception as e:
            st.warning(f"⚠️ Hiba a(z) {model_name} modellel: {e}")
            continue 

    st.error("❌ Egyik engedélyezett AI modellel sem sikerült a feldolgozás.")
    return None

# --- STREAMLIT FELÜLET ---
st.set_page_config(page_title="Forgalmi PDF Feldolgozó Pilot", layout="centered")

st.title("📄 Forgalmi Engedély PDF Feldolgozó")

# --- ÚJ DIAGNOSZTIKA SZEKCIÓ ---
with st.expander("🛠️ Rendszer Diagnosztika (Kattints ide a hibakereséshez)"):
    st.write("Ezen a panelen ellenőrizheted, hogy a Google milyen AI modelleket engedélyezett a te konkrét API kulcsodhoz.")
    if st.button("Lekérdezés indítása"):
        try:
            models = [m.name for m in genai.list_models()]
            st.success("✅ A kulcs működik! A Google az alábbi modelleket engedélyezi számodra:")
            st.json(models)
        except Exception as e:
            st.error(f"❌ Hiba a lekérdezés során: {e}")

st.markdown("Húzz be egy forgalmi engedélyt tartalmazó PDF-et. A rendszer kinyeri az adatokat és azonnal exportálható Excel fájlt készít belőle.")

uploaded_file = st.file_uploader("Forgalmi engedély feltöltése (PDF)", type=['pdf'])

if uploaded_file is not None:
    st.markdown("**Feltöltött dokumentum előnézete:**")
    display_pdf(uploaded_file)
    
    if st.button("Feldolgozás indítása", type="primary", use_container_width=True):
        with st.spinner("PDF elemzése folyamatban (AI fut)..."):
            extracted_data = process_pdf_with_gemini(uploaded_file)
            
            if extracted_data:
                st.write("### Kinyert adatok:")
                df_result = pd.DataFrame([extracted_data])
                st.dataframe(df_result, use_container_width=True, hide_index=True)
                
                output = io.BytesIO()
                with pd.ExcelWriter(output, engine='openpyxl') as writer:
                    df_result.to_excel(writer, index=False, sheet_name='Kinyert_Adatok')
                excel_data = output.getvalue()
                
                st.download_button(
                    label="📥 Kinyert adat letöltése (.xlsx)",
                    data=excel_data,
                    file_name=f"kinyert_adat_{extracted_data.get('Rendszam', 'ismeretlen')}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )
                upsert_record(extracted_data)

st.divider()

st.subheader("📊 Teljes Flotta Adatbázis (Puffer / SharePoint Szimuláció)")
df_admin = load_data()

if not df_admin.empty:
    st.dataframe(df_admin, use_container_width=True, hide_index=True)
    
    db_output = io.BytesIO()
    with pd.ExcelWriter(db_output, engine='openpyxl') as writer:
        df_admin.to_excel(writer, index=False, sheet_name='Flotta_Adatbazis')
    db_excel_data = db_output.getvalue()
    
    st.download_button(
        label="📥 Teljes adatbázis letöltése (.xlsx)",
        data=db_excel_data,
        file_name='Biztosito_Betoltes_Pilot.xlsx',
        mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        type="primary"
    )
else:
    st.info("Az adatbázis jelenleg üres. Tölts fel egy PDF forgalmit a kezdéshez!")
