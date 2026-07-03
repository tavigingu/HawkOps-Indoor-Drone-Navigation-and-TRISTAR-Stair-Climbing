"""
Utilitar transcodare video → H.264 redabil în browser.

OpenCV scrie înregistrările cu fourcc 'mp4v' (MPEG-4 Part 2), pe care browserele
NU îl pot reda în <video> HTML5 (apar gri, fără play). Iar codec-ul nativ H.264
din OpenCV pică pe Windows (DLL openh264 versiune greșită).

Soluția: transcodăm fișierul în H.264 (yuv420p + faststart) folosind PyAV, care
aduce propriul ffmpeg cu libx264. Rezultatul e redabil direct în browser.
"""

import os

try:
    import av  # PyAV — aduce ffmpeg + libx264
except Exception:  # pragma: no cover
    av = None


def _is_browser_h264(path):
    """True dacă fișierul e deja H.264 (nu mai are nevoie de transcodare)."""
    if av is None:
        return False
    try:
        c = av.open(path)
        try:
            vs = c.streams.video[0]
            return vs.codec_context.name == "h264"
        finally:
            c.close()
    except Exception:
        return False


def ensure_browser_h264(path):
    """Transcodează `path` în H.264 redabil în browser, IN-PLACE.

    Returnează calea (aceeași) la succes sau dacă era deja H.264. La orice eroare
    returnează calea originală neatinsă (nu rupe niciodată fluxul de misiune)."""
    if av is None or not path or not os.path.isfile(path):
        return path
    if _is_browser_h264(path):
        return path

    tmp_path = path + ".h264.tmp.mp4"
    try:
        inp = av.open(path)
        in_stream = inp.streams.video[0]
        rate = in_stream.average_rate or 10

        out = av.open(tmp_path, "w", options={"movflags": "+faststart"})
        out_stream = out.add_stream("libx264", rate=rate)
        out_stream.width = in_stream.codec_context.width
        out_stream.height = in_stream.codec_context.height
        out_stream.pix_fmt = "yuv420p"
        out_stream.options = {"crf": "23", "preset": "veryfast"}

        for frame in inp.decode(in_stream):
            for pkt in out_stream.encode(frame):
                out.mux(pkt)
        for pkt in out_stream.encode():  # flush
            out.mux(pkt)

        out.close()
        inp.close()

        # înlocuiește atomic originalul
        os.replace(tmp_path, path)
        print(f"🎞️  Transcodat H.264 (browser): {os.path.basename(path)}")
        return path
    except Exception as err:
        print(f"⚠️  Transcodare H.264 eșuată pentru {os.path.basename(path)}: {err}")
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except Exception:
            pass
        return path
