import streamlit as st
import pandas as pd
import math
from datetime import datetime

# ==========================================
# 0. AYARLAR & ÜRÜN HAVUZU (Mock Data)
# ==========================================
# İleride buraya senin gerçek Excel listeni gömeceğiz.
PRODUCT_CATALOG = {
    "Antiskalantlar": [
        {"code": "CHEM-100", "name": "Basic Phosphonate", "type": "Std", "desc": "Düşük sertlik için ekonomik"},
        {"code": "CHEM-200", "name": "High Performance Polymer", "type": "Pro", "desc": "Yüksek LSI ve Silis için"},
        {"code": "CHEM-300", "name": "Acid Resistant Polymer", "type": "Acid", "desc": "Asitli sistemler için"}
    ],
    "Korozyon_Inh": [
        {"code": "CORR-ZN", "name": "Zinc Inhibitor", "type": "Zn", "desc": "Çinko bazlı"},
        {"code": "CORR-ORG", "name": "Organic Inhibitor", "type": "Org", "desc": "Fosfat/Organik bazlı"}
    ],
    "Biyositler": [
        {"code": "BIO-ISO", "name": "Isothiazolin", "type": "Non-Ox", "desc": "Genel koruma"},
        {"code": "BIO-OX", "name": "Oxidizing Biocide", "type": "Ox", "desc": "Güçlü dezenfeksiyon"}
    ]
}

# ==========================================
# 1. HESAPLAMA MOTORU (FRENCH CREEK STYLE)
# ==========================================
class FrenchCreekStyleEngine:
    def __init__(self):
        self.evap_factor = 0.00153 
        
    def get_log_k(self, temp_c):
        tk = temp_c + 273.15
        pk2 = 107.8871 + 0.03252849 * tk - 5151.79 / tk - 38.92561 * math.log10(tk) + 563713.9 / (tk**2)
        pksp = 171.9065 + 0.077993 * tk - 2839.319 / tk - 71.595 * math.log10(tk)
        return pk2, pksp

    def calculate_indices(self, w, t_c):
        cah = w.get('CaH', 0)
        alk = w.get('Alk', 0)
        if cah <= 0 or alk <= 0: 
            return {"LSI": -99, "RSI": 99, "PSI": 99, "LarsonSkold": 0, "Ca_SO4": 0, "Mg_SiO2": 0, "Ca_PO4_Product": 0}

        tds = w.get('TDS', w.get('Cond', 1000) * 0.65)
        pk2, pksp = self.get_log_k(t_c)
        A = (math.log10(tds + 1) - 1) / 10
        B = -13.12 * math.log10(t_c + 273) + 34.55
        C = math.log10(cah + 0.1) - 0.4
        D = math.log10(alk + 0.1)
        pHs = (9.3 + A + B) - (C + D)

        ph = w.get('pH', 7.0)
        LSI = ph - pHs
        RSI = 2 * pHs - ph
        pHeq = 1.465 * math.log10(alk + 0.1) + 4.54
        PSI = 2 * pHs - pHeq

        pt_risk = 0
        opo4 = w.get('oPO4', 0)
        if opo4 > 0.1: pt_risk = cah * opo4

        epm_Cl = w.get('Cl', 0) / 35.5
        epm_SO4 = w.get('SO4', 0) / 48.0
        epm_Alk = alk / 50.0
        LS_Index = (epm_Cl + epm_SO4) / (epm_Alk + 0.001)

        return {
            "LSI": LSI, "RSI": RSI, "PSI": PSI, "LarsonSkold": LS_Index, 
            "Ca_SO4": cah * w.get('SO4', 0),
            "Mg_SiO2": w.get('MgH', 0) * w.get('SiO2', 0),
            "Ca_PO4_Product": pt_risk
        }

    def run_simulation(self, raw, des, const):
        cycle = 1.0
        history = []
        skin_temp = des.get('t_out', 32) + 15
        losses = des.get('proc_loss', 0) + (des.get('q_circ', 1000) * 0.0002)
        evap = des.get('q_circ', 1000) * des.get('dt', 10) * self.evap_factor * (des.get('load', 100)/100)
        
        max_hydro_cycle = (evap + losses) / losses if losses > 0 else 50.0

        while True:
            curr = {}
            for k, v in raw.items():
                if k == 'pH': continue
                curr[k] = v * cycle
            
            if des.get('acid_ph'):
                curr['pH'] = des['acid_ph']
                curr['Alk'] = raw.get('Alk', 100) * cycle * 0.65 
            else:
                base_ph = raw.get('pH', 7.5)
                curr['pH'] = min(base_ph + math.log10(cycle), 9.3)

            curr['TDS'] = curr.get('Cond', 1000) * 0.65
            idx = self.calculate_indices(curr, skin_temp)
            
            stop = None
            if cycle >= max_hydro_cycle: stop = "Hidrolik Sınır (Su Kaybı)"
            elif curr.get('SiO2', 0) > const['max_SiO2']: stop = f"Silis Limiti"
            elif idx['LSI'] > const['max_LSI']: stop = f"LSI Limiti"
            elif idx['Ca_SO4'] > const['max_CaSO4']: stop = "CaSO4 (Alçıtaşı) Riski"
            elif idx['Ca_PO4_Product'] > const['max_CaPO4']: stop = f"Ca-Fosfat Riski"

            history.append({
                "Cycle": round(cycle, 1), "pH": round(curr['pH'], 2),
                "LSI": round(idx['LSI'], 2), "SiO2": round(curr.get('SiO2', 0), 1),
                "Stop_Reason": stop
            })

            if stop or cycle > 30.0:
                safe_idx = -2 if len(history) > 1 else -1
                return history[safe_idx], history
            cycle += 0.1

    def interpret_indices(self, lsi):
        if lsi > 2.0: return "Yüksek Kışır Riski (Polimer Şart)"
        elif lsi > 0: return "Hafif Kışır Eğilimi"
        else: return "Korozyon Riski"

