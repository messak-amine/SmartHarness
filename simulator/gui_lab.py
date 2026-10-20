"""SmartHarness experimental electrical lab GUI: python -m simulator.gui_lab.

Runs a synthetic, deterministic electrical model alongside the EXISTING
SmartHarness wire-disconnection CAN pipeline. No new CAN message formats.
"""
from __future__ import annotations

import csv
from collections import deque
from pathlib import Path
import re
import subprocess
import sys
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from simulator.electrical_lab import (
    CIRCUITS, LABELS, MODES, BaselineCANBridge, ElectricalLab,
)
from simulator.lab_visuals import AnimatedCircuit

BG = "#091320"
PANEL = "#111f30"
CARD = "#192a3e"
TEXT = "#f0f5fd"
MUTED = "#a9bcd0"
BORDER = "#31475c"
BLUE = "#7ab9ff"
GREEN = "#63ddb0"
RED = "#ff7586"
AMBER = "#ffc76a"
ORANGE = "#f4a261"
COLORS = {1: BLUE, 2: AMBER, 3: RED, 4: GREEN}
MODE_OPTIONS = [(LABELS[m], m) for m in MODES]
MODES_BY_LABEL = {label: mode for label, mode in MODE_OPTIONS}

SCENARIO_NAMES = {
    "normal": "01 · Fonctionnement normal",
    "open": "02 · Déconnexion et récupération",
    "short": "03 · Court-circuit + protection",
    "overload": "04 · Surcharge de courant",
    "undervoltage": "05 · Sous-tension d'alimentation",
    "intermittent": "06 · Panne intermittente",
    "multi": "07 · Pannes sur ECU A + ECU B",
    "off": "08 · OFF pendant un défaut",
}


def scenario_plan(name):
    """Each entry is (annotation, circuit-mode updates, number of 0.5s samples).

    `RESET:ID` is a local simulated protection-reset operation.
    """
    if name == "normal":
        return [("Tous les circuits sont normaux", {}, 5)]
    if name == "open":
        return [("Déconnexion du faisceau des phares", {1: "OPEN"}, 3),
                ("La panne persiste : aucun nouvel événement", {}, 3),
                ("Réparation du faisceau", {1: "NORMAL"}, 3)]
    if name == "short":
        return [("Court-circuit sur les feux de frein", {3: "SHORT"}, 5),
                ("Le défaut électrique est retiré ; protection encore ouverte", {3: "NORMAL"}, 2),
                ("Réarmement manuel de la protection simulée", {"RESET:3": True}, 3)]
    if name == "overload":
        return [("Surcharge de ventilation", {4: "OVERLOAD"}, 5),
                ("Retour à la charge normale", {4: "NORMAL"}, 3)]
    if name == "undervoltage":
        return [("Baisse de tension sur les clignotants", {2: "UNDERVOLTAGE"}, 5),
                ("Tension rétablie", {2: "NORMAL"}, 3)]
    if name == "intermittent":
        return [("Faux contact sur les phares, alternance périodique", {1: "INTERMITTENT"}, 22),
                ("Réparation du faux contact", {1: "NORMAL"}, 3)]
    if name == "multi":
        return [("Défaut ouvert ECU A et surcharge ECU B", {1: "OPEN", 4: "OVERLOAD"}, 4),
                ("Court-circuit supplémentaire sur ECU B", {3: "SHORT"}, 5),
                ("Les défauts sur ECU B sont retirés", {3: "NORMAL", 4: "NORMAL"}, 2),
                ("La protection ECU B est réarmée", {"RESET:3": True}, 3),
                ("Réparation sur ECU A", {1: "NORMAL"}, 3)]
    if name == "off":
        return [("Phares : court-circuit simulé", {1: "SHORT"}, 2),
                ("Circuit coupé : diagnostic mémorisé (politique actuelle)", {"OFF:1": True}, 2),
                ("Défaut retiré alors que circuit OFF", {1: "NORMAL"}, 2),
                ("ON et réévaluation : récupération après temporisation", {"ON:1": True}, 3)]
    raise ValueError(name)


