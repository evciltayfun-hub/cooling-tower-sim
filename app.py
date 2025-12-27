import streamlit as st
import pandas as pd
import math
from datetime import datetime

# ==========================================
# AYARLAR (FRENCH CREEK TARZI)
# ==========================================
PRODUCT_DB = {
    "scale_std": {"code": "FC-100", "name": "Basic Phosphonate", "dose_ppm": 15, "price_usd": 2.2},
    "scale_adv": {"code": "FC-500", "name": "HEDP/Polymer Blend", "dose_ppm": 25, "price_usd": 3.5},
    "scale_pro": {"code": "FC-900", "name": "High Stress Polymer", "dose_ppm": 40, "price_usd": 5.5},
    "corr_zinc": {"code": "ZN-20", "name": "Zinc Based Inhibitor", "dose_ppm": 30, "price_usd": 3.0},
}

# ==========================================
# ENGINE (HESAPLAMA MOTORU)
# ==========================================
class FrenchCreekStyleEngine:
    def __init__(self):
        self.evap_factor = 0.00153 
        
    def get_log_k(self, temp_c):
        """Sıcaklığa bağlı denge sabitleri"""
        tk = temp_c + 273.15
        pk2 = 107.8871 + 0.03252849 * tk - 5151.79 / tk - 38.92561 * math.log10(tk) + 563713.9 / (tk**2)
        pksp = 171.9065 + 0.077993 * tk - 2839.319 / tk - 71.595 * math.log10(tk)
        return pk2, pksp

    def calculate_indices(self, w, t_c):
        """İndeks Hesapları"""
        # Hata koruması (Sıfıra bölünme riskine karşı +0.0001 eklemeleri)
        if w.get('CaH', 0) <= 0 or w.get('Alk', 0) <= 0: 
            return {"LSI": -99, "RSI": 99, "PSI": 99, "LarsonSkold": 0, "Ca_SO4": 0, "Mg_SiO2": 0, "Ca_PO4_Product": 0}

        TDS = w.get('TDS', w['Cond'] * 0.65)
        I = 2.5e-5 * TDS 
        
        # pHs Hesabı
        pk2, pksp = self.get_log_k(t_c)
        A = (math.log10(TDS + 1) - 1) / 10
        B = -13.12 * math.log10(t_c + 273) + 34.55
        C = math.log10(w['CaH'] + 0.1) - 0.4
        D = math.log10(w['Alk'] + 0.1)
        pHs = (9.3 + A + B) - (C + D)

        LSI = w['pH'] - pHs
        RSI = 2 * pHs - w['pH']
        
        pHeq = 1.465 * math.log10(w['Alk'] + 0.1) + 4.54
        PSI = 2 * pHs - pHeq

        # Fosfat İndeksi
        pt_risk = 0
        if w.get('oPO4', 0) > 0.1:
            pt_risk = w['CaH'] * w['oPO4']

        # Larson-Skold
        epm_Cl = w['Cl'] / 35.5
        epm_SO4 = w['SO4'] / 48.0
        epm_Alk = w['Alk'] / 50.0
        LS_Index = (epm_Cl + epm_SO4) / (epm_Alk + 0.001)

        return {
            "LSI": LSI, "RSI": RSI, "PSI": PSI, 
            "LarsonSkold": LS_Index, 
            "Ca_SO4": w['CaH'] * w['SO4'],
            "Mg_SiO2": w['MgH'] * w['SiO2'],
            "Ca_PO4_Product": pt_risk
        }

    def run_simulation(self, raw, des, const):
        cycle = 1.0
        history = []
        skin_temp = des['T_out'] + 15
        
        # Hidrolik Limit Hesabı
        losses = des['proc_loss'] + (des['q_circ'] * 0.0002)
        evap = des['q_circ'] * des['dt'] * self.evap_factor * (des['load']/100)
        
        if losses > 0:
            max_hydro_cycle = (evap + losses) / losses
        else:
            max_hydro_cycle = 50.0

        while True:
            # 1. Konsantrasyon
            curr = {}
            for k, v in raw.items():
                if k == 'pH': continue
                curr[k] = v * cycle
            
            # pH Tahmini
            if des['acid_ph']:
                curr['pH'] = des['acid_ph']
                curr['Alk'] = raw['Alk'] * cycle * 0.65 
            else:
                curr['pH'] = min(raw['pH'] + math.log10(cycle), 9.3)

            # TDS güncelle (önemli, yoksa I yanlış hesaplanır)
            curr['TDS'] = curr['Cond'] * 0.65

            # 2. İndeksler (Skin Temp)
            idx = self.calculate_indices(curr, skin_temp)
            
            # 3. Limit Kontrol
            stop = None
            
            if cycle >= max_hydro_cycle:
                stop = "Hidrolik Sınır (Su Kaybı)"
            elif curr['SiO2'] > const['max_SiO2']: 
                stop = f"Silis Limiti ({int(curr['SiO2'])} ppm)"
            elif idx['LSI'] > const['max_LSI']: 
                stop = f"LSI Limiti (+{idx['LSI']:.2f})"
            elif idx['Ca_SO4'] > const['max_CaSO4']:
                stop = "CaSO4 (Alçıtaşı) Riski"
            elif idx['Ca_PO4_Product'] > const['max_CaPO4']:
                stop = f"Ca-Fosfat Riski (Ürün: {int(idx['Ca_PO4_Product'])})"
            elif curr['pH'] > 8.8 and idx['Mg_SiO2'] > 40000:
                stop = "Magnezyum Silikat Riski"

            # *** DÜZELTME BURADA: Tüm indeksleri sözlüğe ekledik ***
            history.append({
                "Cycle": round(cycle, 1),
                "pH": round(curr['pH'], 2),
                "LSI": round(idx['LSI'], 2),
                "RSI": round(idx['RSI'], 2),
                "PSI": round(idx['PSI'], 2),
                "LarsonSkold": round(idx['LarsonSkold'], 2),  # <--- Eklendi
                "SiO2": round(curr['SiO2'], 1),
                "CaPO4_Prod": int(idx['Ca_PO4_Product']),
                "Stop_Reason": stop
            })

            if stop or cycle > 30.0:
                safe_idx = -2 if len(history) > 1 else -1
                return history[safe_idx], history, max_hydro_cycle
            
            cycle += 0.1

    def interpret_indices(self, vals):
        """Rapor yorumlayıcı"""
        # Hata koruması: get metodu ile güvenli çekim
        lsi = vals.get('LSI', 0)
        ls = vals.get('LarsonSkold', 0)
        
        interp = []
        # Scaling
        if lsi > 2.5: interp.append("🔴 SEVERE SCALING Potential (Ağır Kışır Riski)")
        elif lsi > 1.0: interp.append("🟠 Moderate Scaling (Orta Kışır)")
        elif lsi < 0: interp.append("🟡 Corrosive Tendency (Korozyon Eğilimi)")
        
        # Corrosion
        if ls > 3.0: interp.append("🔴 SEVERE PITTING Corrosion Likely (Şiddetli Oyulma)")
        elif ls > 1.0: interp.append("🟠 Pitting Tendency (Oyulma Eğilimi)")
        
        return interp