# ==========================================
# 2. UYGULAMA MANTIĞI & STATE YÖNETİMİ
# ==========================================
st.set_page_config(page_title="ProChem Wizard V6", layout="wide", page_icon="🧪")
engine = FrenchCreekStyleEngine()

# Session State Başlatma (Hafıza)
if 'step' not in st.session_state: st.session_state.step = 1
# Varsayılan Değerler (Sayfalar arası kaybolmasın diye)
defaults = {
    'customer': 'Demo Firma', 'loc': 'İstanbul', 'sys_id': 'Kule-1', 
    'ca': 80, 'mg': 40, 'alk': 100, 'cl': 50, 'so4': 40, 'sio2': 10, 'ph': 7.8, 'cond': 600, 'po4': 0.0,
    'q_circ': 1500, 'dt': 10, 't_out': 32, 'load': 100, 'loss': 0.0,
    'l_lsi': 2.8, 'l_sio2': 180, 'selected_products': []
}
for k, v in defaults.items():
    if k not in st.session_state: st.session_state[k] = v

# Navigasyon Fonksiyonları
def go_next(): st.session_state.step += 1
def go_back(): st.session_state.step -= 1
def go_step(i): st.session_state.step = i

# --- SIDEBAR NAVİGASYON ---
with st.sidebar:
    st.title("🧪 Proje Sihirbazı")
    st.markdown("---")
    
    # Adımları Buton Gibi Göster
    steps = {1: "📝 Proje Bilgileri", 2: "⚙️ Teknik Veriler", 3: "📊 Analiz Sonuçları", 4: "💊 Ürün Seçimi"}
    
    current = st.session_state.step
    for i, label in steps.items():
        if i == current:
            st.info(f"**{label}** (Aktif)")
        else:
            # Sadece geçmiş adımlara tıklanabilir yapalım (Validation için)
            if st.button(label, key=f"nav_{i}", disabled=(i > current + 1)):
                go_step(i)
                st.rerun()

# ==========================================
# SAYFA 1: PROJE BİLGİLERİ
# ==========================================
if st.session_state.step == 1:
    st.header("📝 Adım 1: Yeni Proje Oluştur")
    st.markdown("---")
    
    c1, c2 = st.columns(2)
    with c1:
        st.session_state.customer = st.text_input("Müşteri / Firma Adı", st.session_state.customer)
        st.session_state.sys_id = st.text_input("Sistem ID / Etiket", st.session_state.sys_id)
    with c2:
        st.session_state.loc = st.text_input("Lokasyon / Fabrika", st.session_state.loc)
        st.date_input("Proje Tarihi", datetime.now())

    st.markdown("###")
    st.button("Sonraki Adım: Teknik Veriler ➡️", on_click=go_next, type="primary")

