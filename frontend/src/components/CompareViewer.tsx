import { useRef, useState } from "react";
import { TransformComponent, TransformWrapper, type ReactZoomPanPinchRef } from "react-zoom-pan-pinch";

export interface CompareSide {
  src: string;
  label: string;
}

const tab = (on: boolean) => `rounded-md px-2 py-1 ${on ? "bg-indigo-600 text-white" : "bg-slate-100 text-slate-700"}`;

export function CompareViewer({ left, right }: { left: CompareSide; right: CompareSide }) {
  const [mode, setMode] = useState<"slider" | "side">("slider");
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-3">
      <div className="mb-2 flex flex-wrap items-center gap-2 text-sm">
        <span className="text-slate-500">对比：</span>
        <button type="button" aria-pressed={mode === "slider"} className={tab(mode === "slider")} onClick={() => setMode("slider")}>
          滑块
        </button>
        <button type="button" aria-pressed={mode === "side"} className={tab(mode === "side")} onClick={() => setMode("side")}>
          并排（同步缩放）
        </button>
      </div>
      {mode === "slider" ? <SliderCompare left={left} right={right} /> : <SideBySide left={left} right={right} />}
    </div>
  );
}

function SliderCompare({ left, right }: { left: CompareSide; right: CompareSide }) {
  const [pos, setPos] = useState(50);
  return (
    <div>
      <div className="relative overflow-hidden rounded-lg bg-slate-50">
        <img src={right.src} alt={right.label} className="block w-full" />
        <img
          src={left.src}
          alt={left.label}
          className="absolute inset-0 h-full w-full object-contain"
          style={{ clipPath: `inset(0 ${100 - pos}% 0 0)` }}
        />
        <div className="pointer-events-none absolute inset-y-0 w-0.5 bg-indigo-500" style={{ left: `${pos}%` }} />
        <span className="absolute left-2 top-2 rounded bg-black/60 px-1.5 text-xs text-white">{left.label}</span>
        <span className="absolute right-2 top-2 rounded bg-black/60 px-1.5 text-xs text-white">{right.label}</span>
      </div>
      <input
        type="range"
        min={0}
        max={100}
        value={pos}
        aria-label="对比位置"
        className="mt-2 w-full"
        onChange={(e) => setPos(Number(e.target.value))}
      />
    </div>
  );
}

function SideBySide({ left, right }: { left: CompareSide; right: CompareSide }) {
  const leftRef = useRef<ReactZoomPanPinchRef>(null);
  const rightRef = useRef<ReactZoomPanPinchRef>(null);
  const syncing = useRef(false);
  const follow = (other: typeof leftRef) => (source: ReactZoomPanPinchRef) => {
    if (syncing.current || !other.current) return;
    const { positionX, positionY, scale } = source.state;
    syncing.current = true;
    other.current.setTransform(positionX, positionY, scale, 0);
    syncing.current = false;
  };
  const sides = [
    { side: left, ref: leftRef, onTransformed: follow(rightRef) },
    { side: right, ref: rightRef, onTransformed: follow(leftRef) },
  ];
  return (
    <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
      {sides.map(({ side, ref, onTransformed }) => (
        <figure key={side.label} className="overflow-hidden rounded-lg border border-slate-200 bg-slate-50">
          <TransformWrapper ref={ref} onTransformed={onTransformed} maxScale={8}>
            <TransformComponent wrapperClass="!w-full" contentClass="!w-full">
              <img src={side.src} alt={side.label} className="block w-full" />
            </TransformComponent>
          </TransformWrapper>
          <figcaption className="px-2 py-1 text-xs text-slate-600">{side.label}</figcaption>
        </figure>
      ))}
    </div>
  );
}
