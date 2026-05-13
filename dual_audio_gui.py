import queue
import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox

import pyaudiowpatch as pyaudio


APP_TITLE = "Dual Bluetooth Audio Mirror"

BAD_TERMS = [
    "hands-free",
    "handsfree",
    "ag audio",
    "headset",
    "telephony",
    "hf audio",
    "bluetooth audio gateway",
]

FORMAT_OPTIONS = {
    "Float32 - best internal quality": pyaudio.paFloat32,
    "Int16 - best compatibility": pyaudio.paInt16,
}
  #Can be changed for your needs.
PROFILE_OPTIONS = {
    "High quality / stable Bluetooth": {
        "chunk": 2048,
        "queue": 24,
    },
    "Balanced": {
        "chunk": 1024,
        "queue": 12,
    },
    "Lower latency / less stable": {
        "chunk": 512,
        "queue": 8,
    },
}


def is_bad_mode(name: str) -> bool:
    name = name.lower()
    return any(term in name for term in BAD_TERMS)


def clean_name(name: str) -> str:
    name = name.lower()

    remove_terms = [
        "loopback",
        "[loopback]",
        "(loopback)",
        "wasapi",
        "speakers",
        "speaker",
        "headphones",
        "headphone",
        "stereo",
        "output",
    ]

    for term in remove_terms:
        name = name.replace(term, "")

    return " ".join(name.split())

#MAYBEEEE...
def maybe_same_device(source_name: str, output_name: str) -> bool:
    source_clean = clean_name(source_name)
    output_clean = clean_name(output_name)

    if not source_clean or not output_clean:
        return False

    return source_clean in output_clean or output_clean in source_clean