# ==========================================
# SAYFA 2: TEKNİK VERİLER
# ==========================================
elif st.session_state.step == 2:
    st.header("⚙️ Adım 2: Su Analizi ve Kule Tasarımı")
    st.markdown("---")
    
    tab_water, tab_sys, tab_lim = st.tabs(["Su Analizi (Makeup)", "Kule Sistemi", "Limitler"])
    
    with tab_water:
        c1, c2, c3 = st.columns(3)
        with c1:
            st.session_state.ph = st.number_input("pH", 0.0, 14.0, st.session_state.ph)
            st.session_state.cond = st.number_input("İletkenlik (µS)", 0, 50000, st.session_state.cond)
        with c2:
            st.session_state.ca = st.number_input("Ca Sertliği", 0, 5000, st.session_state.ca)
            st.session_state.mg = st.number_input("Mg Sertliği", 0, 5000, st.session_state.mg)
            st.session_state.alk = st.number_input("M-Alkalinite", 0, 5000, st.session_state.alk)
        with c3:
            st.session_state.cl = st.number_input("Klorür", 0, 10000, st.session_state.cl)
            st.session_state.so4 = st.number_input("Sülfat", 0, 10000, st.session_state.so4)
            st.session_state.sio2 = st.number_input("Silis", 0, 500, st.session_state.sio2)
            st.session_state.po4 = st.number_input("Orto-Fosfat", 0.0, 50.0, st.session_state.po4)

    with tab_sys:
        c1, c2 = st.columns(2)
        with c1:
            st.session_state.q_circ = st.number_input("Sirkülasyon (m3/h)", 10, 50000, st.session_state.q_circ)
            st.session_state.dt = st.number_input("Delta T (°C)", 1, 30, st.session_state.dt)
        with c2:
            st.session_state.t_out = st.number_input("Havuz Sıcaklığı (°C)", 0, 60, st.session_state.t_out)
            st.session_state.loss = st.number_input("Kaçaklar (m3/h)", 0.0, 100.0, st.session_state.loss)

    with tab_lim:
        st.session_state.l_lsi = st.number_input("Max LSI", 1.0, 3.5, st.session_state.l_lsi)
        st.session_state.l_sio2 = st.number_input("Max Silis", 50, 300, st.session_state.l_sio2)

    st.markdown("###")
    c_back, c_next = st.columns([1, 5])
    c_back.button("⬅️ Geri", on_click=go_back)
    c_next.button("Analizi Çalıştır ➡️", on_click=go_next, type="primary")

# ==========================================
# SAYFA 3: ANALİZ SONUÇLARI
# ==========================================
elif st.session_state.step == 3:
    st.header("📊 Adım 3: Simülasyon Sonuçları")
    st.markdown("---")
    
    # --- SİMÜLASYONU ARKA PLANDA ÇALIŞTIR ---
    raw = {'CaH': st.session_state.ca, 'MgH': st.session_state.mg, 'Alk': st.session_state.alk, 
           'Cl': st.session_state.cl, 'SO4': st.session_state.so4, 'SiO2': st.session_state.sio2, 
           'oPO4': st.session_state.po4, 'pH': st.session_state.ph, 'Cond': st.session_state.cond}
    des = {'q_circ': st.session_state.q_circ, 'dt': st.session_state.dt, 
           't_out': st.session_state.t_out, 'proc_loss': st.session_state.loss, 'load': 100}
    const = {'max_LSI': st.session_state.l_lsi, 'max_SiO2': st.session_state.l_sio2, 
             'max_CaSO4': 2500000, 'max_CaPO4': 1200}
    
    final, hist = engine.run_simulation(raw, des, const)
    
    # State'e kaydet (4. adımda kullanmak için)
    st.session_state.final_res = final
    st.session_state.sim_hist = hist
    
    # --- GÖRSELLEŞTİRME ---
    if final['Stop_Reason']:
        st.warning(f"⚠️ Sınırlandırıcı Faktör: **{final['Stop_Reason']}**")
    else:
        st.success("Sistem Maksimum Hidrolik Limite Ulaştı!")

    k1, k2, k3 = st.columns(3)
    k1.metric("Maksimum Cycle", f"{final['Cycle']}x")
    k2.metric("Son LSI", f"{final['LSI']:.2f}")
    k3.metric("Son Silis", f"{final['SiO2']} ppm")

    st.subheader("💧 Detaylı Su Karakteristiği (Önce/Sonra)")
    # Data Hazırlığı
    chem_data = []
    ions = [("CaH", raw['CaH']), ("MgH", raw['MgH']), ("Alk", raw['Alk']), ("Cl", raw['Cl']), ("SiO2", raw['SiO2'])]
    for name, val in ions:
        chem_data.append([name, val, val * final['Cycle']])
    
    df_chem = pd.DataFrame(chem_data, columns=["Parametre", "Besi Suyu", "Kule Suyu"])
    st.table(df_chem)

    st.markdown("###")
    c_back, c_next = st.columns([1, 5])
    c_back.button("⬅️ Verileri Düzenle", on_click=go_back)
    c_next.button("Ürün Seçimine Geç ➡️", on_click=go_next, type="primary")

