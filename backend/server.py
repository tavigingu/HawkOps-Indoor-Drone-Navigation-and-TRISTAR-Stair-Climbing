#!/usr/bin/env python3
"""
Tello FastAPI Server - API layer
Păstrează endpoint-urile și orchestration-ul backend.
Pipeline-ul video/depth este mutat în stream_pipeline.py.
"""

import signal
import sys
import time
import os
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime

import uvicorn
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

import navigation
import stream_pipeline
import ai_analyzer
import mission_tracker
import database.crud as db_crud
from database.db import init_db
from tello_controller import TelloController


controller = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifecycle manager pentru FastAPI - pornire și oprire."""
    print("🚀 Starting Tello FastAPI Server...")
    init_db()
    yield
    print("🛑 Shutting down server...")
    cleanup()


def cleanup():
    """Curățare resurse la oprirea serverului."""
    global controller

    print("\n📋 Cleanup în curs...")

    try:
        stream_pipeline.stop_streaming()
    except Exception as e:
        print(f"Eroare la oprirea pipeline-ului: {e}")

    if controller:
        try:
            controller.cleanup()
        except Exception as e:
            print(f"Eroare la cleanup controller: {e}")
        finally:
            controller = None

    navigation.reset_navigation_state()
    print("✓ Cleanup complet")


def signal_handler(sig, frame):
    """Handler pentru semnale de oprire (Ctrl+C)."""
    print("\n⚠️  Semnal de oprire primit...")
    cleanup()
    sys.exit(0)


app = FastAPI(
    title="Tello Drone API",
    description="API pentru control și streaming video de la drona DJI Tello",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://localhost:3000",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:3000",
        "*",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

reports_assets_dir = os.path.join(os.path.dirname(__file__), "reports")
os.makedirs(reports_assets_dir, exist_ok=True)
app.mount("/reports/assets", StaticFiles(directory=reports_assets_dir), name="reports-assets")

# Mount directoare înregistrări video ca static files
_base_dir = os.path.dirname(__file__)
for _rec_dir_name in ("hallway_recordings", "stairwell_recordings", "stair_climber_recordings"):
    _rec_dir = os.path.join(_base_dir, _rec_dir_name)
    os.makedirs(_rec_dir, exist_ok=True)
    app.mount(f"/recordings/{_rec_dir_name}", StaticFiles(directory=_rec_dir), name=_rec_dir_name)



@app.get("/video/stair_da2")
async def stair_da2_feed():
    if not stream_pipeline.is_streaming_active():
        raise HTTPException(status_code=503, detail="Video streaming nu este activ.")
    return StreamingResponse(
        stream_pipeline.generate_stair_da2_frames(),
        media_type="multipart/x-mixed-replace; boundary=frame",
        headers={
            "Access-Control-Allow-Origin": "*",
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )

@app.get("/video/stair_sobel")
async def stair_sobel_feed():
    if not stream_pipeline.is_streaming_active():
        raise HTTPException(status_code=503, detail="Video streaming nu este activ.")
    return StreamingResponse(
        stream_pipeline.generate_stair_sobel_frames(),
        media_type="multipart/x-mixed-replace; boundary=frame",
        headers={
            "Access-Control-Allow-Origin": "*",
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )

@app.get("/video/stair_gabor")
async def stair_gabor_feed():
    if not stream_pipeline.is_streaming_active():
        raise HTTPException(status_code=503, detail="Video streaming nu este activ.")
    return StreamingResponse(
        stream_pipeline.generate_stair_gabor_frames(),
        media_type="multipart/x-mixed-replace; boundary=frame",
        headers={
            "Access-Control-Allow-Origin": "*",
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )


@app.get("/video/stair_da2")
async def stair_da2_feed():
    if not stream_pipeline.is_streaming_active():
        raise HTTPException(status_code=503, detail="Video streaming nu este activ.")
    return StreamingResponse(
        stream_pipeline.generate_stair_da2_frames(),
        media_type="multipart/x-mixed-replace; boundary=frame",
        headers={
            "Access-Control-Allow-Origin": "*",
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )

@app.get("/video/stair_sobel")
async def stair_sobel_feed():
    if not stream_pipeline.is_streaming_active():
        raise HTTPException(status_code=503, detail="Video streaming nu este activ.")
    return StreamingResponse(
        stream_pipeline.generate_stair_sobel_frames(),
        media_type="multipart/x-mixed-replace; boundary=frame",
        headers={
            "Access-Control-Allow-Origin": "*",
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )

@app.get("/video/stair_gabor")
async def stair_gabor_feed():
    if not stream_pipeline.is_streaming_active():
        raise HTTPException(status_code=503, detail="Video streaming nu este activ.")
    return StreamingResponse(
        stream_pipeline.generate_stair_gabor_frames(),
        media_type="multipart/x-mixed-replace; boundary=frame",
        headers={
            "Access-Control-Allow-Origin": "*",
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )

def _build_live_payload(room_count: int = 5):
    global controller

    safe_room_count = max(1, min(int(room_count), 10))

    stats_payload = {
        "battery": None,
        "temperature": None,
        "height": None,
        "speed": None,
        "flight_time": None,
        "is_flying": False,
    }
    connected = False

    if controller:
        try:
            stats_payload = {
                "battery": controller.get_battery(),
                "temperature": controller.get_temperature(),
                "height": controller.get_height(),
                "speed": controller.get_speed(),
                "flight_time": controller.get_flight_time(),
                "is_flying": controller.is_flying(),
            }
            connected = True
        except Exception:
            connected = True

    try:
        target_payload = navigation.get_navigation_status()
    except Exception:
        target_payload = {
            "autopilot_status": "Inactiv",
            "wall_measurements": {},
        }

    try:
        reports_payload = ai_analyzer.get_analyzer().get_multi_room_report_snapshots(
            room_count=safe_room_count
        )
    except Exception:
        reports_payload = []

    # Verifică dacă autopilotul tocmai s-a terminat → completează misiunea în DB
    try:
        autopilot_active = target_payload.get("autopilot_active", False)
        mission_tracker.check_and_complete_mission(bool(autopilot_active))
    except Exception:
        pass

    return {
        "connected": connected,
        "stats": stats_payload,
        "target": target_payload,
        "reports": reports_payload,
        "room_count": safe_room_count,
        "updated_at": datetime.now().isoformat(),
    }


@app.get("/")
async def root():
    """Endpoint rădăcină - informații despre API."""
    return {
        "message": "Tello Drone API",
        "version": "1.0.0",
        "status": "running",
        "endpoints": {
            "video_stream": "/video/feed",
            "depth_stream": "/video/depth",
            "single_frame": "/video/frame",
            "calibration_status": "/depth/calibration",
            "calibration_switch": "/depth/calibration/select",
            "stats": "/drone/stats",
            "connect": "/drone/connect",
            "disconnect": "/drone/disconnect",
            "takeoff": "/drone/takeoff",
            "land": "/drone/land",
            "autopilot": "/drone/autopilot",
            "target": "/drone/target",
            "reports_live_list": "/reports/live?room_count=3",
            "reports_live_room": "/reports/live/{room_index}",
        },
    }


@app.get("/video/feed")
async def video_feed():
    """Stream video MJPEG live de la dronă."""
    if not stream_pipeline.is_streaming_active():
        raise HTTPException(
            status_code=503,
            detail="Video streaming nu este activ. Conectează-te la dronă mai întâi.",
        )

    return StreamingResponse(
        stream_pipeline.generate_frames(),
        media_type="multipart/x-mixed-replace; boundary=frame",
        headers={
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET, OPTIONS",
            "Access-Control-Allow-Headers": "*",
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )


@app.get("/video/depth")
async def depth_feed():
    """Stream depth map MJPEG live de la dronă."""
    if not stream_pipeline.is_streaming_active():
        raise HTTPException(
            status_code=503,
            detail="Video streaming nu este activ. Conectează-te la dronă mai întâi.",
        )

    return StreamingResponse(
        stream_pipeline.generate_depth_frames(),
        media_type="multipart/x-mixed-replace; boundary=frame",
        headers={
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET, OPTIONS",
            "Access-Control-Allow-Headers": "*",
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )


@app.get("/video/frame")
async def get_single_frame():
    """Obține un singur frame JPEG (snapshot)."""
    try:
        frame_bytes = stream_pipeline.get_latest_frame_jpeg(quality=90)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Eroare la obținere frame: {str(e)}")

    if frame_bytes is None:
        raise HTTPException(status_code=404, detail="Nu există frame-uri disponibile")

    return Response(
        content=frame_bytes,
        media_type="image/jpeg",
        headers={
            "Access-Control-Allow-Origin": "*",
            "Content-Disposition": "inline; filename=tello_frame.jpg",
        },
    )


@app.get("/depth/calibration")
async def get_calibration_status():
    """Status profiluri calibrare depth și profilul activ."""
    return {
        "success": True,
        **stream_pipeline.get_calibration_status(),
    }


@app.post("/depth/calibration/select")
async def select_calibration_profile(profile: str):
    """Comută profilul activ de calibrare (ex: room/corridor) fără restart."""
    ok, message, available = stream_pipeline.set_active_calibration_profile(profile)
    if not ok:
        raise HTTPException(
            status_code=400,
            detail={
                "message": message,
                "available_profiles": available,
            },
        )

    return {
        "success": True,
        "message": message,
        "active_profile": profile,
        "available_profiles": available,
    }


@app.post("/depth/calibration/reload")
async def reload_calibration_profiles():
    """Reîncarcă profilurile de calibrare de pe disk."""
    stream_pipeline.refresh_calibration_profiles()
    return {
        "success": True,
        **stream_pipeline.get_calibration_status(),
    }


@app.get("/drone/stats")
async def get_drone_stats():
    """Obține statistici și telemetrie de la dronă."""
    global controller

    if not controller:
        return {
            "success": True,
            "connected": False,
            "stats": {
                "battery": None,
                "temperature": None,
                "height": None,
                "speed": None,
                "flight_time": None,
                "is_flying": False,
            },
        }

    try:
        stats = {
            "battery": controller.get_battery(),
            "temperature": controller.get_temperature(),
            "height": controller.get_height(),
            "speed": controller.get_speed(),
            "flight_time": controller.get_flight_time(),
            "is_flying": controller.is_flying(),
        }

        return {
            "success": True,
            "connected": True,
            "stats": stats,
        }
    except Exception as e:
        return {
            "success": False,
            "connected": True,
            "error": str(e),
            "stats": {},
        }


@app.post("/drone/connect")
async def connect_drone():
    """Conectează la dronă și pornește streaming video/depth."""
    global controller

    try:
        if controller:
            return {
                "success": True,
                "message": "Deja conectat la dronă",
                "battery": controller.get_battery(),
            }

        print("🔌 Conectare la dronă...")
        controller = TelloController()

        battery = controller.get_battery()
        temp = controller.get_temperature()

        print(f"✓ Conectat! Baterie: {battery}%, Temp: {temp}°C")

        navigation.reset_navigation_state()
        stream_pipeline.start_streaming(controller)

        return {
            "success": True,
            "message": "Conectat cu succes la dronă",
            "battery": battery,
            "temperature": temp,
        }
    except Exception as e:
        print(f"❌ Eroare la conectare: {e}")
        try:
            stream_pipeline.stop_streaming()
        except Exception:
            pass
        controller = None
        raise HTTPException(status_code=500, detail=f"Eroare la conectare: {str(e)}")


@app.post("/drone/disconnect")
async def disconnect_drone():
    """Deconectează de la dronă și oprește streaming."""
    global controller

    try:
        if not controller:
            return {"success": True, "message": "Nu există conexiune activă"}

        stream_pipeline.stop_streaming()

        if controller.is_flying():
            print("🛬 Aterizare automată...")
            controller.land()

        controller.cleanup()
        controller = None
        navigation.reset_navigation_state()

        return {"success": True, "message": "Deconectat cu succes"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Eroare la deconectare: {str(e)}")


@app.post("/drone/takeoff")
async def takeoff(start_position: str = "hallway"):
    """Decolează drona."""
    global controller

    if not controller:
        raise HTTPException(status_code=400, detail="Nu există conexiune la dronă")

    try:
        if controller.is_flying():
            return {"success": False, "message": "Drona este deja în zbor"}

        battery = controller.get_battery()
        height = controller.get_height()
        temperature = controller.get_temperature()

        # Dacă starea internă e desincronizată dar înălțimea indică zbor, nu mai trimitem takeoff.
        if isinstance(height, int) and height > 20:
            return {
                "success": True,
                "message": "Drona pare deja în zbor (telemetrie)",
                "battery": battery,
                "height": height,
                "temperature": temperature,
                "climb_completed": False,
                "climb_error": None,
            }

        if battery < 20:
            return {
                "success": False,
                "message": f"Baterie prea mică pentru zbor: {battery}%",
            }

        controller.takeoff()
        time.sleep(0.8)

        # Asigură urcarea suplimentară la fiecare decolare (best-effort).
        # Dacă drona refuză comanda (ex: "error Motor stop"), păstrăm decolarea ca reușită.
        climb_completed = False
        climb_error = None
        
        if start_position != "stairs":
            move_up_attempts = 3
            for attempt in range(1, move_up_attempts + 1):
                try:
                    controller.move_up(90)
                    climb_completed = True
                    break
                except Exception as move_err:
                    climb_error = str(move_err)
                    time.sleep(0.4)

        if start_position == "stairs":
            msg = "Decolare reușită (fără 90cm)"
        else:
            msg = "Decolare reușită + 90cm sus" if climb_completed else "Decolare reușită (urcare suplimentară nereușită)"

        return {
            "success": True,
            "message": msg,
            "battery": battery,
            "height": controller.get_height(),
            "temperature": temperature,
            "climb_completed": climb_completed,
            "climb_error": climb_error,
        }
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail={
                "message": f"Eroare la decolare: {str(e)}",
                "battery": controller.get_battery() if controller else None,
                "height": controller.get_height() if controller else None,
                "temperature": controller.get_temperature() if controller else None,
            },
        )


@app.post("/drone/land")
async def land():
    """Aterizează drona."""
    global controller

    if not controller:
        raise HTTPException(status_code=400, detail="Nu există conexiune la dronă")

    try:
        if not controller.is_flying():
            return {"success": False, "message": "Drona nu este în zbor"}

        controller.land()
        navigation.reset_navigation_state()
        return {"success": True, "message": "Aterizare reușită"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Eroare la aterizare: {str(e)}")


@app.post("/drone/emergency")
async def emergency_stop():
    """Oprire de urgență - oprește toate motoarele imediat!"""
    global controller

    if not controller:
        raise HTTPException(status_code=400, detail="Nu există conexiune la dronă")

    try:
        controller.emergency()
        navigation.reset_navigation_state()
        return {"success": True, "message": "⚠️ EMERGENCY STOP executat"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Eroare la emergency stop: {str(e)}")


@app.post("/drone/autopilot")
async def start_autopilot(scan_mode: str = "medium", room_count: int = 1, start_position: str = "hallway", target_floor: int = 1, stair_signals: str = "sobel,gabor,da2", stair_single_flight: bool = False):
    """Pornește autopilotul pe baza target-ului detectat.

    Args:
        scan_mode: "fast" (fără măsurători, orientare rapidă),
               "medium" (360° scan),
               sau "complex" (5-segment crab-style, default: "medium")
        room_count: numărul de camere verificate consecutiv (>=1)
        start_position: de unde pleacă drona ("stairs", "stairwell", "hallway")
        target_floor: etajul țintă (pentru modul urcare scări)
        stair_signals: semnalele active la urcare, listă separată prin virgulă
                       din {sobel,gabor,da2} (ex: "sobel,da2")
    """
    global controller

    if not controller:
        raise HTTPException(status_code=400, detail="Nu există conexiune la dronă")

    if scan_mode not in ["fast", "medium", "complex"]:
        raise HTTPException(status_code=400, detail="scan_mode trebuie să fie 'fast', 'medium' sau 'complex'")

    if room_count < 1:
        raise HTTPException(status_code=400, detail="room_count trebuie să fie >= 1")

    if start_position not in ["stairs", "stairwell", "hallway"]:
        raise HTTPException(status_code=400, detail="start_position invalid")

    try:
        # Crează misiune în DB înainte de a porni autopilotul
        try:
            mission_id = mission_tracker.start_mission(
                scan_mode=scan_mode,
                start_position=start_position,
                room_count=room_count,
                target_floor=target_floor,
            )
        except Exception as _mt_err:
            print(f"⚠️ DB: nu pot crea misiunea: {_mt_err}")
            mission_id = None

        result = navigation.start_autopilot(
            controller,
            scan_mode=scan_mode,
            room_count=room_count,
            start_position=start_position,
            target_floor=target_floor,
            stair_signals=stair_signals,
            stair_single_flight=stair_single_flight,
        )
        return {
            "success": True,
            "message": result["message"],
            "scan_mode": scan_mode,
            "room_count": room_count,
            "target_center": result["target_center"],
            "frame_dimensions": result["frame_dimensions"],
            "mission_id": mission_id,
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Eroare la pornire autopilot: {str(e)}")


@app.get("/drone/target")
async def get_target_status():
    """Returnează starea detecției target-ului și status autopilot."""
    return navigation.get_navigation_status()


@app.get("/reports/live")
async def get_live_reports(room_count: int = 3):
    """Returnează snapshot-uri live/salvate pentru camerele 1..room_count."""
    if room_count < 1:
        raise HTTPException(status_code=400, detail="room_count trebuie să fie >= 1")

    analyzer = ai_analyzer.get_analyzer()
    reports = analyzer.get_multi_room_report_snapshots(room_count=room_count)
    return {
        "success": True,
        "room_count": room_count,
        "reports": reports,
    }


@app.get("/reports/live/{room_index}")
async def get_live_report_for_room(room_index: int):
    """Returnează snapshot live/salvat pentru o cameră specifică."""
    if room_index < 1:
        raise HTTPException(status_code=400, detail="room_index trebuie să fie >= 1")

    analyzer = ai_analyzer.get_analyzer()
    report = analyzer.get_room_report_snapshot(room_index)
    return {
        "success": True,
        "report": report,
    }


@app.websocket("/ws/live")
async def live_updates_websocket(websocket: WebSocket, room_count: int = 5):
    """Canal live pentru status dronă + autopilot + rapoarte (fără polling HTTP în frontend)."""
    await websocket.accept()

    safe_room_count = max(1, min(int(room_count), 10))
    last_sent_signature = None

    try:
        while True:
            payload = _build_live_payload(room_count=safe_room_count)
            signature = str(payload)

            if signature != last_sent_signature:
                await websocket.send_json(
                    {
                        "type": "live_update",
                        "data": payload,
                    }
                )
                last_sent_signature = signature

            try:
                incoming = await asyncio.wait_for(websocket.receive_json(), timeout=0.01)
                if isinstance(incoming, dict):
                    msg_type = incoming.get("type")
                    if msg_type == "ping":
                        await websocket.send_json({"type": "pong"})
                    elif msg_type == "set_room_count":
                        new_count = incoming.get("room_count")
                        if isinstance(new_count, int):
                            safe_room_count = max(1, min(new_count, 10))
                            last_sent_signature = None
            except asyncio.TimeoutError:
                pass

            await asyncio.sleep(0.35)
    except WebSocketDisconnect:
        return
    except Exception:
        try:
            await websocket.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Mission History endpoints
# ---------------------------------------------------------------------------

@app.get("/missions")
async def list_missions(limit: int = 50, offset: int = 0):
    """Returnează lista misiunilor salvate în DB (cele mai recente primele)."""
    try:
        missions = db_crud.list_missions(limit=limit, offset=offset)
        total = db_crud.count_missions()
        return {"success": True, "missions": missions, "total": total}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/missions/{mission_id}")
async def get_mission(mission_id: str):
    """Returnează detaliile complete ale unei misiuni: room scans + persoane."""
    try:
        mission = db_crud.get_mission(mission_id)
        if not mission:
            raise HTTPException(status_code=404, detail="Misiunea nu există")

        room_scans = db_crud.get_room_scans_for_mission(mission_id)
        for scan in room_scans:
            scan["persons"] = db_crud.get_persons_for_scan(scan["id"])

        videos = db_crud.get_videos_for_mission(mission_id)

        # Construiește URL-uri publice pentru videoclipuri
        base_dir = os.path.abspath(os.path.dirname(__file__))
        for video in videos:
            fp = video.get("file_path", "")
            if not fp:
                video["url"] = None
                continue
            fp_abs = os.path.abspath(fp)
            for rec_dir in ("hallway_recordings", "stairwell_recordings", "stair_climber_recordings"):
                rec_abs = os.path.abspath(os.path.join(base_dir, rec_dir))
                if os.path.normcase(fp_abs).startswith(os.path.normcase(rec_abs)):
                    rel = os.path.relpath(fp_abs, rec_abs).replace(os.sep, "/")
                    video["url"] = f"/recordings/{rec_dir}/{rel}"
                    break
            else:
                video["url"] = None

        # Construiește URL-uri publice pentru imagini în room scans și persoane
        def _to_public(path_value):
            if not path_value or not isinstance(path_value, str):
                return path_value
            if path_value.startswith("/reports/assets/"):
                return path_value
            try:
                abs_path = os.path.abspath(path_value)
                reports_abs = os.path.abspath(os.path.join(base_dir, "reports"))
                if abs_path.startswith(reports_abs):
                    rel = os.path.relpath(abs_path, reports_abs).replace(os.sep, "/")
                    return f"/reports/assets/{rel}"
            except Exception:
                pass
            return path_value

        for scan in room_scans:
            scan["pre_entry_image_path"] = _to_public(scan.get("pre_entry_image_path"))
            scan["ocr_crop_path"] = _to_public(scan.get("ocr_crop_path"))
            scan["ocr_full_frame_path"] = _to_public(scan.get("ocr_full_frame_path"))
            for person in scan.get("persons", []):
                person["image_path"] = _to_public(person.get("image_path"))

        # Telemetrie per-modul (comenzi + metrici): centrare, menținere distanță, scanare etc.
        try:
            modules = db_crud.get_modules_for_mission(mission_id)
        except Exception as _mod_err:
            print(f"⚠️ /missions: nu pot citi modulele: {_mod_err}")
            modules = []

        # Telemetrie urcare pe scări (sesiuni + zboruri + serie temporală scoruri)
        try:
            stair_climbs = db_crud.get_stair_climbs_for_mission(mission_id)
        except Exception as _sc_err:
            print(f"⚠️ /missions: nu pot citi telemetria de scări: {_sc_err}")
            stair_climbs = []

        return {
            "success": True,
            "mission": mission,
            "room_scans": room_scans,
            "videos": videos,
            "modules": modules,
            "stair_climbs": stair_climbs,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/stair_chart/{flight_id}.png")
async def stair_chart_png(flight_id: str):
    """Generează un grafic PNG cu evoluția scorurilor per semnal pentru un zbor de scară.
    Cifrele vin din stair_samples — graficul e doar o redare, deci poate fi regenerat oricând."""
    flight = db_crud.get_stair_flight_with_samples(flight_id)
    if flight is None:
        raise HTTPException(status_code=404, detail="Zbor inexistent")
    samples = flight.get("samples") or []
    if not samples:
        raise HTTPException(status_code=404, detail="Niciun eșantion pentru acest zbor")

    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import io

        t = [s.get("t") or 0 for s in samples]
        # afișăm DOAR semnalele care au fost active la urcare (evităm liniile placeholder)
        active = {s.strip() for s in (flight.get("signals") or "").split(",") if s.strip()}
        signal_series = [
            ("grad_score", "Sobel", "#b4b400", "sobel"),
            ("gabor_score", "Gabor", "#b450c8", "gabor"),
            ("depth_stair", "DA2", "#22a0ff", "da2"),
        ]

        fig, ax = plt.subplots(figsize=(9, 4.5), dpi=120)
        for key, label, color, sig in signal_series:
            if active and sig not in active:
                continue  # semnal inactiv → nu-l desenăm (ar fi linie placeholder)
            ax.plot(t, [s.get(key) or 0 for s in samples], label=label, color=color, linewidth=1.8)

        # confidence-urile finale — punctate, ca să se vadă chiar dacă coincid cu un semnal
        ax.plot(t, [s.get("stair_conf") or 0 for s in samples], label="Stair conf",
                color="#2fe38b", linewidth=2.0, linestyle="--")
        ax.plot(t, [s.get("flat_conf") or 0 for s in samples], label="Flat conf",
                color="#ff5050", linewidth=1.6, linestyle=":")

        sig_txt = flight.get("signals") or "?"
        ax.set_title(f"Stair flight {int(flight.get('flight_index', 0)) + 1} — semnale active: {sig_txt} "
                     f"(outcome: {flight.get('outcome')})")
        ax.set_xlabel("timp (s)")
        ax.set_ylabel("scor [0..1]")
        ax.set_ylim(-0.02, 1.02)
        ax.grid(True, alpha=0.25)
        ax.legend(loc="upper right", fontsize=8, ncol=3)
        fig.tight_layout()

        buf = io.BytesIO()
        fig.savefig(buf, format="png")
        plt.close(fig)
        buf.seek(0)
        return Response(content=buf.getvalue(), media_type="image/png")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Eroare generare grafic: {e}")


if __name__ == "__main__":
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    print("=" * 60)
    print("  TELLO DRONE FASTAPI SERVER")
    print("=" * 60)
    print()
    print("🌐 Server pornit pe: http://localhost:8002")
    print("📖 Documentație API: http://localhost:8002/docs")
    print("🎥 Video stream: http://localhost:8002/video/feed")
    print("🎨 Depth stream: http://localhost:8002/video/depth")
    print()
    print("Apasă Ctrl+C pentru oprire")
    print("=" * 60)
    print()

    uvicorn.run(
        app,
        host="127.0.0.1",
        port=8002,
        log_level="info",
        access_log=True,
    )
