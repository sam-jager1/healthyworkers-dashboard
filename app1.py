import streamlit as st
import pandas as pd
import numpy as np
import re

# --- 1. CONFIGURATIE & STYLING ---
st.set_page_config(page_title="Healthy Workers | Data Dashboard", layout="wide")


st.markdown(f"""
    <style>
    /* Achtergrond naar Navy */
    .stApp {{ 
        background-color: #0c0c5b !important; 
    }}

    /* Alle tekst naar wit (zonder div en span) */
    h1, h2, h3, p, label, .stMarkdown, .stText {{
        color: white !important; 
    }}

    /* Omdat we div en span hebben verwijderd, moeten we zorgen 
       dat tekst die wel wit moet zijn, dat ook blijft */
    .stApp {{
        color: white;
    }}

    /* Knoppen specifiek aanpakken */
    div.stButton > button:first-child {{
        background-color: white !important;
        color: #0c0c5b !important;
        border: 2px solid white !important;
        font-weight: bold !important;
    }}
    
    /* Zorg dat de tekst in de knop ook echt de Navy kleur krijgt */
    div.stButton > button:first-child p {{
        color: #0c0c5b !important;
    }}
            
    /* De drag & drop zone zelf (witte achtergrond, navy tekst) */
    [data-testid="stFileUploader"] {{
        background-color: white !important;
        color: #0c0c5b !important;
    }}
    
    /* De instructietekst binnen de uploader */
    [data-testid="stFileUploader"] * {{
        color: #0c0c5b !important;
    }}
    
    /* De 'Browse files' knop binnen de uploader */
    [data-testid="stFileUploader"] button {{
        background-color: white !important;
        color: #0c0c5b !important;
    }}
  
    </style>
""", unsafe_allow_html=True)

# --- 2. SESSION STATE INITIALISATIE ---
if 'page' not in st.session_state:
    st.session_state.page = 'Welkom'
if 'uploaded_files' not in st.session_state:
    st.session_state.uploaded_files = None

# --- 3. HELPER FUNCTIES (Navigatie) ---
def go_to_page(page_name):
    st.session_state.page = page_name
    st.rerun()

# --- 4. DATA LOGICA (Jouw bestaande functies) ---

# Configuratie: Fysieke Caps per type
ENERGY_LIMITS = {
    'Elektriciteit': {'Groep': 1000000, 'Sensor': 250000},
    'Gas':           {'Groep': 50000,   'Sensor': 10000},  
    'Water':         {'Groep': 2500,    'Sensor': 500},
    'Warmte':        {'Groep': 10000,   'Sensor': 2000},
    'Koeling':       {'Groep': 8000,    'Sensor': 1500}
}

MONTHS = ['jan. 2025', 'feb. 2025', 'mrt. 2025', 'apr. 2025', 'mei 2025', 'jun. 2025', 
          'jul. 2025', 'aug. 2025', 'sep. 2025', 'okt. 2025', 'nov. 2025', 'dec. 2025', 
          'jan. 2026', 'feb. 2026', 'mrt. 2026']


def natural_sort_key(s):
    """
    Sorteert strings op een natuurlijke manier (bijv: 1, 2, 10 in plaats van 1, 10, 2).
    """
    return [int(text) if text.isdigit() else text.lower() for text in re.split('([0-9]+)', s)]

def parse_data(file_obj):
    df = pd.read_excel(file_obj, header=None, engine='openpyxl')
    rename_dict = {0: 'Sensor_ID', 1: 'Omschrijving'}
    for i, month in enumerate(MONTHS): rename_dict[i + 2] = month
    df = df.rename(columns=rename_dict)
    
    df['Type'] = 'Overig'
    curr_group = "Overig"
    
    for idx, row in df.iterrows():
        val = str(row['Sensor_ID']).strip()
        if val in ['Hoofdmeters', 'Tussenmeters', 'Aanvullende elektriciteitsstatistieken', 'Virtuele meters']:
            curr_group = val
        elif val.startswith('- ') and not val.startswith('--'):
            df.at[idx, 'Type'] = 'Groep_Totaal'
            df.at[idx, 'Categorie'] = curr_group
            # Pak de hele tekst na het minteken
            df.at[idx, 'Meter_Type'] = val.replace('- ', '').strip()
        elif val.startswith('--'):
            df.at[idx, 'Type'] = 'Sensor'
            df.at[idx, 'Categorie'] = curr_group
            
    df['Meter_Type'] = df['Meter_Type'].ffill()
    for m in MONTHS:
        df[m] = pd.to_numeric(df[m].astype(str).str.replace(',', '.'), errors='coerce')
    return df