class Trace(tk.Canvas):
    """Two traces of local synthetic readings; nothing is measured from hardware."""
    def __init__(self, parent, lab_getter, cid_getter, key, scale, title, line_color):
        super().__init__(parent, bg=PANEL, height=180, bd=0, highlightthickness=0)
        self.lab_getter, self.cid_getter = lab_getter, cid_getter
        self.key, self.scale = key, scale
        self.title, self.line_color = title, line_color
        self.bind("<Configure>", lambda _: self.draw())

    def draw(self):
        self.delete("all")
        w, h = max(200, self.winfo_width()), max(100, self.winfo_height())
        l, r, t, b = 53, w-22, 33, h-29
        self.create_text(l, 13, text=self.title, anchor="w", fill=TEXT,
                         font=("Segoe UI", 10, "bold"))
        for frac in (0, .25, .5, .75, 1):
            y = b-frac*(b-t)
            self.create_line(l,y,r,y,fill="#2b3e50",dash=(3,5))
            self.create_text(l-8,y,text=f"{int(frac*self.scale)}",anchor="e",
                             fill=MUTED,font=("Segoe UI",8))
        self.create_line(l,b,r,b,fill=BORDER)
        hist = self.lab_getter().history[self.cid_getter()][-50:]
        if len(hist) < 2:
            return
        pts=[]
        for i, item in enumerate(hist):
            x=l+(r-l)*i/49 if len(hist)>=50 else l+(r-l)*i/max(1,len(hist)-1)
            value=min(self.scale, getattr(item,self.key))
            y=b-value/self.scale*(b-t)
            pts.extend([x,y])
        self.create_line(*pts, fill=self.line_color,width=2,capstyle="round")
        latest=getattr(hist[-1],self.key)
        self.create_text(r,t-12,text=f"Dernier: {latest}",anchor="e",fill=self.line_color,
                         font=("Segoe UI",9,"bold"))