# ==========================================
# SAYFA 4: ÜRÜN SEÇİMİ (REÇETE)
# ==========================================
elif st.session_state.step == 4:
    st.header("💊 Adım 4: Kimyasal Şartlandırma Reçetesi")
    st.markdown("---")
    
    res = st.session_state.final_res
    
    # 1. OTOMATİK ÖNERİ MOTORU
    st.subheader("🤖 Sistem Önerisi")
    
    rec_text = ""
    rec_type = ""
    
    if res['LSI'] > 2.0:
        rec_type = "Pro"
        rec_text = f"Sistemde **Yüksek Kışır (LSI: {res['LSI']:.2f})** riski var. Yüksek performanslı polimer/kopolimer kullanılmalı."
        st.error(rec_text)
    elif res['LSI'] < 0:
        rec_type = "Zn"
        rec_text = "Sistem **Korozif** karakterde. Çinko veya güçlü korozyon inhibitörü şart."
        st.warning(rec_text)
    else:
        rec_type = "Std"
        rec_text = "Sistem standart aralıkta. Fosfonat bazlı ürünler yeterli olabilir."
        st.success(rec_text)

    # 2. ÜRÜN LİSTESİNDEN SEÇİM
    st.subheader("📋 Ürün Havuzundan Seçim Yap")
    
    c1, c2 = st.columns(2)
    
    with c1:
        st.markdown("**Antiskalant Seçimi**")
        # Listeyi filtrele (Öneri tipine göre default seçimi ayarla)
        opts_anti = [p['name'] for p in PRODUCT_CATALOG['Antiskalantlar']]
        sel_anti = st.selectbox("Antiskalant", opts_anti, index=1 if rec_type=="Pro" else 0)
        
        st.markdown("**Biyosit Seçimi**")
        opts_bio = [p['name'] for p in PRODUCT_CATALOG['Biyositler']]
        sel_bio = st.multiselect("Biyosit Programı", opts_bio, default=[opts_bio[0]])

    with c2:
        st.markdown("**Korozyon İnhibitörü**")
        opts_corr = [p['name'] for p in PRODUCT_CATALOG['Korozyon_Inh']]
        sel_corr = st.selectbox("İnhibitör (Opsiyonel)", ["Yok"] + opts_corr)
        
        # Seçilen ürünlerin detayı
        st.info("💡 **Seçilen Paket Özeti:**\n" + 
                f"- Antiskalant: {sel_anti}\n" + 
                f"- Biyositler: {', '.join(sel_bio)}")

    # 3. FİNAL BUTONLARI
    st.markdown("---")
    c_back, c_finish = st.columns([1, 5])
    c_back.button("⬅️ Geri Dön", on_click=go_back)
    
    if c_finish.button("✅ Projeyi Tamamla ve Raporla", type="primary"):
        st.balloons()
        st.success(f"Tebrikler! {st.session_state.customer} projesi başarıyla oluşturuldu.")
        st.json({
            "Müşteri": st.session_state.customer,
            "Max Cycle": res['Cycle'],
            "Seçilen Ürünler": [sel_anti, sel_bio, sel_corr]
        })
