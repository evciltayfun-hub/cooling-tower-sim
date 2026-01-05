import streamlit as st
import pandas as pd
import math

# ==========================================
# BÖLÜM 1: MÜHENDİSLİK MOTORU (BACKEND)
# ==========================================

class TowerEngine:
    def __init__(self):
        # Fiziksel Sabitler
        self.evap_factor = 0.00153 
        self.drift_rate = 0.0002    

        # Ürün Veritabanı (Basitleştirilmiş)
        self.products = {
            "corrosion": {"name": "CORR-GUARD 500", "desc": "Çinko bazlı korozyon önleyici", "dose": 40},
            "scale_std": {"name": "SCALE-X 100", "desc": "Standart fosfonat antiskalant", "dose": 20},
            "scale_pro": {"name": "POLY-MAX 200", "desc": "Yüksek polimerli antiskalant", "dose": 35},
            "bio_std":   {"name": "BIO-CIDE 30", "desc": "Oksitleyici olmayan biyosit", "dose": 100}
        }

    def validate_inputs(self, data):
        """Kullanıcı hatalarını ve mantıksız girişleri yakalar."""
        warnings = []
        if data['Cond'] > 0 and data['TDS'] > data['Cond']:
            warnings.append("⚠️ Uyarı: TDS genelde İletkenlikten küçük olmalıdır.")
        if data['pH'] > 9.5:
            warnings.append("⚠️ Uyarı: Besi suyu pH'ı çok yüksek (>9.5). Ölçüm hatası olabilir.")
        return warnings

    def calculate_LSI(self, pH, temp_C, tds, ca_h, m_alk):
        """Skin Temperature düzeltmeli LSI Hesabı"""
        if ca_h <= 0 or m_alk <= 0: return -99
        
        A = (math.log10(tds) - 1) / 10
        B = -13.12 * math.log10(temp_C + 273) + 34.55
        C = math.log10(ca_h) - 0.4
        D = math.log10(m_alk)
        
        pHs = (9.3 + A + B) - (C + D)
        return pH - pHs

    def recommend_product(self, lsi, cycle):
        """LSI değerine ve Cycle'a göre kimyasal önerir."""
        if lsi < 0:
            return self.products["corrosion"], "Su korozif eğilimde."
        elif 0 <= lsi < 1.8:
            return self.products["scale_std"], "Standart kireç riski."
        elif 1.8 <= lsi < 2.8:
            return self.products["scale_pro"], "Yüksek kireç potansiyeli (Polimer şart)."
        else:
            return None, "LSI çok yüksek! Asit dozajı şart veya Cycle düşürülmeli."

    def run_simulation(self, water, design, constraints):
        cycle = 1.0
        history = []
        skin_temp = design['T_out'] + 15 # Yüzey sıcaklığı tahmini
        
        while True:
            # 1. Konsantrasyon
            curr_Ca = water['CaH'] * cycle
            curr_Alk = water['Alk'] * cycle
            curr_SiO2 = water['SiO2'] * cycle
            curr_TDS = water['TDS'] * cycle
            
            # Asit/pH Ayarı
            if design['acid_target_ph']:
                curr_pH = design['acid_target_ph']
                curr_Alk = curr_Alk * 0.7 # Asit alkaliniteyi düşürür (basit model)
            else:
                curr_pH = min(water['pH'] + math.log10(cycle), 9.2)

            # 2. İndeksler (Critical = Skin Temp)
            lsi_skin = self.calculate_LSI(curr_pH, skin_temp, curr_TDS, curr_Ca, curr_Alk)
            
            # 3. Limit Kontrol
            stop_reason = None
            if curr_SiO2 > constraints['max_SiO2']: stop_reason = "Silis Limiti"
            elif lsi_skin > constraints['max_LSI']: stop_reason = f"LSI Limiti (Skin: {lsi_skin:.2f})"
            elif curr_Ca > constraints['max_CaH']: stop_reason = "Kalsiyum Sertliği Limiti"
            
            history.append({
                "Cycle": round(cycle, 1), 
                "LSI": round(lsi_skin, 2), 
                "SiO2": round(curr_SiO2, 1),
                "pH": round(curr_pH, 2)
            })

            if stop_reason or cycle > 12.0:
                # Son geçerli cycle'a geri dön (bir önceki adım güvenliydi)
                safe_cycle = max(1.0, round(cycle - 0.1, 1))
                # Sonuç paketi hazırla
                chem, reason = self.recommend_product(history[-2]['LSI'] if len(history)>1 else lsi_skin, safe_cycle)
                
                return {
                    "Max_Cycle": safe_cycle,
                    "Stop_Reason": stop_reason if stop_reason else "Maksimum Döngü Sınırı",
                    "Final_LSI": history[-2]['LSI'] if len(history)>1 else lsi_skin,
                    "Chemical": chem,
                    "Chem_Reason": reason,
                    "History": history
                }
            
            cycle += 0.1

    def calculate_water_balance(self, circulation, delta_t, cycles):
        evap = circulation * delta_t * self.evap_factor
        windage = circulation * self.drift_rate
        if cycles <= 1: blowdown = 0
        else: blowdown = (evap - ((cycles - 1) * windage)) / (cycles - 1)
        makeup = evap + blowdown + windage
        return evap, blowdown, makeup

