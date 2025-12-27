import streamlit as st
import pandas as pd
import math
from datetime import datetime

# ==========================================
# 0. CONFIG & CSS (CUSTOM UI DESIGN)
# ==========================================
st.set_page_config(page_title="ProChem Tower Wizard", layout="wide", page_icon="🏭")

# Endüstriyel Tema ve Kart Tasarımları için CSS Injection
st.markdown("""
<style>
    /* Ana Arka Plan ve Yazı Tipi */
    .reportview-container {
        background: #f0f2f6;
    }
    
    /* Başlık Stilleri */
    h1, h2, h3 {
        color: #1e3d59;
        font-family: 'Roboto', sans-serif;
    }
    
    /* Progress Bar Alanı */
    .stProgress > div > div > div > div {
        background-color: #1e3d59;
    }
    
    /* Özel Sonuç Kartları (Step 3) */
    .metric-card {
        background-color: white;
        padding: 20px;
        border-radius: 10px;
        box-shadow: 0 4px 6px rgba(0,0,0,0.1);
        border-left: 5px solid #1e3d59;
        text-align: center;
    }
    .metric-label {
        font-size: 14px;
        color: #5e6f7f;
        margin-bottom: 5px;
    }
    .metric-value {
        font-size: 32px;
        font-weight: bold;
        color: #1e3d59;
    }
    
    /* Sidebar Genişliği ve Stili */
    .css-1d391kg {
        width: 300px;
    }
</style>
""", unsafe_allow_html=True)

# ==========================================
# 1. MOCK DATA & ENGINE (MANTIK AYNI)
# ==========================================
PRODUCT_CATALOG = {
    "Antiskalantlar": [
        {"code": "CHEM-100", "name": "Basic Phosphonate", "type": "Std"},
        {"code": "CHEM-200", "name": "High Perf. Polymer", "type": "Pro"},
    ],
    "Korozyon_Inh": [{"code": "CORR-ZN", "name": "Zinc Inhibitor", "type": "Zn"}],
    "Biyositler": [{"code": "BIO-ISO", "name": "Isothiazolin", "type": "Non-Ox"}]
}

class FrenchCreekStyleEngine:
    def __init__(self): self.evap_factor = 0.00153 
        
    def calculate_indices(self, w, t_c):
        cah, alk = w.get('CaH', 0), w.get('Alk', 0)
        if cah <= 0 or alk <= 0: return {"LSI": -99, "Ca_SO4": 0, "SiO2": 0}
        tds = w.get('Cond', 1000) * 0.65
        A, B = (math.log10(tds + 1) - 1) / 10, -13.12 * math.log10(t_c + 273) + 34.55
        C, D = math.log10(cah + 0.1) - 0.4, math.log10(alk + 0.1)
        pHs = (9.3 + A + B) - (C + D)
        return {"LSI": w.get('pH', 7.0) - pHs, "Ca_SO4": cah * w.get('SO4', 0), "SiO2": w.get('SiO2', 0)}

    def run_simulation(self, raw, des, const):
        cycle = 1.0
        history = []
        stemp = des.get('t_out', 32) + 15
        losses = des.get('proc_loss', 0) + (des.get('q_circ', 1000) * 0.0002)
        evap = des.get('q_circ', 1000) * des.get('dt', 10) * self.evap_factor
        mhydro = (evap + losses) / losses if losses > 0 else 50.0

        while True:
            curr = {k: (v * cycle if k != 'pH' else min(raw['pH'] + math.log10(cycle), 9.3)) for k, v in raw.items()}
            idx = self.calculate_indices(curr, stemp)
            stop = None
            if cycle >= mhydro: stop = "Hydraulic Limit"
            elif curr['SiO2'] > const['max_SiO2']: stop = "Silica Limit"
            elif idx['LSI'] > const['max_LSI']: stop = "LSI Limit"

            history.append({"Cycle": round(cycle, 1), "LSI": round(idx['LSI'], 2), "SiO2": round(curr['SiO2'], 1), "Stop_Reason": stop})
            if stop or cycle > 20.0: return history[-2 if len(history)>1 else -1], history
            cycle += 0.1

engine = FrenchCreekStyleEngine()

# ==========================================
# 2. STATE YÖNETİMİ & GÖRSEL NAVİGASYON
# ==========================================
if 'step' not in st.session_state: st.session_state.step = 1

# Hafıza Varsayılanları
defaults = {
    'customer': '', 'sys_id': 'Kule-1', 'ca': 80, 'mg': 40, 'alk': 100, 'cl': 50, 'so4': 40, 'sio2': 15, 'ph': 7.8, 'cond': 600,
    'q_circ': 1500, 'dt': 10, 't_out': 32, 'loss': 0.1, 'l_lsi': 2.8, 'l_sio2': 180
}
for k, v in defaults.items():
    if k not in st.session_state: st.session_state[k] = v

# Navigasyon
def go_next(): st.session_state.step += 1
def go_back(): st.session_state.step -= 1

