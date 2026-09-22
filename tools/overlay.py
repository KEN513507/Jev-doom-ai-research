"""Jev ステータスの半透明オーバーレイ（層別色分け）

train/jev_agent.py が書く /tmp/jev_status.txt（1行 = "TAG|本文"）を 200ms ごとに表示する。
使い方: python tools/overlay.py [--geometry 400x300+440+100]
"""
import argparse
import tkinter as tk

STATUS_FILE = "/tmp/jev_status.txt"
UPDATE_MS = 200

# 層ごとの色（SYS1 = 反射層: WallAvoider/ForwardBlockDetector/AreaStagnationDetector/should_force_attack）
COLORS = {
    "SYS1": "#aaaaaa",  # 薄いグレー（反射）
    "SYS2": "#ff88cc",  # ピンク（Jev）
    "SYS3": "#aaddff",  # 薄い水色（Gemini）
    "GAME": "#ff5555",  # 赤（視覚・ゲーム状態）
    "META": "#aaaaaa",  # 薄いグレー（その他）
}


def parse_line(line: str) -> tuple[str, str]:
    """'TAG|本文' を (tag, 本文) に分ける。未知のタグ・タグなしは META"""
    line = line.rstrip("\n")
    if "|" in line:
        src, msg = line.split("|", 1)
        if src in COLORS:
            return src, msg
    return "META", line


class Overlay:
    def __init__(self, geometry: str | None = None):
        self.root = tk.Tk()
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.attributes("-alpha", 0.75)
        if geometry is None:  # 既定: 画面右端
            self.root.update_idletasks()
            sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
            w = 380
            geometry = f"{w}x{sh - 100}+{sw - w - 10}+50"
        self.root.geometry(geometry)
        self.root.configure(bg="#000000")

        self.text = tk.Text(
            self.root,
            fg="#cccccc",
            bg="#000000",
            font=("monospace", 10),
            wrap="word",
            padx=10,
            pady=10,
            borderwidth=0,
            highlightthickness=0,
        )
        self.text.pack(fill="both", expand=True)
        for tag, color in COLORS.items():
            self.text.tag_configure(tag, foreground=color)
        self.text.tag_configure("HEADER", foreground="#ffffff", font=("monospace", 11, "bold"))

        self.root.bind("<Escape>", lambda e: self.root.destroy())
        self.root.focus_force()
        self.update()

    def update(self):
        self.text.config(state="normal")
        self.text.delete("1.0", "end")
        self.text.insert("end", "═══ QUAD SYSTEM ═══\n", "HEADER")
        try:
            with open(STATUS_FILE) as f:
                for line in f:
                    tag, msg = parse_line(line)
                    self.text.insert("end", f"{msg}\n", tag)
        except FileNotFoundError:
            self.text.insert("end", f"waiting for Jev...\n({STATUS_FILE})\n", "META")
        except OSError as e:
            self.text.insert("end", f"error: {e}\n", "META")
        self.text.config(state="disabled")
        self.root.after(UPDATE_MS, self.update)

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--geometry", default=None, help="WxH+X+Y（省略時は画面右端）")
    Overlay(parser.parse_args().geometry).run()
