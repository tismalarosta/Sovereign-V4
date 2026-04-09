"""
Philips Hue connector — local Hue Bridge REST API (v1).
READ-WRITE. Controls lights and scenes on the local LAN.
Source prefix: hue::

All actions are LOW risk (instantly reversible).

Requires in data/.env:
  HUE_BRIDGE_IP=192.168.x.x
  HUE_BRIDGE_TOKEN=<your-username-token>

Gracefully returns NOT_CONFIGURED if either field is empty.
Never raises — always returns a status/success dict.
"""

import httpx

from app.settings import settings


def _base_url() -> str:
    return f"http://{settings.hue_bridge_ip}/api/{settings.hue_bridge_token}"


def _configured() -> bool:
    return bool(settings.hue_bridge_ip and settings.hue_bridge_token)


# ── Read API ──────────────────────────────────────────────────────────────────

def get_lights() -> dict:
    """List all lights and their current state."""
    if not _configured():
        return {"status": "NOT_CONFIGURED", "message": "HUE_BRIDGE_IP/TOKEN not set in data/.env"}
    try:
        r = httpx.get(f"{_base_url()}/lights", timeout=5)
        return {"status": "OK", "lights": r.json()}
    except Exception as exc:
        return {"status": "ERROR", "message": str(exc)}


def get_scenes() -> dict:
    """List all available scenes."""
    if not _configured():
        return {"status": "NOT_CONFIGURED", "message": "HUE_BRIDGE_IP/TOKEN not set in data/.env"}
    try:
        r = httpx.get(f"{_base_url()}/scenes", timeout=5)
        return {"status": "OK", "scenes": r.json()}
    except Exception as exc:
        return {"status": "ERROR", "message": str(exc)}


# ── Action API ────────────────────────────────────────────────────────────────

def turn_on(light_id: str) -> dict:
    """Turn a light on."""
    if not _configured():
        return {"success": False, "stub": False, "message": "Hue not configured", "undo_data": None}
    try:
        httpx.put(f"{_base_url()}/lights/{light_id}/state", json={"on": True}, timeout=5)
        return {
            "success": True,
            "stub": False,
            "message": f"Light {light_id} turned on",
            "undo_data": {"light_id": light_id, "action": "turn_off"},
        }
    except Exception as exc:
        return {"success": False, "stub": False, "message": str(exc), "undo_data": None}


def turn_off(light_id: str) -> dict:
    """Turn a light off."""
    if not _configured():
        return {"success": False, "stub": False, "message": "Hue not configured", "undo_data": None}
    try:
        httpx.put(f"{_base_url()}/lights/{light_id}/state", json={"on": False}, timeout=5)
        return {
            "success": True,
            "stub": False,
            "message": f"Light {light_id} turned off",
            "undo_data": {"light_id": light_id, "action": "turn_on"},
        }
    except Exception as exc:
        return {"success": False, "stub": False, "message": str(exc), "undo_data": None}


def set_brightness(light_id: str, brightness: int) -> dict:
    """Set brightness 0–254. Turns the light on."""
    if not _configured():
        return {"success": False, "stub": False, "message": "Hue not configured", "undo_data": None}
    bri = max(0, min(254, int(brightness)))
    try:
        httpx.put(
            f"{_base_url()}/lights/{light_id}/state",
            json={"on": True, "bri": bri},
            timeout=5,
        )
        return {
            "success": True,
            "stub": False,
            "message": f"Light {light_id} brightness set to {bri}",
            "undo_data": None,
        }
    except Exception as exc:
        return {"success": False, "stub": False, "message": str(exc), "undo_data": None}


def set_color(light_id: str, hue: int, sat: int) -> dict:
    """Set color via hue (0–65535) and saturation (0–254). Turns the light on."""
    if not _configured():
        return {"success": False, "stub": False, "message": "Hue not configured", "undo_data": None}
    h = max(0, min(65535, int(hue)))
    s = max(0, min(254, int(sat)))
    try:
        httpx.put(
            f"{_base_url()}/lights/{light_id}/state",
            json={"on": True, "hue": h, "sat": s},
            timeout=5,
        )
        return {
            "success": True,
            "stub": False,
            "message": f"Light {light_id} color set (hue={h}, sat={s})",
            "undo_data": None,
        }
    except Exception as exc:
        return {"success": False, "stub": False, "message": str(exc), "undo_data": None}


def set_scene(scene_id: str, group_id: str = "0") -> dict:
    """Activate a Hue scene on a group (default group 0 = all lights)."""
    if not _configured():
        return {"success": False, "stub": False, "message": "Hue not configured", "undo_data": None}
    if not scene_id:
        return {"success": False, "stub": False, "message": "scene_id is required", "undo_data": None}
    try:
        httpx.put(
            f"{_base_url()}/groups/{group_id}/action",
            json={"scene": scene_id},
            timeout=5,
        )
        return {
            "success": True,
            "stub": False,
            "message": f"Scene '{scene_id}' activated",
            "undo_data": None,
        }
    except Exception as exc:
        return {"success": False, "stub": False, "message": str(exc), "undo_data": None}


# ── Connector scan (indexes lights + scenes into ChromaDB) ────────────────────

def scan() -> dict:
    """
    Index light names and scene names into ChromaDB so Regis can
    resolve "turn on the bedroom light" → correct light_id from context.
    """
    if not _configured():
        return {
            "connector": "hue",
            "status": "NOT_CONFIGURED",
            "items_indexed": 0,
            "message": "HUE_BRIDGE_IP/TOKEN not set in data/.env",
        }

    try:
        from app.embeddings import embedder
        from app.chroma_store import store
    except ImportError as exc:
        return {
            "connector": "hue",
            "status": "ERROR",
            "items_indexed": 0,
            "message": f"Import error: {exc}",
        }

    try:
        store.delete_by_filter({"source_type": {"$eq": "hue"}})

        lights_resp = get_lights()
        scenes_resp = get_scenes()

        items = 0

        if lights_resp.get("status") == "OK":
            for lid, light in (lights_resp.get("lights") or {}).items():
                name = light.get("name", lid)
                ltype = light.get("type", "unknown")
                text = f"Smart light: {name} (ID: {lid}, type: {ltype})"
                chunk_id = f"hue::light::{lid}"
                try:
                    emb = embedder.embed_one(text)
                    store.upsert(
                        ids=[chunk_id],
                        embeddings=[emb],
                        documents=[text],
                        metadatas=[{
                            "source": chunk_id,
                            "source_type": "hue",
                            "hue_type": "light",
                            "light_id": lid,
                            "light_name": name,
                        }],
                    )
                    items += 1
                except Exception:
                    continue

        if scenes_resp.get("status") == "OK":
            for sid, scene in (scenes_resp.get("scenes") or {}).items():
                name = scene.get("name", sid)
                text = f"Hue scene: {name} (ID: {sid})"
                chunk_id = f"hue::scene::{sid}"
                try:
                    emb = embedder.embed_one(text)
                    store.upsert(
                        ids=[chunk_id],
                        embeddings=[emb],
                        documents=[text],
                        metadatas=[{
                            "source": chunk_id,
                            "source_type": "hue",
                            "hue_type": "scene",
                            "scene_id": sid,
                            "scene_name": name,
                        }],
                    )
                    items += 1
                except Exception:
                    continue

        return {"connector": "hue", "status": "OK", "items_indexed": items}

    except Exception as exc:
        return {
            "connector": "hue",
            "status": "ERROR",
            "items_indexed": 0,
            "message": str(exc),
        }
