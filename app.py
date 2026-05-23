import streamlit as st
import pandas as pd
import numpy as np
import re

# Healthy Workers Styling
st.set_page_config(page_title="Healthy Workers - Data Audit", layout="wide")
st.markdown("""
    <style>
    .main { background-color: #F8F9FA; }
    h1 { color: #0A192F !important; font-family: sans-serif; }
    .category-header { background-color: #0A192F; color: white; padding: 10px; border-radius: 5px; margin-top: 20px; font-weight: bold; }
    .stApp { padding: 20px; }
    </style>
""", unsafe_allow_html=True)

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

def parse_data(file_obj):
    df = pd.read_excel(file_obj, header=None, engine='openpyxl')
    rename_dict = {0: 'Sensor_ID', 1: 'Omschrijving'}
    for i, month in enumerate(MONTHS): rename_dict[i + 2] = month
    df = df.rename(columns=rename_dict)
    
    df['Type'] = 'Overig'
    curr_group = "Tussenmeters"
    
    for idx, row in df.iterrows():
        val = str(row['Sensor_ID']).strip()
        if val in ['Hoofdmeters', 'Tussenmeters', 'Aanvullende elektriciteitsstatistieken']:
            curr_group = val
        elif val.startswith('- ') and not val.startswith('--'):
            df.at[idx, 'Type'] = 'Groep_Totaal'
            df.at[idx, 'Grote_Groep'] = curr_group
            # Pak de hele tekst na het minteken
            df.at[idx, 'Energie_Type'] = val.replace('- ', '').strip()
        elif val.startswith('--'):
            df.at[idx, 'Type'] = 'Sensor'
            df.at[idx, 'Grote_Groep'] = curr_group
            
    df['Energie_Type'] = df['Energie_Type'].fillna(method='ffill')
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
        e_type = str(row['Energie_Type']).lower() # Maak alles lowercase voor de match
    
        # Bepaal het type gebaseerd op sleutelwoorden in de naam
        if 'elektriciteit' in e_type or 'kwh' in e_type:
            cat = 'Elektriciteit'
        elif 'gas' in e_type:
            cat = 'Gas'
        elif 'water' in e_type:
            cat = 'Water'
        elif 'warmte' in e_type:
            cat = 'Warmte'
        elif 'koeling' in e_type:
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

st.title("Healthy Workers — Data Dashboard")
uploaded_files = st.file_uploader("Upload Excel-bestanden", type=["xlsx"], accept_multiple_files=True)

if uploaded_files:
    # 1. Dictionary aanmaken
    buildings_dict = {}
    for f in uploaded_files:
        # Hier kun je de logica aanpassen aan jouw specifieke bestandsnaam
        # Bijv: als de naam 'Gebouw 6' bevat, pakken we dat eruit
        name = f.name.split("-")[3].strip() if len(f.name.split("-")) > 3 else f.name
        buildings_dict[name] = f
    
    # 2. Sorteren op natuurlijke wijze (Gebouw 2 komt voor Gebouw 10)
    def natural_sort_key(s):
        return [int(text) if text.isdigit() else text.lower() for text in re.split('([0-9]+)', s)]
    
    sorted_building_names = sorted(buildings_dict.keys(), key=natural_sort_key)
    
    # 3. Tabs aanmaken op basis van gesorteerde lijst
    tabs = st.tabs(sorted_building_names)
    
    # 4. De loop koppelen aan de gesorteerde tabs
    for idx, tab_name in enumerate(tabs):
        building_name = sorted_building_names[idx]
        with tab_name:
            df = parse_data(buildings_dict[building_name])
            df = df.dropna(subset=['Sensor_ID'])
            df = df[df['Sensor_ID'].astype(str).str.strip() != '']
            fout_type = st.radio("Selecteer type:", ["Data Gaten", "Extreme Waarden", "Duplicaten"], key=f"r_{tab_name}", horizontal=True)
            
            # Anomalieën op Groepsniveau
            agg_gaps, agg_spikes = get_anomalies_robuust(df[df['Type'] == 'Groep_Totaal'], True)
            
            if "Gaten" in fout_type:
                st.subheader("Anomalieën op Groepsniveau")
                st.dataframe(agg_gaps[['Grote_Groep', 'Energie_Type', 'Maanden']], use_container_width=True, hide_index=True)
            elif "Waarden" in fout_type:
                st.subheader("Anomalieën op Groepsniveau")
                st.dataframe(agg_spikes[['Grote_Groep', 'Energie_Type', 'Maand', 'Waarde']], use_container_width=True, hide_index=True)
            
            # Detail-Audit
            st.subheader("Anomalieën op Sensorniveau")
            sens_gaps, sens_spikes = get_anomalies_robuust(df[df['Type'] == 'Sensor'], False)
            if "Gaten" in fout_type:
                st.dataframe(sens_gaps[['Grote_Groep', 'Energie_Type', 'Sensor_ID', 'Maanden']], use_container_width=True, hide_index=True)
            elif "Waarden" in fout_type:
                st.dataframe(sens_spikes[['Grote_Groep', 'Energie_Type', 'Sensor_ID', 'Maand', 'Waarde']], use_container_width=True, hide_index=True)
            elif "Duplicaten" in fout_type:
                # 1. Definieer de basis voor vergelijking
                data_cols = MONTHS 
                
                # 2. We kijken naar ID en de Omschrijving (als die er is)
                # We vervangen lege omschrijvingen tijdelijk door een placeholder om vergelijking mogelijk te maken
                df_temp = df.copy()
                df_temp['Omschrijving'] = df_temp['Omschrijving'].fillna('GEEN_OMSCHRIJVING')
                
                # 3. We groeperen op Grote_Groep (Hoofdmeters/Tussenmeters) 
                # én op de data (ID + Omschrijving + maanden)
                cols_to_check = ['Grote_Groep', 'Sensor_ID', 'Omschrijving'] + data_cols
                
                # Filter op rijen die vaker dan 1x voorkomen in die specifieke groep
                dupe_mask = df_temp.duplicated(subset=cols_to_check, keep=False)
                dupes = df_temp[dupe_mask].copy()
                
                if not dupes.empty:
                    # Aantal bepalen
                    summary = dupes.groupby(cols_to_check).size().reset_index(name='Aantal_Voorkomens')
                    
                    # Kolommen sorteren voor presentatie
                    cols = ['Aantal_Voorkomens'] + ['Grote_Groep', 'Sensor_ID', 'Omschrijving'] + data_cols
                    summary = summary[cols]
                    
                    st.warning(f"Aantal unieke duplicaten per sectie gevonden: {len(summary)}")
                    st.dataframe(summary, use_container_width=True, hide_index=True)
                else:
                    st.success("Geen dubbele rijen gevonden binnen dezelfde categorie.")