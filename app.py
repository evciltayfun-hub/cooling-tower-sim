import streamlit as st
from datetime import date

# ==========================================
# SAYFA AYARLARI & STİL
# ==========================================
st.set_page_config(page_title="ProChem Cooling Tower", layout="wide", page_icon="🏭")

# Sol paneli biraz genişletelim ve yazı tiplerini düzenleyelim
st.markdown("""
<style>
    [data-testid="stSidebar"][aria-expanded="true"] > div:first-child {
        width: 400px;
    }
    .header-style {
        font-size: 18px;
        font-weight: bold;
        color: #1E3D59;
        margin-top: 10px;
        margin-bottom: 10px;
        border-bottom: 2px solid #1E3D59;
    }
</style>
""", unsafe_allow_html=True)

# ==========================================
# SOL PANEL: TÜM GİRİŞLER (INPUT POOL)
# ==========================================
with st.sidebar:
    st.title("🏭 Veri Giriş Paneli")
    
    # --- BÖLÜM 1: MÜŞTERİ BİLGİLERİ ---
    st.markdown('<p class="header-style">1. Proje Künyesi</p>', unsafe_allow_html=True)
    
    c1, c2 = st.columns(2)
    with c1:
        client = st.text_input("Müşteri", "Qatar Cool Plant 1")
        loc = st.text_input("Lokasyon", "Doha/Qatar")
    with c2:
        sys_id = st.text_input("Sistem ID", "CT-01")
        proj_date = st.date_input("Tarih", date.today())

    # --- BÖLÜM 2: KULE TASARIM VERİLERİ ---
    st.markdown('<p class="header-style">2. Kule Tasarım Bilgileri</p>', unsafe_allow_html=True)
    
    # Screenshot'taki sıraya göre inputlar
    q_circ = st.number_input("Recirculation Rate (m³/h)", value=2500.0, step=100.0)
    delta_t = st.number_input("Delta T (°C)", value=6.0, step=0.5)
    volume = st.number_input("System Volume (m³)", value=850.0, step=10.0)
    
    # Screenshot'ta gördüğümüz detaylar
    c3, c4 = st.columns(2)
    with c3:
        f_factor = st.number_input("Evap. Factor (f)", value=0.80, step=0.01, help="Genelde 0.80 - 1.0 arası")
        service_load = st.number_input("Service Load (%)", value=100, step=10)
    with c4:
        losses = st.number_input("Water Losses (m³/h)", value=0.0, step=0.1, help="Spray, Drift, Process Leaks")
        skin_temp = st.number_input("Skin Temp (°C)", value=60.0, step=1.0, help="Eşanjör yüzey sıcaklığı (Kritik!)")

    # --- BÖLÜM 3: SU KİMYASI (MAKE-UP) ---
    st.markdown('<p class="header-style">3. Besi Suyu Analizi (Make-up)</p>', unsafe_allow_html=True)
    
    with st.expander("🧪 Temel İyonlar", expanded=True):
        ph = st.number_input("pH", value=7.8, step=0.1)
        cond = st.number_input("Conductance (µS/cm)", value=1340.0)
        ca = st.number_input("Ca as CaCO3", value=275.0)
        mg = st.number_input("Mg as CaCO3", value=68.4)
        alk = st.number_input("Total Alkalinity (M-Alk)", value=90.0)
    
    with st.expander("🧪 Anyonlar ve Silis", expanded=False):
        so4 = st.number_input("Sulfate (SO4)", value=331.0)
        cl = st.number_input("Chloride (Cl)", value=176.0)
        sio2 = st.number_input("Silica (SiO2)", value=9.4)
        po4 = st.number_input("Orthophosphate (PO4)", value=0.0)
        poly_po4 = st.number_input("Polyphosphate (PO4)", value=0.0)

    with st.expander("🧪 Metaller (Detay)", expanded=False):
        fe = st.number_input("Iron (Fe)", value=0.0)
        al = st.number_input("Aluminum (Al)", value=0.0)
        zn = st.number_input("Zinc (Zn)", value=0.0)
        mn = st.number_input("Manganese (Mn)", value=0.0)
        cu = st.number_input("Copper (Cu)", value=0.0)

# ==========================================
# SAĞ PANEL: (ŞİMDİLİK BOŞ TASLAK)
# ==========================================
st.title(f"📊 Analiz Raporu: {client}")
st.info("👈 Tüm verileri sol taraftan girebilirsiniz. Sonuçlar burada görünecek.")

# Layout Testi için Basit Gösterim
c_res1, c_res2 = st.columns(2)

with c_res1:
    st.subheader("Girilen Sistem Verileri")
    st.write(f"**Sirkülasyon:** {q_circ} m³/h")
    st.write(f"**Delta T:** {delta_t} °C")
    st.write(f"**Hacim:** {volume} m³")
    st.write(f"**Yüzey Sıcaklığı (Skin):** {skin_temp} °C")

with c_res2:
    st.subheader("Girilen Su Verileri")
    st.write(f"**pH:** {ph}")
    st.write(f"**İletkenlik:** {cond} µS/cm")
    st.write(f"**Ca Sertliği:** {ca} ppm")
    st.write(f"**Silis:** {sio2} ppm")
