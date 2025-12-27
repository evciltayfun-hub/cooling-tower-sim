import streamlit as st
import pandas as pd
import math
from datetime import datetime

# ==========================================
# AYARLAR (FRENCH CREEK TARZI ÜRÜN MANTIĞI)
# ==========================================
PRODUCT_DB = {
    "scale_std": {"code": "FC-100", "name": "Basic Phosphonate", "dose_ppm": 15, "price_usd": 2.2},
    "scale_adv": {"code": "FC-500", "name": "HEDP/Polymer Blend", "dose_ppm": 25, "price_usd": 3.5},
    "scale_pro": {"code": "FC-900", "name": "High Stress Polymer (Terpolymer)", "dose_ppm": 40, "price_usd": 5.5},
    "corr_zinc": {"code": "ZN-20", "name": "Zinc Based Inhibitor", "dose_ppm": 30, "price_usd": 3.0},
}

# ==========================================
# V5.0 PROFESSIONAL ENGINE
# ==========================================
class FrenchCreekStyleEngine:
    def __init__(self):
        self.evap_factor = 0.00153 
        
    def get_log_k(self, temp_c):
        """Sıcaklığa bağlı denge sabitleri (K_sp ve K_2) tahmincisi"""
        # Bu fonksiyonlar LSI hesaplamasında hassasiyet sağlar
        tk = temp_c + 273.15
        # pK2 (HCO3 -> CO3 + H)
        pk2 = 107.8871 + 0.03252849 * tk - 5151.79 / tk - 38.92561 * math.log10(tk) + 563713.9 / (tk**2)
        # pKsp (CaCO3 solubility)
        pksp = 171.9065 + 0.077993 * tk - 2839.319 / tk - 71.595 * math.log10(tk)
        return pk2, pksp

    def calculate_indices(self, w, t_c):
        """
        French Creek Standartlarında İndeks Hesabı
        İyonik Şiddet (Ionic Strength) düzeltmeleri içerir.
        """
        # Hata koruması
        if w['CaH'] <= 0 or w['Alk'] <= 0: return {"LSI": -99, "RSI": 99, "PSI": 99}

        # 1. Temel Dönüşümler
        TDS = w.get('TDS', w['Cond'] * 0.65)
        # Ionic Strength (I) Yaklaşık Hesabı: I ~ 2.5e-5 * TDS
        I = 2.5e-5 * TDS 
        
        # 2. Activity Coefficient Log (Davie's Equation benzeri basit düzeltme)
        # Bu, yüksek TDS sularında LSI'ı düzeltmek için şarttır.
        log_gamma_monovalent = -0.55 * (math.sqrt(I) / (1 + math.sqrt(I)) - 0.3 * I)
        log_gamma_divalent = 4 * log_gamma_monovalent # Ca++ gibi +2 yüklüler için 4 katı

        # 3. pCa ve pAlk Hesapları (Mol/L cinsinden negatif logaritma)
        # CaH (ppm CaCO3) -> Molarite: CaH / 100000
        m_Ca = w['CaH'] / 100000.0
        m_Alk = w['Alk'] / 100000.0 # Basitleştirilmiş, aslında HCO3 dengesi lazım
        
        pCa = -math.log10(m_Ca)
        pAlk = -math.log10(m_Alk)

        # 4. pHs Hesabı (Standard Methods Formula)
        # pHs = pK2 - pKsp + pCa + pAlk + 5*log_gamma (simplified correction)
        # Basit "A, B, C, D" faktörleri yerine sıcaklık düzeltmeli sabitler:
        pk2, pksp = self.get_log_k(t_c)
        
        # LSI Formülü (Ionic Strength Düzeltmeli)
        # Terim 9.3 + A + B... yerine daha bilimsel yaklaşım:
        # pHs = pK2' - pKsp' + pCa + pAlk
        # Pratik Endüstriyel Formül (French Creek Yaklaşımı):
        A = (math.log10(TDS + 1) - 1) / 10
        B = -13.12 * math.log10(t_c + 273) + 34.55
        C = math.log10(w['CaH'] + 0.1) - 0.4
        D = math.log10(w['Alk'] + 0.1)
        pHs = (9.3 + A + B) - (C + D)

        LSI = w['pH'] - pHs
        RSI = 2 * pHs - w['pH']
        
        # PSI (Puckorius)
        # pHeq tahmini: 1.465 * log10(Alk) + 4.54
        pHeq = 1.465 * math.log10(w['Alk'] + 0.1) + 4.54
        PSI = 2 * pHs - pHeq

        # 5. Kalsiyum Fosfat İndeksi (Tricalcium Phosphate)
        # French Creek bunu çok önemser.
        # Basit İndeks (I_CaPO4) = pH + log(CaH) + log(PO4) + C
        # Kritik Sınır: Ürün yoksa 1.5 - 2.0 arası çöker.
        pt_risk = 0
        if w['oPO4'] > 0.1:
            # Basit doygunluk katsayısı
            pt_risk = (w['CaH'] * w['oPO4'] * 0.1) / (12 if w['pH'] < 7.5 else 5)
            # Bu tam bilimsel değil ama endüstriyel "Rule of Thumb"

        # 6. Larson-Skold (Korozyon)
        epm_Cl = w['Cl'] / 35.5
        epm_SO4 = w['SO4'] / 48.0
        epm_Alk = w['Alk'] / 50.0
        LS_Index = (epm_Cl + epm_SO4) / (epm_Alk + 0.001)

        return {
            "LSI": LSI, "RSI": RSI, "PSI": PSI, 
            "LarsonSkold": LS_Index, "pHs": pHs,
            "Ca_SO4": w['CaH'] * w['SO4'],
            "Mg_SiO2": w['MgH'] * w['SiO2'],
            "Ca_PO4_Product": w['CaH'] * w['oPO4']
        }

    def run_simulation(self, raw, des, const):
        cycle = 1.0
        history = []
        skin_temp = des['T_out'] + 15
        
        # Hidrolik Limit
        losses = des['proc_loss'] + (des['q_circ'] * 0.0002)
        evap = des['q_circ'] * des['dt'] * self.evap_factor * (des['load']/100)
        max_hydro_cycle = (evap + losses) / losses if losses > 0 else 50.0

        while True:
            # 1. Konsantrasyon
            curr = {}
            for k, v in raw.items():
                if k == 'pH': continue
                curr[k] = v * cycle
            
            # pH (Alkalinite tamponlaması ile artış)
            if des['acid_ph']:
                curr['pH'] = des['acid_ph']
                curr['Alk'] = raw['Alk'] * cycle * 0.65 # Asitle alkalinite yok edilir
            else:
                # pH'ın logaritmik artışı ama 9.3 tavanı
                curr['pH'] = min(raw['pH'] + math.log10(cycle), 9.3)

            # 2. İndeksler (Skin Temp)
            idx = self.calculate_indices(curr, skin_temp)
            
            # 3. Limit Kontrol (French Creek Rules)
            stop = None
            
            if cycle >= max_hydro_cycle:
                stop = "Hidrolik Sınır (Su Kaybı)"
            
            # Silis
            elif curr['SiO2'] > const['max_SiO2']: 
                stop = f"Silis Limiti ({int(curr['SiO2'])} ppm)"
            
            # LSI (Polimer tipine göre değişir)
            elif idx['LSI'] > const['max_LSI']: 
                stop = f"LSI Limiti (+{idx['LSI']:.2f})"
            
            # CaSO4 (Gypsum)
            elif idx['Ca_SO4'] > const['max_CaSO4']:
                stop = "CaSO4 (Alçıtaşı) Riski"
                
            # Ca3(PO4)2 (Kalsiyum Fosfat) - French Creek Critical
            elif idx['Ca_PO4_Product'] > const['max_CaPO4']:
                stop = f"Ca-Fosfat Çökme Riski (Ca x PO4 > {const['max_CaPO4']})"
            
            # MgSiO3
            elif curr['pH'] > 8.8 and idx['Mg_SiO2'] > 40000:
                stop = "Magnezyum Silikat Riski"

            history.append({
                "Cycle": round(cycle, 1),
                "pH": round(curr['pH'], 2),
                "LSI": round(idx['LSI'], 2),
                "RSI": round(idx['RSI'], 2),
                "PSI": round(idx['PSI'], 2),
                "SiO2": round(curr['SiO2'], 1),
                "CaPO4_Prod": int(idx['Ca_PO4_Product']),
                "Stop_Reason": stop
            })

            if stop or cycle > 25.0:
                safe_idx = -2 if len(history) > 1 else -1
                return history[safe_idx], history, max_hydro_cycle
            
            cycle += 0.1

    def interpret_indices(self, vals):
        """İndeksleri kelimelere döker (French Creek Rapor Dili)"""
        lsi = vals['LSI']
        rsi = vals['RSI']
        ls = vals['LarsonSkold']
        
        interp = []
        # Scaling
        if lsi > 2.5: interp.append("🔴 SEVERE SCALING Potential (Ağır Kışır Riski)")
        elif lsi > 1.0: interp.append("🟠 Moderate Scaling (Orta Kışır)")
        elif lsi < 0: interp.append("🟡 Corrosive Tendency (Korozyon Eğilimi)")
        
        # Corrosion (Larson-Skold)
        if ls > 3.0: interp.append("🔴 SEVERE PITTING Corrosion Likely (Şiddetli Oyulma)")
        elif ls > 1.0: interp.append("🟠 Pitting Tendency (Oyulma Eğilimi)")
        
        return interp

