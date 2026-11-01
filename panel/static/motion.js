/* 奶龙控制台 — motion layer.
   Spring physics, the elastic press every control shares, and the
   liquid-glass dock used as the phone navigation bar. The behaviour follows
   FlClash's navigation dock (lens that lifts on press, follows the finger
   with a jelly stretch, flings to the next tab and springs home); this is an
   independent web implementation of that interaction, not a port. */
(function () {
  "use strict";

  const reduceMotion = window.matchMedia ? matchMedia("(prefers-reduced-motion: reduce)") : { matches: false };

  /* ---------- springs ---------- */
  // Spring descriptions use mass 1: stiffness k and damping c.
  function ratioSpring(k, ratio) {
    return { k, c: ratio * 2 * Math.sqrt(k) };
  }
  function durationSpring(ms, bounce = 0) {
    const t = ms / 1000;
    const k = Math.pow((2 * Math.PI) / t, 2);
    const ratio = bounce > 0 ? 1 - bounce : 1 / (bounce + 1);
    return { k, c: ratio * 2 * Math.sqrt(k) };
  }
  const SPRING = {
    track: durationSpring(120),
    press: ratioSpring(311, 0.593),
    follow: ratioSpring(1024, 0.9),
    lift: durationSpring(250),
    travel: durationSpring(400, 0.15),
    jelly: ratioSpring(100, 0.4),
    settle: durationSpring(500, 0.32),
    fade: durationSpring(200),
    glowIn: durationSpring(100),
    glowOut: durationSpring(500),
  };

  class Spring {
    constructor(value = 0, rest = 1e-3) {
      this.x = value;
      this.v = 0;
      this.a = 0;
      this.target = value;
      this.spec = null;
      this.rest = rest;
    }
    to(target, spec) {
      this.target = target;
      if (reduceMotion.matches) {
        this.jump(target);
        return;
      }
      this.spec = spec;
    }
    jump(value) {
      this.x = this.target = value;
      this.v = this.a = 0;
      this.spec = null;
    }
    get moving() {
      return !!this.spec;
    }
    step(dt) {
      if (!this.spec) return false;
      const { k, c } = this.spec;
      const n = Math.max(1, Math.ceil(dt * 240));
      const h = dt / n;
      let a = 0;
      for (let i = 0; i < n; i++) {
        a = -k * (this.x - this.target) - c * this.v;
        this.v += a * h;
        this.x += this.v * h;
      }
      this.a = a;
      if (Math.abs(this.x - this.target) < this.rest && Math.abs(this.v) < this.rest * 20) {
        this.jump(this.target);
        return false;
      }
      return true;
    }
  }

  // One rAF loop drives everything that is currently moving.
  const Loop = {
    items: new Set(),
    raf: 0,
    last: 0,
    add(item) {
      this.items.add(item);
      if (!this.raf) {
        this.last = performance.now();
        this.raf = requestAnimationFrame((t) => this.frame(t));
      }
    },
    frame(t) {
      const dt = Math.min(0.064, Math.max(0.001, (t - this.last) / 1000));
      this.last = t;
      for (const item of [...this.items]) {
        let busy = false;
        try {
          busy = item.tick(dt);
        } catch (e) {
          console.debug(e);
        }
        if (!busy) this.items.delete(item);
      }
      this.raf = this.items.size ? requestAnimationFrame((n) => this.frame(n)) : 0;
    },
  };

  function rubberBand(overshoot, limit) {
    if (!limit) return 0;
    const pull = 1 - 1 / ((Math.abs(overshoot) * 0.55) / limit + 1);
    return limit * pull * Math.sign(overshoot);
  }
  const saturate = (v) => Math.tanh(v);
  const haptic = () => {
    try {
      navigator.vibrate?.(6);
    } catch {}
  };

  /* ---------- elastic press ---------- */
  // Everything pressable swells under the finger (at most 16px on its long
  // side), is pulled a little toward a dragging finger, and springs back
  // with a bounce. A quick tap still rises all the way before settling.
  const ELASTIC =
    "button:not(:disabled):not(.switch):not(.no-elastic), .card.is-link, .bot-item, .list-item, .file-pick-btn, a.link-pill";
  const MAX_GROWTH = 16;
  const PULL_LIMIT = 7 / 32;
  const LIFT_SNAP = 0.975;

  class Press {
    constructor(el) {
      this.el = el;
      this.lift = new Spring(0);
      this.px = new Spring(0);
      this.py = new Spring(0);
      this.releasing = false;
      this.pointer = null;
    }
    press(e) {
      const r = this.el.getBoundingClientRect();
      this.w = r.width || 1;
      this.h = r.height || 1;
      this.ox = e.clientX;
      this.oy = e.clientY;
      this.pointer = e.pointerId;
      this.releasing = false;
      this.lift.to(1, SPRING.press);
      this.el.classList.add("pressing");
      Loop.add(this);
    }
    drag(e) {
      if (e.pointerId !== this.pointer) return;
      const limit = Math.min(this.w, this.h) * PULL_LIMIT;
      this.px.to(rubberBand(e.clientX - this.ox, limit), SPRING.track);
      this.py.to(rubberBand(e.clientY - this.oy, limit), SPRING.track);
      Loop.add(this);
    }
    release() {
      this.pointer = null;
      this.px.to(0, SPRING.press);
      this.py.to(0, SPRING.press);
      this.releasing = true;
      Loop.add(this);
    }
    tick(dt) {
      let busy = this.lift.step(dt);
      busy = this.px.step(dt) || busy;
      busy = this.py.step(dt) || busy;
      if (this.releasing && this.lift.x >= LIFT_SNAP) {
        this.releasing = false;
        this.lift.to(0, SPRING.press);
        busy = true;
      }
      const growth = Math.min(0.25, MAX_GROWTH / Math.max(this.w, this.h));
      const swell = 1 + this.lift.x * growth;
      const sx = swell * (1 + (Math.abs(this.px.x) / this.w) * 0.5);
      const sy = swell * (1 + (Math.abs(this.py.x) / this.h) * 0.5);
      const idle = !busy && this.pointer === null && !this.releasing;
      if (idle) {
        this.el.style.transform = "";
        this.el.classList.remove("pressing");
        return false;
      }
      this.el.style.transform = `translate3d(${this.px.x.toFixed(2)}px,${this.py.x.toFixed(2)}px,0) scale(${sx.toFixed(4)},${sy.toFixed(4)})`;
      return true;
    }
  }

  const Elastic = {
    states: new WeakMap(),
    active: null,
    init() {
      const opts = { passive: true };
      document.addEventListener("pointerdown", (e) => this.down(e), opts);
      document.addEventListener("pointermove", (e) => this.active?.drag(e), opts);
      document.addEventListener("pointerup", () => this.up(), opts);
      document.addEventListener("pointercancel", () => this.up(), opts);
      window.addEventListener("blur", () => this.up());
    },
    down(e) {
      if (e.pointerType === "mouse" && e.button !== 0) return;
      const sw = e.target.closest?.(".switch");
      if (sw && !sw.disabled) Switches.hold(sw);
      const el = e.target.closest?.(ELASTIC);
      if (!el || el.closest(".dock")) return;
      let st = this.states.get(el);
      if (!st) {
        st = new Press(el);
        this.states.set(el, st);
      }
      st.press(e);
      this.active = st;
    },
    up() {
      Switches.release();
      this.active?.release();
      this.active = null;
    },
  };

  /* ---------- switches ---------- */
  // The thumb grows past the track while held and stretches mid-flip.
  const Switches = {
    held: null,
    hold(sw) {
      this.held = sw;
      sw.classList.add("held");
    },
    release() {
      this.held?.classList.remove("held");
      this.held = null;
    },
    flip(sw) {
      sw.classList.remove("flip");
      void sw.offsetWidth;
      sw.classList.add("flip");
      clearTimeout(sw._flipTimer);
      sw._flipTimer = setTimeout(() => sw.classList.remove("flip"), 340);
    },
  };

  /* ---------- liquid-glass dock ---------- */
  const BAR_HEIGHT = 62;
  const BAR_PADDING = 4;
  const MIN_LENS = 84;
  const LENS_GROWTH = 8;
  const LENS_MAGNIFY = 0.16;
  const JELLY_SPEED = 3;
  const JELLY_STRETCH = 0.2;
  const JELLY_BRAKE = 25;
  const JELLY_SQUASH = 0.15;
  const JELLY_ASPECT = 1.4;
  const OVERDRAG = 0.35;
  const LIFT_RELEASE = 0.04;
  const GLOW_REACH = 28;
  const GLOW_GROWTH = 3;
  const GLOW_PEAK = 0.06;
  const FLING_PROJECTION = 0.1;
  const TOUCH_SLOP = 8;

  function roundedRectPath(x, y, w, h) {
    const r = Math.max(0, Math.min(w, h) / 2);
    const R = x + w;
    const B = y + h;
    return `M${x + r},${y}H${R - r}A${r},${r} 0 0 1 ${R - r},${B}H${x + r}A${r},${r} 0 0 1 ${x + r},${y}Z`;
  }

  class Dock {
    constructor(host) {
      this.host = host;
      this.items = [];
      this.selected = 0;
      this.onSelect = () => {};
      this.lens = new Spring(0);
      this.lift = new Spring(0);
      this.swell = new Spring(0);
      this.stretch = new Spring(0);
      this.jelly = new Spring(0, 3e-3);
      this.glow = new Spring(0);
      this.glowSpread = new Spring(0);
      this.glowAt = { x: 0, y: 0 };
      this.pointer = null;
      this.pressed = null;
      this.dragging = false;
      this.dropping = false;
      this.samples = [];
      host.classList.add("dock");
      host.innerHTML = `<div class="dock-press"><div class="dock-bar"><div class="dock-glow"></div><div class="dock-inner"><div class="dock-platter"></div><div class="dock-lens"></div><div class="dock-row dock-out"></div><div class="dock-row dock-in" aria-hidden="true"></div></div></div></div>`;
      this.$press = host.querySelector(".dock-press");
      this.$bar = host.querySelector(".dock-bar");
      this.$glow = host.querySelector(".dock-glow");
      this.$inner = host.querySelector(".dock-inner");
      this.$platter = host.querySelector(".dock-platter");
      this.$lens = host.querySelector(".dock-lens");
      this.$out = host.querySelector(".dock-out");
      this.$in = host.querySelector(".dock-in");
      const opts = { passive: false };
      this.$bar.addEventListener("pointerdown", (e) => this.down(e), opts);
      this.$bar.addEventListener("pointermove", (e) => this.move(e), opts);
      this.$bar.addEventListener("pointerup", (e) => this.end(e, true), opts);
      this.$bar.addEventListener("pointercancel", (e) => this.end(e, false), opts);
      this.$bar.addEventListener("lostpointercapture", (e) => this.end(e, false), opts);
      this.$out.addEventListener("click", (e) => {
        // Keyboard activation; pointer taps commit in end().
        if (e.detail !== 0) return;
        const btn = e.target.closest("[data-index]");
        if (btn) this.commit(Number(btn.dataset.index));
      });
      if (window.ResizeObserver) new ResizeObserver(() => this.paint()).observe(this.$inner);
    }

    update(items, selected, onSelect) {
      const sig = items.map((x) => x.id).join("|");
      this.onSelect = onSelect;
      if (sig !== this.sig) {
        this.sig = sig;
        this.items = items;
        const cell = (x, i, inside) =>
          `<${inside ? "div" : "button"} class="dock-item" ${inside ? "" : `type="button" role="tab" data-index="${i}" aria-label="${x.label}"`}>${x.icon}<span>${x.label}</span></${inside ? "div" : "button"}>`;
        this.$out.innerHTML = items.map((x, i) => cell(x, i, false)).join("");
        this.$in.innerHTML = items.map((x, i) => cell(x, i, true)).join("");
        this.lens.jump(selected);
      }
      const prev = this.selected;
      this.selected = Math.max(0, Math.min(selected, items.length - 1));
      this.$out.querySelectorAll(".dock-item").forEach((b, i) => {
        b.setAttribute("aria-selected", String(i === this.selected));
        b.tabIndex = i === this.selected ? 0 : -1;
      });
      if (this.pressed === null && (this.lens.target !== this.selected || prev !== this.selected)) {
        this.lens.to(this.selected, SPRING.travel);
        Loop.add(this);
      }
      this.paint();
    }

    get layout() {
      const span = this.$inner.clientWidth;
      const n = Math.max(1, this.items.length);
      const pitch = (span - BAR_PADDING * 2) / n;
      if (pitch + BAR_PADDING * 2 >= MIN_LENS || n === 1) {
        return { pitch, lens: pitch + BAR_PADDING * 2, inset: BAR_PADDING, span };
      }
      const lens = Math.min(MIN_LENS, span);
      const closed = (span - lens) / (n - 1);
      return { pitch: closed, lens, inset: (lens - closed) / 2, span };
    }

    positionAt(clientX) {
      const r = this.$inner.getBoundingClientRect();
      const { pitch, inset } = this.layout;
      const last = this.items.length - 1;
      const p = (clientX - r.left - inset) / pitch - 0.5;
      if (p < 0) return rubberBand(p, OVERDRAG);
      if (p > last) return last + rubberBand(p - last, OVERDRAG);
      return p;
    }

    indexAt(p) {
      return Math.max(0, Math.min(this.items.length - 1, Math.round(p)));
    }

    down(e) {
      if (this.pointer !== null || (e.pointerType === "mouse" && e.button !== 0) || !this.items.length) return;
      this.pointer = e.pointerId;
      try {
        this.$bar.setPointerCapture(e.pointerId);
      } catch {}
      this.samples = [{ t: e.timeStamp, x: e.clientX }];
      const r = this.$bar.getBoundingClientRect();
      this.glowAt = { x: e.clientX - r.left, y: e.clientY - r.top };
      this.swell.to(1, SPRING.press);
      this.glowSpread.jump(0);
      this.glow.to(1, SPRING.glowIn);
      const index = this.indexAt(this.positionAt(e.clientX));
      this.pressed = index;
      this.pressX = e.clientX;
      this.dragging = false;
      this.dropping = false;
      this.lift.to(1, SPRING.lift);
      this.lens.to(index, SPRING.travel);
      Loop.add(this);
    }

    move(e) {
      if (e.pointerId !== this.pointer || this.pressed === null) return;
      e.preventDefault();
      this.samples.push({ t: e.timeStamp, x: e.clientX });
      if (this.samples.length > 6) this.samples.shift();
      const r = this.$bar.getBoundingClientRect();
      this.glowAt = { x: e.clientX - r.left, y: e.clientY - r.top };
      if (!this.dragging) {
        if (Math.abs(e.clientX - this.pressX) < TOUCH_SLOP) {
          Loop.add(this);
          return;
        }
        this.dragging = true;
      }
      const overshoot = e.clientX - Math.max(r.left, Math.min(e.clientX, r.right));
      this.stretch.to(rubberBand(overshoot, Math.min(r.width, r.height) * PULL_LIMIT), SPRING.track);
      const p = this.positionAt(e.clientX);
      this.lens.to(p, SPRING.follow);
      const index = this.indexAt(p);
      if (index !== this.pressed) {
        haptic();
        this.pressed = index;
      }
      Loop.add(this);
    }

    end(e, commit) {
      if (e.pointerId !== this.pointer) return;
      this.pointer = null;
      if (commit && this.dragging && this.samples.length > 1) {
        const a = this.samples[0];
        const b = this.samples[this.samples.length - 1];
        const vx = ((b.x - a.x) / Math.max(1, b.t - a.t)) * 1000;
        const lead = (vx / this.layout.pitch) * FLING_PROJECTION;
        const pressed = this.pressed;
        const index = Math.max(0, Math.min(this.items.length - 1, Math.max(pressed - 1, Math.min(pressed + 1, Math.round(this.lens.target + lead)))));
        if (index !== pressed) {
          haptic();
          this.pressed = index;
        }
      }
      const index = this.pressed;
      this.pressed = null;
      this.dragging = false;
      this.dropping = true;
      this.glow.to(0, SPRING.glowOut);
      this.glowSpread.to(1, SPRING.glowOut);
      this.stretch.to(0, SPRING.press);
      this.swell.to(0, SPRING.press);
      if (index === null) return;
      this.lens.to(commit ? index : this.selected, SPRING.travel);
      Loop.add(this);
      if (commit && index !== this.selected) this.commit(index);
    }

    commit(index) {
      this.selected = index;
      this.lens.to(index, SPRING.travel);
      Loop.add(this);
      this.onSelect(this.items[index]?.id, index);
    }

    tick(dt) {
      let busy = false;
      for (const s of [this.lens, this.lift, this.swell, this.stretch, this.glow, this.glowSpread]) busy = s.step(dt) || busy;
      // Jelly: stretch with speed, squash while braking.
      const v = this.lens.v;
      const braking = Math.max(0, -this.lens.a * Math.sign(v));
      const target = JELLY_STRETCH * saturate(Math.abs(v) / JELLY_SPEED) - JELLY_SQUASH * saturate(braking / JELLY_BRAKE);
      if (Math.abs(target - this.jelly.target) > 1e-4) this.jelly.to(target, SPRING.jelly);
      busy = this.jelly.step(dt) || busy;
      // The lens stays lifted until it has risen and arrived.
      if (this.dropping && this.pointer === null && this.lift.x >= LIFT_SNAP && Math.abs(this.lens.target - this.lens.x) <= LIFT_RELEASE) {
        this.dropping = false;
        this.lift.to(0, SPRING.lift);
        busy = true;
      }
      this.paint();
      return busy || this.pointer !== null || this.dropping;
    }

    paint() {
      if (!this.items.length || !this.$inner.isConnected) return;
      const { pitch, lens, inset, span } = this.layout;
      const H = this.$inner.clientHeight || BAR_HEIGHT - BAR_PADDING * 2;
      const lift = Math.max(0, Math.min(1, this.lift.x));
      const jelly = this.jelly.x;
      const growth = LENS_GROWTH * 2 * lift;
      const w = (lens + growth) * (1 + jelly);
      const h = (H + growth) * (1 - jelly * JELLY_ASPECT);
      const cx = inset + (this.lens.x + 0.5) * pitch;
      const x = cx - w / 2;
      const y = (H - h) / 2;
      const box = `translate3d(${x.toFixed(2)}px,${y.toFixed(2)}px,0)`;
      for (const el of [this.$platter, this.$lens]) {
        el.style.width = `${w.toFixed(2)}px`;
        el.style.height = `${h.toFixed(2)}px`;
        el.style.transform = box;
      }
      this.$platter.style.opacity = String(1 - lift);
      this.$lens.style.opacity = String(lift);
      // What lies under the lens is tinted and magnified; the rest is not.
      const reach = { x: x + BAR_PADDING, y, w: Math.max(0, w - BAR_PADDING * 2), h };
      const lensPath = roundedRectPath(reach.x, reach.y, reach.w, reach.h);
      this.$in.style.clipPath = `path("${lensPath}")`;
      this.$out.style.clipPath = `path(evenodd, "M-40,-40H${span + 40}V${H + 40}H-40Z ${lensPath}")`;
      const mag = 1 + LENS_MAGNIFY * lift;
      this.$in.querySelectorAll(".dock-item").forEach((el) => {
        el.style.transform = mag === 1 ? "" : `scale(${mag.toFixed(4)})`;
      });
      // The bar swells under the finger and stretches past its ends.
      const bw = this.$bar.clientWidth || 1;
      const swell = 1 + this.swell.x * Math.min(0.25, MAX_GROWTH / bw);
      const sx = swell * (1 + (Math.abs(this.stretch.x) / bw) * 0.5);
      this.$press.style.transform =
        this.swell.x || this.stretch.x ? `translate3d(${this.stretch.x.toFixed(2)}px,0,0) scale(${sx.toFixed(4)},${swell.toFixed(4)})` : "";
      // Light from the finger that spreads as it fades.
      const g = this.glow.x;
      if (g > 0.002) {
        const radius = GLOW_REACH * (1 + GLOW_GROWTH * this.glowSpread.x);
        const s = GLOW_PEAK * g * g * (document.documentElement.dataset.theme === "dark" ? 2 : 4);
        this.$glow.style.opacity = "1";
        this.$glow.style.background = `radial-gradient(circle ${radius.toFixed(1)}px at ${this.glowAt.x.toFixed(1)}px ${this.glowAt.y.toFixed(1)}px, rgba(255,255,255,${s.toFixed(3)}), rgba(255,255,255,${(s * 0.25).toFixed(3)}) 100%)`;
      } else {
        this.$glow.style.opacity = "0";
      }
    }
  }

  /* ---------- page transitions ---------- */
  function pageTransition(el, kind) {
    if (!el || reduceMotion.matches) return;
    el.classList.remove("page-push", "page-pop", "page-fade");
    void el.offsetWidth;
    el.classList.add(kind === "push" ? "page-push" : kind === "pop" ? "page-pop" : "page-fade");
    clearTimeout(el._pageTimer);
    el._pageTimer = setTimeout(() => el.classList.remove("page-push", "page-pop", "page-fade"), 700);
  }

  Elastic.init();
  window.NailongMotion = { Spring, SPRING, Loop, Dock, Switches, pageTransition, rubberBand };
})();
