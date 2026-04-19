"""
YouTube Premium 결제 관리 프로그램 (tkinter)
-------------------------------------------
친구들과 공유하는 YouTube Premium의 결제일과 커버 기간을 관리합니다.
데이터는 같은 폴더의 yt_premium_data.json 파일에 자동 저장됩니다.

실행: python youtube_premium_tracker.py
"""

import json
import os
import sys
from datetime import date, datetime
from dataclasses import dataclass, asdict
from typing import List, Dict
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import uuid

# -------------------- 경로 & 데이터 --------------------

def data_path() -> str:
    """실행 파일 기준 같은 폴더에 JSON 저장"""
    if getattr(sys, 'frozen', False):
        base = os.path.dirname(sys.executable)
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, 'yt_premium_data.json')


# 스크린샷에서 읽은 초기 데이터
SEED = [
    {"id": "i1", "name": "구구",   "date": "2025-04-01", "months": 12},
    {"id": "i2", "name": "승준",   "date": "2025-11-03", "months": 12},
    {"id": "i3", "name": "준희",   "date": "2025-11-03", "months": 12},
    {"id": "i4", "name": "주용",   "date": "2026-02-01", "months": 12},
    {"id": "i5", "name": "류동헌", "date": "2026-03-01", "months": 5},
    {"id": "i6", "name": "구구",   "date": "2026-04-01", "months": 15},
]


def load_data() -> List[Dict]:
    path = data_path()
    if not os.path.exists(path):
        save_data(SEED)
        return list(SEED)
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return list(SEED)


def save_data(payments: List[Dict]) -> None:
    with open(data_path(), 'w', encoding='utf-8') as f:
        json.dump(payments, f, ensure_ascii=False, indent=2)


# -------------------- 계산 로직 --------------------

def add_months(d: date, months: int) -> date:
    """date에 months를 더해서 새 date 리턴 (월 단위)"""
    total = d.month - 1 + months
    year = d.year + total // 12
    month = total % 12 + 1
    # 일 단위는 그대로 유지, 월말 보정
    day = min(d.day, [31, 29 if year % 4 == 0 and (year % 100 != 0 or year % 400 == 0) else 28,
                      31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1])
    return date(year, month, day)


def parse_date(s: str) -> date:
    return datetime.strptime(s, '%Y-%m-%d').date()


@dataclass
class MemberStatus:
    name: str
    last_pay_date: str
    last_pay_months: int
    total_months: int
    cover_end: str
    days_left: int
    state: str   # 'safe' | 'soon' | 'expired'
    count: int


def compute_status(payments: List[Dict]) -> List[MemberStatus]:
    """멤버별로 결제 기록을 체인하여 커버 만료일 계산"""
    groups: Dict[str, List[Dict]] = {}
    for p in payments:
        groups.setdefault(p['name'], []).append(p)

    today = date.today()
    out: List[MemberStatus] = []
    for name, lst in groups.items():
        lst = sorted(lst, key=lambda x: x['date'])
        cover_end = None
        total_months = 0
        for p in lst:
            pay_d = parse_date(p['date'])
            start = pay_d if (cover_end is None or pay_d > cover_end) else cover_end
            cover_end = add_months(start, int(p['months']))
            total_months += int(p['months'])
        last = lst[-1]
        days_left = (cover_end - today).days
        if days_left < 0:
            state = 'expired'
        elif days_left <= 30:
            state = 'soon'
        else:
            state = 'safe'
        out.append(MemberStatus(
            name=name,
            last_pay_date=last['date'],
            last_pay_months=int(last['months']),
            total_months=total_months,
            cover_end=cover_end.strftime('%Y-%m-%d'),
            days_left=days_left,
            state=state,
            count=len(lst),
        ))
    out.sort(key=lambda x: x.days_left)
    return out


# -------------------- GUI --------------------

