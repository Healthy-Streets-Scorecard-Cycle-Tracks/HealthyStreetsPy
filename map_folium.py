from typing import Dict, Optional, Tuple

import folium
from branca.element import Element, MacroElement
from folium.elements import JSCSSMixin
from jinja2 import Template

from config import (
    CYCLE_ROUTES_JSON,
    LCC_TFL_GEOJSON,
    MAP_COLORS,
    ONE_WAY_DASH,
    TFL_GEOJSON,
    get_route_style,
    logger,
)
from data_processing import line_length_m
from geo_utils import geojson_geom_types, load_geojson

_CYCLE_ROUTES_CACHE = None


def _load_cycle_routes_once() -> Optional[dict]:
    global _CYCLE_ROUTES_CACHE
    if _CYCLE_ROUTES_CACHE is not None:
        return _CYCLE_ROUTES_CACHE
    data = load_geojson(CYCLE_ROUTES_JSON)
    if data:
        try:
            logger.info("Loaded CycleRoutes geojson features=%s", len(data.get("features", [])))
        except Exception:
            logger.info("Loaded CycleRoutes geojson")
    _CYCLE_ROUTES_CACHE = data
    return _CYCLE_ROUTES_CACHE


class GeomanControl(JSCSSMixin, MacroElement):
    _template = Template(
        """
        {% macro script(this, kwargs) %}
            {{ this._parent.get_name() }}.pm.addControls({
                position: {{ this.position|tojson }},
                drawPolyline: false,
                drawPolygon: false,
                drawCircle: false,
                drawMarker: false,
                drawCircleMarker: false,
                drawRectangle: false,
                editMode: false,
                dragMode: false,
                cutPolygon: false,
                removalMode: false,
                rotateMode: false,
                drawText: false
            });
        {% endmacro %}
        """
    )

    default_js = [
        (
            "leaflet_geoman_js",
            "https://unpkg.com/@geoman-io/leaflet-geoman-free@2.17.0/dist/leaflet-geoman.min.js",
        )
    ]
    default_css = [
        (
            "leaflet_geoman_css",
            "https://unpkg.com/@geoman-io/leaflet-geoman-free@2.17.0/dist/leaflet-geoman.css",
        )
    ]

    def __init__(self, position: str = "topleft"):
        super().__init__()
        self._name = "GeomanControl"
        self.position = position