# --- ÜST GÖRSEL NAVİGASYON BAR ---
st.markdown("### Proje Aşamaları")
col_nav1, col_nav2, col_nav3, col_nav4 = st.columns(4)

step_css_active = "background-color: #1e3d59; color: white; padding: 10px; border-radius: 5px; text-align: center; font-weight: bold;"
step_css_inactive = "background-color: #dbe2ef; color: #1e3d59; padding: 10px; border-radius: 5px; text-align: center;"

with col_nav1: st.markdown(f"<div style='{step_css_active if st.session_state.step==1 else step_css_inactive}'>1. Künye</div>", unsafe_allow_html=True)
with col_nav2: st.markdown(f"<div style='{step_css_active if st.session_state.step==2 else step_css_inactive}'>2. Veri Girişi</div>", unsafe_allow_html=True)
with col_nav3: st.markdown(f"<div style='{step_css_active if st.session_state.step==3 else step_css_inactive}'>3. Analiz</div>", unsafe_allow_html=True)
with col_nav4: st.markdown(f"<div style='{step_css_active if st.session_state.step==4 else step_css_inactive}'>4. Reçete</div>", unsafe_allow_html=True)

st.markdown("###") # Boşluk

# ==========================================
# SAYFA 1: KÜNYE
# ==========================================
if st.session_state.step == 1:
    st.subheader("📝 Adım 1: Proje Künyesi")
    
    with st.container():
        st.markdown("<div style='background-color: white; padding: 30px; border-radius: 10px; box-shadow: 0 2px 4px rgba(0,0,0,0.05);'>", unsafe_allow_html=True)
        c1, c2 = st.columns(2)
        st.session_state.customer = c1.text_input("Müşteri Adı *", st.session_state.customer, placeholder="Örn: Demo Enerji")
        st.session_state.sys_id = c2.text_input("Sistem Etiketi", st.session_state.sys_id)
        st.date_input("Tarih", datetime.now())
        st.markdown("</div>", unsafe_allow_html=True)

    st.markdown("###")
    # Doğrulama (Validation)
    if not st.session_state.customer:
        st.warning("Lütfen ilerlemek için müşteri adını giriniz.")
        st.button("İleri ➡️", disabled=True)
    else:
        st.button("Sonraki Adım: Veri Girişi ➡️", on_click=go_next, type="primary")

# ==========================================
# SAYFA 2: VERİ GİRİŞİ
# ==========================================
elif st.session_state.step == 2:
    st.subheader("⚙️ Adım 2: Teknik Veriler")
    
    c_water, c_sys = st.columns([2, 1])
    
    with c_water:
        st.markdown("##### 💧 Besi Suyu Analizi")
        st.markdown("<div style='background-color: white; padding: 20px; border-radius: 10px;'>", unsafe_allow_html=True)
        c1, c2, c3 = st.columns(3)
        st.session_state.ph = c1.number_input("pH", 0.0, 14.0, st.session_state.ph, step=0.1)
        st.session_state.cond = c1.number_input("İletkenlik (µS)", 0, 10000, st.session_state.cond)
        st.session_state.ca = c2.number_input("Ca Sertliği", 0, 2000, st.session_state.ca)
        st.session_state.mg = c2.number_input("Mg Sertliği", 0, 2000, st.session_state.mg)
        st.session_state.alk = c3.number_input("Alkalinite", 0, 2000, st.session_state.alk)
        st.session_state.sio2 = c3.number_input("Silis (SiO2)", 0, 200, st.session_state.sio2)
        st.session_state.so4 = c1.number_input("Sülfat (SO4)", 0, 5000, st.session_state.so4)
        st.session_state.cl = c2.number_input("Klorür (Cl)", 0, 5000, st.session_state.cl)
        st.markdown("</div>", unsafe_allow_html=True)

    with c_sys:
        st.markdown("##### ⚙️ Kule ve Limitler")
        st.markdown("<div style='background-color: white; padding: 20px; border-radius: 10px;'>", unsafe_allow_html=True)
        st.session_state.q_circ = st.number_input("Sirkülasyon (m3/h)", 10, 50000, st.session_state.q_circ)
        st.session_state.dt = st.number_input("Delta T (°C)", 1, 25, st.session_state.dt)
        st.session_state.t_out = st.number_input("Havuz Sıcaklığı (°C)", 10, 55, st.session_state.t_out)
        st.session_state.loss = st.number_input("Kaçaklar (m3/h)", 0.0, 50.0, st.session_state.loss, help="Sürüklenme, spray vb.")
        st.markdown("---")
        st.session_state.l_lsi = st.number_input("Limit LSI", 1.0, 3.5, st.session_state.l_lsi, step=0.1)
        st.markdown("</div>", unsafe_allow_html=True)

    st.markdown("###")
    col_b1, col_b2 = st.columns([1, 8])
    col_b1.button("⬅️ Geri", on_click=go_back)
    col_b2.button("Analizi Çalıştır ➡️", on_click=go_next, type="primary")

