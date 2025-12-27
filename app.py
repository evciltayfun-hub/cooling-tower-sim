import streamlit as st
import pandas as pd
import math
from datetime import datetime

# ==========================================
# AYARLAR VE KİMYASAL VERİTABANI
# ==========================================
PRODUCT_DB = {
    "scale_std": {"code": "AQUASOL-100", "name": "Std. Antiskalant", "dose_ppm": 20, "price_usd": 2.5},
    "scale_pro": {"code": "AQUASOL-PRO", "name": "Yüksek Polimer", "dose_ppm": 35, "price_usd": 4.2},
    "corrosion": {"code": "CORR-STOP", "name": "Korozyon İnhibitörü", "dose_ppm": 40, "price_usd": 3.8},
}

# ==========================================
# V4.0 MASTER ENGINE (HESAPLAMA MOTORU)
# ==========================================
class MasterEngine:
    def __init__(self):
        # Termodinamik Sabit (1 kcal buharlaşma ısısı üzerinden)
        self.evap_factor = 0.00153 
        self.drift_rate_default = 0.0002    

    def calculate_indices(self, water, temp_C):
        """ Kritik İndeks Hesaplayıcı """
        pH = water['pH']
        TDS = water.get('TDS', water['Cond'] * 0.65)
        CaH = water['CaH']
        MgH = water['MgH']
        Alk = water['Alk']
        SiO2 = water['SiO2']
        SO4 = water['SO4']
        Cl = water['Cl']
        
        # Hata önleyici
        if CaH <= 0 or Alk <= 0: return {"LSI": -99, "PSI": -99}
        
        # 1. LSI (Langelier)
        A = (math.log10(TDS + 0.1) - 1) / 10
        B = -13.12 * math.log10(temp_C + 273) + 34.55
        C = math.log10(CaH + 0.1) - 0.4
        D = math.log10(Alk + 0.1)
        pHs = (9.3 + A + B) - (C + D)
        LSI = pH - pHs
        
        # 2. PSI (Puckorius Scaling Index)
        # PSI = 2pHs - pH_eq (Burada pH_eq yerine pratik olarak pH kullanıyoruz, literatüre göre değişebilir)
        # Daha hassas formül: pH_eq = 1.465 * log10(Alk) + 4.54
        pHeq = 1.465 * math.log10(Alk + 0.1) + 4.54
        PSI = 2 * pHs - pHeq

        # 3. Larson-Skold (Korozyon)
        epm_Cl = Cl / 35.5
        epm_SO4 = SO4 / 48.0
        epm_Alk = Alk / 50.0
        LarsonSkold = (epm_Cl + epm_SO4) / (epm_Alk + 0.001)

        # 4. Limit Çarpımları
        Ca_SO4 = CaH * SO4
        Mg_SiO2 = MgH * SiO2

        return {
            "LSI": LSI, "PSI": PSI, "LarsonSkold": LarsonSkold,
            "Ca_SO4": Ca_SO4, "Mg_SiO2": Mg_SiO2, "pHs": pHs
        }

    def run_simulation(self, raw_water, design, constraints):
        cycle = 1.0
        history = []
        skin_temp = design['T_out'] + 15 # Yüzey sıcaklığı (Skin)
        
        # Hidrolik Kontrol: Kaçaklar yüzünden ulaşılabilir maksimum cycle nedir?
        # Formül: Max_Cycle = (Evap + Loss) / Loss
        # Eğer sistemde 0 blöf yapsan bile kaçaklar (loss) tuzluluğu atar.
        evap_rate = design['q_circ'] * design['dt'] * self.evap_factor * (design['load_percent']/100)
        total_uncontrolled_loss = design['process_loss'] + (design['q_circ'] * 0.0002) # Kaçak + Sürüklenme
        
        if total_uncontrolled_loss > 0:
            hydraulic_max_cycle = (evap_rate + total_uncontrolled_loss) / total_uncontrolled_loss
        else:
            hydraulic_max_cycle = 50.0 # Teorik sonsuz

        while True:
            # 1. Konsantrasyon
            curr = {}
            # İyonları Cycle ile çarp
            for ion, val in raw_water.items():
                if ion in ['pH']: continue
                curr[ion] = val * cycle
            
            # pH Tahmini
            if design['acid_target_ph']:
                curr['pH'] = design['acid_target_ph']
                curr['Alk'] = raw_water['Alk'] * cycle * 0.7 
            else:
                curr['pH'] = min(raw_water['pH'] + math.log10(cycle), 9.3)

            # 2. İndeksler (Skin Temp)
            idx = self.calculate_indices(curr, skin_temp)
            
            # 3. DURDURMA MANTIĞI (LIMITERS)
            stop_reason = None
            
            if cycle >= hydraulic_max_cycle:
                stop_reason = f"Hidrolik Sınır (Kaçaklar nedeniyle Max Cycle: {hydraulic_max_cycle:.1f})"
            
            elif curr['SiO2'] > constraints['max_SiO2']: 
                stop_reason = f"Silis Limiti ({int(curr['SiO2'])} > {constraints['max_SiO2']})"
            
            elif idx['LSI'] > constraints['max_LSI']: 
                stop_reason = f"LSI Limiti (Skin LSI: {idx['LSI']:.2f})"
            
            elif idx['Ca_SO4'] > constraints['max_CaSO4']:
                stop_reason = f"Ca x SO4 Limiti (Alçıtaşı Riski)"
            
            elif curr['pH'] > 8.5 and idx['Mg_SiO2'] > constraints['max_MgSiO2']:
                stop_reason = f"Mg x SiO2 Limiti (Magnezyum Silikat)"
            
            # Kayıt
            history.append({
                "Cycle": round(cycle, 1),
                "pH": round(curr['pH'], 2),
                "LSI": round(idx['LSI'], 2),
                "PSI": round(idx['PSI'], 2),
                "SiO2": round(curr['SiO2'], 1),
                "Stop_Reason": stop_reason
            })

            if stop_reason or cycle > 20.0:
                safe_idx = -2 if len(history) > 1 else -1
                safe_data = history[safe_idx]
                return {
                    "Max_Cycle": safe_data['Cycle'],
                    "Stop_Reason": stop_reason if stop_reason else "Max Döngü (20x)",
                    "Final_Values": safe_data,
                    "History": history,
                    "Hydraulic_Limit": hydraulic_max_cycle
                }
            cycle += 0.1

    def calculate_dynamics(self, circ, dt, cycles, vol, load_pct, proc_loss):
        """ Su Dengesi ve Zamanlama (HTI) Hesapları """
        # 1. Yük Faktörü ile Buharlaşma
        evap = circ * dt * self.evap_factor * (load_pct / 100.0)
        
        # 2. Kayıplar
        windage = circ * 0.0002 # %0.02 Drift
        
        # 3. Blöf Hesabı (M = E + B_tot) => B_tot = E / (C-1)
        # B_tot = Controlled_Blowdown + Windage + Process_Loss
        if cycles <= 1: 
            total_blowdown_needed = 0
            makeup = evap # Kabaca
        else:
            total_blowdown_needed = evap / (cycles - 1)
            makeup = evap + total_blowdown_needed
            
        # Kontrollü Blöf (Vana ile atılan)
        controlled_blowdown = total_blowdown_needed - windage - proc_loss
        if controlled_blowdown < 0: controlled_blowdown = 0 # Hidrolik limit durumu
        
        total_water_loss = evap + controlled_blowdown + windage + proc_loss # Makeup'a eşit
        
        # 4. HTI ve Half-Life
        # Retention Time (Alıkonma) = V / (Total Blowdown + Windage + Loss) -> Buharlaşma hariç!
        liquid_loss = controlled_blowdown + windage + proc_loss
        
        if liquid_loss > 0:
            retention_time_hr = vol / liquid_loss
            half_life_hr = 0.693 * retention_time_hr # HTI
            turnover_hr = retention_time_hr # 1 turnover
        else:
            retention_time_hr = 999
            half_life_hr = 999
            turnover_hr = 999
            
        return {
            "Evap": evap,
            "Makeup": makeup,
            "Controlled_Blowdown": controlled_blowdown,
            "Total_Liquid_Loss": liquid_loss,
            "HTI_HalfLife": half_life_hr,
            "Retention_Time": retention_time_hr
        }