# ==========================================
# ARAYÜZ
# ==========================================
st.set_page_config(page_title="FC-Style Modeler V5.1", layout="wide", page_icon="🔬")
engine = FrenchCreekStyleEngine()

st.title("🔬 ProChem Modeling Suite (Stable V5.1)")
st.markdown("*French Creek Standartlarında İleri Seviye Su Şartlandırma Analizi*")

with st.sidebar:
    st.header("1. Make-up Water Chemistry")
    with st.expander("Cations (ppm)", expanded=True):
        ca = st.number_input("Calcium (as CaCO3)", 0, 5000, 80)
        mg = st.number_input("Magnesium (as CaCO3)", 0, 5000, 40)
        na = st.number_input("Sodium (as Na - Optional)", 0, 50000, 0)
    
    with st.expander("Anions (ppm)", expanded=True):
        alk = st.number_input("M-Alkalinity (as CaCO3)", 0, 5000, 100)
        cl = st.number_input("Chloride (as Cl)", 0, 20000, 50)
        so4 = st.number_input("Sulfate (as SO4)", 0, 10000, 40)
        sio2 = st.number_input("Silica (as SiO2)", 0, 500, 15)
        o_po4 = st.number_input("Ortho-Phosphate (as PO4)", 0.0, 50.0, 0.5)
    
    with st.expander("Physical", expanded=True):
        ph = st.number_input("pH", 0.0, 14.0, 7.8)
        cond = st.number_input("Conductivity (µS/cm)", 0, 50000, 600)

    st.header("2. System Parameters")
    q_circ = st.number_input("Recirculation Rate (m³/h)", 10, 50000, 1500)
    dt = st.number_input("Delta-T (°C)", 1, 30, 10)
    t_out = st.number_input("Basin Temp (°C)", 0, 60, 32)
    load = st.slider("Heat Load (%)", 10, 120, 100)
    loss = st.number_input("Unaccounted Losses (m³/h)", 0.0, 100.0, 0.0)

    st.header("3. Product & Limits")
    use_acid = st.checkbox("Acid Feed")
    acid_ph = st.number_input("Target pH", 6.0, 8.5, 7.5) if use_acid else None
    
    l_lsi = st.number_input("Limit LSI", 1.5, 3.2, 2.8)
    l_sio2 = st.number_input("Limit SiO2", 100, 300, 180)
    l_capo4 = st.number_input("Limit Ca x PO4", 100, 5000, 1200)
    
    run = st.button("RUN MODEL", type="primary")