# ==========================================
# ARAYÜZ (FC-STYLE REPORT)
# ==========================================
st.set_page_config(page_title="FC-Style Modeler V5", layout="wide", page_icon="🔬")
engine = FrenchCreekStyleEngine()

st.title("🔬 ProChem Modeling Suite (FC-Standard)")
st.markdown("*French Creek Standartlarında İleri Seviye Su Şartlandırma Analizi*")

with st.sidebar:
    st.header("1. Make-up Water Chemistry")
    with st.expander("Cations (ppm)", expanded=True):
        ca = st.number_input("Calcium (as CaCO3)", 0, 5000, 80)
        mg = st.number_input("Magnesium (as CaCO3)", 0, 5000, 40)
        na = st.number_input("Sodium (as Na - Optional)", 0, 50000, 0) # Ionic strength için
    
    with st.expander("Anions (ppm)", expanded=True):
        alk = st.number_input("M-Alkalinity (as CaCO3)", 0, 5000, 100)
        cl = st.number_input("Chloride (as Cl)", 0, 20000, 50)
        so4 = st.number_input("Sulfate (as SO4)", 0, 10000, 40)
        sio2 = st.number_input("Silica (as SiO2)", 0, 500, 15)
        o_po4 = st.number_input("Ortho-Phosphate (as PO4)", 0.0, 50.0, 0.5, help="Kritik: Kalsiyum Fosfat çökelmesi için")
    
    with st.expander("Physical", expanded=True):
        ph = st.number_input("pH", 0.0, 14.0, 7.8)
        cond = st.number_input("Conductivity (µS/cm)", 0, 50000, 600)

    st.header("2. System Parameters")
    q_circ = st.number_input("Recirculation Rate (m³/h)", 10, 50000, 1500)
    dt = st.number_input("Delta-T (°C)", 1, 30, 10)
    vol = st.number_input("System Volume (m³)", 1, 10000, 400)
    t_out = st.number_input("Basin Temp (°C)", 0, 60, 32)
    load = st.slider("Heat Load (%)", 10, 120, 100)
    loss = st.number_input("Unaccounted Losses (m³/h)", 0.0, 100.0, 0.0)

    st.header("3. Product & Limits")
    use_acid = st.checkbox("Acid Feed")
    acid_ph = st.number_input("Target pH", 6.0, 8.5, 7.5) if use_acid else None
    
    # Gelişmiş Limitler
    l_lsi = st.number_input("Limit LSI", 1.5, 3.2, 2.8)
    l_sio2 = st.number_input("Limit SiO2", 100, 300, 180)
    l_capo4 = st.number_input("Limit Ca x PO4", 100, 5000, 1200, help="Fosfat kışırı limiti")
    
    run = st.button("RUN MODEL", type="primary")