# ==========================================
# ARAYÜZ (FRONTEND)
# ==========================================
st.set_page_config(page_title="ProCool Master V4", layout="wide", page_icon="🏭")
engine = MasterEngine()

# --- CSS ---
st.markdown("""
<style>
    .big-font {font-size:20px !important; font-weight: bold;}
    .report-header {background-color: #f0f2f6; padding: 10px; border-radius: 5px; margin-bottom: 20px;}
</style>
""", unsafe_allow_html=True)

# --- HEADER (PROJE BİLGİLERİ) ---
with st.container():
    c1, c2, c3 = st.columns(3)
    with c1: st.title("🏭 Soğutma Kulesi Uzmanı")
    with c2: st.text_input("Müşteri / Firma Adı", "Demo Kimya A.Ş.")
    with c3: st.date_input("Tarih", datetime.now())

st.markdown("---")

# --- SIDEBAR (INPUTS) ---
with st.sidebar:
    st.header("1. Sistem Tasarım Bilgileri")
    q_circ = st.number_input("Sirkülasyon (m³/h)", 10, 50000, 1200)
    dt = st.number_input("Delta T (°C)", 1, 30, 10)
    vol = st.number_input("Sistem Hacmi (m³)", 1, 10000, 350, help="HTI hesabı için gereklidir")
    
    with st.expander("⚙️ Operasyonel Kayıplar & Yük", expanded=False):
        load_pct = st.slider("Service Load (%)", 10, 120, 100, help="Kulenin çalışma yükü")
        proc_loss = st.number_input("Kaçaklar / Proses Kaybı (m³/h)", 0.0, 500.0, 0.0, help="Spray losses, leakages etc.")
        t_out = st.number_input("Havuz Sıcaklığı (°C)", 0, 60, 32)

    st.header("2. Besi Suyu Analizi")
    with st.expander("Anyon & Katyonlar", expanded=True):
        pH = st.number_input("pH", 0.0, 14.0, 7.8)
        cond = st.number_input("İletkenlik (µS/cm)", 0, 50000, 530)
        alk = st.number_input("M-Alk (ppm CaCO3)", 0, 5000, 88)
        ca_h = st.number_input("Ca Sertliği (ppm CaCO3)", 0, 5000, 64)
        mg_h = st.number_input("Mg Sertliği (ppm CaCO3)", 0, 5000, 30)
        so4 = st.number_input("Sülfat (ppm SO4)", 0, 10000, 28)
        cl = st.number_input("Klorür (ppm Cl)", 0, 20000, 45)
        sio2 = st.number_input("Silis (ppm SiO2)", 0, 500, 10)
    
    with st.expander("Metaller & Diğerleri", expanded=False):
        fe = st.number_input("Demir (Fe ppm)", 0.0, 50.0, 0.0)
        mn = st.number_input("Mangan (Mn ppm)", 0.0, 50.0, 0.0)
        cu = st.number_input("Bakır (Cu ppm)", 0.0, 10.0, 0.0)
        po4 = st.number_input("Fosfat (PO4 ppm)", 0.0, 100.0, 0.0)

    st.header("3. Kısıtlamalar (Limiters)")
    with st.expander("Limit Ayarları", expanded=False):
        lim_sio2 = st.number_input("Max Silis", 100, 250, 175)
        lim_lsi = st.number_input("Max LSI", 1.0, 3.2, 2.8)
        lim_caso4 = st.number_input("Max Ca x SO4", 500000, 4000000, 1250000)
        lim_psi = st.number_input("Min PSI (Scaling)", 3.0, 6.0, 4.5, help="Düşük PSI kireçlenme demektir")

    use_acid = st.checkbox("Asit Dozajı")
    target_ph = st.number_input("Hedef pH", 5.0, 9.0, 7.5) if use_acid else None
    
    btn_calc = st.button("HESAPLA VE RAPORLA", type="primary")

