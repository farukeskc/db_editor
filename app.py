"""
MP4 Ses Dublaj Editörü
=======================
Çok basit bir masaüstü uygulaması: bir MP4 dosyası açar, oynatırken
mikrofondan ses kaydeder ve kaydedilen sesi video ile birleştirip
(orijinal ses yerine) yeni bir MP4 dosyası olarak dışa aktarır.

Kullanılan araçlar:
 - tkinter          : arayüz
 - opencv-python     : video kare okuma / önizleme
 - Pillow            : kareleri tkinter'da gösterme
 - sounddevice       : mikrofon kaydı
 - soundfile         : kaydedilen sesi WAV olarak yazma
 - imageio-ffmpeg    : sistemde ffmpeg kurulu olmasa da ffmpeg
                        binary'sini sağlar (video + ses birleştirme)
"""

import os
import sys
import queue
import shutil
import tempfile
import threading
import subprocess
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

import cv2
import numpy as np
import soundfile as sf
import sounddevice as sd
from PIL import Image, ImageTk
import imageio_ffmpeg


APP_TITLE = "MP4 Ses Dublaj Editörü"
SAMPLE_RATE = 44100
CHANNELS = 1


class VideoInfo:
    def __init__(self, path):
        self.path = path
        cap = cv2.VideoCapture(path)
        if not cap.isOpened():
            raise ValueError("Video dosyası açılamadı.")
        self.fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
        self.frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        self.duration = self.frame_count / self.fps if self.fps else 0.0
        self.width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        self.height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        cap.release()


class AudioRecorder:
    """Mikrofondan sesi WAV dosyasına kaydeder."""

    def __init__(self, samplerate=SAMPLE_RATE, channels=CHANNELS):
        self.samplerate = samplerate
        self.channels = channels
        self._queue = queue.Queue()
        self._stream = None
        self._writer_thread = None
        self._out_path = None
        self._recording = False

    def _callback(self, indata, frames, time_info, status):
        self._queue.put(indata.copy())

    def start(self, out_path):
        self._out_path = out_path
        self._recording = True
        self._queue = queue.Queue()

        self._stream = sd.InputStream(
            samplerate=self.samplerate,
            channels=self.channels,
            callback=self._callback,
        )
        self._stream.start()

        def _writer():
            with sf.SoundFile(
                self._out_path,
                mode="w",
                samplerate=self.samplerate,
                channels=self.channels,
            ) as f:
                while self._recording or not self._queue.empty():
                    try:
                        data = self._queue.get(timeout=0.2)
                        f.write(data)
                    except queue.Empty:
                        continue

        self._writer_thread = threading.Thread(target=_writer, daemon=True)
        self._writer_thread.start()

    def stop(self):
        self._recording = False
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None
        if self._writer_thread is not None:
            self._writer_thread.join(timeout=5)
            self._writer_thread = None