class AudioMirrorEngine:
    def __init__(
            self,
            source_index,
            output_indexes,
            audio_format,
            chunk_size,
            queue_size,
            log_callback,
            stop_event,
    ):
        self.source_index = source_index
        self.output_indexes = output_indexes
        self.audio_format = audio_format
        self.chunk_size = chunk_size
        self.queue_size = queue_size
        self.log = log_callback
        self.stop_event = stop_event

        self.p = None
        self.input_stream = None
        self.output_streams = []
        self.output_queues = []
        self.output_threads = []

    def start(self):
        try:
            self._run()
        except Exception as e:
            self.log(f"[ERROR] {e}")
        finally:
            self.cleanup()

    def _get_device(self, index):
        device = self.p.get_device_info_by_index(index)
        device["index"] = index
        return device

    def _output_worker(self, output_name, output_stream, audio_queue):
        self.log(f"[OK] Output active: {output_name}")

        while not self.stop_event.is_set():
            try:
                data = audio_queue.get(timeout=0.2)
            except queue.Empty:
                continue

            try:
                output_stream.write(data, exception_on_underflow=False)
            except Exception as e:
                self.log(f"[ERROR] Output failed on {output_name}: {e}")
                self.stop_event.set()
                break

    def _run(self):
        self.p = pyaudio.PyAudio()

        source = self._get_device(self.source_index)
        outputs = [self._get_device(index) for index in self.output_indexes]

        source_name = source["name"]
        source_rate = int(float(source.get("defaultSampleRate", 48000)))
        source_channels = int(source.get("maxInputChannels", 0))

        if source_channels <= 0:
            raise RuntimeError("Selected capture source has no input channels.")

        channels = min(source_channels, 2)

        
        self.log("STARTING AUDIO MIRROR")
        self.log("MADARCHODMADARCHODMADARCHODMADARCHODMADARCHODMADARCHODMADARCHODMADARCHODMADARCHOD")
        self.log(f"Capture source: [{source['index']}] {source_name}")
        self.log(f"Sample rate:    {source_rate} Hz")
        self.log(f"Channels:       {channels}")
        self.log(f"Chunk size:     {self.chunk_size}")
        self.log("")

        if not source.get("isLoopbackDevice", False):
            self.log("[WARNING] Source is not marked as a loopback device.")
            self.log("Brother you should select a LOOPBACK ??.")

        if is_bad_mode(source_name):
            self.log("[BAD SOURCE WARNING] Bitch This looks like Hands-Free / Headset mode.")
            self.log("Audio quality will be bad. Pick Stereo / Headphones loopback instead. Bitch")

        for out in outputs:
            out_name = out["name"]
            out_channels = int(out.get("maxOutputChannels", 0))
            out_rate = int(float(out.get("defaultSampleRate", 48000)))

            if out_channels <= 0:
                raise RuntimeError(f"Selected output has no output channels: {out_name}")

            self.log(f"Mirror output:  [{out['index']}] {out_name}")
            self.log(f"Output rate:    {out_rate} Hz")

            if is_bad_mode(out_name):
                self.log("[BAD OUTPUT WARNING] This looks like Hands-Free / Headset mode. BItch")
                self.log("Avoid it if you want good quality.")

            if maybe_same_device(source_name, out_name):
                self.log("[WARNING] Output may be the same device as the capture source Stupid")
                self.log("This can cause echo/delay loop. Usually avoid this.")

        self.log("")
        self.log("[OPENING] Capture stream...")

        self.input_stream = self.p.open(
            format=self.audio_format,
            channels=channels,
            rate=source_rate,
            input=True,
            input_device_index=self.source_index,
            frames_per_buffer=self.chunk_size,
        )

        self.log("[OPENING] Output stream(s)...")

        for out in outputs:
            output_stream = self.p.open(
                format=self.audio_format,
                channels=channels,
                rate=source_rate,
                output=True,
                output_device_index=out["index"],
                frames_per_buffer=self.chunk_size,
            )

            audio_queue = queue.Queue(maxsize=self.queue_size)

            thread = threading.Thread(
                target=self._output_worker,
                args=(out["name"], output_stream, audio_queue),
                daemon=True,
            )

            self.output_streams.append(output_stream)
            self.output_queues.append(audio_queue)
            self.output_threads.append(thread)

        for thread in self.output_threads:
            thread.start()

        self.log("")
        self.log("[RUNNING] Play audio on the PC.")
        self.log("[TIP] For best quality, do not use Bluetooth microphone mode.")
        self.log("")

        dropped_chunks = 0
        last_report = time.time()

        while not self.stop_event.is_set():
            try:
                data = self.input_stream.read(
                    self.chunk_size,
                    exception_on_overflow=False,
                )
            except Exception as e:
                self.log(f"[ERROR] Capture failed: {e}")
                self.stop_event.set()
                break

            for audio_queue in self.output_queues:
                if audio_queue.full():
                    try:
                        audio_queue.get_nowait()
                        dropped_chunks += 1
                    except queue.Empty:
                        pass

                try:
                    audio_queue.put_nowait(data)
                except queue.Full:
                    dropped_chunks += 1

            now = time.time()

            if now - last_report >= 5:
                if dropped_chunks > 0:
                    self.log(f"[STABILITY] Dropped old chunks to avoid lag buildup: {dropped_chunks}")
                    dropped_chunks = 0

                last_report = now

    def cleanup(self):
        self.log("")
        self.log("[CLOSING] Cleaning up audio streams...")

        try:
            if self.input_stream is not None:
                self.input_stream.stop_stream()
                self.input_stream.close()
        except Exception:
            pass

        for stream in self.output_streams:
            try:
                stream.stop_stream()
                stream.close()
            except Exception:
                pass

        try:
            if self.p is not None:
                self.p.terminate()
        except Exception:
            pass

        self.log("[STOPPED]")


