"""
MP4 Kesme (Cut) Editörü
=======================
app.py'daki dublaj editörüne benzer, çok basit bir masaüstü uygulama:
bir MP4 dosyası açar, zaman çizelgesinde gezinerek videodan çıkarmak
istediğiniz bir veya daha fazla bölümü işaretlemenizi sağlar; bu
bölümler videodan silinir ve kalan parçalar birleştirilip yeni bir MP4
dosyası olarak dışa aktarılır (yani "kes ve çıkar", tersine "yalnızca
seçileni tut" değil). Ayrıca videonun belirli bir anındaki kareyi bir
süreliğine dondurup videoyu o kadar uzatan bir "kare dondurma"
mekanizması da içerir (ör. bir ekranda durup üzerine konuşma kaydetmek
için).

Kullanılan araçlar:
 - tkinter          : arayüz
 - opencv-python     : video kare okuma / önizleme
 - Pillow            : kareleri tkinter'da gösterme
 - imageio-ffmpeg    : sistemde ffmpeg kurulu olmasa da ffmpeg
                        binary'sini sağlar (kesme / kare dondurma işlemi)
"""

import os
import shutil
import tempfile
import time
import threading
import subprocess
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

import cv2
from PIL import Image, ImageTk
import imageio_ffmpeg


APP_TITLE = "MP4 Kesme Editörü"