COLORS = {
    'bg':      '#fafaf7',
    'card':    '#ffffff',
    'ink':     '#1a1a1a',
    'muted':   '#6b6b6b',
    'line':    '#e5e3dc',
    'accent':  '#ff0033',
    'safe':    '#2d7a3e',
    'warn':    '#c97a00',
    'danger':  '#cc1f1f',
    'safe_bg': '#e8f5eb',
    'warn_bg': '#fdf3e0',
    'dang_bg': '#fbe8e8',
}


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title('YouTube Premium 결제 장부')
        self.geometry('980x720')
        self.configure(bg=COLORS['bg'])
        self.minsize(800, 600)

        self.payments = load_data()

        self._build_styles()
        self._build_ui()
        self.refresh()

    def _build_styles(self):
        style = ttk.Style(self)
        try:
            style.theme_use('clam')
        except Exception:
            pass
        style.configure('TFrame', background=COLORS['bg'])
        style.configure('Card.TFrame', background=COLORS['card'], relief='solid', borderwidth=1)
        style.configure('Title.TLabel', background=COLORS['bg'], foreground=COLORS['ink'],
                        font=('Helvetica', 24, 'bold'))
        style.configure('Sub.TLabel', background=COLORS['bg'], foreground=COLORS['muted'],
                        font=('Courier', 10))
        style.configure('Section.TLabel', background=COLORS['bg'], foreground=COLORS['muted'],
                        font=('Courier', 10, 'bold'))
        style.configure('Treeview', background=COLORS['card'], fieldbackground=COLORS['card'],
                        foreground=COLORS['ink'], rowheight=30, font=('Helvetica', 11))
        style.configure('Treeview.Heading', background=COLORS['ink'], foreground=COLORS['bg'],
                        font=('Courier', 9, 'bold'))
        style.map('Treeview', background=[('selected', COLORS['ink'])],
                  foreground=[('selected', COLORS['bg'])])

    def _build_ui(self):
        # Header
        header = tk.Frame(self, bg=COLORS['bg'])
        header.pack(fill='x', padx=24, pady=(20, 10))
        tk.Label(header, text='YouTube Premium 결제 장부',
                 bg=COLORS['bg'], fg=COLORS['ink'],
                 font=('Helvetica', 22, 'bold')).pack(side='left')
        tk.Label(header, text='PAYMENT  TRACKER',
                 bg=COLORS['bg'], fg=COLORS['accent'],
                 font=('Courier', 10, 'bold')).pack(side='left', padx=(12, 0), pady=(10, 0))
        self.today_lbl = tk.Label(header, bg=COLORS['bg'], fg=COLORS['muted'],
                                  font=('Courier', 10))
        self.today_lbl.pack(side='right')

        # Summary strip
        self.summary_frame = tk.Frame(self, bg=COLORS['card'],
                                      highlightbackground=COLORS['line'],
                                      highlightthickness=1)
        self.summary_frame.pack(fill='x', padx=24, pady=(0, 16))

        # Two columns: left = members, right = form + history
        body = tk.Frame(self, bg=COLORS['bg'])
        body.pack(fill='both', expand=True, padx=24, pady=(0, 20))

        left = tk.Frame(body, bg=COLORS['bg'])
        left.pack(side='left', fill='both', expand=True)

        tk.Label(left, text='MEMBERS · 멤버별 현황',
                 bg=COLORS['bg'], fg=COLORS['muted'],
                 font=('Courier', 9, 'bold')).pack(anchor='w', pady=(0, 6))

        # scrollable member list
        self.members_canvas = tk.Canvas(left, bg=COLORS['bg'],
                                        highlightthickness=0, bd=0)
        self.members_canvas.pack(side='left', fill='both', expand=True)
        msb = ttk.Scrollbar(left, orient='vertical', command=self.members_canvas.yview)
        msb.pack(side='right', fill='y')
        self.members_canvas.configure(yscrollcommand=msb.set)
        self.members_inner = tk.Frame(self.members_canvas, bg=COLORS['bg'])
        self.members_window = self.members_canvas.create_window(
            (0, 0), window=self.members_inner, anchor='nw'
        )
        self.members_inner.bind('<Configure>',
            lambda e: self.members_canvas.configure(scrollregion=self.members_canvas.bbox('all')))
        self.members_canvas.bind('<Configure>',
            lambda e: self.members_canvas.itemconfig(self.members_window, width=e.width))

        # right column
        right = tk.Frame(body, bg=COLORS['bg'], width=380)
        right.pack(side='right', fill='y', padx=(16, 0))
        right.pack_propagate(False)

        # Form box
        form = tk.Frame(right, bg=COLORS['ink'], padx=18, pady=18)
        form.pack(fill='x')
        tk.Label(form, text='결제 기록 추가', bg=COLORS['ink'], fg=COLORS['bg'],
                 font=('Helvetica', 14, 'bold')).pack(anchor='w', pady=(0, 10))

        tk.Label(form, text='이름', bg=COLORS['ink'], fg='#bbbbbb',
                 font=('Courier', 9)).pack(anchor='w')
        self.name_var = tk.StringVar()
        self.name_combo = ttk.Combobox(form, textvariable=self.name_var)
        self.name_combo.pack(fill='x', pady=(2, 8))

        tk.Label(form, text='결제일 (YYYY-MM-DD)', bg=COLORS['ink'], fg='#bbbbbb',
                 font=('Courier', 9)).pack(anchor='w')
        self.date_var = tk.StringVar(value=date.today().strftime('%Y-%m-%d'))
        tk.Entry(form, textvariable=self.date_var).pack(fill='x', pady=(2, 8))

        tk.Label(form, text='개월 수', bg=COLORS['ink'], fg='#bbbbbb',
                 font=('Courier', 9)).pack(anchor='w')
        self.months_var = tk.StringVar(value='1')
        tk.Entry(form, textvariable=self.months_var).pack(fill='x', pady=(2, 10))

        tk.Button(form, text='+ 추가', bg=COLORS['accent'], fg='white',
                  activebackground='#d9002a', activeforeground='white',
                  font=('Helvetica', 10, 'bold'),
                  relief='flat', cursor='hand2',
                  command=self.add_payment).pack(fill='x', ipady=6)

        # History
        tk.Label(right, text='HISTORY · 전체 기록', bg=COLORS['bg'],
                 fg=COLORS['muted'], font=('Courier', 9, 'bold')).pack(
            anchor='w', pady=(14, 6))

        tree_frame = tk.Frame(right, bg=COLORS['bg'])
        tree_frame.pack(fill='both', expand=True)
        self.tree = ttk.Treeview(
            tree_frame, columns=('date', 'name', 'months'),
            show='headings', height=14
        )
        self.tree.heading('date', text='날짜')
        self.tree.heading('name', text='이름')
        self.tree.heading('months', text='개월')
        self.tree.column('date', width=100, anchor='w')
        self.tree.column('name', width=100, anchor='w')
        self.tree.column('months', width=70, anchor='e')
        self.tree.pack(side='left', fill='both', expand=True)
        tsb = ttk.Scrollbar(tree_frame, orient='vertical', command=self.tree.yview)
        tsb.pack(side='right', fill='y')
        self.tree.configure(yscrollcommand=tsb.set)
        self.tree.bind('<Delete>', lambda e: self.delete_selected())

        delbtn = tk.Button(right, text='선택 삭제  (Delete 키)',
                           font=('Courier', 9), relief='flat',
                           bg=COLORS['bg'], fg=COLORS['muted'],
                           activebackground=COLORS['danger'],
                           activeforeground='white',
                           cursor='hand2',
                           command=self.delete_selected)
        delbtn.pack(fill='x', pady=(6, 0))

        # Footer buttons
        footer = tk.Frame(self, bg=COLORS['bg'])
        footer.pack(fill='x', padx=24, pady=(0, 16))
        tk.Label(footer, text=f'Stored at  {data_path()}',
                 bg=COLORS['bg'], fg=COLORS['muted'],
                 font=('Courier', 8)).pack(side='left')
        tk.Button(footer, text='Reset', bg=COLORS['bg'], fg=COLORS['muted'],
                  relief='flat', font=('Courier', 9),
                  cursor='hand2', command=self.reset_data).pack(side='right', padx=4)
        tk.Button(footer, text='Import', bg=COLORS['bg'], fg=COLORS['muted'],
                  relief='flat', font=('Courier', 9),
                  cursor='hand2', command=self.import_data).pack(side='right', padx=4)
        tk.Button(footer, text='Export', bg=COLORS['bg'], fg=COLORS['muted'],
                  relief='flat', font=('Courier', 9),
                  cursor='hand2', command=self.export_data).pack(side='right', padx=4)

    # -------------------- actions --------------------
    def add_payment(self):
        name = self.name_var.get().strip()
        date_s = self.date_var.get().strip()
        months_s = self.months_var.get().strip()
        if not name or not date_s or not months_s:
            messagebox.showwarning('입력 확인', '이름, 날짜, 개월 수를 모두 입력해주세요')
            return
        try:
            parse_date(date_s)
        except ValueError:
            messagebox.showwarning('날짜 오류', '날짜 형식은 YYYY-MM-DD 여야 합니다 (예: 2026-04-01)')
            return
        try:
            months = int(months_s)
            if months < 1:
                raise ValueError
        except ValueError:
            messagebox.showwarning('개월 오류', '개월 수는 1 이상 정수여야 합니다')
            return

        self.payments.append({
            'id': 'p' + uuid.uuid4().hex[:8],
            'name': name,
            'date': date_s,
            'months': months,
        })
        save_data(self.payments)
        # clear form
        self.name_var.set('')
        self.date_var.set(date.today().strftime('%Y-%m-%d'))
        self.months_var.set('1')
        self.refresh()

    def quick_add_for(self, name: str):
        self.name_var.set(name)
        self.date_var.set(date.today().strftime('%Y-%m-%d'))
        self.months_var.set('1')

    def delete_selected(self):
        sel = self.tree.selection()
        if not sel:
            return
        if not messagebox.askyesno('삭제', f'{len(sel)}건을 삭제할까요?'):
            return
        ids = {self.tree.item(s)['tags'][0] for s in sel}
        self.payments = [p for p in self.payments if p['id'] not in ids]
        save_data(self.payments)
        self.refresh()

    def reset_data(self):
        if not messagebox.askyesno('초기화', '모든 데이터를 스크린샷 기준 초기값으로 되돌릴까요?'):
            return
        self.payments = list(SEED)
        save_data(self.payments)
        self.refresh()

    def export_data(self):
        fp = filedialog.asksaveasfilename(
            defaultextension='.json', filetypes=[('JSON', '*.json')],
            initialfile=f'yt_premium_{date.today().strftime("%Y-%m-%d")}.json'
        )
        if not fp:
            return
        with open(fp, 'w', encoding='utf-8') as f:
            json.dump(self.payments, f, ensure_ascii=False, indent=2)
        messagebox.showinfo('내보내기', f'저장했습니다\n{fp}')

    def import_data(self):
        fp = filedialog.askopenfilename(filetypes=[('JSON', '*.json')])
        if not fp:
            return
        try:
            with open(fp, 'r', encoding='utf-8') as f:
                data = json.load(f)
            assert isinstance(data, list)
        except Exception:
            messagebox.showerror('오류', 'JSON 파일을 읽을 수 없어요')
            return
        if not messagebox.askyesno('불러오기', f'{len(data)}건을 불러옵니다. 현재 데이터를 덮어쓸까요?'):
            return
        self.payments = data
        save_data(self.payments)
        self.refresh()

    # -------------------- rendering --------------------
    def refresh(self):
        # today label
        today = date.today()
        dow = ['월', '화', '수', '목', '금', '토', '일'][today.weekday()]
        self.today_lbl.config(text=f'TODAY  {today.strftime("%Y-%m-%d")}  ({dow})')

        status_list = compute_status(self.payments)

        # name combobox values
        names = sorted({p['name'] for p in self.payments})
        self.name_combo['values'] = names

        # summary
        for w in self.summary_frame.winfo_children():
            w.destroy()
        total_pay = len(self.payments)
        total_months = sum(int(p['months']) for p in self.payments)
        alerts = sum(1 for s in status_list if s.state in ('expired', 'soon'))
        next_up = next((s for s in status_list if s.days_left >= 0), None)

        stats = [
            ('MEMBERS', str(len(status_list)), ''),
            ('PAYMENTS', str(total_pay), '건'),
            ('TOTAL MONTHS', str(total_months), '개월'),
            ('NEXT DUE', f'{next_up.name} · D-{next_up.days_left}' if next_up else '—', ''),
            ('ALERTS', str(alerts), '건'),
        ]
        for i, (lbl, val, suffix) in enumerate(stats):
            cell = tk.Frame(self.summary_frame, bg=COLORS['card'])
            cell.grid(row=0, column=i, sticky='nsew', padx=0)
            self.summary_frame.columnconfigure(i, weight=1)
            tk.Label(cell, text=lbl, bg=COLORS['card'], fg=COLORS['muted'],
                     font=('Courier', 8, 'bold')).pack(anchor='w', padx=14, pady=(10, 0))
            tk.Label(cell, text=val + (('  ' + suffix) if suffix else ''),
                     bg=COLORS['card'], fg=COLORS['ink'],
                     font=('Helvetica', 18, 'bold')).pack(anchor='w', padx=14, pady=(0, 10))
            if i < len(stats) - 1:
                tk.Frame(self.summary_frame, bg=COLORS['line'], width=1).grid(
                    row=0, column=i, sticky='nse')

        # members list
        for w in self.members_inner.winfo_children():
            w.destroy()
        if not status_list:
            tk.Label(self.members_inner, text='데이터가 없습니다',
                     bg=COLORS['bg'], fg=COLORS['muted'],
                     font=('Courier', 10)).pack(pady=40)
        else:
            for s in status_list:
                self._member_card(self.members_inner, s)

        # history tree
        for item in self.tree.get_children():
            self.tree.delete(item)
        for p in sorted(self.payments, key=lambda x: x['date'], reverse=True):
            self.tree.insert('', 'end',
                values=(p['date'], p['name'], f"{p['months']}개월"),
                tags=(p['id'],))

    def _member_card(self, parent, s: MemberStatus):
        border_color = {
            'safe': COLORS['line'],
            'soon': COLORS['warn'],
            'expired': COLORS['danger']
        }[s.state]
        dday_bg = {
            'safe': COLORS['safe_bg'],
            'soon': COLORS['warn_bg'],
            'expired': COLORS['dang_bg']
        }[s.state]
        dday_fg = {
            'safe': COLORS['safe'],
            'soon': COLORS['warn'],
            'expired': COLORS['danger']
        }[s.state]
        dday_text = (
            f'D+{abs(s.days_left)} · 만료됨' if s.days_left < 0
            else 'D-DAY · 오늘!' if s.days_left == 0
            else f'D-{s.days_left}'
        )

        outer = tk.Frame(parent, bg=border_color,
                         highlightbackground=border_color, highlightthickness=0)
        outer.pack(fill='x', pady=6, padx=2)
        pad = 2 if s.state != 'safe' else 1
        card = tk.Frame(outer, bg=COLORS['card'])
        card.pack(fill='x', padx=pad, pady=pad)

        top = tk.Frame(card, bg=COLORS['card'])
        top.pack(fill='x', padx=16, pady=(12, 4))
        tk.Label(top, text=s.name, bg=COLORS['card'], fg=COLORS['ink'],
                 font=('Helvetica', 16, 'bold')).pack(side='left')
        tk.Label(top, text=f'{s.count}회 · {s.total_months}개월 누적',
                 bg=COLORS['card'], fg=COLORS['muted'],
                 font=('Courier', 9)).pack(side='right')

        info = tk.Frame(card, bg=COLORS['card'])
        info.pack(fill='x', padx=16, pady=(0, 4))
        rows = [
            ('마지막 결제', s.last_pay_date),
            ('결제 개월', f'{s.last_pay_months}개월'),
            ('커버 만료', s.cover_end),
        ]
        for k, v in rows:
            r = tk.Frame(info, bg=COLORS['card'])
            r.pack(fill='x', pady=2)
            tk.Label(r, text=k, bg=COLORS['card'], fg=COLORS['muted'],
                     font=('Helvetica', 10)).pack(side='left')
            tk.Label(r, text=v, bg=COLORS['card'], fg=COLORS['ink'],
                     font=('Courier', 10, 'bold')).pack(side='right')

        dday = tk.Label(card, text=dday_text, bg=dday_bg, fg=dday_fg,
                        font=('Helvetica', 13, 'bold'), pady=8)
        dday.pack(fill='x', padx=16, pady=(8, 8))

        btn = tk.Button(card, text=f'+  {s.name} 결제 추가',
                        bg=COLORS['card'], fg=COLORS['ink'],
                        activebackground=COLORS['ink'],
                        activeforeground=COLORS['card'],
                        font=('Courier', 9), relief='solid', bd=1,
                        cursor='hand2',
                        command=lambda n=s.name: self.quick_add_for(n))
        btn.pack(fill='x', padx=16, pady=(0, 12))


if __name__ == '__main__':
    App().mainloop()