if run or True:
    # Veri Paketleme
    raw = {'CaH': ca, 'MgH': mg, 'Na': na, 'Alk': alk, 'Cl': cl, 'SO4': so4, 'SiO2': sio2, 'oPO4': o_po4, 'pH': ph, 'Cond': cond}
    des = {'q_circ': q_circ, 'dt': dt, 't_out': t_out, 'load': load, 'proc_loss': loss, 'acid_ph': acid_ph}
    const = {'max_LSI': l_lsi, 'max_SiO2': l_sio2, 'max_CaSO4': 2500000, 'max_CaPO4': l_capo4}
    
    # Motoru Çalıştır
    final, hist, h_lim = engine.run_simulation(raw, des, const)
    
    # Su Dengesi
    evap = q_circ * dt * 0.00153 * (load/100)
    if final['Cycle'] > 1:
        blow = evap / (final['Cycle'] - 1)
    else:
        blow = 0 # Cycle 1 ise blöf sonsuzdur teorik olarak ama pratik gösterim için 0
        
    mu = evap + blow
    
    # --- RAPORLAMA ---
    st.subheader(f"📊 MODEL SUMMARY @ {final['Cycle']} Cycles")
    
    if final['Stop_Reason']:
        st.error(f"⚠️ LIMITING FACTOR: **{final['Stop_Reason']}**")
    
    k1, k2, k3, k4, k5 = st.columns(5)
    k1.metric("Cycles", f"{final['Cycle']}x")
    k2.metric("Make-up", f"{int(mu)} m³/h")
    k3.metric("Blowdown", f"{float(blow):.1f} m³/h")
    k4.metric("LSI (Skin)", f"{final['LSI']:.2f}")
    k5.metric("Larson-Skold", f"{final.get('LarsonSkold', 0):.2f}") # Güvenli gösterim
    
    st.markdown("---")

    c_left, c_right = st.columns([1, 1])
    
    with c_left:
        st.markdown("#### 🧪 Saturation Indices")
        interpretations = engine.interpret_indices(final)
        for i in interpretations:
            st.write(i)
            
        idx_data = {
            "Index": ["Langelier (LSI)", "Ryznar (RSI)", "Puckorius (PSI)", "Larson-Skold"],
            "Value": [final['LSI'], final['RSI'], final['PSI'], final.get('LarsonSkold', 0)],
            "Guide": ["< 2.8 w/ Polymer", "6.0 - 7.0 Stable", "> 6.0 Stable", "< 3.0 for SS304"]
        }
        st.table(pd.DataFrame(idx_data))

    with c_right:
        st.markdown("#### ⚠️ Mineral Limits")
        pct_sio2 = min(final['SiO2'] / const['max_SiO2'], 1.0)
        st.write(f"**Silica (SiO2):** {final['SiO2']} / {const['max_SiO2']} ppm")
        st.progress(pct_sio2)
        
        pct_capo4 = min(final['CaPO4_Prod'] / const['max_CaPO4'], 1.0)
        st.write(f"**Ca-Phosphate:** {final['CaPO4_Prod']} / {const['max_CaPO4']}")
        st.progress(pct_capo4)

    st.subheader("📈 Simulation Trajectory")
    df = pd.DataFrame(hist)
    st.line_chart(df, x="Cycle", y=["LSI", "RSI", "LarsonSkold"])
    
    with st.expander("View Full Data"):
        st.dataframe(df)