# ==========================================
# SAYFA 3: ANALİZ (GÖRSEL AĞIRLIKLI)
# ==========================================
elif st.session_state.step == 3:
    st.subheader(f"📊 Adım 3: {st.session_state.customer} - Analiz Raporu")
    
    # Simülasyon
    raw = {'CaH': st.session_state.ca, 'MgH': st.session_state.mg, 'Alk': st.session_state.alk, 'SiO2': st.session_state.sio2, 'pH': st.session_state.ph, 'Cond': st.session_state.cond, 'SO4': st.session_state.so4, 'Cl': st.session_state.cl}
    des = {'q_circ': st.session_state.q_circ, 'dt': st.session_state.dt, 't_out': st.session_state.t_out, 'proc_loss': st.session_state.loss, 'load': 100}
    const = {'max_LSI': st.session_state.l_lsi, 'max_SiO2': st.session_state.l_sio2, 'max_CaSO4': 2500000}
    
    final, hist = engine.run_simulation(raw, des, const)
    
    # Su Dengesi Hesabı
    evap = st.session_state.q_circ * st.session_state.dt * 0.00153
    blow = evap / (final['Cycle']-1) if final['Cycle']>1 else 0
    mu = evap + blow

    # --- GÖRSEL DÜZEN (SOL: KULE, SAĞ: SONUÇLAR) ---
    c_vis, c_res = st.columns([1.2, 2])
    
    with c_vis:
        st.markdown("##### Sistem Şeması")
        # Basit bir SVG/Statik görsel placeholder (İleride dinamik yapılabilir)
        # Buraya internetten bulduğun bir şemanın URL'sini veya lokal dosyanı koyabilirsin.
        st.image("https://raw.githubusercontent.com/sogutmakulesi/resimler/main/tower_schema_basic.png", caption="Soğutma Kulesi Kütle Dengesi", use_column_width=True)
        st.caption(f"Buharlaşma: {int(evap)} m3/h | Blöf: {int(blow)} m3/h | Besi: {int(mu)} m3/h")

    with c_res:
        st.markdown("##### Kritik Sonuçlar")
        # Özel styled metric kartları
        mc1, mc2, mc3 = st.columns(3)
        
        mc1.markdown(f"<div class='metric-card'><div class='metric-label'>Maksimum Döngü</div><div class='metric-value'>{final['Cycle']}x</div></div>", unsafe_allow_html=True)
        mc2.markdown(f"<div class='metric-card'><div class='metric-label'>Son LSI (Skin)</div><div class='metric-value'>{final['LSI']:.2f}</div></div>", unsafe_allow_html=True)
        mc3.markdown(f"<div class='metric-card'><div class='metric-label'>Son Silis (SiO2)</div><div class='metric-value'>{int(final['SiO2'])} ppm</div></div>", unsafe_allow_html=True)
        
        st.markdown("###")
        if final['Stop_Reason']:
            st.warning(f"🛑 **Sınırlayıcı Faktör:** {final['Stop_Reason']}")

        st.markdown("##### Su Karakteristiği Değişimi")
        # Tablo verisi
        df_c = pd.DataFrame([
            ["Ca Sertliği (ppm)", raw['CaH'], int(raw['CaH']*final['Cycle'])],
            ["Alkalinite (ppm)", raw['Alk'], int(raw['Alk']*final['Cycle'])],
            ["İletkenlik (µS)", raw['Cond'], int(raw['Cond']*final['Cycle'])]
        ], columns=["Parametre", "Besi Suyu", "Kule Suyu"])
        st.dataframe(df_c, hide_index=True, use_container_width=True)

    st.markdown("###")
    col_b1, col_b2 = st.columns([1, 8])
    col_b1.button("⬅️ Verileri Düzenle", on_click=go_back)
    col_b2.button("Ürün Seçimine Geç ➡️", on_click=go_next, type="primary")

# ==========================================
# SAYFA 4: REÇETE
# ==========================================
elif st.session_state.step == 4:
    st.subheader("💊 Adım 4: Şartlandırma Programı")
    
    st.info("💡 Ürün havuzu entegrasyonu bir sonraki aşamada yapılacaktır. Şuan manuel seçim aktiftir.")
    
    st.markdown("<div style='background-color: white; padding: 20px; border-radius: 10px;'>", unsafe_allow_html=True)
    c1, c2 = st.columns(2)
    
    c1.markdown("**Antiskalant Programı**")
    sel_anti = c1.selectbox("Ana Antiskalant", ["CHEM-100 (Std)", "CHEM-200 (Pro)"])
    
    c2.markdown("**Biyosit Programı**")
    sel_bio = c2.multiselect("Biyositler", ["BIO-ISO (Non-Ox)", "BIO-OX (Ox)"])
    
    st.markdown("</div>", unsafe_allow_html=True)

    st.markdown("###")
    col_b1, col_b2 = st.columns([1, 8])
    col_b1.button("⬅️ Analize Dön", on_click=go_back)
    if col_b2.button("✅ Projeyi Tamamla", type="primary"):
        st.balloons()
        st.success("Proje raporu hazırlandı.")