class EditorApp:
    def __init__(self, root):
        self.root = root
        self.root.title(APP_TITLE)
        self.root.geometry("880x620")
        self.root.minsize(720, 520)

        self.video_info = None
        self.recorder = AudioRecorder()
        self.recording = False
        self.playing = False
        self._play_thread = None
        self._stop_flag = threading.Event()
        self._temp_dir = tempfile.mkdtemp(prefix="mp4editor_")
        self._recorded_wav = os.path.join(self._temp_dir, "recorded_audio.wav")

        self._build_ui()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ------------------------------------------------------------------ UI
    def _build_ui(self):
        top = ttk.Frame(self.root, padding=10)
        top.pack(fill="x")

        self.btn_open = ttk.Button(top, text="MP4 Aç...", command=self.open_video)
        self.btn_open.pack(side="left")

        self.lbl_file = ttk.Label(top, text="Dosya seçilmedi", foreground="#555")
        self.lbl_file.pack(side="left", padx=10)

        video_frame = ttk.Frame(self.root, padding=(10, 0))
        video_frame.pack(fill="both", expand=True)

        self.canvas = tk.Label(video_frame, background="black")
        self.canvas.pack(fill="both", expand=True)

        controls = ttk.Frame(self.root, padding=10)
        controls.pack(fill="x")

        self.btn_play = ttk.Button(
            controls, text="▶ Önizle", command=self.toggle_preview, state="disabled"
        )
        self.btn_play.pack(side="left")

        self.btn_record = ttk.Button(
            controls,
            text="● Kayda Başla (Video + Mikrofon)",
            command=self.toggle_record,
            state="disabled",
        )
        self.btn_record.pack(side="left", padx=10)

        self.btn_export = ttk.Button(
            controls,
            text="Kaydet (Yeni MP4 olarak dışa aktar)",
            command=self.export_video,
            state="disabled",
        )
        self.btn_export.pack(side="left")

        status = ttk.Frame(self.root, padding=(10, 0, 10, 10))
        status.pack(fill="x")

        self.progress = ttk.Progressbar(status, mode="determinate")
        self.progress.pack(fill="x", side="top", pady=(0, 6))

        self.lbl_status = ttk.Label(status, text="Hazır.")
        self.lbl_status.pack(anchor="w")

    def set_status(self, text):
        self.lbl_status.config(text=text)

    # --------------------------------------------------------------- Video
    def open_video(self):
        path = filedialog.askopenfilename(
            title="MP4 dosyası seç",
            filetypes=[("MP4 video", "*.mp4"), ("Tüm dosyalar", "*.*")],
        )
        if not path:
            return
        try:
            info = VideoInfo(path)
        except Exception as exc:
            messagebox.showerror("Hata", f"Video açılamadı:\n{exc}")
            return

        self.video_info = info
        self.lbl_file.config(text=f"{os.path.basename(path)}  ({info.duration:.1f} sn)")
        self.progress.config(maximum=max(info.duration, 0.01), value=0)
        self.btn_play.config(state="normal")
        self.btn_record.config(state="normal")
        self.btn_export.config(state="disabled")
        self.set_status("Video yüklendi. Önizleyebilir veya kayda başlayabilirsiniz.")
        self._show_first_frame()

    def _show_first_frame(self):
        cap = cv2.VideoCapture(self.video_info.path)
        ok, frame = cap.read()
        cap.release()
        if ok:
            self._display_frame(frame)

    def _display_frame(self, frame_bgr):
        frame_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        img = Image.fromarray(frame_rgb)

        max_w = max(self.canvas.winfo_width(), 480)
        max_h = max(self.canvas.winfo_height(), 320)
        img.thumbnail((max_w, max_h))

        photo = ImageTk.PhotoImage(image=img)
        self.canvas.configure(image=photo)
        self.canvas.image = photo  # referansı canlı tut

    # ------------------------------------------------------------- Preview
    def toggle_preview(self):
        if self.playing:
            self._stop_flag.set()
            return
        self._play_video(record_audio=False)

    # ------------------------------------------------------------- Record
    def toggle_record(self):
        if self.recording:
            self._stop_flag.set()
            return
        if not messagebox.askyesno(
            "Kayda başla",
            "Video oynatılırken mikrofonunuzdan ses kaydedilecek.\n"
            "Hazır olduğunuzda Evet'e basın.",
        ):
            return
        self._play_video(record_audio=True)

    def _play_video(self, record_audio):
        self._stop_flag.clear()
        self.playing = True
        if record_audio:
            self.recording = True
            self.btn_record.config(text="■ Kaydı Durdur")
            self.btn_play.config(state="disabled")
            self.btn_export.config(state="disabled")
            self.recorder.start(self._recorded_wav)
            self.set_status("Kayıt yapılıyor... Video oynatılıyor, mikrofon dinleniyor.")
        else:
            self.btn_play.config(text="■ Durdur")
            self.btn_record.config(state="disabled")
            self.set_status("Önizleme oynatılıyor...")

        self._play_thread = threading.Thread(
            target=self._playback_loop, args=(record_audio,), daemon=True
        )
        self._play_thread.start()

    def _playback_loop(self, record_audio):
        cap = cv2.VideoCapture(self.video_info.path)
        fps = self.video_info.fps or 25.0
        delay = 1.0 / fps
        frame_idx = 0

        import time

        start = time.time()
        while not self._stop_flag.is_set():
            ok, frame = cap.read()
            if not ok:
                break
            self.root.after(0, self._display_frame, frame)
            frame_idx += 1
            elapsed_sec = frame_idx / fps
            self.root.after(0, self._update_progress, elapsed_sec)

            target_time = start + frame_idx * delay
            sleep_for = target_time - time.time()
            if sleep_for > 0:
                time.sleep(sleep_for)

        cap.release()
        self.root.after(0, self._finish_playback, record_audio)

    def _update_progress(self, elapsed_sec):
        self.progress.config(value=min(elapsed_sec, self.video_info.duration))

    def _finish_playback(self, record_audio):
        self.playing = False
        if record_audio:
            self.recording = False
            self.recorder.stop()
            self.btn_record.config(text="● Kayda Başla (Video + Mikrofon)")
            self.btn_play.config(state="normal")
            self.btn_export.config(state="normal")
            self.set_status(
                "Kayıt tamamlandı. 'Kaydet' ile videoyla birleştirip dışa aktarabilirsiniz."
            )
        else:
            self.btn_play.config(text="▶ Önizle")
            self.btn_record.config(state="normal")
            self.set_status("Önizleme durdu.")

    # ------------------------------------------------------------- Export
    def export_video(self):
        if not os.path.exists(self._recorded_wav):
            messagebox.showwarning("Uyarı", "Önce bir ses kaydı yapmalısınız.")
            return

        default_name = os.path.splitext(os.path.basename(self.video_info.path))[0] + "_dublaj.mp4"
        out_path = filedialog.asksaveasfilename(
            title="Yeni MP4 olarak kaydet",
            defaultextension=".mp4",
            initialfile=default_name,
            filetypes=[("MP4 video", "*.mp4")],
        )
        if not out_path:
            return

        self.btn_export.config(state="disabled")
        self.set_status("Video ve ses birleştiriliyor...")
        threading.Thread(target=self._run_ffmpeg_merge, args=(out_path,), daemon=True).start()

    def _run_ffmpeg_merge(self, out_path):
        ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
        cmd = [
            ffmpeg_exe,
            "-y",
            "-i", self.video_info.path,
            "-i", self._recorded_wav,
            "-map", "0:v:0",
            "-map", "1:a:0",
            "-c:v", "copy",
            "-c:a", "aac",
            "-shortest",
            out_path,
        ]
        try:
            result = subprocess.run(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
            )
            if result.returncode != 0:
                raise RuntimeError(result.stdout[-2000:])
            self.root.after(0, self._export_done, out_path, None)
        except Exception as exc:
            self.root.after(0, self._export_done, out_path, exc)

    def _export_done(self, out_path, error):
        self.btn_export.config(state="normal")
        if error:
            self.set_status("Dışa aktarma başarısız.")
            messagebox.showerror("Hata", f"Birleştirme başarısız oldu:\n{error}")
        else:
            self.set_status(f"Tamamlandı: {out_path}")
            messagebox.showinfo("Bitti", f"Yeni video kaydedildi:\n{out_path}")

    # -------------------------------------------------------------- Close
    def _on_close(self):
        self._stop_flag.set()
        if self.recording:
            self.recorder.stop()
        try:
            shutil.rmtree(self._temp_dir, ignore_errors=True)
        except Exception:
            pass
        self.root.destroy()


def main():
    root = tk.Tk()
    try:
        from ttkthemes import ThemedStyle  # opsiyonel, kurulu değilse yoksay
        ThemedStyle(root).set_theme("arc")
    except Exception:
        pass
    app = EditorApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