class ShinyBridge(MacroElement):
    _template = Template(
        """
        {% macro script(this, kwargs) %}
            var hssBaseLayers = {};
            {% for name, layer in this.base_layers.items() %}
            hssBaseLayers[{{ name|tojson }}] = {{ layer }};
            {% endfor %}
            var hssOverlayLayers = {};
            {% for name, layer in this.overlay_layers.items() %}
            hssOverlayLayers[{{ name|tojson }}] = {{ layer }};
            {% endfor %}
            var hssOneWayDash = {{ this.one_way_dash|tojson }};

            function hssWireHandlers(map, layerGroup) {
                function sendMessage(type, payload) {
                    if (type === "edited_geojson") {
                        console.log("HSS iframe sendMessage edited_geojson", payload);
                    }
                    if (window.parent && window.parent.postMessage) {
                        window.parent.postMessage({ type: type, payload: payload }, "*");
                    }
                }
                function sendSelected(feature, latlng) {
                    var props = feature && feature.properties ? feature.properties : {};
                    sendMessage("selected_route", {
                        guid: props.guid,
                        properties: props,
                        latlng: latlng
                    });
                }

                function resetAllStyles() {
                    if (layerGroup.eachLayer) {
                        layerGroup.eachLayer(function(l) {
                            if (l && l.options && l.options._hssOriginalStyle && l.setStyle) {
                                l.setStyle(l.options._hssOriginalStyle);
                            }
                        });
                    }
                    if (map && map.eachLayer) {
                        map.eachLayer(function(l) {
                            if (l && l.options && l.options._hssOriginalStyle && l.setStyle) {
                                l.setStyle(l.options._hssOriginalStyle);
                            }
                        });
                    }
                    if (window.hssSelectedLayer && window.hssSelectedLayer.options && window.hssSelectedLayer.options._hssOriginalStyle) {
                        if (window.hssSelectedLayer.setStyle) {
                            window.hssSelectedLayer.setStyle(window.hssSelectedLayer.options._hssOriginalStyle);
                        }
                    }
                    applyHighlightStyles();
                }

                function applyHighlightStyles() {
                    if (!window.hssHighlightGuids) return;
                    var dimOpacity = (typeof window.hssHighlightDimOpacity === 'number') ? window.hssHighlightDimOpacity : 0.3;
                    var total = 0;
                    var highlighted = 0;
                    var dimmed = 0;
                    function maybeHighlight(layer) {
                        if (!layer || !layer.feature || !layer.feature.properties) return;
                        var guid = layer.feature.properties.guid;
                        if (!guid) return;
                        total += 1;
                        if (window.hssSelectedLayer === layer) return;
                        if (!layer.options._hssOriginalStyle && layer.options) {
                            layer.options._hssOriginalStyle = {
                                color: layer.options.color,
                                weight: layer.options.weight,
                                opacity: layer.options.opacity
                            };
                        }
                        if (!layer.setStyle) return;
                        if (window.hssHighlightGuids[guid]) {
                            highlighted += 1;
                            layer.setStyle({
                                color: layer.options._hssOriginalStyle.color,
                                weight: layer.options._hssOriginalStyle.weight,
                                opacity: 0.9,
                                dashArray: layer.options._hssOriginalStyle.dashArray || null
                            });
                        } else if (layer.options._hssOriginalStyle) {
                            dimmed += 1;
                            layer.setStyle({
                                color: layer.options._hssOriginalStyle.color,
                                weight: layer.options._hssOriginalStyle.weight,
                                opacity: dimOpacity,
                                dashArray: layer.options._hssOriginalStyle.dashArray || null
                            });
                        }
                    }
                    if (layerGroup && layerGroup.eachLayer) {
                        layerGroup.eachLayer(function(l) {
                            if (l && l.eachLayer) {
                                l.eachLayer(function(child) { maybeHighlight(child); });
                            } else {
                                maybeHighlight(l);
                            }
                        });
                    }
                    if (map && map.eachLayer) {
                        map.eachLayer(function(l) { maybeHighlight(l); });
                    }
                    console.log('HSS iframe highlight applied', { total: total, highlighted: highlighted, dimmed: dimmed, dimOpacity: dimOpacity });
                }

                function bindFeatureLayer(layer) {
                    if (!layer || !layer.feature || !layer.feature.properties || !layer.feature.properties.guid) {
                        return;
                    }
                    layer.off('click');
                    layer.on('click', function(e) {
                        var feature = layer.feature;
                        if (!feature || !feature.properties || !feature.properties.guid) {
                            return;
                        }
                        console.log('HSS iframe layer click', feature.properties.guid);
                        if (window.hssEditingLayer && window.hssEditingLayer.pm) {
                            window.hssEditingLayer.pm.disable();
                        }
                        resetAllStyles();
                        window.hssSelectedLayer = layer;
                        if (!layer.options._hssOriginalStyle) {
                            layer.options._hssOriginalStyle = {
                                color: layer.options.color,
                                weight: layer.options.weight,
                                opacity: layer.options.opacity
                            };
                        }
                        window.hssSelectedStyle = layer.options._hssOriginalStyle;
                        if (layer.setStyle) {
                            layer.setStyle({ color: "{{ this.highlight_color }}", weight: {{ this.highlight_weight }}, opacity: 0.95 });
                        }
                        if (layer.pm) {
                            console.log('HSS iframe enable edit', feature.properties.guid);
                            layer.pm.enable({ preventMarkerRemoval: true, allowSelfIntersection: true });
                            window.hssEditingLayer = layer;
                            setTimeout(function() {
                                logPmOverlays('after enable');
                            }, 0);
                        }
                        sendSelected(feature, e.latlng);
                    });
                    if (layer.pm && layer.feature && layer.feature.properties) {
                        var gid = layer.feature.properties.guid;
                        layer.on('pm:edit', function() {
                            console.log('HSS iframe layer pm:edit', gid);
                        });
                        layer.on('pm:editstart', function() {
                            console.log('HSS iframe layer pm:editstart', gid);
                            logPmOverlays('editstart');
                        });
                        layer.on('pm:editend', function() {
                            console.log('HSS iframe layer pm:editend', gid);
                            logPmOverlays('editend');
                        });
                        layer.on('pm:vertexdragend', function() {
                            console.log('HSS iframe layer pm:vertexdragend', gid);
                            if (layer.toGeoJSON) {
                                var payload = { features: [layer.toGeoJSON()] };
                                console.log('HSS iframe sending edited_geojson (vertexdragend)', payload);
                                sendMessage("edited_geojson", payload);
                            }
                        });
                        layer.on('pm:markerdragend', function() {
                            console.log('HSS iframe layer pm:markerdragend', gid);
                            if (layer.toGeoJSON) {
                                var payload = { features: [layer.toGeoJSON()] };
                                console.log('HSS iframe sending edited_geojson (markerdragend)', payload);
                                sendMessage("edited_geojson", payload);
                            }
                        });
                        layer.on('pm:vertexadded', function() {
                            console.log('HSS iframe layer pm:vertexadded', gid);
                        });
                        layer.on('pm:vertexremoved', function() {
                            console.log('HSS iframe layer pm:vertexremoved', gid);
                        });
                    }
                }

                function bindLayer(layer) {
                    if (!layer) return;
                    if (layer.eachLayer) {
                        layer.eachLayer(function(child) { bindLayer(child); });
                        return;
                    }
                    bindFeatureLayer(layer);
                }

                function findLayerByGuid(guid) {
                    var found = null;
                    if (!layerGroup || !layerGroup.eachLayer) return null;
                    layerGroup.eachLayer(function(l) {
                        if (found) return;
                        if (l && l.feature && l.feature.properties && l.feature.properties.guid === guid) {
                            found = l;
                        }
                    });
                    if (!found) {
                        if (map && map.eachLayer) {
                            map.eachLayer(function(l) {
                                if (found) return;
                                if (l && l.feature && l.feature.properties && l.feature.properties.guid === guid) {
                                    found = l;
                                }
                            });
                        }
                    }
                    if (!found) {
                        console.log('HSS iframe update_style: layer not found for guid', guid);
                    }
                    return found;
                }

                function updateTooltip(layer) {
                    if (!layer || !layer.getTooltip) return;
                    var t = layer.getTooltip();
                    if (!t) return;
                    var props = layer.feature && layer.feature.properties ? layer.feature.properties : {};
                    var name = props.name || "";
                    var dir = props.OneWay || "";
                    var len = props.Length_m !== undefined ? props.Length_m : "";
                    var html = "<b>Name:</b> " + name + "<br><b>Direction:</b> " + dir + "<br><b>Length (m):</b> " + len;
                    t.setContent(html);
                }

                function normalizeLatLngs(coords) {
                    if (!coords || !coords.length) return coords;
                    if (Array.isArray(coords[0]) && Array.isArray(coords[0][0])) {
                        return coords[0].map(function(c) { return L.latLng(c[0], c[1]); });
                    }
                    return coords.map(function(c) { return L.latLng(c[0], c[1]); });
                }

                bindLayer(layerGroup);
                map.on('pm:edit', function(e) {
                    if (e.layer && e.layer.toGeoJSON) {
                        console.log('HSS iframe pm:edit', e.layer);
                        var payload = { features: [e.layer.toGeoJSON()] };
                        console.log('HSS iframe sending edited_geojson', payload);
                        sendMessage("edited_geojson", payload);
                    }
                });

                map.on('pm:create', function(e) {
                    if (e.layer && e.layer.toGeoJSON) {
                        console.log('HSS iframe pm:create', e.layer);
                        var tempId = "tmp-" + Date.now() + "-" + Math.floor(Math.random() * 1000000);
                        e.layer._hssTempId = tempId;
                        if (!window.hssTempLayerMap) window.hssTempLayerMap = {};
                        window.hssTempLayerMap[tempId] = e.layer;
                        if (window.hssEditingLayer && window.hssEditingLayer.pm) {
                            window.hssEditingLayer.pm.disable();
                        }
                        if (e.layer.pm) {
                            setTimeout(function() {
                                e.layer.pm.enable({ allowSelfIntersection: true });
                                window.hssEditingLayer = e.layer;
                                if (e.layer.setStyle) {
                                    e.layer.setStyle({ color: "{{ this.highlight_color }}", weight: {{ this.highlight_weight }}, opacity: 0.95 });
                                }
                            }, 150);
                        }
                        if (e.layer && e.layer.feature) {
                            setTimeout(function() {
                                sendSelected(e.layer.feature, e.layer.getLatLngs ? e.layer.getLatLngs()[0] : null);
                            }, 0);
                        }
                        var gj = e.layer.toGeoJSON();
                        if (!gj.properties) gj.properties = {};
                        gj.properties._temp_id = tempId;
                        console.log('HSS iframe sending created_geojson', gj);
                        sendMessage("created_geojson", gj);
                    }
                });

                map.on('pm:drawstart', function() {
                    if (window.hssEditingLayer && window.hssEditingLayer.pm) {
                        window.hssEditingLayer.pm.disable();
                    }
                    resetAllStyles();
                });

                map.on('pm:drawend', function() {
                    console.log('HSS iframe pm:drawend');
                });

                map.on('pm:editend', function() {
                    console.log('HSS iframe pm:editend');
                    logPmOverlays('map editend');
                });

                window.addEventListener('message', function(event) {
                    if (!event || !event.data || !event.data.type) return;
                    if (event.data.type === 'start_draw') {
                        if (map.pm) {
                            map.pm.enableDraw('Line', { snappable: false });
                        }
                    }
                    if (event.data.type === 'select_route') {
                        var payload = event.data.payload || {};
                        var guid = payload.guid;
                        if (!guid) return;
                        var layer = findLayerByGuid(guid);
                        if (layer && layer.fire) {
                            if (layer.getBounds && map.getBounds) {
                                var layerBounds = layer.getBounds();
                                if (layerBounds && (payload.zoom || !map.getBounds().contains(layerBounds))) {
                                    map.fitBounds(layerBounds, { padding: [20, 20] });
                                }
                            }
                            var center = null;
                            if (layer.getBounds) {
                                center = layer.getBounds().getCenter();
                            }
                            layer.fire('click', { latlng: center });
                        }
                    }
                    if (event.data.type === 'update_style') {
                        var payload = event.data.payload || {};
                        var guid = payload.guid;
                        console.log('HSS iframe update_style: received payload', payload);
                        if (!guid) return;
                        var layer = findLayerByGuid(guid);
                        if (!layer) return;
                        if (payload.properties && layer.feature && layer.feature.properties) {
                            Object.keys(payload.properties).forEach(function(key) {
                                layer.feature.properties[key] = payload.properties[key];
                            });
                        }
                        var baseColor = payload.style && payload.style.color ? payload.style.color : (layer.options.color || "{{ this.highlight_color }}");
                        var dashArray = payload.style && payload.style.dashArray ? payload.style.dashArray : null;
                        var baseWeight = payload.style && payload.style.weight ? payload.style.weight : null;
                        if (!baseWeight && layer.options && layer.options._hssOriginalStyle && layer.options._hssOriginalStyle.weight) {
                            baseWeight = layer.options._hssOriginalStyle.weight;
                        }
                        if (!baseWeight && layer.options && layer.options.weight) {
                            baseWeight = layer.options.weight;
                        }
                        if (!baseWeight) baseWeight = 3;
                        var baseStyle = {
                            color: baseColor,
                            weight: baseWeight,
                            opacity: 0.9,
                            dashArray: dashArray
                        };
                        layer.options._hssOriginalStyle = baseStyle;
                        if (window.hssSelectedLayer === layer) {
                            if (layer.setStyle) {
                                layer.setStyle({
                                    color: "{{ this.highlight_color }}",
                                    weight: {{ this.highlight_weight }},
                                    opacity: 0.95,
                                    dashArray: dashArray
                                });
                            }
                            console.log('HSS iframe update_style: applied highlight style', guid);
                        } else if (layer.setStyle) {
                            layer.setStyle(baseStyle);
                            console.log('HSS iframe update_style: applied base style', guid, baseStyle);
                        }
                        applyHighlightStyles();
                        updateTooltip(layer);
                        console.log('HSS iframe update_style: updated tooltip', guid);
                    }
                    if (event.data.type === 'replace_geometry') {
                        var payload = event.data.payload || {};
                        var guid = payload.guid;
                        console.log('HSS iframe replace_geometry', payload);
                        if (!guid) return;
                        var layer = findLayerByGuid(guid);
                        if (!layer && window.hssEditingLayer) {
                            layer = window.hssEditingLayer;
                        }
                        if (!layer) {
                            console.log('HSS iframe replace_geometry: no layer for guid', guid);
                        }
                        if (!layer || !payload.coords || !layer.setLatLngs) return;
                        layer.setLatLngs(normalizeLatLngs(payload.coords));
                        if (layer.redraw) layer.redraw();
                        if (layer.pm && layer.pm.enabled && layer.pm.enabled()) {
                            layer.pm.disable();
                            layer.pm.enable();
                        }
                        if (payload.properties && layer.feature && layer.feature.properties) {
                            Object.keys(payload.properties).forEach(function(key) {
                                layer.feature.properties[key] = payload.properties[key];
                            });
                        }
                        updateTooltip(layer);
                        applyHighlightStyles();
                    }
                    if (event.data.type === 'created_update') {
                        var payload = event.data.payload || {};
                        var tempId = payload.temp_id;
                        console.log('HSS iframe created_update', payload);
                        if (!tempId) return;
                        var layer = null;
                        if (window.hssTempLayerMap && window.hssTempLayerMap[tempId]) {
                            layer = window.hssTempLayerMap[tempId];
                        }
                        if (!layer && layerGroup && layerGroup.eachLayer) {
                            layerGroup.eachLayer(function(l) {
                                if (layer) return;
                                if (l && l._hssTempId === tempId) layer = l;
                            });
                        }
                        if (!layer && map && map.eachLayer) {
                            map.eachLayer(function(l) {
                                if (layer) return;
                                if (l && l._hssTempId === tempId) layer = l;
                            });
                        }
                        if (!layer) return;
                        if (payload.guid) {
                            if (!layer.feature) layer.feature = layer.toGeoJSON();
                            if (!layer.feature.properties) layer.feature.properties = {};
                            layer.feature.properties.guid = payload.guid;
                        }
                        if (layerGroup && layerGroup.addLayer) {
                            layerGroup.addLayer(layer);
                        }
                        bindFeatureLayer(layer);
                        if (payload.coords && layer.setLatLngs) {
                            layer.setLatLngs(normalizeLatLngs(payload.coords));
                            if (layer.redraw) layer.redraw();
                        }
                        if (layer.pm && layer.pm.enabled && layer.pm.enabled()) {
                            layer.pm.disable();
                            layer.pm.enable();
                        }
                        if (payload.style && layer.setStyle) {
                            var dashArray = payload.style.dashArray || null;
                            layer.options._hssOriginalStyle = {
                                color: payload.style.color,
                                weight: 3,
                                opacity: 0.9,
                                dashArray: dashArray
                            };
                            layer.setStyle({
                                color: "{{ this.highlight_color }}",
                                weight: {{ this.highlight_weight }},
                                opacity: 0.95,
                                dashArray: dashArray
                            });
                        }
                        if (payload.properties && layer.feature && layer.feature.properties) {
                            Object.keys(payload.properties).forEach(function(key) {
                                layer.feature.properties[key] = payload.properties[key];
                            });
                        }
                        window.hssSelectedLayer = layer;
                        updateTooltip(layer);
                    }
                    if (event.data.type === 'discard_created') {
                        var payload = event.data.payload || {};
                        var tempId = payload.temp_id;
                        console.log('HSS iframe discard_created', payload);
                        if (!tempId) return;
                        var layer = null;
                        if (window.hssTempLayerMap && window.hssTempLayerMap[tempId]) {
                            layer = window.hssTempLayerMap[tempId];
                        }
                        if (!layer && map && map.eachLayer) {
                            map.eachLayer(function(l) {
                                if (layer) return;
                                if (l && l._hssTempId === tempId) layer = l;
                            });
                        }
                        if (layer && map && map.removeLayer) {
                            map.removeLayer(layer);
                        }
                    }
                if (event.data.type === 'set_highlight') {
                    var payload = event.data.payload || {};
                    var list = payload.guids || [];
                    var active = payload.active !== false;
                    if (!active) {
                        window.hssHighlightGuids = null;
                        window.hssHighlightDimOpacity = null;
                        console.log('HSS iframe set_highlight cleared');
                        resetAllStyles();
                        return;
                    }
                    window.hssHighlightGuids = {};
                    window.hssHighlightDimOpacity = payload.dim_opacity;
                    list.forEach(function(g) { window.hssHighlightGuids[g] = true; });
                    console.log('HSS iframe set_highlight', list.length);
                    applyHighlightStyles();
                }
                    if (event.data.type === 'set_route_style') {
                        var payload = event.data.payload || {};
                        var colors = payload.colors || {};
                        var baseWeight = payload.weight || null;
                        if (!baseWeight) baseWeight = 3;
                    if (typeof baseWeight !== 'number') {
                        baseWeight = parseInt(baseWeight, 10);
                    }
                    if (!baseWeight || baseWeight < 1) baseWeight = 1;
                    if (baseWeight > 12) baseWeight = 12;
                    var highlightWeight = baseWeight + 2;
                    if (map && map.eachLayer) {
                        map.eachLayer(function(l) {
                            if (!l || !l.feature || !l.feature.properties || !l.setStyle) return;
                            var props = l.feature.properties || {};
                            if (!props.guid) return;
                            var color = colors.polyline;
                            if (props.Rejected) {
                                color = colors.polyline_rejected || color;
                            } else if (props.AuditedStreetView || props.AuditedInPerson) {
                                color = colors.polyline_approved || color;
                            }
                            var dash = (props.OneWay === 'OneWay') ? hssOneWayDash : null;
                            var style = {
                                color: color || l.options.color,
                                weight: baseWeight,
                                opacity: 0.9,
                                dashArray: dash
                            };
                            l.options._hssOriginalStyle = style;
                            if (window.hssSelectedLayer === l) {
                                l.setStyle({
                                    color: colors.polyline_highlight || "{{ this.highlight_color }}",
                                    weight: highlightWeight,
                                    opacity: 0.95,
                                    dashArray: dash
                                });
                            } else {
                                l.setStyle(style);
                            }
                        });
                    }
                    window.hssHighlightDimOpacity = window.hssHighlightDimOpacity || payload.dim_opacity;
                    applyHighlightStyles();
                }
                if (event.data.type === 'set_basemap') {
                    var payload = event.data.payload || {};
                    var name = payload.name || null;
                    if (!name || !hssBaseLayers[name]) return;
                    Object.keys(hssBaseLayers).forEach(function(key) {
                        if (key !== name && map.hasLayer(hssBaseLayers[key])) {
                            map.removeLayer(hssBaseLayers[key]);
                        }
                    });
                    if (!map.hasLayer(hssBaseLayers[name])) {
                        map.addLayer(hssBaseLayers[name]);
                    }
                }
                if (event.data.type === 'set_overlays') {
                    var payload = event.data.payload || {};
                    var overlays = payload.overlays || {};
                    Object.keys(overlays).forEach(function(name) {
                        if (!hssOverlayLayers[name]) return;
                        if (overlays[name]) {
                            if (!map.hasLayer(hssOverlayLayers[name])) {
                                map.addLayer(hssOverlayLayers[name]);
                            }
                        } else {
                            if (map.hasLayer(hssOverlayLayers[name])) {
                                map.removeLayer(hssOverlayLayers[name]);
                            }
                        }
                    });
                }
            });

                map.on('click', function(e) {
                    sendMessage("map_click", e.latlng);
                });
                map.on('baselayerchange', function(e) {
                    if (e && e.name) {
                        sendMessage('basemap_change', { name: e.name });
                    }
                });
                map.on('overlayadd', function(e) {
                    if (e && e.name) {
                        sendMessage('overlay_change', { name: e.name, visible: true });
                    }
                });
                map.on('overlayremove', function(e) {
                    if (e && e.name) {
                        sendMessage('overlay_change', { name: e.name, visible: false });
                    }
                });

                function logPmOverlays(label) {
                    try {
                        var nodes = Array.from(document.querySelectorAll('.leaflet-pane svg path, .leaflet-pane svg rect, .leaflet-pane svg g'));
                        var pmNodes = nodes.filter(function(el) {
                            var cls = el.getAttribute('class') || '';
                            return cls.indexOf('leaflet-pm') !== -1 || cls.indexOf('pm-') !== -1;
                        }).map(function(el) {
                            return {
                                tag: el.tagName,
                                className: el.getAttribute('class') || '',
                                id: el.getAttribute('id') || ''
                            };
                        });
                        console.log('HSS pm overlays', label, pmNodes);
                    } catch (e) {
                        console.log('HSS pm overlays error', e);
                    }
                }
            }

            hssWireHandlers({{ this.map_name }}, {{ this.layer_name }});
        {% endmacro %}
        """
    )

    def __init__(
        self,
        map_name: str,
        layer_name: str,
        highlight_color: str,
        highlight_weight: int,
        filter_highlight_color: str,
        filter_highlight_weight: int,
        base_layers: Optional[Dict[str, str]] = None,
        one_way_dash: Optional[str] = None,
        overlay_layers: Optional[Dict[str, str]] = None,
    ):
        super().__init__()
        self._name = "ShinyBridge"
        self.map_name = map_name
        self.layer_name = layer_name
        self.highlight_color = highlight_color
        self.highlight_weight = highlight_weight
        self.filter_highlight_color = filter_highlight_color
        self.filter_highlight_weight = filter_highlight_weight
        self.base_layers = base_layers or {}
        self.one_way_dash = one_way_dash or ""
        self.overlay_layers = overlay_layers or {}


