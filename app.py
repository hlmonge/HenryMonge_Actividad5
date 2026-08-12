import math
import requests
import pandas as pd
import streamlit as st
import folium
from streamlit_folium import st_folium
from pathlib import Path

# ─────────────────────────────────────────────
# CONFIGURACIÓN
# ─────────────────────────────────────────────
CSV_PATH = Path(__file__).parent / "estaciones.csv"
OVERPASS_URL = "https://overpass-api.de/api/interpreter"

st.set_page_config(
    page_title="Estaciones Policiales - Honduras",
    page_icon="🚔",
    layout="wide",
)


# ─────────────────────────────────────────────
# FÓRMULA DE HAVERSINE
# ─────────────────────────────────────────────
def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distancia en km entre dos coordenadas geográficas."""
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
def fetch_overpass() -> list[dict]:
    """Obtiene estaciones policiales de Honduras desde OpenStreetMap."""
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
    """Carga estaciones: primero OSM, luego CSV local como respaldo."""
    # 1. Intentar Overpass (OSM)
    datos_osm = fetch_overpass()
    if len(datos_osm) >= 5:
        df = pd.DataFrame(datos_osm)
        # Guardar para uso offline
        try:
            df.to_csv(CSV_PATH, index=False)
        except Exception:
            pass
        return df

    # 2. Usar CSV local (siempre disponible)
    if CSV_PATH.exists():
        df = pd.read_csv(CSV_PATH)
        # Limpiar columna vacía si la hay
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

    # Todas las estaciones (gris/azul pequeño)
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

    # Las 3 más cercanas (verde con popup)
    colores = ["#198754", "#0d6efd", "#fd7e14"]
    iconos = ["1", "2", "3"]
    for i, (_, row) in enumerate(df_cercanas.iterrows()):
        folium.Marker(
            location=[row["lat"], row["lon"]],
            popup=folium.Popup(
                f"<b>#{i+1} {row['nombre']}</b><br>"
                f"📍 {row.get('ciudad','')}, {row.get('departamento','')}<br>"
                f"📏 {row['distancia_km']} km",
                max_width=250,
            ),
            tooltip=f"#{i+1} — {row['nombre']} ({row['distancia_km']} km)",
            icon=folium.DivIcon(
                html=f"""<div style="
                    background:{colores[i]};color:white;
                    border-radius:50%;width:28px;height:28px;
                    display:flex;align-items:center;justify-content:center;
                    font-weight:bold;font-size:14px;
                    border:2px solid white;box-shadow:0 2px 6px rgba(0,0,0,.4);">
                    {iconos[i]}</div>""",
                icon_size=(28, 28),
                icon_anchor=(14, 14),
            ),
        ).add_to(m)

    # Ubicación del usuario
    folium.Marker(
        location=[lat_usuario, lon_usuario],
        tooltip="Tu ubicación",
        icon=folium.Icon(color="red", icon="user", prefix="fa"),
    ).add_to(m)

    # Líneas de conexión al más cercano
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

    # Cargar datos
    with st.spinner("Cargando estaciones policiales..."):
        df = cargar_estaciones()

    # Sidebar — fuente de datos
    with st.sidebar:
        st.markdown("### ℹ️ Información")
        st.success(f"✅ **{len(df)}** estaciones cargadas")
        st.info("Datos: OpenStreetMap + base local verificada")
        st.markdown("---")
        st.markdown("**Coordenadas de referencia:**")
        st.code("Tegucigalpa: 14.0818, -87.2068\nSan Pedro Sula: 15.5036, -88.0256\nLa Ceiba: 15.7745, -86.7906\nComayagua: 14.4490, -87.6395\nCholuteca: 13.2998, -87.1917")
        st.markdown("---")
        n_resultados = st.slider("Mostrar las N más cercanas", 1, 10, 3)

    # ── Formulario de búsqueda ──
    col1, col2, col3 = st.columns([2, 2, 1])
    with col1:
        lat = st.number_input(
            "Latitud",
            value=14.0818,
            format="%.6f",
            step=0.0001,
            help="Latitud de tu ubicación (ej: 14.0818)",
        )
    with col2:
        lon = st.number_input(
            "Longitud",
            value=-87.2068,
            format="%.6f",
            step=0.0001,
            help="Longitud de tu ubicación (ej: -87.2068)",
        )
    with col3:
        st.markdown("<br>", unsafe_allow_html=True)
        buscar = st.button("🔍 Buscar", type="primary", use_container_width=True)

    # ── Resultados ──
    if buscar:
        if not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
            st.error("Coordenadas fuera de rango. Verifica latitud (-90 a 90) y longitud (-180 a 180).")
            return

        cercanas = encontrar_cercanas(df, lat, lon, n=n_resultados)

        st.markdown("---")
        st.markdown(f"### 📍 Las **{n_resultados}** estaciones más cercanas a ({lat:.4f}, {lon:.4f})")

        # Tarjetas de resultado
        cols = st.columns(min(n_resultados, 3))
        medallas = ["🥇", "🥈", "🥉"] + ["📌"] * 7
        for i, (_, row) in enumerate(cercanas.iterrows()):
            col_idx = i % 3
            with cols[col_idx]:
                ciudad = row.get("ciudad", "") or ""
                depto = row.get("departamento", "") or ""
                ubicacion = f"{ciudad}, {depto}".strip(", ")
                st.markdown(f"""
                <div style='background:#f8f9fa;border-left:4px solid #003087;
                            border-radius:6px;padding:0.8rem 1rem;margin-bottom:0.5rem'>
                    <div style='font-size:1.4rem'>{medallas[i]} <b>#{i+1}</b></div>
                    <div style='font-size:0.95rem;font-weight:600;color:#003087'>{row['nombre']}</div>
                    <div style='color:#555;font-size:0.85rem'>📍 {ubicacion}</div>
                    <div style='margin-top:4px;font-size:1rem;color:#198754;font-weight:bold'>
                        📏 {row['distancia_km']} km
                    </div>
                </div>
                """, unsafe_allow_html=True)

        # Mapa
        st.markdown("### 🗺️ Mapa")
        mapa = crear_mapa(df, cercanas, lat, lon)
        st_folium(mapa, width=None, height=480, returned_objects=[])

        # Tabla completa
        with st.expander("📋 Ver tabla de resultados"):
            tabla = cercanas[["nombre", "ciudad", "departamento", "distancia_km"]].copy()
            tabla.columns = ["Estación", "Ciudad", "Departamento", "Distancia (km)"]
            tabla.index = tabla.index + 1
            st.dataframe(tabla, use_container_width=True)

        # Exportar
        csv_out = cercanas.to_csv(index=False).encode("utf-8")
        st.download_button(
            "⬇️ Descargar resultados (CSV)",
            data=csv_out,
            file_name="estaciones_cercanas.csv",
            mime="text/csv",
        )

    else:
        # Mapa inicial centrado en Honduras
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
        st.info("👆 Ingresa tus coordenadas y presiona **Buscar** para encontrar las estaciones más cercanas.")


if __name__ == "__main__":
    main()