# ==========================================
# BÖLÜM 2: GÖRSEL ARAYÜZ (FRONTEND)
# ==========================================

st.set_page_config(page_title="ProCool Tower Sim", layout="wide")
engine = TowerEngine()

# --- CSS Stilleri (Görsellik için) ---
st.markdown("""
<style>
    .metric-card {background-color: #f0f2f6; padding: 15px; border-radius: 10px; border-left: 5px solid #2e86c1;}
    .risk-high {color: #e74c3c; font-weight: bold;}
    .risk-ok {color: #27ae60; font-weight: bold;}
</style>
""", unsafe_allow_html=True)

st.title("🏭 Akıllı Soğutma Kulesi Simülatörü")
st.markdown("Su analizi ve tasarım verilerine göre **otomatik şartlandırma ve blöf rejimi** belirler.")

# --- SIDEBAR (GİRİŞLER) ---
with st.sidebar:
    st.header("1. Su Analizi")
    pH = st.number_input("pH", 6.0, 9.5, 7.8)
    cond = st.number_input("İletkenlik (µS/cm)", 10, 5000, 400)
    tds = st.number_input("TDS (mg/L)", 10, 4000, int(cond*0.65))
    ca = st.number_input("Ca Sertliği (ppm CaCO3)", 0, 1000, 150)
    alk = st.number_input("M-Alkalinite (ppm CaCO3)", 0, 1000, 120)
    sio2 = st.number_input("Silis (SiO2 ppm)", 0, 150, 15)

    st.header("2. Kule Tasarımı")
    q_circ = st.number_input("Sirkülasyon (m3/h)", 10, 50000, 1000)
    dt = st.number_input("Delta T (°C)", 1, 30, 10)
    t_out = st.number_input("Havuz Suyu Sıcaklığı (°C)", 10, 60, 32)
    
    st.header("3. Operasyon")
    use_acid = st.checkbox("Asit Dozajı Var")
    target_ph = st.slider("Hedef pH", 6.5, 8.2, 7.5) if use_acid else None
    
    st.markdown("---")
    if st.button("HESAPLA", type="primary"):
        run_calc = True
    else:
        run_calc = False

# --- ANA EKRAN ---