def build_map(
    rows,
    center: Tuple[float, float],
    zoom: int,
    thunder_key: Optional[str],
    borough_geoms: Dict[str, object],
    london_mask: Optional[object],
    selected_region: Optional[str],
    route_scheme: Optional[str],
    route_width: Optional[int],
) -> folium.Map:
    m = folium.Map(location=center, zoom_start=zoom, tiles=None, control_scale=True, keyboard=False)

    vml_guard = """
    <script>
    if (!document.namespaces) {
        document.namespaces = { add: function(){ return {}; } };
    } else if (typeof document.namespaces.add !== "function") {
        document.namespaces.add = function(){ return {}; };
    }
    </script>
    """
    m.get_root().header.add_child(Element(vml_guard))

    positron = folium.TileLayer("CartoDB positron", name="Positron", control=True, show=True)
    positron.add_to(m)
    osm = folium.TileLayer("OpenStreetMap", name="OSM", control=True, show=False)
    osm.add_to(m)

    if thunder_key:
        ocm = folium.TileLayer(
            tiles=(
                "https://{s}.tile.thunderforest.com/cycle/{z}/{x}/{y}.png"
                f"?apikey={thunder_key}"
            ),
            attr="&copy; Thunderforest, &copy; OpenStreetMap contributors",
            name="OpenCycleMap",
            control=True,
            show=False,
        )
        ocm.add_to(m)
    else:
        ocm = None

    imagery = folium.TileLayer(
        tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        attr="Tiles &copy; Esri",
        name="Imagery",
        control=True,
        show=False,
    )
    imagery.add_to(m)

    routes_group = folium.FeatureGroup(name="Routes", show=True, control=False)
    scheme = get_route_style(route_scheme)
    try:
        base_weight = int(route_width) if route_width is not None else 3
    except Exception:
        base_weight = 3
    base_weight = max(1, min(base_weight, 12))
    highlight_weight = max(base_weight + 2, base_weight + 1)

    features = []
    for _, row in rows.iterrows():
        coords = row.get("_coords")
        if not coords:
            continue
        length_m = line_length_m(coords) if coords else 0.0
        properties = {k: row.get(k) for k in [
            "guid", "name", "id", "Designation", "OneWay", "Flow", "Protection",
            "Ownership", "YearBuildBeforeFlag", "YearBuilt", "AuditedStreetView",
            "AuditedInPerson", "Rejected", "description", "History",
        ]}
        properties["Length_m"] = int(round(length_m))
        features.append({
            "type": "Feature",
            "properties": properties,
            "geometry": {
                "type": "LineString",
                "coordinates": [(lon, lat) for lat, lon in coords],
            },
        })

    def route_style(feat):
        props = feat.get("properties", {})
        if props.get("Rejected"):
            color = scheme["polyline_rejected"]
        elif props.get("AuditedStreetView") or props.get("AuditedInPerson"):
            color = scheme["polyline_approved"]
        else:
            color = scheme["polyline"]
        return {
            "color": color,
            "weight": base_weight,
            "opacity": 0.9,
            "dashArray": ONE_WAY_DASH if props.get("OneWay") == "OneWay" else None,
        }

    folium.map.CustomPane("tflPane", z_index=200).add_to(m)
    tfl_group = folium.FeatureGroup(name="TFL", show=True, control=True)
    tfl_data = load_geojson(TFL_GEOJSON)
    if tfl_data:
        try:
            logger.info("Loaded TFL geojson features=%s", len(tfl_data.get("features", [])))
            logger.info("TFL geom types=%s", geojson_geom_types(tfl_data))
        except Exception:
            logger.info("Loaded TFL geojson")
        folium.GeoJson(
            tfl_data,
            name="TFL",
            style_function=lambda _: {"color": MAP_COLORS["tfl_lines"], "weight": 1, "opacity": 0.5},
            pane="tflPane",
            interactive=False,
            control=False,
        ).add_to(tfl_group)

    lcc_tfl_data = load_geojson(LCC_TFL_GEOJSON)
    if lcc_tfl_data:
        try:
            logger.info("Loaded TFL (LCC) geojson features=%s", len(lcc_tfl_data.get("features", [])))
            logger.info("TFL (LCC) geom types=%s", geojson_geom_types(lcc_tfl_data))
        except Exception:
            logger.info("Loaded TFL (LCC) geojson")
        folium.GeoJson(
            lcc_tfl_data,
            name="TFL (LCC)",
            style_function=lambda _: {"color": MAP_COLORS["tfl_lines"], "weight": 1, "opacity": 0.5},
            pane="tflPane",
            interactive=False,
            control=False,
        ).add_to(tfl_group)

    tfl_group.add_to(m)

    cycle_data = _load_cycle_routes_once()
    cycle_groups = {}
    if cycle_data:
        superhighway = folium.FeatureGroup(name="Cycle Superhighways", show=True, control=True)
        cycleway = folium.FeatureGroup(name="Cycleways", show=True, control=True)
        quietway = folium.FeatureGroup(name="Quietways", show=False, control=True)
        cycle_groups = {
            "superhighway": superhighway,
            "cycleway": cycleway,
            "quietway": quietway,
        }
        for feat in cycle_data.get("features", []):
            props = feat.get("properties", {}) or {}
            route_name = (props.get("Route_Name") or "").strip()
            programme = (props.get("Programme") or "").strip()
            target = cycleway
            if programme == "Cycle Superhighways":
                target = superhighway
            elif programme == "Quietways":
                target = quietway
            color = MAP_COLORS["cycleway"]
            if target is superhighway:
                color = MAP_COLORS["cycle_superhighway"]
            elif target is quietway:
                color = MAP_COLORS["quietway"]
            folium.GeoJson(
                feat,
                name=route_name or "Cycle route",
                style_function=lambda _f, c=color: {"color": c, "weight": 2, "opacity": 0.8},
                tooltip=folium.GeoJsonTooltip(
                    fields=["Route_Name", "Label"],
                    aliases=["Route:", "Label:"],
                    sticky=True,
                ),
            ).add_to(target)
        for group in (superhighway, cycleway, quietway):
            group.add_to(m)

    geojson = folium.GeoJson(
        {"type": "FeatureCollection", "features": features},
        name="routes",
        style_function=route_style,
        tooltip=folium.GeoJsonTooltip(
            fields=["name", "OneWay", "Length_m"],
            aliases=["Name:", "Direction:", "Length (m):"],
            sticky=True,
        ),
    )
    geojson.add_to(routes_group)
    routes_group.add_to(m)

    if borough_geoms:
        for name, geom in borough_geoms.items():
            if name == selected_region:
                continue
            folium.GeoJson(
                geom.__geo_interface__,
                name=name,
                style_function=lambda _: {
                    "color": "#2674BA",
                    "weight": 1,
                    "fillOpacity": 0.25,
                    "fillColor": "#bfbfbf",
                },
                control=False,
            ).add_to(m)

    if london_mask is not None:
        london_layer = folium.GeoJson(
            london_mask.__geo_interface__,
            name="London",
            style_function=lambda _: {
                "color": "#2674BA",
                "weight": 2,
                "fillOpacity": 0.35,
                "fillColor": "#bfbfbf",
            },
            control=False,
        ).add_to(m)
        london_layer.add_child(
            Element(
                f"""
            <style>
              #{london_layer.get_name()}_pane .leaflet-interactive {{ pointer-events: none; }}
            </style>
            """
            )
        )

    GeomanControl().add_to(m)

    base_layers = {
        "Positron": positron.get_name(),
        "OSM": osm.get_name(),
        "Imagery": imagery.get_name(),
    }
    if ocm is not None:
        base_layers["OpenCycleMap"] = ocm.get_name()

    overlay_layers = {
        "TFL": tfl_group.get_name(),
    }
    if cycle_groups:
        overlay_layers["Cycle Superhighways"] = cycle_groups["superhighway"].get_name()
        overlay_layers["Cycleways"] = cycle_groups["cycleway"].get_name()
        overlay_layers["Quietways"] = cycle_groups["quietway"].get_name()

    bridge = ShinyBridge(
        m.get_name(),
        geojson.get_name(),
        scheme["polyline_highlight"],
        highlight_weight,
        scheme["polyline_filter"],
        highlight_weight + 1,
        base_layers=base_layers,
        one_way_dash=ONE_WAY_DASH,
        overlay_layers=overlay_layers,
    )
    bridge.add_to(m)

    folium.LayerControl(collapsed=False).add_to(m)
    m.get_root().html.add_child(
        Element(
            """
            <style>
              .leaflet-pm-marker-icon,
              .leaflet-pm-icon-marker {
                width: 14px !important;
                height: 14px !important;
                margin-left: -7px !important;
                margin-top: -7px !important;
                border-radius: 50%;
              }
              .leaflet-pm-rectangle {
                display: none !important;
              }
              .leaflet-interactive:focus,
              .leaflet-interactive {
                outline: none !important;
              }
            </style>
            """
        )
    )

    if selected_region and selected_region in borough_geoms:
        bounds = borough_geoms[selected_region].bounds
        m.fit_bounds([[bounds[1], bounds[0]], [bounds[3], bounds[2]]])

    return m
