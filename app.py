import streamlit as st
import pandas as pd
import math

# ==========================================
# AYARLAR VE KİMYASAL VERİTABANI
# ==========================================
PRODUCT_DB = {
    "scale_std": {"code": "AQUASOL-100", "name": "Std. Antiskalant", "dose_ppm": 20, "price_usd": 2.5},
    "scale_pro": {"code": "AQUASOL-PRO", "name": "Yüksek Polimer", "dose_ppm": 35, "price_usd": 4.2},
    "corrosion": {"code": "CORR-STOP", "name": "Korozyon İnhibitörü", "dose_ppm": 40, "price_usd": 3.8},
}

# ==========================================
# PROFESYONEL HESAPLAMA MOTORU (V3.0)
# ==========================================
class ExpertTowerEngine:
    def __init__(self):
        self.evap_factor = 0.00153 
        self.drift_rate = 0.0002    

    def calculate_indices(self, water, temp_C):
        """
        Tüm kritik indeksleri hesaplar.
        """
        # Verileri çek (Hata almamak için 0.0001 ekleyerek sıfıra bölünmeyi önle)
        pH = water['pH']
        TDS = water['Cond'] * 0.65 # Tahmini TDS
        CaH = water['CaH']
        MgH = water['MgH'] # Mg Sertliği (CaCO3 cinsinden)
        Alk = water['Alk']
        SiO2 = water['SiO2']
        SO4 = water['SO4']
        Cl = water['Cl']
        
        # 1. LSI (Langelier) Hesabı
        if CaH <= 0 or Alk <= 0: return {}
        
        A = (math.log10(TDS + 0.1) - 1) / 10
        B = -13.12 * math.log10(temp_C + 273) + 34.55
        C = math.log10(CaH + 0.1) - 0.4
        D = math.log10(Alk + 0.1)
        pHs = (9.3 + A + B) - (C + D)
        LSI = pH - pHs
        
        # 2. PSI (Puckorius Scaling Index) = 2pHs - pH_eq (Basit yaklaşım: 2pHs - pH)
        # Ryznar (2pHs - pH) ile benzer mantıkta kullanılır.
        RSI = 2 * pHs - pH 
        
        # 3. Larson-Skold Index (Korozyon)
        # Formül: (epm Cl + epm SO4) / epm Alk
        # Eşdeğer Ağırlıklar: Cl:35.5, SO4:48, CaCO3:50
        epm_Cl = Cl / 35.5
        epm_SO4 = SO4 / 48.0
        epm_Alk = Alk / 50.0
        
        if epm_Alk > 0:
            LarsonSkold = (epm_Cl + epm_SO4) / epm_Alk
        else:
            LarsonSkold = 99.0 # Hata durumu

        # 4. Limit Çarpımları
        # Ca x SO4 (Limit genelde 1.250.000 - 2.000.000 arasıdır polimerle)
        # Not: Ca sertlik (CaCO3) cinsinden değil, Ca iyonu cinsinden gerekebilir ama 
        # endüstriyel pratiklerde genelde CaCO3 * ppm SO4 kullanılır.
        # Biz güvenli tarafta kalmak için Ca(as CaCO3) kullanıyoruz.
        Ca_SO4_Product = CaH * SO4
        
        # Mg x SiO2 (Magnezyum Silikat)
        # pH > 8.5 ise risk başlar.
        Mg_SiO2_Product = MgH * SiO2

        return {
            "LSI": LSI,
            "RSI": RSI,
            "LarsonSkold": LarsonSkold,
            "Ca_SO4": Ca_SO4_Product,
            "Mg_SiO2": Mg_SiO2_Product,
            "pHs": pHs
        }

    def run_simulation(self, raw_water, design, constraints):
        cycle = 1.0
        history = []
        skin_temp = design['T_out'] + 15 
        
        while True:
            # 1. Konsantrasyon (Linear Artış)
            curr = {}
            for ion, val in raw_water.items():
                if ion == 'pH': continue # pH logaritmik değişir
                curr[ion] = val * cycle
            
            # pH Tahmini (Döngü ile artar ama 9.0-9.2 civarında doyuma ulaşır)
            if design['acid_target_ph']:
                curr['pH'] = design['acid_target_ph']
                curr['Alk'] = raw_water['Alk'] * cycle * 0.7 # Asit alkaliniteyi yok eder
            else:
                # Doğal pH yükselmesi simülasyonu
                curr['pH'] = min(raw_water['pH'] + math.log10(cycle), 9.3)

            # 2. İndeks Hesapla (Skin Temperature'da)
            indices = self.calculate_indices(curr, skin_temp)
            
            # 3. LIMIT KONTROLÜ (Görseldeki limitlere göre)
            stop_reason = None
            
            # A. Silis Limiti
            if curr['SiO2'] > constraints['max_SiO2']: 
                stop_reason = f"Silis Limiti ({int(curr['SiO2'])} > {constraints['max_SiO2']})"
            
            # B. LSI Limiti
            elif indices['LSI'] > constraints['max_LSI']: 
                stop_reason = f"LSI Limiti (Skin LSI: {indices['LSI']:.2f})"
            
            # C. Ca x SO4 Limiti (Alçıtaşı)
            elif indices['Ca_SO4'] > constraints['max_CaSO4']:
                stop_reason = f"Ca x SO4 Limiti ({int(indices['Ca_SO4'])} > {constraints['max_CaSO4']})"
                
            # D. Mg x SiO2 Limiti (Sadece pH > 8.5 ise aktiftir)
            elif curr['pH'] > 8.5 and indices['Mg_SiO2'] > constraints['max_MgSiO2']:
                stop_reason = f"Mg x SiO2 Limiti ({int(indices['Mg_SiO2'])} > {constraints['max_MgSiO2']})"
            
            # Veriyi kaydet
            history.append({
                "Cycle": round(cycle, 1),
                "pH": round(curr['pH'], 2),
                "LSI": round(indices['LSI'], 2),
                "SiO2": round(curr['SiO2'], 1),
                "Ca_SO4": int(indices['Ca_SO4']),
                "LarsonSkold": round(indices['LarsonSkold'], 2),
                "Stop_Reason": stop_reason
            })

            # Döngüyü Kır
            if stop_reason or cycle > 20.0:
                # Güvenli bir önceki cycle'ı al
                safe_idx = -2 if len(history) > 1 else -1
                safe_data = history[safe_idx]
                
                return {
                    "Max_Cycle": safe_data['Cycle'],
                    "Stop_Reason": stop_reason if stop_reason else "Max Döngü (20x)",
                    "Final_Values": safe_data,
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
st.set_page_config(page_title="ProWater Simulator V3", layout="wide", page_icon="🧪")
engine = ExpertTowerEngine()

st.title("🧪 Soğutma Kulesi Limit Analizi (V3.0)")

# --- INPUT SIDEBAR (Görseldeki sıraya göre) ---
with st.sidebar:
    st.header("1. Detaylı Su Analizi (Make-up)")
    
    with st.expander("Temel İyonlar", expanded=True):
        pH = st.number_input("pH", 0.0, 14.0, 7.8, step=0.1)
        cond = st.number_input("İletkenlik (µS/cm)", 0, 50000, 530)
        alk = st.number_input("Total Alk (ppm CaCO3)", 0, 5000, 88)
        ca_h = st.number_input("Ca Sertliği (ppm CaCO3)", 0, 5000, 64)
        mg_h = st.number_input("Mg Sertliği (ppm CaCO3)", 0, 5000, 30)
        # Total Hardness otomatik gösterilebilir ama input istemişsin
        th_calc = ca_h + mg_h
        st.caption(f"Hesaplanan Toplam Sertlik: {th_calc} ppm")
    
    with st.expander("Anyonlar & Diğerleri", expanded=True):
        so4 = st.number_input("Sülfat (ppm SO4)", 0, 10000, 28)
        cl = st.number_input("Klorür (ppm Cl)", 0, 20000, 45)
        sio2 = st.number_input("Silis (ppm SiO2)", 0, 500, 10) # Görselde 1.0 ama risk görmek için 10 yaptım
        fe = st.number_input("Demir (ppm Fe)", 0.0, 50.0, 0.0)
        # Diğer metaller hesaplamada limiter değil ama kayıt için eklenebilir
    
    st.header("2. Sistem Limitleri (Constraints)")
    with st.expander("Limit Ayarları", expanded=False):
        lim_sio2 = st.number_input("Max Silis (ppm)", 100, 300, 175)
        lim_lsi = st.number_input("Max LSI (Skin)", 1.0, 3.5, 2.8)
        lim_caso4 = st.number_input("Max Ca x SO4", 500000, 5000000, 1250000)
        lim_mgsio2 = st.number_input("Max Mg x SiO2", 10000, 100000, 35000)
        
    st.header("3. Operasyonel")
    q_circ = st.number_input("Sirkülasyon (m3/h)", 0, 100000, 1000)
    dt = st.number_input("Delta T (°C)", 1, 30, 10)
    t_out = st.number_input("Havuz Sıcaklığı (°C)", 0, 60, 35)
    
    use_acid = st.checkbox("Asit Dozajı (pH Kontrol)")
    target_ph = st.number_input("Hedef pH", 6.0, 9.0, 7.8) if use_acid else None
    
    btn_calc = st.button("ANALİZ ET", type="primary")

if btn_calc or True:
    # Simülasyon Veri Paketi
    water_data = {
        'pH': pH, 'Cond': cond, 'Alk': alk, 'CaH': ca_h, 'MgH': mg_h,
        'SO4': so4, 'Cl': cl, 'SiO2': sio2
    }
    constraints = {
        'max_SiO2': lim_sio2, 'max_LSI': lim_lsi, 
        'max_CaSO4': lim_caso4, 'max_MgSiO2': lim_mgsio2
    }
    
    res = engine.run_simulation(water_data, {'T_out': t_out, 'acid_target_ph': target_ph}, constraints)
    evap, blow, makeup = engine.calculate_balance(q_circ, dt, res['Max_Cycle'])
    
    # --- SONUÇ EKRANI ---
    st.subheader(f"🏁 Analiz Sonucu: {res['Max_Cycle']} Cycle")
    
    if res['Stop_Reason'] != "Max Döngü (20x)":
        st.error(f"🛑 DURMA NEDENİ: **{res['Stop_Reason']}**")
    else:
        st.success("Sistem hidrolik sınıra kadar (20x) güvenli.")

    # KPI Sütunları
    k1, k2, k3, k4 = st.columns(4)
    final_vals = res['Final_Values']
    
    k1.metric("Besi Suyu", f"{int(makeup)} m³/h")
    k2.metric("Blöf", f"{float(blow):.2f} m³/h")
    k3.metric("Son Silis", f"{final_vals['SiO2']} ppm", delta=f"{constraints['max_SiO2']-final_vals['SiO2']:.0f} boşluk")
    k4.metric("Son LSI", f"{final_vals['LSI']}", delta_color="inverse")

    # --- DETAYLI TABLOLAR ---
    t1, t2 = st.tabs(["📉 Limiter Grafikleri", "📋 Veri Dökümü"])
    
    df = pd.DataFrame(res['History'])
    
    with t1:
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("**Kireçlenme Limitleri**")
            st.line_chart(df, x="Cycle", y=["LSI", "SiO2"])
        with c2:
            st.markdown("**Korozyon & Tuz Limitleri**")
            st.line_chart(df, x="Cycle", y=["LarsonSkold"])
            st.info(f"Larson-Skold Endeksi: **{final_vals['LarsonSkold']}** " + 
                    ("⚠️ (Korozyon Riski Yüksek)" if final_vals['LarsonSkold'] > 3.0 else "✅ (Güvenli)"))

    with t2:
        st.dataframe(df.style.highlight_max(axis=0, color="#ffcdd2"))
