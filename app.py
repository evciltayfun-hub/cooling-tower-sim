import streamlit as st
import pandas as pd
import math

# ==========================================
# AYARLAR VE ÜRÜN VERİTABANI (BURAYI KENDİNE GÖRE DÜZENLE)
# ==========================================

# Buradaki isimleri ve fiyatları kendi gerçek ürünlerinle değiştirebilirsin.
PRODUCT_DB = {
    "scale_std": {
        "code": "AQUASOL-100", 
        "name": "Standart Antiskalant", 
        "desc": "Düşük sertlik ve standart sular için ekonomik fosfonat.",
        "limit_LSI": 1.8,  # Bu LSI'a kadar bunu öner
        "dose_ppm": 20,
        "price_usd": 2.50  # kg fiyatı
    },
    "scale_pro": {
        "code": "AQUASOL-PRO", 
        "name": "Yüksek Performans Polimer", 
        "desc": "Yüksek silis ve sertlik içeren sular için kopolimer.",
        "limit_LSI": 2.8,  # LSI 1.8 ile 2.8 arasındaysa bunu öner
        "dose_ppm": 35,
        "price_usd": 4.20
    },
    "corrosion": {
        "code": "CORR-STOP 50", 
        "name": "Korozyon İnhibitörü", 
        "desc": "Yumuşak sular için çinko-fosfat bazlı koruyucu.",
        "limit_LSI": 0.0,  # LSI negatifse (korozifse) bunu öner
        "dose_ppm": 40,
        "price_usd": 3.80
    },
    "biocide": {
        "code": "BIO-SHOCK", 
        "name": "İsotiazolin Biyosit", 
        "desc": "Geniş spektrumlu bakteri kontrolü.",
        "dose_ppm": 100,   # Haftalık şok dozajı varsayımı
        "price_usd": 6.00
    }
}

# ==========================================
# HESAPLAMA MOTORU
# ==========================================

class TowerEngine:
    def __init__(self):
        self.evap_factor = 0.00153 
        self.drift_rate = 0.0002    

    def calculate_LSI(self, pH, temp_C, tds, ca_h, m_alk):
        if ca_h <= 0 or m_alk <= 0: return -99
        A = (math.log10(tds) - 1) / 10
        B = -13.12 * math.log10(temp_C + 273) + 34.55
        C = math.log10(ca_h) - 0.4
        D = math.log10(m_alk)
        pHs = (9.3 + A + B) - (C + D)
        return pH - pHs

    def select_product(self, lsi):
        """LSI değerine göre veritabanından en karlı ürünü seçer"""
        if lsi < 0:
            return PRODUCT_DB["corrosion"], "Su korozif yapıda, metal kaybı riski var."
        elif 0 <= lsi <= PRODUCT_DB["scale_std"]["limit_LSI"]:
            return PRODUCT_DB["scale_std"], "Standart kireçlenme eğilimi."
        elif lsi <= PRODUCT_DB["scale_pro"]["limit_LSI"]:
            return PRODUCT_DB["scale_pro"], "Yüksek kireçlenme potansiyeli. Polimer desteği şart."
        else:
            return None, "LSI limitleri aşıldı! Asit dozajı şart."

    def run_simulation(self, water, design, constraints):
        cycle = 1.0
        history = []
        skin_temp = design['T_out'] + 15
        
        while True:
            # Konsantrasyon
            curr_Ca = water['CaH'] * cycle
            curr_Alk = water['Alk'] * cycle
            curr_SiO2 = water['SiO2'] * cycle
            curr_TDS = water['TDS'] * cycle
            
            # pH Tahmini
            if design['acid_target_ph']:
                curr_pH = design['acid_target_ph']
                curr_Alk = curr_Alk * 0.75 # Asit alkaliniteyi düşürür
            else:
                curr_pH = min(water['pH'] + math.log10(cycle), 9.2)

            # LSI Hesapla (Skin Temperature)
            lsi_skin = self.calculate_LSI(curr_pH, skin_temp, curr_TDS, curr_Ca, curr_Alk)
            
            # Limit Kontrolü
            stop_reason = None
            if curr_SiO2 > constraints['max_SiO2']: stop_reason = "Silis (SiO2) Limiti"
            elif lsi_skin > constraints['max_LSI']: stop_reason = f"LSI Limiti ({lsi_skin:.2f})"
            elif curr_Ca > constraints['max_CaH']: stop_reason = "Kalsiyum Sertliği Limiti"
            
            history.append({
                "Cycle": round(cycle, 1), 
                "LSI": round(lsi_skin, 2), 
                "SiO2": round(curr_SiO2, 1),
                "pH": round(curr_pH, 2)
            })

            if stop_reason or cycle > 15.0:
                safe_cycle = max(1.0, round(cycle - 0.1, 1))
                # Son durum için ürün seçimi
                final_lsi = history[-2]['LSI'] if len(history)>1 else lsi_skin
                product, reason = self.select_product(final_lsi)
                
                return {
                    "Max_Cycle": safe_cycle,
                    "Stop_Reason": stop_reason if stop_reason else "Max Döngü",
                    "Final_LSI": final_lsi,
                    "Product": product,
                    "Tech_Note": reason,
                    "History": history
                }
            cycle += 0.1

    def calculate_balance(self, circ, dt, cycles):
        evap = circ * dt * self.evap_factor
        wind = circ * self.drift_rate
        if cycles <= 1: blow = 0
        else: blow = (evap - ((cycles - 1) * wind)) / (cycles - 1)
        makeup = evap + blow + wind
        return evap, blow, makeup