def get_anomalies_robuust(data_subset, is_group):
    gaps, spikes = [], []
    for _, row in data_subset.iterrows():
        vals = row[MONTHS].values.astype(float)
        # 1. Gaten
        g = [MONTHS[i] for i, v in enumerate(vals) if np.isnan(v) or v == 0]
        if g: gaps.append(row.to_dict() | {'Maanden': ", ".join(g)})
        
        # 2. Robuuste Spike Detectie
        m_type = str(row['Meter_Type']).lower() # Maak alles lowercase voor de match
    
        # Bepaal het type gebaseerd op sleutelwoorden in de naam
        if 'elektriciteit' in m_type or 'kwh' in m_type:
            cat = 'Elektriciteit'
        elif 'gas' in m_type:
            cat = 'Gas'
        elif 'water' in m_type:
            cat = 'Water'
        elif 'warmte' in m_type:
            cat = 'Warmte'
        elif 'koeling' in m_type:
            cat = 'Koeling'
        else:
            cat = 'Overig' # Fallback
            
        limit = ENERGY_LIMITS[cat]['Groep' if is_group else 'Sensor']
        
        # Modified Z-Score berekening
        median = np.nanmedian(vals)
        mad = np.nanmedian(np.abs(vals - median))
        z_scores = (0.6745 * (vals - median)) / (mad if mad != 0 else 1)
        
        for i, val in enumerate(vals):
            if np.isnan(val): continue
            # Methode A: Fysieke Cap | Methode B: Modified Z-Score > 3.5
            if val > limit or abs(z_scores[i]) > 3.5:
                spikes.append(row.to_dict() | {'Maand': MONTHS[i], 'Waarde': val, 'Reden': 'Cap' if val > limit else 'Z-Score'})
    return pd.DataFrame(gaps), pd.DataFrame(spikes)

# --- 5. SCHERMEN ---

# SCHERM 1: WELKOM
if st.session_state.page == 'Welkom':
    
    st.title("Data Dashboard - Healthy Workers")
    st.markdown("""
    ### Welkom bij het data dashboard van Healthy Workers.
    Deze tool helpt om databestanden te analyseren op:
    *   **Data Gaten:** Ontbrekende maanden of nul-waarden.
    *   **Extreme Waarden:** Waarden die extreem hoog zijn of statistisch afwijken (Z-Score).
    *   **Duplicaten:** Identieke rijen in de dataset.
    
    Klik op de knop hieronder om te beginnen met het uploaden van de bestanden.
    """)
    
    if st.button("Start Analyse ➔"):
        go_to_page('Upload')

# SCHERM 2: UPLOAD
elif st.session_state.page == 'Upload':
    st.title("Bestanden Uploaden")
    st.info("Upload hier de .xlsx bestanden die je wilt controleren.")
    
    files = st.file_uploader("Selecteer Excel-bestanden", type=["xlsx"], accept_multiple_files=True)
    
    col1, col2 = st.columns([1, 5])
    with col1:
        if st.button("⬅ Terug"):
            go_to_page('Welkom')
    with col2:
        if files:
            st.session_state.uploaded_files = files
            if st.button("Bestanden Verwerken ➔"):
                go_to_page('Analyse')

