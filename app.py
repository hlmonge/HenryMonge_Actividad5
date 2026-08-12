import math
import requests
import pandas as pd
import streamlit as st
import folium
from streamlit_folium import st_folium
from streamlit_js_eval import get_geolocation
from pathlib import Path

# ─────────────────────────────────────────────
# CONFIGURACIÓN
# ─────────────────────────────────────────────
CSV_PATH = Path(__file__).parent / "estaciones.csv"
OVERPASS_URL = "https://overpass-api.de/api/interpreter"

# Paleta de colores para N marcadores (sin límite)
COLORES = [
    "#198754", "#0d6efd", "#fd7e14", "#6f42c1",
    "#d63384", "#20c997", "#ffc107", "#0dcaf0",
    "#dc3545", "#6c757d",
]
MEDALLAS = ["🥇", "🥈", "🥉"] + ["📌"] * 17

st.set_page_config(
    page_title="Estaciones Policiales - Honduras",
    page_icon="🚔",
    layout="wide",
)


# ─────────────────────────────────────────────
# FÓRMULA DE HAVERSINE
# ─────────────────────────────────────────────
def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lam = math.radians(lon2 - lon1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lam / 2) ** 2
    return round(2 * R * math.asin(math.sqrt(a)), 2)


# ─────────────────────────────────────────────
# CARGA DE DATOS
# ─────────────────────────────────────────────
@st.cache_data(show_spinner=False, ttl=86400)
def fetch_overpass() -> list:
    query = """
    [out:json][timeout:30];
    area["name"="Honduras"]["boundary"="administrative"]["admin_level"="2"]->.hn;
    (
      node["amenity"="police"](area.hn);
      way["amenity"="police"](area.hn);
    );
    out center;
    """
    try:
        r = requests.post(OVERPASS_URL, data={"data": query}, timeout=30)
        r.raise_for_status()
        elementos = r.json().get("elements", [])
        estaciones = []
        for el in elementos:
            tags = el.get("tags", {})
            nombre = (
                tags.get("name")
                or tags.get("name:es")
                or tags.get("operator")
                or "Estación Policial"
            )
            if el["type"] == "node":
                lat, lon = el["lat"], el["lon"]
            else:
                centro = el.get("center", {})
                lat = centro.get("lat")
                lon = centro.get("lon")
            if lat and lon:
                estaciones.append({
                    "nombre": nombre,
                    "lat": float(lat),
                    "lon": float(lon),
                    "ciudad": tags.get("addr:city", ""),
                    "departamento": tags.get("addr:state", ""),
                })
        return estaciones
    except Exception:
        return []


@st.cache_data(show_spinner=False)
def cargar_estaciones() -> pd.DataFrame:
    datos_osm = fetch_overpass()
    if len(datos_osm) >= 5:
        df = pd.DataFrame(datos_osm)
        try:
            df.to_csv(CSV_PATH, index=False)
        except Exception:
            pass
        return df

    if CSV_PATH.exists():
        df = pd.read_csv(CSV_PATH)
        df = df.loc[:, ~df.columns.str.startswith("Unnamed")]
        df = df.dropna(subset=["lat", "lon"])
        return df

    st.error("No se pudo cargar la base de datos de estaciones.")
    st.stop()


# ─────────────────────────────────────────────
# LÓGICA DE BÚSQUEDA
# ─────────────────────────────────────────────
def encontrar_cercanas(df: pd.DataFrame, lat: float, lon: float, n: int = 3) -> pd.DataFrame:
    df = df.copy()
    df["distancia_km"] = df.apply(
        lambda r: haversine(lat, lon, r["lat"], r["lon"]), axis=1
    )
    return df.nsmallest(n, "distancia_km").reset_index(drop=True)