if run_calc or True: # İlk açılışta çalışsın
    # 1. Hata Kontrolü
    warnings = engine.validate_inputs({'pH': pH, 'Cond': cond, 'TDS': tds})
    for w in warnings:
        st.warning(w)

    # 2. Simülasyonu Çalıştır
    res = engine.run_simulation(
        water={'pH': pH, 'TDS': tds, 'CaH': ca, 'Alk': alk, 'SiO2': sio2},
        design={'T_out': t_out, 'acid_target_ph': target_ph},
        constraints={'max_SiO2': 150, 'max_LSI': 2.8, 'max_CaH': 1200}
    )

    # 3. Su Dengesi Hesabı
    evap, blow, makeup = engine.calculate_water_balance(q_circ, dt, res['Max_Cycle'])

    # --- SONUÇ PANELİ ---
    
    # Görsel Renk Belirleme (Cycle ve Riske göre)
    color = "#3498db" # Mavi (Güvenli)
    if res['Final_LSI'] > 2.0: color = "#f1c40f" # Sarı (Dikkat)
    if res['Stop_Reason'] != "Maksimum Döngü Sınırı": color = "#e74c3c" # Kırmızı (Limit)

    # Üst KPI Kartları
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Maksimum Cycle", f"{res['Max_Cycle']}x")
    with col2:
        st.metric("Tüketim (Besi Suyu)", f"{int(makeup)} m³/h")
    with col3:
        st.metric("Blöf Miktarı", f"{float(blow):.2f} m³/h")
    with col4:
        st.metric("Kritik LSI (Skin)", f"{res['Final_LSI']:.2f}")

    # Detaylı Analiz
    c1, c2 = st.columns([2, 1])
    
    with c1:
        st.subheader("🔍 Simülasyon Grafiği")
        df_hist = pd.DataFrame(res['History'])
        st.line_chart(df_hist, x="Cycle", y=["LSI", "SiO2"])
        
        st.info(f"**Durma Nedeni:** Sistem **{res['Stop_Reason']}** sebebiyle durduruldu.")

    with c2:
        st.subheader("🧪 Kimyasal Önerisi")
        if res['Chemical']:
            st.success(f"**Önerilen:** {res['Chemical']['name']}")
            st.write(f"_{res['Chemical']['desc']}_")
            st.write(f"**Neden:** {res['Chem_Reason']}")
            st.write(f"**Dozaj:** {res['Chemical']['dose']} ppm")
            
            # Günlük Tüketim Hesabı
            daily_cons = (makeup * res['Chemical']['dose'] * 24) / 1000
            st.write(f"**Günlük:** {daily_cons:.1f} kg/gün")
        else:
            st.error("Uygun ürün bulunamadı. Şartlar çok ağır.")

    # --- GÖRSEL TEMSİL (SVG) ---
    st.subheader("Visual Twin")
    
    # Basit bir SVG Kule Çizimi (Dinamik Renkli)
    svg_code = f"""
    <svg width="400" height="300" xmlns="http://www.w3.org/2000/svg">
     <rect x="100" y="50" width="150" height="200" fill="#ddd" stroke="#555" stroke-width="3"/>
     <rect x="105" y="150" width="140" height="95" fill="{color}" opacity="0.8">
       <animate attributeName="height" from="90" to="95" dur="2s" repeatCount="indefinite" />
     </rect>
     <circle cx="175" cy="50" r="20" fill="#555" />
     <line x1="50" y1="200" x2="100" y2="200" stroke="#2980b9" stroke-width="5" marker-end="url(#arrow)" />
     <text x="10" y="195" font-family="Arial" font-size="12">Makeup: {int(makeup)}</text>
     
     <line x1="250" y1="230" x2="300" y2="230" stroke="#c0392b" stroke-width="5" />
     <text x="260" y="220" font-family="Arial" font-size="12">Blow: {float(blow):.1f}</text>
     
     <text x="130" y="200" font-family="Arial" font-size="14" fill="white" font-weight="bold">CoC: {res['Max_Cycle']}</text>
    </svg>
    """
    st.image(svg_code if False else f"data:image/svg+xml;utf8,{svg_code}", use_column_width=False)