class DualAudioApp:
    def __init__(self, root):
        self.root = root
        self.root.title(APP_TITLE)
        self.root.geometry("950x720")

        self.devices = []
        self.loopback_sources = []
        self.outputs = []

        self.source_map = {}
        self.output_map = {}

        self.engine_thread = None
        self.stop_event = threading.Event()

        self._build_ui()
        self.refresh_devices()

    def _build_ui(self):
        main = ttk.Frame(self.root, padding=12)
        main.pack(fill=tk.BOTH, expand=True)

        title = ttk.Label(
            main,
            text="Dual Bluetooth / Multi-Device Audio Mirror",
            font=("Segoe UI", 16, "bold"),
        )
        title.pack(anchor="w")

        info = ttk.Label(
            main,
            text=(
                "Use Device 1 as your normal Windows output, then select its LOOPBACK source here. "
                "Select Device 2 as the mirror output. Avoid Hands-Free / Headset / AG Audio devices."
            ),
            wraplength=900,
        )
        info.pack(anchor="w", pady=(4, 12))

        controls = ttk.LabelFrame(main, text="Device Selection", padding=12)
        controls.pack(fill=tk.X)

        ttk.Label(controls, text="Device 1 capture source / loopback:").grid(
            row=0, column=0, sticky="w", pady=5
        )

        self.source_combo = ttk.Combobox(
            controls,
            state="readonly",
            width=95,
        )
        self.source_combo.grid(row=0, column=1, sticky="ew", pady=5, padx=8)

        ttk.Label(controls, text="Device 2 mirror output:").grid(
            row=1, column=0, sticky="w", pady=5
        )

        self.output1_combo = ttk.Combobox(
            controls,
            state="readonly",
            width=95,
        )
        self.output1_combo.grid(row=1, column=1, sticky="ew", pady=5, padx=8)

        ttk.Label(controls, text="Optional extra output:").grid(
            row=2, column=0, sticky="w", pady=5
        )

        self.output2_combo = ttk.Combobox(
            controls,
            state="readonly",
            width=95,
        )
        self.output2_combo.grid(row=2, column=1, sticky="ew", pady=5, padx=8)

        controls.columnconfigure(1, weight=1)

        settings = ttk.LabelFrame(main, text="Quality Settings", padding=12)
        settings.pack(fill=tk.X, pady=12)

        ttk.Label(settings, text="Quality profile:").grid(
            row=0, column=0, sticky="w", pady=5
        )

        self.profile_combo = ttk.Combobox(
            settings,
            state="readonly",
            values=list(PROFILE_OPTIONS.keys()),
            width=35,
        )
        self.profile_combo.set("High quality / stable Bluetooth")
        self.profile_combo.grid(row=0, column=1, sticky="w", padx=8, pady=5)

        ttk.Label(settings, text="Audio format:").grid(
            row=0, column=2, sticky="w", padx=(24, 0), pady=5
        )

        self.format_combo = ttk.Combobox(
            settings,
            state="readonly",
            values=list(FORMAT_OPTIONS.keys()),
            width=35,
        )
        self.format_combo.set("Float32 - best internal quality")
        self.format_combo.grid(row=0, column=3, sticky="w", padx=8, pady=5)

        self.hide_bad_var = tk.BooleanVar(value=True)
        self.hide_bad_check = ttk.Checkbutton(
            settings,
            text="Hide low-quality Hands-Free / Headset devices",
            variable=self.hide_bad_var,
            command=self.refresh_devices,
        )
        self.hide_bad_check.grid(row=1, column=0, columnspan=4, sticky="w", pady=5)

        buttons = ttk.Frame(main)
        buttons.pack(fill=tk.X, pady=(0, 12))

        self.refresh_button = ttk.Button(
            buttons,
            text="Refresh Devices",
            command=self.refresh_devices,
        )
        self.refresh_button.pack(side=tk.LEFT)

        self.start_button = ttk.Button(
            buttons,
            text="Start Mirror",
            command=self.start_mirror,
        )
        self.start_button.pack(side=tk.LEFT, padx=8)

        self.stop_button = ttk.Button(
            buttons,
            text="Stop",
            command=self.stop_mirror,
            state=tk.DISABLED,
        )
        self.stop_button.pack(side=tk.LEFT)

        self.open_sound_button = ttk.Button(
            buttons,
            text="Open Windows Sound Settings",
            command=self.open_sound_settings,
        )
        self.open_sound_button.pack(side=tk.LEFT, padx=8)

        log_frame = ttk.LabelFrame(main, text="Log", padding=8)
        log_frame.pack(fill=tk.BOTH, expand=True)

        self.log_text = tk.Text(log_frame, height=20, wrap=tk.WORD)
        self.log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        scrollbar = ttk.Scrollbar(log_frame, command=self.log_text.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.log_text.config(yscrollcommand=scrollbar.set)

    def log(self, text):
        def append():
            self.log_text.insert(tk.END, text + "\n")
            self.log_text.see(tk.END)

        self.root.after(0, append)

    def open_sound_settings(self):
        import subprocess

        try:
            subprocess.Popen(["start", "ms-settings:sound"], shell=True)
        except Exception as e:
            messagebox.showerror("Error", str(e))

    def format_device_label(self, device):
        index = device["index"]
        name = device["name"]
        rate = int(float(device.get("defaultSampleRate", 0)))
        max_in = int(device.get("maxInputChannels", 0))
        max_out = int(device.get("maxOutputChannels", 0))
        is_loopback = bool(device.get("isLoopbackDevice", False))

        tags = []

        if is_loopback:
            tags.append("LOOPBACK")

        if max_out > 0:
            tags.append("OUTPUT")

        if is_bad_mode(name):
            tags.append("AVOID: HANDS-FREE")

        tag_text = ", ".join(tags)

        return f"[{index}] {name} | {rate} Hz | In:{max_in} Out:{max_out} | {tag_text}"

    def refresh_devices(self):
        self.log("[REFRESH] Scanning Windows audio devices...")

        p = pyaudio.PyAudio()

        try:
            self.devices = []
            self.loopback_sources = []
            self.outputs = []

            for i in range(p.get_device_count()):
                device = p.get_device_info_by_index(i)
                device["index"] = i

                name = device["name"]
                max_input = int(device.get("maxInputChannels", 0))
                max_output = int(device.get("maxOutputChannels", 0))
                is_loopback = bool(device.get("isLoopbackDevice", False))

                if self.hide_bad_var.get() and is_bad_mode(name):
                    continue

                self.devices.append(device)

                if is_loopback and max_input > 0:
                    self.loopback_sources.append(device)

                if max_output > 0:
                    self.outputs.append(device)

            source_labels = [self.format_device_label(d) for d in self.loopback_sources]
            output_labels = [self.format_device_label(d) for d in self.outputs]

            self.source_map = {
                self.format_device_label(d): d["index"] for d in self.loopback_sources
            }

            self.output_map = {
                self.format_device_label(d): d["index"] for d in self.outputs
            }

            self.source_combo["values"] = source_labels
            self.output1_combo["values"] = output_labels
            self.output2_combo["values"] = ["None"] + output_labels

            if source_labels:
                self.source_combo.set(source_labels[0])
            else:
                self.source_combo.set("")

            if output_labels:
                self.output1_combo.set(output_labels[0])
            else:
                self.output1_combo.set("")

            self.output2_combo.set("None")

            self.log(f"[OK] Found {len(self.loopback_sources)} loopback sources.")
            self.log(f"[OK] Found {len(self.outputs)} output devices.")
            self.log("")

        finally:
            p.terminate()

    def start_mirror(self):
        if self.engine_thread and self.engine_thread.is_alive():
            messagebox.showwarning("Already running", "Audio mirror is already running.")
            return

        source_label = self.source_combo.get()
        output1_label = self.output1_combo.get()
        output2_label = self.output2_combo.get()

        if not source_label or source_label not in self.source_map:
            messagebox.showerror("Missing source", "Select a loopback capture source.")
            return

        if not output1_label or output1_label not in self.output_map:
            messagebox.showerror("Missing output", "Select at least one mirror output.")
            return

        source_index = self.source_map[source_label]
        output_indexes = [self.output_map[output1_label]]

        if output2_label and output2_label != "None":
            if output2_label in self.output_map:
                extra_index = self.output_map[output2_label]
                if extra_index not in output_indexes:
                    output_indexes.append(extra_index)

        if source_index in output_indexes:
            messagebox.showwarning(
                "Possible wrong selection",
                "Your source and output indexes look the same. This may cause echo or feedback.",
            )

        profile_name = self.profile_combo.get()
        profile = PROFILE_OPTIONS[profile_name]

        format_name = self.format_combo.get()
        audio_format = FORMAT_OPTIONS[format_name]

        self.stop_event.clear()

        engine = AudioMirrorEngine(
            source_index=source_index,
            output_indexes=output_indexes,
            audio_format=audio_format,
            chunk_size=profile["chunk"],
            queue_size=profile["queue"],
            log_callback=self.log,
            stop_event=self.stop_event,
        )

        self.engine_thread = threading.Thread(
            target=engine.start,
            daemon=True,
        )

        self.engine_thread.start()

        self.start_button.config(state=tk.DISABLED)
        self.stop_button.config(state=tk.NORMAL)
        self.refresh_button.config(state=tk.DISABLED)

        self.root.after(500, self._watch_engine)

    def _watch_engine(self):
        if self.engine_thread and self.engine_thread.is_alive():
            self.root.after(500, self._watch_engine)
        else:
            self.start_button.config(state=tk.NORMAL)
            self.stop_button.config(state=tk.DISABLED)
            self.refresh_button.config(state=tk.NORMAL)

    def stop_mirror(self):
        self.stop_event.set()
        self.log("[STOP REQUESTED]")


def main():
    root = tk.Tk()
    app = DualAudioApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()