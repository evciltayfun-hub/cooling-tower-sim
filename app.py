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
        cah = w.get('CaH', 0)
        alk = w.get('Alk', 0)
        
        if cah <= 0 or alk <= 0: 
            return {"LSI": -99, "RSI": 99, "PSI": 99, "LarsonSkold": 0, "Ca_SO4": 0, "Mg_SiO2": 0, "Ca_PO4_Product": 0}

        tds = w.get('TDS', w.get('Cond', 1000) * 0.65)
        
        # pHs Hesabı
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

        # Fosfat İndeksi
        pt_risk = 0
        opo4 = w.get('oPO4', 0)
        if opo4 > 0.1:
            pt_risk = cah * opo4

        # Larson-Skold
        epm_Cl = w.get('Cl', 0) / 35.5
        epm_SO4 = w.get('SO4', 0) / 48.0
        epm_Alk = alk / 50.0
        LS_Index = (epm_Cl + epm_SO4) / (epm_Alk + 0.001)

        return {
            "LSI": LSI, "RSI": RSI, "PSI": PSI, 
            "LarsonSkold": LS_Index, 
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
            if des.get('acid_ph'):
                curr['pH'] = des['acid_ph']
                curr['Alk'] = raw.get('Alk', 100) * cycle * 0.65 
            else:
                base_ph = raw.get('pH', 7.5)
                curr['pH'] = min(base_ph + math.log10(cycle), 9.3)

            curr['TDS'] = curr.get('Cond', 1000) * 0.65

            # 2. İndeksler
            idx = self.calculate_indices(curr, skin_temp)
            
            # 3. Limit Kontrol
            stop = None
            if cycle >= max_hydro_cycle: stop = "Hidrolik Sınır (Su Kaybı)"
            elif curr.get('SiO2', 0) > const['max_SiO2']: stop = f"Silis Limiti ({int(curr['SiO2'])} ppm)"
            elif idx['LSI'] > const['max_LSI']: stop = f"LSI Limiti (+{idx['LSI']:.2f})"
            elif idx['Ca_SO4'] > const['max_CaSO4']: stop = "CaSO4 (Alçıtaşı) Riski"
            elif idx['Ca_PO4_Product'] > const['max_CaPO4']: stop = f"Ca-Fosfat Riski"

            history.append({
                "Cycle": round(cycle, 1),
                "pH": round(curr['pH'], 2),
                "LSI": round(idx['LSI'], 2),
                "RSI": round(idx['RSI'], 2),
                "LarsonSkold": round(idx['LarsonSkold'], 2), 
                "SiO2": round(curr.get('SiO2', 0), 1),
                "Stop_Reason": stop
            })

            if stop or cycle > 30.0:
                safe_idx = -2 if len(history) > 1 else -1
                return history[safe_idx], history, max_hydro_cycle
            
            cycle += 0.1
    
    def interpret_indices(self, vals):
        lsi = vals.get('LSI', 0)
        ls = vals.get('LarsonSkold', 0)
        interp = []
        if lsi > 2.5: interp.append("🔴 SEVERE SCALING (Ağır Kışır)")
        elif lsi > 1.0: interp.append("🟠 Moderate Scaling (Orta Kışır)")
        elif lsi < 0: interp.append("🟡 Corrosive (Korozyon)")
        if ls > 3.0: interp.append("🔴 SEVERE PITTING (Oyulma)")
        return interp

# ==========================================
# ARAYÜZ (STREAMLIT)
# ==========================================
st.set_page_config(page_title="FC-Style Modeler V5.5", layout="wide", page_icon="🔬")
engine = FrenchCreekStyleEngine()

st.title("🔬 ProChem Modeling Suite (V5.5)")
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
    raw = {'CaH': ca, 'MgH': mg, 'Na': na, 'Alk': alk, 'Cl': cl, 'SO4': so4, 'SiO2': sio2, 'oPO4': o_po4, 'pH': ph, 'Cond': cond}
    des = {'q_circ': q_circ, 'dt': dt, 't_out': t_out, 'load': load, 'proc_loss': loss, 'acid_ph': acid_ph}
    const = {'max_LSI': l_lsi, 'max_SiO2': l_sio2, 'max_CaSO4': 2500000, 'max_CaPO4': l_capo4}
    
    # Simülasyon
    final, hist, h_lim = engine.run_simulation(raw, des, const)
    cycles = final['Cycle']
    
    # Su Dengesi
    evap = q_circ * dt * 0.00153 * (load/100)
    blow = evap / (cycles - 1) if cycles > 1 else 0
    mu = evap + blow
    
    # --- RAPORLAMA ---
    st.subheader(f"📊 MODEL SUMMARY @ {cycles} Cycles")
    if final['Stop_Reason']:
        st.error(f"⚠️ LIMITING FACTOR: **{final['Stop_Reason']}**")
    
    # KPI
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Cycles", f"{cycles}x")
    c2.metric("Makeup", f"{int(mu)} m³/h")
    c3.metric("Blowdown", f"{float(blow):.1f} m³/h")
    c4.metric("LSI (Skin)", f"{final['LSI']:.2f}")

    st.markdown("---")
    
    # --- YENİ EKLENEN KISIM: DETAYLI SU KARAKTERİSTİĞİ TABLOSU ---
    st.subheader("💧 Detailed Water Chemistry (Makeup vs Tower)")
    
    # Tablo verisini oluştur
    # İyonlar düz çarpılır, pH simülasyondan gelir
    chem_data = []
    
    # 1. pH ve İletkenlik (Özel Durumlar)
    chem_data.append(["pH", ph, final['pH'], "-"])
    chem_data.append(["Conductivity (µS/cm)", cond, int(cond * cycles), f"{cycles}x"])
    
    # 2. İyonlar (Döngü ile çarpılanlar)
    ions_to_show = [
        ("Calcium (CaH)", "ppm", raw['CaH']),
        ("Magnesium (MgH)", "ppm", raw['MgH']),
        ("M-Alkalinity", "ppm", raw['Alk']),
        ("Chloride (Cl)", "ppm", raw['Cl']),
        ("Sulfate (SO4)", "ppm", raw['SO4']),
        ("Silica (SiO2)", "ppm", raw['SiO2']),
        ("O-Phosphate", "ppm", raw['oPO4']),
        ("Sodium (Na)", "ppm", raw['Na'])
    ]
    
    for name, unit, val in ions_to_show:
        tower_val = val * cycles
        # Asit dozajı varsa Alkalinite düzeltmesi (Görsel amaçlı basit düzeltme)
        if name == "M-Alkalinity" and des['acid_ph']:
             tower_val = val * cycles * 0.65 # Tahmini nötrleşme
        
        chem_data.append([name, f"{val:.1f}", f"{tower_val:.1f}", f"{cycles}x"])

    # DataFrame Oluştur
    df_chem = pd.DataFrame(chem_data, columns=["Parameter", "Make-up", "Recirculation (Tower)", "Conc. Factor"])
    
    # Tabloyu Göster
    col_table, col_graph = st.columns([1, 1])
    
    with col_table:
        st.dataframe(df_chem, hide_index=True, use_container_width=True)
    
    with col_graph:
        st.markdown("#### 🧪 Saturation Indices")
        interp = engine.interpret_indices(final)
        for i in interp: st.write(i)
        
        idx_df = pd.DataFrame({
            "Index": ["Langelier (LSI)", "Ryznar (RSI)", "Larson-Skold"],
            "Value": [final['LSI'], final['RSI'], final.get('LarsonSkold', 0)]
        })
        st.table(idx_df)

    # Simülasyon Grafiği
    st.subheader("📈 Simulation Trend")
    st.line_chart(pd.DataFrame(hist), x="Cycle", y=["LSI", "RSI", "SiO2"])