# ==========================================
# ARAYÜZ (FRONTEND)
# ==========================================

st.set_page_config(page_title="ChemTech Kule Uzmanı", layout="wide", page_icon="🏭")
engine = TowerEngine()

st.title("🏭 ChemTech - Akıllı Şartlandırma Simülatörü")

# --- SIDEBAR ---
with st.sidebar:
    st.header("💧 Besi Suyu Analizi")
    pH = st.number_input("pH", 6.0, 9.5, 7.8)
    cond = st.number_input("İletkenlik (µS/cm)", 10, 10000, 400)
    tds = st.number_input("TDS (mg/L)", 10, 8000, int(cond*0.65))
    ca = st.number_input("Ca Sertliği (ppm CaCO3)", 0, 2000, 150)
    alk = st.number_input("M-Alk (ppm CaCO3)", 0, 2000, 120)
    sio2 = st.number_input("Silis (SiO2 ppm)", 0, 200, 15)

    st.header("⚙️ Sistem Bilgileri")
    q_circ = st.number_input("Sirkülasyon (m3/h)", 10, 50000, 1000)
    dt = st.number_input("Delta T (°C)", 1, 30, 10)
    t_out = st.number_input("Havuz Sıcaklığı (°C)", 10, 60, 32)
    
    st.header("🧪 Opsiyonlar")
    use_acid = st.checkbox("Asit Dozajı")
    target_ph = st.slider("Hedef pH", 6.0, 8.5, 7.5) if use_acid else None
    
    calc_btn = st.button("SİMÜLASYONU BAŞLAT", type="primary")

# --- HESAPLAMA ---
if calc_btn or True:
    # Simülasyon
    res = engine.run_simulation(
        water={'pH': pH, 'TDS': tds, 'CaH': ca, 'Alk': alk, 'SiO2': sio2},
        design={'T_out': t_out, 'acid_target_ph': target_ph},
        constraints={'max_SiO2': 160, 'max_LSI': 2.9, 'max_CaH': 1200}
    )
    
    evap, blow, makeup = engine.calculate_balance(q_circ, dt, res['Max_Cycle'])
    
    # --- SEKMELER (TABS) ---
    tab1, tab2, tab3 = st.tabs(["📊 Simülasyon Özeti", "💰 Maliyet Analizi", "📈 Detay Grafikler"])

    with tab1:
        # KPI Kartları
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Maksimum Cycle", f"{res['Max_Cycle']}x")
        c2.metric("Blöf (Atık Su)", f"{float(blow):.1f} m³/h")
        c3.metric("Besi Suyu İhtiyacı", f"{int(
