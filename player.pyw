"""Banjo Sound Lab - browse, play and export the sounds from Banjo-Kazooie."""
import array
import json
import os
import shutil
import subprocess
import sys
import threading
import tkinter as tk
import wave as wavemod
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from banjolib.paths import app_dir, data_dir, resource_dir  # noqa: E402

BG = '#12161e'
PANEL = '#12161e'
INK = '#f2f4f8'
DIM = '#96a0b4'
GOLD = '#ffc63c'
BLUE = '#57b6ff'
SEL = '#1f2a3d'

FFMPEG_CANDIDATES = [Path(r'C:\ffmpeg\ffmpeg.exe'), Path(r'C:\ffmpeg\bin\ffmpeg.exe')]


def find_ffmpeg():
    for c in FFMPEG_CANDIDATES:
        if c.exists():
            return str(c)
    return shutil.which('ffmpeg')


class Audio:
    """Thin wrapper so a missing mixer never takes the window down."""

    def __init__(self):
        self.ok = False
        self.error = ''
        self.sound = None
        self.channel = None
        try:
            import pygame
            pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=512)
            self.pygame = pygame
            self.ok = True
        except Exception as exc:
            self.error = str(exc)

    def play(self, path, volume, loop):
        if not self.ok:
            return
        self.stop()
        self.sound = self.pygame.mixer.Sound(str(path))
        self.sound.set_volume(volume)
        self.channel = self.sound.play(loops=-1 if loop else 0)

    def stop(self):
        if self.ok and self.channel is not None:
            self.channel.stop()
            self.channel = None

    def set_volume(self, v):
        if self.sound is not None:
            self.sound.set_volume(v)


