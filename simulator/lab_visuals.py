"""Tkinter artwork for simulated lights and fan (onscreen only)."""
import tkinter as tk
import math

class AnimatedCircuit(tk.Canvas):
    """Animated *visualization* of the simulated circuit's logical state.

    It deliberately does not invent extra hardware sensors or CAN messages.
    The existing Circuit/ECU classes still decide the electrical diagnostics.
    """

    W, H = 320, 164

    def __init__(self, parent, circuit_id):
        super().__init__(parent, bg="#0b1628", height=158, relief="flat",
                         highlightthickness=1, highlightbackground="#35445b", bd=0)
        self.circuit_id = circuit_id
        self.last_state = None
        self._dimensions = (320, 164)
        self.bind("<Configure>", self._on_resize)

    def _on_resize(self, event):
        self._dimensions = (max(1, event.width), max(1, event.height))
        self.last_state = None

    def _coords(self, coords):
        w, h = self._dimensions
        return tuple((x * w / self.W if i % 2 == 0 else x * h / self.H)
                     for i, x in enumerate(coords))

    def _oval(self, x1, y1, x2, y2, fill, outline="", width=1):
        return self.create_oval(*self._coords((x1,y1,x2,y2)), fill=fill,
                                outline=outline, width=width)

    def _rect(self, x1, y1, x2, y2, fill, outline="", width=1):
        return self.create_rectangle(*self._coords((x1,y1,x2,y2)), fill=fill,
                                     outline=outline, width=width)

    def _line(self, *points, fill, width=2, smooth=False):
        return self.create_line(*self._coords(points), fill=fill, width=width,
                                capstyle="round", smooth=smooth)

    def _poly(self, coords, fill, outline="", width=1):
        return self.create_polygon(*self._coords(coords), fill=fill,
                                   outline=outline, width=width, smooth=False)

    def _scene(self):
        self._rect(0, 0, 320, 164, "#0b1628")
        self._rect(0, 110, 320, 164, "#101e30")
        self._line(14, 147, 306, 147, fill="#26344a")

    def _car(self, rear=False):
        self._oval(39, 116, 281, 168, "#09101b")  # road shadow
        self._poly((64,57, 88,28, 230,28, 256,57), "#1b3046", "#486480")
        self._poly((86,31, 111,12, 209,12, 232,31), "#0c1727", "#334960")
        self._poly((36,88, 51,59, 269,59, 284,88, 284,133, 36,133),
                   "#26374b", "#6c8396")
        self._poly((49,66, 77,51, 243,51, 271,66, 261,79, 59,79), "#253e56")
        self._line(48,130,272,130,fill="#516779",width=3)
        if rear:
            self._rect(124,120,196,130,"#111b29")
            self._line(101,43,217,43,fill="#678399",width=2)
        else:
            self._rect(128,90,192,115,"#0b1827",outline="#465d73")
            for y in (95,101,107,112):
                self._line(131,y,189,y,fill="#52697e",width=1)

    def _glow(self, cx, cy, tone):
        if tone == "white":
            steps = [(39,"#1c3952"),(33,"#355673"),(27,"#718da8"),(21,"#b6dcfa"),(15,"#e5f7ff"),(9,"#ffffff")]
            rays = "#476581"
        elif tone == "red":
            steps = [(38,"#49212a"),(31,"#7d2833"),(25,"#b72a37"),(18,"#ff4859"),(12,"#ff9da4"),(6,"#fff2e7")]
            rays = "#6f2731"
        else:
            steps = [(33,"#493720"),(26,"#80511c"),(21,"#bc7419"),(16,"#ffae35"),(10,"#ffe091"),(5,"#fff7cf")]
            rays = "#6b4d24"
        for rad, color in steps:
            self._oval(cx-rad,cy-rad,cx+rad,cy+rad,color)
        self._line(cx-42,cy,cx+42,cy,fill=rays,width=1)
        self._line(cx,cy-32,cx,cy+31,fill=rays,width=1)

    def _front_lights(self, on):
        self._car()
        for x in (79,241):
            self._oval(x-36,83,x+36,119,"#101e31",outline="#657c95",width=2)
            self._oval(x-27,88,x+27,113,"#33495b" if on else "#152336",outline="#879baf")
            if on:
                # Light beams stretch downward from the two real positions.
                self._poly((x-9,109, x+9,109, x+55,163,x-55,163), "#223c56")
                self._glow(x,101,"white")
            else:
                self._oval(x-10,92,x+10,110,"#405166",outline="#697c8f")

    def _indicators(self, on):
        self._car()
        for x in (77,243):
            self._rect(x-33,91,x+33,111,"#3f3421" if not on else "#82551b",outline="#aa8850")
            for dx in (-23,-11,1,13,25):
                color = "#ffe798" if on else "#4f4736"
                self._rect(x+dx-4,95,x+dx+2,108,color)
            if on:
                self._glow(x,101,"amber")
        # The physical design has one shared Indicators channel; both blink together.
        self._line(139,116,181,116,fill="#60788d",width=2)

    def _brakes(self, on):
        self._car(rear=True)
        for x in (78,242):
            self._rect(x-37,85,x+37,111,"#511e2a",outline="#9c5460",width=2)
            for dy in (0,8,16):
                self._line(x-29,89+dy,x+29,89+dy,
                           fill="#ff5765" if on else "#67303b",width=3)
            if on:
                self._glow(x,99,"red")
        self._rect(125,50,195,57,"#ff3346" if on else "#3b2230")
        if on:
            self._line(126,53,194,53,fill="#ffbfc0",width=3)

    def _fan(self, on, angle):
        self._rect(0,0,320,164,"#0a192b")
        self._rect(58,5,262,159,"#21374b",outline="#70869a",width=2)
        self._rect(69,13,250,151,"#122235",outline="#4d657b")
        for x,y in ((77,23),(242,23),(77,141),(242,141)):
            self._oval(x-4,y-4,x+4,y+4,"#9cabb8",outline="#263b4a")
            self._line(x-2,y-2,x+2,y+2,fill="#435465",width=1)
        self._oval(90,13,230,152,"#071522",outline="#6e8391",width=3)
        for r in (66,57,48):
            self._oval(160-r,82-r,160+r,82+r,"",outline="#41586c",width=2)
        # Five blades, redrawn at new angle while the circuit is powered.
        for i in range(5):
            theta = angle + i*2*math.pi/5
            base = [(17,-7),(29,-17),(50,-18),(60,-8),(42,8),(27,13),(17,7)]
            c,s = math.cos(theta), math.sin(theta)
            xy=[]
            for dx,dy in base:
                xy.extend((160+dx*c-dy*s,82+dx*s+dy*c))
            self._poly(xy, "#7893a6" if on else "#3d5264", outline="#9db9c9" if on else "#566c7d")
        for r,c in ((17,"#829fb4"),(12,"#2d4255"),(7,"#a4bdcc")):
            self._oval(160-r,82-r,160+r,82+r,c)
        if on:
            # Airflow stripes: purely visual, no airflow sensor claimed.
            for d in range(3):
                shift = 3*math.sin(angle*2+d)
                self._line(232,54+d*26+shift,252,50+d*26+shift,276,54+d*26+shift,302,50+d*26+shift,
                           fill="#74b9e0" if d == 1 else "#466b89",width=2,smooth=True)
        else:
            self._line(244,132,302,132,fill="#40546b",width=2)

    def render(self, circuit, fault, angle, blink):
        lit = bool(circuit.command_on and circuit.connected)
        state = (lit, bool(fault), bool(blink) if self.circuit_id==2 else None,
                 round(angle,2) if self.circuit_id==4 and lit else None,
                 self._dimensions)
        if state == self.last_state:
            return
        self.last_state = state
        self.delete("all")
        self._scene()
        if self.circuit_id == 1:
            self._front_lights(lit)
        elif self.circuit_id == 2:
            self._indicators(lit and blink)
        elif self.circuit_id == 3:
            self._brakes(lit)
        else:
            self._fan(lit, angle)
        if fault:
            self._rect(6,6,96,25,"#4e1b2a",outline="#fa5f78")
            self.create_text(*self._coords((51,15)),text="WIRE FAULT",fill="#ffd8df",
                             font=("Segoe UI",8,"bold"))
        elif not circuit.command_on:
            self._rect(6,6,70,25,"#293443")
            self.create_text(*self._coords((38,15)),text="OFF",fill="#cbd7e5",
                             font=("Segoe UI",9,"bold"))