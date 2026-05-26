from __future__ import annotations

from pathlib import Path
from queue import Empty, Queue
from threading import Event, Thread
import os
import traceback
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import webbrowser

import customtkinter as ctk

from scraper import DEFAULT_RESULT_COUNT, ScrapeConfig, run_scrape


ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")


class ThumbnailScraperApp(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()

        self.title("Thumbnail Scraper Studio")
        self.geometry("1360x860")
        self.minsize(1180, 780)

        self._events: Queue[dict[str, object]] = Queue()
        self._stop_event = Event()
        self._worker: Thread | None = None
        self._running = False
        self._progress_target = DEFAULT_RESULT_COUNT
        self._last_stage = "Idle"
        self.preview_photo: tk.PhotoImage | None = None

        self.query_var = tk.StringVar(value="best ai tools")
        self.results_var = tk.StringVar(value=str(DEFAULT_RESULT_COUNT))
        self.output_var = tk.StringVar(value=str((Path.cwd() / "data").resolve()))
        self.headless_var = tk.BooleanVar(value=True)

        self.stage_var = tk.StringVar(value="Ready")
        self.collection_var = tk.StringVar(value="0 / 0")
        self.download_var = tk.StringVar(value="0 / 0")
        self.failed_var = tk.StringVar(value="0")
        self.verification_var = tk.StringVar(value="Pending")
        self.preview_status_var = tk.StringVar(value="Awaiting browser preview")
        self.output_status_var = tk.StringVar(value="Select an output folder and start scraping.")
        self._results_columns = ("index", "title", "video_url", "thumbnail_url", "thumbnail_file")

        self._build_ui()
        self.after(100, self._poll_events)

    def _build_ui(self) -> None:
        self.configure(fg_color="#0B1020")
        self.grid_columnconfigure(0, weight=7)
        self.grid_columnconfigure(1, weight=5)
        self.grid_rowconfigure(1, weight=1)

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, columnspan=2, padx=28, pady=(24, 12), sticky="ew")
        header.grid_columnconfigure(0, weight=1)

        title = ctk.CTkLabel(
            header,
            text="Thumbnail Scraper Studio",
            font=("Segoe UI", 30, "bold"),
            text_color="#F8FAFC",
        )
        title.grid(row=0, column=0, sticky="w")

        subtitle = ctk.CTkLabel(
            header,
            text="Search YouTube, stream live progress, choose where results land, and stop without losing partial data.",
            font=("Segoe UI", 14),
            text_color="#94A3B8",
        )
        subtitle.grid(row=1, column=0, sticky="w", pady=(8, 0))

        self._build_settings_panel()
        self._build_progress_panel()

    def _card(self, parent: ctk.CTkBaseClass) -> ctk.CTkFrame:
        return ctk.CTkFrame(parent, corner_radius=20, fg_color="#111827", border_width=1, border_color="#243044")

    def _build_settings_panel(self) -> None:
        panel = ctk.CTkScrollableFrame(
            self,
            corner_radius=20,
            fg_color="#111827",
            border_width=1,
            border_color="#243044",
            scrollbar_button_color="#334155",
            scrollbar_button_hover_color="#475569",
        )
        panel.grid(row=1, column=0, padx=(28, 12), pady=(12, 24), sticky="nsew")
        panel.grid_columnconfigure(0, weight=1)
        panel.grid_rowconfigure(7, weight=1)

        heading = ctk.CTkLabel(panel, text="Scrape Settings", font=("Segoe UI", 22, "bold"), text_color="#E2E8F0")
        heading.grid(row=0, column=0, padx=24, pady=(22, 6), sticky="w")

        self._labeled_entry(panel, 1, "Search query", self.query_var, "Type the YouTube search phrase")
        self._labeled_entry(panel, 2, "Results to collect", self.results_var, "Example: 50")
        self._labeled_entry(panel, 3, "Output folder", self.output_var, "Choose where CSV and thumbnails are saved", browse=True)

        advanced = ctk.CTkFrame(panel, fg_color="#0F172A", corner_radius=16)
        advanced.grid(row=4, column=0, padx=20, pady=(8, 10), sticky="ew")
        advanced.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            advanced,
            text="Backend defaults are active. The scraper uses its built-in result target and verification pass automatically.",
            font=("Segoe UI", 13),
            text_color="#CBD5E1",
            wraplength=470,
            justify="left",
        ).grid(row=0, column=0, padx=16, pady=(16, 8), sticky="w")

        ctk.CTkLabel(
            advanced,
            text=f"Result target: {DEFAULT_RESULT_COUNT} | Browser preview and results table update live during the run.",
            font=("Segoe UI", 12, "bold"),
            text_color="#60A5FA",
            wraplength=470,
            justify="left",
        ).grid(row=1, column=0, padx=16, pady=(0, 16), sticky="w")

        headless = ctk.CTkCheckBox(
            panel,
            text="Run browser headless",
            variable=self.headless_var,
            font=("Segoe UI", 13),
            fg_color="#3B82F6",
            hover_color="#2563EB",
        )
        headless.grid(row=5, column=0, padx=24, pady=(2, 16), sticky="w")

        buttons = ctk.CTkFrame(panel, fg_color="transparent")
        buttons.grid(row=6, column=0, padx=20, pady=(0, 18), sticky="ew")
        buttons.grid_columnconfigure((0, 1, 2), weight=1)

        self.start_button = ctk.CTkButton(
            buttons,
            text="Start Scraping",
            height=44,
            corner_radius=14,
            fg_color="#2563EB",
            hover_color="#1D4ED8",
            command=self._start_scrape,
        )
        self.start_button.grid(row=0, column=0, padx=(0, 8), sticky="ew")

        self.stop_button = ctk.CTkButton(
            buttons,
            text="Stop",
            height=44,
            corner_radius=14,
            fg_color="#7C2D12",
            hover_color="#9A3412",
            command=self._request_stop,
            state="disabled",
        )
        self.stop_button.grid(row=0, column=1, padx=8, sticky="ew")

        open_button = ctk.CTkButton(
            buttons,
            text="Open Folder",
            height=44,
            corner_radius=14,
            fg_color="#334155",
            hover_color="#475569",
            command=self._open_output_folder,
        )
        open_button.grid(row=0, column=2, padx=(8, 0), sticky="ew")

        footer = ctk.CTkLabel(
            panel,
            textvariable=self.output_status_var,
            font=("Segoe UI", 12),
            text_color="#94A3B8",
            wraplength=500,
            justify="left",
        )
        footer.grid(row=7, column=0, padx=24, pady=(0, 22), sticky="w")

    def _labeled_entry(
        self,
        parent: ctk.CTkFrame,
        row: int,
        label: str,
        variable: tk.StringVar,
        hint: str,
        browse: bool = False,
    ) -> None:
        container = ctk.CTkFrame(parent, fg_color="#0F172A", corner_radius=16)
        container.grid(row=row, column=0, padx=20, pady=(8, 0), sticky="ew")
        container.grid_columnconfigure(0, weight=1)
        container.grid_columnconfigure(1, weight=0)

        label_widget = ctk.CTkLabel(container, text=label, font=("Segoe UI", 13, "bold"), text_color="#CBD5E1")
        label_widget.grid(row=0, column=0, padx=16, pady=(16, 4), sticky="w")

        entry_row = ctk.CTkFrame(container, fg_color="transparent")
        entry_row.grid(row=1, column=0, columnspan=2, padx=16, pady=(0, 14), sticky="ew")
        entry_row.grid_columnconfigure(0, weight=1)

        entry = ctk.CTkEntry(entry_row, textvariable=variable, height=40, corner_radius=12, placeholder_text=hint)
        entry.grid(row=0, column=0, sticky="ew")

        if browse:
            browse_button = ctk.CTkButton(
                entry_row,
                text="Browse",
                width=110,
                height=40,
                corner_radius=12,
                fg_color="#334155",
                hover_color="#475569",
                command=self._browse_folder,
            )
            browse_button.grid(row=0, column=1, padx=(12, 0), sticky="e")

    def _build_progress_panel(self) -> None:
        panel = self._card(self)
        panel.grid(row=1, column=1, padx=(12, 28), pady=(12, 24), sticky="nsew")
        panel.grid_columnconfigure(0, weight=1)
        panel.grid_rowconfigure(3, weight=1)

        heading = ctk.CTkLabel(panel, text="Live Progress", font=("Segoe UI", 22, "bold"), text_color="#E2E8F0")
        heading.grid(row=0, column=0, padx=24, pady=(22, 6), sticky="w")

        stage = ctk.CTkLabel(panel, textvariable=self.stage_var, font=("Segoe UI", 15, "bold"), text_color="#60A5FA")
        stage.grid(row=1, column=0, padx=24, pady=(0, 6), sticky="w")

        self.progress_bar = ctk.CTkProgressBar(panel, height=18, corner_radius=999)
        self.progress_bar.grid(row=2, column=0, padx=24, pady=(6, 10), sticky="ew")
        self.progress_bar.set(0)

        preview_card = ctk.CTkFrame(panel, fg_color="#0F172A", corner_radius=18)
        preview_card.grid(row=3, column=0, padx=20, pady=(8, 10), sticky="nsew")
        preview_card.grid_columnconfigure(0, weight=1)
        preview_card.grid_rowconfigure(1, weight=1)

        preview_header = ctk.CTkFrame(preview_card, fg_color="transparent")
        preview_header.grid(row=0, column=0, padx=18, pady=(16, 6), sticky="ew")
        preview_header.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(preview_header, text="Browser Preview", font=("Segoe UI", 15, "bold"), text_color="#E2E8F0").grid(
            row=0, column=0, sticky="w"
        )
        ctk.CTkLabel(
            preview_header,
            textvariable=self.preview_status_var,
            font=("Segoe UI", 12, "bold"),
            text_color="#34D399",
        ).grid(row=0, column=1, sticky="e")

        self.preview_label = ctk.CTkLabel(
            preview_card,
            text="The running browser will appear here.",
            fg_color="#111827",
            corner_radius=14,
            text_color="#94A3B8",
            width=560,
            height=260,
        )
        self.preview_label.grid(row=1, column=0, padx=18, pady=(0, 14), sticky="nsew")

        stats = ctk.CTkFrame(panel, fg_color="#0F172A", corner_radius=16)
        stats.grid(row=4, column=0, padx=20, pady=(0, 10), sticky="ew")
        stats.grid_columnconfigure((0, 1, 2, 3), weight=1)

        self._stat_tile(stats, 0, 0, "Collected", self.collection_var)
        self._stat_tile(stats, 0, 1, "Downloaded", self.download_var)
        self._stat_tile(stats, 0, 2, "Failed", self.failed_var)
        self._stat_tile(stats, 0, 3, "Verify", self.verification_var)

        results_frame = ctk.CTkFrame(panel, fg_color="#0F172A", corner_radius=16)
        results_frame.grid(row=5, column=0, padx=20, pady=(0, 10), sticky="nsew")
        results_frame.grid_columnconfigure(0, weight=1)
        results_frame.grid_rowconfigure(1, weight=1)

        results_header = ctk.CTkFrame(results_frame, fg_color="transparent")
        results_header.grid(row=0, column=0, padx=18, pady=(16, 6), sticky="ew")
        results_header.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(results_header, text="Scrape Results", font=("Segoe UI", 15, "bold"), text_color="#E2E8F0").grid(
            row=0, column=0, sticky="w"
        )

        self.results_table = ttk.Treeview(
            results_frame,
            columns=self._results_columns,
            show="headings",
            height=7,
            selectmode="browse",
        )
        self.results_table.grid(row=1, column=0, padx=(18, 0), pady=(0, 14), sticky="nsew")

        table_scroll = ttk.Scrollbar(results_frame, orient="vertical", command=self.results_table.yview)
        table_scroll.grid(row=1, column=1, padx=(0, 18), pady=(0, 14), sticky="ns")
        self.results_table.configure(yscrollcommand=table_scroll.set)

        self.results_table.heading("index", text="#")
        self.results_table.heading("title", text="Title")
        self.results_table.heading("video_url", text="Video URL")
        self.results_table.heading("thumbnail_url", text="Thumbnail URL")
        self.results_table.heading("thumbnail_file", text="File")

        self.results_table.column("index", width=56, anchor="center", stretch=False)
        self.results_table.column("title", width=260, anchor="w", stretch=True)
        self.results_table.column("video_url", width=210, anchor="w", stretch=True)
        self.results_table.column("thumbnail_url", width=210, anchor="w", stretch=True)
        self.results_table.column("thumbnail_file", width=210, anchor="w", stretch=True)
        self.results_table.bind("<Double-1>", self._open_selected_result)

        self._style_results_table()

        logs_label = ctk.CTkLabel(panel, text="Activity log", font=("Segoe UI", 14, "bold"), text_color="#CBD5E1")
        logs_label.grid(row=6, column=0, padx=24, pady=(8, 6), sticky="w")

        self.log_box = ctk.CTkTextbox(panel, height=120, corner_radius=16, fg_color="#0F172A", text_color="#E2E8F0")
        self.log_box.grid(row=7, column=0, padx=20, pady=(0, 20), sticky="nsew")
        self.log_box.configure(state="normal")
        self._append_log("Ready. Choose settings and press Start Scraping.")

    def _style_results_table(self) -> None:
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure(
            "Results.Treeview",
            background="#0F172A",
            fieldbackground="#0F172A",
            foreground="#E2E8F0",
            borderwidth=0,
            rowheight=26,
            font=("Segoe UI", 10),
        )
        style.configure(
            "Results.Treeview.Heading",
            background="#111827",
            foreground="#E2E8F0",
            font=("Segoe UI", 10, "bold"),
            relief="flat",
        )
        style.map("Results.Treeview", background=[("selected", "#1E3A8A")])
        self.results_table.configure(style="Results.Treeview")

    def _clear_results_table(self) -> None:
        if hasattr(self, "results_table"):
            for item in self.results_table.get_children():
                self.results_table.delete(item)

    def _populate_results_table(self, results: list[dict[str, str]]) -> None:
        self._clear_results_table()
        for index, result in enumerate(results, start=1):
            self.results_table.insert(
                "",
                "end",
                values=(
                    index,
                    result.get("title", ""),
                    result.get("video_url", ""),
                    result.get("thumbnail_url", ""),
                    result.get("thumbnail_file", ""),
                ),
            )

    def _open_selected_result(self, event: object | None = None) -> None:
        selection = self.results_table.selection()
        if not selection:
            return

        item = self.results_table.item(selection[0])
        values = item.get("values", [])
        if len(values) < 3:
            return

        video_url = str(values[2])
        if video_url:
            webbrowser.open_new_tab(video_url)

    def _set_preview_image(self, preview_path: str, label: str | None = None) -> None:
        path = Path(preview_path)
        if not path.exists():
            return

        try:
            image = tk.PhotoImage(file=str(path))
            factor = max(1, (image.width() + 539) // 540, (image.height() + 259) // 260)
            if factor > 1:
                image = image.subsample(factor, factor)
            self.preview_photo = image
            self.preview_label.configure(image=self.preview_photo, text="")
            if label:
                self.preview_status_var.set(label)
        except Exception:
            self.preview_label.configure(text="Preview unavailable.", image="")

    def _stat_tile(self, parent: ctk.CTkFrame, row: int, column: int, title: str, variable: tk.StringVar) -> None:
        tile = ctk.CTkFrame(parent, fg_color="#111827", corner_radius=16, border_width=1, border_color="#1F2937")
        tile.grid(row=row, column=column, padx=12, pady=12, sticky="nsew")
        tile.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(tile, text=title, font=("Segoe UI", 12), text_color="#94A3B8").grid(
            row=0, column=0, padx=16, pady=(16, 4), sticky="w"
        )
        ctk.CTkLabel(tile, textvariable=variable, font=("Segoe UI", 24, "bold"), text_color="#F8FAFC").grid(
            row=1, column=0, padx=16, pady=(0, 16), sticky="w"
        )

    def _browse_folder(self) -> None:
        chosen = filedialog.askdirectory(initialdir=self.output_var.get() or str(Path.cwd()))
        if chosen:
            self.output_var.set(chosen)

    def _open_output_folder(self) -> None:
        folder = Path(self.output_var.get()).expanduser()
        folder.mkdir(parents=True, exist_ok=True)
        try:
            os.startfile(folder)
        except Exception:
            messagebox.showinfo("Open Folder", f"Open this folder manually:\n{folder}")

    def _set_running(self, running: bool) -> None:
        self._running = running
        self.start_button.configure(state="disabled" if running else "normal")
        self.stop_button.configure(state="normal" if running else "disabled")

    def _append_log(self, message: str) -> None:
        self.log_box.configure(state="normal")
        self.log_box.insert("end", message + "\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def _reset_progress(self, target: int) -> None:
        self._progress_target = max(1, target)
        self.progress_bar.set(0)
        self.stage_var.set("Preparing...")
        self.collection_var.set(f"0 / {self._progress_target}")
        self.download_var.set("0 / 0")
        self.failed_var.set("0")
        self.verification_var.set("Pending")
        self.preview_status_var.set("Awaiting browser preview")
        self.output_status_var.set("Launching the browser and starting the scrape.")
        self.preview_label.configure(text="The running browser will appear here.", image="")
        self.preview_photo = None
        self._clear_results_table()
        self.log_box.configure(state="normal")
        self.log_box.delete("1.0", "end")
        self.log_box.configure(state="disabled")

    def _request_stop(self) -> None:
        if self._running:
            self._stop_event.set()
            self.output_status_var.set("Stop requested. The app will save whatever it already collected.")
            self._append_log("Stop requested by user.")

    def _start_scrape(self) -> None:
        if self._running:
            return

        try:
            query = self.query_var.get().strip()
            if not query:
                raise ValueError("Search query cannot be empty.")

            result_count = max(1, int(self.results_var.get().strip()))
            output_dir = Path(self.output_var.get()).expanduser()
        except Exception as exc:
            messagebox.showerror("Invalid settings", f"Please check the inputs:\n{exc}")
            return

        self._reset_progress(result_count)
        self._stop_event.clear()
        self._set_running(True)
        self._append_log(f"Search query: {query}")
        self._append_log(f"Requested results: {result_count}")
        self._append_log(f"Output folder: {output_dir}")
        self.output_status_var.set("Scraping in progress...")

        config = ScrapeConfig(
            query=query,
            output_dir=output_dir,
            result_count=result_count,
            headless=self.headless_var.get(),
        )

        self._worker = Thread(target=self._worker_main, args=(config,), daemon=True)
        self._worker.start()

    def _worker_main(self, config: ScrapeConfig) -> None:
        try:
            outcome = run_scrape(
                config,
                progress_cb=self._enqueue_progress,
                log_cb=self._enqueue_log,
                stop_event=self._stop_event,
            )
            self._events.put({"type": "done", "outcome": outcome})
        except Exception:
            self._events.put({"type": "error", "trace": traceback.format_exc()})

    def _enqueue_progress(self, stage: str, metrics: dict[str, object]) -> None:
        self._events.put({"type": "progress", "stage": stage, "metrics": metrics})

    def _enqueue_log(self, message: str) -> None:
        self._events.put({"type": "log", "message": message})

    def _poll_events(self) -> None:
        while True:
            try:
                item = self._events.get_nowait()
            except Empty:
                break

            event_type = item.get("type")
            if event_type == "progress":
                self._handle_progress(item["stage"], item["metrics"])
            elif event_type == "log":
                self._append_log(str(item["message"]))
            elif event_type == "done":
                self._handle_done(item["outcome"])
            elif event_type == "error":
                self._handle_error(str(item["trace"]))

        self.after(100, self._poll_events)

    def _handle_progress(self, stage: str, metrics: dict[str, object]) -> None:
        self._last_stage = stage
        self.stage_var.set(stage)

        if stage == "Preview":
            preview_path = str(metrics.get("preview_path", ""))
            preview_label = str(metrics.get("preview_label", "Browser preview"))
            self._set_preview_image(preview_path, preview_label)
            return

        if stage in {"Starting", "Scraping", "Scrolling", "Progress", "Verifying"}:
            unique = int(metrics.get("unique", metrics.get("collected", 0)) or 0)
            target = max(1, self._progress_target)
            self.collection_var.set(f"{unique} / {target}")
            self.progress_bar.set(min(1.0, unique / target))
            self.output_status_var.set("Verifying the collected result count..." if stage == "Verifying" else "Collecting results from YouTube...")
            return

        if stage == "Downloading":
            downloaded = int(metrics.get("downloaded", 0) or 0)
            failed = int(metrics.get("failed", 0) or 0)
            total = int(metrics.get("total", 1) or 1)
            self.download_var.set(f"{downloaded} / {total}")
            self.failed_var.set(str(failed))
            if total > 0:
                self.progress_bar.set(min(1.0, downloaded / total))
            self.output_status_var.set("Downloading thumbnails...")
            return

        if stage == "Saving":
            self.progress_bar.set(1.0)
            self.output_status_var.set(f"Saving finished: {metrics.get('csv_path', '')}")

        if stage == "Verified":
            verified = bool(metrics.get("verified", False))
            collected = int(metrics.get("collected", 0) or 0)
            target = int(metrics.get("target", self._progress_target) or self._progress_target)
            self.verification_var.set("Passed" if verified and collected >= target else "Failed")
            return

    def _handle_done(self, outcome: object) -> None:
        self._set_running(False)
        self.progress_bar.set(1.0)

        if hasattr(outcome, "collected"):
            collected = getattr(outcome, "collected")
            downloaded = getattr(outcome, "downloaded")
            failed = getattr(outcome, "failed")
            stopped_early = getattr(outcome, "stopped_early")
            verified = getattr(outcome, "verified", False)
            csv_path = getattr(outcome, "csv_path")
            thumbnail_dir = getattr(outcome, "thumbnail_dir")
            results = getattr(outcome, "results", [])

            self.collection_var.set(f"{collected} / {self._progress_target}")
            self.download_var.set(f"{downloaded} / {collected}")
            self.failed_var.set(str(failed))
            self.verification_var.set("Passed" if verified and collected >= self._progress_target else "Failed")
            self.stage_var.set("Done" if verified and not stopped_early else "Verified partial" if not verified else "Stopped and saved")
            self.output_status_var.set(f"Saved CSV to {csv_path}")
            self._append_log(f"Thumbnails saved in: {thumbnail_dir}")
            self._append_log(f"CSV saved in: {csv_path}")
            self._append_log(
                f"Verifier result: {'passed' if verified and collected >= self._progress_target else 'failed'} ({collected}/{self._progress_target})"
            )
            self._populate_results_table(results)
            if stopped_early:
                self._append_log("Scrape stopped early, but the partial data was saved.")
        else:
            self._append_log("Scrape finished.")

    def _handle_error(self, trace: str) -> None:
        self._set_running(False)
        self.stage_var.set("Error")
        self.output_status_var.set("The scrape failed. See the log for details.")
        self._append_log(trace)
        messagebox.showerror("Scrape failed", "The scraper hit an unexpected error. Check the log panel for details.")


def main() -> None:
    app = ThumbnailScraperApp()
    app.mainloop()


if __name__ == "__main__":
    main()