class LabWindow:
    def __init__(self, root):
        self.root = root
        self.lab = ElectricalLab()
        self.bridge = BaselineCANBridge()
        self.running = False
        self.closed = False
        self.job = None
        self.scenario_job = None
        self.scenario_tasks = deque()
        self.can_rows = []
        self.frames_total = 0
        self.selected_cid = tk.IntVar(value=1)
        self.scenario = tk.StringVar(value=SCENARIO_NAMES["open"])
        self.report = tk.StringVar(value="Logiciel uniquement · aucun équipement connecté")
        self.widgets = {}
        self.visuals = {}
        self.controls = {}
        self.root.title("SmartHarness | Engineering Diagnostics Lab · experimental")
        self.root.geometry("1510x980")
        self.root.minsize(1060,740)
        self.root.configure(bg=BG)
        self._style()
        self._build()
        self._tick()
        self.root.protocol("WM_DELETE_WINDOW", self.close)

    def _style(self):
        style=ttk.Style(self.root)
        style.theme_use("clam")
        style.configure("S.Treeview",font=("Segoe UI",9),rowheight=26,background=PANEL,
                        fieldbackground=PANEL,foreground=TEXT)
        style.configure("S.Treeview.Heading",font=("Segoe UI",9,"bold"),
                        background=CARD,foreground=TEXT)
        style.map("S.Treeview",background=[("selected","#31516c")])
        style.configure("S.TNotebook",background=BG,borderwidth=0)
        style.configure("S.TNotebook.Tab",font=("Segoe UI",10,"bold"),
                        background=CARD,foreground=MUTED,padding=(18,9))
        style.map("S.TNotebook.Tab",background=[("selected",PANEL)],foreground=[("selected",TEXT)])

    def label(self,parent,text,*,size=10,color=TEXT,bold=False,**kwargs):
        return tk.Label(parent,text=text,bg=parent.cget("bg"),fg=color,
                        font=("Segoe UI",size,"bold" if bold else "normal"),**kwargs)

    def btn(self,parent,text,command,color=BLUE):
        return tk.Button(parent,text=text,command=command,bg=color,fg=BG,
                         relief="flat",bd=0,padx=12,pady=8,cursor="hand2",
                         font=("Segoe UI",9,"bold"))

    def _build(self):
        header=tk.Frame(self.root,bg=BG,padx=18,pady=10)
        header.pack(fill="x")
        self.label(header,"SmartHarness  /  ENGINEERING LAB",size=20,bold=True).pack(side="left")
        self.btn(header,"▶ Démarrer",self.toggle_run,GREEN).pack(side="right",padx=5)
        self.btn(header,"PAS +0.5 s",self.step_once,BLUE).pack(side="right",padx=5)
        self.btn(header,"↺ Réinitialiser",self.reset,AMBER).pack(side="right",padx=5)
        self.label(self.root,"Modèle électrique basse tension synthétique | diagnostics avancés locaux | CAN officiel inchangé",
                   color=MUTED,size=10).pack(fill="x",padx=20,anchor="w")
        self.label(self.root,"Court-circuit, surcharge et sous-tension ne sont PAS encodés en messages CAN v0.1.",
                   color=AMBER,size=10).pack(fill="x",padx=20,anchor="w",pady=(0,5))

        tabs=ttk.Notebook(self.root,style="S.TNotebook")
        tabs.pack(expand=True,fill="both",padx=12,pady=8)
        live=tk.Frame(tabs,bg=BG)
        graphs=tk.Frame(tabs,bg=BG)
        logs=tk.Frame(tabs,bg=BG)
        tabs.add(live,text="01  CIRCUITS & CONTRÔLES")
        tabs.add(graphs,text="02  MESURES & COURBES")
        tabs.add(logs,text="03  HISTORIQUE & CAN")
        self.tabs=tabs

        top=tk.Frame(live,bg=BG)
        top.pack(fill="both",expand=True)
        grid=tk.Frame(top,bg=BG)
        grid.pack(side="left",fill="both",expand=True,padx=(0,8))
        for cid in CIRCUITS:
            card=tk.Frame(grid,bg=PANEL,padx=11,pady=9,highlightthickness=1,
                          highlightbackground=BORDER)
            card.grid(row=(cid-1)//2,column=(cid-1)%2,padx=5,pady=5,sticky="nsew")
            header=tk.Frame(card,bg=PANEL)
            header.pack(fill="x")
            name, ecu, _ = CIRCUITS[cid]
            self.label(header,f"{cid:02d}  {name.upper()}  ·  ECU {ecu}",size=12,bold=True).pack(side="left")
            status=self.label(header,"NORMAL",color=GREEN,bold=True)
            status.pack(side="right")
            visual=AnimatedCircuit(card,cid)
            visual.pack(fill="both",expand=True,pady=(5,6))
            self.visuals[cid]=visual
            values=self.label(card,"V: —     I: —     P: —",color=MUTED,size=10)
            values.pack(fill="x",anchor="w")
            ctrl=tk.Frame(card,bg=PANEL)
            ctrl.pack(fill="x",pady=(6,0))
            flag=tk.BooleanVar(value=True)
            check=tk.Checkbutton(ctrl,text="Commande ON",variable=flag,bg=PANEL,fg=TEXT,
                                selectcolor=CARD,activebackground=PANEL,
                                activeforeground=TEXT,command=lambda c=cid,v=flag:self.command(c,v.get()))
            check.pack(side="left")
            mode=tk.StringVar(value=LABELS["NORMAL"])
            selector=ttk.Combobox(ctrl,textvariable=mode,state="readonly",
                                  values=[x[0] for x in MODE_OPTIONS],width=18)
            selector.pack(side="right",padx=5)
            selector.bind("<<ComboboxSelected>>",lambda _,c=cid,v=mode:self.mode(c,v.get()))
            self.btn(card,"Réarmer protection",lambda c=cid:self.reset_fuse(c),AMBER).pack(anchor="e",pady=(5,0))
            self.widgets[cid]=(status,values)
            self.controls[cid]=(flag,mode)
        grid.columnconfigure(0,weight=1)
        grid.columnconfigure(1,weight=1)
        grid.rowconfigure(0,weight=1)
        grid.rowconfigure(1,weight=1)
        aside=tk.Frame(top,bg=PANEL,padx=13,pady=12,width=315,highlightbackground=BORDER,
                       highlightthickness=1)
        aside.pack(side="right",fill="y")
        aside.pack_propagate(False)
        self.label(aside,"SCÉNARIOS PÉDAGOGIQUES",bold=True,size=12).pack(anchor="w")
        chooser=ttk.Combobox(aside,state="readonly",textvariable=self.scenario,
                             values=list(SCENARIO_NAMES.values()),width=32)
        chooser.pack(fill="x",pady=9)
        self.description=self.label(aside,SCENARIO_NAMES["open"],color=MUTED,wraplength=270)
        self.description.pack(fill="x",anchor="w")
        chooser.bind("<<ComboboxSelected>>",lambda _:self.description.config(text=self.scenario.get()))
        self.btn(aside,"▶ EXÉCUTER SCÉNARIO",self.run_scenario,GREEN).pack(fill="x",pady=12)
        self.label(aside,"Scénarios: normal, coupure, court-circuit + protection, surcharge, sous-tension, faux contact, deux ECU, OFF pendant défaut.",
                   color=MUTED,wraplength=270,justify="left").pack(fill="x",pady=5)
        self.label(aside,"SURVEILLANCE",size=12,bold=True).pack(anchor="w",pady=(20,8))
        self.summary=self.label(aside,"",color=TEXT,justify="left",wraplength=270)
        self.summary.pack(anchor="w",fill="x")
        self.label(aside,"Les capteurs, la source et la protection sont SIMULÉS, pas mesurés.",
                   color=AMBER,justify="left",wraplength=270).pack(side="bottom",anchor="w")

        block=tk.Frame(graphs,bg=PANEL,padx=15,pady=12)
        block.pack(fill="both",expand=True,padx=10,pady=10)
        selector=tk.Frame(block,bg=PANEL)
        selector.pack(fill="x")
        self.label(selector,"ANALYSE D'UN CIRCUIT",size=13,bold=True).pack(side="left")
        for cid in CIRCUITS:
            tk.Radiobutton(selector,text=CIRCUITS[cid][0],value=cid,
                           variable=self.selected_cid,command=self._draw_graphs,bg=PANEL,fg=TEXT,
                           selectcolor=CARD,activebackground=PANEL,activeforeground=TEXT).pack(side="left",padx=12)
        self.vtrace=Trace(block,lambda:self.lab,lambda:self.selected_cid.get(),
                          "voltage_mv",3600,"TENSION SIMULÉE (mV)",BLUE)
        self.vtrace.pack(fill="both",expand=True,pady=10)
        self.itrace=Trace(block,lambda:self.lab,lambda:self.selected_cid.get(),
                          "current_ma",8500,"COURANT SIMULÉ (mA)",ORANGE)
        self.itrace.pack(fill="both",expand=True,pady=10)
        self.label(block,"Hypothèses : source 3,3 V, résistance série 0,25 Ω ; charge résistive ; seuils expérimentaux. Une vraie mesure aura un autre comportement.",
                   color=MUTED,wraplength=1100).pack(anchor="w",pady=6)

        content=tk.Frame(logs,bg=BG)
        content.pack(fill="both",expand=True,padx=12,pady=12)
        localbox=tk.Frame(content,bg=PANEL,padx=10,pady=10)
        localbox.pack(fill="both",expand=True,pady=(0,10))
        self.label(localbox,"DIAGNOSTIC AVANCÉ LOCAL — hors contrat CAN",size=12,bold=True).pack(anchor="w")
        self.local_tree=ttk.Treeview(localbox,style="S.Treeview",show="headings",
                                    columns=("t","ecu","c","kind","transition","seq"),height=9)
        for key,name,width in [("t","t (s)",70),("ecu","ECU",65),("c","Circuit",75),
                                ("kind","Événement",105),("transition","Transition",330),("seq","Seq local",85)]:
            self.local_tree.heading(key,text=name)
            self.local_tree.column(key,width=width,stretch=key=="transition")
        self.local_tree.pack(fill="both",expand=True,pady=6)
        canbox=tk.Frame(content,bg=PANEL,padx=10,pady=10)
        canbox.pack(fill="both",expand=True)
        self.label(canbox,"CAN VIRTUEL ORIGINAL — uniquement déconnexion / récupération",size=12,bold=True).pack(anchor="w")
        self.can_tree=ttk.Treeview(canbox,style="S.Treeview",show="headings",
                                  columns=("t","id","data","circuit","kind","seq"),height=8)
        for key,name,width in [("t","t (s)",70),("id","CAN ID",75),("data","Données (8 octets)",255),
                               ("circuit","Circuit",75),("kind","Code",125),("seq","Seq CAN",85)]:
            self.can_tree.heading(key,text=name)
            self.can_tree.column(key,width=width,stretch=key=="data")
        self.can_tree.pack(fill="both",expand=True,pady=6)
        tools=tk.Frame(content,bg=BG)
        tools.pack(fill="x",pady=10)
        self.btn(tools,"Exporter CSV",self.export_csv,BLUE).pack(side="left",padx=5)
        self.btn(tools,"Exécuter tests Python",self.run_tests,GREEN).pack(side="left",padx=5)
        self.tests_result=self.label(tools,"Tests non exécutés depuis cette interface",color=MUTED)
        self.tests_result.pack(side="left",padx=15)
        footer=self.label(self.root,"",color=AMBER,size=10)
        footer.pack(fill="x",padx=20,pady=(0,8))
        self.footer=footer

    def command(self,cid,on):
        self.stop_scenario()
        self.lab.set_command(cid,on)
        self._tick()

    def mode(self,cid,label):
        self.stop_scenario()
        self.lab.set_mode(cid,MODES_BY_LABEL[label])
        self._tick()

    def reset_fuse(self,cid):
        try:
            self.lab.reset_fuse(cid)
            self._tick()
        except ValueError as e:
            messagebox.showwarning("Protection simulée",str(e))

    def _tick(self):
        readings,events=self.lab.step()
        frames=self.bridge.step(self.lab,readings)
        for event in events:
            self.local_tree.insert("","end",values=(f"{event.seconds:.1f}",event.ecu,event.circuit,
                event.kind,f"{LABELS[event.previous]} → {LABELS[event.current]}",event.seq))
        for frame,diagnostic in frames:
            self.can_rows.append((f"{self.lab.tick*.5:.1f}",f"0x{frame.arbitration_id:03X}",
                                  bytes(frame.data).hex(" ").upper(),diagnostic["circuit"],
                                  "OPEN" if diagnostic["fault_code"]==1 else "RECOVERY",diagnostic["seq"]))
            self.can_tree.insert("","end",values=self.can_rows[-1])
            self.frames_total+=1
        for cid,r in readings.items():
            ch=self.lab.channels[cid]
            status=self.widgets[cid][0]
            stat=LABELS[r.diagnostic] if r.diagnostic != "OFF" else "Commande OFF"
            if r.diagnostic not in ("OFF", "NORMAL"):
                stat += " · confirmé" if ch.stable == r.diagnostic else " · filtrage..."
            status.config(text=stat.upper(),fg=GREEN if r.diagnostic=="NORMAL" else (MUTED if r.diagnostic=="OFF" else RED))
            self.widgets[cid][1].config(text=f"{r.voltage_mv} mV   |   {r.current_ma} mA   |   {r.power_mw} mW")
            # Existing animation represents availability, not realistic motor speed.
            from types import SimpleNamespace
            proxy=SimpleNamespace(command_on=r.command_on,connected=(r.actual_mode=="NORMAL"))
            self.visuals[cid].render(proxy, ch.stable=="OPEN",self.lab.tick*.42,(self.lab.tick%2==0))
        self.summary.config(text=(f"Temps simulé : {self.lab.tick*0.5:.1f} s\n"
                                  f"Alertes locales : {len(self.lab.events)}\n"
                                  f"Messages CAN ouverts/recovery : {self.frames_total}\n"
                                  f"ECU A seq local : {self.lab.sequences['A']}\n"
                                  f"ECU B seq local : {self.lab.sequences['B']}"))
        self._draw_graphs()
        self.footer.config(text=self.report.get())

    def _draw_graphs(self):
        if hasattr(self,"vtrace"):
            self.vtrace.draw()
            self.itrace.draw()

    def _loop(self):
        self.job=None
        if not self.running or self.closed:
            return
        try:
            self._tick()
        except Exception as e:
            self.running=False
            messagebox.showerror("Simulation error",str(e))
            return
        self.job=self.root.after(500,self._loop)

    def toggle_run(self):
        self.stop_scenario()
        self.running=not self.running
        self.report.set("Simulation continue active (0,5s / pas)" if self.running else "Simulation en pause")
        if self.running:
            self._loop()

    def step_once(self):
        self.stop_scenario()
        self.running=False
        self._tick()

    def stop_scenario(self):
        if self.scenario_job is not None:
            self.root.after_cancel(self.scenario_job)
            self.scenario_job=None
        self.scenario_tasks.clear()

    def reset(self, silent=False):
        self.stop_scenario()
        self.running=False
        if self.job is not None:
            self.root.after_cancel(self.job)
            self.job=None
        self.lab=ElectricalLab()
        self.bridge.reset()
        self.frames_total=0
        self.can_rows.clear()
        for tree in (self.local_tree,self.can_tree):
            for item in tree.get_children():
                tree.delete(item)
        for cid, (flag,mode) in self.controls.items():
            flag.set(True)
            mode.set(LABELS["NORMAL"])
        self.report.set("Simulation réinitialisée")
        if not silent:
            self._tick()

    def run_scenario(self):
        name=next(k for k,v in SCENARIO_NAMES.items() if v==self.scenario.get())
        plan=scenario_plan(name)
        self.reset(silent=True)
        for title,changes,repeats in plan:
            self.scenario_tasks.append((title, changes))
            self.scenario_tasks.extend((title,{}) for _ in range(repeats-1))
        self.tabs.select(0)
        self._scenario_step()

    def _scenario_step(self):
        self.scenario_job=None
        if not self.scenario_tasks or self.closed:
            if not self.closed:
                self.report.set(f"Scénario terminé · {len(self.lab.events)} diagnostics locaux · {self.frames_total} trames CAN")
                self.footer.config(text=self.report.get())
            return
        label, changes=self.scenario_tasks.popleft()
        for cid,mode in changes.items():
            if isinstance(cid,int):
                self.lab.set_mode(cid,mode)
                self.controls[cid][1].set(LABELS[mode])
            elif cid.startswith("RESET:"):
                self.lab.reset_fuse(int(cid.split(":")[1]))
            elif cid.startswith("OFF:"):
                n=int(cid.split(":")[1]); self.lab.set_command(n,False); self.controls[n][0].set(False)
            elif cid.startswith("ON:"):
                n=int(cid.split(":")[1]); self.lab.set_command(n,True); self.controls[n][0].set(True)
        self.report.set(label)
        self._tick()
        self.scenario_job=self.root.after(480,self._scenario_step)

    def export_csv(self):
        if not self.lab.events and not self.can_rows:
            messagebox.showinfo("CSV","Aucun événement à exporter")
            return
        path=filedialog.asksaveasfilename(defaultextension=".csv",filetypes=[("CSV","*.csv")],
                                          initialfile="smartharness_lab_events.csv")
        if not path:
            return
        with open(path,"w",newline="",encoding="utf-8") as fp:
            writer=csv.writer(fp)
            writer.writerow(["source","time_s","ecu","circuit","event","details","sequence"])
            for e in self.lab.events:
                writer.writerow(["advanced_local",e.seconds,e.ecu,e.circuit,e.kind,
                                 f"{e.previous}->{e.current}",e.seq])
            for t,identifier,payload,circuit,kind,seq in self.can_rows:
                writer.writerow(["original_virtual_CAN",t,identifier,circuit,kind,payload,seq])
        self.report.set(f"CSV exporté : {path}")
        self.footer.config(text=self.report.get())

    def run_tests(self):
        project=Path(__file__).resolve().parent.parent
        self.tests_result.config(text="Exécution...",fg=AMBER)
        self.root.update_idletasks()
        try:
            result=subprocess.run([sys.executable,"-m","unittest","discover","-s","tests","-v"],
                                  cwd=project,capture_output=True,text=True,timeout=45)
            output=result.stdout+"\n"+result.stderr
            match=re.search(r"Ran (\d+) tests?",output)
            count=match.group(1) if match else "?"
            ok=result.returncode==0 and re.search(r"(?m)^OK$",output)
            self.tests_result.config(text=f"{count} tests — {'OK' if ok else 'ERREUR'}",
                                     fg=GREEN if ok else RED)
            if not ok:
                messagebox.showerror("Unit tests","Échec. Exécutez les tests dans le terminal pour les détails.\n"+output[-2200:])
        except (OSError,subprocess.TimeoutExpired) as e:
            self.tests_result.config(text="Erreur de lancement",fg=RED)
            messagebox.showerror("Unit tests",str(e))

    def close(self):
        self.closed=True
        self.stop_scenario()
        if self.job is not None:
            self.root.after_cancel(self.job)
            self.job=None
        self.bridge.close()
        self.root.destroy()


def main():
    root=tk.Tk()
    try:
        LabWindow(root)
    except Exception as e:
        messagebox.showerror("SmartHarness Engineering Lab",f"Impossible de démarrer : {e}")
        root.destroy()
        return
    root.mainloop()


if __name__=="__main__":
    main()