def format_time(seconds):
    """Saniyeyi 'M:SS.s' biçiminde metne çevirir."""
    seconds = max(seconds, 0)
    minutes = int(seconds // 60)
    secs = seconds - minutes * 60
    return f"{minutes}:{secs:04.1f}"


def merge_segments(segments):
    """Çakışan/bitişik (başlangıç, bitiş) aralıklarını birleştirip
    başlangıca göre sıralanmış, ayrık bir liste döndürür."""
    valid = sorted((max(s, 0.0), max(e, 0.0)) for s, e in segments if e > s)
    if not valid:
        return []
    merged = [list(valid[0])]
    for start, end in valid[1:]:
        if start <= merged[-1][1] + 0.05:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return [(s, e) for s, e in merged]


def complement_segments(removed, total_duration):
    """Çıkarılacak aralıkların (removed) tümleyenini, yani videodan
    korunacak aralıkları döndürür."""
    keep = []
    cursor = 0.0
    for start, end in removed:
        if start > cursor + 0.05:
            keep.append((cursor, start))
        cursor = max(cursor, end)
    if cursor < total_duration - 0.05:
        keep.append((cursor, total_duration))
    return keep


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


class CutterApp:
    def __init__(self, root):
        self.root = root
        self.root.title(APP_TITLE)
        self.root.geometry("880x760")
        self.root.minsize(720, 640)

        self.video_info = None
        self.playing = False
        self._play_thread = None
        self._stop_flag = threading.Event()
        self._seeking = False

        self.start_time = 0.0
        self.end_time = 0.0
        self.freeze_time = 0.0
        self.removed_segments = []
        self._temp_dir = tempfile.mkdtemp(prefix="cutter_editor_")

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

        # ------------------------------------------------------- Zaman çubuğu
        timeline = ttk.Frame(self.root, padding=10)
        timeline.pack(fill="x")

        self.pos_var = tk.DoubleVar(value=0.0)
        self.scale = ttk.Scale(
            timeline,
            from_=0,
            to=1,
            orient="horizontal",
            variable=self.pos_var,
            command=self._on_scale_move,
            state="disabled",
        )
        self.scale.pack(fill="x", side="top")

        time_row = ttk.Frame(timeline)
        time_row.pack(fill="x", pady=(4, 0))
        self.lbl_time = ttk.Label(time_row, text="0:00.0 / 0:00.0")
        self.lbl_time.pack(side="left")

        self.btn_play = ttk.Button(
            time_row, text="▶ Oynat", command=self.toggle_play, state="disabled"
        )
        self.btn_play.pack(side="right")

        # --------------------------------------------------------- İşaretleme
        mark_frame = ttk.LabelFrame(
            self.root, text="Çıkarılacak Bölümler (videodan silinecek aralıklar)", padding=10
        )
        mark_frame.pack(fill="x", padx=10, pady=(0, 10))

        ttk.Label(mark_frame, text="Başlangıç (sn):").grid(row=0, column=0, sticky="w")
        self.start_var = tk.StringVar(value="0.0")
        self.start_entry = ttk.Entry(mark_frame, textvariable=self.start_var, width=10)
        self.start_entry.grid(row=0, column=1, padx=(4, 10))
        self.btn_mark_start = ttk.Button(
            mark_frame,
            text="Buradan İşaretle",
            command=self.mark_start,
            state="disabled",
        )
        self.btn_mark_start.grid(row=0, column=2, padx=(0, 4))
        self.btn_goto_start = ttk.Button(
            mark_frame, text="Git", width=5, command=self.goto_start, state="disabled"
        )
        self.btn_goto_start.grid(row=0, column=3)

        ttk.Label(mark_frame, text="Bitiş (sn):").grid(row=1, column=0, sticky="w", pady=(6, 0))
        self.end_var = tk.StringVar(value="0.0")
        self.end_entry = ttk.Entry(mark_frame, textvariable=self.end_var, width=10)
        self.end_entry.grid(row=1, column=1, padx=(4, 10), pady=(6, 0))
        self.btn_mark_end = ttk.Button(
            mark_frame,
            text="Buradan İşaretle",
            command=self.mark_end,
            state="disabled",
        )
        self.btn_mark_end.grid(row=1, column=2, padx=(0, 4), pady=(6, 0))
        self.btn_goto_end = ttk.Button(
            mark_frame, text="Git", width=5, command=self.goto_end, state="disabled"
        )
        self.btn_goto_end.grid(row=1, column=3, pady=(6, 0))

        self.lbl_selection = ttk.Label(mark_frame, text="Yeni bölüm: 0.0 sn")
        self.lbl_selection.grid(row=2, column=0, columnspan=2, sticky="w", pady=(8, 0))

        self.btn_preview_sel = ttk.Button(
            mark_frame,
            text="Seçimi Önizle",
            command=self.preview_selection,
            state="disabled",
        )
        self.btn_preview_sel.grid(row=2, column=2, sticky="w", pady=(8, 0))

        self.btn_add_segment = ttk.Button(
            mark_frame,
            text="➕ Bu Aralığı Listeye Ekle",
            command=self.add_segment,
            state="disabled",
        )
        self.btn_add_segment.grid(row=2, column=3, sticky="w", pady=(8, 0))

        list_row = ttk.Frame(mark_frame)
        list_row.grid(row=3, column=0, columnspan=4, sticky="we", pady=(8, 0))
        mark_frame.grid_columnconfigure(3, weight=1)

        self.segment_listbox = tk.Listbox(list_row, height=5, exportselection=False)
        self.segment_listbox.pack(side="left", fill="both", expand=True)
        segment_scroll = ttk.Scrollbar(
            list_row, orient="vertical", command=self.segment_listbox.yview
        )
        segment_scroll.pack(side="left", fill="y")
        self.segment_listbox.config(yscrollcommand=segment_scroll.set)

        list_btn_row = ttk.Frame(mark_frame)
        list_btn_row.grid(row=4, column=0, columnspan=4, sticky="w", pady=(6, 0))

        self.btn_delete_segment = ttk.Button(
            list_btn_row,
            text="Seçili Satırı Sil",
            command=self.delete_selected_segment,
            state="disabled",
        )
        self.btn_delete_segment.pack(side="left")

        self.btn_clear_segments = ttk.Button(
            list_btn_row,
            text="Listeyi Temizle",
            command=self.clear_segments,
            state="disabled",
        )
        self.btn_clear_segments.pack(side="left", padx=(8, 0))

        self.lbl_removal_summary = ttk.Label(mark_frame, text="0 bölüm çıkarılacak.")
        self.lbl_removal_summary.grid(row=5, column=0, columnspan=4, sticky="w", pady=(8, 0))

        self.precise_var = tk.BooleanVar(value=False)
        self.chk_precise = ttk.Checkbutton(
            mark_frame,
            text="Kare hassasiyetiyle kes (yeniden kodla, daha yavaş)",
            variable=self.precise_var,
        )
        self.chk_precise.grid(row=6, column=0, columnspan=4, sticky="w", pady=(6, 0))

        # ------------------------------------------------------- Kare Dondurma
        freeze_frame = ttk.LabelFrame(
            self.root, text="Kare Dondur (Durup Konuşma Kaydı için)", padding=10
        )
        freeze_frame.pack(fill="x", padx=10, pady=(0, 10))

        ttk.Label(freeze_frame, text="Dondurulacak an (sn):").grid(
            row=0, column=0, sticky="w"
        )
        self.freeze_var = tk.StringVar(value="0.0")
        self.freeze_entry = ttk.Entry(freeze_frame, textvariable=self.freeze_var, width=10)
        self.freeze_entry.grid(row=0, column=1, padx=(4, 10))
        self.btn_mark_freeze = ttk.Button(
            freeze_frame,
            text="Buradan İşaretle",
            command=self.mark_freeze,
            state="disabled",
        )
        self.btn_mark_freeze.grid(row=0, column=2, padx=(0, 4))
        self.btn_goto_freeze = ttk.Button(
            freeze_frame, text="Git", width=5, command=self.goto_freeze, state="disabled"
        )
        self.btn_goto_freeze.grid(row=0, column=3)

        ttk.Label(freeze_frame, text="Dondurma süresi (sn):").grid(
            row=1, column=0, sticky="w", pady=(6, 0)
        )
        self.freeze_duration_var = tk.StringVar(value="3.0")
        self.freeze_duration_entry = ttk.Entry(
            freeze_frame, textvariable=self.freeze_duration_var, width=10
        )
        self.freeze_duration_entry.grid(row=1, column=1, padx=(4, 10), pady=(6, 0))

        self.btn_freeze = ttk.Button(
            freeze_frame,
            text="🧊 Kareyi Dondur ve Dışa Aktar",
            command=self.freeze_export,
            state="disabled",
        )
        self.btn_freeze.grid(row=1, column=2, columnspan=2, sticky="w", pady=(6, 0))

        ttk.Label(
            freeze_frame,
            text=(
                "Seçilen andaki kare belirtilen süre boyunca ekranda sabit kalır,\n"
                "bu süre videonun toplam uzunluğuna eklenir (ses o bölümde sessizdir)."
            ),
            foreground="#555",
        ).grid(row=2, column=0, columnspan=4, sticky="w", pady=(6, 0))

        # ---------------------------------------------------------- Kontroller
        controls = ttk.Frame(self.root, padding=(10, 0, 10, 10))
        controls.pack(fill="x")

        self.btn_cut = ttk.Button(
            controls,
            text="✂ Bölümleri Çıkar ve Dışa Aktar",
            command=self.export_without_segments,
            state="disabled",
        )
        self.btn_cut.pack(side="left")

        status = ttk.Frame(self.root, padding=(10, 0, 10, 10))
        status.pack(fill="x")

        self.progress = ttk.Progressbar(status, mode="indeterminate")
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
        self.start_time = 0.0
        self.end_time = info.duration
        self.freeze_time = 0.0
        self.removed_segments = []
        self.start_var.set(f"{self.start_time:.1f}")
        self.end_var.set(f"{self.end_time:.1f}")
        self.freeze_var.set("0.0")

        self.lbl_file.config(text=f"{os.path.basename(path)}  ({info.duration:.1f} sn)")
        self.scale.config(from_=0, to=max(info.duration, 0.01), state="normal")
        self.pos_var.set(0.0)

        for btn in (
            self.btn_play,
            self.btn_mark_start,
            self.btn_mark_end,
            self.btn_goto_start,
            self.btn_goto_end,
            self.btn_preview_sel,
            self.btn_add_segment,
            self.btn_delete_segment,
            self.btn_clear_segments,
            self.btn_cut,
            self.btn_mark_freeze,
            self.btn_goto_freeze,
            self.btn_freeze,
        ):
            btn.config(state="normal")
        self.segment_listbox.config(state="normal")

        self._update_selection_label()
        self._refresh_segment_list()
        self.set_status(
            "Video yüklendi. Çıkarmak istediğiniz aralığı işaretleyip listeye ekleyin."
        )
        self._seek_to(0.0)

    def _seek_to(self, seconds):
        """Belirtilen saniyedeki kareyi okuyup önizleme alanında gösterir."""
        cap = cv2.VideoCapture(self.video_info.path)
        cap.set(cv2.CAP_PROP_POS_MSEC, max(seconds, 0) * 1000)
        ok, frame = cap.read()
        cap.release()
        if ok:
            self._display_frame(frame)
        self._update_time_label(seconds)

    def _display_frame(self, frame_bgr):
        frame_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        img = Image.fromarray(frame_rgb)

        max_w = max(self.canvas.winfo_width(), 480)
        max_h = max(self.canvas.winfo_height(), 320)
        img.thumbnail((max_w, max_h))

        photo = ImageTk.PhotoImage(image=img)
        self.canvas.configure(image=photo)
        self.canvas.image = photo  # referansı canlı tut

    def _update_time_label(self, current):
        total = self.video_info.duration if self.video_info else 0.0
        self.lbl_time.config(text=f"{format_time(current)} / {format_time(total)}")

    def _update_selection_label(self):
        length = max(self.end_time - self.start_time, 0.0)
        self.lbl_selection.config(
            text=(
                f"Yeni bölüm: {format_time(self.start_time)} → "
                f"{format_time(self.end_time)}  ({length:.1f} sn)"
            )
        )

    # ------------------------------------------------------------ Zaman çubuğu
    def _on_scale_move(self, value):
        if self.playing:
            return
        self._seek_to(float(value))

    # ----------------------------------------------------------- İşaretleme
    def mark_start(self):
        self.start_time = self.pos_var.get()
        if self.start_time > self.end_time:
            self.end_time = self.video_info.duration
            self.end_var.set(f"{self.end_time:.1f}")
        self.start_var.set(f"{self.start_time:.1f}")
        self._update_selection_label()

    def mark_end(self):
        self.end_time = self.pos_var.get()
        if self.end_time < self.start_time:
            self.start_time = 0.0
            self.start_var.set(f"{self.start_time:.1f}")
        self.end_var.set(f"{self.end_time:.1f}")
        self._update_selection_label()

    def _read_time_entry(self, var, fallback):
        try:
            value = float(var.get())
        except ValueError:
            return fallback
        return min(max(value, 0.0), self.video_info.duration if self.video_info else value)

    def goto_start(self):
        self.start_time = self._read_time_entry(self.start_var, self.start_time)
        self.start_var.set(f"{self.start_time:.1f}")
        self.pos_var.set(self.start_time)
        self._seek_to(self.start_time)
        self._update_selection_label()

    def goto_end(self):
        self.end_time = self._read_time_entry(self.end_var, self.end_time)
        self.end_var.set(f"{self.end_time:.1f}")
        self.pos_var.set(self.end_time)
        self._seek_to(self.end_time)
        self._update_selection_label()

    # ----------------------------------------------------- Çıkarma Listesi
    def add_segment(self):
        start = self._read_time_entry(self.start_var, self.start_time)
        end = self._read_time_entry(self.end_var, self.end_time)
        if end <= start:
            messagebox.showwarning("Uyarı", "Bitiş zamanı başlangıçtan büyük olmalı.")
            return
        self.start_time, self.end_time = start, end
        self.removed_segments.append((start, end))
        self._refresh_segment_list()
        self.set_status("Bölüm çıkarma listesine eklendi.")

    def _refresh_segment_list(self):
        self.removed_segments = merge_segments(self.removed_segments)
        self.segment_listbox.delete(0, tk.END)
        for start, end in self.removed_segments:
            self.segment_listbox.insert(
                tk.END,
                f"{format_time(start)} → {format_time(end)}   ({end - start:.1f} sn)",
            )
        self._update_removal_summary()

    def _update_removal_summary(self):
        total = self.video_info.duration if self.video_info else 0.0
        removed = sum(end - start for start, end in self.removed_segments)
        remaining = max(total - removed, 0.0)
        self.lbl_removal_summary.config(
            text=(
                f"{len(self.removed_segments)} bölüm çıkarılacak ({removed:.1f} sn)  "
                f"→  kalan video uzunluğu: {remaining:.1f} sn"
            )
        )

    def delete_selected_segment(self):
        selection = self.segment_listbox.curselection()
        if not selection:
            return
        del self.removed_segments[selection[0]]
        self._refresh_segment_list()

    def clear_segments(self):
        if not self.removed_segments:
            return
        if messagebox.askyesno("Listeyi Temizle", "Çıkarma listesindeki tüm bölümler silinsin mi?"):
            self.removed_segments = []
            self._refresh_segment_list()

    def mark_freeze(self):
        self.freeze_time = self.pos_var.get()
        self.freeze_var.set(f"{self.freeze_time:.1f}")

    def goto_freeze(self):
        self.freeze_time = self._read_time_entry(self.freeze_var, self.freeze_time)
        self.freeze_var.set(f"{self.freeze_time:.1f}")
        self.pos_var.set(self.freeze_time)
        self._seek_to(self.freeze_time)

    # ------------------------------------------------------------- Oynatma
    def toggle_play(self):
        if self.playing:
            self._stop_flag.set()
            return
        self._play_video(self.pos_var.get(), self.video_info.duration)

    def preview_selection(self):
        if self.playing:
            return
        start = self._read_time_entry(self.start_var, self.start_time)
        end = self._read_time_entry(self.end_var, self.end_time)
        if end <= start:
            messagebox.showwarning("Uyarı", "Bitiş zamanı başlangıçtan büyük olmalı.")
            return
        self._play_video(start, end)

    def _play_video(self, start_sec, end_sec):
        self._stop_flag.clear()
        self.playing = True
        self.pos_var.set(start_sec)
        self.btn_play.config(text="■ Durdur")
        self.btn_preview_sel.config(state="disabled")
        self.btn_cut.config(state="disabled")
        self.set_status("Oynatılıyor...")

        self._play_thread = threading.Thread(
            target=self._playback_loop, args=(start_sec, end_sec), daemon=True
        )
        self._play_thread.start()

    def _playback_loop(self, start_sec, end_sec):
        cap = cv2.VideoCapture(self.video_info.path)
        cap.set(cv2.CAP_PROP_POS_MSEC, start_sec * 1000)
        fps = self.video_info.fps or 25.0
        delay = 1.0 / fps

        start_wall = time.time()
        frame_idx = 0
        while not self._stop_flag.is_set():
            ok, frame = cap.read()
            if not ok:
                break
            current = start_sec + frame_idx / fps
            if current >= end_sec:
                break
            self.root.after(0, self._display_frame, frame)
            self.root.after(0, self._update_playhead, current)
            frame_idx += 1

            target_time = start_wall + frame_idx * delay
            sleep_for = target_time - time.time()
            if sleep_for > 0:
                time.sleep(sleep_for)

        cap.release()
        self.root.after(0, self._finish_playback)

    def _update_playhead(self, current):
        self.pos_var.set(current)
        self._update_time_label(current)

    def _finish_playback(self):
        self.playing = False
        self.btn_play.config(text="▶ Oynat")
        self.btn_preview_sel.config(state="normal")
        self.btn_cut.config(state="normal")
        self.set_status("Oynatma durdu.")

    # --------------------------------------------------------------- Kesme
    @staticmethod
    def _ffmpeg_run(cmd):
        result = subprocess.run(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
        )
        if result.returncode != 0:
            raise RuntimeError(result.stdout[-2000:])

    def _build_cut_command(self, start, end, precise, out_path):
        ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
        duration = max(end - start, 0.01)

        if precise:
            # -ss girişten sonra: yavaş ama kare hassasiyetli (yeniden kodlar).
            return [
                ffmpeg_exe, "-y",
                "-i", self.video_info.path,
                "-ss", f"{start:.3f}",
                "-t", f"{duration:.3f}",
                "-pix_fmt", "yuv420p",
                "-c:v", "libx264",
                "-c:a", "aac", "-ar", "44100", "-ac", "2",
                out_path,
            ]
        # -ss girişten önce: hızlı (stream copy), ama en yakın keyframe'e
        # yuvarlanabilir.
        return [
            ffmpeg_exe, "-y",
            "-ss", f"{start:.3f}",
            "-i", self.video_info.path,
            "-t", f"{duration:.3f}",
            "-c", "copy",
            out_path,
        ]

    def _concat_via_demuxer(self, work_dir, segment_paths, out_path):
        ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
        concat_list = os.path.join(work_dir, "concat.txt")
        with open(concat_list, "w", encoding="utf-8") as f:
            for p in segment_paths:
                escaped = p.replace("'", "'\\''")
                f.write(f"file '{escaped}'\n")

        try:
            self._ffmpeg_run([
                ffmpeg_exe, "-y",
                "-f", "concat", "-safe", "0",
                "-i", concat_list,
                "-c", "copy",
                out_path,
            ])
        except Exception:
            # Parametre uyuşmazlığı gibi bir sebeple kopyalama başarısız
            # olursa, birleştirirken yeniden kodlayarak tekrar dene.
            self._ffmpeg_run([
                ffmpeg_exe, "-y",
                "-f", "concat", "-safe", "0",
                "-i", concat_list,
                "-pix_fmt", "yuv420p",
                "-c:v", "libx264",
                "-c:a", "aac",
                out_path,
            ])

    def export_without_segments(self):
        if not self.video_info:
            return
        if not self.removed_segments:
            messagebox.showwarning(
                "Uyarı", "Önce çıkarmak istediğiniz en az bir bölümü listeye ekleyin."
            )
            return

        keep_segments = complement_segments(self.removed_segments, self.video_info.duration)
        if not keep_segments:
            messagebox.showwarning(
                "Uyarı", "Videonun tamamı çıkarılamaz; en az bir bölüm kalmalı."
            )
            return

        base = os.path.splitext(os.path.basename(self.video_info.path))[0]
        default_name = f"{base}_kesildi.mp4"
        out_path = filedialog.asksaveasfilename(
            title="Kesilmiş videoyu kaydet",
            defaultextension=".mp4",
            initialfile=default_name,
            filetypes=[("MP4 video", "*.mp4")],
        )
        if not out_path:
            return

        self.btn_cut.config(state="disabled")
        self.progress.start(12)
        self.set_status("Seçilen bölümler çıkarılıyor...")
        threading.Thread(
            target=self._run_remove_segments,
            args=(out_path, keep_segments, self.precise_var.get()),
            daemon=True,
        ).start()

    def _run_remove_segments(self, out_path, keep_segments, precise):
        """`keep_segments` içindeki aralıkları çıkarıp (kalanları koruyarak)
        tek bir MP4 olarak birleştirir. Böylece `keep_segments` arasındaki
        boşluklar -yani kullanıcının işaretlediği bölümler- videodan
        çıkarılmış olur."""
        work_dir = tempfile.mkdtemp(prefix="remove_", dir=self._temp_dir)
        try:
            if len(keep_segments) == 1:
                start, end = keep_segments[0]
                self._ffmpeg_run(self._build_cut_command(start, end, precise, out_path))
            else:
                segment_paths = []
                for idx, (start, end) in enumerate(keep_segments):
                    part_path = os.path.join(work_dir, f"part_{idx}.mp4")
                    self._ffmpeg_run(self._build_cut_command(start, end, precise, part_path))
                    segment_paths.append(part_path)
                self._concat_via_demuxer(work_dir, segment_paths, out_path)

            self.root.after(0, self._remove_segments_done, out_path, None)
        except Exception as exc:
            self.root.after(0, self._remove_segments_done, out_path, exc)
        finally:
            shutil.rmtree(work_dir, ignore_errors=True)

    def _remove_segments_done(self, out_path, error):
        self.progress.stop()
        self.btn_cut.config(state="normal")
        if error:
            self.set_status("Kesme işlemi başarısız.")
            messagebox.showerror("Hata", f"Video oluşturulamadı:\n{error}")
        else:
            self.set_status(f"Tamamlandı: {out_path}")
            messagebox.showinfo("Bitti", f"Kesilmiş video kaydedildi:\n{out_path}")

    # --------------------------------------------------------- Kare Dondurma
    def freeze_export(self):
        if not self.video_info:
            return

        freeze_time = self._read_time_entry(self.freeze_var, self.freeze_time)
        try:
            freeze_duration = float(self.freeze_duration_var.get())
        except ValueError:
            freeze_duration = 0.0
        if freeze_duration <= 0:
            messagebox.showwarning("Uyarı", "Dondurma süresi 0'dan büyük olmalı.")
            return

        self.freeze_time = freeze_time
        self.freeze_var.set(f"{freeze_time:.1f}")

        base = os.path.splitext(os.path.basename(self.video_info.path))[0]
        default_name = f"{base}_donduruldu.mp4"
        out_path = filedialog.asksaveasfilename(
            title="Dondurulmuş videoyu kaydet",
            defaultextension=".mp4",
            initialfile=default_name,
            filetypes=[("MP4 video", "*.mp4")],
        )
        if not out_path:
            return

        self.btn_freeze.config(state="disabled")
        self.progress.start(12)
        self.set_status("Kare donduruluyor ve video oluşturuluyor...")
        threading.Thread(
            target=self._run_freeze_export,
            args=(out_path, freeze_time, freeze_duration),
            daemon=True,
        ).start()

    def _run_freeze_export(self, out_path, freeze_time, freeze_duration):
        """Videoyu [0, T] + [dondurulmuş kare x süre] + [T, son] olarak
        yeniden birleştirip tek bir MP4 olarak dışa aktarır."""
        ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
        work_dir = tempfile.mkdtemp(prefix="freeze_", dir=self._temp_dir)

        try:
            fps = self.video_info.fps or 25.0
            total_duration = self.video_info.duration
            freeze_time = min(max(freeze_time, 0.0), total_duration)
            tail_duration = total_duration - freeze_time

            frame_path = os.path.join(work_dir, "frame.png")
            part_a = os.path.join(work_dir, "part_a.mp4")
            freeze_clip = os.path.join(work_dir, "freeze.mp4")
            part_b = os.path.join(work_dir, "part_b.mp4")

            # 1) Dondurulacak andaki kareyi PNG olarak çıkar.
            self._ffmpeg_run([
                ffmpeg_exe, "-y",
                "-i", self.video_info.path,
                "-ss", f"{freeze_time:.3f}",
                "-frames:v", "1",
                frame_path,
            ])

            segment_paths = []

            # 2) Baştan donma anına kadar olan parça (varsa).
            if freeze_time > 0.05:
                self._ffmpeg_run([
                    ffmpeg_exe, "-y",
                    "-i", self.video_info.path,
                    "-t", f"{freeze_time:.3f}",
                    "-r", f"{fps:.3f}",
                    "-pix_fmt", "yuv420p",
                    "-c:v", "libx264",
                    "-c:a", "aac", "-ar", "44100", "-ac", "2",
                    part_a,
                ])
                segment_paths.append(part_a)

            # 3) Dondurulan kare + sessiz ses, istenen süre boyunca.
            self._ffmpeg_run([
                ffmpeg_exe, "-y",
                "-loop", "1", "-i", frame_path,
                "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
                "-t", f"{freeze_duration:.3f}",
                "-r", f"{fps:.3f}",
                "-pix_fmt", "yuv420p",
                "-c:v", "libx264",
                "-c:a", "aac", "-ar", "44100", "-ac", "2",
                "-shortest",
                freeze_clip,
            ])
            segment_paths.append(freeze_clip)

            # 4) Donma anından videonun sonuna kadar olan parça (varsa).
            if tail_duration > 0.05:
                self._ffmpeg_run([
                    ffmpeg_exe, "-y",
                    "-ss", f"{freeze_time:.3f}",
                    "-i", self.video_info.path,
                    "-t", f"{tail_duration:.3f}",
                    "-r", f"{fps:.3f}",
                    "-pix_fmt", "yuv420p",
                    "-c:v", "libx264",
                    "-c:a", "aac", "-ar", "44100", "-ac", "2",
                    part_b,
                ])
                segment_paths.append(part_b)

            # 5) Parçaları concat demuxer ile tek dosyada birleştir.
            self._concat_via_demuxer(work_dir, segment_paths, out_path)

            self.root.after(0, self._freeze_done, out_path, None)
        except Exception as exc:
            self.root.after(0, self._freeze_done, out_path, exc)
        finally:
            shutil.rmtree(work_dir, ignore_errors=True)

    def _freeze_done(self, out_path, error):
        self.progress.stop()
        self.btn_freeze.config(state="normal")
        if error:
            self.set_status("Kare dondurma işlemi başarısız.")
            messagebox.showerror("Hata", f"Video oluşturulamadı:\n{error}")
        else:
            self.set_status(f"Tamamlandı: {out_path}")
            messagebox.showinfo("Bitti", f"Dondurulmuş video kaydedildi:\n{out_path}")

    # -------------------------------------------------------------- Kapatma
    def _on_close(self):
        self._stop_flag.set()
        shutil.rmtree(self._temp_dir, ignore_errors=True)
        self.root.destroy()


def main():
    root = tk.Tk()
    try:
        from ttkthemes import ThemedStyle  # opsiyonel, kurulu değilse yoksay
        ThemedStyle(root).set_theme("arc")
    except Exception:
        pass
    app = CutterApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