# ─────────────────────────────────────────────
# MAPA FOLIUM
# ─────────────────────────────────────────────
def crear_mapa(
    df_todas: pd.DataFrame,
    df_cercanas: pd.DataFrame,
    lat_usuario: float,
    lon_usuario: float,
) -> folium.Map:
    m = folium.Map(location=[lat_usuario, lon_usuario], zoom_start=9, tiles="OpenStreetMap")

    # Todas las estaciones (fondo gris)
    for _, row in df_todas.iterrows():
        folium.CircleMarker(
            location=[row["lat"], row["lon"]],
            radius=5,
            color="#6c757d",
            fill=True,
            fill_color="#6c757d",
            fill_opacity=0.5,
            tooltip=row["nombre"],
        ).add_to(m)

    # N más cercanas — colores dinámicos con módulo para evitar IndexError
    for i, (_, row) in enumerate(df_cercanas.iterrows()):
        color = COLORES[i % len(COLORES)]
        ciudad = row.get("ciudad", "") or ""
        depto = row.get("departamento", "") or ""
        folium.Marker(
            location=[row["lat"], row["lon"]],
            popup=folium.Popup(
                f"<b>#{i+1} {row['nombre']}</b><br>"
                f"📍 {ciudad}, {depto}<br>"
                f"📏 {row['distancia_km']} km",
                max_width=260,
            ),
            tooltip=f"#{i+1} — {row['nombre']} ({row['distancia_km']} km)",
            icon=folium.DivIcon(
                html=f"""<div style="
                    background:{color};color:white;
                    border-radius:50%;width:28px;height:28px;
                    display:flex;align-items:center;justify-content:center;
                    font-weight:bold;font-size:13px;
                    border:2px solid white;box-shadow:0 2px 6px rgba(0,0,0,.4);">
                    {i+1}</div>""",
                icon_size=(28, 28),
                icon_anchor=(14, 14),
            ),
        ).add_to(m)

    # Marcador del usuario
    folium.Marker(
        location=[lat_usuario, lon_usuario],
        tooltip="📍 Tu ubicación",
        icon=folium.Icon(color="red", icon="user", prefix="fa"),
    ).add_to(m)

    # Líneas punteadas hacia cada cercana
    for _, row in df_cercanas.iterrows():
        folium.PolyLine(
            locations=[[lat_usuario, lon_usuario], [row["lat"], row["lon"]]],
            color="#dc3545",
            weight=1.5,
            opacity=0.5,
            dash_array="6",
        ).add_to(m)

    return m