# SCHERM 3: ANALYSE
elif st.session_state.page == 'Analyse':
    st.title("Data Analyse Resultaten")
    
    if st.button("⬅ Terug naar Upload"):
        go_to_page('Upload')
    
    # 1. DATA PRE-LOADEN (Dit gebeurt maar één keer)
    if 'parsed_data_dict' not in st.session_state:
        st.session_state.parsed_data_dict = {}
        for f in st.session_state.uploaded_files:
            # We laden het bestand hier vast in de session_state
            building_key = f.name.split("-")[3].strip() if len(f.name.split("-")) > 3 else f.name
            f.seek(0)
            data = parse_data(f)
            # Opschonen direct bij het inladen
            data = data.dropna(subset=['Sensor_ID'])
            data = data[data['Sensor_ID'].astype(str).str.strip() != '']
            st.session_state.parsed_data_dict[building_key] = data

    # 2. TABS OPBOUWEN
    sorted_names = sorted(st.session_state.parsed_data_dict.keys(), key=natural_sort_key)
    tabs = st.tabs(sorted_names)
    
    # 3. PER TAB DE DATA OPHALEN UIT DE DICTIONARY
    for idx, tab_name in enumerate(tabs):
        with tab_name:
            building_name = sorted_names[idx]
            # HIER HAAL JE DE SPECIFIEKE DATA OP
            df = st.session_state.parsed_data_dict[building_name]
            
            # Unieke radio knop voor dit gebouw
            fout_type = st.radio(
                "Selecteer type:", 
                ["Data Gaten", "Extreme Waarden", "Duplicaten"], 
                key=f"radio_{building_name}", 
                horizontal=True
            )

            # Anomalieën op Groepsniveau
            agg_gaps, agg_spikes = get_anomalies_robuust(df[df['Type'] == 'Groep_Totaal'], True)
            
            if "Gaten" in fout_type:
                st.subheader("Anomalieën op Groepsniveau")
                if not agg_gaps.empty:
                    st.dataframe(agg_gaps[['Categorie', 'Meter_Type', 'Maanden']], use_container_width=True, hide_index=True)
                else:
                    st.success("Geen gaten gevonden op groepsniveau.")

            elif "Waarden" in fout_type:
                st.subheader("Anomalieën op Groepsniveau")
                # HIER ZAT DE FOUT: check of hij niet leeg is
                if not agg_spikes.empty:
                    st.dataframe(agg_spikes[['Categorie', 'Meter_Type', 'Maand', 'Waarde']], use_container_width=True, hide_index=True)
                else:
                    st.info("Geen extreme waarden gevonden op groepsniveau.")
            
            # Anomalieën op Sensorniveau
            st.subheader("Anomalieën op Sensorniveau")
            sens_gaps, sens_spikes = get_anomalies_robuust(df[df['Type'] == 'Sensor'], False)
            
            if "Gaten" in fout_type:
                if not sens_gaps.empty:
                    st.dataframe(sens_gaps[['Categorie', 'Meter_Type', 'Sensor_ID', 'Maanden']], use_container_width=True, hide_index=True)
                else:
                    st.success("Geen gaten gevonden op sensorniveau.")
            
            elif "Waarden" in fout_type:
                # OOK HIER DE CHECK TOEVOEGEN
                if not sens_spikes.empty:
                    st.dataframe(sens_spikes[['Categorie', 'Meter_Type', 'Sensor_ID', 'Maand', 'Waarde']], use_container_width=True, hide_index=True)
                else:
                    st.info("Geen extreme waarden gevonden op sensorniveau.")
            elif "Duplicaten" in fout_type:

                # 1. Voorbereiding: Omschrijving voor vergelijking (niet voor weergave)
                df_temp = df.copy()
                df_temp['Omschrijving_Comp'] = df_temp['Omschrijving'].fillna('GEEN_OMSCHRIJVING')
                data_cols = MONTHS
                check_cols = ['Sensor_ID', 'Omschrijving_Comp'] + data_cols
                
                # 2. Identificeer duplicaten per groep
                df_temp['Counts_Per_Groep'] = df_temp.groupby(['Categorie'] + check_cols)['Sensor_ID'].transform('count')
                
                # 3. Tabel 1: Duplicaten BINNEN dezelfde categorie
                interne_dupes = df_temp[df_temp['Counts_Per_Groep'] > 1].copy()
                
                if not interne_dupes.empty:
                    # Groeperen voor samenvatting
                    summary_int = interne_dupes.groupby(['Categorie'] + check_cols).size().reset_index(name='Aantal_Voorkomens')
                    # Kolommen herordenen: Aantal eerst, dan data, dan groep
                    cols_order = ['Aantal_Voorkomens','Sensor_ID', 'Categorie'] + data_cols
                    st.warning("Duplicaten binnen dezelfde categorie:")
                    st.dataframe(summary_int[cols_order], use_container_width=True, hide_index=True)
                else:
                    st.success("Geen duplicaten gevonden binnen dezelfde categorieën.")
                
                # 4. Tabel 2: Cross-categorie duplicaten
                # Groeperen op 'check_cols' (ID+Omschrijving+Data) om te zien of ze in verschillende 'Categorie' staan
                cross_dupes = df_temp.groupby(check_cols)['Categorie'].unique().reset_index()
                cross_dupes['Aantal_Categorieën'] = cross_dupes['Categorie'].apply(len)
                cross_result = cross_dupes[cross_dupes['Aantal_Categorieën'] > 1].copy()
                
                if not cross_result.empty:
                    # We tellen hoe vaak deze combinatie voorkomt in de originele dataset
                    counts = df_temp.groupby(check_cols).size().reset_index(name='Totaal_Voorkomens')
                    
                    # We mergen dit terug naar onze cross_result op basis van de check_cols
                    cross_result = cross_result.merge(counts, on=check_cols, how='left')
                    
                    # Kolom met categorieën netjes samenvoegen
                    cross_result['Categorieën'] = cross_result['Categorie'].apply(lambda x: ', '.join(x))
                    
                    # Kolomvolgorde: Totaal eerst, dan data, dan de lijst met groepen
                    cols_order_cross = ['Totaal_Voorkomens', 'Sensor_ID', 'Categorieën'] + data_cols
                    
                    st.error("Duplicaten in verschillende categorieën:")
                    st.dataframe(cross_result[cols_order_cross], use_container_width=True, hide_index=True)
                else:
                    st.info("Geen duplicaten in verschillende categorieën gevonden.")