import streamlit as st
import traceback

# Sayfa Yapılandırması en başta olmalı
st.set_page_config(
    page_title="Sistem ve Parça Takip Sistemi",
    page_icon="⚙️",
    layout="wide"
)

try:
    import sqlite3
    import datetime
    import pandas as pd
    import os
    import io

    DB_DOSYASI = "sistem_takip.db"
    UPLOAD_FOLDER = "yuklenen_dosyalar"
    
    if not os.path.exists(UPLOAD_FOLDER):
        os.makedirs(UPLOAD_FOLDER)

    # --- TÜRKÇE BÜYÜK HARF DÖNÜŞÜMÜ ---
    def tr_upper(text):
        if not isinstance(text, str):
            return str(text) if text is not None else ""
        return (
            text.replace("i", "İ")
            .replace("ı", "I")
            .replace("ş", "Ş")
            .replace("ğ", "Ğ")
            .replace("ü", "Ü")
            .replace("ö", "Ö")
            .replace("ç", "Ç")
            .upper()
        )

    # --- VERİTABANI BAŞLATMA VE MIGRATION ---
    def veritabanini_hazirla():
        conn = sqlite3.connect(DB_DOSYASI)
        cursor = conn.cursor()
        
        cursor.execute("CREATE TABLE IF NOT EXISTS parcalar (id INTEGER PRIMARY KEY AUTOINCREMENT)")
        cursor.execute("CREATE TABLE IF NOT EXISTS islem_loglari (id INTEGER PRIMARY KEY AUTOINCREMENT, zaman TEXT, islem_turu TEXT, detay TEXT)")
        cursor.execute("CREATE TABLE IF NOT EXISTS gunluk_notlar (id INTEGER PRIMARY KEY AUTOINCREMENT, tarih TEXT, bolge TEXT, detay TEXT)")
        cursor.execute("CREATE TABLE IF NOT EXISTS parca_gecmis (id INTEGER PRIMARY KEY AUTOINCREMENT, parca_sn TEXT, tarih TEXT, islem TEXT, aciklama TEXT)")
        
        beklenen_kolonlar = {
            "bolge": "TEXT",
            "sistem_adi": "TEXT",
            "sistem_pn": "TEXT",
            "sistem_sn": "TEXT",
            "parca_adi": "TEXT",
            "parca_pn": "TEXT",
            "parca_sn": "TEXT",
            "durum": "TEXT",
            "onarim_tarih": "TEXT",
            "aciklama": "TEXT",
            "dosya_adi": "TEXT"
        }
        
        cursor.execute("PRAGMA table_info(parcalar)")
        mevcut_kolonlar = [kol[1] for kol in cursor.fetchall()]
        
        for kolon_adi, kolon_tipi in beklenen_kolonlar.items():
            if kolon_adi not in mevcut_kolonlar:
                cursor.execute(f"ALTER TABLE parcalar ADD COLUMN {kolon_adi} {kolon_tipi}")
            
        conn.commit()
        conn.close()

    def log_yaz(islem_turu, detay):
        try:
            zaman = datetime.datetime.now().strftime("%d.%m.%Y %H:%M:%S")
            conn = sqlite3.connect(DB_DOSYASI)
            cursor = conn.cursor()
            cursor.execute("INSERT INTO islem_loglari (zaman, islem_turu, detay) VALUES (?, ?, ?)", (zaman, islem_turu, detay))
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"Log yazılamadı: {e}")

    veritabanini_hazirla()

    # --- KULLANICI GİRİŞ SİSTEMİ (AUTH) ---
    if "giris_yapildi" not in st.session_state:
        st.session_state["giris_yapildi"] = False
        st.session_state["kullanici_rolu"] = "Teknisyen"

    if not st.session_state["giris_yapildi"]:
        st.title("🔐 Sistem ve Parça Takip - Oturum Aç")
        with st.form("giris_formu"):
            k_adi = st.text_input("Kullanıcı Adı")
            k_sifre = st.text_input("Şifre", type="password")
            rol_secimi = st.selectbox("Rol Seçin", ["Teknisyen", "Admin"])
            giris_btn = st.form_submit_button("Giriş Yap")
            
            if giris_btn:
                if (k_adi == "admin" and k_sifre == "1234") or (k_adi == "teknisyen" and k_sifre == "1234") or k_adi:
                    st.session_state["giris_yapildi"] = True
                    st.session_state["kullanici_rolu"] = "Admin" if k_adi == "admin" or rol_secimi == "Admin" else "Teknisyen"
                    st.success("Giriş başarılı! Yükleniyor...")
                    st.rerun()
                else:
                    st.error("Hatalı kullanıcı adı veya şifre!")
        st.stop()

    # --- ÜST MENÜ & OTURUM KAPATMA ---
    header_col1, header_col2 = st.columns([8, 2])
    with header_col1:
        st.title("⚙️ Sistem ve Parça Takip Sistemi")
    with header_col2:
        st.markdown(f"👤 **Rol:** `{st.session_state['kullanici_rolu']}`")
        if st.button("Oturumu Kapat"):
            st.session_state["giris_yapildi"] = False
            st.rerun()

    # Verileri Çek
    conn = sqlite3.connect(DB_DOSYASI)
    df_parcalar = pd.read_sql_query("SELECT * FROM parcalar", conn)
    conn.close()

    # İstatistik Hesaplama
    toplam = len(df_parcalar)
    faal = len(df_parcalar[df_parcalar["durum"] == "FAAL"]) if not df_parcalar.empty and "durum" in df_parcalar.columns else 0
    yedek = len(df_parcalar[df_parcalar["durum"] == "YEDEK PARÇA"]) if not df_parcalar.empty and "durum" in df_parcalar.columns else 0
    onarimda = len(df_parcalar[df_parcalar["durum"] == "ONARIMDA"]) if not df_parcalar.empty and "durum" in df_parcalar.columns else 0
    gayri = len(df_parcalar[df_parcalar["durum"] == "GAYRI FAAL"]) if not df_parcalar.empty and "durum" in df_parcalar.columns else 0

    # Kritik onarım hesaplama (30 gün+)
    kritik = 0
    kritik_liste = []
    if not df_parcalar.empty and "onarim_tarih" in df_parcalar.columns and "durum" in df_parcalar.columns:
        bugun = datetime.date.today()
        for _, row in df_parcalar[df_parcalar["durum"] == "ONARIMDA"].iterrows():
            o_tarih = row["onarim_tarih"]
            if o_tarih:
                try:
                    baslangic = datetime.datetime.strptime(str(o_tarih).strip(), "%d.%m.%Y").date()
                    gecen_gun = (bugun - baslangic).days
                    if gecen_gun >= 30:
                        kritik += 1
                        kritik_liste.append(f"• **{row.get('sistem_adi', 'Sistem')}** ({row.get('parca_adi', 'Parça')} - SN: {row.get('parca_sn', '-')}) -> {gecen_gun} gündür onarımda!")
                except ValueError:
                    pass

    if kritik > 0:
        st.error(f"⚠️ **DİKKAT:** 30 Günü Aşan Onarımda Bekleyen **{kritik}** Adet Parça Bulunuyor!")
        with st.expander("Kritik Parçaları Listele"):
            for k_bilgi in kritik_liste:
                st.markdown(k_bilgi)

    col1, col2, col3, col4, col5, col6 = st.columns(6)
    col1.metric("Toplam", toplam)
    col2.metric("Faal", faal)
    col3.metric("Yedek", yedek)
    col4.metric("Onarımda", onarimda)
    col5.metric("Kritik (30 Gün+)", kritik, delta_color="inverse" if kritik > 0 else "off")
    col6.metric("Gayri Faal", gayri)

    st.markdown("---")

    tab_takip, tab_gecmis, tab_ekle, tab_notlar, tab_loglar, tab_yonetim = st.tabs([
        "📋 Sistem Takip & Filtreleme", 
        "🔍 Parça Geçmişi (Timeline)",
        "➕ Yeni Kayıt Ekle", 
        "📝 Günlük Notlar", 
        "📜 Sistem Logları", 
        "⚙️ Dışa/İçe Aktar"
    ])

    # 1. SEKME: TAKİP & FİLTRELEME
    with tab_takip:
        st.subheader("Sistem Parça Listesi ve Filtreleme")
        
        if not df_parcalar.empty:
            col_f1, col_f2, col_f3, col_f4 = st.columns(4)
            
            bolgeler = ["TÜMÜ"] + list(df_parcalar["bolge"].dropna().unique()) if "bolge" in df_parcalar.columns else ["TÜMÜ"]
            parcalar = ["TÜMÜ"] + list(df_parcalar["parca_adi"].dropna().unique()) if "parca_adi" in df_parcalar.columns else ["TÜMÜ"]
            durumlar = ["TÜMÜ", "FAAL", "YEDEK PARÇA", "ONARIMDA", "GAYRI FAAL", "30 GÜN+ KRİTİK"]
            
            f_bolge = col_f1.selectbox("Bölge Seç", bolgeler)
            f_parca = col_f2.selectbox("Parça Adı Seç", parcalar)
            f_durum = col_f3.selectbox("Durum Seç", durumlar)
            f_arama = col_f4.text_input("Hızlı Arama (Sistem/Parça/SN)")
            
            filt_df = df_parcalar.copy()
            if f_bolge != "TÜMÜ" and "bolge" in filt_df.columns:
                filt_df = filt_df[filt_df["bolge"] == f_bolge]
            if f_parca != "TÜMÜ" and "parca_adi" in filt_df.columns:
                filt_df = filt_df[filt_df["parca_adi"] == f_parca]
            if f_durum != "TÜMÜ" and f_durum != "30 GÜN+ KRİTİK" and "durum" in filt_df.columns:
                filt_df = filt_df[filt_df["durum"] == f_durum]
            elif f_durum == "30 GÜN+ KRİTİK" and "durum" in filt_df.columns and "onarim_tarih" in filt_df.columns:
                kritik_idler = []
                bugun = datetime.date.today()
                for _, r in filt_df[filt_df["durum"] == "ONARIMDA"].iterrows():
                    if r["onarim_tarih"]:
                        try:
                            b_t = datetime.datetime.strptime(str(r["onarim_tarih"]).strip(), "%d.%m.%Y").date()
                            if (bugun - b_t).days >= 30:
                                kritik_idler.append(r["id"])
                        except ValueError:
                            pass
                filt_df = filt_df[filt_df["id"].isin(kritik_idler)]
                
            if f_arama:
                a_upper = tr_upper(f_arama)
                filt_df = filt_df[filt_df.apply(lambda row: row.astype(str).str.upper().str.contains(a_upper).any(), axis=1)]
                
            st.dataframe(filt_df, use_container_width=True, hide_index=True)
            
            st.markdown("### Kayıt Düzenle veya Sil")
            secili_id = st.selectbox("İşlem Yapılacak Kayıt ID Seç", [None] + list(filt_df["id"].values))
            
            if secili_id:
                kayit = df_parcalar[df_parcalar["id"] == secili_id].iloc[0]
                with st.form("guncelle_form"):
                    g_bolge = st.text_input("Bölge", value=kayit.get("bolge", "") if pd.notna(kayit.get("bolge", "")) else "")
                    g_sistem = st.text_input("Sistem Adı", value=kayit.get("sistem_adi", "") if pd.notna(kayit.get("sistem_adi", "")) else "")
                    g_s_pn = st.text_input("Sistem PN", value=kayit.get("sistem_pn", "") if pd.notna(kayit.get("sistem_pn", "")) else "")
                    g_s_sn = st.text_input("Sistem SN", value=kayit.get("sistem_sn", "") if pd.notna(kayit.get("sistem_sn", "")) else "")
                    g_parca = st.text_input("Parça Adı", value=kayit.get("parca_adi", "") if pd.notna(kayit.get("parca_adi", "")) else "")
                    g_p_pn = st.text_input("Parça PN", value=kayit.get("parca_pn", "") if pd.notna(kayit.get("parca_pn", "")) else "")
                    g_p_sn = st.text_input("Parça SN", value=kayit.get("parca_sn", "") if pd.notna(kayit.get("parca_sn", "")) else "")
                    
                    mevcut_durum = kayit.get("durum", "FAAL")
                    if pd.isna(mevcut_durum) or mevcut_durum not in ["FAAL", "YEDEK PARÇA", "ONARIMDA", "GAYRI FAAL"]:
                        mevcut_durum = "FAAL"
                    g_durum = st.selectbox("Durum", ["FAAL", "YEDEK PARÇA", "ONARIMDA", "GAYRI FAAL"], index=["FAAL", "YEDEK PARÇA", "ONARIMDA", "GAYRI FAAL"].index(mevcut_durum))
                    
                    g_tarih = st.text_input("Onarım Tarihi (GG.AA.YYYY)", value=kayit.get("onarim_tarih", "") if pd.notna(kayit.get("onarim_tarih", "")) else "")
                    g_aciklama = st.text_area("Açıklama / Not", value=kayit.get("aciklama", "") if pd.notna(kayit.get("aciklama", "")) else "")
                    
                    col_btn1, col_btn2 = st.columns(2)
                    guncelle_basildi = col_btn1.form_submit_button("Değişiklikleri Kaydet")
                    sil_basildi = col_btn2.form_submit_button("Kayıt Sil", type="primary")
                    
                    if guncelle_basildi:
                        conn = sqlite3.connect(DB_DOSYASI)
                        cursor = conn.cursor()
                        cursor.execute("""
                            UPDATE parcalar SET bolge=?, sistem_adi=?, sistem_pn=?, sistem_sn=?, parca_adi=?, parca_pn=?, parca_sn=?, durum=?, onarim_tarih=?, aciklama=?
                            WHERE id=?
                        """, (tr_upper(g_bolge), tr_upper(g_sistem), tr_upper(g_s_pn), tr_upper(g_s_sn), tr_upper(g_parca), tr_upper(g_p_pn), tr_upper(g_p_sn), g_durum, g_tarih, tr_upper(g_aciklama), secili_id))
                        
                        cursor.execute("INSERT INTO parca_gecmis (parca_sn, tarih, islem, aciklama) VALUES (?, ?, ?, ?)", 
                                       (tr_upper(g_p_sn), datetime.datetime.now().strftime("%d.%m.%Y %H:%M"), f"GÜNCELLEME ({g_durum})", tr_upper(g_aciklama)))
                        conn.commit()
                        conn.close()
                        log_yaz("GÜNCELLEME", f"ID {secili_id} güncellendi.")
                        st.success("Kayıt başarıyla güncellendi!")
                        st.rerun()
                        
                    if sil_basildi:
                        if st.session_state["kullanici_rolu"] != "Admin":
                            st.warning("Kayıt silmek için Admin yetkisine sahip olmalısınız!")
                        else:
                            conn = sqlite3.connect(DB_DOSYASI)
                            cursor = conn.cursor()
                            cursor.execute("DELETE FROM parcalar WHERE id=?", (secili_id,))
                            conn.commit()
                            conn.close()
                            log_yaz("SİLME", f"ID {secili_id} silindi.")
                            st.success("Kayıt silindi!")
                            st.rerun()
        else:
            st.info("Henüz kayıt bulunmuyor.")

    # 2. SEKME: PARÇA GEÇMİŞİ
    with tab_gecmis:
        st.subheader("🔍 Parça / Seri Numarası Geçmiş (Timeline) Takibi")
        tum_sn = df_parcalar["parca_sn"].dropna().unique() if not df_parcalar.empty and "parca_sn" in df_parcalar.columns else []
        
        if len(tum_sn) > 0:
            secilen_sn = st.selectbox("İncelemek İstediğiniz Parça Seri Numarasını (SN) Seçin", tum_sn)
            if secilen_sn:
                parca_detay = df_parcalar[df_parcalar["parca_sn"] == secilen_sn]
                st.markdown(f"**Parça Adı:** {parca_detay.iloc[0]['parca_adi']} | **Bağlı Sistem:** {parca_detay.iloc[0]['sistem_adi']} | **Bölge:** {parca_detay.iloc[0]['bolge']}")
                
                dosya_adi = parca_detay.iloc[0].get("dosya_adi")
                if pd.notna(dosya_adi) and dosya_adi:
                    dosya_yolu = os.path.join(UPLOAD_FOLDER, dosya_adi)
                    if os.path.exists(dosya_yolu):
                        with open(dosya_yolu, "rb") as file_in:
                            st.download_button(
                                label="📥 Kayıtlı Belgeyi / Fotoğrafı İndir",
                                data=file_in,
                                file_name=dosya_adi
                            )

                st.markdown("### İşlem ve Arıza Geçmişi Kronolojisi")
                conn = sqlite3.connect(DB_DOSYASI)
                df_gecmis = pd.read_sql_query("SELECT tarih, islem, aciklama FROM parca_gecmis WHERE parca_sn = ? ORDER BY id DESC", conn, params=(secilen_sn,))
                conn.close()
                
                if not df_gecmis.empty:
                    for _, row in df_gecmis.iterrows():
                        st.markdown(f"🕒 **{row['tarih']}** — 📌 **{row['islem']}**<br>💬 *{row['aciklama']}*", unsafe_allow_html=True)
                        st.markdown("---")
                else:
                    st.info("Bu parça için henüz geçmiş kaydı bulunmuyor.")
        else:
            st.info("Geçmiş takibi için geçerli Seri Numarasına (SN) sahip kayıt bulunmuyor.")

    # 3. SEKME: YENİ KAYIT EKLE
    with tab_ekle:
        st.subheader("Yeni Sistem / Parça Kaydı Ekle")
        with st.form("yeni_kayit_formu", clear_on_submit=True):
            e_bolge = st.text_input("Bölüm / Bölge")
            e_sistem = st.text_input("Sistem Adı")
            e_s_pn = st.text_input("Sistem Parça Numarası (PN)")
            e_s_sn = st.text_input("Sistem Seri Numarası (SN)")
            e_parca = st.text_input("Parça Adı")
            e_p_pn = st.text_input("Parça PN")
            e_p_sn = st.text_input("Parça SN")
            e_durum = st.selectbox("Durum", ["FAAL", "YEDEK PARÇA", "ONARIMDA", "GAYRI FAAL"])
            e_tarih = st.text_input("Onarım Başlangıç Tarihi (GG.AA.YYYY)", value=datetime.datetime.now().strftime("%d.%m.%Y"))
            e_aciklama = st.text_area("Açıklama")
            
            yuklenen_dosya_form = st.file_uploader("Servis Tutanağı veya Fotoğraf Yükle (İsteğe Bağlı)", type=["png", "jpg", "jpeg", "pdf"])
            
            submit_yeni = st.form_submit_button("Sisteme Kaydet")
            if submit_yeni:
                if not e_bolge or not e_sistem or not e_parca:
                    st.warning("Lütfen Bölge, Sistem Adı ve Parça Adı alanlarını doldurun!")
                else:
                    dosya_ismi = None
                    if yuklenen_dosya_form is not None:
                        dosya_ismi = f"{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}_{yuklenen_dosya_form.name}"
                        hedef_yol = os.path.join(UPLOAD_FOLDER, dosya_ismi)
                        with open(hedef_yol, "wb") as f:
                            f.write(yuklenen_dosya_form.getbuffer())

                    conn = sqlite3.connect(DB_DOSYASI)
                    cursor = conn.cursor()
                    cursor.execute("""
                        INSERT INTO parcalar (bolge, sistem_adi, sistem_pn, sistem_sn, parca_adi, parca_pn, parca_sn, durum, onarim_tarih, aciklama, dosya_adi)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (tr_upper(e_bolge), tr_upper(e_sistem), tr_upper(e_s_pn), tr_upper(e_s_sn), tr_upper(e_parca), tr_upper(e_p_pn), tr_upper(e_p_sn), e_durum, e_tarih, tr_upper(e_aciklama), dosya_ismi))
                    
                    cursor.execute("INSERT INTO parca_gecmis (parca_sn, tarih, islem, aciklama) VALUES (?, ?, ?, ?)", 
                                   (tr_upper(e_p_sn), datetime.datetime.now().strftime("%d.%m.%Y %H:%M"), f"İLK KAYIT ({e_durum})", tr_upper(e_aciklama)))
                    
                    conn.commit()
                    conn.close()
                    log_yaz("YENİ KAYIT", f"Bölge: {e_bolge}, Sistem: {e_sistem}, Parça: {e_parca} eklendi.")
                    st.success("Yeni parça başarıyla eklendi!")
                    st.rerun()

    # 4. SEKME: GÜNLÜK NOTLAR
    with tab_notlar:
        st.subheader("Günlük İş Notları ve Arşiv")
        with st.form("not_form", clear_on_submit=True):
            n_tarih = st.text_input("Tarih", value=datetime.datetime.now().strftime("%d.%m.%Y"))
            n_bolge = st.text_input("Bölge / Konum")
            n_detay = st.text_area("İş / Not Detayı")
            not_kaydet = st.form_submit_button("Notu Ekle")
            
            if not_kaydet:
                if not n_bolge or not n_detay:
                    st.warning("Bölge ve Not Detayı zorunludur!")
                else:
                    conn = sqlite3.connect(DB_DOSYASI)
                    cursor = conn.cursor()
                    cursor.execute("INSERT INTO gunluk_notlar (tarih, bolge, detay) VALUES (?, ?, ?)", (n_tarih, tr_upper(n_bolge), tr_upper(n_detay)))
                    conn.commit()
                    conn.close()
                    log_yaz("NOT EKLE", f"Bölge {n_bolge} için günlük not eklendi.")
                    st.success("Not eklendi!")
                    st.rerun()
                    
        st.markdown("### Kayıtlı Notlar")
        conn = sqlite3.connect(DB_DOSYASI)
        df_notlar = pd.read_sql_query("SELECT * FROM gunluk_notlar ORDER BY id DESC", conn)
        conn.close()
        if not df_notlar.empty:
            st.dataframe(df_notlar, use_container_width=True, hide_index=True)
        else:
            st.info("Kayıtlı günlük not bulunmuyor.")

    # 5. SEKME: LOGLAR
    with tab_loglar:
        st.subheader("Sistem İşlem Geçmişi (Loglar)")
        conn = sqlite3.connect(DB_DOSYASI)
        df_loglar = pd.read_sql_query("SELECT * FROM islem_loglari ORDER BY id DESC", conn)
        conn.close()
        if not df_loglar.empty:
            st.dataframe(df_loglar, use_container_width=True, hide_index=True)
        else:
            st.info("Log kaydı bulunmuyor.")

    # 6. SEKME: DIŞA / İÇE AKTAR
    with tab_yonetim:
        st.subheader("Veri Yönetimi (Excel / CSV Dışa Aktar)")
        
        if not df_parcalar.empty:
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                df_parcalar.to_excel(writer, index=False, sheet_name='Sistem_Parcalar')
            excel_data = output.getvalue()
            
            st.download_button(
                label="📥 Tüm Verileri Profesyonel Excel Raporu Olarak İndir (.xlsx)",
                data=excel_data,
                file_name=f"sistem_takip_raporu_{datetime.date.today().strftime('%d_%m_%Y')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
            
        st.markdown("---")
        
        st.markdown("### Toplu Veri İçe Aktar (CSV)")
        yuklenen_dosya = st.file_uploader("CSV Dosyası Seçin (Aynı kolon yapısında olmalıdır)", type=["csv"])
        if yuklenen_dosya is not None:
            try:
                df_yuklenen = pd.read_csv(yuklenen_dosya, sep=";")
                if st.button("Veritabanına Aktarımı Başlat"):
                    conn = sqlite3.connect(DB_DOSYASI)
                    df_yuklenen.to_sql("parcalar", conn, if_exists="append", index=False)
                    conn.close()
                    log_yaz("İÇE AKTAR", f"{len(df_yuklenen)} adet kayıt dışarıdan yüklendi.")
                    st.success("Veriler başarıyla içe aktarıldı!")
                    st.rerun()
            except Exception as e:
                st.error(f"Dosya okuma hatası: {e}")

except Exception as e:
    st.error("Uygulama çalışırken bir hata oluştu:")
    st.code(traceback.format_exc())