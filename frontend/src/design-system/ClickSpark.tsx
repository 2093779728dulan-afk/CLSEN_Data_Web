import { createPortal } from "react-dom";
import { useCallback, useEffect, useRef, type MouseEvent, type ReactNode } from "react";
import styles from "./ClickSpark.module.css";

type Spark = { x: number; y: number; angle: number; startTime: number; color: string };

/** React Bits ClickSpark's radial canvas strokes, adapted to a shared action boundary. */
export function ClickSpark({ children }: { children: ReactNode }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const sparks = useRef<Spark[]>([]);
  const frame = useRef<number | undefined>(undefined);
  const enabled = useRef(false);
  const palette = useRef<string[]>([]);

  const clear = useCallback(() => {
    if (frame.current !== undefined) cancelAnimationFrame(frame.current);
    frame.current = undefined;
    sparks.current = [];
    const canvas = canvasRef.current;
    canvas?.getContext("2d")?.clearRect(0, 0, canvas.width, canvas.height);
  }, []);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || typeof window.matchMedia !== "function") return;
    const preference = window.matchMedia("(prefers-reduced-motion: reduce)");
    const colors = window.matchMedia("(forced-colors: active)");
    const syncPreference = () => { enabled.current = !preference.matches && !colors.matches; clear(); };
    const resize = () => {
      clear();
      const scale = Math.min(window.devicePixelRatio || 1, 2);
      canvas.width = Math.round(window.innerWidth * scale);
      canvas.height = Math.round(window.innerHeight * scale);
      canvas.getContext("2d")?.setTransform(scale, 0, 0, scale, 0, 0);
    };
    const tokens = getComputedStyle(document.documentElement);
    palette.current = [1, 2, 3, 4].map(i => tokens.getPropertyValue(`--spark-color-${i}`).trim());
    syncPreference(); resize();
    preference.addEventListener("change", syncPreference);
    colors.addEventListener("change", syncPreference);
    window.addEventListener("resize", resize);
    // A spark belongs to the clicked control, not the content subsequently scrolled into view.
    window.addEventListener("scroll", clear, true);
    return () => {
      clear(); preference.removeEventListener("change", syncPreference);
      colors.removeEventListener("change", syncPreference);
      window.removeEventListener("resize", resize); window.removeEventListener("scroll", clear, true);
    };
  }, [clear]);

  const draw = useCallback(function drawFrame(timestamp: number) {
    const canvas = canvasRef.current;
    const ctx = canvas?.getContext("2d");
    if (!canvas || !ctx) { frame.current = undefined; return; }
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    sparks.current = sparks.current.filter(spark => {
      const elapsed = timestamp - spark.startTime;
      if (elapsed >= 400) return false;
      const progress = Math.max(0, elapsed / 400);
      const eased = progress * (2 - progress); // Upstream ease-out.
      const distance = eased * 18;
      const lineLength = 7 * (1 - eased);
      ctx.strokeStyle = spark.color; ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.moveTo(spark.x + distance * Math.cos(spark.angle), spark.y + distance * Math.sin(spark.angle));
      ctx.lineTo(spark.x + (distance + lineLength) * Math.cos(spark.angle), spark.y + (distance + lineLength) * Math.sin(spark.angle));
      ctx.stroke();
      return true;
    });
    frame.current = sparks.current.length ? requestAnimationFrame(drawFrame) : undefined;
  }, []);

  const click = (event: MouseEvent<HTMLDivElement>) => {
    if (!enabled.current || !(event.target instanceof Element)) return;
    const control = event.target.closest<HTMLElement>("button, a[href], [role='button']");
    if (!control || control.matches(":disabled, [aria-disabled='true'], [aria-busy='true'], [data-click-spark='off']") || !canvasRef.current?.getContext("2d")) return;
    const bounds = control.getBoundingClientRect();
    const x = event.detail === 0 ? bounds.left + bounds.width / 2 : event.clientX;
    const y = event.detail === 0 ? bounds.top + bounds.height / 2 : event.clientY;
    const now = performance.now();
    const burst = Array.from({ length: 8 }, (_, i) => ({ x, y, angle: 2 * Math.PI * i / 8, startTime: now, color: palette.current[i % 4]! }));
    // Keep only recent bursts during rapid clicks; no idle animation loop.
    sparks.current = [...sparks.current.slice(-56), ...burst];
    if (frame.current === undefined) frame.current = requestAnimationFrame(draw);
  };

  return <div className={styles.boundary} onClickCapture={click}>
    {children}
    {createPortal(<canvas aria-hidden="true" className={styles.canvas} ref={canvasRef} />, document.body)}
  </div>;
}
