/**
 * Shader / stylization metadata for future Cesium, Three.js, and Blender/Blosm.
 * Mirrors catmod/spatial/presets.py. Does not load WebGL.
 */
window.CATMOD_RENDER_PRESETS = {
  default: "PHOTOREAL_DEFAULT",
  storey_height_m: 3.5,
  presets: {
    VICE_CITY_NEON: {
      id: "VICE_CITY_NEON",
      label: "Vice City Neon",
      engine_hint: "stylized_pbr",
      palette: {
        sky: "#12061F",
        fog: "#3B0A58",
        emissive_a: "#FF2BD6",
        emissive_b: "#00F5FF",
        building: "#1B1030",
        water: "#5B2CFF",
        risk_low: "#00F5FF",
        risk_moderate: "#C77DFF",
        risk_high: "#FF2BD6"
      },
      flood_heatmap: "purple_cyan",
      material: {
        wetness: 0.85,
        roughness: 0.18,
        metalness: 0.35,
        rain_ripples: true,
        neon_bloom: 1.4,
        outline_width: 0
      }
    },
    GTA_STYLIZED: {
      id: "GTA_STYLIZED",
      label: "GTA Stylized",
      engine_hint: "cel_shaded",
      palette: {
        sky: "#7EC8E3",
        fog: "#F2D0A4",
        emissive_a: "#FF6B00",
        emissive_b: "#FFE566",
        building: "#E8D5B7",
        water: "#2E86AB",
        risk_low: "#2A9D4A",
        risk_moderate: "#F4A259",
        risk_high: "#D62828"
      },
      flood_heatmap: "high_contrast_hazard",
      material: {
        wetness: 0.15,
        roughness: 0.85,
        metalness: 0.05,
        rain_ripples: false,
        neon_bloom: 0,
        outline_width: 2,
        cel_bands: 3
      }
    },
    PHOTOREAL_DEFAULT: {
      id: "PHOTOREAL_DEFAULT",
      label: "Photoreal",
      aliases: ["PHOTOREAL"],
      engine_hint: "photoreal_3d_tiles",
      palette: {
        sky: "#87CEEB",
        fog: "#C9D6DF",
        building: "#B8B0A8",
        water: "#4C8DDE",
        risk_low: "#2A9D4A",
        risk_moderate: "#E0B825",
        risk_high: "#C1121F"
      },
      flood_heatmap: "true_color_inundation",
      material: {
        wetness: 0.35,
        roughness: 0.55,
        metalness: 0.12,
        use_satellite_textures: true,
        use_google_3d_tiles: true,
        outline_width: 0
      }
    }
  }
};