# --- ANA EKRAN ---
if btn_calc or True:
    # 1. Simülasyon
    water_data = {'pH': pH, 'Cond': cond, 'Alk': alk, 'CaH': ca_h, 'MgH': mg_h, 'SO4': so4, 'Cl': cl, 'SiO2': sio2, 'TDS': cond*0.65}
    constraints = {'max_SiO2': lim_sio2, 'max_LSI': lim_lsi, 'max_CaSO4': lim_caso4, 'max_MgSiO2': 35000}
    design_data = {'T_out': t_out, 'acid_target_ph': target_ph, 'q_circ': q_circ, 'dt': dt, 'load_percent': load_pct, 'process_loss': proc_loss}
    
    res = engine.run_simulation(water_data, design_data, constraints)
    
    # 2. Dinamik Su Dengesi ve HTI
    dyn = engine.calculate_dynamics(q_circ, dt, res['Max_Cycle'], vol, load_pct, proc_loss)
    
    # --- SONUÇ PANELLERİ ---
    
    # KPI SECTION
    st.subheader("🎯 Simülasyon Sonuçları")
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Maksimum Cycle", f"{res['Max_Cycle']}x")
    k2.metric("HTI (Half-Life)", f"{dyn['HTI_HalfLife']:.1f} Saat", help="Sisteme giren kimyasalın %50'sinin atılması için geçen süre")
    k3.metric("Besi Suyu (Makeup)", f"{int(dyn['Makeup'])} m³/h")
    k4.metric("Toplam Blöf", f"{dyn['Total_Liquid_Loss']:.2f} m³/h")

    if res['Stop_Reason'] != "Max Döngü (20x)":
        st.error(f"🛑 **Sınırlayıcı Faktör:** {res['Stop_Reason']}")
    
    # SEKMELER
    tab1, tab2, tab3 = st.tabs(["📊 Sistem Analizi", "💧 Su Dengesi Detayı", "🧪 Kule Suyu Tahmini"])
    
    with tab1:
        col1, col2 = st.columns([2, 1])
        with col1:
            st.markdown("#### Limiter Grafiği")
            df_hist = pd.DataFrame(res['History'])
            st.line_chart(df_hist, x="Cycle", y=["LSI", "SiO2", "PSI"])
        with col2:
            st.markdown("#### Kritik İndeksler (Son Durum)")
            last = res['Final_Values']
            st.write(f"**LSI:** {last['LSI']} (Max {constraints['max_LSI']})")
            st.write(f"**PSI:** {last['PSI']}")
            st.write(f"**Silis:** {last['SiO2']} ppm")
            st.progress(min(last['SiO2'] / constraints['max_SiO2'], 1.0))

    with tab2:
        st.markdown("#### 🌊 Detaylı Su Kayıp Analizi")
        b1, b2, b3 = st.columns(3)
        b1.info(f"**Buharlaşma:** {dyn['Evap']:.1f} m³/h\n*(Saf su kaybı)*")
        b2.warning(f"**Kontrollü Blöf:** {dyn['Controlled_Blowdown']:.2f} m³/h\n*(Otomasyon ile atılan)*")
        b3.error(f"**Kaçak & Sürüklenme:** {proc_loss + (q_circ*0.0002):.2f} m³/h\n*(İstenmeyen kayıp)*")
        
        st.caption(f"Sistem Hacmi: {vol} m³ | Servis Yükü: %{load_pct}")
        if dyn['Controlled_Blowdown'] == 0:
            st.warning("⚠️ DİKKAT: Sistemdeki kaçaklar (Proses/Sürüklenme) o kadar yüksek ki, vana açmaya gerek kalmadan sistem dengeleniyor. Bu durum kimyasal kontrolünü zorlaştırır.")

    with tab3:
        st.markdown("#### 🧪 Konsantre Kule Suyu (Tahmini)")
        # Son cycle'daki iyonları göster
        final_ions = {k: v * res['Max_Cycle'] for k, v in water_data.items() if k != 'pH'}
        final_ions['pH'] = last['pH']
        final_ions['Fe'] = fe * res['Max_Cycle'] # Demir de konsantre olur
        
        df_ions = pd.DataFrame([final_ions]).T
        df_ions.columns = ["Konsantrasyon (ppm)"]
        st.dataframe(df_ions.style.format("{:.1f}"))