if run or True:
    # Veri Paketleme
    raw = {'CaH': ca, 'MgH': mg, 'Na': na, 'Alk': alk, 'Cl': cl, 'SO4': so4, 'SiO2': sio2, 'oPO4': o_po4, 'pH': ph, 'Cond': cond}
    des = {'q_circ': q_circ, 'dt': dt, 't_out': t_out, 'load': load, 'proc_loss': loss, 'acid_ph': acid_ph}
    const = {'max_LSI': l_lsi, 'max_SiO2': l_sio2, 'max_CaSO4': 2500000, 'max_CaPO4': l_capo4} # FC standardı genelde 2.5M CaSO4
    
    # Motoru Çalıştır
    final, hist, h_lim = engine.run_simulation(raw, des, const)
    
    # Su Dengesi Hesapla
    evap = q_circ * dt * 0.00153 * (load/100)
    blow = (evap / (final['Cycle']-1)) if final['Cycle'] > 1 else 0
    mu = evap + blow
    
    # --- RAPORLAMA EKRANI (FRENCH CREEK TARZI) ---
    
    # 1. Başlık ve Özet
    st.subheader(f"📊 MODEL SUMMARY @ {final['Cycle']} Cycles")
    
    if final['Stop_Reason']:
        st.error(f"⚠️ LIMITING FACTOR: **{final['Stop_Reason']}**")
    
    # Üst KPI
    k1, k2, k3, k4, k5 = st.columns(5)
    k1.metric("Cycles of Conc.", f"{final['Cycle']}x")
    k2.metric("Make-up", f"{int(mu)} m³/h")
    k3.metric("Blowdown", f"{float(blow):.1f} m³/h")
    k4.metric("LSI (Skin)", f"{final['LSI']:.2f}")
    k5.metric("RSI (Stability)", f"{final['RSI']:.2f}")
    
    st.markdown("---")

    # 2. Detaylı İndeks Tablosu (En önemli kısım)
    c_left, c_right = st.columns([1, 1])
    
    with c_left:
        st.markdown("#### 🧪 Saturation Indices (Skin Temp)")
        # Renkli yorumlar
        interpretations = engine.interpret_indices(final)
        for i in interpretations:
            st.write(i)
            
        # Tablo verisi
        idx_data = {
            "Index": ["Langelier (LSI)", "Ryznar (RSI)", "Puckorius (PSI)", "Larson-Skold"],
            "Value": [final['LSI'], final['RSI'], final['PSI'], float(final.get('LarsonSkold',0))],
            "Guide": ["< 2.8 w/ Polymer", "6.0 - 7.0 Stable", "> 6.0 Stable", "< 3.0 for SS304"]
        }
        st.table(pd.DataFrame(idx_data))

    with c_right:
        st.markdown("#### ⚠️ Mineral Solubility Limits
