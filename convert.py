import tkinter as tk
from tkinter import filedialog, ttk
import os
import subprocess
import threading
import queue
from concurrent.futures import ThreadPoolExecutor, as_completed
import time

class AudioConverter:
    def __init__(self, root):
        self.root = root
        self.root.title("Video to Audio Converter")
        self.root.geometry("1600x900")  # Kích thước cửa sổ

        # Số CPU cores để sử dụng (để lại 1 core cho hệ thống)
        self.max_workers = max(1, os.cpu_count() - 1)

        # Queue cho việc cập nhật UI
        self.progress_queue = queue.Queue()

        self.setup_ui()
        self.files_to_convert = []
        self.converting = False

        # Bắt đầu check queue để cập nhật UI
        self.check_progress_queue()

    def setup_ui(self):
        main_frame = ttk.Frame(self.root, padding="20")
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))

        # CPU Usage info
        cpu_info = f"Đang sử dụng {self.max_workers} CPU cores để xử lý"
        ttk.Label(main_frame, text=cpu_info, font=("Arial", 14)).grid(row=0, column=0, columnspan=3, padx=5, pady=5)

        # Các nút chức năng
        ttk.Button(main_frame, text="Chọn Files", command=self.select_files, width=20).grid(row=1, column=0, padx=5, pady=5)
        ttk.Button(main_frame, text="Chọn Thư mục", command=self.select_folder, width=20).grid(row=1, column=1, padx=5, pady=5)
        ttk.Button(main_frame, text="Chuyển đổi", command=self.convert_all, width=20).grid(row=1, column=2, padx=5, pady=5)

        # Listbox hiển thị các file được chọn
        self.file_listbox = tk.Listbox(main_frame, width=120, height=25, font=("Arial", 12))
        self.file_listbox.grid(row=2, column=0, columnspan=3, padx=5, pady=5)

        # Thanh cuộn
        scrollbar = ttk.Scrollbar(main_frame, orient="vertical", command=self.file_listbox.yview)
        scrollbar.grid(row=2, column=3, sticky=(tk.N, tk.S))
        self.file_listbox.configure(yscrollcommand=scrollbar.set)

        # Frame cho progress bars
        progress_frame = ttk.LabelFrame(main_frame, text="Tiến trình", padding="10")
        progress_frame.grid(row=3, column=0, columnspan=3, padx=5, pady=5, sticky="ew")

        # Progress bar tổng thể
        ttk.Label(progress_frame, text="Tổng tiến trình:", font=("Arial", 12)).grid(row=0, column=0, padx=5, pady=5)
        self.total_progress = ttk.Progressbar(progress_frame, length=1200, mode='determinate')
        self.total_progress.grid(row=0, column=1, padx=5, pady=5)
        self.total_progress_label = ttk.Label(progress_frame, text="0%", font=("Arial", 12))
        self.total_progress_label.grid(row=0, column=2, padx=5, pady=5)

        # Label trạng thái
        self.status_label = ttk.Label(main_frame, text="Sẵn sàng", font=("Arial", 14))
        self.status_label.grid(row=4, column=0, columnspan=3, padx=5, pady=5)

        # Label hiển thị ETA
        self.eta_label = ttk.Label(main_frame, text="Thời gian dự kiến: --:--:--", font=("Arial", 14))
        self.eta_label.grid(row=5, column=0, columnspan=3, padx=5, pady=5)

    def check_progress_queue(self):
        try:
            while True:
                msg = self.progress_queue.get_nowait()
                if msg[0] == "progress":
                    self.update_progress(msg[1])
                elif msg[0] == "status":
                    self.status_label.config(text=msg[1])
                elif msg[0] == "eta":
                    self.eta_label.config(text=f"Thời gian dự kiến: {msg[1]}")
        except queue.Empty:
            pass
        finally:
            self.root.after(100, self.check_progress_queue)

    def update_progress(self, value):
        self.total_progress['value'] = value
        self.total_progress_label.config(text=f"{value}%")

    def select_files(self):
        if self.converting:
            return
        files = filedialog.askopenfilenames(
            title="Chọn video files",
            filetypes=[("Video files", "*.mp4")]
        )
        self.add_files(files)

    def select_folder(self):
        if self.converting:
            return
        folder = filedialog.askdirectory(title="Chọn thư mục chứa video")
        if folder:
            video_files = []
            for root, dirs, files in os.walk(folder):
                for file in files:
                    if file.endswith('.mp4'):
                        video_files.append(os.path.join(root, file))
            self.add_files(video_files)

    def add_files(self, files):
        for file in files:
            if file not in self.files_to_convert:
                self.files_to_convert.append(file)
                self.file_listbox.insert(tk.END, file)

    def get_video_duration(self, input_path):
        """
        Lấy tổng thời lượng của video (tính bằng giây).
        """
        command = [
            "ffprobe",
            "-i", input_path,
            "-show_entries", "format=duration",
            "-v", "quiet",
            "-of", "csv=p=0"
        ]
        try:
            result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8', errors='ignore')
            duration = float(result.stdout.strip())
            return duration
        except Exception as e:
            print(f"Lỗi khi lấy thời lượng video: {e}")
            return None

    def convert_with_ffmpeg(self, input_path, output_path, start_time):
        """
        Chuyển đổi file video sang âm thanh bằng ffmpeg với tiến trình theo dõi thời gian thực.
        """
        total_duration = self.get_video_duration(input_path)
        if total_duration is None:
            return False

        command = [
            "ffmpeg",
            "-hwaccel", "cuda",  # Sử dụng GPU NVIDIA
            "-i", input_path,
            "-vn",  # Bỏ video, chỉ giữ âm thanh
            "-c:a", "libmp3lame",  # Codec âm thanh
            "-qscale:a", "2",  # Chất lượng cao
            "-threads", str(self.max_workers),  # Tận dụng nhiều CPU threads
            output_path
        ]

        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            universal_newlines=True,
            encoding='utf-8',
            errors='ignore'
        )

        last_update_time = start_time
        last_progress = 0

        while True:
            line = process.stdout.readline()
            if not line:
                break

            # Tìm thời gian đã xử lý trong dòng đầu ra của ffmpeg
            if "time=" in line:
                time_str = line.split("time=")[1].split()[0]
                hours, minutes, seconds = map(float, time_str.split(":"))
                current_time = hours * 3600 + minutes * 60 + seconds
                progress = int((current_time / total_duration) * 100)

                # Tính ETA
                current_real_time = time.time()
                elapsed_time = current_real_time - last_update_time
                if elapsed_time > 0 and progress > last_progress:
                    speed = (progress - last_progress) / elapsed_time  # Phần trăm mỗi giây
                    remaining_percent = 100 - progress
                    eta_seconds = remaining_percent / speed if speed > 0 else 0
                    eta_formatted = time.strftime("%H:%M:%S", time.gmtime(eta_seconds))
                    self.progress_queue.put(("eta", eta_formatted))

                    last_update_time = current_real_time
                    last_progress = progress

                self.progress_queue.put(("progress", progress))

        process.wait()
        return process.returncode == 0

    def convert_all(self):
        if not self.files_to_convert or self.converting:
            return
        self.converting = True
        total_files = len(self.files_to_convert)
        start_time = time.time()  # Ghi nhận thời gian bắt đầu
        self.progress_queue.put(("status", "Đang bắt đầu chuyển đổi..."))

        def process_files():
            success_count = 0
            with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                futures = {
                    executor.submit(self.process_single_file, file, i, total_files, start_time): file
                    for i, file in enumerate(self.files_to_convert)
                }

                for future in as_completed(futures):
                    if future.result():
                        success_count += 1

            self.progress_queue.put(("status", 
                f"Hoàn thành! {success_count}/{total_files} files đã được chuyển đổi"))
            
            self.converting = False
            self.files_to_convert = []
            self.root.after(0, lambda: self.file_listbox.delete(0, tk.END))

        # Bắt đầu xử lý trong thread riêng
        threading.Thread(target=process_files, daemon=True).start()

    def process_single_file(self, input_path, index, total_files, start_time):
        # Lưu file output cùng thư mục với file input
        output_filename = os.path.splitext(os.path.basename(input_path))[0] + ".mp3"
        output_dir = os.path.dirname(input_path)
        output_path = os.path.join(output_dir, output_filename)

        self.progress_queue.put(("status", f"Đang chuyển đổi file {index + 1}/{total_files}: {os.path.basename(input_path)}"))
        success = self.convert_with_ffmpeg(input_path, output_path, start_time)
        return success

def main():
    root = tk.Tk()
    app = AudioConverter(root)
    root.mainloop()

if __name__ == "__main__":
    main()