# ─────────────────────────────────────────────
# INTERFAZ PRINCIPAL
# ─────────────────────────────────────────────
def main():
    # Header
    st.markdown("""
        <div style='text-align:center;padding:1rem 0 0.5rem'>
            <h1 style='color:#003087;margin:0'>🚔 Estaciones Policiales Cercanas</h1>
            <p style='color:#555;margin:0'>Honduras — Policía Nacional</p>
        </div>
        <hr style='margin:0.5rem 0 1.5rem'>
    """, unsafe_allow_html=True)

    # Inicializar session state
    if "lat" not in st.session_state:
        st.session_state["lat"] = 14.0818
    if "lon" not in st.session_state:
        st.session_state["lon"] = -87.2068
    if "gps_solicitado" not in st.session_state:
        st.session_state["gps_solicitado"] = False
    if "buscar" not in st.session_state:
        st.session_state["buscar"] = False

    # Cargar datos
    with st.spinner("Cargando estaciones policiales..."):
        df = cargar_estaciones()

    # Sidebar
    with st.sidebar:
        st.markdown("### ℹ️ Información")
        st.success(f"✅ **{len(df)}** estaciones cargadas")
        st.info("Datos: OpenStreetMap + base local verificada")
        st.markdown("---")
        st.markdown("**Coordenadas de referencia (manual):**")
        st.code(
            "Tegucigalpa:    14.0818, -87.2068\n"
            "San Pedro Sula: 15.5036, -88.0256\n"
            "La Ceiba:       15.7745, -86.7906\n"
            "Comayagua:      14.4490, -87.6395\n"
            "Choluteca:      13.2998, -87.1917"
        )
        st.markdown("---")
        n_resultados = st.slider("Mostrar las N más cercanas", 1, 10, 3)

    # ── GPS ──────────────────────────────────────
    st.markdown("#### 📡 Obtener ubicación")

    col_gps, col_info = st.columns([1, 3])
    with col_gps:
        if st.button("📍 Usar mi GPS", type="primary", use_container_width=True):
            st.session_state["gps_solicitado"] = True
            st.session_state["buscar"] = False

    with col_info:
        st.caption(
            "Presiona **Usar mi GPS** para detectar tu ubicación automáticamente. "
            "Tu navegador pedirá permiso — acéptalo. "
            "El GPS **debe estar activo** en tu dispositivo."
        )

    # Intentar obtener GPS si fue solicitado
    if st.session_state["gps_solicitado"]:
        with st.spinner("⏳ Esperando permiso GPS del dispositivo..."):
            loc = get_geolocation()

        if loc and "coords" in loc:
            st.session_state["lat"] = round(loc["coords"]["latitude"], 6)
            st.session_state["lon"] = round(loc["coords"]["longitude"], 6)
            st.session_state["gps_solicitado"] = False
            st.session_state["buscar"] = True
            st.success(
                f"✅ GPS obtenido: **{st.session_state['lat']}, {st.session_state['lon']}**"
            )
        else:
            st.warning(
                "⚠️ No se pudo obtener el GPS. Verifica que:\n"
                "- El GPS/Localización está **activado** en tu dispositivo.\n"
                "- Le diste **permiso** al navegador cuando lo solicitó.\n"
                "- Estás en una conexión **HTTPS** (Streamlit Cloud cumple esto).\n\n"
                "También puedes ingresar las coordenadas manualmente abajo."
            )

    st.markdown("---")

    # ── Formulario manual ──────────────────────
    st.markdown("#### 🗺️ Coordenadas (manual o desde GPS)")
    col1, col2, col3 = st.columns([2, 2, 1])
    with col1:
        lat = st.number_input(
            "Latitud",
            value=st.session_state["lat"],
            format="%.6f",
            step=0.0001,
            key="input_lat",
        )
    with col2:
        lon = st.number_input(
            "Longitud",
            value=st.session_state["lon"],
            format="%.6f",
            step=0.0001,
            key="input_lon",
        )
    with col3:
        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("🔍 Buscar", type="primary", use_container_width=True):
            st.session_state["buscar"] = True
            st.session_state["lat"] = lat
            st.session_state["lon"] = lon

    # ── Resultados ────────────────────────────
    if st.session_state["buscar"]:
        lat_busq = st.session_state["lat"]
        lon_busq = st.session_state["lon"]

        if not (-90 <= lat_busq <= 90) or not (-180 <= lon_busq <= 180):
            st.error("Coordenadas fuera de rango. Verifica latitud (-90 a 90) y longitud (-180 a 180).")
            return

        cercanas = encontrar_cercanas(df, lat_busq, lon_busq, n=n_resultados)

        st.markdown("---")
        st.markdown(
            f"### 📍 Las **{n_resultados}** estaciones más cercanas "
            f"a ({lat_busq:.4f}, {lon_busq:.4f})"
        )

        # Tarjetas — máximo 3 columnas por fila
        n_cols = min(n_resultados, 3)
        cols = st.columns(n_cols)
        for i, (_, row) in enumerate(cercanas.iterrows()):
            ciudad = row.get("ciudad", "") or ""
            depto = row.get("departamento", "") or ""
            ubicacion = f"{ciudad}, {depto}".strip(", ")
            color = COLORES[i % len(COLORES)]
            medalla = MEDALLAS[i]
            with cols[i % n_cols]:
                st.markdown(f"""
                <div style='background:#f8f9fa;border-left:4px solid {color};
                            border-radius:6px;padding:0.8rem 1rem;margin-bottom:0.6rem'>
                    <div style='font-size:1.3rem'>{medalla} <b>#{i+1}</b></div>
                    <div style='font-size:0.95rem;font-weight:600;color:#003087'>{row['nombre']}</div>
                    <div style='color:#555;font-size:0.85rem'>📍 {ubicacion}</div>
                    <div style='margin-top:4px;font-size:1rem;color:{color};font-weight:bold'>
                        📏 {row['distancia_km']} km
                    </div>
                </div>
                """, unsafe_allow_html=True)

        # Mapa
        st.markdown("### 🗺️ Mapa")
        mapa = crear_mapa(df, cercanas, lat_busq, lon_busq)
        st_folium(mapa, width=None, height=500, returned_objects=[])

        # Tabla
        with st.expander("📋 Ver tabla completa de resultados"):
            tabla = cercanas[["nombre", "ciudad", "departamento", "distancia_km"]].copy()
            tabla.columns = ["Estación", "Ciudad", "Departamento", "Distancia (km)"]
            tabla.index = tabla.index + 1
            st.dataframe(tabla, use_container_width=True)

        # Descargar
        csv_out = cercanas.to_csv(index=False).encode("utf-8")
        st.download_button(
            "⬇️ Descargar resultados (CSV)",
            data=csv_out,
            file_name="estaciones_cercanas.csv",
            mime="text/csv",
        )

    else:
        # Mapa inicial — Honduras completo
        st.markdown("### 🗺️ Mapa de Honduras — Estaciones Policiales")
        m_init = folium.Map(location=[14.5, -86.9], zoom_start=7, tiles="OpenStreetMap")
        for _, row in df.iterrows():
            folium.CircleMarker(
                location=[row["lat"], row["lon"]],
                radius=6,
                color="#003087",
                fill=True,
                fill_color="#0d6efd",
                fill_opacity=0.7,
                tooltip=row["nombre"],
            ).add_to(m_init)
        st_folium(m_init, width=None, height=480, returned_objects=[])
        st.info(
            "👆 Presiona **📍 Usar mi GPS** para detectar tu ubicación, "
            "o ingresa las coordenadas manualmente y presiona **🔍 Buscar**."
        )


if __name__ == "__main__":
    main()