class Renderer:
    """Turns a music sequence into a WAV on demand, then keeps it cached."""

    def __init__(self, library: Path, rom_path):
        self.cache = library / 'music'
        self.cache.mkdir(parents=True, exist_ok=True)
        self.rom_path = rom_path
        self.rom = None
        self.voicer = None
        self.lock = threading.Lock()

    @property
    def available(self):
        return bool(self.rom_path) and Path(self.rom_path).exists()

    def path_for(self, row):
        safe = ''.join(ch if ch.isalnum() or ch in ' -_' else '_' for ch in row['name'])
        return self.cache / ('%03d %s.wav' % (row['id'], safe.strip()))

    def cached(self, row):
        p = self.path_for(row)
        return p if p.exists() else None

    def render(self, row):
        import wave as wv

        import numpy as np

        from banjolib import n64seq, synth
        from banjolib.bkrom import BanjoKazooieRom

        dest = self.path_for(row)
        if dest.exists():
            return dest
        with self.lock:
            if self.rom is None:
                self.rom = BanjoKazooieRom(self.rom_path)
                bank = self.rom.music_bank
                self.voicer = synth.Voicer(bank.file, bank.file.banks[0])
            seq = n64seq.parse(self.rom.asset_data(row['asset']))
            audio = synth.render(seq, self.voicer)
        pcm = (np.clip(audio, -1.0, 1.0) * 32767).astype('<i2')
        tmp = dest.with_suffix('.part')
        with wv.open(str(tmp), 'wb') as w:
            w.setnchannels(2)
            w.setsampwidth(2)
            w.setframerate(synth.OUT_RATE)
            w.writeframes(pcm.tobytes())
        tmp.replace(dest)
        return dest


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title('Banjo Sound Lab')
        self.geometry('1000x680')
        self.resizable(False, False)
        self.configure(bg=BG)

        self.audio = Audio()
        self.library = data_dir() / 'library'
        self.index = None
        self.rows = []
        self.shown = []
        self.progress = None
        self.renderer = None
        self.pending = None

        self._bg_image = None
        canvas = tk.Canvas(self, width=1000, height=680, highlightthickness=0, bd=0, bg=BG)
        canvas.place(x=0, y=0)
        bg_path = resource_dir() / 'assets' / 'bg.png'
        if bg_path.exists():
            self._bg_image = tk.PhotoImage(file=str(bg_path))
            canvas.create_image(0, 0, anchor='nw', image=self._bg_image)
        self.canvas = canvas

        self._style()
        self._header()
        self._panels()
        self._bind_keys()

        if (self.library / 'index.json').exists():
            self.load_library()
        else:
            self.after(250, self.first_run)

    # ------------------------------------------------------------ styling
    def _style(self):
        s = ttk.Style(self)
        try:
            s.theme_use('clam')
        except tk.TclError:
            pass
        s.configure('TCombobox', fieldbackground=SEL, background=SEL, foreground=INK,
                    arrowcolor=GOLD, bordercolor=SEL, lightcolor=SEL, darkcolor=SEL,
                    selectbackground=SEL, selectforeground=INK)
        self.option_add('*TCombobox*Listbox.background', SEL)
        self.option_add('*TCombobox*Listbox.foreground', INK)
        self.option_add('*TCombobox*Listbox.selectBackground', GOLD)
        self.option_add('*TCombobox*Listbox.selectForeground', '#20160a')
        s.configure('Vertical.TScrollbar', background='#2a3548', troughcolor=PANEL,
                    bordercolor=PANEL, arrowcolor=DIM)
        s.configure('Gold.Horizontal.TScale', background=GOLD, troughcolor=SEL,
                    bordercolor=SEL, lightcolor=GOLD, darkcolor=GOLD)
        s.configure('Gold.Horizontal.TProgressbar', background=GOLD, troughcolor=SEL,
                    bordercolor=PANEL, lightcolor=GOLD, darkcolor=GOLD)

    def _header(self):
        self.canvas.create_text(26, 32, anchor='w', text='BANJO SOUND LAB',
                                fill=GOLD, font=('Segoe UI Black', 24))
        self.canvas.create_text(28, 66, anchor='w',
                                text='effects, voices and music straight from the cartridge',
                                fill=DIM, font=('Segoe UI', 10))
        self.status = tk.Label(self, text='', bg=BG, fg=DIM, font=('Segoe UI', 9))
        self.canvas.create_window(984, 36, anchor='e', window=self.status)

    def _panels(self):
        self.search_var = tk.StringVar()
        self.search_var.trace_add('write', lambda *_: self.refilter())
        box = tk.Frame(self, bg=SEL, highlightthickness=0)
        self.entry = tk.Entry(box, textvariable=self.search_var, bg=SEL, fg=INK,
                              insertbackground=GOLD, relief='flat',
                              font=('Segoe UI', 11), width=30)
        self.entry.pack(padx=8, pady=6)
        self.placeholder = 'search…'
        self.entry.insert(0, self.placeholder)
        self.entry.configure(fg=DIM)
        self.entry.bind('<FocusIn>', self.clear_placeholder)
        self.entry.bind('<FocusOut>', self.restore_placeholder)
        self.canvas.create_window(32, 114, anchor='nw', window=box)

        self.cat_var = tk.StringVar()
        self.cat = ttk.Combobox(self, textvariable=self.cat_var, state='readonly',
                                width=31, font=('Segoe UI', 10))
        self.cat.bind('<<ComboboxSelected>>', lambda e: self.refilter())
        self.canvas.create_window(32, 156, anchor='nw', window=self.cat)

        holder = tk.Frame(self, bg=PANEL)
        self.listbox = tk.Listbox(holder, bg=PANEL, fg=INK, selectbackground=SEL,
                                  selectforeground=GOLD, relief='flat',
                                  font=('Consolas', 10), activestyle='none',
                                  highlightthickness=0, width=40, height=26)
        sb = ttk.Scrollbar(holder, orient='vertical', command=self.listbox.yview,
                           style='Vertical.TScrollbar')
        self.listbox.configure(yscrollcommand=sb.set)
        self.listbox.pack(side='left', fill='both', expand=True)
        sb.pack(side='right', fill='y')
        self.listbox.bind('<<ListboxSelect>>', lambda e: self.on_select())
        self.listbox.bind('<Double-Button-1>', lambda e: self.play())
        self.canvas.create_window(32, 194, anchor='nw', window=holder)

        self.count_lbl = tk.Label(self, text='', bg=PANEL, fg=DIM, font=('Segoe UI', 9))
        self.canvas.create_window(32, 634, anchor='nw', window=self.count_lbl)

        self.title_lbl = tk.Label(self, text='', bg=PANEL, fg=INK,
                                  font=('Segoe UI Semibold', 20), anchor='w',
                                  justify='left', wraplength=540)
        self.canvas.create_window(412, 122, anchor='nw', window=self.title_lbl)

        self.sym_lbl = tk.Label(self, text='', bg=PANEL, fg=BLUE, font=('Consolas', 10),
                                anchor='w')
        self.canvas.create_window(412, 168, anchor='nw', window=self.sym_lbl)

        self.meta_lbl = tk.Label(self, text='', bg=PANEL, fg=DIM, font=('Segoe UI', 10),
                                 anchor='w', justify='left')
        self.canvas.create_window(412, 196, anchor='nw', window=self.meta_lbl)

        self.wave = tk.Canvas(self, width=556, height=150, bg=PANEL,
                              highlightthickness=1, highlightbackground='#243049')
        self.canvas.create_window(412, 238, anchor='nw', window=self.wave)

        bar = tk.Frame(self, bg=PANEL)
        self._button(bar, '\u25b6  Play', self.play, GOLD, '#20160a').pack(side='left')
        self._button(bar, '\u25a0  Stop', self.stop, '#2a3548', INK).pack(side='left', padx=8)
        self.loop_var = tk.BooleanVar(value=False)
        tk.Checkbutton(bar, text='Loop', variable=self.loop_var, bg=PANEL, fg=DIM,
                       selectcolor=SEL, activebackground=PANEL, activeforeground=GOLD,
                       font=('Segoe UI', 10), relief='flat', bd=0,
                       highlightthickness=0).pack(side='left', padx=(6, 0))
        self.canvas.create_window(412, 410, anchor='nw', window=bar)

        vol = tk.Frame(self, bg=PANEL)
        tk.Label(vol, text='Volume', bg=PANEL, fg=DIM, font=('Segoe UI', 10)).pack(side='left')
        self.vol_var = tk.DoubleVar(value=0.85)
        ttk.Scale(vol, from_=0, to=1, orient='horizontal', variable=self.vol_var,
                  length=210, style='Gold.Horizontal.TScale',
                  command=self.on_volume).pack(side='left', padx=12)
        self.vol_lbl = tk.Label(vol, text='85%', bg=PANEL, fg=GOLD,
                                font=('Consolas', 10), width=4)
        self.vol_lbl.pack(side='left')
        self.canvas.create_window(412, 458, anchor='nw', window=vol)

        save = tk.Frame(self, bg=PANEL)
        self._button(save, 'Save this sound\u2026', self.save_one,
                     '#2a3548', INK).pack(side='left')
        self._button(save, 'Export everything listed\u2026', self.save_many,
                     '#2a3548', INK).pack(side='left', padx=8)
        self.canvas.create_window(412, 512, anchor='nw', window=save)

        self.hint = tk.Label(self, text='', bg=PANEL, fg=DIM, font=('Segoe UI', 9),
                             anchor='w', justify='left', wraplength=548)
        self.canvas.create_window(412, 562, anchor='nw', window=self.hint)

    def clear_placeholder(self, _event=None):
        if self.search_var.get() == self.placeholder:
            self.entry.delete(0, tk.END)
        self.entry.configure(fg=INK)

    def restore_placeholder(self, _event=None):
        if not self.search_var.get().strip():
            self.entry.delete(0, tk.END)
            self.entry.insert(0, self.placeholder)
            self.entry.configure(fg=DIM)

    def _button(self, parent, text, cmd, bg, fg):
        return tk.Button(parent, text=text, command=cmd, bg=bg, fg=fg,
                         activebackground=bg, activeforeground=fg, relief='flat',
                         font=('Segoe UI Semibold', 11), bd=0, padx=16, pady=7,
                         cursor='hand2')

    def _bind_keys(self):
        self.bind('<Return>', lambda e: self.play())
        self.bind('<Escape>', lambda e: self.stop())
        self.bind('<Control-f>', lambda e: self.entry.focus_set())
        self.listbox.bind('<Down>', lambda e: self.step(1) or 'break')
        self.listbox.bind('<Up>', lambda e: self.step(-1) or 'break')

    def show_progress(self, maximum):
        if self.progress is None:
            self.progress = ttk.Progressbar(self, length=556, mode='determinate',
                                            style='Gold.Horizontal.TProgressbar')
            self.progress_win = self.canvas.create_window(412, 600, anchor='nw',
                                                          window=self.progress)
        self.progress['maximum'] = max(maximum, 1)
        self.progress['value'] = 0

    def hide_progress(self):
        if self.progress is not None:
            self.canvas.delete(self.progress_win)
            self.progress.destroy()
            self.progress = None

    # ------------------------------------------------------------ library
    def first_run(self):
        if not messagebox.askyesno(
                'Banjo Sound Lab',
                'No sound library yet.\n\n'
                'Choose your Banjo-Kazooie ROM and every sound will be decoded '
                'out of it. This takes under a minute and only happens once.'):
            return
        rom = filedialog.askopenfilename(
            title='Select a Banjo-Kazooie ROM',
            filetypes=[('Nintendo 64 ROM', '*.z64 *.n64 *.v64'), ('All files', '*.*')])
        if rom:
            self.extract(rom)

    def extract(self, rom):
        self.show_progress(100)
        self.status.configure(text='decoding the ROM\u2026')

        def work():
            try:
                from banjolib.library import build

                def report(done, total):
                    self.progress['maximum'] = total
                    self.progress['value'] = done
                build(rom, self.library, report)
                self.after(0, self.done_extract, None)
            except Exception as exc:
                self.after(0, self.done_extract, exc)

        threading.Thread(target=work, daemon=True).start()

    def done_extract(self, exc):
        self.hide_progress()
        if exc:
            self.status.configure(text='extraction failed')
            messagebox.showerror('Extraction failed', str(exc))
            return
        self.load_library()

    def load_library(self):
        self.index = json.loads((self.library / 'index.json').read_text())
        cats = list(self.index['categories'])
        self.cat['values'] = ['All sounds'] + cats
        self.cat_var.set('All sounds')
        self.rows = []
        for cat, entries in self.index['categories'].items():
            for e in entries:
                row = dict(e)
                row['category'] = cat
                self.rows.append(row)
        self.renderer = Renderer(self.library, self.index.get('rom'))
        self.status.configure(text='%s \u2014 %d sounds' %
                                   (self.index.get('game', 'library'), len(self.rows)))
        self.refilter()
        if not self.audio.ok:
            self.hint.configure(text='Audio output unavailable (%s). '
                                     'Browsing and exporting still work.' % self.audio.error)

    # ------------------------------------------------------------ list
    def refilter(self):
        if not self.rows:
            return
        q = self.search_var.get().strip().lower()
        if q == self.placeholder:
            q = ''
        cat = self.cat_var.get()
        self.shown = [r for r in self.rows
                      if (cat in ('All sounds', '') or r['category'] == cat)
                      and (not q or q in r['name'].lower()
                           or q in r.get('symbol', '').lower())]
        self.listbox.delete(0, tk.END)
        for r in self.shown:
            self.listbox.insert(tk.END, '%3d  %s' % (r['id'], r['name']))
        self.count_lbl.configure(text='%d of %d sounds' % (len(self.shown), len(self.rows)))
        if self.shown:
            self.listbox.selection_set(0)
            self.listbox.see(0)
            self.on_select()
        else:
            self.title_lbl.configure(text='nothing matches')
            self.sym_lbl.configure(text='')
            self.meta_lbl.configure(text='')
            self.wave.delete('all')

    def step(self, delta):
        if not self.shown:
            return
        cur = self.listbox.curselection()
        i = max(0, min(len(self.shown) - 1, (cur[0] if cur else 0) + delta))
        self.listbox.selection_clear(0, tk.END)
        self.listbox.selection_set(i)
        self.listbox.see(i)
        self.on_select()

    @property
    def current(self):
        cur = self.listbox.curselection()
        if not cur or cur[0] >= len(self.shown):
            return None
        return self.shown[cur[0]]

    def on_select(self):
        r = self.current
        if not r:
            return
        self.title_lbl.configure(text=r['name'])
        self.sym_lbl.configure(text=r.get('symbol') or '')
        bits = [r['category']]
        if r.get('render'):
            mins, secs = divmod(int(r['seconds']), 60)
            bits += ['%d:%02d' % (mins, secs), '%d notes' % r.get('notes', 0)]
        else:
            bits += ['%.2f s' % r['seconds'], '%d Hz' % r['rate']]
        if r.get('looped'):
            bits.append('loops in game')
        self.meta_lbl.configure(text='   \u2022   '.join(bits))
        path = self.audio_path(r)
        if path:
            self.draw_wave(path)
            self.hint.configure(text='Enter or double-click plays    \u00b7    Esc stops'
                                     '    \u00b7    Ctrl+F jumps to the search box')
        else:
            self.wave.delete('all')
            self.wave.create_text(278, 75, text='press Play to render this track',
                                  fill=DIM, font=('Segoe UI', 11))
            self.hint.configure(text='Music is stored as sequence data rather than audio, so '
                                     'the first play renders it through the instrument bank. '
                                     'It is cached after that.')

    def draw_wave(self, path):
        c = self.wave
        c.delete('all')
        w, h = 556, 150
        try:
            with wavemod.open(str(path)) as f:
                data = array.array('h')
                data.frombytes(f.readframes(f.getnframes()))
        except Exception:
            return
        n = len(data)
        if not n:
            return
        mid = h / 2
        c.create_line(0, mid, w, mid, fill='#243049')
        peak = max(1, max(abs(v) for v in data[::max(1, n // 4000)]))
        for x in range(w):
            a = x * n // w
            b = max(a + 1, (x + 1) * n // w)
            stride = max(1, (b - a) // 24)
            chunk = data[a:b:stride]
            if not chunk:
                continue
            y0 = mid - max(chunk) / peak * (mid - 8)
            y1 = mid - min(chunk) / peak * (mid - 8)
            c.create_line(x, y0, x, y1, fill=GOLD if x % 2 == 0 else '#c9962c')

    # ------------------------------------------------------------ playback
    def audio_path(self, row):
        """Existing audio for a row, or None when music still needs rendering."""
        if not row.get('render'):
            return self.library / row['file']
        if self.renderer is None:
            return None
        return self.renderer.cached(row)

    def play(self):
        r = self.current
        if not r or not self.audio.ok:
            return
        path = self.audio_path(r)
        if path is None:
            self.render_then_play(r)
            return
        try:
            self.audio.play(path, self.vol_var.get(), self.loop_var.get())
        except Exception as exc:
            messagebox.showerror('Playback failed', str(exc))

    def render_then_play(self, row):
        if self.renderer is None or not self.renderer.available:
            messagebox.showwarning(
                'ROM needed',
                'Music is rendered from the sequence data in the ROM, and the ROM '
                'this library was built from can no longer be found.\n\n'
                'Delete the library folder next to the program and start it again '
                'to point it at the right file.')
            return
        if self.pending == row['id']:
            return
        self.pending = row['id']
        self.status.configure(text='rendering %s...' % row['name'])
        self.wave.delete('all')
        self.wave.create_text(278, 75, text='rendering...', fill=GOLD,
                              font=('Segoe UI Semibold', 13))

        def work():
            try:
                path = self.renderer.render(row)
                self.after(0, self.render_done, row, path, None)
            except Exception as exc:
                self.after(0, self.render_done, row, None, exc)

        threading.Thread(target=work, daemon=True).start()

    def render_done(self, row, path, exc):
        self.pending = None
        if exc:
            self.status.configure(text='render failed')
            messagebox.showerror('Could not render that track', str(exc))
            return
        self.status.configure(text='rendered %s' % row['name'])
        cur = self.current
        if cur and cur['id'] == row['id'] and cur['category'] == row['category']:
            self.draw_wave(path)
            try:
                self.audio.play(path, self.vol_var.get(), self.loop_var.get())
            except Exception as err:
                messagebox.showerror('Playback failed', str(err))

    def stop(self):
        self.audio.stop()

    def on_volume(self, value):
        v = float(value)
        self.audio.set_volume(v)
        self.vol_lbl.configure(text='%d%%' % round(v * 100))

    # ------------------------------------------------------------ export
    @staticmethod
    def safe_name(name):
        return ''.join(ch if ch.isalnum() or ch in ' -_' else '_' for ch in name).strip()

    def save_one(self):
        r = self.current
        if not r:
            return
        types = [('WAV audio', '*.wav')]
        if find_ffmpeg():
            types += [('MP3 audio', '*.mp3'), ('OGG audio', '*.ogg'), ('FLAC audio', '*.flac')]
        dest = filedialog.asksaveasfilename(title='Save sound as',
                                            initialfile=self.safe_name(r['name']) + '.wav',
                                            defaultextension='.wav', filetypes=types)
        if not dest:
            return
        def work():
            try:
                src = self.audio_path(r) or self.renderer.render(r)
                self.convert(src, Path(dest))
                self.after(0, lambda: self.status.configure(
                    text='saved %s' % Path(dest).name))
            except Exception as exc:
                message = str(exc)
                self.after(0, lambda: messagebox.showerror('Save failed', message))

        self.status.configure(text='saving...')
        threading.Thread(target=work, daemon=True).start()

    def save_many(self):
        if not self.shown:
            return
        folder = filedialog.askdirectory(title='Export the listed sounds into\u2026')
        if not folder:
            return
        fmt = '.wav'
        if find_ffmpeg() and messagebox.askyesno('Export format',
                                                 'Export as MP3?\n\nYes = MP3,  No = WAV'):
            fmt = '.mp3'
        rows = list(self.shown)
        folder = Path(folder)
        self.show_progress(len(rows))

        def work():
            failed = 0
            for i, r in enumerate(rows):
                dest = folder / ('%03d %s%s' % (r['id'], self.safe_name(r['name']), fmt))
                try:
                    src = self.audio_path(r) or self.renderer.render(r)
                    self.convert(src, dest)
                except Exception:
                    failed += 1
                if self.progress is not None:
                    self.progress['value'] = i + 1
            self.after(0, self.done_export, len(rows), failed, folder)

        threading.Thread(target=work, daemon=True).start()

    def done_export(self, total, failed, folder):
        self.hide_progress()
        self.status.configure(text='exported %d files' % (total - failed))
        messagebox.showinfo('Export finished',
                            'Wrote %d of %d files to\n%s' % (total - failed, total, folder))

    @staticmethod
    def convert(src: Path, dest: Path):
        if dest.suffix.lower() == '.wav':
            shutil.copyfile(src, dest)
            return
        ff = find_ffmpeg()
        if not ff:
            raise RuntimeError('ffmpeg is needed for that format')
        flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0) if os.name == 'nt' else 0
        res = subprocess.run([ff, '-y', '-loglevel', 'error', '-i', str(src), str(dest)],
                             capture_output=True, creationflags=flags)
        if res.returncode != 0:
            raise RuntimeError(res.stderr.decode('utf-8', 'replace')[:300])


if __name__ == '__main__':
    App().mainloop()
